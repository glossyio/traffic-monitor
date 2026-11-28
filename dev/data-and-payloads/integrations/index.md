# MQTT and ThingsBoard

The MQTT broker is on by default and accepts connections only from the device itself. The ThingsBoard upload is off until you turn it on.

## MQTT

Node-RED hosts an MQTT broker on the device at port `1883`. Frigate, the air quality sensor, and Node-RED connect to it on the device. Other devices on your network, such as Home Assistant or a display board that shows the day's counts, can connect once you give the broker a login; see [Connect from other devices](#connect-from-other-devices). Settings are in [node-red-tm.env](https://docs.trafficmonitor.ai/dev/configuration/environment/index.md).

| Topic                                | Direction                                                                                                    | Contents                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frigate/events`                     | Frigate to the Traffic Monitor                                                                               | Frigate's [event messages](https://docs.frigate.video/integrations/mqtt). The Traffic Monitor records the ones with `type: "end"` as [events](https://docs.trafficmonitor.ai/dev/data-and-payloads/events-payload/index.md), and reads the `new` and `update` ones for the [time stopped and the time in each zone](https://docs.trafficmonitor.ai/dev/data-and-payloads/events-payload/#time-stopped-and-time-in-each-zone). |
| `frigate/<camera>/<object>/snapshot` | Frigate to subscribers                                                                                       | A cropped JPEG of each detected object, which can show a person. Frigate publishes it only when the camera's `mqtt` setting is on, and new installs turn it off. The Traffic Monitor doesn't use it. See [Tune object detection](https://docs.trafficmonitor.ai/dev/configuration/frigate-config/#recordings-and-snapshots).                                                                                                  |
| `frigate/stats`                      | Frigate to the Traffic Monitor                                                                               | Frigate's status report, about once a minute. The Traffic Monitor adds each camera's frame rates and whether detection was on up into the [watch log](https://docs.trafficmonitor.ai/dev/data-and-payloads/watch-log/index.md). Each report also prompts it to read from Frigate's settings whether each camera is on.                                                                                                        |
| `frigate/onConnect`                  | The Traffic Monitor to Frigate                                                                               | An empty message, sent when a [reference picture](https://docs.trafficmonitor.ai/dev/use/cameras/#the-people-check) is taken, to ask what Frigate is tracking.                                                                                                                                                                                                                                                                |
| `frigate/camera_activity`            | Frigate to the Traffic Monitor                                                                               | Frigate's answer to `frigate/onConnect`: each camera's tracked objects. The Traffic Monitor keeps each object's label and whether it is standing still, for the picture's data file, and nothing else. Like `frigate/events`, the message itself can hold a recognized name when Frigate's face recognition is on, and a client that holds the broker's login can read it.                                                    |
| `aq/<sensor>/readings`               | [Air quality sensor](https://docs.trafficmonitor.ai/dev/add-ons/air-quality/index.md) to the Traffic Monitor | One JSON reading. See [Air quality](https://docs.trafficmonitor.ai/dev/data-and-payloads/air-quality-aq-payload/index.md).                                                                                                                                                                                                                                                                                                    |
| `tm/events`                          | The Traffic Monitor to subscribers                                                                           | Today's cumulative counts, mainly for a display board. Published with QoS 1 and retained, so a new subscriber gets the latest counts at once. See below.                                                                                                                                                                                                                                                                      |

`tm/event`, without the `s`, is the per-event message inside Node-RED. Each recorded event carries it to the dashboards and to the ThingsBoard upload. It isn't published on the broker, so MQTT clients such as Home Assistant can't subscribe to it.

### tm/events

A JSON object with the same counts as **Today's counts** on the [Monitoring](https://docs.trafficmonitor.ai/dev/ui/monitoring/index.md) dashboard: events that passed through `zone_capture`, for the camera selected on the legacy dashboard at `http://<device>/ui/`, in a day that starts at 04:00 local time.

| Key                                                         | Meaning                                                                                                                                                                                                                                                                            |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `car`, `person`, `bicycle`, `motorcycle`, `bus`, `dog`, ... | One key per object type that has been counted today, named as Frigate labels it                                                                                                                                                                                                    |
| `bicycle_adj`                                               | `bicycle` plus `motorcycle`. Present once a bicycle has been counted.                                                                                                                                                                                                              |
| `person_adj`                                                | `person` minus `bicycle` minus `motorcycle`: a pedestrian count, because every cyclist is also detected as a person. Scooter riders count as people. It can be negative, when more bicycles and motorcycles than people have been counted. Present once a person has been counted. |
| `event_latest`                                              | The object type of the most recent counted event, such as `car`                                                                                                                                                                                                                    |

To watch it from another computer:

```
mosquitto_sub -h <device> -u <username> -P <password> -t tm/events
```

### Connect from other devices

1. Give the broker a login:

   ```
   bash traffic-monitor/script/tmsetup.sh -t node-red-tm -C mqtt_lan
   ```

   This creates the username `tm` and a random password. To choose your own instead, set `TM_MQTT_BROKER_USERNAME` and `TM_MQTT_BROKER_PASSWORD` in `/opt/traffic-monitor/node-red-tm/node-red-tm.env` and run the command without `-C mqtt_lan`. Use only letters, digits, `.`, `_`, and `-`, with no quotes and no comment after the value on the same line; otherwise the installer stops with a message.

   The broker then requires the login from every client, the installer gives it to Frigate, and port 1883 opens to your network.

