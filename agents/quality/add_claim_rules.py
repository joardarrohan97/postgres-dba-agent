from pathlib import Path
p = Path("agents/quality/claim_checker.py")
s = p.read_text()
marker = "    findings = []"
assert s.count(marker) == 1, "Unexpected checker structure"
addition = """        "PGF006": (("without pg_monitor membership, pg_stat_activity is inaccessible", "missing pg_monitor membership makes pg_stat_activity inaccessible"), "HIGH", "Missing pg_monitor membership alone does not prove pg_stat_activity is inaccessible. Check actual access."),
        "PGF007": (("track_activities defaults to off", "track_activities is off by default"), "HIGH", "PostgreSQL track_activities defaults to on; inspect the live setting."),
        "PGF008": (("without pg_monitor membership, pg_stat_user_tables is inaccessible", "missing pg_monitor membership makes pg_stat_user_tables inaccessible"), "HIGH", "Check actual table-statistics view access rather than inferring denial from role membership."),
        "PGF009": (("likely missing indexes", "missing indexes are the most likely cause", "high probability of missing indexes"), "MEDIUM", "Do not rank missing indexes without query-specific execution-plan or workload evidence."),
        "PGF010": (("grant pg_monitor and pg_read_all_stats", "grant pg_read_all_stats and pg_monitor"), "MEDIUM", "pg_monitor includes pg_read_all_stats; recommending both memberships is redundant."),
"""
p.write_text(s.replace(marker, addition + marker))
print("Added five rules.")