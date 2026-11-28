---
description: What a Traffic Monitor stores, which of it could identify a person, the database tables, and how to get the data off the device.
---

# Data and privacy

The Traffic Monitor is a data collection tool. Everything it collects is processed and stored on the device, in open formats, so you own it and can share it.

## What the device stores

| Where | What | How long |
|---|---|---|
| `/opt/traffic-monitor/node-red-tm/db/tmdb.sqlite` | The database: [events](events-payload.md), [radar readings](radar-payload.md), [air quality readings](air-quality-aq-payload.md), the device's deployment history, the [watch log](watch-log.md) of whether each camera and radar was working, the [setup history](setup-history.md) of which model, versions, and camera settings were in force, and operator comments | Until you delete it |
| `/opt/traffic-monitor/frigate/storage/` | Frigate's cropped snapshots of each detection, and recordings of alerts and detections | About an hour, by default |
| Your ThingsBoard server | A copy of the data above, plus system metrics | If you turn on the [ThingsBoard upload](integrations.md#thingsboard) |

## Privacy

We believe in [open data](https://en.wikipedia.org/wiki/Open_data): anonymized data is a public good and the basis of useful research. The database is designed to be shareable. With the default settings it is [de-identified](https://en.wikipedia.org/wiki/De-identification): it records what passed (a label), when, how fast, the path it took across the camera's picture, and which zones it went through, and never an image or a plate number. Its location is rounded to about 1 km, which in a town shows the neighbourhood but not the address.

Images do exist on the device, briefly. Frigate keeps snapshots and short clips for about an hour so you can check what it detected. To keep none, turn off recordings and snapshots as described in [Tune object detection](../configuration/frigate-config.md#recordings-and-snapshots). To keep them longer, raise the retention there, and treat the device as holding images of people.

By default, the device sends no images or video anywhere. Everything is processed on the device, and `tmdb.sqlite` holds only metadata. The live view and the recordings are behind the device's [login](../use/control-app.md), which decides who on your network can open the apps. It isn't a control on the images themselves: anyone with an account on the device can see them, and they're ordinary files on the device's card. Frigate can also publish a snapshot of each detected object on the device's [MQTT broker](integrations.md#mqtt). New installs turn those snapshots off, and they stay on the device unless you give the broker a login, which opens it to your network. [Tune object detection](../configuration/frigate-config.md#recordings-and-snapshots) shows the setting. A snapshot you choose to [submit to Frigate+](../configuration/frigate-config.md#submit-snapshots) does leave the device, and it can show people.

With the default settings, the database is de-identified: it holds no images, plate numbers, or exact location. The place the device was used at is stored as a survey id, which has no coordinates in it, and any coordinates are rounded to about 1 km by default and never stored more precisely (see [deployment](#deployment)). Where homes are far apart, a square about 1 km across may hold only one or two of them, so the rounded location can point to the house even though it isn't exact. If the device is at a home, especially in a rural area, choose **About 10 km** or **No location stored** on the [Location](../use/location.md) page before it starts recording. The exact location stays on the device, in `config.yml` and in the control app's list of places, and neither is part of the database. The database, and the download on the Data export page, hold rounded locations; the Sharing page's [download with each place's exact location](../use/sharing.md#include-each-places-exact-location) adds the exact ones, for admins.

The database stops being de-identified if you:

* Install the [Plate Recognizer](../add-ons/plate-recognizer.md) add-on. Plate numbers go into the `plate_recognizer` table. Don't share a database from a device that has ever had the add-on on.
* Keep a database that an earlier version of the Traffic Monitor recorded while Frigate's face recognition or license plate recognition was on. The `sub_label` column keeps only delivery companies' logos, so a recognized person's or a known plate's name isn't saved, but rows recorded earlier can still hold one.
* Write identifying details into operator comments.
* Name a zone in Frigate after a street, a house number, or a person. Zone names are saved with every event; see [Zone names are saved with your data](../use/cameras.md#zone-names-are-saved-with-your-data).
* Keep the copy of the database that an upgrade leaves in `db/backup/`. It can hold the exact coordinates from before they were rounded (see [deployment](#deployment)), so don't share it.

For an area the camera shouldn't see at all, such as a window or a yard, aim the camera so the area is out of frame. A [motion mask](../configuration/frigate-config.md#masks) only stops motion there from starting a detection; the area still shows in the live view and in recordings.

Other software on the device, such as Frigate and the air quality sensor's service, keeps its own working data under its own retention rules.

## Tables

Tables for sensors the device doesn't have stay empty.

| Table | Contents | Could identify a person? |
|---|---|---|
| `events` | One row per object the camera detected, with its path, direction, and speed. See [Events](events-payload.md). | No, except rows an earlier version recorded with a recognized person's or plate's name in `sub_label`, or a zone name you typed |
| `radar_dov` | Detected object velocity readings from the radar | No |
| `radar_timed_speed_counts` | Counts and average speeds the radar reports every 300 seconds | No |
| `radar_raw_speed_magnitude` | Raw speed and magnitude readings, three per sample | No |
| `radar_raw_speed_magnitude_single` | The strongest reading of each sample | No |
| `radar_oc_payload` | Per-object summaries from the radar, including estimated length | No |
| `airquality` | Air quality and weather readings. See [Air quality](air-quality-aq-payload.md). | No |
| `deployment` | Where each sensor was, and when | No, except where homes are far apart: the location is rounded to about 1 km (two decimal places) by default and never stored more precisely, which in a rural area can point to a single home (see [Privacy](#privacy)) |
| `watch_camera` | Whether each camera was working, every five minutes. See [Watch log](watch-log.md). | No |
| `watch_radar` | Whether each radar was working, every five minutes. See [Watch log](watch-log.md). | No |
| `setup_device` | Which detection model, software versions, and unit settings were in force, and when. See [Setup history](setup-history.md). | Only text a person chose: a model's title and file name |
| `setup_camera` | Each camera's detect size, zones, masks, and filters, and when they were in force. See [Setup history](setup-history.md). | Only text a person chose: a zone's key and the key of a profile |
| `setup_radar` | What each radar answered about its model, firmware, and settings, such as the cosine angles it corrects by, and when. See [Setup history](setup-history.md#setup_radar). | No |
| `events_with_setup` (a view) | Every column of `events`, with the setup in force when the event started. See [Setup history](setup-history.md). | The same as `events` and the setup tables above |
| `comments` | Notes typed on the [Data export](../ui/database.md) page | Possibly, if the operator types names |
| `plate_recognizer` | Plate reads from the [Plate Recognizer](../add-ons/plate-recognizer.md) add-on | Yes |

The [radar](radar-payload.md) tables are described on their own page. The two tables below have no other page.

### deployment

A row for each combination of sensor, survey, and mounting the device has had, taken from the `deployment` settings in [config.yml](../configuration/node-red-config.md#deployment). A new row starts when the survey id, the sensor's heading, how the sensor is mounted, or a radar's angle into the road changes; moving the coordinates alone does not start one. A correction made on the Location page, and a change of the place's time zone, change the row in place instead, and start no new row. Removing a sensor's entry from `config.yml` ends its row; disabling the sensor doesn't. Every other table's `deployment_id` column holds the `id` of one of these rows, so you can tell where a reading was taken after the device has moved. The database declares no foreign key; it's a plain text column.

| Column | Type | Meaning |
|---|---|---|
| `id` | TEXT, primary key | The deployment id |
| `entryStartDateTime` | REAL | Unix time, in milliseconds, when this deployment began |
| `entryEndDateTime` | REAL | Unix time, in milliseconds, when it ended; empty for the current one |
| `survey_id` | TEXT | The place: one id for each place the device has been used at, such as `3f9a1c2e-si`. It has no coordinates in it, so rows at the same place share it. Empty when no survey id was set. |
| `location_precision` | INTEGER | The number of decimal places kept in `lat` and `lon`: `1` (about 10 km) or `2` (about 1 km). Empty when the row has no coordinates. |
| `lat` | REAL | Latitude in decimal degrees, rounded to `location_precision` decimal places; empty when no location was given or the precision is `none` |
| `lon` | REAL | Longitude in decimal degrees, rounded the same way |
| `timezone` | TEXT | The place's time zone as a tz database name, such as `America/New_York`. Empty when none was set. It is recorded whatever the precision, also when no location is stored. |
| `heading_deg` | INTEGER | The way the sensor faces, in whole degrees clockwise from true north: 0 is north, 90 is east, 180 is south, 270 is west. From 0 to 359. Empty when no heading was set. |
| `pitch_deg` | REAL | How far below level the centre of the sensor's view points, in degrees, with one decimal. From 0 (level) to 90 (straight down). Empty when not recorded. |
| `height_m` | REAL | How high the sensor is above the road, in metres, with two decimals. Above 0 and at most 100. Empty when not recorded. |
| `view_distance_m` | REAL | How far along the ground the centre of the sensor's view is, in metres, with two decimals. From 0 to 1,000. Empty when not recorded. |
| `mount` | TEXT | The usual mount the sensor was set up from: `tripod`, `pole`, `window`, or another key of lower-case letters, digits, and underscores, up to 32. Empty when not recorded. |
| `road_angle_deg` | REAL | The angle between the radar's beam and the road, in degrees, with one decimal. 0 is straight along the road, and 89 is almost straight across it. From 0 to 89. Radars only. Empty when not recorded. |
| `lane_distance_m` | REAL | How far across the road from the radar the near edge of the first lane that carries traffic is, in metres, with two decimals. From 0 to 100. Radars only. Empty when not recorded. |
| `lane_width_m` | REAL | The width of one lane, in metres, with two decimals. Above 0 and at most 10. Radars only. Empty when not recorded. |
| `lanes_toward` | INTEGER | How many lanes carry traffic toward the radar, from 0 to 3. Radars only. Empty when not recorded. |
| `lanes_away` | INTEGER | How many lanes carry traffic away from the radar, from 0 to 3. Radars only. Empty when not recorded. |
| `turn_lane` | INTEGER | `1` when there is a turning lane in the middle of the road. Radars only. Empty when not recorded. |
| `toward_side` | TEXT | Which side of the radar's view the traffic toward it is on: `near` or `far`. Radars only. Empty when not recorded. |
| `intersection` | INTEGER | `1` when the sensor's view takes in an intersection. Radars and cameras. Empty when not recorded. |
| `sensorType` | TEXT | `cameras`, `radars`, or `airquality_monitors` |
| `sensorName` | TEXT | The sensor's name in `config.yml`. For a camera, that's its entry's name under `sensors.cameras`, which can differ from its name in Frigate. |
| `deviceName` | TEXT | The Raspberry Pi's serial number (`TM_RPI_SN` in [node-red-tm.env](../configuration/environment.md)). Rows written by earlier releases can hold `undefined` instead. |

The four mounting columns (`pitch_deg`, `height_m`, `view_distance_m`, and `mount`) are empty on a row that was recorded before the columns existed, and on any row for which nothing was recorded. Only a correction made through the control app changes them on a row that exists.

The eight columns from `road_angle_deg` to `intersection` describe where a radar points and what the street in its view looks like; only `intersection` is also kept for a camera. They are empty on a row recorded before the columns existed, and on any row for which nothing was recorded. A change of `road_angle_deg` starts a new row, as a change of the mounting does. A change of the other seven, which are facts about the street, is made in the row that is open and starts no new one. Until the control app's Mounting page has fields for them, you set them by hand in [config.yml](../configuration/node-red-config.md#how-a-sensor-is-mounted). The `intersection` tick changes how a camera's events are matched to the radar's readings; see [Events](events-payload.md#direction-and-speed).

`timezone` is empty on a row that was recorded before the column existed, and on a row at a place with no time zone. Changing a place's time zone on the control app rewrites it on every row of that place, the ended ones too. It starts no deployment and changes no `deployment_id`.

!!! note "Older exports have `bearing`"

    Before this release the table had a `bearing` column instead of `heading_deg`. It held one of eight compass points, and older closed rows can hold `null` or `undefined` there. The upgrade writes each row's `heading_deg` as the centre of its point, from the [table of centres](../configuration/node-red-config.md#if-your-file-still-says-bearing), and leaves it empty when the row had no point. It then removes `bearing` from the database. A copy made before the upgrade, or an export from an older device, keeps `bearing`, so a query that reads an older copy has to convert the point. A converted heading is only as exact as the point it came from: a sensor that was recorded as facing `n` reads 0, even if it really faced a little to one side.

The database holds shareable data only, so the exact location is never written to it. A database upgraded from a release that stored exact coordinates holds rounded ones. When Node-RED first starts after the upgrade, the database migration copies the database to `db/backup/tmdb-v<N>-<time>.sqlite` in the `node-red-tm` directory, where N is the schema version the device was on before, and that copy holds the exact rows. A device upgrading from a release (0.7.1 or earlier) has `tmdb-v0-…`, and a device that already ran a development build with the first schema version has `tmdb-v1-…`. The copy is kept until the next schema change succeeds. You can delete it sooner, once the control app has read the past places from it; see [Places after an update](../build-your-own-device-diy/update.md#places-after-an-update). The first upgrade from a release copies the whole database, so it needs free space of about 1.2 times the database's size. If the disk was too full for the copy, it was skipped and the exact coordinates are gone.

### comments

Free-text notes an operator adds on the [Data export](../ui/database.md) page, for example "threshold lowered to 0.4" or "road work on the north side", so that whoever analyzes the data later knows what changed and when.

| Column | Type | Meaning |
|---|---|---|
| `id` | TEXT, primary key | |
| `effectiveDateTime` | TIMESTAMP | When the note starts to apply |
| `expirationDateTime` | TIMESTAMP | When it stops applying; empty if open-ended |
| `entryDateTime` | TIMESTAMP | When it was written |
| `comment` | TEXT | The note |
| `commenter_name` | TEXT | Who wrote it |

### The exact location in a database copy

The database on the device never holds an exact location. A copy made with [**Download your data**](../use/sharing.md#include-each-places-exact-location) on the Sharing page, with **Include each place's exact location** ticked, does: the device adds a table and a view to the copy, and only to the copy. The database itself, and the download on the [Data export](../ui/database.md) page, never have them. The `deployment` table in the copy is unchanged, so its `lat` and `lon` stay rounded.

`survey_exact_location` has one row for each place the device has been at that has a location:

| Column | Type | Meaning |
|---|---|---|
| `survey_id` | TEXT, primary key | The place, as in `deployment.survey_id` |
| `lat` | REAL | Latitude in decimal degrees, to five decimal places |
| `lon` | REAL | Longitude in decimal degrees, to five decimal places |

`deployment_exact` is the `deployment` table with two more columns after its own, `exact_lat` and `exact_lon`, taken from `survey_exact_location` by `survey_id`. They are empty for a row whose place has no row in the table: a place with no location, a place deleted from the Location page, and a deployment from before any place was recorded. A planned place is never in the table. The table holds what the `exact_location` attribute holds when the exact location is [shared](../use/sharing.md): a place's id and its coordinates. [Share data](../use/sharing.md#what-the-copy-adds) has an example query.

### Schema versions

The tables are defined by numbered migrations in the repository's [`container/node-red-tm/schema/`](https://github.com/glossyio/traffic-monitor/tree/main/container/node-red-tm/schema) folder, and `schema.sql` there shows the whole current schema. Each time the Node-RED service starts, it applies any migrations the database doesn't have yet and records the schema version in the database. Before it does, it saves a copy of the database in `/opt/traffic-monitor/node-red-tm/db/backup/` and keeps only the most recent copy. It makes no copy of a new database, or when the disk has less free space than about 1.2 times the database's size. It also makes none when the only migration to apply is the first, which only adds missing tables. You can read the version with `PRAGMA user_version;`.

If a migration fails, it's rolled back, and Node-RED starts on the previous version, which may not be able to save new data. The control app's [Status page](../use/device-health.md#the-status-page) then shows **Database schema** as a problem. To see why, run `sudo journalctl -u node-red-tm | grep tmdb-migrate`, or download the diagnostics on the Device page. See [the FAQ entry](../help-and-faq/frequently-asked-questions.md#troubleshooting).

## Getting the data

* **Download** the whole database from the [Sharing page](../use/sharing.md#download-your-data), or from the [Data export](../ui/database.md) page, which also exports events, radar readings, or air quality readings over a date range as JSON.
* **Open** the database with [DB Browser for SQLite](https://sqlitebrowser.org/), or from code with any SQLite library, such as Python's built-in `sqlite3`.
* **Subscribe** to today's counts over MQTT, or **upload** everything to ThingsBoard. See [MQTT and ThingsBoard](integrations.md).
* **Review** snapshots and clips in Frigate's **Explore** view at `http://<device>/frigate/`.
