-- The direction a sensor faces, as a heading in whole degrees clockwise from true north.
--
-- This migration adds the column and changes no row. The next two files fill it from each row's
-- bearing (0009) and drop that column (0010). They are separate files because 0009 and 0010 apply
-- only to a table that has a bearing, and this one applies to every shape of the deployment table.

ALTER TABLE deployment ADD COLUMN heading_deg INTEGER;
