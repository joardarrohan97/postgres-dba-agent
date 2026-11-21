from __future__ import annotations

from typing import Any

import psycopg

from .analysis import analyze_plan, build_findings
from .queries import QUERIES, SECTION_MAP


def _fetch(conn: psycopg.Connection, sql: str) -> list[dict[str, Any]]:
    return conn.execute(sql).fetchall()


def collect_report(conn: psycopg.Connection, command: str, *, long_txn_seconds: int = 300,
                   dead_tuple_pct: float = 20.0, dead_tuple_min: int = 100) -> dict[str, Any]:
    if command not in SECTION_MAP:
        raise ValueError(f"Unsupported diagnostic section: {command}")
    report: dict[str, Any] = {"metadata": {"toolkit_version": "2.1.0", "read_only": True}}
    for index, section in enumerate(SECTION_MAP[command]):
        savepoint = f"dba_v2_section_{index}"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            report[section] = _fetch(conn, QUERIES[section])
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except psycopg.Error as exc:
            # A failed statement aborts the current transaction until rolled back to its savepoint.
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            report[section] = {"error": str(exc).splitlines()[0], "optional_or_permission_limited": section in {"statements", "replication_slots"}}
    report["findings"] = build_findings(report, long_txn_seconds, dead_tuple_pct, dead_tuple_min)
    return report


def run_explain(conn: psycopg.Connection, sql: str, *, analyze: bool = False) -> dict[str, Any]:
    statement = sql.strip()
    if not statement:
        raise ValueError("SQL is empty")
    # Enforce a single read query at the CLI boundary. PostgreSQL read-only tx is the second guard.
    cleaned = statement.lstrip()
    if not (cleaned[:6].upper() == "SELECT" or cleaned[:4].upper() == "WITH"):
        raise ValueError("Only SELECT or WITH statements are accepted by the plan analyzer")
    if ";" in cleaned.rstrip(";"):
        raise ValueError("Multiple SQL statements are not accepted")
    options = "FORMAT JSON, VERBOSE, COSTS, SETTINGS"
    if analyze:
        options += ", ANALYZE, BUFFERS, WAL, TIMING"
    # The connection is in a READ ONLY transaction; ANALYZE still executes SELECT and can call functions.
    result = conn.execute(f"EXPLAIN ({options}) {statement}").fetchone()
    doc = result["QUERY PLAN"] if "QUERY PLAN" in result else next(iter(result.values()))
    return {"analyze_executed": analyze, "plan": doc, "analysis": analyze_plan(doc),
            "safety_note": "EXPLAIN ANALYZE executes the statement. Use only trusted SELECTs; read-only transactions do not prevent external side effects in user-defined functions."}
