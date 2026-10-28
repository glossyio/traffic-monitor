import sqlite3

import pytest

from tm_control.core.state import MIGRATIONS, State

NOW = "2026-10-27T12:00:00+00:00"


def _migrated(tmp_path):
    state = State(tmp_path / "state.sqlite")
    state.migrate()
    return state


def _add_user(con, username, role="admin"):
    with con:
        con.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (username, "placeholder-hash", role, NOW),
        )


def test_fresh_database_gets_every_migration(tmp_path):
    state = State(tmp_path / "state.sqlite")
    assert state.version() == 0
    assert state.migrate() == len(MIGRATIONS) == state.version()


def test_migrate_twice_changes_nothing(tmp_path):
    state = _migrated(tmp_path)
    _add_user(state.connect(), "admin")
    assert state.migrate() == len(MIGRATIONS)
    assert state.connect().execute("SELECT count(*) FROM users").fetchone()[0] == 1


def test_migration_one_creates_the_tables(tmp_path):
    con = _migrated(tmp_path).connect()
    tables = {row["name"] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"users", "device", "eula_acceptances", "jobs", "audit"} <= tables


def test_failed_migration_leaves_the_version_and_tables_alone(tmp_path, monkeypatch):
    monkeypatch.setattr("tm_control.core.state.MIGRATIONS", ["CREATE TABLE t (a INTEGER); SELECT * FROM missing;"])
    state = State(tmp_path / "state.sqlite")
    with pytest.raises(sqlite3.OperationalError):
        state.migrate()
    assert state.version() == 0
    assert state.connect().execute("SELECT count(*) FROM sqlite_master WHERE name = 't'").fetchone()[0] == 0


def test_connection_uses_wal_and_foreign_keys(tmp_path):
    con = State(tmp_path / "state.sqlite").connect()
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert con.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert con.row_factory is sqlite3.Row


def test_users_role_is_constrained(tmp_path):
    con = _migrated(tmp_path).connect()
    with pytest.raises(sqlite3.IntegrityError):
        _add_user(con, "admin", role="root")


def test_usernames_are_unique_ignoring_case(tmp_path):
    con = _migrated(tmp_path).connect()
    _add_user(con, "admin")
    with pytest.raises(sqlite3.IntegrityError):
        _add_user(con, "Admin")


def test_jobs_refer_to_existing_users(tmp_path):
    con = _migrated(tmp_path).connect()
    with pytest.raises(sqlite3.IntegrityError), con:
        con.execute(
            "INSERT INTO jobs (id, name, requested_by, requested_at, status) VALUES ('j1', 'x', 42, ?, 'queued')",
            (NOW,),
        )
