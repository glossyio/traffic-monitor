import collections
import re
import sqlite3
import subprocess
import sys

import pytest

from helpers import (
    BASELINE_TABLES,
    LEGACY_SCHEMA,
    RUNNER,
    columns,
    create_db,
    files_in,
    migrate,
    query,
    tables,
    tmdb_migrate,
    user_version,
)


def legacy_db(path):
    """A device database from before migrations: the old flows' tables, some rows, version 0."""
    create_db(path, LEGACY_SCHEMA.read_text())
    con = sqlite3.connect(path)
    con.executemany(
        "INSERT INTO events (id, camera, label, frame_time) VALUES (?, ?, ?, ?)",
        [("1721144705.617111-aaaaaa", "picam_h265", "car", 1721144705.6),
         ("1721144801.100000-bbbbbb", "picam_h265", "bicycle", 1721144801.1)],
    )
    con.execute("INSERT INTO radar_dov (time, direction, velocity, radarName) VALUES (1721144705.5, 'inbound', 24.5, 'TM_RADAR_SERIAL_PORT_00')")
    con.commit()
    con.close()


def output(capsys):
    captured = capsys.readouterr()
    return captured.out + captured.err


# --- applying migrations ---------------------------------------------------


def test_fresh_database_gets_baseline_tables_and_version(db_path):
    assert migrate("--db", db_path) == 0

    assert tables(db_path) == BASELINE_TABLES
    assert user_version(db_path) == 1
    assert files_in(db_path.parent / "backup") == []  # nothing to back up yet


def test_pre_migration_database_is_adopted_with_rows_intact(db_path, capsys):
    legacy_db(db_path)

    assert migrate("--db", db_path) == 0

    assert user_version(db_path) == 1
    assert query(db_path, "SELECT count(*) FROM events") == [(2,)]
    assert query(db_path, "SELECT count(*) FROM radar_dov") == [(1,)]
    assert "DRIFT" not in output(capsys)


def test_baseline_creates_the_same_columns_as_the_old_flows(db_path, tmp_path):
    legacy_path = tmp_path / "legacy.sqlite"
    create_db(legacy_path, LEGACY_SCHEMA.read_text())

    assert migrate("--db", db_path) == 0

    for table in BASELINE_TABLES:
        # cid, name, type, notnull, default, pk
        assert query(db_path, f"PRAGMA table_info({table})") == query(legacy_path, f"PRAGMA table_info({table})"), table


def test_up_to_date_database_is_not_migrated_again(db_path, make_migrations):
    # Without IF NOT EXISTS, a second application of 0001 would fail.
    migrations = make_migrations({"0001_create_a.sql": "CREATE TABLE a (x);"})

    assert migrate("--db", db_path, "--migrations", migrations) == 0
    assert migrate("--db", db_path, "--migrations", migrations) == 0

    assert user_version(db_path) == 1


def test_failed_migration_is_rolled_back_and_later_ones_are_skipped(db_path, make_migrations, capsys):
    migrations = make_migrations({
        "0001_create_a.sql": "CREATE TABLE a (x);",
        "0002_broken.sql": "CREATE TABLE b (x);\nINSERT INTO no_such_table VALUES (1);",
        "0003_create_c.sql": "CREATE TABLE c (x);",
    })

    assert migrate("--db", db_path, "--migrations", migrations) == 1

    assert user_version(db_path) == 1
    assert tables(db_path) == {"a"}  # b rolled back, c never attempted
    assert "0002_broken.sql" in output(capsys)


@pytest.mark.parametrize("files", [
    {"0001_a.sql": "CREATE TABLE a (x);", "0003_c.sql": "CREATE TABLE c (x);"},
    {"0001_a.sql": "CREATE TABLE a (x);", "0001_b.sql": "CREATE TABLE b (x);"},
    {"0001_a.sql": "CREATE TABLE a (x);", "add_b.sql": "CREATE TABLE b (x);"},
    {},
], ids=["gap", "duplicate number", "unnumbered file", "no migrations"])
def test_invalid_migration_set_is_rejected_before_touching_the_database(db_path, make_migrations, files):
    migrations = make_migrations(files)

    assert migrate("--db", db_path, "--migrations", migrations) == 2

    assert not db_path.exists()


def test_database_that_cannot_be_opened_is_reported_as_an_error(tmp_path, capsys):
    assert migrate("--db", tmp_path / "no_such_directory" / "tmdb.sqlite") == 1

    assert "ERROR" in output(capsys)


def test_database_newer_than_the_migrations_is_left_unchanged(db_path):
    create_db(db_path, "CREATE TABLE from_the_future (x);", user_version=5)

    assert migrate("--db", db_path) == 0

    assert user_version(db_path) == 5
    assert tables(db_path) == {"from_the_future"}
    assert files_in(db_path.parent / "backup") == []


# --- backups ----------------------------------------------------------------


