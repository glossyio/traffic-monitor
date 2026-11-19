---
description: The two watch log tables, which record every five minutes whether each camera and radar was working, so that a quiet road can be told from a sensor that was off.
---

# Watch log

An hour with no events looks the same whether the road was empty or nothing was watching it. The watch log tells the two apart. Every five minutes the device writes one row for each camera and one for each radar, saying what that sensor was doing.

Cameras go in `watch_camera` and radars in `watch_radar`. Both tables are in the database, in the [Data export](../ui/database.md) page's database download.

## What a row covers

A row covers the five minutes that end at its `time`, which is always a multiple of five minutes on the device's clock. There is a row for every camera and radar listed in [config.yml](../configuration/node-red-config.md#sensorscameras), whether it is enabled or not, so a sensor that was switched off shows up as a row with `enabled` 0 rather than as a gap.

A window with no row means Node-RED didn't see that whole window. That covers every window a restart, a reboot, or a power cut touched, from the one Node-RED stopped in through the one it started in: one window for a quick restart, more for a longer outage. The first row after a start comes at the second five-minute mark, five to ten minutes later. It also covers a window in which the device's clock jumped. If the clock is set back by more than about ten minutes, the times that come round again keep their first rows on the device, while the upload sends the new ones. Treat a missing window as unknown, not as working or as not working.

## watch_camera

One row for each camera and window. The primary key is `time` and `camera`.

