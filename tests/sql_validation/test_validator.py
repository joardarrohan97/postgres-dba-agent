import os
import pytest
from agents.sql_validation.parser import parse_statement, SQLValidationError
from agents.sql_validation.policy import validate_read_only
from agents.sql_validation.functions import validate_functions
from agents.sql_validation.validator import validate_candidate

def test_valid_select():
    assert validate_read_only(parse_statement("SELECT 1")) is True

def test_multiple_statements_rejected():
    with pytest.raises(SQLValidationError):
        parse_statement("SELECT 1; DROP TABLE test")

def test_delete_rejected():
    with pytest.raises(SQLValidationError):
        validate_read_only(parse_statement("DELETE FROM test"))

def test_select_into_rejected():
    with pytest.raises(SQLValidationError):
        validate_read_only(parse_statement("SELECT 1 INTO test"))

def test_row_lock_rejected():
    with pytest.raises(SQLValidationError):
        validate_read_only(parse_statement("SELECT * FROM pg_catalog.pg_class FOR UPDATE"))

def test_sleep_rejected():
    with pytest.raises(SQLValidationError):
        validate_functions(parse_statement("SELECT pg_catalog.pg_sleep(5)"))

def test_terminate_backend_rejected():
    with pytest.raises(SQLValidationError):
        validate_functions(parse_statement("SELECT pg_catalog.pg_terminate_backend(123)"))

@pytest.mark.skipif(not os.environ.get("DBA_AGENT_DSN"), reason="DBA_AGENT_DSN not configured")
def test_invalid_table_rejected():
    result = validate_candidate("SELECT * FROM definitely_missing_table", os.environ["DBA_AGENT_DSN"])
    assert result["status"] == "CATALOG_REJECTED"


def test_allowlisted_qualified_function():
    assert validate_functions(
        parse_statement("SELECT pg_catalog.now()")
    ) is True


def test_unqualified_function_rejected():
    with pytest.raises(SQLValidationError):
        validate_functions(parse_statement("SELECT count(*)"))


def test_non_catalog_function_schema_rejected():
    with pytest.raises(SQLValidationError):
        validate_functions(parse_statement("SELECT public.now()"))


def test_quoted_pg_catalog_schema_allowed():
    assert validate_functions(
        parse_statement('SELECT "pg_catalog".now()')
    ) is True


def test_nested_prohibited_function_rejected():
    with pytest.raises(SQLValidationError):
        validate_functions(
            parse_statement(
                "SELECT pg_catalog.pg_sleep(pg_catalog.count(*))"
            )
        )


def test_cast_is_not_treated_as_function_call():
    assert validate_functions(
        parse_statement("SELECT CAST(1 AS INTEGER)")
    ) is True


def test_current_timestamp_is_not_treated_as_function_call():
    assert validate_functions(
        parse_statement("SELECT CURRENT_TIMESTAMP")
    ) is True


def test_union_select_allowed():
    stmt = parse_statement("SELECT 1 UNION SELECT 2")
    assert validate_read_only(stmt) is True


def test_intersect_select_allowed():
    stmt = parse_statement("SELECT 1 INTERSECT SELECT 2")
    assert validate_read_only(stmt) is True


def test_cte_rejected():
    with pytest.raises(SQLValidationError):
        validate_read_only(
            parse_statement("WITH x AS (SELECT 1) SELECT * FROM x")
        )


def test_malformed_sql_rejected():
    with pytest.raises(SQLValidationError):
        parse_statement("SELECT FROM WHERE")
