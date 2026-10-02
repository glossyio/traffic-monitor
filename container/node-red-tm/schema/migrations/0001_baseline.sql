-- Baseline: the tables Node-RED created with CREATE TABLE IF NOT EXISTS nodes up to TM 0.6.1.
-- IF NOT EXISTS lets existing devices adopt this version without changing their tables;
-- tmdb_migrate.py reports any table that differs from this shape as drift.

CREATE TABLE IF NOT EXISTS deployment (
    id TEXT PRIMARY KEY,
    entryStartDateTime REAL,
    entryEndDateTime REAL,
    lat REAL,
    lon REAL,
    bearing TEXT,
    sensorType TEXT,
    sensorName TEXT,
    deviceName TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    camera TEXT,
    label TEXT,
    sub_label TEXT,
    top_score REAL,
    frame_time REAL,
    start_time REAL,
    end_time REAL,
    entered_zones TEXT,
    score REAL,
    area REAL,
    ratio REAL,
    motionless_count REAL,
    position_changes REAL,
    attributes TEXT,
    direction_calc TEXT,
    speed_calc REAL,
    provenance TEXT,
    deployment_id TEXT DEFAULT NULL,
    radarName TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS radar_dov (
    time REAL,
    unit TEXT,
    direction TEXT,
    velocity REAL,
    radarName TEXT,
    deployment_id TEXT
);

CREATE TABLE IF NOT EXISTS radar_timed_speed_counts (
    time REAL,
    direction TEXT,
    units TEXT,
    count INTEGER,
    average REAL,
    radarName TEXT,
    deployment_id TEXT
);

CREATE TABLE IF NOT EXISTS radar_raw_speed_magnitude (
    time REAL,
    unit TEXT,
    magnitude TEXT,
    speed TEXT,
    radarName TEXT,
    deployment_id TEXT
);

CREATE TABLE IF NOT EXISTS radar_raw_speed_magnitude_single (
    time REAL,
    unit TEXT,
    magnitude REAL,
    speed REAL,
    radarName TEXT,
    deployment_id TEXT
);

CREATE TABLE IF NOT EXISTS radar_oc_payload (
    start_time REAL,
    end_time REAL,
    delta_time_msec REAL,
    direction TEXT,
    frames_count REAL,
    velocity_max REAL,
    velocity_min REAL,
    magnitude_max REAL,
    magnitude_mean REAL,
    velocity_change REAL,
    frames_per_velocity REAL,
    object_length REAL,
    units TEXT,
    object_label TEXT,
    radarName TEXT,
    deployment_id TEXT
);

CREATE TABLE IF NOT EXISTS airquality (
    entryDateTime REAL,
    gas_calibrated INTEGER,
    temp REAL,
    bar REAL,
    hum REAL,
    dew REAL,
    temp_raw REAL,
    bar_raw REAL,
    hum_raw REAL,
    pm01 REAL,
    pm025 REAL,
    pm10 REAL,
    gas_red REAL,
    gas_oxi REAL,
    gas_nh3 REAL,
    gas_red_raw REAL,
    gas_oxi_raw REAL,
    gas_nh3_raw REAL,
    lux REAL,
    lux_raw REAL,
    proximity REAL,
    sensorName TEXT,
    deployment_id TEXT
);

CREATE TABLE IF NOT EXISTS plate_recognizer (
    event_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    camera_id TEXT NOT NULL,
    processing_time REAL,
    plate_type TEXT,
    plate_score REAL,
    plate_xmin INTEGER,
    plate_ymin INTEGER,
    plate_xmax INTEGER,
    plate_ymax INTEGER,
    plate_value TEXT,
    plate_value_score REAL,
    plate_region_value TEXT,
    plate_region_score REAL,
    vehicle_type TEXT,
    vehicle_score REAL,
    vehicle_xmin INTEGER,
    vehicle_ymin INTEGER,
    vehicle_xmax INTEGER,
    vehicle_ymax INTEGER,
    vehicle_make TEXT,
    vehicle_model TEXT,
    vehicle_make_model_score REAL,
    vehicle_orientation TEXT,
    vehicle_orientation_score REAL,
    vehicle_color TEXT,
    vehicle_color_score REAL,
    json_payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    effectiveDateTime TIMESTAMP,
    expirationDateTime TIMESTAMP,
    entryDateTime TIMESTAMP,
    comment TEXT,
    commenter_name TEXT
);
