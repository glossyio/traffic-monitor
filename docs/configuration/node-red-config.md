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
* A `deployment` without `lat` or `lon` isn't recorded, so leave the keys in place even when they're empty.
* A camera whose `camera_radar` names a radar that isn't in the file records no events. On a device without a radar, remove `camera_radar` or keep the radar's entry with `enabled: false`.

## thingsboard

Uploads events, readings, and device telemetry to a [ThingsBoard](https://thingsboard.io/) server. See [MQTT and ThingsBoard](../data-and-payloads/integrations.md).

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | `true` or `false` | `false` | Turn the upload on. |
| `host` | text | `tb.server.com` (a placeholder) | The server's hostname, without protocol or port. Required when enabled. |
| `protocol` | `http` or `https` | `https` | How to reach the server. |
| `port` | number | none | Set it only if the server isn't on the standard port for the protocol. |
| `access_token` | text | empty | The device's access token from ThingsBoard. This is the one secret in the file. |

## deployment

Where the device is. Every event and reading is stored with a deployment id that points at these values, so set them before you collect data and update them when you move the device.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `lat` | decimal degrees, such as `45.5225` | empty | Latitude. Four decimal places give address-level accuracy. |
| `lon` | decimal degrees, such as `-122.6919` | empty | Longitude. |
| `bearing` | `n`, `s`, `e`, `w`, `ne`, `nw`, `se`, or `sw` | empty | The compass direction the camera and radar face. |

A `deployment:` block with the same three settings under any sensor overrides these for that sensor, for a device whose cameras face different ways.

## sensors.cameras

One entry per camera, named exactly as the camera is named in Frigate. The default camera is `picam_h265`. Events from a camera that isn't listed here, or is disabled, are ignored.

To rename a camera, rename it in Frigate's config and choose **Save & Restart**. Frigate uses a new camera name only after it restarts, so **Save** alone changes nothing yet. Then rename its entry here to match. Until both names agree, that camera's events aren't recorded, and the Status page's **Cameras in config.yml** check shows an error.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | `true` or `false` | `true` for `picam_h265` | Record this camera's events. Frigate keeps running either way. |
| `camera_radar` | a radar name from `sensors.radars` | `TM_RADAR_SERIAL_PORT_00` | The radar that supplies speeds for this camera. One radar can serve several cameras. Leave it out on a device without a radar. |
| `plate_recognizer` | `true` or `false` | `false` | Send this camera's events to the [Plate Recognizer](../add-ons/plate-recognizer.md) add-on. |
| `deployment` | block | inherited | Per-camera `lat`, `lon`, and `bearing`. |

## sensors.radars

One entry per radar. A radar's name is the name of the variable that holds its serial port in [node-red-tm.env](environment.md), `TM_RADAR_SERIAL_PORT_00` through `TM_RADAR_SERIAL_PORT_03`.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | `true` or `false` | `true` for `TM_RADAR_SERIAL_PORT_00` | Read this radar. Set it to `false` on a device without a radar. |
| `opt_api_commands_array` | a JSON array in a string | `'["^/+0.00\n", "^/-0.00\n"]'` | Extra [OPS243 API](https://omnipresense.com/wp-content/uploads/2023/06/AN-010-Y_API_Interface.pdf) commands sent to the radar when the service starts and whenever you save this file, after the Traffic Monitor's own setup commands. The default sets the cosine correction to 0 degrees in both directions. |
| `deployment` | block | inherited | Per-radar `lat`, `lon`, and `bearing`. |

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
| `token` | text | none | Your Plate Recognizer API token. Plates aren't read until this is set. |
| `url` | URL | none | The add-on's address inside the device, `http://plate-recognizer:8080`. |
