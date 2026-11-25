---
description: The two setup history tables and the events_with_setup view, which record which detection model, software versions, and camera settings were in force over time, so you can compare counts across them.
---

# Setup history

The detection model decides what the device counts. A different model, a moved zone, or a lower frame rate changes the numbers without the road changing, so a count means little unless you know the setup it was made with. The setup history records the setup over time, and a view ties each event to the setup in force when it started.

The device keeps two tables, `setup_device` for the whole unit and `setup_camera` for each camera, and one view, `events_with_setup`. They are in the database, in the [Data export](../ui/database.md) page's database download. They are not in the JSON export. With [Share data](../use/sharing.md) on, the rows are also [uploaded](#what-the-device-uploads).

## How the rows work

A row says what was true from `started` until `ended`. The row in force has no `ended`. The device starts a new row only when something differs from the row in force, so a unit that is never changed has one row of each kind for months. Every few minutes the device compares the setup with the open rows. A list that is only reordered, such as the same zones in another order, is not a difference.

Times in these tables are Unix time in milliseconds, as in the deployment history. An event's `start_time` is in seconds, so the view compares `start_time * 1000`.

A camera has a row for each key under `sensors.cameras` in [config.yml](../configuration/node-red-config.md#sensorscameras) whose Frigate camera exists, named by that key, the same name as `events.camera`. If two keys point at one Frigate camera, only the one that comes first in `config.yml` gets a row. A camera's row ends when its key leaves `config.yml`.

## setup_device

One row for each period in which these facts were the same. The primary key is `id`.

| Column | Type | Meaning | Values |
|---|---|---|---|
| `id` | TEXT | The row's id | |
| `started` | INTEGER | When the row's facts began to hold | Unix time in milliseconds |
| `ended` | INTEGER | When they stopped holding | Unix time in milliseconds; empty while the row is in force |
| `tm_version` | TEXT | The Traffic Monitor version installed | Such as `0.8.0`, or `0.8.0-dev` on an install made from the `dev` branch |
| `tm_commit` | TEXT | The commit the install was made from | Empty when the installer didn't know it |
| `schema_version` | INTEGER | The database's schema version | |
| `frigate_version` | TEXT | Frigate's version | |
| `unit_system` | TEXT | Frigate's unit system, which names the unit of a zone's `distances` | `metric` (metres) or `imperial` (feet) |
| `detector` | TEXT | The kind of detector Frigate uses | Such as `edgetpu`, `hailo8l`, or `cpu` |
| `model_id` | TEXT | The Frigate+ model's id | Empty for a model that isn't from Frigate+ |
| `model_file` | TEXT | The model file's name | Empty when the model has no file, as with Frigate's built-in model on a unit that detects on the processor |
| `model_sha256` | TEXT | The SHA-256 of the model file | Identifies the file whatever its name. Empty when `model_file` is, or when the file isn't there. |
| `model_kind` | TEXT | Where the model comes from | `frigate_plus` (a Frigate+ model), `local` (a file someone uploaded), `installer_default` (the model the installer sets up for your accelerator), or `frigate_default` (the model that comes with Frigate) |
| `model_title` | TEXT | The title the model was given | Empty for a model with no title. It's text a person typed. |
| `model_trained_at` | TEXT | When a Frigate+ model was trained, as Frigate+ wrote it | Empty for other models |
| `model_base` | TEXT | The Frigate+ model's base model | Empty for other models |
| `model_type` | TEXT | The model's type, as Frigate reports it | Such as `yolonas` |
| `model_width`, `model_height` | INTEGER | The size of the picture the model takes in, in pixels | |
| `labels_available` | TEXT | The object labels the model can recognise | A JSON list, sorted, such as `["bicycle","car","person"]`. Empty (`NULL`) when the labels can't be read. |

An empty column is `NULL`: the device couldn't read the fact, or it doesn't apply. A text fact longer than 128 characters, and a JSON fact (a list of labels, the zones, the masks, the thresholds) whose JSON is longer than 16,000 characters, are recorded as empty, never cut. The limits are counted as Node-RED counts them, so a character outside the basic plane, such as an emoji, counts as two.

## setup_camera

One row for each camera and period. The primary key is `id`; the rows of one camera are those with the same `camera`.

| Column | Type | Meaning | Values |
|---|---|---|---|
| `id` | TEXT | The row's id | |
| `started` | INTEGER | When the row's facts began to hold | Unix time in milliseconds |
| `ended` | INTEGER | When they stopped holding | Unix time in milliseconds; empty while the row is in force |
| `camera` | TEXT | The camera's key under `sensors.cameras` in `config.yml` | The same as `events.camera` |
| `detect_width`, `detect_height` | INTEGER | The size of the picture Frigate detects on, in pixels | |
| `detect_fps` | INTEGER | The frame rate Frigate detects at | |
| `stationary_threshold` | INTEGER | Frigate's `detect.stationary.threshold`: how many frames an object goes without moving before it counts as stationary | |
| `stationary_interval` | INTEGER | Frigate's `detect.stationary.interval`: how many frames pass between detections on a stationary object | |
| `lens_hfov` | REAL | The detect picture's horizontal field of view, in degrees | Empty. Nothing fills it yet. |
| `labels_tracked` | TEXT | The object labels Frigate tracks on this camera | A JSON list, sorted, such as `["car","person"]` |
| `thresholds` | TEXT | The filter numbers of each tracked label | A JSON object; see below |
| `zones` | TEXT | The camera's zones | A JSON list; see below |
| `masks` | TEXT | The camera's masks | A JSON object; see below |
| `profile` | TEXT | The key of Frigate's active profile | Set only when this camera defines that profile. Empty otherwise. |

The JSON columns are written with sorted keys and no spaces. The examples below have line breaks so you can read them.

### thresholds

Each tracked label's filter numbers from Frigate: any of `min_area`, `max_area`, `min_ratio`, `max_ratio`, `threshold`, and `min_score`. A label with none set is left out.

```json
{
    "car": {"min_area": 5000, "threshold": 0.7},
    "person": {"min_score": 0.5}
}
```

### zones

A list of the camera's zones, sorted by `key`. Each zone has these fields, and nothing else: the name Frigate shows for a zone and its colour aren't kept.

| Field | Meaning |
|---|---|
| `key` | The zone's key in Frigate, such as `zone_capture` |
| `enabled` | Whether the zone is on |
| `corners` | The zone's corners as `[x, y]`, fractions of the picture from its top left corner, in the order Frigate stores them. Usually 0 to 1; a corner past the picture's edge is kept as it is, so a value can be below 0 or above 1 |
| `distances` | The lengths of the zone's sides as entered in Frigate, in the unit `unit_system` names; `[]` when none |
| `inertia`, `loitering_time`, `speed_threshold` | The zone's settings in Frigate; `null` when not set |
| `objects` | The labels the zone counts, sorted |
| `filters` | The zone's filter numbers for each label, as in `thresholds` |

```json
[
    {
        "key": "zone_capture",
        "enabled": true,
        "corners": [[0.12, 0.40], [0.88, 0.40], [0.95, 0.85], [0.05, 0.85]],
        "distances": [12.0, 4.5, 12.0, 4.5],
        "inertia": 3,
        "loitering_time": 0,
        "speed_threshold": null,
        "objects": ["bicycle", "car"],
        "filters": {}
    }
]
```

### masks

A mask is an area where Frigate ignores motion or objects. The column is `{}` for a camera with no masks. Otherwise it has these three keys, each a list of masks, and a mask is `{"enabled": <true or false>, "corners": [[x, y], ...]}`. The corners are fractions of the picture, as in `zones`. Frigate's own id and name for a mask aren't kept, and a mask with no shape (empty, or fewer than three corners) isn't recorded.

| Key | Meaning |
|---|---|
| `motion` | Masks that stop motion in an area from starting a detection |
| `objects` | Masks that ignore a detection in an area, for every label |
| `object_filters` | An object for each label that has a mask of its own: `{"<label>": [<mask>, ...]}`. A label appears only when it has one. |

```json
{
    "motion": [{"enabled": true, "corners": [[0.0, 0.0], [1.0, 0.0], [1.0, 0.1], [0.0, 0.1]]}],
    "objects": [],
    "object_filters": {}
}
```

## events_with_setup

The view lists every column of `events`, then the setup in force when each event started. An event appears once, whatever the tables hold.

* `setup_device_id`, then the `setup_device` facts under a `setup_` prefix: `setup_tm_version`, `setup_model_file`, `setup_model_sha256`, and so on.
* `setup_camera_id`, then the `setup_camera` facts under a `camera_` prefix: `camera_detect_width`, `camera_zones`, `camera_profile`, and so on.

The setup in force is the row with `started` at or before the event's `start_time` and with no `ended`, or an `ended` after it. An event with no row in force has all of these columns empty.

Replace `picam_h265` below with your camera's name.

How many events of each label each model counted, with the events that came before the setup history listed apart:

```sql
SELECT COALESCE(setup_model_file, '(no setup recorded)') AS model_file,
       label,
       COUNT(*) AS events
FROM events_with_setup
GROUP BY setup_model_file, label
ORDER BY setup_model_file, events DESC;
```

The events a camera recorded while its zones were as they are now, by label:

```sql
SELECT label, COUNT(*) AS events
FROM events_with_setup
WHERE camera = 'picam_h265'
  AND camera_zones = (SELECT zones FROM setup_camera
                      WHERE camera = 'picam_h265' AND ended IS NULL)
GROUP BY label
ORDER BY events DESC;
```

To compare two models, compare their counts over periods of similar traffic, and check each model's `labels_available` first: a label a model can't recognise is never counted.

## What to know

* **A change made in Frigate's own screens is recorded within five minutes.** Events in between are tied to the earlier row.
* **A change made on the control app's pages is recorded sooner.** A camera entry you save on the [Cameras](../use/cameras.md) page is recorded about 30 seconds later. When you use another model on the [Detection](../use/detection.md) page, the device records it about 30 seconds later, and the new model's row starts when Frigate has restarted and answers.
* **While Frigate is down, nothing is recorded as changed.** When Frigate doesn't answer, runs in safe mode, or can't say which profile is active, the rows stay as they are, and the row for the new setup starts once it answers. A camera's row ends when its key leaves `config.yml`, whatever Frigate says.
* **Events from before this was installed have no row.** Their setup columns in the view are empty. The first rows start within a few minutes of an upgrade.
* **The Status page says when it stops.** The **Setup history** check on the [Status](../use/device-health.md#the-setup-history-checks) page warns when no snapshot has arrived for 15 minutes.

## What the device uploads

With **Share data** on, the device sends the setup history to the server as one `setup` telemetry value, `{"device": [...], "cameras": [...]}`: the rows of `setup_device` and `setup_camera`, with the fields below. There is no separate choice for it. See [MQTT and ThingsBoard](integrations.md#thingsboard) for the list of what is sent.

* **When a row opens or closes,** the device sends it. A change to the model sends the row that ended and the new one.
* **Every open row is sent again** after Node-RED starts, after the upload is turned on or its server changes, and once a day. A unit that starts sharing months after its rows opened still tells the server its setup, and a row the server missed arrives again.
* **A row can arrive more than once.** A server keeps one row for each `id`. A row that closed while sharing was off, or while the server couldn't be reached, is never sent after the fact. The server learns the setup from the open rows, and a close it missed shows as the start of the next row.
* **A sent row** has the table's columns in order, with the JSON columns as lists and objects, and `ended` empty while the row is in force. It leaves out `model_title`, `model_file`, and `profile`.

## What an operator typed

The rows hold a few names a person chose, and they are saved with your data. They are a zone's `key`, a model's title (`model_title`) and file name (`model_file`), and a profile's key (`profile`). A zone's key is saved with every event already; see [Zone names are saved with your data](../use/cameras.md#zone-names-are-saved-with-your-data). Don't name any of these after a street, a house number, or a person. The Status page's **Model and profile names** check warns when a model's title, the file name of a model you uploaded (the part before its last dot), or a profile's key looks like an address or a person's name, and never shows the name.

A zone's key is sent with shared data, inside `zones`, as it is with every event. A model's title, its file name, and a profile's key stay on the device, in the database and its download, and are never uploaded. A server tells models apart by `model_sha256` and `model_id`, and sees a profile only as settings that changed.

The names Frigate shows for zones, masks, and cameras are not kept. Frigate's own name for a camera, a camera's stream address, and a mask's id aren't either. The rows say which camera by its key in `config.yml`.
