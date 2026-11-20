-- How long each object stood still, and how long it spent in each zone.
--
-- stationary_time is the total time, in seconds, Frigate held the object as stationary. stops is how
-- many separate times it became stationary. zone_times is a JSON object with a key for each zone
-- Frigate listed the object in, holding the seconds in it and the seconds stationary in it:
-- {"zone_stop_sign_e": {"time": 3.4, "stationary": 0}}. Frigate sends no such times; the flows add
-- them up from the new, update, and end messages it sends while it follows the object. A figure of
-- 21600 means six hours or more. The three are filled together or left empty together, as when
-- Node-RED restarted while the object was being followed.
--
-- This migration only adds columns. Rows written before it keep them empty.

ALTER TABLE events ADD COLUMN stationary_time REAL;
ALTER TABLE events ADD COLUMN stops INTEGER;
ALTER TABLE events ADD COLUMN zone_times TEXT;
