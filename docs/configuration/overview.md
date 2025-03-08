---
description: Traffic Monitor Configuration overview
---

# Config Overview

Traffic Monitor settings and configuration are stored and controlled locally, on each device.&#x20;

The following configuration files control the most common operations:

* [frigate-config.md](frigate-config.md "mention") - to enable and configure object detection
* Node-RED [#environment-file](node-red-config.md#environment-file "mention") - to configure hardware sensors
* Node-RED [#config-file](node-red-config.md#config-file "mention") - to enable and configure sensors and ThingsBoard IoT hub connection

It is recommended to start with a minimal configuration and add to it as needed.

## Backup and Restore

Backup and restore are built into the Node-RED Device Dashboard but require a connection to a [ThingsBoard](https://thingsboard.io/) IoT (Internet of Things) hub server.
