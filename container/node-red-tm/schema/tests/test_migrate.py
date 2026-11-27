import collections
import datetime
import re
import sqlite3
import subprocess
import sys
import types

import pytest

import helpers
from helpers import (
    ALL_TABLES,
    BASELINE_TABLES,
    LATEST_VERSION,
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


def baseline_only(make_migrations):
    """Just the real baseline, for tests about what 0001 alone does."""
    baseline = (helpers.SCHEMA_DIR / "migrations" / "0001_baseline.sql").read_text()
    return make_migrations({"0001_baseline.sql": baseline})


def with_a_second_migration(make_migrations):
    """The real baseline plus a 0002, so adopting a pre-migration database is more than the baseline."""
    baseline = (helpers.SCHEMA_DIR / "migrations" / "0001_baseline.sql").read_text()
    return make_migrations({"0001_baseline.sql": baseline, "0002_create_extra.sql": "CREATE TABLE extra (x);"})


def output(capsys):
    captured = capsys.readouterr()
    return captured.out + captured.err


# --- applying migrations ---------------------------------------------------


def test_fresh_database_gets_baseline_tables_and_version(db_path):
    assert migrate("--db", db_path) == 0

    assert tables(db_path) == ALL_TABLES
    assert user_version(db_path) == LATEST_VERSION
    assert files_in(db_path.parent / "backup") == []  # nothing to back up yet


def test_pre_migration_database_is_adopted_with_rows_intact(db_path, capsys):
    legacy_db(db_path)

    assert migrate("--db", db_path) == 0

    assert user_version(db_path) == LATEST_VERSION
    assert query(db_path, "SELECT count(*) FROM events") == [(2,)]
    assert query(db_path, "SELECT count(*) FROM radar_dov") == [(1,)]
    assert "DRIFT" not in output(capsys)


def test_baseline_creates_the_same_columns_as_the_old_flows(db_path, tmp_path, make_migrations):
    legacy_path = tmp_path / "legacy.sqlite"
    create_db(legacy_path, LEGACY_SCHEMA.read_text())

    assert migrate("--db", db_path, "--migrations", baseline_only(make_migrations)) == 0

    for table in BASELINE_TABLES:
        # cid, name, type, notnull, default, pk
        assert query(db_path, f"PRAGMA table_info({table})") == query(legacy_path, f"PRAGMA table_info({table})"), table


@pytest.mark.parametrize("had_flow_index", [False, True])
def test_baseline_adds_or_keeps_the_radar_time_index(db_path, had_flow_index):
    # TM 0.6.1 databases don't have this index; #197's flows created it on databases that ran them.
    legacy_db(db_path)
    if had_flow_index:
        con = sqlite3.connect(db_path)
        con.execute("CREATE INDEX index_radar_singleton_time ON radar_raw_speed_magnitude_single(time)")
        con.commit()
        con.close()

    assert migrate("--db", db_path) == 0

    assert user_version(db_path) == LATEST_VERSION
    assert query(db_path, "SELECT name FROM sqlite_master WHERE type = 'index' "
                          "AND tbl_name = 'radar_raw_speed_magnitude_single'") == [("index_radar_singleton_time",)]


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


@pytest.mark.parametrize("statement", ["COMMIT;", "begin transaction;", "ROLLBACK;", "VACUUM;", "PRAGMA user_version = 7;"])
def test_migration_that_controls_its_own_transaction_is_rejected(db_path, make_migrations, statement, capsys):
    """A COMMIT inside a file would end the runner's transaction early, so a later failure left half a change."""
    migrations = make_migrations({"0001_create_a.sql": f"CREATE TABLE a (x);\n{statement}\nCREATE TABLE b (x);"})

    assert migrate("--db", db_path, "--migrations", migrations) == 2

    assert not db_path.exists()
    assert "0001_create_a.sql" in output(capsys)


def test_transaction_words_in_comments_and_names_are_allowed(db_path, make_migrations):
    migrations = make_migrations({"0001_create_a.sql": "-- COMMIT is added by the runner\n/* ROLLBACK; */\nCREATE TABLE a (end_time REAL, begin_time REAL);"})

    assert migrate("--db", db_path, "--migrations", migrations) == 0


def test_database_that_cannot_be_opened_is_reported_as_an_error(tmp_path, capsys):
    assert migrate("--db", tmp_path / "no_such_directory" / "tmdb.sqlite") == 1

    assert "ERROR" in output(capsys)


def test_database_newer_than_the_migrations_is_left_unchanged(db_path):
    create_db(db_path, "CREATE TABLE from_the_future (x);", user_version=LATEST_VERSION + 1)

    assert migrate("--db", db_path) == 0

    assert user_version(db_path) == LATEST_VERSION + 1
    assert tables(db_path) == {"from_the_future"}
    assert files_in(db_path.parent / "backup") == []


# --- backups ----------------------------------------------------------------


def test_adopting_a_pre_migration_database_needs_no_backup(db_path, make_migrations):
    """The baseline only creates what's missing, and copying a multi-GB database would add minutes of downtime."""
    legacy_db(db_path)

    assert migrate("--db", db_path, "--migrations", baseline_only(make_migrations)) == 0

    assert files_in(db_path.parent / "backup") == []


def test_backup_holds_the_database_as_it_was_before_migrating(db_path, make_migrations):
    legacy_db(db_path)

    assert migrate("--db", db_path, "--migrations", with_a_second_migration(make_migrations)) == 0

    backups = files_in(db_path.parent / "backup")
    assert len(backups) == 1 and backups[0].startswith("tmdb-v0-") and backups[0].endswith(".sqlite")
    backup = db_path.parent / "backup" / backups[0]
    assert user_version(backup) == 0
    assert query(backup, "SELECT count(*) FROM events") == [(2,)]


def test_only_the_latest_backup_is_kept(db_path, make_migrations):
    create_db(db_path, "CREATE TABLE existing (x);")
    migrations = make_migrations({"0001_create_a.sql": "CREATE TABLE a (x);", "0002_create_b.sql": "CREATE TABLE b (x);"})
    assert migrate("--db", db_path, "--migrations", migrations) == 0

    make_migrations({"0003_create_c.sql": "CREATE TABLE c (x);"})
    assert migrate("--db", db_path, "--migrations", migrations) == 0

    backups = files_in(db_path.parent / "backup")
    assert len(backups) == 1 and backups[0].startswith("tmdb-v2-")


def test_a_failed_migration_keeps_the_older_backups(db_path, make_migrations):
    """A retry after a failure must not delete the only copy from before this release."""
    create_db(db_path, "CREATE TABLE a (x);", user_version=1)
    backup_dir = db_path.parent / "backup"
    backup_dir.mkdir()
    create_db(backup_dir / "tmdb-v0-20260101T000000Z.sqlite", "CREATE TABLE old (x);")
    migrations = make_migrations({"0001_create_a.sql": "CREATE TABLE a (x);", "0002_broken.sql": "INSERT INTO no_such_table VALUES (1);"})

    assert migrate("--db", db_path, "--migrations", migrations) == 1

    backups = files_in(backup_dir)
    assert len(backups) == 2 and backups[0] == "tmdb-v0-20260101T000000Z.sqlite" and backups[1].startswith("tmdb-v1-")


def test_a_retry_after_a_failed_migration_replaces_that_versions_backup(db_path, make_migrations, monkeypatch):
    """Each failed start would otherwise add another full copy until the disk filled."""
    create_db(db_path, "CREATE TABLE a (x);", user_version=1)
    backup_dir = db_path.parent / "backup"
    backup_dir.mkdir()
    create_db(backup_dir / "tmdb-v0-20260101T000000Z.sqlite", "CREATE TABLE old (x);")
    migrations = make_migrations({"0001_create_a.sql": "CREATE TABLE a (x);", "0002_broken.sql": "INSERT INTO no_such_table VALUES (1);"})
    # Give each run its own timestamp, so the second copy can't simply overwrite the first
    times = iter([datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc),
                  datetime.datetime(2026, 2, 2, tzinfo=datetime.timezone.utc)])
    clock = types.SimpleNamespace(now=lambda tz: next(times))
    monkeypatch.setattr(tmdb_migrate, "datetime", types.SimpleNamespace(datetime=clock, timezone=datetime.timezone))

    assert migrate("--db", db_path, "--migrations", migrations) == 1
    assert migrate("--db", db_path, "--migrations", migrations) == 1

    assert files_in(backup_dir) == ["tmdb-v0-20260101T000000Z.sqlite", "tmdb-v1-20260202T000000Z.sqlite"]


