"""
test_db_schema.py

Validates that the in-memory DB has the tables and columns documented at:
    https://docs.trafficmonitor.ai/sensor-payloads/events-payload
    https://docs.trafficmonitor.ai/sensor-payloads/radar-payload
    
These tests fail if the schema changes without tests being updated.
"""

import pytest

def get_columns(db, table):
    cursor = db.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in cursor.fetchall()}

def get_tables(db):
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row["name"] for row in cursor.fetchall()}

class TestTablesExist:
    def test_deployment_table_exists(self, db):
        assert "deployment" in get_tables(db)

    def test_events_table_exists(self, db):
        assert "events" in get_tables(db)

    def test_radar_table_exists(self, db):
        assert "radar" in get_tables(db)

class TestDeploymentColumns:
    REQUIRED = {"id", "label", "bearing", "created_at"}

    def test_required_columns_present(self, db):
        cols = get_columns(db, "deployment")
        missing = self.REQUIRED - cols
        assert not missing, f"deployment table missing columns: {missing}"
    
class TestEventsColumns:
    REQUIRED = {
        "id", "camera", "label", "score", "best_timestamp", "start_timestamp",
        "end_timestamp", "zones", "deployment_id", "created_at",
    }

    def test_required_columns_present(self, db):
        cols = get_columns(db, "events")
        missing = self.REQUIRED - cols
        assert not missing, f"events table missing columns: {missing}"

class TestRadarColumns:
    REQUIRED = {
        "id", "sensor", "direction", "max_speed", "avg_speed", "dov_count",
        "speeds", "duration_ms", "frame_count", "delta_speed", "est_length",
        "units", "classification", "start_time", "end_time", "deployment_id",
        "created_at",
    }

    def test_required_columns_present(self, db):
        cols = get_columns(db, "radar")
        missing = self.REQUIRED - cols
        assert not missing, f"radar table missing columns: {missing}"
