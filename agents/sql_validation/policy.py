from sqlglot import exp

from .parser import SQLValidationError


def validate_read_only(stmt):
    if not isinstance(stmt, (exp.Select, exp.SetOperation)):
        raise SQLValidationError("Only SELECT statements are allowed.")

    select_nodes = list(stmt.find_all(exp.Select))

    if not select_nodes:
        raise SQLValidationError("Only SELECT statements are allowed.")

    for select in select_nodes:
        if select.args.get("into") is not None:
            raise SQLValidationError("SELECT INTO is not allowed.")

        if select.args.get("locks"):
            raise SQLValidationError(
                "SELECT FOR UPDATE/SHARE is not allowed."
            )

        if select.args.get("with_") is not None:
            raise SQLValidationError(
                "CTEs are temporarily disabled pending recursive validation."
            )

    return True
