---
description: The events table: one row per object the camera detected, with its label, times, zones, direction, and radar speed.
---

# Events

An event is one object that Frigate detected and tracked until it left the frame: a car, a person, a bicycle, and so on. The Traffic Monitor adds the direction of travel and, when the device has a radar, the speed, and stores the result in the `events` table of the database.

## How an event is made

1. Frigate publishes a message on the device's MQTT topic `frigate/events` for each tracked object. When the object leaves the frame, the message has `type: "end"` and holds everything Frigate knows about it.
2. The Traffic Monitor keeps the `end` message if the camera is enabled in [config.yml](../configuration/node-red-config.md#sensorscameras) and the object moved.
3. It sets `direction_calc` from the order in which the object entered `zone_near` and `zone_far`.
4. If the object passed through `zone_radar` and the camera has a radar, it sets `speed_calc` to the median of the radar's readings in that direction while the object was in view, with a two-second margin on each side, and adds `radar` to `provenance`.
5. It writes the row, publishes today's counts on `tm/events`, and uploads the event to ThingsBoard if that is on. See [MQTT and ThingsBoard](integrations.md).

[First-time setup](../setup-guide.md#3-adjust-the-zones) describes the four zones.

## Columns

Values that come straight from Frigate's message are marked *Frigate*. Frigate's [MQTT](https://docs.frigate.video/integrations/mqtt) page documents them in full.

| Column | Type | Meaning | Values |
|---|---|---|---|
| `id` | TEXT, primary key | Frigate's event id | Unix time in seconds, a hyphen, and six random characters, such as `1721144705.617111-fg3luy` |
| `camera` | TEXT | *Frigate.* The camera's name | As named in Frigate, `picam_h265` by default |
| `label` | TEXT | *Frigate.* The object type | One of Frigate's [object labels](https://docs.frigate.video/configuration/objects) |
| `sub_label` | TEXT | *Frigate.* A label added by another process, such as a recognized face | Usually empty |
| `top_score` | REAL | *Frigate.* The highest detection score while the object was tracked | 0 to 1 |
| `frame_time` | REAL | *Frigate.* When the best frame of the object was taken | Unix time in seconds |
| `start_time` | REAL | *Frigate.* When the object was first seen | Unix time in seconds |
| `end_time` | REAL | *Frigate.* When the object was last seen | Unix time in seconds |
| `entered_zones` | TEXT | *Frigate.* The zones the object entered, in order | A JSON array of zone names, such as `["zone_capture", "zone_near", "zone_radar", "zone_far"]` |
| `score` | REAL | *Frigate.* The object's current score when the event ended | 0 to 1 |
| `area` | REAL | *Frigate.* Width × height of the object's box, in pixels | |
| `ratio` | REAL | *Frigate.* Width ÷ height of the object's box | Less than 1 is taller than wide |
| `motionless_count` | REAL | *Frigate.* Frames in which the object didn't move | A count |
| `position_changes` | REAL | *Frigate.* How many times the object changed position | A count |
| `attributes` | TEXT | *Frigate.* Attributes detected on the object, with their best scores | A JSON object, such as `{"face": 0.86}`; usually empty |
| `direction_calc` | TEXT | Direction of travel relative to the device | `outbound` (away from the device), `inbound` (toward it), or empty if the object didn't pass through both direction zones |
| `speed_calc` | REAL | Speed from the radar, in the radar's units (mph by default) | Positive for inbound and negative for outbound; empty if no speed was matched |
| `provenance` | TEXT | Which sensors contributed, primary first | A JSON array: `["frigate"]`, or `["frigate", "radar"]` when a speed was matched |
| `radarName` | TEXT | The radar paired with the camera, whether or not it supplied a speed | A radar name such as `TM_RADAR_SERIAL_PORT_00`, or empty |
| `deployment_id` | TEXT | Where the device was. See the [deployment](data-overview.md#deployment) table. | A `deployment.id`, or empty |
