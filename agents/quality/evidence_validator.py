"""Evidence-aware checks for PostgreSQL DBA report claims."""
from __future__ import annotations

def _section_succeeded(report: dict, name: str) -> bool:
    # Successful collect_report sections are lists, even when they contain no rows.
    return isinstance(report.get(name), list)

def _setting(report: dict, name: str):
    rows = report.get("config")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and row.get("name") == name:
            return str(row.get("setting", "")).lower()
    return None

def validate_evidence(report: dict, answer: str) -> dict:
    if not isinstance(report, dict) or not isinstance(answer, str) or not answer.strip():
        return {"passed": False, "status": "INVALID_INPUT", "findings": [], "unverified": []}
    text = " ".join(answer.lower().split())
    findings, unverified = [], []
    activity_checked = any(_section_succeeded(report, key) for key in ("connections", "connection_details", "transactions", "blocking"))
    broad_access_phrases = (
        'cannot access detailed cumulative statistics',
        'cannot access detailed statistics',
        'detailed cumulative statistics are inaccessible',
        'detailed statistics are inaccessible',
        'statistics views are inaccessible',
        'statistics views are not accessible',
    )
    broad_access_claim = any(phrase in text for phrase in broad_access_phrases) or ("detailed cumulative statistics including" in text and ("inaccessible" in text or "cannot access" in text))
    if broad_access_claim and 'pg_stat_activity' in text and activity_checked:
        findings.append({'rule_id': 'EV006', 'severity': 'HIGH', 'message': 'The report broadly claims detailed statistics or activity are inaccessible, but the live activity diagnostic succeeded.'})
    if broad_access_claim and 'pg_stat_user_tables' in text and _section_succeeded(report, 'tables'):
        findings.append({'rule_id': 'EV007', 'severity': 'HIGH', 'message': 'The report broadly claims detailed statistics or table statistics are inaccessible, but the live table-statistics diagnostic succeeded.'})
    if broad_access_claim and 'pg_stat_database' in text and _section_succeeded(report, 'database_stats'):
        findings.append({'rule_id': 'EV008', 'severity': 'HIGH', 'message': 'The report claims database statistics are unavailable or incomplete, but the live database_stats diagnostic succeeded.'})
    if "pg_stat_activity is inaccessible" in text or "cannot access pg_stat_activity" in text:
        if activity_checked:
            findings.append({"rule_id": "EV001", "severity": "HIGH", "message": "The live report successfully queried pg_stat_activity; the blanket inaccessibility claim conflicts with this evidence."})
        else:
            unverified.append("pg_stat_activity accessibility was not established by the available diagnostic sections.")
    if "pg_stat_user_tables is inaccessible" in text or "cannot access pg_stat_user_tables" in text:
        if _section_succeeded(report, "tables"):
            findings.append({"rule_id": "EV002", "severity": "HIGH", "message": "The live report successfully queried pg_stat_user_tables; the blanket inaccessibility claim conflicts with this evidence."})
        else:
            unverified.append("pg_stat_user_tables accessibility was not established by the available diagnostic sections.")
    if "track_activities defaults to off" in text or "track_activities is off by default" in text or "track_activities default is off" in text:
        findings.append({"rule_id": "EV003", "severity": "HIGH", "message": "PostgreSQL track_activities defaults to on; check the live setting for this server."})
    live_track = _setting(report, "track_activities")
    if live_track == "on" and ("track_activities is disabled" in text or "track_activities is off" in text):
        findings.append({"rule_id": "EV004", "severity": "HIGH", "message": "The collected pg_settings evidence reports track_activities=on, contradicting the disabled claim."})
    elif live_track is None and any(phrase in text for phrase in ("track_activities is enabled", "track_activities is disabled", "track_activities is on", "track_activities is off")):
        unverified.append("The report makes a claim about the live track_activities setting, but this diagnostic report does not contain that setting.")
    permissions = report.get("permissions")
    if isinstance(permissions, list) and permissions and isinstance(permissions[0], dict):
        if permissions[0].get("has_pg_monitor") is False and ("pg_stat_activity is inaccessible because" in text or "inaccessible due to missing pg_monitor" in text or "cannot access pg_stat_activity because" in text):
            if activity_checked:
                findings.append({"rule_id": "EV005", "severity": "HIGH", "message": "Missing pg_monitor membership does not establish view inaccessibility; the live activity diagnostic succeeded."})
            else:
                unverified.append("The report infers activity-view access from pg_monitor membership without a successful activity-view check.")
    status = "REVIEW_REQUIRED" if findings else ("UNVERIFIED_CLAIMS" if unverified else "NO_EVIDENCE_CONTRADICTIONS")
    return {"passed": not findings, "status": status, "findings": findings, "unverified": unverified}
