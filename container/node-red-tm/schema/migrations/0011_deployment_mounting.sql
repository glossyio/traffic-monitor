-- How a sensor is mounted, as four more facts on a deployment (heading_deg, from 0008, is the fifth).
--
--   pitch_deg        tilt below level, in degrees (REAL)
--   height_m         height above the road, in metres (REAL)
--   view_distance_m  distance along the ground to the centre of the view, in metres (REAL)
--   mount            the usual mount the values were started from, such as tripod or pole (TEXT)
--
-- Every value is optional. Every row that exists keeps NULL in all four, and no row is rewritten.
-- The limits are checked where the values are read from config.yml, not here.

ALTER TABLE deployment ADD COLUMN pitch_deg REAL;
ALTER TABLE deployment ADD COLUMN height_m REAL;
ALTER TABLE deployment ADD COLUMN view_distance_m REAL;
ALTER TABLE deployment ADD COLUMN mount TEXT;
