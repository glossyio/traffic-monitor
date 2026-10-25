#!/usr/bin/env python3
"""Apply versioned schema migrations to the Traffic Monitor database (tmdb.sqlite).

On the device this runs as ExecStartPre of node-red-tm.service, so it finishes
before Node-RED opens the database. Run it as the user Node-RED runs as (the
code owner, through runuser): a database or backup/ it creates belongs to the
caller, and Node-RED can't write a root-owned one. It uses only the standard library because
it runs with the system python3, outside any venv. See README.md for how to add
a migration.
"""

import argparse
import datetime
import re
import shutil
import sqlite3
import sys
from pathlib import Path

MIGRATION_NAME = re.compile(r"^(\d{4})_[A-Za-z0-9_-]+\.sql$")
# The runner wraps each file in its own transaction and sets user_version, so a file must not.
# A COMMIT inside a file would end that transaction early and let a later failure leave half a change.
SQL_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
FORBIDDEN_STATEMENT = re.compile(
    r"(?:^|;)\s*(BEGIN|COMMIT|END|ROLLBACK|SAVEPOINT|RELEASE|VACUUM|PRAGMA\s+user_version)\b", re.IGNORECASE)
# Free space needed for a pre-migration backup, as a multiple of the database size.
BACKUP_SPACE_FACTOR = 1.2


class MigrationError(Exception):
    pass


def log(message):
    print(f"tmdb-migrate: {message}", file=sys.stderr, flush=True)


def load_migrations(directory):
    """Return the migration files in order; numbers must run 0001..N with no gaps."""
    numbered = {}
    for path in sorted(Path(directory).glob("*.sql")):
        match = MIGRATION_NAME.match(path.name)
        if not match:
            raise MigrationError(f"{path.name}: migration names must look like 0001_short_name.sql")
        number = int(match.group(1))
        if number in numbered:
            raise MigrationError(f"{path.name}: duplicate migration number {number:04d}")
        forbidden = FORBIDDEN_STATEMENT.search(SQL_COMMENT.sub("", path.read_text()))
        if forbidden:
            # This also rejects a trigger's END; extend the check if a migration ever needs a trigger.
            raise MigrationError(f"{path.name}: remove {forbidden.group(1)}; the runner handles transactions and user_version")
        numbered[number] = path
    if not numbered:
        raise MigrationError(f"no migrations found in {directory}")
    if sorted(numbered) != list(range(1, len(numbered) + 1)):
        raise MigrationError(f"migration numbers must run 0001..{len(numbered):04d} without gaps")
    return [numbered[number] for number in sorted(numbered)]


def user_version(con):
    return con.execute("PRAGMA user_version").fetchone()[0]


def has_tables(con):
    return con.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0] > 0


def backup_database(con, db_path, backup_dir, version):
    """Copy the database into backup_dir and return the copy's path, or None if space is short.

    The copy replaces any backup of the same version, left by a run whose migrations failed.
    Backups of other versions stay until the migrations succeed (see remove_backups_except),
    unless they take the space the new one needs. Nothing is deleted when the copy is skipped.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    for partial in backup_dir.glob("tmdb-v*.sqlite.partial"):
        partial.unlink()  # left by a run that stopped mid-copy
    needed = db_path.stat().st_size * BACKUP_SPACE_FACTOR
    free = shutil.disk_usage(backup_dir).free
    same = sorted(backup_dir.glob(f"tmdb-v{version}-*.sqlite"))
    other = sorted(set(backup_dir.glob("tmdb-v*.sqlite")) - set(same))
    if free + total_size(same) + total_size(other) < needed:
        log(f"WARNING: skipping backup, {free / 2**20:.0f} MiB free in {backup_dir}, {needed / 2**20:.0f} MiB needed")
        return None
    superseded = same
    if free + total_size(same) < needed:
        log(f"WARNING: deleting {len(other)} older backup(s) to make room for a new one")
        superseded = same + other
    for old in superseded:
        old.unlink()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"tmdb-v{version}-{stamp}.sqlite"
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)
    try:
        con.execute("VACUUM INTO ?", (str(partial),))
        partial.rename(target)
    finally:
        partial.unlink(missing_ok=True)
    log(f"backed up {db_path} to {target}")
    return target


def total_size(paths):
    return sum(path.stat().st_size for path in paths)


def remove_backups_except(backup_dir, keep):
    for old in backup_dir.glob("tmdb-v*.sqlite"):
        if old != keep:
            old.unlink()


def apply_migrations(con, migrations, current):
    """Apply migrations[current:], each in its own transaction that also sets user_version."""
    for number, path in enumerate(migrations[current:], start=current + 1):
        try:
            con.executescript(f"BEGIN IMMEDIATE;\n{path.read_text()}\n;\nPRAGMA user_version = {number};\nCOMMIT;")
        except sqlite3.Error as exc:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise MigrationError(f"{path.name} failed and was rolled back: {exc}") from exc
        if user_version(con) != number:
            raise MigrationError(f"{path.name} left user_version at {user_version(con)}, expected {number}")
        log(f"applied {path.name}")


def expected_schema(migrations):
    """An in-memory database built from the given migrations."""
    con = sqlite3.connect(":memory:")
    for path in migrations:
        con.executescript(path.read_text())
    return con


def indexes_and_views(con):
    """{(type, name)} for every index and view, leaving out SQLite's automatic indexes."""
    return set(con.execute(
        "SELECT type, name FROM sqlite_master WHERE type IN ('index', 'view') AND name NOT LIKE 'sqlite_%'"))


