-- Survey ids and stored location precision for deployment rows, plus an index for counting
-- a survey's events.
--
-- This migration rewrites existing data. Every deployment row that has both lat and lon gets a
-- survey_id, one per exact (lat, lon) place, assigned before rounding, so rows at the same spot
-- share an id. Then those coordinates are rounded to one decimal place (about 11 km) and
-- location_precision is set to 1. A row with only one of lat and lon gets NULL for both, no
-- survey_id, and no precision.
--
-- The exact coordinates are not kept in this database. Before applying this file, the runner
-- copies the database to db/backup/tmdb-v<version>-<UTC time>.sqlite (tmdb-v1-..., or tmdb-v0-...
-- on a database that adopts the baseline on the same start), and that copy holds the rows as
-- they were. If the disk is too full for the copy, the runner logs a warning and skips it.

ALTER TABLE deployment ADD COLUMN survey_id TEXT;
ALTER TABLE deployment ADD COLUMN location_precision INTEGER;

CREATE TEMP TABLE deployment_place_survey AS
    SELECT lat, lon, lower(hex(randomblob(4))) || '-si' AS survey_id
    FROM (SELECT DISTINCT lat, lon FROM deployment WHERE lat IS NOT NULL AND lon IS NOT NULL);

UPDATE deployment SET survey_id = (
    SELECT place.survey_id FROM deployment_place_survey AS place
    WHERE place.lat = deployment.lat AND place.lon = deployment.lon
)
WHERE lat IS NOT NULL AND lon IS NOT NULL;

DROP TABLE deployment_place_survey;

UPDATE deployment SET lat = ROUND(lat, 1), lon = ROUND(lon, 1), location_precision = 1
WHERE lat IS NOT NULL AND lon IS NOT NULL;

UPDATE deployment SET lat = NULL, lon = NULL
WHERE lat IS NULL OR lon IS NULL;

-- Speeds up counting and listing the events of a deployment, and so of a survey.
CREATE INDEX IF NOT EXISTS index_events_deployment_id ON events(deployment_id);
