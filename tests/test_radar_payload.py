"""
test_radar_payload.py

Tests for radar payload structure, field types, and DB insertion.
Based on the documented Radar Payload:
  https://docs.trafficmonitor.ai/sensor-payloads/radar-payload

Radar sensor: OmniPreSence OPS243-A Doppler Radar
"""

import json
import pytest
from conftest import make_radar_payload

def insert_radar(db, payload):
    db.execute(
        """
        INSERT INTO radar
            (id, sensor, direction, max_speed, avg_speed, dov_count, speeds,
             duration_ms, frame_count, delta_speed, est_length, units,
             classification, start_time, end_time, deployment_id, created_at)
        VALUES
            (:id, :sensor, :direction, :max_speed, :avg_speed, :dov_count, :speeds,
             :duration_ms, :frame_count, :delta_speed, :est_length, :units,
             :classification, :start_time, :end_time, :deployment_id, :created_at)
        """,
        payload,
    )
    db.commit()

class TestRadarInsertion:
    def test_valid_reading_inserts(self, db_with_deployment):
        payload = make_radar_payload()
        insert_radar(db_with_deployment, payload)
        row = db_with_deployment.execute(
            "SELECT * FROM radar WHERE id=?", (payload["id"],)
        ).fetchone()
        assert row is not None
        assert row["sensor"] == "radar_front"

    def test_missing_sensor_raises(self, db_with_deployment):
        payload = make_radar_payload(sensor=None)
        with pytest.raises(Exception):
            insert_radar(db_with_deployment, payload)

    def test_duplicate_id_raises(self, db_with_deployment):
        payload = make_radar_payload()
        insert_radar(db_with_deployment, payload)
        with pytest.raises(Exception):
            insert_radar(db_with_deployment, payload)

class TestRadarDirection:
    VALID_DIRECTIONS = {"inbound", "outbound"}

    def test_inbound_is_valid(self):
        payload = make_radar_payload(direction="inbound")
        assert payload["direction"] in self.VALID_DIRECTIONS

    def test_outbound_is_valid(self):
        payload = make_radar_payload(direction="outbound")
        assert payload["direction"] in self.VALID_DIRECTIONS

    def test_invalid_direction_stored_without_constraint(self, db_with_deployment):
        payload = make_radar_payload(direction="sideways")
        insert_radar(db_with_deployment, payload)
        row = db_with_deployment.execute(
            "SELECT direction FROM radar WHERE id=?", (payload["id"],)
        ).fetchone()
        assert row["direction"] == "sideways"

class TestRadarSpeedFields:
    def test_max_speed_gte_avg_speed(self):
        payload = make_radar_payload(max_speed=30.0, avg_speed=25.0)
        assert payload["max_speed"] >= payload["avg_speed"]

    def test_delta_speed_equals_max_minus_min(self):
        speeds = [28.5, 27.2, 26.1]
        delta = max(speeds) - min(speeds)
        payload = make_radar_payload(
            speeds=json.dumps(speeds),
            delta_speed=round(delta, 2),
        )
        parsed_speeds = json.loads(payload["speeds"])
        assert abs((max(parsed_speeds) - min(parsed_speeds)) - payload["delta_speed"]) < 0.01

    def test_negative_speed_stored_without_constraint(self, db_with_deployment):
        payload = make_radar_payload(max_speed=-5.0, avg_speed=-5.0)
        insert_radar(db_with_deployment, payload)
        row = db_with_deployment.execute(
            "SELECT max_speed FROM radar WHERE id=?", (payload["id"],)
        ).fetchone()
        assert row["max_speed"] < 0

    def test_speeds_array_is_valid_json(self):
        payload = make_radar_payload(speeds=json.dumps([28.5, 27.2, 26.1]))
        parsed = json.loads(payload["speeds"])
        assert isinstance(parsed, list)
        assert all(isinstance(s, (int, float)) for s in parsed)

    def test_dov_count_matches_speeds_array_length(self):
        speeds = [28.5, 27.2, 26.1]
        payload = make_radar_payload(
            speeds=json.dumps(speeds),
            dov_count=len(speeds),
        )
        assert payload["dov_count"] == len(json.loads(payload["speeds"]))

class TestRadarUnits:
    VALID_UNITS = {"mph", "kph"}

    def test_mph_is_valid(self):
        payload = make_radar_payload(units="mph")
        assert payload["units"] in self.VALID_UNITS

    def test_kph_is_valid(self):
        payload = make_radar_payload(units="kph")
        assert payload["units"] in self.VALID_UNITS

class TestRadarClassification:
    def test_classification_is_valid_json_object(self):
        payload = make_radar_payload(
            classification=json.dumps({"car": 0.86, "bike": 0.05, "person": 0.10})
        )
        parsed = json.loads(payload["classification"])
        assert isinstance(parsed, dict)

    def test_classification_scores_between_0_and_1(self):
        clf = {"car": 0.86, "bike": 0.05, "person": 0.10}
        payload = make_radar_payload(classification=json.dumps(clf))
        parsed = json.loads(payload["classification"])
        for label, score in parsed.items():
            assert 0.0 <= score <= 1.0, f"{label} score {score} out of range"
