# MQTT and ThingsBoard

The MQTT broker is on by default and accepts connections only from the device itself. The ThingsBoard upload is off until you turn it on.

## MQTT

Node-RED hosts an MQTT broker on the device at port `1883`. Frigate, the air quality sensor, and Node-RED connect to it on the device. Other devices on your network, such as Home Assistant or a display board that shows the day's counts, can connect once you give the broker a login; see [Connect from other devices](#connect-from-other-devices). Settings are in [node-red-tm.env](https://docs.trafficmonitor.ai/dev/configuration/environment/index.md).

| Topic                                | Direction                                                                                                    | Contents                                                                                                                                                                                                                                                                                                                     |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frigate/events`                     | Frigate to the Traffic Monitor                                                                               | Frigate's [event messages](https://docs.frigate.video/integrations/mqtt). The Traffic Monitor records the ones with `type: "end"` as [events](https://docs.trafficmonitor.ai/dev/data-and-payloads/events-payload/index.md).                                                                                                 |
| `frigate/<camera>/<object>/snapshot` | Frigate to subscribers                                                                                       | A cropped JPEG of each detected object, which can show a person. Frigate publishes it only when the camera's `mqtt` setting is on, and new installs turn it off. The Traffic Monitor doesn't use it. See [Tune object detection](https://docs.trafficmonitor.ai/dev/configuration/frigate-config/#recordings-and-snapshots). |
| `aq/<sensor>/readings`               | [Air quality sensor](https://docs.trafficmonitor.ai/dev/add-ons/air-quality/index.md) to the Traffic Monitor | One JSON reading. See [Air quality](https://docs.trafficmonitor.ai/dev/data-and-payloads/air-quality-aq-payload/index.md).                                                                                                                                                                                                   |
| `tm/events`                          | The Traffic Monitor to subscribers                                                                           | Today's cumulative counts, mainly for a display board. Published with QoS 1 and retained, so a new subscriber gets the latest counts at once. See below.                                                                                                                                                                     |

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

The device can upload its data to a [ThingsBoard](https://thingsboard.io/) server, which gives you dashboards and storage for a fleet of devices. Turn it on in the `thingsboard` section of [config.yml](https://docs.trafficmonitor.ai/dev/configuration/node-red-config/#thingsboard) with the server's hostname and the device's access token. The device picks up the change when you save the file.

Once connected, the device sends over ThingsBoard's HTTP API:

- Each [event](https://docs.trafficmonitor.ai/dev/data-and-payloads/events-payload/index.md) as telemetry, with `ts` set to the event's `frame_time` in milliseconds and `values` holding every column of the event.
- Each [radar](https://docs.trafficmonitor.ai/dev/data-and-payloads/radar-payload/index.md) and [air quality](https://docs.trafficmonitor.ai/dev/data-and-payloads/air-quality-aq-payload/index.md) reading as telemetry. Readings from the high-rate radar tables are batched to avoid hundreds of messages per vehicle.
- The device's system metrics as telemetry, every five minutes.
- The deployment location, radar information, and the Traffic Monitor settings as device attributes.

### Config backup

With ThingsBoard connected, the **Backup & Restore** section of the legacy dashboard at `http://<device>/ui/` saves Frigate's config as an attribute of the device in ThingsBoard.
