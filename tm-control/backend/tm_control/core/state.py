"""tm-control's own database (users, claim state, EULA record, jobs, audit), versioned by numbered migrations.

The device's StateDirectory holds it as state.sqlite. MIGRATIONS[0] is migration 1; PRAGMA user_version records
how many have been applied. Never edit a migration that has shipped; append a new one.
"""

import sqlite3
from pathlib import Path


def _centre(column: str) -> str:
    """SQL for the heading at the centre of an old bearing in `column`: one of the eight compass points, after trimming
    and lower-casing, gives its index times 45; anything else gives NULL."""
    points = ("n", "ne", "e", "se", "s", "sw", "w", "nw")
    whens = " ".join(f"WHEN '{point}' THEN {index * 45}" for index, point in enumerate(points))
    return f"CASE lower(trim({column}, ' ' || char(9, 10, 11, 12, 13))) {whens} END"


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
    # Which run of a job's unit is the job's own (core/jobs.py): the unit's InvocationID when the job was requested,
    # and its run's InvocationID once seen.
    """
    ALTER TABLE jobs ADD COLUMN prior_invocation TEXT;
    ALTER TABLE jobs ADD COLUMN invocation TEXT;
    """,
    # The unit's places (design section 5): the exact history of where it stood and which way its sensors faced.
    # map_mode, map_block_ref and map_side are created for the map feature and not written yet.
    """
    CREATE TABLE surveys (
        id TEXT PRIMARY KEY,  -- '<8 hex>-si'
        description TEXT,  -- private; never leaves the device
        lat REAL, lon REAL,  -- exact, at most 5 decimal places; NULL for no location
        status TEXT NOT NULL CHECK (status IN ('planned', 'in_use', 'used')),
        source TEXT NOT NULL,  -- 'ui' | 'csv' | 'default' | 'imported_config' | 'imported_backup'
        map_mode TEXT CHECK (map_mode IN ('block', 'rounded_point')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE TABLE survey_bearings (
        survey_id TEXT NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
        sensor_type TEXT NOT NULL,
        sensor_name TEXT NOT NULL,
        bearing TEXT NOT NULL,
        map_block_ref TEXT,
        map_side TEXT CHECK (map_side IN ('left', 'right', 'both')),
        PRIMARY KEY (survey_id, sensor_type, sensor_name)
    );
    CREATE TABLE survey_corrections (
        id INTEGER PRIMARY KEY,
        survey_id TEXT NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
        deployment_id TEXT,
        field TEXT NOT NULL CHECK (field IN ('location', 'bearing')),
        old_value TEXT,  -- 'lat,lon' (NULL for no location) or a bearing
        new_value TEXT,
        reason TEXT,
        source TEXT NOT NULL,  -- 'ui' | 'config'
        at TEXT NOT NULL,
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE INDEX survey_corrections_survey ON survey_corrections (survey_id);
    """,
    # What the owner agreed to share, one row per change (design: the Sharing page). The latest row per target and
    # consent is the answer; older rows are the history. A deleted user leaves the row with no user.
    """
    CREATE TABLE sharing_consents (
        id INTEGER PRIMARY KEY,
        target TEXT NOT NULL,  -- 'maintainer' | 'own:<host>'
        consent TEXT NOT NULL CHECK (consent IN ('share_data', 'exact_location', 'public_map')),
        granted INTEGER NOT NULL CHECK (granted IN (0, 1)),
        notice_version TEXT NOT NULL,  -- the notice's version, 'own-server', or 'pre-consent'
        at TEXT NOT NULL,
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        note TEXT
    );
    """,
    # Each sensor's heading in whole degrees from true north in place of its eight-point bearing (issue #357). Both
    # tables are rebuilt: survey_corrections.field's CHECK names the old field. A bearing becomes its point's centre,
    # anything else NULL, and each place keeps its sensors' order.
    f"""
    CREATE TABLE survey_sensors (
        survey_id TEXT NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
        sensor_type TEXT NOT NULL,
        sensor_name TEXT NOT NULL,
        heading_deg INTEGER CHECK (heading_deg BETWEEN 0 AND 359),  -- NULL for none
        map_block_ref TEXT,
        map_side TEXT CHECK (map_side IN ('left', 'right', 'both')),
        PRIMARY KEY (survey_id, sensor_type, sensor_name)
    );
    INSERT INTO survey_sensors (survey_id, sensor_type, sensor_name, heading_deg, map_block_ref, map_side)
        SELECT survey_id, sensor_type, sensor_name, {_centre("bearing")}, map_block_ref, map_side
        FROM survey_bearings ORDER BY rowid;
    DROP TABLE survey_bearings;
    CREATE TABLE survey_corrections_new (
        id INTEGER PRIMARY KEY,
        survey_id TEXT NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
        deployment_id TEXT,
        field TEXT NOT NULL CHECK (field IN ('location', 'heading_deg')),
        old_value TEXT,  -- 'lat,lon' (NULL for no location) or a heading in degrees (NULL for none)
        new_value TEXT,
        reason TEXT,
        source TEXT NOT NULL,  -- 'ui' | 'config'
        at TEXT NOT NULL,
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
    );
    INSERT INTO survey_corrections_new
        (id, survey_id, deployment_id, field, old_value, new_value, reason, source, at, user_id)
        SELECT id, survey_id, deployment_id,
               CASE field WHEN 'bearing' THEN 'heading_deg' ELSE field END,
               CASE field WHEN 'bearing' THEN CAST({_centre("old_value")} AS TEXT) ELSE old_value END,
               CASE field WHEN 'bearing' THEN CAST({_centre("new_value")} AS TEXT) ELSE new_value END,
               reason, source, at, user_id
        FROM survey_corrections;
    DROP TABLE survey_corrections;
    ALTER TABLE survey_corrections_new RENAME TO survey_corrections;
    CREATE INDEX survey_corrections_survey ON survey_corrections (survey_id);
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
