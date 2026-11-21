#!/usr/bin/env python3
"""Read-only PostgreSQL DBA diagnostics CLI.

All database inspection runs inside a READ ONLY transaction. This tool never
executes DDL/DML, VACUUM, ANALYZE, EXPLAIN ANALYZE, or configuration changes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

import psycopg
from psycopg.rows import dict_row


QUERIES: dict[str, str] = {
    "health": """
        SELECT
            current_database() AS database_name,
            current_user AS connected_user,
            current_setting('server_version') AS server_version,
            current_setting('server_version_num')::int AS server_version_num,
            pg_postmaster_start_time() AS server_started_at,
            clock_timestamp() AS checked_at,
            pg_size_pretty(pg_database_size(current_database())) AS database_size,
            pg_database_size(current_database()) AS database_size_bytes
    """,
    "connections": """
        SELECT
            state,
            count(*)::int AS connection_count
        FROM pg_stat_activity
        WHERE datname = current_database()
          AND backend_type = 'client backend'
        GROUP BY state
        ORDER BY connection_count DESC, state
    """,
    "long_transactions": """
        SELECT
            pid,
            usename AS username,
            application_name,
            client_addr::text AS client_address,
            state,
            xact_start,
            clock_timestamp() - xact_start AS transaction_age,
            backend_xmin::text AS backend_xmin,
            wait_event_type,
            wait_event,
            left(regexp_replace(query, E'[\\\\n\\\\r\\\\t]+', ' ', 'g'), 500) AS query
        FROM pg_stat_activity
        WHERE datname = current_database()
          AND pid <> pg_backend_pid()
          AND xact_start IS NOT NULL
        ORDER BY xact_start
    """,
    "blocking": """
        SELECT
            blocked.pid AS blocked_pid,
            blocked.usename AS blocked_user,
            blocked.application_name AS blocked_application,
            clock_timestamp() - blocked.query_start AS blocked_query_age,
            left(regexp_replace(blocked.query, E'[\\\\n\\\\r\\\\t]+', ' ', 'g'), 300) AS blocked_query,
            blocker.pid AS blocker_pid,
            blocker.usename AS blocker_user,
            blocker.application_name AS blocker_application,
            blocker.state AS blocker_state,
            blocker.xact_start AS blocker_xact_start,
            clock_timestamp() - blocker.xact_start AS blocker_transaction_age,
            left(regexp_replace(blocker.query, E'[\\\\n\\\\r\\\\t]+', ' ', 'g'), 300) AS blocker_query
        FROM pg_stat_activity AS blocked
        CROSS JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS p(blocker_pid)
        JOIN pg_stat_activity AS blocker ON blocker.pid = p.blocker_pid
        WHERE blocked.datname = current_database()
        ORDER BY blocked.pid, blocker.pid
    """,
    "tables": """
        SELECT
            s.schemaname,
            s.relname AS table_name,
            c.reltuples::bigint AS planner_row_estimate,
            s.n_live_tup AS estimated_live_rows,
            s.n_dead_tup AS estimated_dead_rows,
            round(
                100.0 * s.n_dead_tup /
                NULLIF(s.n_live_tup + s.n_dead_tup, 0), 2
            ) AS estimated_dead_tuple_pct,
            pg_size_pretty(pg_relation_size(s.relid)) AS heap_size,
            pg_size_pretty(pg_total_relation_size(s.relid)) AS total_size,
            s.seq_scan,
            s.idx_scan,
            s.n_tup_ins,
            s.n_tup_upd,
            s.n_tup_del,
            s.n_tup_hot_upd,
            s.last_vacuum,
            s.last_autovacuum,
            s.last_analyze,
            s.last_autoanalyze
        FROM pg_stat_user_tables AS s
        JOIN pg_class AS c ON c.oid = s.relid
        ORDER BY pg_total_relation_size(s.relid) DESC
    """,
    "indexes": """
        SELECT
            st.schemaname,
            st.relname AS table_name,
            st.indexrelname AS index_name,
            am.amname AS access_method,
            i.indisprimary AS is_primary,
            i.indisunique AS is_unique,
            i.indisvalid AS is_valid,
            st.idx_scan,
            st.idx_tup_read,
            st.idx_tup_fetch,
            pg_size_pretty(pg_relation_size(st.indexrelid)) AS index_size
        FROM pg_stat_user_indexes AS st
        JOIN pg_index AS i ON i.indexrelid = st.indexrelid
        JOIN pg_class AS ic ON ic.oid = st.indexrelid
        JOIN pg_am AS am ON am.oid = ic.relam
        ORDER BY pg_relation_size(st.indexrelid) DESC
    """,
    "replication": """
        SELECT
            pid,
            usename AS username,
            application_name,
            client_addr::text AS client_address,
            state,
            sync_state,
            sent_lsn::text AS sent_lsn,
            write_lsn::text AS write_lsn,
            flush_lsn::text AS flush_lsn,
            replay_lsn::text AS replay_lsn,
            write_lag,
            flush_lag,
            replay_lag
        FROM pg_stat_replication
        ORDER BY application_name, pid
    """,
    "wal_receiver": """
        SELECT
            status,
            receive_start_lsn::text AS receive_start_lsn,
            written_lsn::text AS written_lsn,
            flushed_lsn::text AS flushed_lsn,
            latest_end_lsn::text AS latest_end_lsn,
            last_msg_send_time,
            last_msg_receipt_time,
            sender_host,
            sender_port,
            slot_name
        FROM pg_stat_wal_receiver
    """,
}


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (timedelta,)):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def fetch_rows(conn: psycopg.Connection, sql: str) -> list[dict[str, Any]]:
    return conn.execute(sql).fetchall()


def collect(conn: psycopg.Connection, section: str) -> list[dict[str, Any]]:
    return fetch_rows(conn, QUERIES[section])


def build_findings(report: dict[str, Any], long_txn_seconds: int) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    blockers = report.get("blocking", [])
    if blockers:
        findings.append({
            "severity": "CRITICAL",
            "title": "Blocked sessions detected",
            "evidence": f"{len(blockers)} blocked/blocker relationship(s) found.",
            "recommendation": "Inspect both sessions, transaction age, application owner, and lock chain before terminating anything. Do not terminate sessions automatically.",
        })

    for txn in report.get("long_transactions", []):
        age = txn.get("transaction_age")
        if isinstance(age, timedelta) and age.total_seconds() >= long_txn_seconds:
            findings.append({
                "severity": "WARNING",
                "title": "Long-running transaction",
                "evidence": f"PID {txn['pid']} has held a transaction for {age}. State: {txn.get('state')}; backend_xmin: {txn.get('backend_xmin')}.",
                "recommendation": "Confirm with the application owner whether the transaction is expected. Check its snapshot horizon and impact on VACUUM before taking action.",
            })

    for table in report.get("tables", []):
        dead_pct = table.get("estimated_dead_tuple_pct")
        dead_rows = table.get("estimated_dead_rows")
        if dead_pct is not None and dead_pct >= 20 and (dead_rows or 0) >= 100:
            findings.append({
                "severity": "WARNING",
                "title": f"Elevated estimated dead tuples: {table['schemaname']}.{table['table_name']}",
                "evidence": f"Estimated dead tuples: {dead_rows}; estimated dead tuple percentage: {dead_pct}%.",
                "recommendation": "Treat these as statistics estimates, not a direct bloat measurement. Check autovacuum settings, table activity, long transactions, and run an appropriately planned VACUUM if authorized.",
            })

        if table.get("last_autovacuum") is None and table.get("last_vacuum") is None:
            findings.append({
                "severity": "INFO",
                "title": f"No recorded vacuum timestamp: {table['schemaname']}.{table['table_name']}",
                "evidence": "Both last_vacuum and last_autovacuum are NULL in pg_stat_user_tables.",
                "recommendation": "A NULL timestamp alone does not prove a vacuum problem. Consider table age, write activity, dead-tuple estimates, and statistics reset time.",
            })

    if not findings:
        findings.append({
            "severity": "INFO",
            "title": "No configured threshold findings",
            "evidence": "No blocking sessions, threshold-exceeding transactions, or elevated dead-tuple estimates were detected by this basic scan.",
            "recommendation": "This is not a full health guarantee. Review the detailed report and establish workload-specific baselines.",
        })

    return findings


def print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("(no rows)")
        return
    columns = list(rows[0].keys())
    values = [[json.dumps(row.get(c), default=json_default) if isinstance(row.get(c), (dict, list)) else str(row.get(c) if row.get(c) is not None else "") for c in columns] for row in rows]
    widths = [min(max(len(c), *(len(r[i]) for r in values)), 42) for i, c in enumerate(columns)]
    print(" | ".join(c[:widths[i]].ljust(widths[i]) for i, c in enumerate(columns)))
    print("-+-".join("-" * w for w in widths))
    for row in values:
        print(" | ".join(v[:widths[i]].ljust(widths[i]) for i, v in enumerate(row)))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only PostgreSQL DBA diagnostics. No database changes are performed."
    )
    parser.add_argument(
        "command",
        choices=["health", "connections", "transactions", "blocking", "tables", "indexes", "replication", "all"],
        help="Diagnostic section to run",
    )
    parser.add_argument("--dsn", default=os.getenv("PG_DSN"), help="PostgreSQL DSN; defaults to PG_DSN environment variable")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--long-txn-seconds", type=int, default=300, help="Warning threshold for transaction age (default: 300)")
    parser.add_argument("--timeout-ms", type=int, default=10000, help="Per-statement timeout in milliseconds (default: 10000)")
    args = parser.parse_args()

    if not args.dsn:
        print("ERROR: Set PG_DSN or pass --dsn. Do not put credentials in source code.", file=sys.stderr)
        return 2
    if args.long_txn_seconds < 1 or args.timeout_ms < 1:
        print("ERROR: thresholds must be positive integers.", file=sys.stderr)
        return 2

    section_map = {
        "health": ["health"],
        "connections": ["connections"],
        "transactions": ["long_transactions"],
        "blocking": ["blocking"],
        "tables": ["tables"],
        "indexes": ["indexes"],
        "replication": ["replication", "wal_receiver"],
        "all": list(QUERIES.keys()),
    }
    report: dict[str, Any] = {}
    try:
        with psycopg.connect(
            args.dsn,
            connect_timeout=5,
            application_name="postgres_dba_toolkit",
            row_factory=dict_row,
            options=f"-c statement_timeout={args.timeout_ms}",
        ) as conn:
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                for index, section in enumerate(section_map[args.command]):
                    savepoint = f"dba_section_{index}"
                    conn.execute(f"SAVEPOINT {savepoint}")
                    try:
                        report[section] = collect(conn, section)
                        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                    except psycopg.Error as exc:
                        report[section] = {"error": str(exc).splitlines()[0]}
                        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                        conn.execute(f"RELEASE SAVEPOINT {savepoint}")

                if args.command == "all" or args.command in {"transactions", "blocking", "tables"}:
                    if not any(isinstance(v, dict) and "error" in v for v in report.values()):
                        report["findings"] = build_findings(report, args.long_txn_seconds)

        if args.format == "json":
            print(json.dumps(report, default=json_default, indent=2))
        else:
            for section, rows in report.items():
                print(f"\n=== {section.upper()} ===")
                if isinstance(rows, dict) and "error" in rows:
                    print(f"ERROR: {rows['error']}")
                elif section == "findings":
                    for item in rows:
                        print(f"[{item['severity']}] {item['title']}")
                        print(f"  Evidence: {item['evidence']}")
                        print(f"  Recommendation: {item['recommendation']}")
                else:
                    print_table(rows)
        return 0
    except psycopg.OperationalError as exc:
        print(f"CONNECTION ERROR: {exc}", file=sys.stderr)
        return 3
    except psycopg.Error as exc:
        print(f"DATABASE ERROR: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
