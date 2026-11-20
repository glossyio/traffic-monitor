-- The watch log: what each camera and each radar was doing, one row per sensor for each
-- five-minute window.
--
-- watch_camera and watch_radar hold one row per sensor for the five minutes that end at time
-- (Unix seconds). Every column is a number, 0 or 1, or a key from config.yml (camera, radar) or a
-- deployment id. A window with no row means Node-RED didn't see the whole window.
--
-- These are the first WITHOUT ROWID tables in tmdb: the rows are small and have a primary key, so
-- the key isn't stored twice. This migration only adds tables.

CREATE TABLE watch_camera (
    time INTEGER NOT NULL,
    camera TEXT NOT NULL,
    config_enabled INTEGER,
    deployment_id TEXT,
    frigate_answers INTEGER,
    camera_answers INTEGER,
    camera_fps REAL,
    process_fps REAL,
    skipped_fps REAL,
    detection_fps REAL,
    detection_enabled INTEGER,
    camera_on INTEGER,
    PRIMARY KEY (time, camera)
) WITHOUT ROWID;

CREATE TABLE watch_radar (
    time INTEGER NOT NULL,
    radar TEXT NOT NULL,
    config_enabled INTEGER,
    deployment_id TEXT,
    port_open INTEGER,
    last_reading_at REAL,
    PRIMARY KEY (time, radar)
) WITHOUT ROWID;
