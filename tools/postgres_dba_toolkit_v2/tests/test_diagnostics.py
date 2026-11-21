import sys
import types
import unittest

# The diagnostic collector only needs the psycopg exception hierarchy for this mocked test.
class FakePsycopgError(Exception):
    pass

class FakeUndefinedTable(FakePsycopgError):
    pass

fake_psycopg = types.ModuleType("psycopg")
fake_psycopg.Error = FakePsycopgError
fake_psycopg.errors = types.SimpleNamespace(UndefinedTable=FakeUndefinedTable)
sys.modules.setdefault("psycopg", fake_psycopg)

from dba_agent.diagnostics import collect_report

class FakeCursor:
    def __init__(self, rows): self.rows = rows
    def fetchall(self): return self.rows

class FakeConnection:
    def __init__(self): self.commands = []
    def execute(self, sql):
        self.commands.append(sql)
        if sql.strip().startswith("SELECT current_database"):
            return FakeCursor([{"database_name": "test"}])
        if sql.strip().startswith("SELECT current_user"):
            return FakeCursor([{"connected_user": "tester", "is_superuser": False,
                                "has_pg_read_all_stats": False, "has_pg_monitor": False,
                                "can_connect": True}])
        if sql.strip().startswith(("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT")):
            return FakeCursor([])
        raise FakeUndefinedTable("relation does not exist")

class DiagnosticsTests(unittest.TestCase):
    def test_optional_query_error_is_isolated_by_savepoint(self):
        fake = FakeConnection()
        report = collect_report(fake, "all")
        self.assertIn("health", report)
        self.assertIn("statements", report)
        self.assertIsInstance(report["statements"], dict)
        self.assertTrue(any(cmd.startswith("ROLLBACK TO SAVEPOINT") for cmd in fake.commands))
        self.assertTrue(any("Monitoring visibility may be limited" in f["title"] for f in report["findings"]))

if __name__ == "__main__":
    unittest.main()
