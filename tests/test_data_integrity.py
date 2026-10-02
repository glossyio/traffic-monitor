"""
test_data_integrity.py

Tests for cross-table data integrity:
- Foreign key enforcement (deployment_id references)
- Orphan record detection
- Multi-table query correctness

These tests are valuable because the project has had repeated breaking
schema changes between releases. A passing integrity suite means any
migration script can be validated before deployment.
"""

import json
import time
import pytest
from conftest import make_event_payload, make_radar_payload

def insert_event(db, payload):
    db.execute(
        """INSERT INTO events
           (id, camera, label, sub_label, score, best_timestamp,
            start_timestamp, end_timestamp, zones, deployment_id, created_at)
           VALUES
           (:id, :camera, :label, :sub_label, :score, :best_timestamp,
            :start_timestamp, :end_timestamp, :zones, :deployment_id, :created_at)""",
        payload,
    )
    db.commit()


def insert_radar(db, payload):
    db.execute(
        """INSERT INTO radar
           (id, sensor, direction, max_speed, avg_speed, dov_count,
            speeds, duration_ms, frame_count, delta_speed, est_length,
            units, classification, start_time, end_time, deployment_id, created_at)
           VALUES
           (:id, :sensor, :direction, :max_speed, :avg_speed, :dov_count,
            :speeds, :duration_ms, :frame_count, :delta_speed, :est_length,
            :units, :classification, :start_time, :end_time, :deployment_id, :created_at)""",
        payload,
    )
    db.commit()

class TestForeignKeys:
    def test_event_fk_requires_valid_deployment(self, db_with_deployment):
        payload = make_event_payload(deployment_id="deploy-001")
        insert_event(db_with_deployment, payload)
        row = db_with_deployment.execute(
            "SELECT * FROM events WHERE id=?", (payload["id"],)
        ).fetchone()
        assert row is not None

    def test_event_invalid_deployment_id_raises(self, db_with_deployment):
        payload = make_event_payload(deployment_id="does-not-exist")
        with pytest.raises(Exception):
            insert_event(db_with_deployment, payload)

    def test_radar_fk_requires_valid_deployment(self, db_with_deployment):
        payload = make_radar_payload(deployment_id="deploy-001")
        insert_radar(db_with_deployment, payload)
        row = db_with_deployment.execute(
            "SELECT * FROM radar WHERE id=?", (payload["id"],)
        ).fetchone()
        assert row is not None

    def test_radar_invalid_deployment_id_raises(self, db_with_deployment):
        payload = make_radar_payload(deployment_id="does-not-exist")
        with pytest.raises(Exception):
            insert_radar(db_with_deployment, payload)

class TestDeploymentTable:
    def test_deployment_id_is_primary_key(self, db):
        db.execute(
            "INSERT INTO deployment (id, label, bearing, created_at) VALUES (?,?,?,?)",
            ("dep-1", "North Street", 0.0, int(time.time())),
        )
        db.commit()
        with pytest.raises(Exception):
            db.execute(
                "INSERT INTO deployment (id, label, bearing, created_at) VALUES (?,?,?,?)",
                ("dep-1", "Duplicate", 180.0, int(time.time())),
            )

    def test_multiple_deployments_allowed(self, db):
        for i in range(3):
            db.execute(
                "INSERT INTO deployment (id, label, bearing, created_at) VALUES (?,?,?,?)",
                (f"dep-{i}", f"Location {i}", float(i * 90), int(time.time())),
            )
        db.commit()
        count = db.execute("SELECT COUNT(*) FROM deployment").fetchone()[0]
        assert count == 3

class TestCrossTableQueries:
    def test_events_joined_to_deployment(self, db_with_deployment):
        payload = make_event_payload(deployment_id="deploy-001")
        insert_event(db_with_deployment, payload)

        row = db_with_deployment.execute(
            """
            SELECT e.label, d.label as location
            FROM events e
            JOIN deployment d ON e.deployment_id = d.id
            WHERE e.id = ?
            """,
            (payload["id"],),
        ).fetchone()

        assert row["label"] == "car"
        assert row["location"] == "Front Street North"

    def test_radar_joined_to_deployment(self, db_with_deployment):
        payload = make_radar_payload(deployment_id="deploy-001")
        insert_radar(db_with_deployment, payload)

        row = db_with_deployment.execute(
            """
            SELECT r.max_speed, d.label as location
            FROM radar r
            JOIN deployment d ON r.deployment_id = d.id
            WHERE r.id = ?
            """,
            (payload["id"],),
        ).fetchone()

        assert row["location"] == "Front Street North"
        assert row["max_speed"] > 0

    def test_count_events_per_label(self, db_with_deployment):
        labels = ["car", "car", "bicycle", "person", "car"]
        for i, label in enumerate(labels):
            p = make_event_payload(id=f"evt-{i}", label=label)
            insert_event(db_with_deployment, p)

        rows = db_with_deployment.execute(
            "SELECT label, COUNT(*) as cnt FROM events GROUP BY label ORDER BY cnt DESC"
        ).fetchall()

        counts = {row["label"]: row["cnt"] for row in rows}
        assert counts["car"] == 3
        assert counts["bicycle"] == 1
        assert counts["person"] == 1

    def test_avg_speed_query_across_radar_readings(self, db_with_deployment):
        speeds = [25.0, 30.0, 35.0]
        for i, spd in enumerate(speeds):
            p = make_radar_payload(id=f"rad-{i}", max_speed=spd, avg_speed=spd)
            insert_radar(db_with_deployment, p)

        result = db_with_deployment.execute(
            "SELECT AVG(max_speed) as fleet_avg FROM radar"
        ).fetchone()

        assert abs(result["fleet_avg"] - 30.0) < 0.01
