"""Validated fixed-query CRUD; each write holds an IMMEDIATE transaction."""
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.memory_settings import MemorySettings
from memory.database import connection, get_default_db_path, initialize_database
from memory.models import MemoryRecord
from memory.retrieval import bounded, rank
from memory.validation import (text, validate_category, validate_expiration, validate_limit,
    validate_memory_content, validate_memory_id, validate_tags, validate_timestamp)
from security.validator import ValidationError

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")

def _record(row):
    try:
        tags = json.loads(row["tags"])
        if type(tags) is not list or any(type(tag) is not str for tag in tags):
            raise ValueError()
        record = MemoryRecord(
            validate_memory_id(row["id"]), validate_category(row["category"]),
            validate_memory_content(row["content"]), validate_timestamp(row["created_at"]),
            validate_timestamp(row["updated_at"]),
            validate_expiration(row["expires_at"] or ""), row["source"],
            validate_tags(",".join(tags)))
        if record.source != "user_approved":
            raise ValueError()
        return record
    except (ValueError, TypeError, KeyError):
        raise ValidationError("MEMORY_DATABASE_CORRUPT") from None

class MemoryRepository:
    def __init__(self, db_path=None, *, settings=None, clock=utc_now):
        self.path = Path(db_path) if db_path is not None else get_default_db_path()
        self.settings = settings if settings is not None else MemorySettings()
        self.clock = clock

    def _now(self):
        return validate_timestamp(self.clock())

    def initialize(self):
        initialize_database(self.path, self._now())

    def count(self):
        with connection(self.path) as con:
            return con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def create(self, content, category="note", tags="", expires_at=""):
        content = validate_memory_content(content)
        category = validate_category(category)
        tags = validate_tags(tags)
        expiration = validate_expiration(expires_at)
        now = self._now()
        if expiration is not None and expiration <= now:
            raise ValidationError("MEMORY_INVALID_RECORD")
        with connection(self.path, write=True) as con:
            if con.execute("SELECT COUNT(*) FROM memories").fetchone()[0] >= self.settings.max_records:
                raise ValidationError("MEMORY_CAPACITY_EXCEEDED")
            record = MemoryRecord(secrets.token_urlsafe(16), category, content, now, now,
                                  expiration, "user_approved", tags)
            con.execute("INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (record.id, category, content, now, now, expiration,
                         record.source, json.dumps(tags)))
        return record

    def get(self, memory_id):
        memory_id = validate_memory_id(memory_id)
        with connection(self.path) as con:
            row = con.execute(
                "SELECT * FROM memories WHERE id=? AND (expires_at IS NULL OR expires_at>?)",
                (memory_id, self._now())).fetchone()
            if row is None:
                raise ValidationError("MEMORY_RECORD_NOT_FOUND")
            return _record(row)

    def _existing(self, con, memory_id, expected_updated_at, now):
        row = con.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        if row is None or (row["expires_at"] is not None and row["expires_at"] <= now):
            raise ValidationError("MEMORY_RECORD_NOT_FOUND")
        record = _record(row)
        if record.updated_at != expected_updated_at:
            raise ValidationError("MEMORY_CONFLICT")
        return record

    def update(self, memory_id, expected_updated_at, content, category, tags="", expires_at=""):
        memory_id = validate_memory_id(memory_id)
        expected = validate_timestamp(expected_updated_at)
        content = validate_memory_content(content)
        category = validate_category(category)
        tags = validate_tags(tags)
        expiration = validate_expiration(expires_at)
        now = self._now()
        if expiration is not None and expiration <= now:
            raise ValidationError("MEMORY_INVALID_RECORD")
        with connection(self.path, write=True) as con:
            old = self._existing(con, memory_id, expected, now)
            # A version must change even if the clock repeats or moves backwards.
            updated = max(now, (datetime.fromisoformat(old.updated_at) +
                               timedelta(microseconds=1)).isoformat(timespec="microseconds"))
            con.execute(
                "UPDATE memories SET content=?, category=?, tags=?, expires_at=?, updated_at=? WHERE id=?",
                (content, category, json.dumps(tags), expiration, updated, memory_id))
            return MemoryRecord(memory_id, category, content, old.created_at, updated,
                                expiration, old.source, tags)

    def delete(self, memory_id, expected_updated_at, category, expected_content):
        memory_id = validate_memory_id(memory_id)
        expected = validate_timestamp(expected_updated_at)
        category = validate_category(category)
        content = validate_memory_content(expected_content)
        with connection(self.path, write=True) as con:
            old = self._existing(con, memory_id, expected, self._now())
            if old.category != category or old.content != content:
                raise ValidationError("MEMORY_CONFLICT")
            con.execute("DELETE FROM memories WHERE id=?", (memory_id,))

    def _active(self, category):
        category = validate_category(category, optional=True)
        with connection(self.path) as con:
            # Never scan more than the configured hard cap. A DB larger than its
            # current configuration fails visibly instead of partial ranking.
            if con.execute("SELECT COUNT(*) FROM memories").fetchone()[0] > self.settings.max_records:
                raise ValidationError("MEMORY_CAPACITY_EXCEEDED")
            rows = con.execute(
                """SELECT * FROM memories
                   WHERE (expires_at IS NULL OR expires_at>?) AND (?='' OR category=?)
                   ORDER BY updated_at DESC, id DESC LIMIT ?""",
                (self._now(), category, category, self.settings.max_records)).fetchall()
            return [_record(row) for row in rows]

    def list(self, category="", limit=10):
        validate_limit(limit)
        return bounded(self._active(category), min(limit, self.settings.max_results),
                       self.settings.max_result_bytes)

    def search(self, query, category="", limit=10):
        query = text(query, 256)
        validate_limit(limit)
        return bounded(rank(self._active(category), query), min(limit, self.settings.max_results),
                       self.settings.max_result_bytes)

    def retrieve(self, memory_id):
        return bounded([self.get(memory_id)], 1, self.settings.max_result_bytes)

    def cleanup_expired(self):
        """Trusted maintenance; never called by retrieval or registered as a tool."""
        with connection(self.path, write=True) as con:
            return con.execute(
                "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at<=?",
                (self._now(),)).rowcount