def test_backup_holds_the_database_as_it_was_before_migrating(db_path):
    legacy_db(db_path)

    assert migrate("--db", db_path) == 0

    backups = files_in(db_path.parent / "backup")
    assert len(backups) == 1 and backups[0].startswith("tmdb-v0-") and backups[0].endswith(".sqlite")
    backup = db_path.parent / "backup" / backups[0]
    assert user_version(backup) == 0
    assert query(backup, "SELECT count(*) FROM events") == [(2,)]


def test_only_the_latest_backup_is_kept(db_path, make_migrations):
    create_db(db_path, "CREATE TABLE existing (x);")
    migrations = make_migrations({"0001_create_a.sql": "CREATE TABLE a (x);"})
    assert migrate("--db", db_path, "--migrations", migrations) == 0

    make_migrations({"0002_create_b.sql": "CREATE TABLE b (x);"})
    assert migrate("--db", db_path, "--migrations", migrations) == 0

    backups = files_in(db_path.parent / "backup")
    assert len(backups) == 1 and backups[0].startswith("tmdb-v1-")


def test_backup_is_skipped_but_migrations_run_when_disk_space_is_low(db_path, monkeypatch, capsys):
    legacy_db(db_path)
    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(tmdb_migrate.shutil, "disk_usage", lambda path: usage(10_000, 9_999, 1))

    assert migrate("--db", db_path) == 0

    assert user_version(db_path) == 1
    assert [name for name in files_in(db_path.parent / "backup") if name.endswith(".sqlite")] == []
    assert "WARNING" in output(capsys)


def test_failed_backup_stops_the_migration(db_path, make_migrations, tmp_path):
    create_db(db_path, "CREATE TABLE existing (x);")
    migrations = make_migrations({"0001_create_a.sql": "CREATE TABLE a (x);"})
    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("")

    assert migrate("--db", db_path, "--migrations", migrations, "--backup-dir", not_a_directory / "backup") == 1

    assert user_version(db_path) == 0
    assert tables(db_path) == {"existing"}


# --- drift ------------------------------------------------------------------


def test_drift_is_reported_for_an_old_deployment_table_and_left_alone(db_path, capsys):
    legacy_db(db_path)
    con = sqlite3.connect(db_path)
    con.executescript("""
        DROP TABLE deployment;
        CREATE TABLE deployment (id TEXT PRIMARY KEY, entryDateTime REAL, lat REAL, lon REAL,
                                 orientation TEXT, address TEXT, description TEXT);
    """)
    con.close()

    assert migrate("--db", db_path) == 0

    drift = [line for line in output(capsys).splitlines() if "DRIFT" in line and "deployment" in line]
    missing = " ".join(line for line in drift if "missing" in line)
    unexpected = " ".join(line for line in drift if "unexpected" in line)
    for column in ["entryStartDateTime", "entryEndDateTime", "bearing", "sensorType", "sensorName", "deviceName"]:
        assert column in missing
    for column in ["entryDateTime", "orientation", "address", "description"]:
        assert column in unexpected
    assert columns(db_path, "deployment") == ["id", "entryDateTime", "lat", "lon", "orientation", "address", "description"]


def test_drift_is_reported_for_a_changed_column_type(db_path, make_migrations, capsys):
    create_db(db_path, "CREATE TABLE t (a TEXT);")
    migrations = make_migrations({"0001_create_t.sql": "CREATE TABLE IF NOT EXISTS t (a REAL);"})

    assert migrate("--db", db_path, "--migrations", migrations) == 0

    drift = [line for line in output(capsys).splitlines() if "DRIFT" in line]
    assert len(drift) == 1 and re.search(r"\bt\b", drift[0]) and "REAL" in drift[0] and "TEXT" in drift[0]


# --- check mode -------------------------------------------------------------


def test_check_reports_pending_migrations_without_changing_anything(db_path, capsys):
    legacy_db(db_path)

    assert migrate("--db", db_path, "--check") == 1

    log = output(capsys)
    assert "0001_baseline.sql" in log
    assert "DRIFT" not in log  # drift is judged after migrating, not against an unmigrated database
    assert user_version(db_path) == 0
    assert not (db_path.parent / "backup").exists()


def test_check_passes_once_the_database_is_migrated(db_path):
    legacy_db(db_path)
    assert migrate("--db", db_path) == 0

    assert migrate("--db", db_path, "--check") == 0


def test_check_fails_on_drift(db_path, make_migrations):
    create_db(db_path, "CREATE TABLE t (a TEXT);", user_version=1)
    migrations = make_migrations({"0001_create_t.sql": "CREATE TABLE IF NOT EXISTS t (a REAL);"})

    assert migrate("--db", db_path, "--migrations", migrations, "--check") == 1


def test_check_does_not_create_a_missing_database(db_path):
    assert migrate("--db", db_path, "--check") == 1

    assert not db_path.exists()


# --- running on the device ----------------------------------------------------


def test_runner_needs_only_the_standard_library(db_path):
    # The device runs the script with the system python3, outside any venv.
    # -I -S hides site-packages, so a third-party import fails here too.
    result = subprocess.run([sys.executable, "-I", "-S", str(RUNNER), "--db", str(db_path)],
                            capture_output=True, text=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert tables(db_path) == BASELINE_TABLES
