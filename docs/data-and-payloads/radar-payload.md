---
description: The five radar tables: detected object velocities, timed counts, raw speed and magnitude readings, and per-object summaries.
---

# Radar

The [OmniPreSense OPS243-A](https://omnipresense.com/product/ops243-doppler-radar-sensor/) Doppler radar measures the speed and direction of whatever moves in front of it, does its own signal processing, and reports readings over USB as JSON. The Traffic Monitor turns on several of the radar's reporting modes when the service starts and stores each kind of reading in its own table. The radar's [API guide](https://omnipresense.com/wp-content/uploads/2023/06/AN-010-Y_API_Interface.pdf) describes the modes and the commands.

| Reading | Radar command | Table | What it is |
|---|---|---|---|
| Detected object velocity | `ON` | `radar_dov` | The radar decides an object is present when it sees two consecutive speed reports, then reports the highest speed, and again if a higher one follows. One or a few readings per object. These readings supply the speeds for [events](events-payload.md). |
| Timed speed counts | `@O`, every 300 seconds | `radar_timed_speed_counts` | How many objects passed in each direction during the interval, and their average speed |
| Raw speed and magnitude | `OS` and `OM` with `O3` | `radar_raw_speed_magnitude` | The three strongest speed and magnitude pairs from each sample. Magnitude reflects the object's size, distance, and reflectivity. |
| Strongest reading | the first of the three above | `radar_raw_speed_magnitude_single` | The single strongest pair from each sample, for easier analysis |
| Object summary | `OC` | `radar_oc_payload` | One row per object, with its time in view, speed range, magnitude, and estimated length. Needs OPS9243 firmware. |

Across the tables, `direction` is `inbound` (toward the radar) or `outbound` (away from it), speeds are positive for inbound and negative for outbound, and the unit is the radar's speed unit, mph by default. `radarName` is the radar's name from [config.yml](../configuration/node-red-config.md#sensorsradars), and `deployment_id` points at the [deployment](data-overview.md#deployment) the reading was taken in.

## radar_dov

| Column | Type | Meaning | Values |
|---|---|---|---|
| `time` | REAL | When the radar took the reading | Unix time in seconds |
| `unit` | TEXT | Speed unit | `mph` |
| `direction` | TEXT | Direction of travel | `inbound` or `outbound` |
| `velocity` | REAL | The object's highest speed so far | Positive inbound, negative outbound |
| `radarName` | TEXT | The radar | |
| `deployment_id` | TEXT | The deployment | |

## radar_timed_speed_counts

| Column | Type | Meaning | Values |
|---|---|---|---|
| `time` | REAL | End of the interval | Unix time in seconds |
| `direction` | TEXT | Direction of travel | `inbound` or `outbound` |
| `units` | TEXT | Speed unit | `mph` |
| `count` | INTEGER | Objects detected in this direction during the interval | 0 or more |
| `average` | REAL | Their average speed | Positive inbound, negative outbound |
| `radarName` | TEXT | The radar | |
| `deployment_id` | TEXT | The deployment | |

## radar_raw_speed_magnitude

| Column | Type | Meaning | Values |
|---|---|---|---|
| `time` | REAL | When the sample was taken | Unix time in seconds |
| `unit` | TEXT | Speed unit | `mph` |
| `magnitude` | TEXT | The three strongest magnitudes in the sample, strongest first | A JSON array of positive numbers |
| `speed` | TEXT | The speeds that go with each magnitude | A JSON array; positive inbound, negative outbound |
| `radarName` | TEXT | The radar | |
| `deployment_id` | TEXT | The deployment | |

## radar_raw_speed_magnitude_single

| Column | Type | Meaning | Values |
|---|---|---|---|
| `time` | REAL | When the sample was taken | Unix time in seconds |
| `unit` | TEXT | Speed unit | `mph` |
| `magnitude` | REAL | The strongest magnitude in the sample | Positive |
| `speed` | REAL | The speed that goes with it | Positive inbound, negative outbound |
| `radarName` | TEXT | The radar | |
| `deployment_id` | TEXT | The deployment | |

## radar_oc_payload

| Column | Type | Meaning | Values |
|---|---|---|---|
| `start_time` | REAL | When the object entered the radar's view | Unix time in seconds |
| `end_time` | REAL | When it left | Unix time in seconds |
| `delta_time_msec` | REAL | Time in view | Milliseconds |
| `direction` | TEXT | Direction of travel | `inbound` or `outbound` |
| `frames_count` | REAL | Radar frames in which the object was seen | A count |
| `velocity_max` | REAL | Highest speed while in view | |
| `velocity_min` | REAL | Lowest speed while in view | |
| `magnitude_max` | REAL | Highest magnitude while in view | |
| `magnitude_mean` | REAL | Average magnitude while in view | |
| `velocity_change` | REAL | `velocity_max` minus `velocity_min`. A vehicle at the edge of the radar's view shows a larger change, from the cosine effect, so this hints at which lane it was in. Dividing by `velocity_max` normalizes it. | |
| `frames_per_velocity` | REAL | `frames_count` ÷ `velocity_max`, the inverse of speed used to estimate length | |
| `object_length` | REAL | Estimated length, from speed and time in view | In the unit's length system: feet for `imperial` |
| `units` | TEXT | Unit system | `imperial` or `metric` |
| `object_label` | TEXT | Reserved for a radar-based object classification | Always empty |
| `radarName` | TEXT | The radar | |
| `deployment_id` | TEXT | The deployment | |
