#!/usr/bin/env python3
"""PostgreSQL DBA Toolkit v2 - evidence-first, read-only diagnostics + plan analysis."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dba_agent.db import connect
from dba_agent.diagnostics import collect_report, run_explain
from dba_agent.ollama import ask_ollama
from dba_agent.report import render_report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Evidence-first PostgreSQL DBA diagnostics. Diagnostics are read-only; EXPLAIN ANALYZE requires explicit opt-in."
    )
    p.add_argument("command", choices=[
        "health", "connections", "transactions", "blocking", "tables", "indexes",
        "replication", "config", "statements", "all", "explain", "ask"
    ])
    p.add_argument("--dsn", default=os.getenv("PG_DSN"), help="libpq DSN; defaults to PG_DSN")
    p.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    p.add_argument("--long-txn-seconds", type=int, default=300)
    p.add_argument("--dead-tuple-pct", type=float, default=20.0)
    p.add_argument("--dead-tuple-min", type=int, default=100)
    p.add_argument("--timeout-ms", type=int, default=10000)
    p.add_argument("--sql", help="Trusted SELECT/WITH query for EXPLAIN")
    p.add_argument("--sql-file", type=Path, help="Read trusted SQL from a file for EXPLAIN")
    p.add_argument("--analyze", action="store_true", help="Run EXPLAIN ANALYZE (executes the statement)")
    p.add_argument("--allow-execution", action="store_true", help="Required confirmation for EXPLAIN ANALYZE")
    p.add_argument("--question", help="Question for the local Ollama model when command=ask")
    p.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "qwen3.5:4b"))
    p.add_argument("--ollama-url", default=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"))
    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "ask" and not args.question:
        print("ERROR: ask requires --question", file=sys.stderr)
        return 2
    if args.command in {"explain"} and not (args.sql or args.sql_file):
        print("ERROR: explain requires --sql or --sql-file", file=sys.stderr)
        return 2
    if args.sql and args.sql_file:
        print("ERROR: use either --sql or --sql-file, not both", file=sys.stderr)
        return 2
    if args.analyze and not args.allow_execution:
        print("SAFETY ERROR: --analyze executes the statement. Add --allow-execution only after reviewing trusted SQL.", file=sys.stderr)
        return 2
    if args.allow_execution and not args.analyze:
        print("ERROR: --allow-execution is only valid with --analyze", file=sys.stderr)
        return 2
    if args.timeout_ms < 1 or args.long_txn_seconds < 1 or args.dead_tuple_min < 0 or not (0 <= args.dead_tuple_pct <= 100):
        print("ERROR: invalid threshold or timeout", file=sys.stderr)
        return 2
    if not args.dsn:
        print("ERROR: Set PG_DSN or pass --dsn. Do not put credentials in source code.", file=sys.stderr)
        return 2

    try:
        if args.command == "explain":
            sql = args.sql if args.sql is not None else args.sql_file.read_text(encoding="utf-8")
            with connect(args.dsn, args.timeout_ms) as conn:
                result = run_explain(conn, sql, analyze=args.analyze)
            report = {"explain": result}
        else:
            with connect(args.dsn, args.timeout_ms) as conn:
                diagnostic_command = "all" if args.command == "ask" else args.command
                report = collect_report(
                    conn, diagnostic_command,
                    long_txn_seconds=args.long_txn_seconds,
                    dead_tuple_pct=args.dead_tuple_pct,
                    dead_tuple_min=args.dead_tuple_min,
                )
            if args.command == "ask":
                answer = ask_ollama(
                    base_url=args.ollama_url,
                    model=args.model,
                    question=args.question,
                    report=report,
                )
                report["senior_dba_assessment"] = answer

        print(render_report(report, args.format))
        return 0
    except FileNotFoundError as exc:
        print(f"FILE ERROR: {exc}", file=sys.stderr)
        return 2
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4
    except Exception as exc:
        # Keep error output useful without printing DSNs or credentials.
        print(f"EXECUTION ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
