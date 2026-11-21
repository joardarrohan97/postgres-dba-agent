import os
from .validator import validate_candidate

def validate_proposal(sql: str, dsn: str | None = None) -> dict:
    """Validate proposed SQL. Never executes the proposed SQL."""
    database_dsn = dsn if dsn is not None else os.environ.get("DBA_AGENT_DSN", "")
    return validate_candidate(sql, database_dsn)
