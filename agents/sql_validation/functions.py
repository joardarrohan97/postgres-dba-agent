from sqlglot import exp

from .parser import SQLValidationError


SAFE_FUNCTIONS = {
    "now", "statement_timestamp", "transaction_timestamp", "clock_timestamp",
    "current_database", "current_schema", "version", "pg_backend_pid",
    "pg_blocking_pids", "pg_relation_size", "pg_total_relation_size",
    "pg_table_size", "pg_indexes_size", "pg_size_pretty", "pg_get_userbyid",
    "pg_get_viewdef", "pg_get_indexdef", "count", "sum", "avg", "min", "max",
    "array_agg", "string_agg", "bool_and", "bool_or", "round", "abs",
    "ceil", "floor", "lower", "upper", "length", "substring", "date_trunc",
    "unnest",
}


# These are SQL expressions/syntax forms, not ordinary function calls.
# The previous parser visitor did not collect them as function calls.
NON_CALL_FUNCTION_NODES = {
    "Cast",
    "TryCast",
    "CurrentDate",
    "CurrentTime",
    "CurrentTimestamp",
    "CurrentUser",
    "CurrentRole",
    "SessionUser",
    "User",
    "CurrentSchema",
    "CurrentCatalog",
}


def validate_functions(stmt):
    for func in stmt.find_all(exp.Func):
        if type(func).__name__ in NON_CALL_FUNCTION_NODES:
            continue

        parent = func.parent

        # A permitted function must have exactly this AST shape:
        # pg_catalog.function_name(...)
        if (
            not isinstance(parent, exp.Dot)
            or parent.expression is not func
            or not isinstance(parent.this, exp.Identifier)
        ):
            name = (func.name or type(func).__name__).lower()
            raise SQLValidationError(f"Unapproved function schema: {(name,)}")

        schema = str(parent.this.this).lower()
        function_name = (func.name or "").lower()

        if schema != "pg_catalog":
            raise SQLValidationError(
                f"Unapproved function schema: {(schema, function_name)}"
            )

        if function_name not in SAFE_FUNCTIONS:
            raise SQLValidationError(
                f"Function not allowlisted: {function_name}"
            )

    return True
