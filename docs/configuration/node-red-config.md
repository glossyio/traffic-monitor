---
description: Every setting in the Traffic Monitor's config.yml, with its type, default, and effect.
---

# config.yml settings

The Traffic Monitor's own settings live in `/opt/traffic-monitor/node-red-tm/config/config.yml` on the device. The installer writes it from [this template](https://github.com/glossyio/traffic-monitor/blob/main/container/node-red-tm/config/config.yml.j2) on the first install and leaves it alone afterwards, unless you run the installer with `-f`.

The Traffic Monitor reads the file again whenever you save it, so changes take effect without a restart. If the file has a YAML error, it keeps the previous settings until the service restarts, and after a restart it has no settings at all until you fix the file.

Keep the three top-level sections (`thingsboard`, `deployment`, `sensors`) in the file. The file has no time settings: the installer's `-z` option sets the device's time zone, and you change it later on the [Date and time](../use/device-health.md#the-date-and-time-page) page. A `time` section left from an older install is ignored. The Default column below shows the values the template writes. A setting that's missing from the file behaves differently in a few cases:

* A camera or radar without `enabled` is off.
* A radar without `opt_api_commands_array` gets no extra commands.
* ThingsBoard without `host` stays off.
* A camera whose `camera_radar` names a radar that isn't in the file records no events. On a device without a radar, remove `camera_radar` or keep the radar's entry with `enabled: false`.

## thingsboard

Uploads events, readings, and device telemetry to a [ThingsBoard](https://thingsboard.io/) server. See [MQTT and ThingsBoard](../data-and-payloads/integrations.md).

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | `true` or `false` | `false` | Turn the upload on. |
| `host` | text | `tb.server.com` (a placeholder) | The server's hostname. If it starts with `http://` or `https://`, that is used and `protocol` is ignored. Required when enabled. |
| `protocol` | `http` or `https` | `https` | How to reach the server. |
| `port` | number | none | Set it only if the server isn't on the standard port for the protocol. |

The device's access token isn't in this file. Set it on the control app's [Device page](../use/device-health.md#tokens-and-keys); it's kept with the device's other secrets.

## deployment

Where the device is. Every event and reading is stored with a deployment id that points at these values. The control app's [Location page](../use/location.md) writes them when you claim the device, deploy it to a place, change the precision, or correct a value, so you rarely edit them here. All of them are optional.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `survey_id` | `<8 lower-case hex digits>-si`, such as `3f9a1c2e-si` | empty | The place in use, with no coordinates in it. The Location page writes it. Each device makes its own ids, and two devices never need to share one. Upper case is folded to lower case; an id in any other form is ignored and logged as an error. |
| `database_precision` | `none`, `1`, or `2` | `'2'` | How many decimal places of `lat` and `lon` the database keeps: `none` stores no coordinates, `1` about 10 km, `2` about 1 km. A number without quotes works too. |
| `lat` | decimal degrees, such as `45.52252` | empty | Latitude of the place in use, optional, with five decimal places at most. The database stores it rounded to `database_precision`; this file and the control app keep the exact value. |
| `lon` | decimal degrees, such as `-122.69120` | empty | Longitude, optional, with the same rules as `lat`. Set both or neither: a row with only one gets neither. |
| `bearing` | `n`, `s`, `e`, `w`, `ne`, `nw`, `se`, or `sw` | empty | The compass direction the camera and radar face. Optional; a value that isn't one of these, including one with spaces around it, is logged as an error. |

A change of `survey_id`, or of a sensor's `bearing`, closes that sensor's current deployment and starts a new one. A change of `lat` or `lon` doesn't. While `survey_id` is empty, current deployments stay as they are, and a bearing change waits until you set one. When you first set `survey_id`, a current deployment with no survey id and the same bearing takes it over and keeps its deployment id.

Lowering `database_precision` rewrites the current deployments in place. Raising it takes effect from the next new deployment, because coordinates already rounded can't be made finer. The Location page can also round the rows already stored; see [Choose the precision](../use/location.md#choose-the-precision).

A `deployment:` block under a camera or radar can hold `bearing`, for a device whose cameras face different ways. A `lat` or `lon` there isn't read, because the location belongs to the whole device. The installer removes it, and the Status page's Location check warns about it until then.

### Edit the location by hand

Use the [Location page](../use/location.md) to move the device or fix a value. If you edit this section by hand instead, Node-RED applies the change as soon as you save the file, and the control app records it the next time its Location page is opened:

* **`survey_id` set to a place the page lists** is a move there, as **Deploy here** would be. The file takes that place's location, replacing any `lat` or `lon` you changed in the same edit.
* **`survey_id` set to an id the page doesn't list** becomes a new place, in use, at this file's `lat` and `lon`.
* **Only `lat` or `lon` changed** is a correction of the place in use, as **Correct location** would be: the place's stored rows take the new location.
* **A `lat` or `lon` that isn't a number in range**, such as one with a typo, stays in the file as you typed it. New deployments store no location until you fix it, and the Status page's Location check names the key.

On a device upgraded from a release that recorded coordinates, the update leaves `survey_id` empty, and the control app fills it in the first time the Location page is opened; see [Places after an update](../build-your-own-device-diy/update.md#places-after-an-update).

## sensors.cameras

One entry per camera, named exactly as the camera is named in Frigate. The default camera is `picam_h265`. Events from a camera that isn't listed here, or is disabled, are ignored.

To rename a camera, rename it in Frigate's config and choose **Save & Restart**. Frigate uses a new camera name only after it restarts, so **Save** alone changes nothing yet. Then rename its entry here to match. Until both names agree, that camera's events aren't recorded, and the Status page's **Cameras in config.yml** check shows an error.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | `true` or `false` | `true` for `picam_h265` | Record this camera's events. Frigate keeps running either way. |
| `camera_radar` | a radar name from `sensors.radars` | `TM_RADAR_SERIAL_PORT_00` | The radar that supplies speeds for this camera. One radar can serve several cameras. Leave it out on a device without a radar. |
| `plate_recognizer` | `true` or `false` | `false` | Send this camera's events to the [Plate Recognizer](../add-ons/plate-recognizer.md) add-on. |
| `deployment` | block | inherited | Per-camera `bearing`. |

## sensors.radars

One entry per radar. A radar's name is the name of the variable that holds its serial port in [node-red-tm.env](environment.md), `TM_RADAR_SERIAL_PORT_00` through `TM_RADAR_SERIAL_PORT_03`.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | `true` or `false` | `true` for `TM_RADAR_SERIAL_PORT_00` | Read this radar. Set it to `false` on a device without a radar. |
| `opt_api_commands_array` | a JSON array in a string | `'["^/+0.00\n", "^/-0.00\n"]'` | Extra [OPS243 API](https://omnipresense.com/wp-content/uploads/2023/06/AN-010-Y_API_Interface.pdf) commands sent to the radar when the service starts and whenever you save this file, after the Traffic Monitor's own setup commands. The default sets the cosine correction to 0 degrees in both directions. |
| `deployment` | block | inherited | Per-radar `bearing`. |

## sensors.airquality_monitors

One entry per [air quality sensor](../add-ons/air-quality.md), named as the middle part of the topic the sensor publishes to: `aq/<name>/readings`.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | `true` or `false` | `false` | Record this sensor's readings. Readings from a sensor that isn't enabled are dropped. |
| `mqtt_topic_incoming` | text | `readings` | Present in the template but not used. The device subscribes to every topic under `aq/`. |

## addons.plate_recognizer

Only needed with the [Plate Recognizer](../add-ons/plate-recognizer.md) add-on. The section isn't in the template; add it.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `url` | URL | none | The add-on's address inside the device, `http://plate-recognizer:8080`. |

The API token and license key aren't in this file. Set them on the control app's [Device page](../use/device-health.md#tokens-and-keys); plates aren't read until they're set.
