"""Phrase-based DBA report review aid; not a complete fact verifier."""
def validate_report(report):
    if not isinstance(report, str) or not report.strip():
        return {"passed": False, "status": "INVALID_INPUT", "findings": []}
    text = " ".join(report.lower().split())
    rules = {
        "PGF001": (("pg_monitor is an extension", "pg_read_all_stats is an extension", "pg_monitor and pg_read_all_stats are extensions"), "HIGH", "These are predefined PostgreSQL roles, not extensions."),
        "PGF002": (("explain analyze does not execute", "explain analyze doesn't execute", "explain analyze never executes"), "HIGH", "EXPLAIN ANALYZE executes the statement being analyzed."),
        "PGF003": (("a superuser is always required", "superuser is always required", "a superuser is required for explain", "superuser is required for explain"), "HIGH", "Superuser is not universally required; requirements depend on the statement and referenced objects."),
        "PGF004": (("pg_stat_activity is inaccessible", "pg_stat_user_tables is inaccessible", "pg_statio_user_tables is inaccessible", "pg_settings is inaccessible", "requires superuser to access pg_stat_activity"), "MEDIUM", "Do not claim an entire view is inaccessible without checking actual permissions and columns."),
        "PGF005": (("grant superuser", "grant superuser privileges", "give dba_monitor superuser", "alter role dba_monitor superuser"), "HIGH", "Do not recommend granting superuser as a diagnostic workaround."),
    }
    findings = []
    for rule_id, (phrases, severity, message) in rules.items():
        for phrase in phrases:
            start = 0
            while (index := text.find(phrase, start)) >= 0:
                findings.append({"rule_id": rule_id, "severity": severity, "excerpt": text[max(0,index-80):index+len(phrase)+80], "message": message})
                start = index + len(phrase)
    return {"passed": not findings, "status": "REVIEW_REQUIRED" if findings else "NO_KNOWN_PATTERN_FLAGS", "findings": findings}
