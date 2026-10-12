"""Stage 7 repository tests use only isolated temporary databases."""
import json
import os
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from config.memory_settings import MemorySettings, load_memory_settings
from config.settings import ConfigurationError
from memory.database import connection
from memory.repository import MemoryRepository
from security.validator import ValidationError

NOW = "2026-10-08T12:00:00.000000+00:00"

class MemoryRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "memory.sqlite3"
        self.now = NOW
        self.repo = MemoryRepository(self.path, clock=lambda: self.now)
        self.repo.initialize()

    def assert_code(self, code, operation, *args, **kwargs):
        with self.assertRaises(ValidationError) as result:
            operation(*args, **kwargs)
        self.assertEqual(result.exception.error_id, code)

    def test_restart_persistence_and_schema(self):
        record = self.repo.create("Concise explanations", "preference", "style,brief")
        reopened = MemoryRepository(self.path)
        reopened.initialize()
        self.assertEqual(reopened.get(record.id), record)
        self.assertEqual(record.source, "user_approved")
        self.assertNotIn(record.content, repr(record))
        with connection(self.path) as con:
            self.assertEqual(con.execute("SELECT version FROM schema_migrations").fetchone()[0], 1)
            self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(con.execute("PRAGMA synchronous").fetchone()[0], 2)
            self.assertEqual(con.execute("PRAGMA busy_timeout").fetchone()[0], 5000)

    def test_crud_and_monotonic_version(self):
        first = self.repo.create("Brief", "preference", "style")
        updated = self.repo.update(first.id, first.updated_at, "Detailed", "note")
        self.assertGreater(updated.updated_at, first.updated_at)
        self.assertEqual(updated.created_at, first.created_at)
        self.assertEqual(updated.tags, ())
        self.assertEqual(self.repo.get(first.id), updated)
        self.repo.delete(updated.id, updated.updated_at, updated.category, updated.content)
        self.assert_code("MEMORY_RECORD_NOT_FOUND", self.repo.get, updated.id)
        self.assertEqual(self.repo.search("Detailed")["memories"], [])

    def test_approved_content_whitespace_is_preserved_exactly(self):
        record = self.repo.create("  Exact reviewed text.  ")
        self.assertEqual(self.repo.get(record.id).content, "  Exact reviewed text.  ")

    def test_stale_update_and_delete_are_conflicts(self):
        first = self.repo.create("First")
        updated = self.repo.update(first.id, first.updated_at, "Second", "note")
        self.assert_code("MEMORY_CONFLICT", self.repo.update, first.id, first.updated_at, "Third", "note")
        self.assert_code("MEMORY_CONFLICT", self.repo.delete, first.id, first.updated_at, "note", "First")
        self.assert_code("MEMORY_CONFLICT", self.repo.delete, first.id, updated.updated_at, "note", "Wrong")
        self.assertEqual(self.repo.get(first.id).content, "Second")

    def test_fixed_parameterized_queries_preserve_sql_text_as_data(self):
        value = "x'); DROP TABLE memories; --"
        record = self.repo.create(value)
        self.assertEqual(self.repo.get(record.id).content, value)
        self.assertEqual(self.repo.search(value)["memories"][0]["id"], record.id)
        self.assertEqual(self.repo.count(), 1)
        self.assert_code("MEMORY_INVALID_RECORD", self.repo.get, "' OR 1=1 --")
        self.assertEqual(self.repo.search("%_")["memories"], [])

    def test_invalid_content_category_tags_id_query_limit(self):
        for value in ("", " ", "x" * 1025, "a\nb", "\u202esecret", "\ud800", 2, {}, None):
            self.assert_code("MEMORY_INVALID_RECORD", self.repo.create, value)
        for category in ("unknown", [], None):
            self.assert_code("MEMORY_INVALID_RECORD", self.repo.create, "safe", category)
        for tags in ("a," * 130, "x" * 33, "a b", ",".join(str(x) for x in range(9)), []):
            self.assert_code("MEMORY_INVALID_RECORD", self.repo.create, "safe", tags=tags)
        for query in ("", " " * 2, "x" * 257, None):
            self.assert_code("MEMORY_INVALID_RECORD", self.repo.search, query)
        for limit in (0, 51, True, "1"):
            self.assert_code("MEMORY_INVALID_RECORD", self.repo.list, limit=limit)
        self.assertEqual(self.repo.count(), 0)

    def test_obvious_secrets_and_configured_key_rejected(self):
        examples = ("password: abc", "my password is abc", "api_key=abc", "Bearer abc",
                    "sk-" + "a" * 30, "AIza" + "a" * 35, "ghp_" + "a" * 36,
                    "-----BEGIN RSA PRIVATE KEY-----", "https://user:pass@example.com")
        for value in examples:
            self.assert_code("SECRET_DETECTED", self.repo.create, value)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "distinctive-test-credential"}):
            self.assert_code("SECRET_DETECTED", self.repo.create, "key distinctive-test-credential")
            self.assert_code("SECRET_DETECTED", self.repo.create, "safe", tags="distinctive-test-credential")
        record = self.repo.create("safe")
        self.assert_code("SECRET_DETECTED", self.repo.update, record.id, record.updated_at,
                         "password: abc", "note")
        self.assertEqual(self.repo.get(record.id).content, "safe")

    def test_exact_phrase_token_ranking_category_and_recency(self):
        first = self.repo.create("concise technical explanations", "preference")
        self.now = "2026-10-08T13:00:00.000000+00:00"
        self.repo.create("technical notes concise", "note")
        result = self.repo.search("concise technical")
        self.assertEqual(result["memories"][0]["id"], first.id)
        self.assertEqual(len(result["memories"]), 2)
        self.assertEqual(len(self.repo.search("concise", category="preference")["memories"]), 1)
        self.assertEqual(self.repo.search("unmatched")["memories"], [])
        self.assertEqual(self.repo.search("concise", limit=1)["memories"][0]["category"], "note")
        self.assertEqual(self.repo.search("concise"), self.repo.search("concise"))

    def test_configured_result_count_and_serialized_bytes(self):
        for _ in range(4):
            self.repo.create("\u00e9" * 1000)
        small = MemoryRepository(self.path, settings=MemorySettings(max_results=2, max_result_bytes=7500))
        result = small.list(limit=50)
        self.assertEqual(len(result["memories"]), 1)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=True).encode()), 7500)
        self.assertEqual(result["trust"], "untrusted_memory_data")
        tiny = MemoryRepository(self.path, settings=MemorySettings(max_result_bytes=512))
        result = tiny.retrieve(self.repo.list()["memories"][0]["id"])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["memories"], [])

    def test_capacity_counts_expired_until_trusted_cleanup(self):
        repo = MemoryRepository(self.path, settings=MemorySettings(max_records=1), clock=lambda: self.now)
        repo.create("one", expires_at="2026-10-08T13:00:00Z")
        self.now = "2026-10-08T14:00:00.000000+00:00"
        self.assert_code("MEMORY_CAPACITY_EXCEEDED", repo.create, "two")
        self.assertEqual(repo.cleanup_expired(), 1)
        repo.create("two")
        self.assertEqual(repo.count(), 1)

    def test_expiration_utc_read_only_filtering_and_clear(self):
        record = self.repo.create("expires", expires_at="2026-10-08T18:00:00+05:00")
        self.assertEqual(record.expires_at, "2026-10-08T13:00:00.000000+00:00")
        self.now = record.expires_at
        self.assert_code("MEMORY_RECORD_NOT_FOUND", self.repo.get, record.id)
        self.assertEqual(self.repo.list()["memories"], [])
        self.assertEqual(self.repo.search("expires")["memories"], [])
        self.assertEqual(self.repo.count(), 1)  # Reads must not delete.
        for expiration in ("2026-10-10", "2026-10-10T00:00:00", NOW):
            self.assert_code("MEMORY_INVALID_RECORD", self.repo.create, "bad", expires_at=expiration)
        self.now = NOW
        cleared = self.repo.update(record.id, record.updated_at, "safe", "note", expires_at="")
        self.assertIsNone(cleared.expires_at)

    def test_concurrent_capacity_is_atomic(self):
        repo = MemoryRepository(self.path, settings=MemorySettings(max_records=3))
        def create(index):
            try:
                repo.create("record " + str(index))
                return "ok"
            except ValidationError as error:
                return error.error_id
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(create, range(12)))
        self.assertEqual(results.count("ok"), 3)
        self.assertEqual(results.count("MEMORY_CAPACITY_EXCEEDED"), 9)
        self.assertEqual(repo.count(), 3)

    def test_concurrent_initialization_is_idempotent(self):
        path = Path(self.temp.name) / "other.sqlite3"
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: MemoryRepository(path).initialize(), range(4)))
        self.assertEqual(MemoryRepository(path).count(), 0)

    def test_transaction_rollback_and_connection_cleanup(self):
        record = self.repo.create("before")
        with self.assertRaises(RuntimeError):
            with connection(self.path, write=True) as con:
                con.execute("UPDATE memories SET content=? WHERE id=?", ("after", record.id))
                raise RuntimeError("do not log")
        self.assertEqual(self.repo.get(record.id).content, "before")
        self.repo.create("still usable")

    def test_duplicate_id_conflict_rolls_back(self):
        record = self.repo.create("before")
        with patch("memory.repository.secrets.token_urlsafe", return_value=record.id):
            self.assert_code("MEMORY_CONFLICT", self.repo.create, "after")
        self.assertEqual(self.repo.count(), 1)
        self.assertEqual(self.repo.get(record.id).content, "before")

    def test_missing_database_never_created_by_reads_or_writes(self):
        path = Path(self.temp.name) / "missing.sqlite3"
        repo = MemoryRepository(path)
        self.assert_code("MEMORY_DATABASE_UNAVAILABLE", repo.list)
        self.assert_code("MEMORY_DATABASE_UNAVAILABLE", repo.create, "safe")
        self.assertFalse(path.exists())

    def test_corruption_preserved_without_replacement(self):
        path = Path(self.temp.name) / "bad.sqlite3"
        original = b"not a SQLite database private contents"
        path.write_bytes(original)
        repo = MemoryRepository(path)
        self.assert_code("MEMORY_DATABASE_CORRUPT", repo.initialize)
        self.assertEqual(path.read_bytes(), original)

    def test_future_version_rejected_without_mutation(self):
        record = self.repo.create("preserved")
        with connection(self.path, write=True) as con:
            con.execute("UPDATE schema_migrations SET version=2")
        self.assert_code("MEMORY_SCHEMA_UNSUPPORTED", self.repo.initialize)
        self.assert_code("MEMORY_SCHEMA_UNSUPPORTED", self.repo.list)
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute("SELECT content FROM memories WHERE id=?", (record.id,)).fetchone()[0], "preserved")
        con.close()

    def test_unknown_schema_not_replaced(self):
        path = Path(self.temp.name) / "unknown.sqlite3"
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE unrelated(value TEXT)")
        con.close()
        self.assert_code("MEMORY_SCHEMA_UNSUPPORTED", MemoryRepository(path).initialize)

    def test_configuration_bounds(self):
        for key, value in (("JARVIS_MEMORY_MAX_RECORDS", "10001"),
                           ("JARVIS_MEMORY_MAX_RESULTS", "0"),
                           ("JARVIS_MEMORY_MAX_RESULT_BYTES", "12001"),
                           ("JARVIS_MEMORY_MAX_RECORDS", "bad")):
            with self.assertRaises(ConfigurationError):
                load_memory_settings({key: value})
        self.assertEqual(load_memory_settings({}).max_records, 1000)
