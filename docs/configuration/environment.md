---
description: The variables in node-red-tm.env: radar serial ports, database path, MQTT broker, and the values the installer fills in.
---

# node-red-tm.env settings

`/opt/traffic-monitor/node-red-tm/node-red-tm.env` holds the environment the Node-RED container starts with. The installer writes it from [this template](https://github.com/glossyio/traffic-monitor/blob/main/container/node-red-tm/node-red-tm.env.j2) on the first install and leaves it alone afterwards, unless you run the installer with `-f`. Most devices never need it edited.

After editing it, restart the service:

```bash
sudo systemctl restart node-red-tm.service
```

| Variable | Default | Meaning |
|---|---|---|
| `TM_VERSION` | the installed release | The Traffic Monitor version, shown on the dashboards and sent with telemetry. The installer sets it; don't edit it. |
| `TM_RPI_SN` | the Raspberry Pi's serial number | Identifies the device in ThingsBoard, and is the `deviceName` in each [deployment](../data-and-payloads/data-overview.md#deployment) record. Set by the installer. |
| `TM_HOSTNAME` | the device's hostname at install | Prefix for the file names of [data exports](../ui/database.md). Set by the installer. |
| `NODE_RED_CREDENTIAL_SECRET` | `myNodeRED1234` | Encrypts the credentials saved in the Node-RED editor. Leave it as it is: every installer run copies in the repository's credentials file, which is encrypted with this default, so a changed value leaves Node-RED unable to read it. |
| `TM_DATABASE_PATH_TMDB` | `/db/tmdb.sqlite` | The database, as seen inside the container. On the device it's `/opt/traffic-monitor/node-red-tm/db/tmdb.sqlite`. Leave it; schema migrations and downloads expect this path. |
| `TM_MQTT_BROKER_HOST` | `localhost` | The MQTT broker that Node-RED hosts. Frigate and the air quality sensor publish to it. See [MQTT and ThingsBoard](../data-and-payloads/integrations.md). |
| `TM_MQTT_BROKER_PORT` | `1883` | The broker's port. |
| `TM_MQTT_BROKER_USERNAME` | empty | Present in the file but not used. The broker doesn't ask for a username. |
| `TM_MQTT_BROKER_PASSWORD` | empty | Present in the file but not used. |
| `TM_RADAR_SERIAL_PORT_00` to `TM_RADAR_SERIAL_PORT_03` | `/dev/ttyACM0` to `/dev/ttyACM3` | The serial port of each radar. The variable's name is the radar's name in [config.yml](node-red-config.md#sensorsradars). The installer passes only the ports that exist at install time into the container, so after plugging in a radar rerun `bash traffic-monitor/script/tmsetup.sh -t node-red-tm`. |
