-- The time zone of the place a deployment was recorded at, as one more fact on a deployment.
--
--   timezone  an IANA name such as America/New_York (TEXT)
--
-- The value is optional. Every row that exists keeps NULL, and no row is rewritten.
-- The name is checked where it is read from config.yml and from a request, not here.

ALTER TABLE deployment ADD COLUMN timezone TEXT;
