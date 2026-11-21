import unittest
from dba_agent.analysis import analyze_plan, build_findings


class AnalysisTests(unittest.TestCase):
    def test_missing_planner_stats_is_reported(self):
        report = {"tables": [{"schemaname": "public", "table_name": "t", "planner_row_estimate": -1,
                              "estimated_live_rows": 3, "estimated_dead_rows": 0}]}
        findings = build_findings(report)
        self.assertTrue(any("Planner statistics missing" in x["title"] for x in findings))

    def test_tiny_static_table_no_vacuum_warning(self):
        report = {"tables": [{"schemaname": "public", "table_name": "tiny", "planner_row_estimate": 5,
                              "estimated_live_rows": 5, "estimated_dead_rows": 0,
                              "last_analyze": None, "last_autoanalyze": None,
                              "n_mod_since_analyze": 0}]}
        findings = build_findings(report)
        self.assertFalse(any("vacuum timestamp" in x["title"].lower() for x in findings))
        self.assertFalse(any("No recorded ANALYZE" in x["title"] for x in findings))


    def test_blocking_finding_includes_blocker_context(self):
        from datetime import timedelta
        report = {"blocking": [{
            "blocked_pid": 9069, "blocked_user": "postgres", "blocker_pid": 9056,
            "wait_event_type": "Lock", "wait_event": "transactionid",
            "blocker_state": "idle in transaction",
            "blocked_query_age": timedelta(seconds=12),
            "blocker_transaction_age": timedelta(seconds=40),
            "blocker_state_age": timedelta(seconds=35),
            "blocker_upstream_pids": [],
            "waiting_locks": [{"locktype": "transactionid", "mode": "ShareLock"}],
        }]}
        findings = build_findings(report)
        blocking = next(x for x in findings if x["category"] == "locking")
        self.assertEqual(blocking["severity"], "CRITICAL")
        self.assertIn("9056", blocking["evidence"])
        self.assertIn("idle in transaction", blocking["evidence"])
        self.assertIn("transactionid", blocking["evidence"])
        self.assertIn("never terminate automatically", blocking["recommendation"])

    def test_plan_estimation_error(self):
        doc = [{"Plan": {"Node Type": "Seq Scan", "Relation Name": "t", "Plan Rows": 10,
                         "Actual Rows": 200, "Actual Loops": 1, "Plans": []},
                "Planning Time": 0.1, "Execution Time": 2.0}]
        result = analyze_plan(doc)
        self.assertEqual(result["root_node"], "Seq Scan")
        self.assertTrue(any("cardinality" in x["title"].lower() for x in result["observations"]))


if __name__ == "__main__":
    unittest.main()
