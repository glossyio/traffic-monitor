-- tmdb-migrate: needs-column deployment.bearing
-- The heading takes the place of the bearing: each row's heading_deg is filled from its bearing.
--
-- This migration rewrites data. Each deployment row that has no heading_deg yet (0008 added the
-- column) takes it from its bearing: one of the eight compass points, after trimming (spaces, tabs,
-- and line breaks) and lower-casing, becomes the heading of the point's centre (n 0, ne 45, e 90,
-- se 135, s 180, sw 225, w 270, nw 315). Any other value (empty, NULL, the text 'null' or
-- 'undefined', a word, a number) leaves the heading NULL. A row that already has a heading keeps
-- it: Node-RED writes headings from version 8 on, and a row it wrote has no bearing.
--
-- The next file, 0010, drops the bearing column. They are two files so that a drop that fails (a
-- view, an index, or a trigger on the device names the column) leaves the rows converted at
-- version 9, where Node-RED compares real headings.
--
-- The first line tells the runner to apply this file only to a database whose deployment table has
-- a bearing. An older table shape without one skips it and keeps its version.
--
-- The bearing column still holds the old text after this file. The runner also copies the database
-- to db/backup/tmdb-v<version>-<UTC time>.sqlite before applying the pending files.

UPDATE deployment SET heading_deg = CASE lower(trim(bearing, ' ' || char(9, 10, 11, 12, 13)))
    WHEN 'n' THEN 0 WHEN 'ne' THEN 45 WHEN 'e' THEN 90 WHEN 'se' THEN 135
    WHEN 's' THEN 180 WHEN 'sw' THEN 225 WHEN 'w' THEN 270 WHEN 'nw' THEN 315 END
WHERE heading_deg IS NULL;
