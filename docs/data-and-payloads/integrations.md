---
description: The device's MQTT broker and topics, the daily counts it publishes, and the optional ThingsBoard upload with config backup.
---

# MQTT and ThingsBoard

Nothing leaves the device unless you set up one of these.

## MQTT

Node-RED hosts an MQTT broker on the device at port `1883`, with no authentication. Settings are in [node-red-tm.env](../configuration/environment.md). Any MQTT client on your network can subscribe, for example Home Assistant or a display board that shows the day's counts.

| Topic | Direction | Contents |
|---|---|---|
| `frigate/events` | Frigate to the Traffic Monitor | Frigate's [event messages](https://docs.frigate.video/integrations/mqtt). The Traffic Monitor records the ones with `type: "end"` as [events](events-payload.md). |
| `aq/<sensor>/readings` | [Air quality sensor](../add-ons/air-quality.md) to the Traffic Monitor | One JSON reading. See [Air quality](air-quality-aq-payload.md). |
| `tm/events` | The Traffic Monitor to subscribers | Today's cumulative counts, mainly for a display board. Published with QoS 1 and retained, so a new subscriber gets the latest counts at once. See below. |

`tm/event`, without the `s`, is the per-event message inside Node-RED. Each recorded event carries it to the dashboards and to the ThingsBoard upload. It isn't published on the broker, so MQTT clients such as Home Assistant can't subscribe to it.

### tm/events

A JSON object with today's counts for events that passed through `zone_capture`. The counts are for the camera selected on the legacy dashboard at `http://<device>/ui/`. The day starts at 04:00 local time, so from midnight until 04:00 the counts are empty.

| Key | Meaning |
|---|---|
| `car`, `person`, `bicycle`, `motorcycle`, `bus`, `dog`, ... | One key per object type that has been counted today, named as Frigate labels it |
| `bicycle_adj` | `bicycle` plus `motorcycle`. Present once a bicycle has been counted. |
| `person_adj` | `person` minus `bicycle` minus `motorcycle`: a pedestrian count, because every cyclist is also detected as a person. Scooter riders count as people. It can be negative, when more bicycles and motorcycles than people have been counted. Present once a person has been counted. |
| `event_latest` | The object type of the most recent counted event, such as `car` |

To watch it from another computer:

```bash
mosquitto_sub -h <device> -t tm/events
```

## ThingsBoard

The device can upload its data to a [ThingsBoard](https://thingsboard.io/) server, which gives you dashboards and storage for a fleet of devices. Turn it on in the `thingsboard` section of [config.yml](../configuration/node-red-config.md#thingsboard) with the server's hostname and the device's access token. The device picks up the change when you save the file.

Once connected, the device sends over ThingsBoard's HTTP API:

* Each [event](events-payload.md) as telemetry, with `ts` set to the event's `frame_time` in milliseconds and `values` holding every column of the event.
* Each [radar](radar-payload.md) and [air quality](air-quality-aq-payload.md) reading as telemetry. Readings from the high-rate radar tables are batched to avoid hundreds of messages per vehicle.
* The device's system metrics as telemetry, every five minutes.
* The deployment location, radar information, and the Traffic Monitor settings as device attributes.

### Config backup

With ThingsBoard connected, the **Backup & Restore** section of the legacy dashboard at `http://<device>/ui/` saves Frigate's config as an attribute of the device in ThingsBoard.
