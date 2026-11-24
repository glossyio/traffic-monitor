-- The setup history: which model, which software versions, and which camera settings were in force,
-- and when.
--
-- setup_device holds what is true of the whole unit; setup_camera holds what is true of one camera
-- (camera is the key under sensors.cameras in config.yml). started and ended are Unix milliseconds,
-- as in deployment; ended is empty while the row is in force. The JSON columns (labels_available,
-- labels_tracked, thresholds, zones, masks) hold JSON written with sorted keys and no spaces.
-- lens_hfov stays empty until a later change fills it.
--
-- events_with_setup lists every event once, with the setup in force at its start_time. It stores
-- nothing. An event with no row in force has the setup columns empty.
--
-- This migration only adds two tables, two indexes, and one view.

CREATE TABLE setup_device (
    id TEXT PRIMARY KEY,
    started INTEGER NOT NULL,
    ended INTEGER,
    tm_version TEXT,
    tm_commit TEXT,
    schema_version INTEGER,
    frigate_version TEXT,
    unit_system TEXT,
    detector TEXT,
    model_id TEXT,
    model_file TEXT,
    model_sha256 TEXT,
    model_kind TEXT,
    model_title TEXT,
    model_trained_at TEXT,
    model_base TEXT,
    model_type TEXT,
    model_width INTEGER,
    model_height INTEGER,
    labels_available TEXT
);

CREATE TABLE setup_camera (
    id TEXT PRIMARY KEY,
    started INTEGER NOT NULL,
    ended INTEGER,
    camera TEXT NOT NULL,
    detect_width INTEGER,
    detect_height INTEGER,
    detect_fps INTEGER,
    stationary_threshold INTEGER,
    stationary_interval INTEGER,
    lens_hfov REAL,
    labels_tracked TEXT,
    thresholds TEXT,
    zones TEXT,
    masks TEXT,
    profile TEXT
);

CREATE INDEX index_setup_device_started ON setup_device(started);
CREATE INDEX index_setup_camera_camera_started ON setup_camera(camera, started);

-- A later migration that adds a column to either table drops and recreates this view to show it.
-- e.* is read when the view is used, so a column added to events shows up without that.
CREATE VIEW events_with_setup AS
SELECT e.*,
    d.id AS setup_device_id,
    d.tm_version AS setup_tm_version,
    d.tm_commit AS setup_tm_commit,
    d.schema_version AS setup_schema_version,
    d.frigate_version AS setup_frigate_version,
    d.unit_system AS setup_unit_system,
    d.detector AS setup_detector,
    d.model_id AS setup_model_id,
    d.model_file AS setup_model_file,
    d.model_sha256 AS setup_model_sha256,
    d.model_kind AS setup_model_kind,
    d.model_title AS setup_model_title,
    d.model_trained_at AS setup_model_trained_at,
    d.model_base AS setup_model_base,
    d.model_type AS setup_model_type,
    d.model_width AS setup_model_width,
    d.model_height AS setup_model_height,
    d.labels_available AS setup_labels_available,
    c.id AS setup_camera_id,
    c.detect_width AS camera_detect_width,
    c.detect_height AS camera_detect_height,
    c.detect_fps AS camera_detect_fps,
    c.stationary_threshold AS camera_stationary_threshold,
    c.stationary_interval AS camera_stationary_interval,
    c.lens_hfov AS camera_lens_hfov,
    c.labels_tracked AS camera_labels_tracked,
    c.thresholds AS camera_thresholds,
    c.zones AS camera_zones,
    c.masks AS camera_masks,
    c.profile AS camera_profile
FROM events e
LEFT JOIN setup_device d ON d.id = (
    SELECT s.id FROM setup_device s
    WHERE s.started <= e.start_time * 1000 AND (s.ended IS NULL OR s.ended > e.start_time * 1000)
    ORDER BY s.started DESC, s.id DESC LIMIT 1)
LEFT JOIN setup_camera c ON c.id = (
    SELECT s.id FROM setup_camera s
    WHERE s.camera = e.camera AND s.started <= e.start_time * 1000
        AND (s.ended IS NULL OR s.ended > e.start_time * 1000)
    ORDER BY s.started DESC, s.id DESC LIMIT 1);
