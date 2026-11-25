-- tmdb-migrate: needs-column deployment.bearing
-- The bearing column goes: 0009 filled heading_deg from it.
--
-- This migration drops a column, and with it each row's old bearing text. It fails, and is rolled
-- back, while a view, an index, or a trigger on the device names the column; the rows keep the
-- headings 0009 gave them, and the next start tries again.
--
-- The first line tells the runner to apply this file only to a database whose deployment table has
-- a bearing. An older table shape without one skips it and keeps its version.
--
-- The old text is not kept in this database. Before applying the pending files, the runner copies
-- the database to db/backup/tmdb-v<version>-<UTC time>.sqlite, and that copy holds the bearings as
-- they were. If the disk is too full for the copy, the runner logs a warning and skips it.

ALTER TABLE deployment DROP COLUMN bearing;
