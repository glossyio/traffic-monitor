-- More of what Frigate sends about each event, and where its speed came from.
--
-- path_data is the object's path across the picture, a JSON list of [[x, y], t] points. box and
-- best_box are the object's box at the last frame and at the best frame, as JSON
-- [left, top, width, height] fractions of the frame, and best_frame_time is the best frame's time.
-- frigate_speed, frigate_speed_unit, and frigate_velocity_angle are Frigate's own speed estimate,
-- its unit, and its angle, as Frigate sent them. speed_unit is the unit of speed_calc,
-- speed_source says whether speed_calc came from the radar or from Frigate, and radar_readings is
-- how many radar readings stand behind a radar speed. direction_source says how direction_calc was
-- decided: zones_radar, zones, zones_radar_opposite (the radar saw only the other way), or radar.
--
-- This migration only adds columns. Rows written before it keep them empty; their speed_calc,
-- when they have one, came from the radar.

ALTER TABLE events ADD COLUMN path_data TEXT;
ALTER TABLE events ADD COLUMN box TEXT;
ALTER TABLE events ADD COLUMN best_box TEXT;
ALTER TABLE events ADD COLUMN best_frame_time REAL;
ALTER TABLE events ADD COLUMN frigate_speed REAL;
ALTER TABLE events ADD COLUMN frigate_speed_unit TEXT;
ALTER TABLE events ADD COLUMN frigate_velocity_angle REAL;
ALTER TABLE events ADD COLUMN speed_unit TEXT;
ALTER TABLE events ADD COLUMN speed_source TEXT;
ALTER TABLE events ADD COLUMN radar_readings INTEGER;
ALTER TABLE events ADD COLUMN direction_source TEXT;
