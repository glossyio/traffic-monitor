---
description: The device's MQTT broker and topics, the daily counts it publishes, and the optional ThingsBoard upload.
---

# MQTT and ThingsBoard

The MQTT broker is on by default and accepts connections only from the device itself. The ThingsBoard upload is off until you turn it on.

## MQTT

Node-RED hosts an MQTT broker on the device at port `1883`. Frigate, the air quality sensor, and Node-RED connect to it on the device. Other devices on your network, such as Home Assistant or a display board that shows the day's counts, can connect once you give the broker a login; see [Connect from other devices](#connect-from-other-devices). Settings are in [node-red-tm.env](../configuration/environment.md).

| Topic | Direction | Contents |
|---|---|---|
| `frigate/events` | Frigate to the Traffic Monitor | Frigate's [event messages](https://docs.frigate.video/integrations/mqtt). The Traffic Monitor records the ones with `type: "end"` as [events](events-payload.md), and reads the `new` and `update` ones for the [time stopped and the time in each zone](events-payload.md#time-stopped-and-time-in-each-zone). |
| `frigate/<camera>/<object>/snapshot` | Frigate to subscribers | A cropped JPEG of each detected object, which can show a person. Frigate publishes it only when the camera's `mqtt` setting is on, and new installs turn it off. The Traffic Monitor doesn't use it. See [Tune object detection](../configuration/frigate-config.md#recordings-and-snapshots). |
| `frigate/stats` | Frigate to the Traffic Monitor | Frigate's status report, about once a minute. The Traffic Monitor adds each camera's frame rates and whether detection was on up into the [watch log](watch-log.md). Each report also prompts it to read from Frigate's settings whether each camera is on. |
| `aq/<sensor>/readings` | [Air quality sensor](../add-ons/air-quality.md) to the Traffic Monitor | One JSON reading. See [Air quality](air-quality-aq-payload.md). |
| `tm/events` | The Traffic Monitor to subscribers | Today's cumulative counts, mainly for a display board. Published with QoS 1 and retained, so a new subscriber gets the latest counts at once. See below. |

`tm/event`, without the `s`, is the per-event message inside Node-RED. Each recorded event carries it to the dashboards and to the ThingsBoard upload. It isn't published on the broker, so MQTT clients such as Home Assistant can't subscribe to it.

### tm/events

A JSON object with the same counts as **Today's counts** on the [Monitoring](../ui/monitoring.md) dashboard: events that passed through `zone_capture`, for the camera selected on the legacy dashboard at `http://<device>/ui/`, in a day that starts at 04:00 local time.

| Key | Meaning |
|---|---|
| `car`, `person`, `bicycle`, `motorcycle`, `bus`, `dog`, ... | One key per object type that has been counted today, named as Frigate labels it |
| `bicycle_adj` | `bicycle` plus `motorcycle`. Present once a bicycle has been counted. |
| `person_adj` | `person` minus `bicycle` minus `motorcycle`: a pedestrian count, because every cyclist is also detected as a person. Scooter riders count as people. It can be negative, when more bicycles and motorcycles than people have been counted. Present once a person has been counted. |
| `event_latest` | The object type of the most recent counted event, such as `car` |

To watch it from another computer:

```bash
mosquitto_sub -h <device> -u <username> -P <password> -t tm/events
```

### Connect from other devices

1. Give the broker a login:

    ```bash
    bash traffic-monitor/script/tmsetup.sh -t node-red-tm -C mqtt_lan
    ```

    This creates the username `tm` and a random password. To choose your own instead, set `TM_MQTT_BROKER_USERNAME` and `TM_MQTT_BROKER_PASSWORD` in `/opt/traffic-monitor/node-red-tm/node-red-tm.env` and run the command without `-C mqtt_lan`. Use only letters, digits, `.`, `_`, and `-`, with no quotes and no comment after the value on the same line; otherwise the installer stops with a message.

    The broker then requires the login from every client, the installer gives it to Frigate, and port 1883 opens to your network.

2. Read the login:

    ```bash
    sudo grep ^TM_MQTT_BROKER_ /opt/traffic-monitor/node-red-tm/node-red-tm.env
    ```

3. Give it to the [air quality sensor](../add-ons/air-quality.md) and to each MQTT client.
4. Check from another computer:

    ```bash
    mosquitto_sub -h <device> -u <username> -P <password> -t tm/events
    ```

5. To change the login, edit the two values and run `bash traffic-monitor/script/tmsetup.sh -t node-red-tm` again. To remove it, leave both values blank and run the same command: the broker stops checking logins and port 1883 closes to the network.

!!! warning

    The login crosses the network unencrypted, and anyone who has it can read every topic and publish false data. Open MQTT only on a network you trust.

## ThingsBoard

The device can upload its data to a [ThingsBoard](https://thingsboard.io/) server, which gives you dashboards and storage for a fleet of devices. Turn it on, and choose what is uploaded, on the control app's Sharing page; see [Share data](../use/sharing.md). The page sets the server and the device's access token. The [`thingsboard` section](../configuration/node-red-config.md#thingsboard) of config.yml holds the server's address.

Once connected, the device sends over ThingsBoard's HTTP API:

* Each [event](events-payload.md) as telemetry, with `ts` set to the event's `frame_time` in milliseconds and `values.event` holding the event's columns that are on the list of what is shared, [`upload-lists.json`](https://github.com/glossyio/traffic-monitor/blob/main/container/node-red-tm/data/upload-lists.json). A column that isn't on the list stays on the device.
* Each [radar](radar-payload.md) and [air quality](air-quality-aq-payload.md) reading as telemetry. Readings from the high-rate radar tables are batched to avoid hundreds of messages per vehicle.
* The device's system metrics as telemetry, every five minutes.
* The [watch log](watch-log.md) as telemetry, every five minutes: one `watch` value with `cameras` and `radars` lists holding that window's rows, and `ts` set to the end of the window in milliseconds. The fields sent are the `watch_camera` and `watch_radar` lists in `upload-lists.json`, which hold every column of the two tables.
* The deployment location and radar information as device attributes. Each sensor's entry in the `deployments` attribute, and each deployment row sent as telemetry, carries `heading_deg`, the way the sensor faces in whole degrees clockwise from true north. Earlier releases sent `bearing`, a compass point, in its place. A dashboard, rule, or script that read `bearing` must read `heading_deg` now; the old key is no longer sent, and the value is a number, not a letter pair. In the attribute every value is text, so the heading arrives as `"90"`, or as an empty string when none is set. A deployment row sent as telemetry also carries the place's `timezone`, a tz database name, and how the sensor is mounted: `pitch_deg`, `height_m`, `view_distance_m`, and `mount`. The zone is sent whatever the precision, and each of these five is `null` when none was set or recorded. They hold no coordinate, name, or description. Only the fields on the `deployment` list in `upload-lists.json` are sent; a field of a row that isn't on the list stays on the device. The `deployments` attribute itself carries the sensor's type, location, heading, and id only, with no time zone.
