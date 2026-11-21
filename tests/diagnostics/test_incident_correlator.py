from agents.diagnostics.incident_correlator import correlate_incident


def normal_connection():
    return {
        "status": "ANALYZED",
        "classification": "NORMAL",
        "utilization_percent": 1.0,
        "total_connections": 1,
        "max_connections": 100,
        "connection_states": {"active": 1},
    }


def normal_transactions():
    return {
        "status": "ANALYZED",
        "severity": "NORMAL",
        "blocking_count": 0,
        "long_transactions": [],
        "idle_in_transaction": [],
        "long_running_queries": [],
        "blocking_relationships": [],
        "missing_evidence": [],
    }


def test_normal_snapshot_produces_no_incident():
    result = correlate_incident(normal_connection(), normal_transactions())
    assert result["status"] == "ANALYZED"
    assert result["severity"] == "NORMAL"
    assert result["incident_count"] == 0


def test_critical_connection_pressure_is_detected():
    connection = normal_connection()
    connection["classification"] = "CRITICAL"
    connection["utilization_percent"] = 95.0

    result = correlate_incident(connection, normal_transactions())

    assert result["severity"] == "CRITICAL"
    assert result["incidents"][0]["id"] == "CONNECTION_PRESSURE"


def test_blocking_relationships_are_detected():
    transaction = normal_transactions()
    transaction.update({
        "severity": "HIGH",
        "blocking_count": 2,
        "blocking_relationships": [
            {"blocked_pid": 101, "blocker_pid": 99}
        ],
    })

    result = correlate_incident(normal_connection(), transaction)

    assert result["severity"] == "HIGH"
    assert "LOCK_CONTENTION" in [
        item["id"] for item in result["incidents"]
    ]


def test_idle_in_transaction_is_detected():
    transaction = normal_transactions()
    transaction["idle_in_transaction"] = [
        {"pid": 101, "transaction_age_seconds": 180}
    ]
    transaction["severity"] = "HIGH"

    result = correlate_incident(normal_connection(), transaction)

    assert "IDLE_IN_TRANSACTION" in [
        item["id"] for item in result["incidents"]
    ]


def test_long_transactions_are_detected():
    transaction = normal_transactions()
    transaction["long_transactions"] = [
        {"pid": 101, "transaction_age_seconds": 600}
    ]
    transaction["severity"] = "WATCH"

    result = correlate_incident(normal_connection(), transaction)

    assert "LONG_TRANSACTION" in [
        item["id"] for item in result["incidents"]
    ]


def test_multiple_incidents_use_highest_severity():
    connection = normal_connection()
    connection["classification"] = "CRITICAL"

    transaction = normal_transactions()
    transaction["blocking_count"] = 1
    transaction["blocking_relationships"] = [
        {"blocked_pid": 101, "blocker_pid": 99}
    ]
    transaction["severity"] = "HIGH"

    result = correlate_incident(connection, transaction)

    assert result["incident_count"] == 2
    assert result["severity"] == "CRITICAL"


def test_missing_analyzer_evidence_is_not_reported_as_normal():
    result = correlate_incident(
        {"status": "INSUFFICIENT_DATA"},
        {
            "status": "INSUFFICIENT_DATA",
            "missing_evidence": ["blocking section missing"],
        },
    )

    assert result["status"] == "PARTIAL"
    assert result["severity"] == "UNKNOWN"
    assert result["missing_evidence"]


def test_no_automatic_remediation_is_performed():
    result = correlate_incident(
        normal_connection(),
        normal_transactions(),
    )

    assert "No SQL is executed" in result["safety"]
    assert "remediation" in result["safety"]
