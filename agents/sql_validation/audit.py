import os
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

def log_validation(sql, result):
    log_dir = Path.home() / ".local" / "state" / "postgres-dba-agent"
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(log_dir, 0o700)
    path = log_dir / "sql_validation.jsonl"
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        "status": result.get("status"),
        "valid": result.get("valid"),
        "message": result.get("message"),
    }
    payload = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, payload)
    finally:
        os.close(fd)