def older_backup_of_size(backup_dir, size):
    """A v0 backup file of about size bytes."""
    path = backup_dir / "tmdb-v0-20260101T000000Z.sqlite"
    create_db(path, f"CREATE TABLE old (x); INSERT INTO old VALUES (zeroblob({size}));")
    return path


def test_older_backups_make_room_for_a_new_one_when_space_is_short(db_path, make_migrations, monkeypatch, capsys):
    create_db(db_path, "CREATE TABLE a (x);", user_version=1)
    backup_dir = db_path.parent / "backup"
    backup_dir.mkdir()
    older_backup_of_size(backup_dir, 100_000)
    usage = collections.namedtuple("usage", "total used free")
    # Too little space for a copy of the database until the older backup is gone
    monkeypatch.setattr(tmdb_migrate.shutil, "disk_usage", lambda path: usage(10**12, 0, 1))
    migrations = make_migrations({"0001_create_a.sql": "CREATE TABLE a (x);", "0002_create_b.sql": "CREATE TABLE b (x);"})

    assert migrate("--db", db_path, "--migrations", migrations) == 0

    backups = files_in(backup_dir)
    assert len(backups) == 1 and backups[0].startswith("tmdb-v1-")
    assert "deleting 1 older backup" in output(capsys)


def test_older_backups_are_kept_when_deleting_them_would_not_make_room(db_path, make_migrations, monkeypatch, capsys):
    """Deleting them anyway would leave the device with no backup at all."""
    create_db(db_path, "CREATE TABLE a (x); INSERT INTO a VALUES (zeroblob(100000));", user_version=1)
    backup_dir = db_path.parent / "backup"
    backup_dir.mkdir()
    older_backup_of_size(backup_dir, 0)
    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(tmdb_migrate.shutil, "disk_usage", lambda path: usage(10**12, 0, 1))
    migrations = make_migrations({"0001_create_a.sql": "CREATE TABLE a (x);", "0002_create_b.sql": "CREATE TABLE b (x);"})

    assert migrate("--db", db_path, "--migrations", migrations) == 0

    assert user_version(db_path) == 2
    assert files_in(backup_dir) == ["tmdb-v0-20260101T000000Z.sqlite"]
    assert "skipping backup" in output(capsys)


