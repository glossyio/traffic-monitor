-- Survey ids and stored location precision for deployment rows, plus an index for counting
-- a survey's events.
--
-- This migration rewrites existing data. Every deployment row whose lat and lon are both numbers
-- gets a survey_id, one per exact (lat, lon) place, assigned before rounding, so rows at the same
-- spot share an id. Then those coordinates are rounded to two decimal places (about 1 km), the
-- default precision, and location_precision is set to 2. Any other row (one of lat and lon
-- missing, or either stored as text, such as '') gets NULL for both, no survey_id, and no
-- precision.
--
-- The exact coordinates are not kept in this database. Before applying this file, the runner
-- copies the database to db/backup/tmdb-v<version>-<UTC time>.sqlite, and that copy holds the
-- rows as they were. A unit upgrading from a release (0.7.1 or earlier) is at version 0 and
-- adopts the baseline on the same start, so its copy is tmdb-v0-...; a unit that already ran a
-- development build with the baseline has tmdb-v1-.... If the disk is too full for the copy,
-- the runner logs a warning and skips it.

ALTER TABLE deployment ADD COLUMN survey_id TEXT;
ALTER TABLE deployment ADD COLUMN location_precision INTEGER;

CREATE TEMP TABLE deployment_place_survey AS
    SELECT lat, lon, lower(hex(randomblob(4))) || '-si' AS survey_id
    FROM (SELECT DISTINCT lat, lon FROM deployment
          WHERE typeof(lat) IN ('real', 'integer') AND typeof(lon) IN ('real', 'integer'));

UPDATE deployment SET survey_id = (
    SELECT place.survey_id FROM deployment_place_survey AS place
    WHERE place.lat = deployment.lat AND place.lon = deployment.lon
)
WHERE typeof(lat) IN ('real', 'integer') AND typeof(lon) IN ('real', 'integer');

DROP TABLE deployment_place_survey;

UPDATE deployment SET lat = ROUND(lat, 2), lon = ROUND(lon, 2), location_precision = 2
WHERE typeof(lat) IN ('real', 'integer') AND typeof(lon) IN ('real', 'integer');

-- Every row the step above did not round: no location, so no survey_id either.
UPDATE deployment SET lat = NULL, lon = NULL
WHERE location_precision IS NULL;

-- Speeds up counting and listing the events of a deployment, and so of a survey.
CREATE INDEX IF NOT EXISTS index_events_deployment_id ON events(deployment_id);
