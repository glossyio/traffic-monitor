-- Where a sensor points and what the street in its view looks like, as eight more facts on a deployment.
--
--   road_angle_deg   angle into the road: 0 is straight along it, 90 is straight across;
--                    0 to 89 degrees, one decimal (REAL). Radars.
--   lane_distance_m  straight across to the near edge of the first lane that carries traffic;
--                    0 to 100 metres, two decimals (REAL). Radars.
--   lane_width_m     width of one lane; above 0 and at most 10 metres, two decimals (REAL). Radars.
--   lanes_toward     lanes coming toward the unit; 0 to 3 (INTEGER). Radars.
--   lanes_away       lanes going away from the unit; 0 to 3 (INTEGER). Radars.
--   turn_lane        a turning lane in the middle; 1 or NULL (INTEGER). Radars.
--   toward_side      the side the traffic toward the unit is on, near or far (TEXT). Radars.
--   intersection     this view takes in an intersection; 1 or NULL (INTEGER). Radars and cameras.
--
-- Every value is optional. Every row that exists keeps NULL in all eight, and no row is rewritten.
-- A new deployment starts only when road_angle_deg changes; Node-RED corrects the other seven in the open row.
-- The limits are checked where the values are read from config.yml, not here.

ALTER TABLE deployment ADD COLUMN road_angle_deg REAL;
ALTER TABLE deployment ADD COLUMN lane_distance_m REAL;
ALTER TABLE deployment ADD COLUMN lane_width_m REAL;
ALTER TABLE deployment ADD COLUMN lanes_toward INTEGER;
ALTER TABLE deployment ADD COLUMN lanes_away INTEGER;
ALTER TABLE deployment ADD COLUMN turn_lane INTEGER;
ALTER TABLE deployment ADD COLUMN toward_side TEXT;
ALTER TABLE deployment ADD COLUMN intersection INTEGER;
