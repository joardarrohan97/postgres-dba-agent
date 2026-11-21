
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

ROOT = Path(__file__).resolve().parents[1]

# Reuse the existing v2.1 toolkit without modifying it.
sys.path.insert(
    0,
    str(ROOT / "tools" / "postgres_dba_toolkit_v2")
)

from agents.execution_broker import run_diagnostic
from agents.sql_validation.interface import validate_proposal
from agents.quality.claim_checker import validate_report
from agents.quality.evidence_validator import validate_evidence
from agents.diagnostics.connection_pressure import analyze_connection_pressure
from agents.diagnostics.transaction_lock_analyzer import analyze_transaction_locks
from agents.diagnostics.incident_correlator import correlate_incident

from knowledge_ingestion.embeddings.rag_answer import (
    retrieve_documents,
    ollama_request,
)

CHAT_MODEL = "qwen3.5:4b"
TOP_K = 5


def choose_diagnostic(question):
    """Deterministic diagnostic selection; no generated SQL."""

    q = question.lower()

    if any(word in q for word in (
        "slow query", "query slow", "performance",
        "high cpu", "slowdown", "latency"
    )):
        return "all"

    if any(word in q for word in (
        "blocking", "blocked", "lock contention",
        "deadlock", "waiting for lock"
    )):
        return "blocking"

    if any(word in q for word in (
        "replication", "replica", "standby",
        "replication lag", "wal receiver"
    )):
        return "replication"

    if any(word in q for word in (
        "index", "unused index", "index scan"
    )):
        return "indexes"

    if any(word in q for word in (
        "bloat", "vacuum", "dead tuples",
        "table size", "table statistics"
    )):
        return "tables"

    if any(word in q for word in (
        "connection", "connections", "too many connections"
    )):
        return "connections"

    if any(word in q for word in (
        "transaction", "long running transaction",
        "idle in transaction"
    )):
        return "transactions"

    if any(word in q for word in (
        "configuration", "config", "postgres settings"
    )):
        return "config"

    if any(word in q for word in (
        "statement statistics", "top queries",
        "query statistics"
    )):
        return "statements"

    return "health"


