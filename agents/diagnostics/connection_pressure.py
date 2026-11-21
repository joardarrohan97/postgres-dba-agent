"""Read-only connection-pressure scoring for PostgreSQL diagnostic reports."""
DEFAULT_THRESHOLDS = {"watch": 60.0, "high": 80.0, "critical": 90.0}

def analyze_connection_pressure(report, thresholds=None):
    if not isinstance(report, dict):
        return {"status": "INSUFFICIENT_DATA", "missing_evidence": ["report"]}
    rows = report.get("connections")
    config = report.get("config")
    maximum = None
    if isinstance(config, list):
        for row in config:
            if isinstance(row, dict) and row.get("name") == "max_connections":
                try:
                    maximum = int(row.get("setting"))
                except (TypeError, ValueError):
                    pass
                break
    missing = []
    if not isinstance(rows, list):
        missing.append("connections")
    if maximum is None or maximum <= 0:
        missing.append("config.max_connections")
    if missing:
        return {"status": "INSUFFICIENT_DATA", "missing_evidence": missing,
                "recommendation": "Collect connection counts and max_connections before assessing pressure."}
    counts = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("connection_count", row.get("count"))
        try:
            count = int(raw)
        except (TypeError, ValueError):
            continue
        if count < 0:
            continue
        state = str(row.get("state") or "unknown").lower()
        counts[state] = counts.get(state, 0) + count
    total = sum(counts.values())
    utilization = total / maximum * 100
    limits = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        limits.update(thresholds)
    if not (0 <= limits["watch"] <= limits["high"] <= limits["critical"] <= 100):
        raise ValueError("Thresholds must satisfy 0 <= watch <= high <= critical <= 100.")
    level = ("CRITICAL" if utilization >= limits["critical"] else
             "HIGH" if utilization >= limits["high"] else
             "WATCH" if utilization >= limits["watch"] else "NORMAL")
    idle_tx = counts.get("idle in transaction", 0) + counts.get("idle in transaction (aborted)", 0)
    recommendations = {
        "NORMAL": ["No connection-capacity change is indicated by the collected evidence."],
        "WATCH": ["Monitor connection growth and identify application pools or clients creating connections."],
        "HIGH": ["Investigate connection sources and application pool limits before changing max_connections."],
        "CRITICAL": ["Investigate connection sources and pooling urgently; do not terminate sessions automatically."]
    }[level]
    if idle_tx:
        recommendations.append("Review idle-in-transaction sessions and ownership; do not terminate them automatically.")
    if counts.get("idle", 0):
        recommendations.append("Review idle connection patterns; idle sessions are not automatically harmful.")
    return {
        "status": "ANALYZED", "classification": level, "max_connections": maximum,
        "total_connections": total, "nominal_remaining_capacity": max(maximum-total, 0),
        "utilization_percent": round(utilization, 2), "connection_states": counts,
        "active_connections": counts.get("active", 0), "idle_connections": counts.get("idle", 0),
        "idle_in_transaction_connections": idle_tx, "thresholds_percent": limits,
        "recommendations": recommendations,
        "safety": "Read-only analysis. No sessions are terminated and no configuration is changed. Reserved slots may reduce capacity available to ordinary roles."
    }
