"""Fixed schema, explicit transactions, and short-lived SQLite connections."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from config.settings import load_settings
from memory.models import SCHEMA_VERSION
from security.validator import ValidationError, validate_local_path

SCHEMA = (
    "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)",
    """CREATE TABLE memories (
        id TEXT PRIMARY KEY NOT NULL, category TEXT NOT NULL
        CHECK(category IN ('preference','fact','project','instruction','note')),
        content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 1024),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT,
        source TEXT NOT NULL CHECK(source='user_approved'), tags TEXT NOT NULL)""",
    "CREATE INDEX memories_recency ON memories(updated_at DESC, id)",
    "CREATE INDEX memories_expiration ON memories(expires_at)",
)

def get_default_db_path():
    return load_settings().data_dir / "memory.sqlite3"

def database_error(error):
    code = getattr(error, "sqlite_errorcode", 0) & 255
    if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
        return ValidationError("MEMORY_DATABASE_CORRUPT")
    if isinstance(error, sqlite3.IntegrityError):
        return ValidationError("MEMORY_CONFLICT")
    if code in (sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_READONLY):
        return ValidationError("MEMORY_DATABASE_UNAVAILABLE")
    return ValidationError("MEMORY_STORAGE_FAILED")

@contextmanager
def connection(path, *, initialize=False, write=False):
    con = None
    try:
        path = validate_local_path(Path(path), must_exist=not initialize)
        # Only trusted initialization can create the database.
        con = sqlite3.connect(path.as_uri() + ("?mode=rwc" if initialize else "?mode=rw"),
                              uri=True, timeout=5, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA synchronous=FULL")
        con.execute("PRAGMA trusted_schema=OFF")
        if initialize:
            con.execute("PRAGMA journal_mode=WAL")
        if not write:
            con.execute("PRAGMA query_only=ON")
        con.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        if not initialize:
            check_schema(con)
        yield con
        con.commit()
    except sqlite3.Error as error:
        raise database_error(error) from None
    except (OSError, ValueError) as error:
        if isinstance(error, ValidationError) and error.error_id.startswith(("MEMORY_", "SECRET_")):
            raise
        raise ValidationError("MEMORY_DATABASE_UNAVAILABLE") from None
    finally:
        if con is not None:
            con.close()  # Also rolls back any uncommitted transaction.

def check_schema(con):
    try:
        versions = [row[0] for row in con.execute("SELECT version FROM schema_migrations ORDER BY version")]
    except sqlite3.OperationalError:
        raise ValidationError("MEMORY_SCHEMA_UNSUPPORTED") from None
    if versions != [SCHEMA_VERSION]:
        raise ValidationError("MEMORY_SCHEMA_UNSUPPORTED")
    columns = [row[1] for row in con.execute("PRAGMA table_info(memories)")]
    if columns != ["id", "category", "content", "created_at", "updated_at", "expires_at", "source", "tags"]:
        raise ValidationError("MEMORY_SCHEMA_UNSUPPORTED")

def initialize_database(path, now):
    """Trusted setup only; never reset unknown databases.

    Future migrations require fixed numbered statements, a backup, and
    compatibility tests. Version changes belong to the same transaction.
    """
    with connection(path, initialize=True, write=True) as con:
        tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if not tables:
            for statement in SCHEMA:
                con.execute(statement)
            con.execute("INSERT INTO schema_migrations VALUES (?, ?)", (SCHEMA_VERSION, now))
        check_schema(con)
