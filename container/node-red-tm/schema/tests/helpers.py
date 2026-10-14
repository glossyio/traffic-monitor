"""Shared paths and helpers for the tmdb schema tests. All test data is synthetic."""

import sqlite3
import sys
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCHEMA_DIR))

import tmdb_migrate  # noqa: E402

RUNNER = SCHEMA_DIR / "tmdb_migrate.py"
LEGACY_SCHEMA = Path(__file__).resolve().parent / "fixtures" / "legacy_v0_schema.sql"
FLOWS_JSON = SCHEMA_DIR.parent / "data" / "flows.json"

# The tables 0001_baseline.sql defines, listed by hand.
BASELINE_TABLES = {
    "airquality",
    "comments",
    "deployment",
    "events",
    "plate_recognizer",
    "radar_dov",
    "radar_oc_payload",
    "radar_raw_speed_magnitude",
    "radar_raw_speed_magnitude_single",
    "radar_timed_speed_counts",
}


def migrate(*args):
    """Run the runner's command line in-process and return its exit code."""
    return tmdb_migrate.main([str(arg) for arg in args])


def create_db(path, sql, user_version=0):
    con = sqlite3.connect(path)
    con.executescript(sql)
    con.execute(f"PRAGMA user_version = {user_version}")
    con.commit()
    con.close()


def query(path, sql):
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def user_version(path):
    return query(path, "PRAGMA user_version")[0][0]


def tables(path):
    return {name for (name,) in query(path, "SELECT name FROM sqlite_master WHERE type = 'table'")}


def columns(path, table):
    return [row[1] for row in query(path, f"PRAGMA table_info({table})")]


def files_in(directory):
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []
