---
description: The two watch log tables, which record every five minutes whether each camera and radar was working, so that a quiet road can be told from a sensor that was off.
---

# Watch log

An hour with no events looks the same whether the road was empty or nothing was watching it. The watch log tells the two apart. Every five minutes the device writes one row for each camera and one for each radar, saying what that sensor was doing.

Cameras go in `watch_camera` and radars in `watch_radar`. Both tables are in the database, in the [Data export](../ui/database.md) page's database download.

## What a row covers

A row covers the five minutes that end at its `time`, which is always a multiple of five minutes on the device's clock. There is a row for every camera and radar listed in [config.yml](../configuration/node-red-config.md#sensorscameras), whether it is enabled or not, so a sensor that was switched off in `config.yml` shows up as a row with `config_enabled` 0 rather than as a gap.

A window with no row means Node-RED didn't see that whole window. That covers every window a restart, a reboot, or a power cut touched, from the one Node-RED stopped in through the one it started in: one window for a quick restart, more for a longer outage. The first row after a start comes at the second five-minute mark, five to ten minutes later. It also covers a window in which the device's clock jumped. If the clock is set back by more than about ten minutes, the times that come round again keep their first rows on the device, while the upload sends the new ones. Treat a missing window as unknown, not as working or as not working.

## watch_camera

One row for each camera and window. The primary key is `time` and `camera`.

| Column | Type | Meaning | Values |
|---|---|---|---|
| `time` | INTEGER | End of the five-minute window | Unix time in seconds |
| `camera` | TEXT | The camera's name in `config.yml`, the same name as `events.camera` | |
| `config_enabled` | INTEGER | The camera's `enabled` setting in `config.yml`. This is only the setting. It says nothing about whether the camera was working; the columns after it are for that. | `1` or `0` |
| `deployment_id` | TEXT | The [deployment](data-overview.md#deployment) the camera had | Empty if it has none, or while the camera is off in `config.yml` |
| `frigate_answers` | INTEGER | How many status reports Frigate sent in the window. Frigate reports once a minute unless its `mqtt.stats_interval` setting was changed, so a full window has about 5. It is the same on every camera's row. | 0 or more; 0 when Frigate sent none |
| `camera_answers` | INTEGER | How many of those reports covered this camera | 0 or more, up to `frigate_answers` |
| `camera_fps` | REAL | Frames per second the camera delivered, averaged over the reports | Empty when `camera_answers` is 0 or `camera_on` is 0 |
| `process_fps` | REAL | Frames per second Frigate processed | Empty when `camera_answers` is 0 or `camera_on` is 0 |
| `skipped_fps` | REAL | Frames per second Frigate skipped because it was behind | Empty when `camera_answers` is 0 or `camera_on` is 0 |
| `detection_fps` | REAL | Regions per second sent to the detector. Frigate can send several regions of one frame, so this can be higher than `camera_fps`. | Empty when `camera_answers` is 0 or `camera_on` is 0 |
| `detection_enabled` | INTEGER | Whether detection was on for the whole window. It is 0 when detection was off in any report of the window. | `1` or `0`; empty when `camera_answers` is 0 |
| `camera_on` | INTEGER | Whether the camera was on in Frigate for the whole window. Frigate can turn a camera off without stopping, with the power button in its live view. It is 0 when the camera was off at any time the device asked. The device reads Frigate's settings each time one of its status reports arrives. | `1` or `0`; empty when Frigate sent no report in the window, or when its settings couldn't be read or didn't list this camera |

The four frame rates are means of the reports in the window, rounded to two decimals. They are empty for a camera that was turned off because Frigate keeps listing such a camera in its reports and repeats the last frame rates it measured, so the device leaves them out rather than record numbers from before.

## watch_radar

One row for each radar and window. The primary key is `time` and `radar`.

| Column | Type | Meaning | Values |
|---|---|---|---|
| `time` | INTEGER | End of the five-minute window | Unix time in seconds |
| `radar` | TEXT | The radar's name in [config.yml](../configuration/node-red-config.md#sensorsradars), the same as `radarName` in the radar tables | |
| `config_enabled` | INTEGER | The radar's `enabled` setting in `config.yml`. This is only the setting. It says nothing about whether the radar was working; the columns after it are for that. | `1` or `0` |
| `deployment_id` | TEXT | The [deployment](data-overview.md#deployment) the radar had | Empty if it has none, or while the radar is off in `config.yml` |
| `port_open` | INTEGER | Whether the device had the radar's serial port open for the whole window: at each of the minute checks and at `time` | `1` or `0` |
| `last_reading_at` | REAL | When the radar's last reading arrived, as at `time`. The radar's answers to the minute check are not readings and don't count. | Unix time in seconds; empty if none since Node-RED started |
| `radar_answers` | INTEGER | Once a minute the device asks each radar that is switched on in `config.yml` for its power state. This is how many answers the radar gave in the window, so a full window has about 5. A window in which the radar was set up (a `config.yml` save) has a few more, because the setup's own commands are answered the same way. | 0 or more; 0 when it gave none or wasn't asked |
| `radar_on` | INTEGER | Whether the radar was active for the whole window. It is 0 when any answer said idle. In idle a radar's transmitter is off and it sends no readings, while its serial port stays open. | `1` or `0`; empty when the radar didn't answer, wasn't asked, or gave a state this version doesn't know |

A radar with nothing passing it sends little, so a recent `last_reading_at` isn't needed for the radar to be working. It is a time, not a figure for the window: it can be older than the window while the radar is working.

## The same idea in both tables

The two tables follow one pattern, so a column in one has a counterpart in the other.

| The idea | `watch_camera` | `watch_radar` |
|---|---|---|
| The entry's `enabled` setting in `config.yml` | `config_enabled` | `config_enabled` |
| The connection | | `port_open` |
| How often the program that reports on cameras spoke | `frigate_answers` | |
| How many answers there were about this sensor | `camera_answers` | `radar_answers` |
| The sensor's own switch, for the whole window | `camera_on` | `radar_on` |
| What the sensor delivered | the four frame rates, means over the window | `last_reading_at`, as at `time` |
| Detection | `detection_enabled` | |

Some differences stay. Frigate keeps running a camera that `config.yml` switches off, so that camera's row still shows what Frigate said. A radar that `config.yml` switches off is held in idle and isn't asked, so its row has `radar_answers` 0 and `radar_on` empty. The device asks Frigate about a camera's switch when a status report arrives, and asks each radar once a minute on its own clock, so a Frigate that sent nothing isn't asked and a silent radar is.

## How to read it

A camera was watching in a window when `config_enabled`, `camera_on`, and `detection_enabled` are all 1, `camera_answers` is 4 or more, and `camera_fps` is above 0. A radar was watching when `config_enabled`, `port_open`, and `radar_on` are all 1 and `radar_answers` is 4 or more.

What a camera row looks like in each situation:

| What happened | How the row looks |
|---|---|
| Watching, with traffic | `camera_on` 1, `detection_enabled` 1, `camera_fps` above 0, `detection_fps` above 0 |
| Watching, with nothing moving in view | `camera_on` 1, `detection_enabled` 1, `camera_fps` above 0, `detection_fps` 0. Frigate runs the detector only where it sees motion or is tracking an object, so a quiet road gives 0 with detection on. |
| Camera on, detection switched off in Frigate or on the [Cameras](../use/cameras.md) page for the whole window | `detection_enabled` 0, `camera_fps` above 0, `detection_fps` 0 |
| Detection switched on or off partway through the window | `detection_enabled` 0. `detection_fps` can be above 0: it's the mean of all the window's reports, including those with detection on. |
| The camera was turned off in Frigate, for all or part of the window | `camera_on` 0 and the four frame rates empty. `detection_enabled` still shows Frigate's detection switch. |
| The camera's stream was down while Frigate ran | `camera_on` 1, `camera_fps` 0 |
| Frigate sent its reports, but the device couldn't read its settings | `frigate_answers` and `camera_answers` about 5, `camera_on` empty, the frame rates as Frigate reported them. The device can't tell whether the camera was on, so the window doesn't count as watching. |
| Frigate ran without this camera, as when its configuration didn't load | `frigate_answers` about 5, `camera_answers` 0, the frame rates and `detection_enabled` empty |
| Frigate answered for only part of the window | `camera_answers` well under 5 |
| Frigate sent nothing for the whole window: it was restarting or not responding | `frigate_answers` 0, `camera_answers` 0, the frame rates and `detection_enabled` empty, `camera_on` empty. There is nothing about any camera. |
| The camera was switched off in `config.yml` | `config_enabled` 0, `deployment_id` empty. The other columns still show what Frigate reported. |

What a radar row looks like:

| What happened | How the row looks |
|---|---|
| Watching | `config_enabled`, `port_open`, and `radar_on` all 1, `radar_answers` about 5 |
| The radar was switched off in `config.yml` | `config_enabled` 0, `deployment_id` empty, `radar_answers` 0, `radar_on` empty |
| The radar was in idle for all or part of the window | `radar_on` 0. The port is still open, and the row would otherwise look like a working radar. |
| The radar was set up during the window, as when `config.yml` was saved | `radar_on` 0, because a setup puts the radar in idle for a few seconds, and `radar_answers` more than 5 |
| The radar didn't answer | `radar_answers` 0 or low, `radar_on` empty when there were no answers |
| The radar was unplugged for part of the window | `port_open` 0, `radar_answers` low |
| The radar's serial port wasn't open for the whole window | `port_open` 0, `radar_answers` 0, `radar_on` empty |

## Examples

These use Python's built-in `sqlite3`, or any SQLite tool. Replace `picam_h265` and the dates with your own.

How many of each hour's twelve windows a camera was watching, for one day in your computer's local time. `windows_logged` is how many of the twelve have a row, so you can tell a missing window from one when the camera wasn't watching.

```sql
SELECT strftime('%Y-%m-%d %H:00', time - 1, 'unixepoch', 'localtime') AS hour,
       camera,
       COUNT(*) AS windows_logged,
       SUM(CASE WHEN config_enabled = 1 AND camera_on = 1
                 AND detection_enabled = 1 AND camera_answers >= 4
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
       w.camera_on,
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

How many of each hour's twelve windows a radar was watching, by the radar rule. A radar that was idle or didn't answer counts as not watching, as does one whose serial port closed at any minute check.

```sql
SELECT strftime('%Y-%m-%d %H:00', time - 1, 'unixepoch', 'localtime') AS hour,
       radar,
       COUNT(*) AS windows_logged,
       SUM(CASE WHEN config_enabled = 1 AND port_open = 1
                 AND radar_on = 1 AND radar_answers >= 4
                THEN 1 ELSE 0 END) AS windows_watching
FROM watch_radar
WHERE time > CAST(strftime('%s', '2026-03-14', 'utc') AS INTEGER)
  AND time <= CAST(strftime('%s', '2026-03-15', 'utc') AS INTEGER)
GROUP BY hour, radar
ORDER BY hour, radar;
```

## Where the watch log goes

The rows are in the database download and in the ThingsBoard upload, as one `watch` value every five minutes; see [MQTT and ThingsBoard](integrations.md#thingsboard). They are not in the JSON export.

A `watch` value holds the window's rows, one list for cameras and one for radars. This one is from a camera that was on with detection switched off, and a radar that was active:

```json
{
    "cameras": [
        {
            "time": 1773489600,
            "camera": "picam_h265",
            "config_enabled": 1,
            "deployment_id": "1773400000000-3f9c2a1b-d",
            "frigate_answers": 5,
            "camera_answers": 5,
            "camera_fps": 10.06,
            "process_fps": 10.1,
            "skipped_fps": 0,
            "detection_fps": 0,
            "detection_enabled": 0,
            "camera_on": 1
        }
    ],
    "radars": [
        {
            "time": 1773489600,
            "radar": "TM_RADAR_SERIAL_PORT_00",
            "config_enabled": 1,
            "deployment_id": "1773400000000-8b51e0d7-d",
            "port_open": 1,
            "last_reading_at": 1773489595.09,
            "radar_answers": 5,
            "radar_on": 1
        }
    ]
}
```

An empty column is `null`. Each row holds only numbers, sensor names from `config.yml`, and a deployment id, so it can't identify a person.