def test_a_partial_backup_from_an_interrupted_run_is_removed(db_path, make_migrations):
    create_db(db_path, "CREATE TABLE a (x);", user_version=1)
    backup_dir = db_path.parent / "backup"
    backup_dir.mkdir()
    (backup_dir / "tmdb-v1-20260101T000000Z.sqlite.partial").write_text("cut off")
    migrations = make_migrations({"0001_create_a.sql": "CREATE TABLE a (x);", "0002_create_b.sql": "CREATE TABLE b (x);"})

    assert migrate("--db", db_path, "--migrations", migrations) == 0

    assert not any(name.endswith(".partial") for name in files_in(backup_dir))


def test_backup_is_skipped_but_migrations_run_when_disk_space_is_low(db_path, make_migrations, monkeypatch, capsys):
    legacy_db(db_path)
    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(tmdb_migrate.shutil, "disk_usage", lambda path: usage(10_000, 9_999, 1))

    assert migrate("--db", db_path, "--migrations", with_a_second_migration(make_migrations)) == 0

    assert user_version(db_path) == 2
    assert [name for name in files_in(db_path.parent / "backup") if name.endswith(".sqlite")] == []
    assert "WARNING" in output(capsys)


def test_failed_backup_stops_the_migration(db_path, make_migrations, tmp_path):
    create_db(db_path, "CREATE TABLE existing (x);")
    migrations = make_migrations({"0001_create_a.sql": "CREATE TABLE a (x);", "0002_create_b.sql": "CREATE TABLE b (x);"})
    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("")

    assert migrate("--db", db_path, "--migrations", migrations, "--backup-dir", not_a_directory / "backup") == 1

    assert user_version(db_path) == 0
    assert tables(db_path) == {"existing"}


