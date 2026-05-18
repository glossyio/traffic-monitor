"""
Shared pytest fixtures for traffic-monitor test suite.

All fixtures use in-memory SQLite so no device or real DB is required.
Schema mirrors tmdb.events.sqlite as documented at:
  https://docs.trafficmonitor.ai/sensor-payloads/events-payload
  https://docs.trafficmonitor.ai/sensor-payloads/radar-payload
"""

import json
import sqlite3
import time
import pytest

# Schema DDL
# Derived from documented payload fields. Update if upstream schema changes.

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS deployment (
    id          TEXT PRIMARY KEY,
    label       TEXT,
    bearing     REAL,
    created_at  INTEGER
);

CREATE TABLE IF NOT EXISTS events (
    id              TEXT PRIMARY KEY,
    camera          TEXT NOT NULL,
    label           TEXT NOT NULL,
    sub_label       TEXT,
    score           REAL,
    best_timestamp  INTEGER,
    start_timestamp INTEGER NOT NULL,
    end_timestamp   INTEGER NOT NULL,
    zones           TEXT,
    deployment_id   TEXT,
    created_at      INTEGER,
    FOREIGN KEY (deployment_id) REFERENCES deployment(id)
);

CREATE TABLE IF NOT EXISTS radar (
    id              TEXT PRIMARY KEY,
    sensor          TEXT NOT NULL,
    direction       TEXT,
    max_speed       REAL,
    avg_speed       REAL,
    dov_count       INTEGER,
    speeds          TEXT,
    duration_ms     INTEGER,
    frame_count     INTEGER,
    delta_speed     REAL,
    est_length      REAL,
    units           TEXT,
    classification  TEXT,
    start_time      INTEGER,
    end_time        INTEGER,
    deployment_id   TEXT,
    created_at      INTEGER,
    FOREIGN KEY (deployment_id) REFERENCES deployment(id)
);
"""
@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()

@pytest.fixture
def db_with_deployment(db):
    db.execute(
        "INSERT INTO deployment (id, label, bearing, created_at) VALUES (?,?,?,?)",
        ("deploy-001", "Front Street North", 0.0, int(time.time())),
    )
    db.commit()
    return db

def make_event_payload(**overrides):
    now = int(time.time())
    base = {
        "id": "avt-abc123",
        "camera": "front_cam",
        "label": "car",
        "sub_label": None,
        "score": 0.87,
        "best_timestamp": now,
        "start_timestamp": now - 3,
        "end_timestamp": now,
        "zones": json.dumps(["zone_road"]),
        "deployment_id": "deploy-001",
        "created_at": now,
    }
    base.update(overrides)
    return base

def make_radar_payload(**overrides):
    now = int(time.time())
    base = {
        "id": "rad-xyz789",
        "sensor": "radar_front",
        "direction": "inbound",
        "max_speed": 28.5,
        "avg_speed": 26.1,
        "dov_count": 3,
        "speeds": json.dumps([28.5, 27.2, 26.1]),
        "duration_ms": 1400,
        "frame_count": 28,
        "delta_speed": 2.4,
        "est_length": 4.3,
        "units": "mph",
        "classification": json.dumps({"car": 0.86, "bike": 0.05}),
        "start_time": now - 2,
        "end_time": now,
        "deployment_id": "deploy-001",
        "created_at": now,
    }
    base.update(overrides)
    return base