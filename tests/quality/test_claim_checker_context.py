from agents.quality.claim_checker import validate_report

def test_accepts_correct_postgres_explanations():
    text = "pg_monitor is a predefined role, not an extension. EXPLAIN ANALYZE executes the statement. A superuser is not always required for EXPLAIN."
    assert validate_report(text)["status"] == "NO_KNOWN_PATTERN_FLAGS"

def test_detection_is_case_insensitive():
    result = validate_report("PG_MONITOR IS AN EXTENSION.")
    assert "PGF001" in [x["rule_id"] for x in result["findings"]]

def test_detects_multiple_inaccuracies():
    text = "pg_monitor is an extension. EXPLAIN ANALYZE does not execute. Grant superuser privileges to dba_monitor."
    ids = {x["rule_id"] for x in validate_report(text)["findings"]}
    assert {"PGF001", "PGF002", "PGF005"}.issubset(ids)

def test_unrelated_technical_text_is_not_flagged():
    result = validate_report("The database has 24 MB of data and PostgreSQL 18.6 is running.")
    assert result["status"] == "NO_KNOWN_PATTERN_FLAGS"
