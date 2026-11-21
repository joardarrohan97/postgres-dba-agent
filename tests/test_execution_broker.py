import stat
from contextlib import contextmanager
import pytest
from agents import execution_broker as broker

VALID_DSN = "postgresql://dba_monitor@127.0.0.1:5432/postgres_dba_lab"

def test_unknown_diagnostic_rejected():
    result = broker.run_diagnostic("drop_table", VALID_DSN)
    assert result["status"] == "REJECTED"

def test_company_database_rejected():
    result = broker.run_diagnostic("health", "postgresql://dba_monitor@127.0.0.1:5432/company_db")
    assert result["status"] == "TARGET_REJECTED"

def test_hostaddr_override_rejected():
    dsn = "host=127.0.0.1 hostaddr=192.0.2.10 dbname=postgres_dba_lab user=dba_monitor port=5432"
    result = broker.run_diagnostic("health", dsn)
    assert result["status"] == "TARGET_REJECTED"

def test_missing_dsn_rejected(monkeypatch):
    monkeypatch.delenv("DBA_AGENT_DSN", raising=False)
    result = broker.run_diagnostic("health", "")
    assert result["status"] == "CONFIGURATION_ERROR"

def test_allowlisted_diagnostic_runs_through_toolkit(monkeypatch):
    calls = []
    @contextmanager
    def fake_connect(dsn):
        calls.append(("connect", dsn))
        yield object()
    def fake_collect(conn, diagnostic):
        calls.append(("collect", diagnostic))
        return {"sample": True}
    monkeypatch.setattr(broker, "connect", fake_connect)
    monkeypatch.setattr(broker, "collect_report", fake_collect)
    monkeypatch.setattr(broker, "_audit", lambda diagnostic, status: None)
    result = broker.run_diagnostic("health", VALID_DSN)
    assert result["status"] == "COMPLETED"
    assert result["read_only"] is True
    assert calls == [("connect", VALID_DSN), ("collect", "health")]

def test_audit_request_failure_blocks_execution(monkeypatch):
    def fail_audit(diagnostic, status):
        raise OSError("simulated audit failure")
    def should_not_connect(dsn):
        pytest.fail("Database connection must not start when request audit fails")
    monkeypatch.setattr(broker, "_audit", fail_audit)
    monkeypatch.setattr(broker, "connect", should_not_connect)
    result = broker.run_diagnostic("health", VALID_DSN)
    assert result["status"] == "AUDIT_FAILURE"

def test_audit_log_has_private_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr(broker.Path, "home", lambda: tmp_path)
    broker._audit("health", "REQUESTED")
    path = tmp_path / ".local/state/postgres-dba-agent/execution_broker.jsonl"
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

def test_connections_diagnostic_is_allowlisted(monkeypatch):
    calls = []
    @contextmanager
    def fake_connect(dsn):
        calls.append(("connect", dsn))
        yield object()
    def fake_collect(conn, diagnostic):
        calls.append(("collect", diagnostic))
        return {"connections": [], "connection_details": []}
    monkeypatch.setattr(broker, "connect", fake_connect)
    monkeypatch.setattr(broker, "collect_report", fake_collect)
    monkeypatch.setattr(broker, "_audit", lambda diagnostic, status: None)
    result = broker.run_diagnostic("connections", VALID_DSN)
    assert result["status"] == "COMPLETED"
    assert result["report"]["connection_details"] == []
    assert calls == [("connect", VALID_DSN), ("collect", "connections")]
