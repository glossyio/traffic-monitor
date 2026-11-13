---
description: What a Traffic Monitor stores, which of it could identify a person, the database tables, and how to get the data off the device.
---

# Data and privacy

The Traffic Monitor is a data collection tool. Everything it collects is processed and stored on the device, in open formats, so you own it and can share it.

## What the device stores

| Where | What | How long |
|---|---|---|
| `/opt/traffic-monitor/node-red-tm/db/tmdb.sqlite` | The database: [events](events-payload.md), [radar readings](radar-payload.md), [air quality readings](air-quality-aq-payload.md), the device's deployment history, and operator comments | Until you delete it |
| `/opt/traffic-monitor/frigate/storage/` | Frigate's cropped snapshots of each detection, and recordings of alerts and detections | About an hour, by default |
| Your ThingsBoard server | A copy of the data above, plus system metrics | If you turn on the [ThingsBoard upload](integrations.md#thingsboard) |

## Privacy

We believe in [open data](https://en.wikipedia.org/wiki/Open_data): anonymized data is a public good and the basis of useful research. The database is designed to be shareable. With the default settings it is [de-identified](https://en.wikipedia.org/wiki/De-identification): it records what passed (a label), when, how fast, and through which zones, and never an image or a plate number. Its location is rounded to about 1 km, which in a town shows the neighbourhood but not the address.

Images do exist on the device, briefly. Frigate keeps snapshots and short clips for about an hour so you can check what it detected. To keep none, turn off recordings and snapshots as described in [Tune object detection](../configuration/frigate-config.md#recordings-and-snapshots). To keep them longer, raise the retention there, and treat the device as holding images of people.

By default, the device sends no images or video anywhere. Everything is processed on the device, and `tmdb.sqlite` holds only metadata. The live view and the recordings are behind the device's [login](../use/control-app.md), which decides who on your network can open the apps. It isn't a control on the images themselves: anyone with an account on the device can see them, and they're ordinary files on the device's card. Frigate can also publish a snapshot of each detected object on the device's [MQTT broker](integrations.md#mqtt). New installs turn those snapshots off, and they stay on the device unless you give the broker a login, which opens it to your network. [Tune object detection](../configuration/frigate-config.md#recordings-and-snapshots) shows the setting. A snapshot you choose to [submit to Frigate+](../configuration/frigate-config.md#submit-snapshots) does leave the device, and it can show people.

With the default settings, the database is de-identified: it holds no images, plate numbers, or exact location. The place the device was used at is stored as a survey id, which has no coordinates in it, and any coordinates are rounded to about 1 km by default and never stored more precisely (see [deployment](#deployment)). Where homes are far apart, a square about 1 km across may hold only one or two of them, so the rounded location can point to the house even though it isn't exact. If the device is at a home, especially in a rural area, choose **About 10 km** or **No location stored** on the [Location](../use/location.md) page before it starts recording. The exact location stays on the device, in `config.yml` and in the control app's list of places, and neither is part of the database.

The database stops being de-identified if you:

* Install the [Plate Recognizer](../add-ons/plate-recognizer.md) add-on. Plate numbers go into the `plate_recognizer` table. Don't share a database from a device that has ever had the add-on on.
* Turn on Frigate features that add identifying sub-labels or attributes to events, such as face recognition or license plate recognition.
* Write identifying details into operator comments.
* Keep the copy of the database that an upgrade leaves in `db/backup/`. It can hold the exact coordinates from before they were rounded (see [deployment](#deployment)), so don't share it.

For an area the camera shouldn't see at all, such as a window or a yard, aim the camera so the area is out of frame. A [motion mask](../configuration/frigate-config.md#masks) only stops motion there from starting a detection; the area still shows in the live view and in recordings.

Other software on the device, such as Frigate and the air quality sensor's service, keeps its own working data under its own retention rules.

## Tables

Tables for sensors the device doesn't have stay empty.

| Table | Contents | Could identify a person? |
|---|---|---|
| `events` | One row per object the camera detected, with direction and speed. See [Events](events-payload.md). | Only through Frigate sub-labels or attributes, if you turn those on |
| `radar_dov` | Detected object velocity readings from the radar | No |
| `radar_timed_speed_counts` | Counts and average speeds the radar reports every 300 seconds | No |
| `radar_raw_speed_magnitude` | Raw speed and magnitude readings, three per sample | No |
| `radar_raw_speed_magnitude_single` | The strongest reading of each sample | No |
| `radar_oc_payload` | Per-object summaries from the radar, including estimated length | No |
| `airquality` | Air quality and weather readings. See [Air quality](air-quality-aq-payload.md). | No |
| `deployment` | Where each sensor was, and when | No, except where homes are far apart: the location is rounded to about 1 km (two decimal places) by default and never stored more precisely, which in a rural area can point to a single home (see [Privacy](#privacy)) |
| `comments` | Notes typed on the [Data export](../ui/database.md) page | Possibly, if the operator types names |
| `plate_recognizer` | Plate reads from the [Plate Recognizer](../add-ons/plate-recognizer.md) add-on | Yes |

The [radar](radar-payload.md) tables are described on their own page. The two tables below have no other page.

### deployment

A row for each combination of sensor, survey, and bearing the device has had, taken from the `deployment` settings in [config.yml](../configuration/node-red-config.md#deployment). A new row starts when the survey id or the sensor's bearing changes; moving the coordinates alone does not start one. Removing a sensor's entry from `config.yml` ends its row; disabling the sensor doesn't. Every other table's `deployment_id` column holds the `id` of one of these rows, so you can tell where a reading was taken after the device has moved. The database declares no foreign key; it's a plain text column.

| Column | Type | Meaning |
|---|---|---|
| `id` | TEXT, primary key | The deployment id |
| `entryStartDateTime` | REAL | Unix time, in milliseconds, when this deployment began |
| `entryEndDateTime` | REAL | Unix time, in milliseconds, when it ended; empty for the current one |
| `survey_id` | TEXT | The place: one id for each place the device has been used at, such as `3f9a1c2e-si`. It has no coordinates in it, so rows at the same place share it. Empty when no survey id was set. |
| `location_precision` | INTEGER | The number of decimal places kept in `lat` and `lon`: `1` (about 10 km) or `2` (about 1 km). Empty when the row has no coordinates. |
| `lat` | REAL | Latitude in decimal degrees, rounded to `location_precision` decimal places; empty when no location was given or the precision is `none` |
| `lon` | REAL | Longitude in decimal degrees, rounded the same way |
| `bearing` | TEXT | Compass direction the sensor faces: `n`, `s`, `e`, `w`, `ne`, `nw`, `se`, or `sw`. Empty when no bearing was set; closed rows written by earlier releases can hold `null` or `undefined` instead. |
| `sensorType` | TEXT | `cameras`, `radars`, or `airquality_monitors` |
| `sensorName` | TEXT | The sensor's name in `config.yml`. For a camera, that's its entry's name under `sensors.cameras`, which can differ from its name in Frigate. |
| `deviceName` | TEXT | The Raspberry Pi's serial number (`TM_RPI_SN` in [node-red-tm.env](../configuration/environment.md)). Rows written by earlier releases can hold `undefined` instead. |

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

### Schema versions

The tables are defined by numbered migrations in the repository's [`container/node-red-tm/schema/`](https://github.com/glossyio/traffic-monitor/tree/main/container/node-red-tm/schema) folder, and `schema.sql` there shows the whole current schema. Each time the Node-RED service starts, it applies any migrations the database doesn't have yet and records the schema version in the database. Before it does, it saves a copy of the database in `/opt/traffic-monitor/node-red-tm/db/backup/` and keeps only the most recent copy. It makes no copy of a new database, or when the disk has less free space than about 1.2 times the database's size. It also makes none when the only migration to apply is the first, which only adds missing tables. You can read the version with `PRAGMA user_version;`.

If a migration fails, it's rolled back, and Node-RED starts on the previous version, which may not be able to save new data. The control app's [Status page](../use/device-health.md#the-status-page) then shows **Database schema** as a problem. To see why, run `sudo journalctl -u node-red-tm | grep tmdb-migrate`, or download the diagnostics on the Device page. See [the FAQ entry](../help-and-faq/frequently-asked-questions.md#troubleshooting).

## Getting the data

* **Download** the whole database, or a JSON export of events, radar readings, or air quality readings over a date range, from the [Data export](../ui/database.md) page.
* **Open** the database with [DB Browser for SQLite](https://sqlitebrowser.org/), or from code with any SQLite library, such as Python's built-in `sqlite3`.
* **Subscribe** to today's counts over MQTT, or **upload** everything to ThingsBoard. See [MQTT and ThingsBoard](integrations.md).
* **Review** snapshots and clips in Frigate's **Explore** view at `http://<device>/frigate/`.
