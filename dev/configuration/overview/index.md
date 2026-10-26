# Config Overview

Traffic Monitor settings and configuration are stored and controlled locally, on each device.

The following configuration files control the most common operations:

- [Frigate Config](https://docs.trafficmonitor.ai/dev/configuration/frigate-config/index.md) - to enable and configure object detection
- Node-RED [Environment File](https://docs.trafficmonitor.ai/dev/configuration/node-red-config/#environment-file) - to configure hardware sensors
- Node-RED [Config File](https://docs.trafficmonitor.ai/dev/configuration/node-red-config/#config-file) - to enable and configure sensors and ThingsBoard IoT hub connection

It is recommended to start with a minimal configuration and add to it as needed.

## Backup and Restore

Backup and restore are built into the Node-RED Device Dashboard but require a connection to a [ThingsBoard](https://thingsboard.io/) IoT (Internet of Things) hub server.