# --- the runner's own lines -------------------------------------------------

NEEDS_BEARING = "-- tmdb-migrate: needs-column t.old\nALTER TABLE t DROP COLUMN old;\n"


def test_a_needs_column_migration_is_applied_when_the_column_exists(db_path, make_migrations, capsys):
    migrations = make_migrations({"0001_create_t.sql": "CREATE TABLE t (keep TEXT, old TEXT);",
                                  "0002_drop_old.sql": NEEDS_BEARING})

    assert migrate("--db", db_path, "--migrations", migrations) == 0

    assert user_version(db_path) == 2
    assert columns(db_path, "t") == ["keep"]
    assert "skipped" not in output(capsys)


def test_a_needs_column_migration_is_skipped_when_it_does_not(db_path, make_migrations, capsys):
    # An older table shape: t never had the column, though 0001 creates it for a new database.
    create_db(db_path, "CREATE TABLE t (keep TEXT);", user_version=1)
    migrations = make_migrations({"0001_create_t.sql": "CREATE TABLE IF NOT EXISTS t (keep TEXT, old TEXT);",
                                  "0002_drop_old.sql": NEEDS_BEARING})

    assert migrate("--db", db_path, "--migrations", migrations) == 0

    assert user_version(db_path) == 2
    assert columns(db_path, "t") == ["keep"]
    assert "tmdb-migrate: 0002_drop_old.sql: skipped, t has no column old" in output(capsys)


class FailingConnection:
    """A connection that raises sqlite3.Error from one call, as a locked database does, and passes the rest on."""

    def __init__(self, con, fail_on, begin_first=False):
        self.con = con
        self.fail_on = fail_on
        self.begin_first = begin_first

    @property
    def in_transaction(self):
        return self.con.in_transaction

    def execute(self, sql, *args):
        if self.fail_on in sql:
            raise sqlite3.OperationalError("database is locked")
        return self.con.execute(sql, *args)

    def executescript(self, script):
        if self.fail_on in script:
            if self.begin_first:
                self.con.execute("BEGIN IMMEDIATE")  # the script began its transaction, then failed
            raise sqlite3.OperationalError("database is locked")
        return self.con.executescript(script)


@pytest.mark.parametrize("fail_on, begin_first", [("PRAGMA table_info", False), ("PRAGMA user_version = 2", True)],
                         ids=["the column lookup", "the version write"])
def test_a_skip_that_hits_a_sqlite_error_is_rolled_back(db_path, make_migrations, fail_on, begin_first):
    create_db(db_path, "CREATE TABLE t (keep TEXT);", user_version=1)
    migrations = tmdb_migrate.load_migrations(make_migrations({"0001_create_t.sql": "CREATE TABLE IF NOT EXISTS t (keep TEXT, old TEXT);",
                                                               "0002_drop_old.sql": NEEDS_BEARING}))
    con = sqlite3.connect(db_path, isolation_level=None)
    try:
        with pytest.raises(tmdb_migrate.MigrationError) as raised:
            tmdb_migrate.apply_migrations(FailingConnection(con, fail_on, begin_first), migrations, 1)

        assert str(raised.value) == "0002_drop_old.sql failed and was rolled back: database is locked"
        assert not con.in_transaction
        assert tmdb_migrate.user_version(con) == 1
    finally:
        con.close()


@pytest.mark.parametrize("head", [
    "-- tmdb-migrate: needs-column deployment",
    "-- tmdb-migrate: needs-column a.b.c",
    "-- tmdb-migrate: needs-table t",
    "-- tmdb-migrate:",
    "-- tmdb-migrate: needs-column t.old ",
    "-- tmdb-migrate:needs-column t.old",
    "--tmdb-migrate: needs-column t.old",
    "-- Drop the old column.\n-- tmdb-migrate: needs-column t.old",
    "\n-- tmdb-migrate: needs-column t.old",
    "-- tmdb-migrate: needs-column t.old\n-- tmdb-migrate: needs-column t.keep",
], ids=["no column", "too many dots", "unknown word", "empty", "trailing space", "no space after the colon",
        "no space after the dashes", "under a header comment", "after a blank line", "a second runner line"])
