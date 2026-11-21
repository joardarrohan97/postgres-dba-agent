from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import psycopg
from psycopg.conninfo import conninfo_to_dict
ROOT = Path(__file__).resolve().parents[1]
TOOLKIT = ROOT / "tools" / "postgres_dba_toolkit_v2"
if str(TOOLKIT) not in sys.path:
    sys.path.insert(0, str(TOOLKIT))
from dba_agent.db import connect
from dba_agent.diagnostics import collect_report
ALLOWED_DIAGNOSTICS = {"health", "connections", "transactions", "blocking", "tables", "indexes", "replication", "config", "statements", "all"}
def _audit(diagnostic, status):
    directory = Path.home() / ".local" / "state" / "postgres-dba-agent"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    path = directory / "execution_broker.jsonl"
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), "database": "postgres_dba_lab", "diagnostic": diagnostic, "status": status}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, (json.dumps(record) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
def run_diagnostic(diagnostic: str, dsn: str | None = None) -> dict:
    if diagnostic not in ALLOWED_DIAGNOSTICS:
        return {"status": "REJECTED", "message": "Diagnostic is not allowlisted."}
    database_dsn = dsn if dsn is not None else os.environ.get("DBA_AGENT_DSN", "")
    if not database_dsn:
        return {"status": "CONFIGURATION_ERROR", "message": "Database DSN is missing."}
    try:
        target = conninfo_to_dict(database_dsn)
    except Exception:
        return {"status": "TARGET_REJECTED", "message": "Database connection target is invalid."}
    if target.get("dbname") != "postgres_dba_lab" or target.get("user") != "dba_monitor" or target.get("host") != "127.0.0.1" or target.get("port", "5432") != "5432" or target.get("hostaddr") or target.get("service") or target.get("servicefile"):
        return {"status": "TARGET_REJECTED", "message": "Only the local postgres_dba_lab database and dba_monitor role are permitted."}
    try:
        _audit(diagnostic, "REQUESTED")
    except OSError:
        return {"status": "AUDIT_FAILURE", "message": "Could not record the diagnostic request; operation blocked."}
    try:
        with connect(database_dsn) as conn:
            report = collect_report(conn, diagnostic)
    except Exception as exc:
        try:
            _audit(diagnostic, "FAILED")
        except OSError:
            pass
        return {"status": "DIAGNOSTIC_FAILED", "error_type": type(exc).__name__}
    try:
        _audit(diagnostic, "COMPLETED")
    except OSError:
        return {"status": "AUDIT_FAILURE", "message": "Diagnostic completed, but completion audit failed."}
    return {"status": "COMPLETED", "diagnostic": diagnostic, "read_only": True, "report": report}
