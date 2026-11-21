
from datetime import timedelta

from agents.diagnostics.transaction_lock_analyzer import analyze_transaction_locks


def test_missing_all_sections_is_insufficient():
    result = analyze_transaction_locks({})
    assert result["status"] == "INSUFFICIENT_DATA"


def test_empty_successful_sections_are_normal():
    result = analyze_transaction_locks({"transactions": [], "connection_details": [], "blocking": []})
    assert result["status"] == "ANALYZED"
    assert result["severity"] == "NORMAL"
    assert result["blocking_count"] == 0


def test_detects_long_transaction():
    result = analyze_transaction_locks({"transactions": [{"pid": 11, "transaction_age": timedelta(seconds=400), "state": "active"}]})
    assert result["long_transactions"][0]["pid"] == 11
    assert result["severity"] == "WATCH"


def test_detects_idle_in_transaction():
    result = analyze_transaction_locks({"connection_details": [{"pid": 12, "state": "idle in transaction", "transaction_age": timedelta(seconds=90)}]})
    assert result["idle_in_transaction"][0]["pid"] == 12
    assert result["severity"] == "HIGH"


def test_detects_long_active_query():
    result = analyze_transaction_locks({"connection_details": [{"pid": 13, "state": "active", "query_age": timedelta(seconds=90), "transaction_age": timedelta(seconds=100)}]})
    assert result["long_running_queries"][0]["pid"] == 13
    assert result["severity"] == "WATCH"


def test_detects_blocking_pair():
    result = analyze_transaction_locks({"blocking": [{"blocked_pid": 21, "blocker_pid": 22, "blocked_query_age": timedelta(seconds=90), "blocker_state": "idle in transaction"}]})
    assert result["blocking_count"] == 1
    assert result["severity"] == "CRITICAL"


def test_deduplicates_blocking_pairs():
    row = {"blocked_pid": 21, "blocker_pid": 22}
    result = analyze_transaction_locks({"blocking": [row, row]})
    assert result["blocking_count"] == 1


def test_custom_thresholds_and_no_termination_actions():
    result = analyze_transaction_locks({"transactions": [{"pid": 1, "transaction_age": 30}]}, {"long_transaction_seconds": 20})
    assert result["severity"] == "WATCH"
    assert "terminate" in result["safety"].lower()
    assert not any("pg_terminate_backend" in x or "pg_cancel_backend" in x for x in result["recommendations"])
