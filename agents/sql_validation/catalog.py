import psycopg

def validate_catalog(sql: str, dsn: str):
    if not dsn:
        return {"valid": False, "status": "CATALOG_UNAVAILABLE", "message": "Database DSN is missing."}
    try:
        conn = psycopg.connect(dsn, connect_timeout=5)
    except psycopg.Error as exc:
        return {"valid": False, "status": "CATALOG_UNAVAILABLE", "message": f"Database connection failed: {exc.__class__.__name__}"}
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '5s'")
                cur.execute("SET LOCAL lock_timeout = '1s'")
                cur.execute("EXPLAIN (FORMAT JSON, COSTS OFF) " + sql)
                cur.fetchone()
        return {"valid": True, "status": "CATALOG_VALIDATED", "message": "PostgreSQL accepted the query for analysis, object resolution, permission checks and planning. The query was not executed."}
    except psycopg.Error as exc:
        return {"valid": False, "status": "CATALOG_REJECTED", "message": f"PostgreSQL rejected the query: {exc.__class__.__name__}: {exc.sqlstate or 'unknown SQLSTATE'}"}
    finally:
        conn.close()