def test_an_unknown_runner_line_is_refused(db_path, make_migrations, head, capsys):
    migrations = make_migrations({"0001_create_t.sql": "CREATE TABLE t (old TEXT);",
                                  "0002_drop_old.sql": f"{head}\nALTER TABLE t DROP COLUMN old;\n"})

    assert migrate("--db", db_path, "--migrations", migrations) == 2

    assert not db_path.exists()
    assert "0002_drop_old.sql" in output(capsys)


@pytest.mark.parametrize("text", [
    "\ufeff" + NEEDS_BEARING,
    NEEDS_BEARING.replace("\n", "\r\n"),
], ids=["after a BOM", "with CRLF line ends"])
def test_a_runner_line_is_read_after_a_bom_and_with_crlf(db_path, make_migrations, text, capsys):
    create_db(db_path, "CREATE TABLE t (keep TEXT);", user_version=1)
    migrations = make_migrations({"0001_create_t.sql": "CREATE TABLE IF NOT EXISTS t (keep TEXT, old TEXT);",
                                  "0002_drop_old.sql": text})

    assert migrate("--db", db_path, "--migrations", migrations) == 0

    assert user_version(db_path) == 2
    assert "tmdb-migrate: 0002_drop_old.sql: skipped, t has no column old" in output(capsys)


def test_a_file_with_a_bom_is_applied(db_path, make_migrations):
    migrations = make_migrations({"0001_create_t.sql": "\ufeffCREATE TABLE t (keep TEXT, old TEXT);",
                                  "0002_drop_old.sql": "\ufeff" + NEEDS_BEARING})

    assert migrate("--db", db_path, "--migrations", migrations) == 0

    assert user_version(db_path) == 2
    assert columns(db_path, "t") == ["keep"]


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

    log = output(capsys)
    drift = [line for line in log.splitlines() if "DRIFT" in line and "deployment" in line]
    missing = " ".join(line for line in drift if "missing" in line)
    unexpected = " ".join(line for line in drift if "unexpected" in line)
    for column in ["entryStartDateTime", "entryEndDateTime", "sensorType", "sensorName", "deviceName"]:
        assert column in missing
    assert "bearing" not in missing and "heading_deg" not in missing
    for column in ["entryDateTime", "orientation", "address", "description"]:
        assert column in unexpected
    # 0002 and 0008 add their columns; 0009 and 0010 are skipped (no bearing); the old columns are kept
    assert user_version(db_path) == LATEST_VERSION
    assert "0009_deployment_heading_from_bearing.sql: skipped, deployment has no column bearing" in log
    assert "0010_deployment_drop_bearing.sql: skipped, deployment has no column bearing" in log
    assert columns(db_path, "deployment") == ["id", "entryDateTime", "lat", "lon", "orientation", "address", "description",
                                              "survey_id", "location_precision", "heading_deg", "pitch_deg", "height_m",
                                              "view_distance_m", "mount", "timezone"]


def test_drift_is_reported_for_a_missing_index(db_path, make_migrations, capsys):
    create_db(db_path, "CREATE TABLE t (a REAL);")
    migrations = make_migrations({"0001_create_t.sql": "CREATE TABLE IF NOT EXISTS t (a REAL);",
                                  "0002_index_t.sql": "CREATE INDEX index_t_a ON t(a);"})
    assert migrate("--db", db_path, "--migrations", migrations) == 0
    capsys.readouterr()
    sqlite3.connect(db_path).execute("DROP INDEX index_t_a").connection.close()

    assert migrate("--db", db_path, "--migrations", migrations, "--check") == 1

    assert "DRIFT missing index index_t_a" in output(capsys)


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
    assert tables(db_path) == ALL_TABLES
