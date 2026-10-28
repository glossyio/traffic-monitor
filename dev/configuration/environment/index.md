______________________________________________________________________

## description: The variables in node-red-tm.env: radar serial ports, database path, MQTT broker, and the values the installer fills in.

# node-red-tm.env settings

`/opt/traffic-monitor/node-red-tm/node-red-tm.env` holds the environment the Node-RED container starts with. The installer writes it from [this template](https://github.com/glossyio/traffic-monitor/blob/main/container/node-red-tm/node-red-tm.env.j2) on the first install and leaves it alone afterwards, unless you run the installer with `-f`. Most devices never need it edited.

After editing it, restart the service:

```
sudo systemctl restart node-red-tm.service
```

After changing the MQTT broker login

A restart or reboot isn't enough after you change `TM_MQTT_BROKER_USERNAME` or `TM_MQTT_BROKER_PASSWORD`. Run the installer instead, so Frigate gets the same login and port 1883 opens or closes to match:

```
bash traffic-monitor/script/tmsetup.sh -t node-red-tm
```

Otherwise the broker refuses Frigate's connection, and no events are recorded.

| Variable                                               | Default                          | Meaning                                                                                                                                                                                                                                                                                                                                                                           |
| ------------------------------------------------------ | -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TM_VERSION`                                           | the installed release            | The Traffic Monitor version, shown on the dashboards and sent with telemetry. The installer sets it; don't edit it.                                                                                                                                                                                                                                                               |
| `TM_RPI_SN`                                            | the Raspberry Pi's serial number | Identifies the device in ThingsBoard, and fills `deviceName` in [deployment](https://docs.trafficmonitor.ai/dev/data-and-payloads/data-overview/#deployment) records. Set by the installer.                                                                                                                                                                                       |
| `TM_HOSTNAME`                                          | the device's hostname at install | Prefix for the file names of [data exports](https://docs.trafficmonitor.ai/dev/ui/database/index.md). Set by the installer.                                                                                                                                                                                                                                                       |
| `NODE_RED_CREDENTIAL_SECRET`                           | `myNodeRED1234`                  | Encrypts the credentials saved in the Node-RED editor. Leave it as it is: every installer run copies in the repository's credentials file, which is encrypted with this default, so a changed value leaves Node-RED unable to read it.                                                                                                                                            |
| `TM_DATABASE_PATH_TMDB`                                | `/db/tmdb.sqlite`                | The database, as seen inside the container. On the device it's `/opt/traffic-monitor/node-red-tm/db/tmdb.sqlite`. Leave it; schema migrations and downloads expect this path.                                                                                                                                                                                                     |
| `TM_MQTT_BROKER_HOST`                                  | `localhost`                      | The MQTT broker that Node-RED hosts. Frigate and the air quality sensor publish to it. See [MQTT and ThingsBoard](https://docs.trafficmonitor.ai/dev/data-and-payloads/integrations/index.md).                                                                                                                                                                                    |
| `TM_MQTT_BROKER_PORT`                                  | `1883`                           | The broker's port.                                                                                                                                                                                                                                                                                                                                                                |
| `TM_MQTT_BROKER_USERNAME`                              | empty                            | The broker's login username. When it and the password are both set, the broker requires the login from every client, and port 1883 opens to the network. Letters, digits, `.`, `_`, and `-` only, with no quotes and no comment after the value. See [Connect from other devices](https://docs.trafficmonitor.ai/dev/data-and-payloads/integrations/#connect-from-other-devices). |
| `TM_MQTT_BROKER_PASSWORD`                              | empty                            | The broker's login password, with the same rules as the username.                                                                                                                                                                                                                                                                                                                 |
| `TM_RADAR_SERIAL_PORT_00` to `TM_RADAR_SERIAL_PORT_03` | `/dev/ttyACM0` to `/dev/ttyACM3` | The serial port of each radar. The variable's name is the radar's name in [config.yml](https://docs.trafficmonitor.ai/dev/configuration/node-red-config/#sensorsradars). The installer passes only the ports that exist at install time into the container, so after plugging in a radar rerun `bash traffic-monitor/script/tmsetup.sh -t node-red-tm`.                           |
