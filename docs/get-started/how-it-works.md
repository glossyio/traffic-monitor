---
description: How the camera, radar, Frigate, and Node-RED turn passing traffic into counts, speeds, and a database on the device.
---

# How it works

A Traffic Monitor is a Raspberry Pi 5 running a few cooperating programs. Everything happens on the device, so it works without an internet connection once it's installed.

## From the street to the database

1. **The camera** streams H.265 video at 1536×864 and 10 frames per second to Frigate.
2. **[Frigate](https://frigate.video/)** finds and tracks objects in the video, using the AI accelerator if the device has one and the CPU if not. It records which **zones** each object passed through. When an object leaves the frame, Frigate publishes an event on the device's MQTT broker.
3. **The radar** (optional) measures the speed and direction of whatever moves in front of it and reports readings over USB several times a second.
4. **[Node-RED](https://nodered.org/)** runs the Traffic Monitor logic. It keeps every radar reading, and for each Frigate event it:
    * counts the object if it passed through `zone_capture`;
    * works out the direction of travel from the order in which the object entered `zone_near` and `zone_far`;
    * attaches a speed when the object passed through `zone_radar`: the median radar reading in that direction while the object was in view, with a two-second margin on each side.
5. **The database**, one SQLite file on the device, stores the events, the radar readings, air quality readings from the optional sensor, and the device's deployment history. The dashboards read from it, and you can download it.

[First-time setup](../setup-guide.md) walks through turning on detection and adjusting the four zones. [Events](../data-and-payloads/events-payload.md) lists every column an event has.

## What you see

The device serves a home page at `http://<device>/` that links to the dashboards, Frigate, and the system tools. [Home page and apps](../use/home-page.md) describes each one.

## What stays on the device

The database holds labels, times, speeds, and zones, not pictures. Frigate keeps cropped snapshots and short clips for about an hour so you can check what was detected, and nothing is sent anywhere unless you turn on an integration. [Data and privacy](../data-and-payloads/data-overview.md) has the details.

## Settings

Three files on the device control the behavior described above. You edit them over SSH.

| File | What it controls |
|---|---|
| Frigate's `config.yml` | Camera, detection, zones, object filters, and recording. Most changes are made in Frigate's own web UI. See [Tune object detection](../configuration/frigate-config.md). |
| Node-RED's `config.yml` | Deployment location, which sensors are on, which radar pairs with which camera, time zone, and the ThingsBoard connection. See [config.yml settings](../configuration/node-red-config.md). |
| `node-red-tm.env` | Radar serial ports, the database path, and the MQTT broker. See [node-red-tm.env settings](../configuration/environment.md). |
