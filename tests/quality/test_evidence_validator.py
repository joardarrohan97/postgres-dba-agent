from agents.quality.evidence_validator import validate_evidence

def test_flags_activity_inaccessible_when_query_succeeded():
    result = validate_evidence({"connections": []}, "pg_stat_activity is inaccessible.")
    assert "EV001" in [item["rule_id"] for item in result["findings"]]

def test_empty_successful_activity_query_still_proves_access():
    result = validate_evidence({"connections": []}, "pg_stat_activity is inaccessible.")
    assert result["status"] == "REVIEW_REQUIRED"

def test_flags_table_stats_inaccessible_when_query_succeeded():
    result = validate_evidence({"tables": []}, "pg_stat_user_tables is inaccessible.")
    assert "EV002" in [item["rule_id"] for item in result["findings"]]

def test_flags_incorrect_track_activities_default():
    result = validate_evidence({}, "track_activities defaults to off.")
    assert "EV003" in [item["rule_id"] for item in result["findings"]]

def test_uses_live_track_activities_setting():
    report = {"config": [{"name": "track_activities", "setting": "on"}]}
    result = validate_evidence(report, "track_activities is disabled.")
    assert "EV004" in [item["rule_id"] for item in result["findings"]]

def test_missing_track_activities_evidence_is_unverified():
    result = validate_evidence({"config": []}, "track_activities is enabled.")
    assert result["status"] == "UNVERIFIED_CLAIMS"
    assert result["unverified"]

def test_does_not_infer_access_from_role_membership_alone():
    report = {"permissions": [{"has_pg_monitor": False}]}
    result = validate_evidence(report, "pg_stat_activity is inaccessible because of missing pg_monitor.")
    assert result["status"] == "UNVERIFIED_CLAIMS"

def test_accepts_supported_activity_diagnostic_claim():
    report = {"connections": [], "permissions": [{"has_pg_monitor": False}]}
    result = validate_evidence(report, "The connections diagnostic successfully queried pg_stat_activity.")
    assert result["status"] == "NO_EVIDENCE_CONTRADICTIONS"

def test_invalid_input():
    assert validate_evidence({}, "")["status"] == "INVALID_INPUT"


def test_flags_broad_activity_statistics_access_claim():
    report = {"connections": []}
    answer = "Cannot access detailed cumulative statistics such as pg_stat_activity due to missing roles."
    result = validate_evidence(report, answer)
    assert "EV006" in [item["rule_id"] for item in result["findings"]]

def test_flags_broad_table_statistics_access_claim():
    report = {"tables": []}
    answer = "Detailed cumulative statistics including pg_stat_user_tables are inaccessible."
    result = validate_evidence(report, answer)
    assert "EV007" in [item["rule_id"] for item in result["findings"]]

def test_flags_both_broad_access_claims_together():
    report = {"connections": [], "tables": []}
    answer = "Cannot access detailed cumulative statistics (e.g. pg_stat_activity, pg_stat_user_tables) due to missing roles."
    result = validate_evidence(report, answer)
    ids = [item["rule_id"] for item in result["findings"]]
    assert "EV006" in ids and "EV007" in ids

def test_qualified_cross_user_visibility_caveat_is_not_flagged():
    report = {"connections": [], "permissions": [{"has_pg_monitor": False}]}
    answer = "The connections query succeeded. dba_monitor is not a member of pg_monitor, so details for other users may be restricted; empty results do not prove a permission failure."
    result = validate_evidence(report, answer)
    assert "EV006" not in [item["rule_id"] for item in result["findings"]]