def compact_report(value):
    """Limit diagnostic output before sending it to the LLM."""

    if isinstance(value, dict):
        return {
            key: compact_report(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [compact_report(item) for item in value[:10]]

    if isinstance(value, str):
        return value[:500]

    return value


def _diagnostic_status(report, section):
    value = report.get(section)
    if section not in report:
        return {"status": "NOT_COLLECTED", "row_count": None}
    if isinstance(value, list):
        count = len(value)
        return {"status": "QUERY_SUCCEEDED_WITH_ROWS" if count else "QUERY_SUCCEEDED_EMPTY", "row_count": count}
    if isinstance(value, dict) and value.get("error") is not None:
        error = str(value["error"])
        lowered = error.lower()
        denied = "42501" in lowered or any(term in lowered for term in ("permission denied", "insufficient privilege", "not authorized"))
        return {"status": "QUERY_FAILED", "failure_type": "PERMISSION_DENIED" if denied else "OTHER_ERROR", "error": error[:300], "row_count": None}
    return {"status": "NOT_COLLECTED", "row_count": None}

def _humanize_setting(setting, unit):
    factors = {"b": 1, "kb": 1024, "8kb": 8192, "mb": 1048576, "gb": 1073741824}
    factor = factors.get(str(unit or "").lower())
    try:
        if factor is not None:
            total = float(setting) * factor
            for size, label in ((1099511627776, "TiB"), (1073741824, "GiB"), (1048576, "MiB"), (1024, "KiB")):
                if total >= size:
                    amount = total / size
                    return f"{amount:g} {label}"
            return f"{total:g} B"
    except (TypeError, ValueError):
        pass
    return f"{setting} {unit}".strip()

def _configuration_evidence(report):
    status = _diagnostic_status(report, "config")
    rows = report.get("config") if isinstance(report.get("config"), list) else []
    settings = [{"name": row.get("name"), "raw_setting": row.get("setting"), "unit": row.get("unit"), "interpreted_value": _humanize_setting(row.get("setting"), row.get("unit"))} for row in rows if isinstance(row, dict)]
    return {"diagnostic": status, "settings": settings}

def build_monitoring_access_summary(report):
    activity_sections = ("connections", "connection_details", "transactions", "blocking")
    activity = {name: _diagnostic_status(report, name) for name in activity_sections}
    def combined(items):
        statuses = [item["status"] for item in items.values()]
        if any(status == "QUERY_SUCCEEDED_WITH_ROWS" for status in statuses):
            return "QUERY_SUCCEEDED_WITH_ROWS"
        if any(status == "QUERY_SUCCEEDED_EMPTY" for status in statuses):
            return "QUERY_SUCCEEDED_EMPTY"
        if any(status == "QUERY_FAILED" for status in statuses):
            return "QUERY_FAILED"
        return "NOT_COLLECTED"
    permissions = report.get("permissions")
    membership = {}
    if isinstance(permissions, list) and permissions and isinstance(permissions[0], dict):
        membership = {name: permissions[0].get(field) for name, field in (("pg_monitor", "has_pg_monitor"), ("pg_read_all_stats", "has_pg_read_all_stats"))}
    tables = _diagnostic_status(report, "tables")
    database = _diagnostic_status(report, "database_stats")
    return {"role_membership": membership, "view_access": {"pg_stat_activity": {"status": combined(activity), "diagnostics": activity}, "pg_stat_user_tables": tables, "pg_stat_database": database}, "configuration": _configuration_evidence(report), "interpretation": "NOT_COLLECTED means no result was supplied and is not evidence of query failure or permission denial. QUERY_SUCCEEDED_EMPTY means the query ran successfully and returned zero rows. QUERY_SUCCEEDED_WITH_ROWS means it ran and returned data. QUERY_FAILED includes a failure_type; only PERMISSION_DENIED establishes a permission error for that diagnostic. Role membership alone does not prove view inaccessibility."}
POSTGRESQL_SAFETY_RULES = """
MANDATORY POSTGRESQL DBA RULES:

1. Never invent query execution metrics, execution plans,
   permission failures, or root causes.

2. Distinguish OBSERVED, HYPOTHESIS, and UNCONFIRMED.

3. pg_monitor and pg_read_all_stats are predefined roles,
   not extensions.

4. Missing pg_monitor membership does not imply that all
   PostgreSQL statistics views are inaccessible.

5. Ordinary EXPLAIN does not inherently require superuser.
   EXPLAIN ANALYZE executes the underlying statement.

6. Never recommend granting superuser privileges to a
   monitoring account.

7. Never recommend CREATE EXTENSION, GRANT, ALTER SYSTEM,
   CREATE INDEX, VACUUM FULL, or REINDEX as an automatic action.

8. Do not label missing indexes, WAL settings, or I/O
   bottlenecks as LIKELY without supporting evidence.

9. If query-specific evidence is missing, explicitly state
   that the root cause cannot yet be determined.

10. All remediation proposals must include operational risk
    and required approval.

11. Documentation describes general PostgreSQL behavior;
    it is not evidence that a condition exists in this database.

12. Never execute generated SQL. Use only approved,
    deterministic diagnostic tools.
  13. pg_monitor and pg_read_all_stats are predefined PostgreSQL roles, never extensions.
  14. Never claim superuser is generally required for EXPLAIN or EXPLAIN ANALYZE. Permissions depend on the query and referenced objects.
  15. EXPLAIN ANALYZE executes the underlying statement. Warn about execution cost and possible side effects.
  16. Explain that pg_monitor and pg_read_all_stats membership is cluster-wide, not database-scoped.
  17. Never recommend changing track_activities through ALTER SYSTEM or restarting PostgreSQL to enable it.
  18. Never infer index availability, usage, or missing indexes from database size.
  19. Use only actual permission evidence in the diagnostic report.
  20. If the actual slow SQL or execution plan is unavailable, state that the root cause cannot be determined.
  21. Never recommend superuser access as a workaround for diagnostic visibility.
  22. Treat connection_pressure_analysis as deterministic evidence. Do not override its utilization or classification with guesses. Do not recommend increasing max_connections or terminating sessions unless the collected evidence supports the action.
  23. Treat connection_pressure_analysis and transaction_lock_analysis as authoritative deterministic results.
  24. Treat incident_correlation as the authoritative unified incident assessment. Do not invent incidents, alter severity, or claim root cause beyond its evidence. Never contradict their severity, classification, counts, missing_evidence, or recommendations. If either analyzer reports INSUFFICIENT_DATA, explicitly state that the assessment cannot be completed from available evidence.
"""


def build_prompt(question, documents, report, section):
    sources = []

    for index, doc in enumerate(documents, start=1):
        sources.append(
            f"""
SOURCE {index}
Topic: {doc.get("topic")}
URL: {doc.get("source_url")}
Similarity: {doc.get("similarity")}
Documentation:
{doc.get("content", "")[:1500]}
"""
        )

    documentation = "\n".join(sources)

    live_evidence = json.dumps(
        compact_report(report),
        indent=2,
        default=str
    )

    monitoring_evidence = json.dumps(build_monitoring_access_summary(report), indent=2)

    system_prompt = """
You are an evidence-driven PostgreSQL DBA incident analysis agent.

You receive:
1. A user's DBA question.
2. Retrieved official PostgreSQL documentation.
3. Live diagnostic evidence collected by the existing DBA toolkit.

STRICT RULES:

- Treat live diagnostic results as evidence about the lab database.
- Never invent database metrics, query results or configuration values.
- Distinguish observed facts from hypotheses and recommendations.
- A missing result or permission error is not proof that a problem
  does not exist.
- Do not recommend changes without explaining their risks.
- Do not execute SQL or modify the database.
- Do not claim that a remediation has been performed.
- Use documentation sources to support technical explanations.
- Do not assume every sequential scan is a performance problem.
- Do not assume WAL configuration is responsible without evidence.
- If evidence is insufficient, explain what additional information
  is needed.
- Treat the MONITORING ACCESS EVIDENCE block as authoritative for the
  status of the tested diagnostic views.
- Never infer view inaccessibility from missing pg_monitor or
  pg_read_all_stats membership.
- A successful diagnostic query proves access for that query, even
  when it returns zero rows. Do not claim that view is inaccessible.
- Recommend a role grant only when a required capability has an
  actual PERMISSION_DENIED result and the grant is justified.

Respond using:

1. Incident summary
2. Observed database evidence
3. Potential root causes, ranked by evidence
4. Recommended diagnostic steps
5. Suggested remediation, with risks
6. Documentation sources

Clearly label each conclusion as OBSERVED, LIKELY, or UNCONFIRMED.
"""

    system_prompt = system_prompt + "\n\n" + POSTGRESQL_SAFETY_RULES

    user_prompt = f"""
USER QUESTION:
{question}

DIAGNOSTIC SECTION:
{section}

LIVE POSTGRESQL DIAGNOSTIC REPORT:
{live_evidence}

MONITORING ACCESS EVIDENCE (DETERMINISTIC):
{monitoring_evidence}

RETRIEVED POSTGRESQL DOCUMENTATION:
{documentation}

Analyze the question using both the live evidence and documentation.
If they do not establish a root cause, do not invent one.
"""


    return system_prompt, user_prompt


def validate_sql_proposal(sql):
    """Validate proposed SQL without executing it."""
    return validate_proposal(sql)


def run_diagnostic_bundle(section, dsn):
    if section == "connections":
        names = ["connections", "transactions", "blocking", "config"]
    elif section in ("transactions", "blocking"):
        names = ["transactions", "connections", "blocking", "config"]
    else:
        names = [section]
    merged = {}
    findings = []
    metadata = {}
    for name in names:
        result = run_diagnostic(name, dsn)
        if result.get("status") != "COMPLETED":
            return result
        part = result["report"]
        metadata = metadata or part.get("metadata", {})
        for key, value in part.items():
            if key in ("metadata", "findings"):
                continue
            if isinstance(value, list):
                merged.setdefault(key, [])
                merged[key].extend(value)
            else:
                merged[key] = value
        findings.extend(part.get("findings", []))
    for key, value in merged.items():
        if isinstance(value, list):
            seen = set()
            unique = []
            for item in value:
                marker = json.dumps(item, sort_keys=True, default=str)
                if marker not in seen:
                    seen.add(marker)
                    unique.append(item)
            merged[key] = unique
    seen = set()
    merged_findings = []
    for item in findings:
        marker = json.dumps(item, sort_keys=True, default=str)
        if marker not in seen:
            seen.add(marker)
            merged_findings.append(item)
    merged["metadata"] = metadata
    merged["findings"] = merged_findings
    return {"status": "COMPLETED", "diagnostic": names, "read_only": True, "report": merged}


def run_orchestrator(question):
    dsn = os.getenv("DBA_AGENT_DSN")

    if not dsn:
        raise RuntimeError(
            "DBA_AGENT_DSN is not configured."
        )

    print("\n[1/4] Selecting diagnostic checks...")
    section = choose_diagnostic(question)
    print(f"Selected diagnostic section: {section}")

    print("\n[2/4] Retrieving PostgreSQL documentation...")
    documents = retrieve_documents(question)
    print(f"Retrieved passages: {len(documents)}")

    print("\n[3/4] Collecting live PostgreSQL evidence...")

    broker_result = run_diagnostic_bundle(section, dsn)
    if broker_result.get("status") != "COMPLETED":
        raise RuntimeError("Diagnostic broker blocked or failed: " + broker_result.get("status", "UNKNOWN"))
    report = broker_result["report"]
    connection_pressure = analyze_connection_pressure(report)
    transaction_lock_analysis = analyze_transaction_locks(report)
    incident_correlation = correlate_incident(connection_pressure, transaction_lock_analysis)
    analysis_report = dict(report)
    analysis_report["connection_pressure_analysis"] = connection_pressure
    analysis_report["transaction_lock_analysis"] = transaction_lock_analysis
    analysis_report["incident_correlation"] = incident_correlation

    print("Diagnostic collection completed through execution broker.")
    print("Connection pressure:", connection_pressure.get("classification", connection_pressure.get("status")))
    print("Transaction/lock analysis:", transaction_lock_analysis.get("severity", transaction_lock_analysis.get("status")))
    print("Unified incident assessment:", incident_correlation.get("severity", incident_correlation.get("status")))
    print("Toolkit version:", report["metadata"]["toolkit_version"])

    print("\n[4/4] Asking Qwen to analyze the evidence...")

    system_prompt, user_prompt = build_prompt(
        question,
        documents,
        analysis_report,
        section
    )

    result = ollama_request(
       "/api/chat",
    {
        "model": CHAT_MODEL,
        "think": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_ctx": 8192,
            "num_predict": 1800
        }
    }
)

    answer = result["message"]["content"]
    quality_review = validate_report(answer)
    if quality_review["findings"]:
        answer += "\\n\\nQUALITY REVIEW — HUMAN REVIEW REQUIRED\\n"
        for finding in quality_review["findings"]:
            answer += "- {} ({}): {}\\n".format(finding["rule_id"], finding["severity"], finding["message"])
    elif not quality_review["passed"]:
        answer += "\\n\\nQUALITY REVIEW: Invalid report input; manual review required.\\n"
    evidence_review = validate_evidence(report, answer)
    if evidence_review["findings"]:
        answer += "\n\nEVIDENCE REVIEW — HUMAN REVIEW REQUIRED\n"
        for finding in evidence_review["findings"]:
            answer += "- {} ({}): {}\n".format(finding["rule_id"], finding["severity"], finding["message"])
    if evidence_review["unverified"]:
        answer += "\n\nEVIDENCE NOT COLLECTED — MANUAL VERIFICATION REQUIRED\n"
        for item in evidence_review["unverified"]:
            answer += "- {}\n".format(item)
    answer += chr(10) + chr(10) + "DETERMINISTIC ASSESSMENT — AUTHORITATIVE" + chr(10)
    answer += json.dumps({"connection_pressure": connection_pressure, "transaction_lock": transaction_lock_analysis, "incident_correlation": incident_correlation}, indent=2, default=str)
    print("\nDEBUG: Ollama response keys:", result.keys())
    print("DEBUG: Ollama message:", result.get("message"))
    print("DEBUG: Done:", result.get("done"))
    print("DEBUG: Done reason:", result.get("done_reason"))

    print("\n" + "=" * 60)
    print("POSTGRESQL DBA INCIDENT ANALYSIS")
    print("=" * 60)
    print(answer)

    print("\n" + "=" * 60)
    print("DIAGNOSTIC METADATA")
    print("=" * 60)
    print(json.dumps(report["metadata"], indent=2, default=str))

    print("\nRetrieved documentation sources:")
    for doc in documents:
        print(
            f"- {doc.get('topic')} | "
            f"{doc.get('source_url')}"
        )



    return {
        "question": question,
        "diagnostic": section,
        "answer": answer,
        "read_only": True,
        "metrics": {
            "connection_pressure": connection_pressure,
            "transaction_lock": transaction_lock_analysis,
            "incident_correlation": incident_correlation,
        },
        "evidence": report,
        "report_metadata": report["metadata"],
        "sources": [
            {
                "topic": doc.get("topic"),
                "source_url": doc.get("source_url"),
            }
            for doc in documents
        ],
        "quality_review": quality_review,
        "evidence_review": evidence_review,
    }

def main():
    if len(sys.argv) < 2:
        print(
            'Usage: python agents/orchestrator.py '
            '"Your PostgreSQL DBA question"'
        )
        sys.exit(1)

    question = " ".join(sys.argv[1:])

    try:
        run_orchestrator(question)
    except Exception as error:
        print(f"\nOrchestrator error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()