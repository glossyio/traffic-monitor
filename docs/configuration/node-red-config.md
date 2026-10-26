---
description: Every setting in the Traffic Monitor's config.yml, with its type, default, and effect.
---

# config.yml settings

The Traffic Monitor's own settings live in `/opt/traffic-monitor/node-red-tm/config/config.yml` on the device. The installer writes it from [this template](https://github.com/glossyio/traffic-monitor/blob/main/container/node-red-tm/config/config.yml.j2) on the first install and leaves it alone afterwards, unless you run the installer with `-f`.

The file is read only when the Node-RED service starts, so after editing it run:

```bash
sudo systemctl restart node-red-tm.service
```

Keep the four top-level sections (`thingsboard`, `deployment`, `sensors`, `time`) in the file. Within them, a missing setting takes the default below.

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
| `opt_api_commands_array` | a JSON array in a string | `'["^/+0.00\n", "^/-0.00\n"]'` | Extra [OPS243 API](https://omnipresense.com/wp-content/uploads/2023/06/AN-010-Y_API_Interface.pdf) commands sent to the radar when the service starts, after the Traffic Monitor's own setup commands. The default sets the cosine correction to 0 degrees in both directions. |
| `deployment` | block | inherited | Per-radar `lat`, `lon`, and `bearing`. |

## sensors.airquality_monitors

One entry per [air quality sensor](../add-ons/air-quality.md), named as the middle part of the topic the sensor publishes to: `aq/<name>/readings`.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | `true` or `false` | `false` | Record this sensor's readings. Readings from a sensor that isn't enabled are dropped. |
| `mqtt_topic_incoming` | text | `readings` | Present in the template but not used. The device subscribes to every topic under `aq/`. |

## time

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `timezone` | a [tz database name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) | the installer's `-z` value, `America/Los_Angeles` unless you set one | The time zone the dashboards use, including the 04:00 daily reset. The installer sets the system clock to the same zone. |
| `npt_set` | `true` or `false` | `true` | Present in the template but not used. |

## addons.plate_recognizer

Only needed with the [Plate Recognizer](../add-ons/plate-recognizer.md) add-on. The section isn't in the template; add it.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `token` | text | none | Your Plate Recognizer API token. Plates aren't read until this is set. |
| `url` | URL | none | The add-on's address inside the device, `http://plate-recognizer:8080`. |
