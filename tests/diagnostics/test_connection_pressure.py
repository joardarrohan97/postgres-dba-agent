import pytest
from agents.diagnostics.connection_pressure import analyze_connection_pressure

def report(rows, maximum=100):
    return {"connections": rows, "config": [{"name": "max_connections", "setting": str(maximum)}]}

def test_one_active_connection_is_normal():
    result = analyze_connection_pressure(report([{"state": "active", "connection_count": 1}]))
    assert result["classification"] == "NORMAL"
    assert result["utilization_percent"] == 1.0
    assert result["nominal_remaining_capacity"] == 99

@pytest.mark.parametrize(("count", "expected"), [(59, "NORMAL"), (60, "WATCH"), (80, "HIGH"), (90, "CRITICAL")])
def test_utilization_thresholds(count, expected):
    assert analyze_connection_pressure(report([{"state": "active", "connection_count": count}]))["classification"] == expected

def test_connection_states_are_counted():
    result = analyze_connection_pressure(report([{"state": "active", "connection_count": 2}, {"state": "idle", "connection_count": 3}, {"state": "idle in transaction", "connection_count": 1}]))
    assert (result["total_connections"], result["active_connections"], result["idle_connections"], result["idle_in_transaction_connections"]) == (6, 2, 3, 1)
    assert any("do not terminate" in item for item in result["recommendations"])

def test_empty_successful_query_means_zero_connections():
    assert analyze_connection_pressure(report([]))["total_connections"] == 0

def test_missing_config_is_insufficient_not_zero():
    result = analyze_connection_pressure({"connections": []})
    assert result["status"] == "INSUFFICIENT_DATA"
    assert "config.max_connections" in result["missing_evidence"]

def test_invalid_threshold_order_is_rejected():
    with pytest.raises(ValueError):
        analyze_connection_pressure(report([{"state": "active", "connection_count": 1}]), {"watch": 80, "high": 60, "critical": 90})
