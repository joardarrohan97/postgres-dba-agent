from agents.quality.claim_checker import validate_report

def test_flags_role_as_extension(): assert "PGF001" in [x["rule_id"] for x in validate_report("pg_monitor is an extension.")["findings"]]
def test_flags_explain_error(): assert "PGF002" in [x["rule_id"] for x in validate_report("EXPLAIN ANALYZE does not execute the query.")["findings"]]
def test_flags_superuser_requirement(): assert "PGF003" in [x["rule_id"] for x in validate_report("A superuser is always required for EXPLAIN.")["findings"]]
def test_flags_view_access_claim(): assert "PGF004" in [x["rule_id"] for x in validate_report("pg_stat_activity is inaccessible to ordinary users.")["findings"]]
def test_flags_superuser_grant(): assert "PGF005" in [x["rule_id"] for x in validate_report("Grant superuser privileges to dba_monitor.")["findings"]]
def test_accepts_correct_facts(): assert validate_report("pg_monitor is a predefined role, not an extension. EXPLAIN ANALYZE executes the statement. A superuser is not always required for EXPLAIN.")["status"]=="NO_KNOWN_PATTERN_FLAGS"
def test_empty_report(): assert validate_report("")["status"]=="INVALID_INPUT"
