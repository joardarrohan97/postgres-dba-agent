from .parser import parse_statement, SQLValidationError
from .policy import validate_read_only
from .functions import validate_functions
from .catalog import validate_catalog
from .audit import log_validation

def validate_sql(sql: str):
    try:
        stmt = parse_statement(sql)
        validate_read_only(stmt)
        validate_functions(stmt)
        return {"valid": True, "status": "STATIC_VALIDATION_PASSED", "message": "SQL passed syntax, statement policy and function checks."}
    except SQLValidationError as exc:
        return {"valid": False, "status": "REJECTED", "message": str(exc)}

def validate_candidate(sql: str, dsn: str):
    result = validate_sql(sql)
    if result["valid"]:
        result = validate_catalog(sql, dsn)
    try:
        log_validation(sql, result)
    except OSError as exc:
        return {"valid": False, "status": "AUDIT_FAILURE", "message": f"Audit logging failed: {exc.__class__.__name__}"}
    return result