| Column | Type | Meaning | Values |
|---|---|---|---|
| `time` | INTEGER | End of the five-minute window | Unix time in seconds |
| `camera` | TEXT | The camera's name in `config.yml`, the same name as `events.camera` | |
| `enabled` | INTEGER | Whether the camera's entry in `config.yml` was enabled | `1` or `0` |
| `deployment_id` | TEXT | The [deployment](data-overview.md#deployment) the camera had | Empty if it has none, or while the camera is off |
| `frigate_answered` | INTEGER | Whether Frigate sent any status report in the window | `1` or `0` |
| `stats_messages` | INTEGER | How many of Frigate's reports in the window included this camera. Frigate reports once a minute unless its `mqtt.stats_interval` setting was changed, so a full window has about 5. | 0 or more |
| `camera_fps` | REAL | Frames per second the camera delivered, averaged over the reports | Empty when `stats_messages` is 0 |
| `process_fps` | REAL | Frames per second Frigate processed | Empty when `stats_messages` is 0 |
| `skipped_fps` | REAL | Frames per second Frigate skipped because it was behind | Empty when `stats_messages` is 0 |
| `detection_fps` | REAL | Regions per second sent to the detector. Frigate can send several regions of one frame, so this can be higher than `camera_fps`. | Empty when `stats_messages` is 0 |
| `detection_enabled` | INTEGER | Whether detection was on for the whole window. It is 0 when detection was off in any report of the window. | `1` or `0`; empty when `stats_messages` is 0 |

The four frame rates are means of the reports in the window, rounded to two decimals.

## watch_radar

One row for each radar and window. The primary key is `time` and `radar`.

| Column | Type | Meaning | Values |
|---|---|---|---|
| `time` | INTEGER | End of the five-minute window | Unix time in seconds |
| `radar` | TEXT | The radar's name in [config.yml](../configuration/node-red-config.md#sensorsradars), the same as `radarName` in the radar tables | |
| `enabled` | INTEGER | Whether the radar's entry in `config.yml` was enabled | `1` or `0` |
| `deployment_id` | TEXT | The [deployment](data-overview.md#deployment) the radar had | Empty if it has none, or while the radar is off |
| `port_open` | INTEGER | Whether the device had the radar's serial port open, as at `time` | `1` or `0` |
| `last_reading_at` | REAL | When the radar's last reading arrived, as at `time` | Unix time in seconds; empty if none since Node-RED started |

A radar with nothing passing it sends little, so a recent `last_reading_at` isn't needed for the radar to be working.

## How to read it

A camera was watching in a window when `enabled`, `frigate_answered`, and `detection_enabled` are all 1, `stats_messages` is 4 or more, and `camera_fps` is above 0. A radar was watching when `enabled` and `port_open` are both 1.

What a camera row looks like in each situation:

| What happened | How the row looks |
|---|---|
| Watching, with traffic | `detection_enabled` 1, `camera_fps` above 0, `detection_fps` above 0 |
| Watching, with nothing moving in view | `detection_enabled` 1, `camera_fps` above 0, `detection_fps` 0. Frigate runs the detector only where it sees motion or is tracking an object, so a quiet road gives 0 with detection on. |
| Camera on, detection switched off in Frigate or on the [Cameras](../use/cameras.md) page for the whole window | `detection_enabled` 0, `camera_fps` above 0, `detection_fps` 0 |
| Detection switched on or off partway through the window | `detection_enabled` 0. `detection_fps` can be above 0: it's the mean of all the window's reports, including those with detection on. |
| The camera's stream was down while Frigate ran | `frigate_answered` 1, `camera_fps` 0 |
| Frigate ran without this camera, as when its configuration didn't load | `frigate_answered` 1, `stats_messages` 0, the frame rates and `detection_enabled` empty |
| Frigate answered for only part of the window | `stats_messages` well under 5 |
| Frigate sent nothing for the whole window: it was restarting or not responding | `frigate_answered` 0, `stats_messages` 0, the frame rates and `detection_enabled` empty. There is nothing about any camera. |
| The camera was switched off in `config.yml` | `enabled` 0, `deployment_id` empty. The other columns still show what Frigate reported. |

What a radar row looks like:

| What happened | How the row looks |
|---|---|
| The radar was switched off in `config.yml` | `enabled` 0, `deployment_id` empty |
| The radar's serial port wasn't open, as when the radar was unplugged | `port_open` 0 |

## Examples

These use Python's built-in `sqlite3`, or any SQLite tool. Replace `picam_h265` and the dates with your own.

How many of each hour's twelve windows a camera was watching, for one day in your computer's local time. `windows_logged` is how many of the twelve have a row, so you can tell a missing window from one when the camera wasn't watching.

```sql
SELECT strftime('%Y-%m-%d %H:00', time - 1, 'unixepoch', 'localtime') AS hour,
       camera,
       COUNT(*) AS windows_logged,
       SUM(CASE WHEN enabled = 1 AND frigate_answered = 1
                 AND detection_enabled = 1 AND stats_messages >= 4
                 AND camera_fps > 0
                THEN 1 ELSE 0 END) AS windows_watching
FROM watch_camera
WHERE time > CAST(strftime('%s', '2026-03-14', 'utc') AS INTEGER)
  AND time <= CAST(strftime('%s', '2026-03-15', 'utc') AS INTEGER)
GROUP BY hour, camera
ORDER BY hour, camera;
```

The events in each window, next to whether the camera was watching. An event belongs to the window that its `start_time` falls in, from five minutes before `time` up to and including `time`. A window with no events and a camera that was watching is a quiet road; a window with no events and a camera that wasn't is no information.

```sql
SELECT w.time,
       w.camera_fps,
       w.detection_enabled,
       COUNT(e.id) AS events
FROM watch_camera AS w
LEFT JOIN events AS e
       ON e.camera = w.camera
      AND e.start_time > w.time - 300
      AND e.start_time <= w.time
WHERE w.camera = 'picam_h265'
  AND w.time > CAST(strftime('%s', '2026-03-14', 'utc') AS INTEGER)
  AND w.time <= CAST(strftime('%s', '2026-03-15', 'utc') AS INTEGER)
GROUP BY w.time
ORDER BY w.time;
```

## Where the watch log goes

The rows are in the database download and in the ThingsBoard upload, as one `watch` value every five minutes; see [MQTT and ThingsBoard](integrations.md#thingsboard). They are not in the JSON export.

A `watch` value holds the window's rows, one list for cameras and one for radars. This one is from a camera that was on with detection switched off:

```json
{
    "cameras": [
        {
            "time": 1773489600,
            "camera": "picam_h265",
            "enabled": 1,
            "deployment_id": "1773400000000-3f9c2a1b-d",
            "frigate_answered": 1,
            "stats_messages": 5,
            "camera_fps": 10.06,
            "process_fps": 10.1,
            "skipped_fps": 0,
            "detection_fps": 0,
            "detection_enabled": 0
        }
    ],
    "radars": [
        {
            "time": 1773489600,
            "radar": "TM_RADAR_SERIAL_PORT_00",
            "enabled": 1,
            "deployment_id": "1773400000000-8b51e0d7-d",
            "port_open": 1,
            "last_reading_at": 1773489595.09
        }
    ]
}
```

An empty column is `null`. Each row holds only numbers, sensor names from `config.yml`, and a deployment id, so it can't identify a person.
