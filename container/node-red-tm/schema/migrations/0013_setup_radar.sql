-- The radar's setup history: which model and firmware a radar reported, and the settings it said it
-- was using, and when.
--
-- setup_radar holds one row for each stretch in which a radar's answers stayed the same. radar is the
-- key under sensors.radars in config.yml. started and ended are Unix milliseconds, as in the other
-- setup tables; ended is empty while the row is in force. The other columns are what the radar
-- answered, and a value it didn't answer is NULL, never 0:
--   part_number          the radar's model (its Product answer)
--   firmware_version     its Version answer
--   cosine_inbound_deg   the angle it says it corrects traffic coming toward it by, in degrees
--   cosine_outbound_deg  the same for traffic going away, in degrees
--   speed_unit           the unit of its speeds (its Units answer)
--   sampling_rate        samples per second (its SamplingRate answer)
--   speed_min            the lowest speed it reports, in speed_unit
--   magnitude_min        the lowest signal strength it reports
--
-- events_with_setup gains the radar's columns for the radar named in the event's radarName, in force at
-- the event's start_time: setup_radar_id, and each of the eight as radar_<column>. An event with no
-- radar, or no row in force, has them empty.
--
-- This migration adds one table and one index, and recreates the view with every column it had, in
-- the same order, and then the radar's.

CREATE TABLE setup_radar (
    id TEXT PRIMARY KEY,
    started INTEGER NOT NULL,
    ended INTEGER,
    radar TEXT NOT NULL,
    part_number TEXT,
    firmware_version TEXT,
    cosine_inbound_deg REAL,
    cosine_outbound_deg REAL,
    speed_unit TEXT,
    sampling_rate INTEGER,
    speed_min REAL,
    magnitude_min REAL
);

CREATE INDEX index_setup_radar_radar_started ON setup_radar(radar, started);

DROP VIEW events_with_setup;

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
    c.profile AS camera_profile,
    r.id AS setup_radar_id,
    r.part_number AS radar_part_number,
    r.firmware_version AS radar_firmware_version,
    r.cosine_inbound_deg AS radar_cosine_inbound_deg,
    r.cosine_outbound_deg AS radar_cosine_outbound_deg,
    r.speed_unit AS radar_speed_unit,
    r.sampling_rate AS radar_sampling_rate,
    r.speed_min AS radar_speed_min,
    r.magnitude_min AS radar_magnitude_min
FROM events e
LEFT JOIN setup_device d ON d.id = (
    SELECT s.id FROM setup_device s
    WHERE s.started <= e.start_time * 1000 AND (s.ended IS NULL OR s.ended > e.start_time * 1000)
    ORDER BY s.started DESC, s.id DESC LIMIT 1)
LEFT JOIN setup_camera c ON c.id = (
    SELECT s.id FROM setup_camera s
    WHERE s.camera = e.camera AND s.started <= e.start_time * 1000
        AND (s.ended IS NULL OR s.ended > e.start_time * 1000)
    ORDER BY s.started DESC, s.id DESC LIMIT 1)
LEFT JOIN setup_radar r ON r.id = (
    SELECT s.id FROM setup_radar s
    WHERE s.radar = e.radarName AND s.started <= e.start_time * 1000
        AND (s.ended IS NULL OR s.ended > e.start_time * 1000)
    ORDER BY s.started DESC, s.id DESC LIMIT 1);
