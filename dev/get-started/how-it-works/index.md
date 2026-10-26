# How it works

A Traffic Monitor is a Raspberry Pi 5 running a few cooperating programs. Everything happens on the device, so it works without an internet connection once it's installed.

## From the street to the database

1. **The camera** streams H.265 video at 1536×864 and 10 frames per second to Frigate.

1. **[Frigate](https://frigate.video/)** finds and tracks objects in the video, using the AI accelerator if the device has one and the CPU if not. It records which **zones** each object passed through. When an object leaves the frame, Frigate publishes an event on the device's MQTT broker.

1. **The radar** (optional) measures the speed and direction of whatever moves in front of it and reports readings over USB several times a second.

1. **[Node-RED](https://nodered.org/)** runs the Traffic Monitor logic. It keeps every radar reading, and it records every moving object from an enabled camera as an event. When the camera has a radar and the object entered any zone, it:

   - works out the direction of travel from the order in which the object entered `zone_near` and `zone_far`, or from the radar if the zones don't give one;
   - attaches a speed: the median radar reading in that direction while the object was in view, with a two-second margin on each side.

   Without a radar, events have no direction or speed. [Direction and speed](https://docs.trafficmonitor.ai/dev/data-and-payloads/events-payload/#direction-and-speed) has the exact rules.

   The dashboards and the daily counts then filter the events by zone: they count objects that passed through `zone_capture`, and they use only objects that passed through `zone_radar` for speed statistics. 5. **The database**, one SQLite file on the device, stores the events, the radar readings, air quality readings from the optional sensor, and the device's deployment history. The dashboards read from it, and you can download it.

[First-time setup](https://docs.trafficmonitor.ai/dev/setup-guide/index.md) walks through turning on detection and adjusting the four zones. [Events](https://docs.trafficmonitor.ai/dev/data-and-payloads/events-payload/index.md) lists every column an event has.

## What you see

The device serves a home page at `http://<device>/` that links to the dashboards, Frigate, and the system tools. [Home page and apps](https://docs.trafficmonitor.ai/dev/use/home-page/index.md) describes each one.

## What stays on the device

The database holds labels, times, speeds, and zones, not pictures. Frigate keeps cropped snapshots and short clips for about an hour so you can check what was detected, and nothing is sent anywhere unless you turn on an integration. [Data and privacy](https://docs.trafficmonitor.ai/dev/data-and-payloads/data-overview/index.md) has the details.

## Settings

Three files on the device control the behavior described above. You edit them over SSH.

| File                    | What it controls                                                                                                                                                                                                                                                                                          |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Frigate's `config.yml`  | Camera, detection, zones, object filters, and recording. Most changes are made in Frigate's own web UI. See [Tune object detection](https://docs.trafficmonitor.ai/dev/configuration/frigate-config/index.md).                                                                                            |
| Node-RED's `config.yml` | Deployment location, which sensors are on, which radar pairs with which camera, and the ThingsBoard connection. Times shown on the dashboards use the device's time zone, which the installer sets. See [config.yml settings](https://docs.trafficmonitor.ai/dev/configuration/node-red-config/index.md). |
| `node-red-tm.env`       | Radar serial ports, the database path, and the MQTT broker. See [node-red-tm.env settings](https://docs.trafficmonitor.ai/dev/configuration/environment/index.md).                                                                                                                                        |
