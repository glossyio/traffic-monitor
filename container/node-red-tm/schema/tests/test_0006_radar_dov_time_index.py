"""0006 adds an index on radar_dov(time), so a query for a stretch of time no longer reads the whole table."""

import sqlite3

from helpers import LATEST_VERSION, SCHEMA_DIR, migrate, query, user_version

EVENT_QUERY = ("SELECT * FROM radar_dov WHERE time BETWEEN 1761800000 AND 1761800009 "
               "AND radarName = 'TM_RADAR_SERIAL_PORT_00'")


def at_version_5(tmp_path):
    """A database migrated through 0005 only, with a few radar readings."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for path in sorted((SCHEMA_DIR / "migrations").glob("000[1-5]_*.sql")):
        (migrations / path.name).write_text(path.read_text())
    db_path = tmp_path / "tmdb.sqlite"
    assert migrate("--db", db_path, "--migrations", migrations) == 0
    con = sqlite3.connect(db_path)
    con.executemany("INSERT INTO radar_dov (time, unit, direction, velocity, radarName) VALUES (?, 'mph', 'inbound', ?, ?)",
                    [(1761800000 + second, 20 + second, "TM_RADAR_SERIAL_PORT_00") for second in range(20)])
    con.commit()
    con.close()
    return db_path


def plan(db_path, sql):
    return " ".join(row[3] for row in query(db_path, "EXPLAIN QUERY PLAN " + sql))


def test_0006_adds_the_index_and_changes_no_row(tmp_path):
    db_path = at_version_5(tmp_path)
    before = query(db_path, "SELECT * FROM radar_dov ORDER BY time")
    assert user_version(db_path) == 5 and "USING INDEX" not in plan(db_path, EVENT_QUERY)
    assert migrate("--db", db_path, "--backup-dir", tmp_path / "backup") == 0
    assert user_version(db_path) == LATEST_VERSION
    assert query(db_path, "SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name = 'index_radar_dov_time'") == [
        ("radar_dov",)]
    assert [row[2] for row in query(db_path, "PRAGMA index_info(index_radar_dov_time)")] == ["time"]
    assert query(db_path, "SELECT * FROM radar_dov ORDER BY time") == before


def test_queries_for_a_stretch_of_time_use_the_index(tmp_path):
    db_path = tmp_path / "tmdb.sqlite"
    assert migrate("--db", db_path) == 0
    for sql in (EVENT_QUERY, EVENT_QUERY + " AND NOT (time > 1761800003 AND time < 1761800006)",
                "SELECT * FROM radar_dov ORDER BY time DESC LIMIT 5"):
        assert "USING INDEX index_radar_dov_time" in plan(db_path, sql)
    assert len(query(db_path, EVENT_QUERY)) == 0
