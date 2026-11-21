from __future__ import annotations

from typing import Any

SEVERITY_RANK = {
    "NORMAL": 0,
    "WATCH": 1,
    "HIGH": 2,
    "CRITICAL": 3,
}


def correlate_incident(
    connection_pressure: dict[str, Any],
    transaction_lock: dict[str, Any],
) -> dict[str, Any]:

    incidents = []
    missing = []
    recommendations = []

    if not isinstance(connection_pressure, dict):
        connection_pressure = {}

    if not isinstance(transaction_lock, dict):
        transaction_lock = {}

    if connection_pressure.get("status") != "ANALYZED":
        missing.append("Connection-pressure analysis is incomplete.")

    if transaction_lock.get("status") != "ANALYZED":
        missing.append("Transaction and lock analysis is incomplete.")

    for item in transaction_lock.get("missing_evidence", []):
        if item not in missing:
            missing.append(item)

    def add_incident(identifier, severity, title, evidence, next_steps):
        incidents.append({
            "id": identifier,
            "severity": severity,
            "title": title,
            "evidence": evidence,
            "recommended_investigation": next_steps,
        })

    classification = str(
        connection_pressure.get("classification", "UNKNOWN")
    ).upper()

    if classification in ("WATCH", "HIGH", "CRITICAL"):
        add_incident(
            "CONNECTION_PRESSURE",
            classification,
            "Elevated PostgreSQL connection utilization",
            {
                "utilization_percent": connection_pressure.get("utilization_percent"),
                "total_connections": connection_pressure.get("total_connections"),
                "max_connections": connection_pressure.get("max_connections"),
                "connection_states": connection_pressure.get("connection_states", {}),
            },
            [
                "Review connection sources and application pool sizing.",
                "Check whether connection growth is sustained before considering configuration changes.",
            ],
        )

    blocking_count = transaction_lock.get("blocking_count", 0)

    if isinstance(blocking_count, (int, float)) and blocking_count > 0:
        severity = str(transaction_lock.get("severity", "HIGH")).upper()

        if severity not in SEVERITY_RANK or severity == "NORMAL":
            severity = "HIGH"

        add_incident(
            "LOCK_CONTENTION",
            severity,
            "PostgreSQL blocking relationships detected",
            {
                "blocking_count": blocking_count,
                "blocking_relationships": transaction_lock.get(
                    "blocking_relationships", []
                ),
            },
            [
                "Identify blocker and blocked sessions.",
                "Review transaction ownership and lock wait duration before intervention.",
            ],
        )

    incident_types = [
        (
            "long_transactions",
            "LONG_TRANSACTION",
            "Long-running transactions detected",
            "Review transaction age, application ownership and whether the transaction is still required.",
        ),
        (
            "idle_in_transaction",
            "IDLE_IN_TRANSACTION",
            "Idle-in-transaction sessions detected",
            "Investigate application transaction handling and sessions holding open transactions.",
        ),
        (
            "long_running_queries",
            "LONG_RUNNING_QUERY",
            "Long-running queries detected",
            "Inspect SQL text and execution plans before proposing query or index changes.",
        ),
    ]

    for key, identifier, title, recommendation in incident_types:
        rows = transaction_lock.get(key, [])

        if isinstance(rows, list) and rows:
            severity = str(transaction_lock.get("severity", "WATCH")).upper()

            if severity not in SEVERITY_RANK or severity == "NORMAL":
                severity = "WATCH"

            add_incident(
                identifier,
                severity,
                title,
                {"count": len(rows), "details": rows},
                [recommendation],
            )

    known_symptoms = any(
        item["id"] in (
            "LOCK_CONTENTION",
            "LONG_TRANSACTION",
            "IDLE_IN_TRANSACTION",
            "LONG_RUNNING_QUERY",
        )
        for item in incidents
    )

    analyzer_severity = str(
        transaction_lock.get("severity", "UNKNOWN")
    ).upper()

    if analyzer_severity in ("HIGH", "CRITICAL") and not known_symptoms:
        add_incident(
            "TRANSACTION_LOCK_ALERT",
            analyzer_severity,
            "Transaction and lock analyzer reported elevated severity",
            {"analyzer_severity": analyzer_severity},
            ["Inspect the underlying transaction and lock diagnostic evidence."],
        )

    for incident in incidents:
        recommendations.extend(
            incident["recommended_investigation"]
        )

    complete = (
        connection_pressure.get("status") == "ANALYZED"
        and transaction_lock.get("status") == "ANALYZED"
        and not missing
    )

    if incidents:
        severity = max(
            (item["severity"] for item in incidents),
            key=lambda value: SEVERITY_RANK.get(value, 0),
        )
    else:
        severity = "NORMAL" if complete else "UNKNOWN"

    if not incidents and complete:
        recommendations.append(
            "No incident-specific remediation is indicated by the current diagnostic snapshot."
        )

    if missing:
        recommendations.append(
            "Collect the missing diagnostic evidence before drawing further conclusions."
        )

    return {
        "status": "ANALYZED" if complete else "PARTIAL",
        "severity": severity,
        "confidence": "HIGH" if complete else "LIMITED",
        "incident_count": len(incidents),
        "incidents": incidents,
        "missing_evidence": missing,
        "recommendations": list(dict.fromkeys(recommendations)),
        "safety": (
            "Deterministic correlation of read-only diagnostic results. "
            "A single snapshot does not establish trends or prove root cause. "
            "No SQL is executed and no remediation is performed."
        ),
    }
