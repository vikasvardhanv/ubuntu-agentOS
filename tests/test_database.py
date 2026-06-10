import sqlite3
import unittest
from contextlib import closing
from pathlib import Path


class DatabaseSchemaTests(unittest.TestCase):
    def test_schema_initializes(self):
        schema = Path("db/migrations/001_initial.sql").read_text(encoding="utf-8")
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.executescript(schema)
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertTrue({"agents", "actions", "approvals", "memories", "audit_events"} <= tables)
