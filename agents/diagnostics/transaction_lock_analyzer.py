
"""Deterministic, read-only analysis of PostgreSQL transaction and lock evidence."""
from __future__ import annotations

from datetime import timedelta
from typing import Any


def _seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parts = text.split(":")
            if len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            return float(text)
        except ValueError:
            return None
    return None


def _age(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in row:
            value = _seconds(row.get(key))
            if value is not None:
                return value
    return None


def _item(pid: Any, age: float | None, state: Any, username: Any, application: Any) -> dict[str, Any]:
    return {
        "pid": pid,
        "age_seconds": round(age, 2) if age is not None else None,
        "state": state,
        "username": username,
        "application_name": application,
    }


def analyze_transaction_locks(
    report: dict[str, Any],
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Analyze collected toolkit evidence; never performs database actions."""
    limits = {
        "long_transaction_seconds": 300.0,
        "long_query_seconds": 60.0,
        "idle_in_transaction_seconds": 60.0,
    }
    if thresholds:
        for key, value in thresholds.items():
            if key in limits and isinstance(value, (int, float)) and value >= 0:
                limits[key] = float(value)

    sections = ("transactions", "connection_details", "blocking")
    missing = [name for name in sections if name not in report]
    if len(missing) == len(sections):
        return {
            "status": "INSUFFICIENT_DATA",
            "missing_evidence": list(sections),
            "blocking_count": 0,
            "long_transactions": [],
            "idle_in_transaction": [],
            "long_running_queries": [],
            "blocking_relationships": [],
            "recommendations": ["Collect transactions, connection_details, and blocking diagnostics before assessing transaction and lock health."],
            "safety": "Analysis only; no sessions were cancelled or terminated.",
        }

    transactions = report.get("transactions")
    details = report.get("connection_details")
    blocking = report.get("blocking")
    for name, value in (("transactions", transactions), ("connection_details", details), ("blocking", blocking)):
        if isinstance(value, dict) and value.get("error"):
            missing.append(name + ": " + str(value.get("error")))

    long_transactions = []
    if isinstance(transactions, list):
        for row in transactions:
            age = _age(row, "transaction_age")
            if age is not None and age >= limits["long_transaction_seconds"]:
                long_transactions.append(_item(row.get("pid"), age, row.get("state"), row.get("username"), row.get("application_name")))

    idle_in_transaction = []
    long_queries = []
    if isinstance(details, list):
        for row in details:
            state = str(row.get("state") or "").lower()
            xact_age = _age(row, "transaction_age")
            query_age = _age(row, "query_age")
            item = _item(row.get("pid"), xact_age, row.get("state"), row.get("username"), row.get("application_name"))
            if state.startswith("idle in transaction") and xact_age is not None and xact_age >= limits["idle_in_transaction_seconds"]:
                idle_in_transaction.append(item)
            if state == "active" and query_age is not None and query_age >= limits["long_query_seconds"]:
                query_item = _item(row.get("pid"), query_age, row.get("state"), row.get("username"), row.get("application_name"))
                query_item["transaction_age_seconds"] = round(xact_age, 2) if xact_age is not None else None
                long_queries.append(query_item)

    relationships = []
    seen = set()
    if isinstance(blocking, list):
        for row in blocking:
            pair = (row.get("blocked_pid"), row.get("blocker_pid"))
            if pair in seen:
                continue
            seen.add(pair)
            relationships.append({
                "blocked_pid": pair[0],
                "blocker_pid": pair[1],
                "blocked_query_age_seconds": round(_age(row, "blocked_query_age"), 2) if _age(row, "blocked_query_age") is not None else None,
                "blocked_transaction_age_seconds": round(_age(row, "blocked_transaction_age"), 2) if _age(row, "blocked_transaction_age") is not None else None,
                "blocker_transaction_age_seconds": round(_age(row, "blocker_transaction_age"), 2) if _age(row, "blocker_transaction_age") is not None else None,
                "blocker_state": row.get("blocker_state"),
                "blocked_wait_event": row.get("wait_event"),
                "blocked_wait_event_type": row.get("wait_event_type"),
                "blocker_upstream_pids": row.get("blocker_upstream_pids"),
            })

    if relationships:
        severity = "CRITICAL" if any((x["blocked_query_age_seconds"] or 0) >= limits["long_query_seconds"] for x in relationships) else "HIGH"
    elif idle_in_transaction or long_transactions:
        severity = "HIGH" if idle_in_transaction else "WATCH"
    elif long_queries:
        severity = "WATCH"
    else:
        severity = "NORMAL"

    recommendations = []
    if relationships:
        recommendations.append("Inspect the blocked and blocker sessions, application transaction boundaries, and lock-wait context; identify the root blocker before considering any intervention.")
    if idle_in_transaction:
        recommendations.append("Contact the owning application or user to resolve idle-in-transaction sessions; check transaction age and held locks before taking action.")
    if long_transactions:
        recommendations.append("Review long transaction ownership and workload intent; long transactions can retain snapshots and delay cleanup.")
    if long_queries:
        recommendations.append("Review the actual SQL and execution plan for long-running active queries; query age alone does not establish the cause.")
    if not recommendations:
        recommendations.append("No transaction or lock remediation is indicated by the collected evidence.")

    return {
        "status": "ANALYZED",
        "severity": severity,
        "thresholds_seconds": limits,
        "blocking_count": len(relationships),
        "long_transactions": long_transactions,
        "idle_in_transaction": idle_in_transaction,
        "long_running_queries": long_queries,
        "blocking_relationships": relationships,
        "missing_evidence": missing,
        "recommendations": recommendations,
        "safety": "Read-only analysis. Never automatically cancel or terminate sessions; validate ownership, impact, and approval before intervention.",
    }
