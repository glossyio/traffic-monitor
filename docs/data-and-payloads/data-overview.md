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

We believe in [open data](https://en.wikipedia.org/wiki/Open_data): anonymized data is a public good and the basis of useful research. The database is designed to be shareable. With the default settings it is [de-identified](https://en.wikipedia.org/wiki/De-identification): it records what passed (a label), when, how fast, and through which zones, and never an image or a plate number.

Images do exist on the device, briefly. Frigate keeps snapshots and short clips for about an hour so you can check what it detected. To keep none, turn off recordings and snapshots as described in [Tune object detection](../configuration/frigate-config.md#recordings-and-snapshots). To keep them longer, raise the retention there, and treat the device as holding images of people.

By default, no images or video leave the device. Everything is processed on the device, and `tmdb.sqlite` holds only metadata. Anyone on the device's network can open the live view and the recordings, though, because they have no login; [Home page and apps](../use/home-page.md) shows which apps ask for one.

The database stops being de-identified if you:

* Install the [Plate Recognizer](../add-ons/plate-recognizer.md) add-on. Plate numbers go into the `plate_recognizer` table. Don't share a database from a device that has ever had the add-on on.
* Turn on Frigate features that add identifying sub-labels or attributes to events, such as face recognition or license plate recognition.
* Write identifying details into operator comments.

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
| `deployment` | Where each sensor was, and when | Possibly: it holds the exact location, which is a home address if the device is mounted at a home |
| `comments` | Notes typed on the [Data export](../ui/database.md) page | Possibly, if the operator types names |
| `plate_recognizer` | Plate reads from the [Plate Recognizer](../add-ons/plate-recognizer.md) add-on | Yes |

The [radar](radar-payload.md) tables are described on their own page. The two tables below have no other page.

### deployment

A row for each combination of sensor, location, and bearing the device has had, taken from the `deployment` settings in [config.yml](../configuration/node-red-config.md#deployment). Every other table's `deployment_id` column holds the `id` of one of these rows, so you can tell where a reading was taken after the device has moved. The database declares no foreign key; it's a plain text column.

| Column | Type | Meaning |
|---|---|---|
| `id` | TEXT, primary key | The deployment id |
| `entryStartDateTime` | REAL | Unix time, in milliseconds, when this deployment began |
| `entryEndDateTime` | REAL | Unix time, in milliseconds, when it ended; empty for the current one |
| `lat` | REAL | Latitude in decimal degrees |
| `lon` | REAL | Longitude in decimal degrees |
| `bearing` | TEXT | Compass direction the sensor faces: `n`, `s`, `e`, `w`, `ne`, `nw`, `se`, or `sw` |
| `sensorType` | TEXT | `cameras`, `radars`, or `airquality_monitors` |
| `sensorName` | TEXT | The sensor's name in `config.yml` |
| `deviceName` | TEXT | The Raspberry Pi's serial number (`TM_RPI_SN` in [node-red-tm.env](../configuration/environment.md)) |

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

The tables are defined by numbered migrations in the repository's [`container/node-red-tm/schema/`](https://github.com/glossyio/traffic-monitor/tree/main/container/node-red-tm/schema) folder, and `schema.sql` there shows the whole current schema. Each time the Node-RED service starts, it applies any migrations the database doesn't have yet and records the schema version in the database. Before it does, it saves a copy of the database in `/opt/traffic-monitor/node-red-tm/db/backup/` and keeps only the most recent copy. It skips the copy for a new, empty database, for the first schema version on a database from before schema versions, which changes no existing table, and when the disk has less free space than about 1.2 times the database's size. You can read the version with `PRAGMA user_version;`.

## Getting the data

* **Download** the whole database from the [Data export](../ui/database.md) page, or a JSON export over a date range of the `events` table or one object type, the five radar tables, and the `airquality` table.
* **Open** the database with [DB Browser for SQLite](https://sqlitebrowser.org/), or from code with any SQLite library, such as Python's built-in `sqlite3`.
* **Subscribe** to today's counts over MQTT, or **upload** everything to ThingsBoard. See [MQTT and ThingsBoard](integrations.md).
* **Review** snapshots and clips in Frigate's **Explore** view at `http://<device>/frigate/`.
