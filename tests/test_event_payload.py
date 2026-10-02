"""
test_event_payload.py

Tests for event payload structure, field types, and DB insertion.
Based on the documented Events Payload:
  https://docs.trafficmonitor.ai/sensor-payloads/events-payload
"""

import json
import time
import pytest
from conftest import make_event_payload

def insert_event(db, payload):
    db.execute(
        """
        INSERT INTO events
            (id, camera, label, sub_label, score, best_timestamp,
             start_timestamp, end_timestamp, zones, deployment_id, created_at)
        VALUES
            (:id, :camera, :label, :sub_label, :score, :best_timestamp,
             :start_timestamp, :end_timestamp, :zones, :deployment_id, :created_at)
        """,
        payload,
    )
    db.commit()

class TestEventInsertion:
    def test_valid_event_inserts(self, db_with_deployment):
        payload = make_event_payload()
        insert_event(db_with_deployment, payload)
        row = db_with_deployment.execute(
            "SELECT * FROM events WHERE id = ?", (payload["id"],)
        ).fetchone()
        assert row is not None
        assert row["label"] == "car"

    def test_duplicate_id_raises(self, db_with_deployment):
        payload = make_event_payload()
        insert_event(db_with_deployment, payload)
        with pytest.raises(Exception):
            insert_event(db_with_deployment, payload)

    def test_missing_camera_raises(self, db_with_deployment):
        payload = make_event_payload(camera=None)
        with pytest.raises(Exception):
            insert_event(db_with_deployment, payload)

    def test_missing_label_raises(self, db_with_deployment):
        payload = make_event_payload(label=None)
        with pytest.raises(Exception):
            insert_event(db_with_deployment, payload)

class TestEventTimestamps:
    def test_end_after_start(self):
        payload = make_event_payload()
        assert payload["end_timestamp"] >= payload["start_timestamp"]

    def test_inverted_timestamps_stored_but_invalid(self, db_with_deployment):
        now = int(time.time())
        payload = make_event_payload(
            start_timestamp=now,
            end_timestamp=now - 10
        )
        insert_event(db_with_deployment, payload)
        row = db_with_deployment.execute(
            "SELECT * FROM events WHERE id=?", (payload["id"],)
        ).fetchone()
        assert row["end_timestamp"] < row["start_timestamp"]

    def test_best_timestamp_between_start_and_end(self):
        now = int(time.time())
        payload = make_event_payload(
            start_timestamp=now - 5,
            best_timestamp=now - 2,
            end_timestamp=now,
        )
        assert payload["start_timestamp"] <= payload["best_timestamp"] <= payload["end_timestamp"]

class TestEventScore:
    def test_score_between_0_and_1(self):
        payload = make_event_payload(score=0.87)
        assert 0.0 <= payload["score"] <= 1.0

    def test_score_above_1_stored_without_constraint(self, db_with_deployment):
        payload = make_event_payload(score=1.5)
        insert_event(db_with_deployment, payload)
        row = db_with_deployment.execute(
            "SELECT score FROM events WHERE id=?", (payload["id"],)
        ).fetchone()
        assert row["score"] == 1.5

class TestEventZones:
    def test_zones_is_valid_json_array(self):
        payload = make_event_payload(zones=json.dumps(["zone_road", "zone_sidewalk"]))
        parsed = json.loads(payload["zones"])
        assert isinstance(parsed, list)
        assert all(isinstance(z, str) for z in parsed)

    def test_empty_zones_allowed(self, db_with_deployment):
        payload = make_event_payload(zones=json.dumps([]))
        insert_event(db_with_deployment, payload)
        row = db_with_deployment.execute(
            "SELECT zones FROM events WHERE id=?", (payload["id"],)
        ).fetchone()
        assert json.loads(row["zones"]) == []

class TestKnownObjectLabels:
    VALID_LABELS = {"car", "bicycle", "person", "motorcycle", "truck", "bus", "dog", "cat"}

    def test_car_is_valid_label(self):
        payload = make_event_payload(label="car")
        assert payload["label"] in self.VALID_LABELS

    def test_unknown_label_not_in_expected_set(self):
        payload = make_event_payload(label="ufo")
        assert payload["label"] not in self.VALID_LABELS
