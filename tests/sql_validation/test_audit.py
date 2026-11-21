import stat
from agents.sql_validation import audit, validator

def test_audit_log_created_with_private_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr(audit.Path, "home", lambda: tmp_path)
    audit.log_validation("SELECT 1", {"valid": True, "status": "CATALOG_VALIDATED", "message": "Test"})
    path = tmp_path / ".local/state/postgres-dba-agent/sql_validation.jsonl"
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    content = path.read_text()
    assert "sql_sha256" in content
    assert "SELECT 1" not in content

def test_audit_failure_fails_closed(monkeypatch):
    def fail_logging(sql, result):
        raise OSError("Simulated disk failure")
    monkeypatch.setattr(validator, "log_validation", fail_logging)
    result = validator.validate_candidate("DELETE FROM employees", "")
    assert result["status"] == "AUDIT_FAILURE"
    assert result["valid"] is False
