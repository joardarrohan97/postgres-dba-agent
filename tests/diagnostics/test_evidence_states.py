from agents.orchestrator import _diagnostic_status, _configuration_evidence, build_monitoring_access_summary

def test_missing_section_is_not_collected():
    assert _diagnostic_status({}, "tables")["status"] == "NOT_COLLECTED"

def test_empty_successful_query_is_distinguished():
    result = _diagnostic_status({"tables": []}, "tables")
    assert result["status"] == "QUERY_SUCCEEDED_EMPTY"
    assert result["row_count"] == 0

def test_successful_query_with_rows_is_distinguished():
    result = _diagnostic_status({"tables": [{"name": "orders"}]}, "tables")
    assert result["status"] == "QUERY_SUCCEEDED_WITH_ROWS"
    assert result["row_count"] == 1

def test_permission_error_is_explicitly_identified():
    report = {"tables": {"error": "permission denied for view pg_stat_user_tables"}}
    result = _diagnostic_status(report, "tables")
    assert result["status"] == "QUERY_FAILED"
    assert result["failure_type"] == "PERMISSION_DENIED"

def test_other_query_error_is_not_mislabelled_permission_error():
    report = {"tables": {"error": "relation does not exist"}}
    result = _diagnostic_status(report, "tables")
    assert result["status"] == "QUERY_FAILED"
    assert result["failure_type"] == "OTHER_ERROR"

def test_effective_cache_size_is_converted_to_gib():
    report = {"config": [{"name": "effective_cache_size", "setting": "524288", "unit": "8kB"}]}
    result = _configuration_evidence(report)
    setting = next(row for row in result["settings"] if row["name"] == "effective_cache_size")
    assert setting["raw_setting"] == "524288"
    assert setting["unit"] == "8kB"
    assert setting["interpreted_value"] == "4 GiB"

def test_missing_statistics_section_does_not_prove_permission_failure():
    result = build_monitoring_access_summary({"permissions": [{"has_pg_monitor": False}]})
    assert result["view_access"]["pg_stat_user_tables"]["status"] == "NOT_COLLECTED"
    assert "does not prove view inaccessibility" in result["interpretation"]
