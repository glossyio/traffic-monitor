"""tm-control's own database (users, claim state, EULA record, jobs, audit), versioned by numbered migrations.

The device's StateDirectory holds it as state.sqlite. MIGRATIONS[0] is migration 1; PRAGMA user_version records
how many have been applied. Never edit a migration that has shipped; append a new one.
"""

import sqlite3
from pathlib import Path

MIGRATIONS = [
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,  -- never reused: an old cookie or audit row never names a new user
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin', 'viewer')),
        session_epoch INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    -- setup_code_hash, claimed_at
    CREATE TABLE device (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE eula_acceptances (
        id INTEGER PRIMARY KEY,
        version TEXT NOT NULL,
        accepted_at TEXT NOT NULL,
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL  -- kept as device history when the user goes
    );
    CREATE TABLE jobs (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        requested_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        requested_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL
    );
    CREATE TABLE audit (id INTEGER PRIMARY KEY, at TEXT NOT NULL, user_id INTEGER, action TEXT NOT NULL, detail TEXT);
    """,
]


def _statements(script):
    """Split a migration into single statements, so they can all run inside one transaction."""
    *pieces, rest = script.split(";")
    statement = ""
    for piece in pieces:
        statement += piece + ";"
        if sqlite3.complete_statement(statement):  # a ; inside a string or trigger body doesn't end it
            yield statement
            statement = ""
    if (statement + rest).strip():
        yield statement + rest  # an unterminated statement: let SQLite report it


class State:
    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        """A new connection. It may move between threads (FastAPI runs a dependency and its endpoint in
        different worker threads), but two threads must never use it at once."""
        con = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout = 5000")
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def version(self) -> int:
        con = self.connect()
        try:
            return con.execute("PRAGMA user_version").fetchone()[0]
        finally:
            con.close()

    def migrate(self) -> int:
        """Apply the pending migrations, each with its user_version in one transaction; return the new version.

        A database newer than this code (after a downgrade) is left as it is.
        """
        con = self.connect()
        con.isolation_level = None  # transactions are explicit below
        try:
            while True:
                con.execute("BEGIN IMMEDIATE")  # take the write lock before reading the version
                try:
                    version = con.execute("PRAGMA user_version").fetchone()[0]
                    if version >= len(MIGRATIONS):
                        con.execute("COMMIT")
                        return version
                    for statement in _statements(MIGRATIONS[version]):
                        con.execute(statement)
                    con.execute(f"PRAGMA user_version = {version + 1}")
                    con.execute("COMMIT")
                except BaseException:
                    con.execute("ROLLBACK")
                    raise
        finally:
            con.close()
