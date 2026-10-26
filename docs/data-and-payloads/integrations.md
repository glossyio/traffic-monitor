---
description: The device's MQTT broker and topics, the daily counts it publishes, and the optional ThingsBoard upload with config backup and restore.
---

# MQTT and ThingsBoard

Nothing leaves the device unless you set up one of these.

## MQTT

Node-RED hosts an MQTT broker on the device at port `1883`, with no authentication by default. Settings are in [node-red-tm.env](../configuration/environment.md). Any MQTT client on your network can subscribe, for example Home Assistant or a display that shows the day's counts.

| Topic | Direction | Contents |
|---|---|---|
| `frigate/events` | Frigate to the Traffic Monitor | Frigate's [event messages](https://docs.frigate.video/integrations/mqtt). The Traffic Monitor records the ones with `type: "end"` as [events](events-payload.md). |
| `aq/<sensor>/readings` | [Air quality sensor](../add-ons/air-quality.md) to the Traffic Monitor | One JSON reading. See [Air quality](air-quality-aq-payload.md). |
| `tm/events` | The Traffic Monitor to subscribers | Today's cumulative counts, updated as events are recorded. See below. |

### tm/events

A JSON object with today's counts for the camera selected on the [Monitoring dashboard](../ui/monitoring.md), covering events that passed through `zone_capture`. Counts reset at 04:00 local time.

| Key | Meaning |
|---|---|
| `car`, `person`, `bicycle`, `motorcycle`, `bus`, `dog`, ... | One key per object type that has been counted today, named as Frigate labels it |
| `bicycle_adj` | `bicycle` plus `motorcycle` |
| `person_adj` | `person` minus `bicycle` minus `motorcycle`: a pedestrian count, because every cyclist is also detected as a person. Scooter riders count as people. |
| `event_latest` | The most recent event |

To watch it from another computer:

```bash
mosquitto_sub -h <device> -t tm/events
```

## ThingsBoard

The device can upload its data to a [ThingsBoard](https://thingsboard.io/) server, which gives you dashboards and storage for a fleet of devices. Turn it on in the `thingsboard` section of [config.yml](../configuration/node-red-config.md#thingsboard) with the server's hostname and the device's access token, then restart the service.

Once connected, the device sends over ThingsBoard's HTTP API:

* Each [event](events-payload.md) as telemetry, with `ts` set to the event's `frame_time` in milliseconds and `values` holding every column of the event.
* Each [radar](radar-payload.md) and [air quality](air-quality-aq-payload.md) reading as telemetry. Readings from the high-rate radar tables are batched to avoid hundreds of messages per vehicle.
* The deployment location, the device's system metrics, radar information, and the Traffic Monitor settings as device attributes.

### Config backup and restore

With ThingsBoard connected, the **Backup & Restore** section of the legacy dashboard at `http://<device>/ui/` saves the device's settings files, including Frigate's config, as attributes of the device in ThingsBoard, and restores them from there. A restore pushes the Frigate part through Frigate's API and restarts Frigate.