def table_columns(con):
    """{table: {column: declared type}} for every table in the database."""
    names = [name for (name,) in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {name: {row[1]: row[2].upper() for row in con.execute(f'PRAGMA table_info("{name}")')} for name in names}


def report_drift(con, migrations):
    """Log each difference from what these migrations create. Returns True on any drift.

    Compares table, column, index, and view names and declared column types. NOT NULL, defaults,
    and keys are left out, because older devices' tables differ there harmlessly.
    """
    reference = expected_schema(migrations)
    expected = table_columns(reference)
    actual = table_columns(con)
    issues = [f"missing table {name}" for name in sorted(expected.keys() - actual.keys())]
    issues += [f"unexpected table {name}" for name in sorted(actual.keys() - expected.keys())]
    for name in sorted(expected.keys() & actual.keys()):
        want, have = expected[name], actual[name]
        missing = [column for column in want if column not in have]
        unexpected = [column for column in have if column not in want]
        changed = [f"{column} {have[column]} (expected {want[column]})"
                   for column in want if column in have and have[column] != want[column]]
        if missing:
            issues.append(f"{name}: missing columns: {', '.join(missing)}")
        if unexpected:
            issues.append(f"{name}: unexpected columns: {', '.join(unexpected)}")
        if changed:
            issues.append(f"{name}: column types differ: {', '.join(changed)}")
    want, have = indexes_and_views(reference), indexes_and_views(con)
    issues += [f"missing {kind} {name}" for kind, name in sorted(want - have)]
    issues += [f"unexpected {kind} {name}" for kind, name in sorted(have - want)]
    for issue in issues:
        log(f"DRIFT {issue}")
    return bool(issues)


def migrate_database(db_path, migrations, backup_dir):
    latest = len(migrations)
    con = sqlite3.connect(db_path, isolation_level=None)
    try:
        current = user_version(con)
        if current > latest:
            log(f"WARNING: {db_path} is at version {current}, newer than these migrations ({latest}); leaving it unchanged")
            return
        if current == latest:
            log(f"{db_path} is up to date at version {latest}")
        else:
            backup = None
            # 0001 is the baseline: CREATE ... IF NOT EXISTS only, so adopting a database from
            # before migrations changes no existing table, and a multi-GB copy would only add downtime.
            if has_tables(con) and migrations[current:] != migrations[:1]:
                backup = backup_database(con, db_path, backup_dir, current)
            apply_migrations(con, migrations, current)
            if backup:
                remove_backups_except(backup_dir, backup)
            log(f"migrated {db_path} from version {current} to {latest}")
        report_drift(con, migrations)
    finally:
        con.close()


def dump_schema(migrations):
    """The schema these migrations create, as SQL. schema.sql holds this output."""
    con = expected_schema(migrations)
    rows = con.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
        "ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 WHEN 'view' THEN 2 ELSE 3 END, name")
    parts = [
        "-- Generated by tmdb_migrate.py --dump-schema from migrations/. Do not edit.\n"
        "-- Regenerate: python3 container/node-red-tm/schema/tmdb_migrate.py --dump-schema"
        " > container/node-red-tm/schema/schema.sql",
        f"PRAGMA user_version = {len(migrations)};",
    ]
    parts += ["\n".join(line.rstrip() for line in sql.splitlines()) + ";" for (sql,) in rows]
    return "\n\n".join(parts) + "\n"


def check_database(db_path, migrations):
    """Report version, pending migrations, and drift without changing anything. Returns 0 only if clean."""
    latest = len(migrations)
    if not db_path.exists():
        log(f"{db_path} does not exist; {latest} migration(s) pending")
        return 1
    con = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        current = user_version(con)
        if current > latest:
            log(f"WARNING: {db_path} is at version {current}, newer than these migrations ({latest})")
            return 1
        pending = [path.name for path in migrations[current:]]
        if pending:
            # Drift is judged against the migrated schema, so it waits until nothing is pending.
            log(f"{db_path} is at version {current}; pending: {', '.join(pending)}")
            return 1
        log(f"{db_path} is up to date at version {current}")
        return 1 if report_drift(con, migrations) else 0
    finally:
        con.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Apply tmdb.sqlite schema migrations.")
    parser.add_argument("--db", type=Path, help="database file, e.g. /opt/traffic-monitor/node-red-tm/db/tmdb.sqlite")
    parser.add_argument("--migrations", type=Path, default=Path(__file__).resolve().parent / "migrations",
                        help="directory of NNNN_name.sql files (default: migrations/ next to this script)")
    parser.add_argument("--backup-dir", type=Path,
                        help="where to keep the pre-migration backup (default: backup/ next to the database)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="report version, pending migrations, and drift; change nothing (exit 1 if not clean)")
    mode.add_argument("--dump-schema", action="store_true",
                      help="print the schema the migrations create (used to regenerate schema.sql)")
    args = parser.parse_args(argv)
    if args.db is None and not args.dump_schema:
        parser.error("--db is required")

    try:
        migrations = load_migrations(args.migrations)
    except MigrationError as exc:
        log(f"ERROR: {exc}")
        return 2
    if args.dump_schema:
        print(dump_schema(migrations), end="")
        return 0
    try:
        if args.check:
            return check_database(args.db, migrations)
        migrate_database(args.db, migrations, args.backup_dir or args.db.parent / "backup")
        return 0
    except (MigrationError, sqlite3.Error, OSError) as exc:
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
