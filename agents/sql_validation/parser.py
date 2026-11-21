from sqlglot import parse
from sqlglot.errors import ErrorLevel, ParseError


class SQLValidationError(Exception):
    pass


def parse_statement(sql: str):
    if not isinstance(sql, str) or not sql.strip():
        raise SQLValidationError("SQL cannot be empty.")

    try:
        statements = [
            statement
            for statement in parse(
                sql,
                read="postgres",
                error_level=ErrorLevel.RAISE,
            )
            if statement is not None
        ]
    except ParseError as exc:
        raise SQLValidationError(f"SQL syntax error: {exc}") from exc

    if len(statements) != 1:
        raise SQLValidationError("Exactly one SQL statement is allowed.")

    return statements[0]