1. Read the login:

   ```
   sudo grep ^TM_MQTT_BROKER_ /opt/traffic-monitor/node-red-tm/node-red-tm.env
   ```

1. Give it to the [air quality sensor](https://docs.trafficmonitor.ai/dev/add-ons/air-quality/index.md) and to each MQTT client.

1. Check from another computer:

   ```
   mosquitto_sub -h <device> -u <username> -P <password> -t tm/events
   ```

1. To change the login, edit the two values and run `bash traffic-monitor/script/tmsetup.sh -t node-red-tm` again. To remove it, leave both values blank and run the same command: the broker stops checking logins and port 1883 closes to the network.

Warning

The login crosses the network unencrypted, and anyone who has it can read every topic and publish false data. Open MQTT only on a network you trust.

## ThingsBoard

The device can upload its data to a [ThingsBoard](https://thingsboard.io/) server, which gives you dashboards and storage for a fleet of devices. Turn it on, and choose what is uploaded, on the control app's Sharing page; see [Share data](https://docs.trafficmonitor.ai/dev/use/sharing/index.md). The page sets the server and the device's access token. The [`thingsboard` section](https://docs.trafficmonitor.ai/dev/configuration/node-red-config/#thingsboard) of config.yml holds the server's address.

Once connected, the device sends over ThingsBoard's HTTP API:

- Each [event](https://docs.trafficmonitor.ai/dev/data-and-payloads/events-payload/index.md) as telemetry, with `ts` set to the event's `frame_time` in milliseconds and `values.event` holding the event's columns that are on the list of what is shared, [`upload-lists.json`](https://github.com/glossyio/traffic-monitor/blob/main/container/node-red-tm/data/upload-lists.json). A column that isn't on the list stays on the device.
- Each [radar](https://docs.trafficmonitor.ai/dev/data-and-payloads/radar-payload/index.md) and [air quality](https://docs.trafficmonitor.ai/dev/data-and-payloads/air-quality-aq-payload/index.md) reading as telemetry. Readings from the high-rate radar tables are batched to avoid hundreds of messages per vehicle.
- The device's system metrics as telemetry, every five minutes.
- The [watch log](https://docs.trafficmonitor.ai/dev/data-and-payloads/watch-log/index.md) as telemetry, every five minutes: one `watch` value with `cameras` and `radars` lists holding that window's rows, and `ts` set to the end of the window in milliseconds. The fields sent are the `watch_camera` and `watch_radar` lists in `upload-lists.json`, which hold every column of the two tables.
- The [setup history](https://docs.trafficmonitor.ai/dev/data-and-payloads/setup-history/index.md) as telemetry: one `setup` value with `device`, `cameras`, and `radars` lists of rows, sent when a row opens or closes. A list with no rows is left out. Only the zones that are on are sent, and only for a camera that is captured. The device also sends every open row again when the cameras that are captured change, on the first complete snapshot after Node-RED starts, after the upload is turned on or its server changes, and once a day; the radars' open rows are sent again after Node-RED starts, after the upload is turned on or its server changes, and once a day. A row can arrive more than once, so a server should key rows on `id`. The device sends an empty value as `null`, but ThingsBoard leaves out a key whose value is `null` when it stores the row, so a row that is still in force arrives there without `ended`, and a fact the device doesn't know arrives without its key. The fields sent are the `setup_device`, `setup_camera`, and `setup_radar` lists in `upload-lists.json`. The first two hold every column of their tables except `model_title`, `model_file`, and `profile`: a model's title and file name and a profile's key are never sent. The third holds all twelve columns of `setup_radar`: the radar's key, model, firmware version, and the settings it runs with, among them the two angles that correct its speeds. A radar's serial number is not in the table and is never sent. A server tells models apart by `model_sha256` and `model_id`, and sees a profile only as settings that changed. A camera that isn't captured has no `zones` in its row, and a zone that is off is left out of the list.
- The deployment location and radar information as device attributes. Each sensor's entry in the `deployments` attribute, and each deployment row sent as telemetry, carries `heading_deg`, the way the sensor faces in whole degrees clockwise from true north. Earlier releases sent `bearing`, a compass point, in its place. A dashboard, rule, or script that read `bearing` must read `heading_deg` now; the old key is no longer sent, and the value is a number, not a letter pair. In the attribute every value is text, so the heading arrives as `"90"`, or as an empty string when none is set. A deployment row sent as telemetry also carries the place's `timezone`, a tz database name, how the sensor is mounted: `pitch_deg`, `height_m`, `view_distance_m`, and `mount`, and the radar's aim and the street in its view: `road_angle_deg`, `lane_distance_m`, `lane_width_m`, `lanes_toward`, `lanes_away`, `turn_lane`, `toward_side`, and `intersection`. The zone is sent whatever the precision, and each of these thirteen is `null` when none was set or recorded. They hold no coordinate, name, or description. Only the fields on the `deployment` list in `upload-lists.json` are sent; a field of a row that isn't on the list stays on the device. The `deployments` attribute itself carries the sensor's type, location, heading, and id only, with no time zone.
