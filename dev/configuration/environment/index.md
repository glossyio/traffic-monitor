______________________________________________________________________

## description: The variables in node-red-tm.env and frigate.env: radar serial ports, database path, MQTT broker, the Frigate+ key, and the values the installer fills in.

# Env file settings

Two env files hold the environment that the Node-RED and Frigate containers start with. The installer writes each from its template on the first install and leaves it alone afterwards, unless you run the installer with `-f`. Most devices never need either edited.

## node-red-tm.env

`/opt/traffic-monitor/node-red-tm/node-red-tm.env` is written from [this template](https://github.com/glossyio/traffic-monitor/blob/main/container/node-red-tm/node-red-tm.env.j2).

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
| `TM_NR_TOKEN_KEY`                                      | generated on the device          | Lets the Node-RED editor check that the device's [login](https://docs.trafficmonitor.ai/dev/use/control-app/index.md) let you in. The installer sets it on every run; leave it. Without it, the editor refuses everyone.                                                                                                                                                          |
| `TM_THINGSBOARD_ACCESS_TOKEN`                          | the token you set, or empty      | The device's access token for the [ThingsBoard upload](https://docs.trafficmonitor.ai/dev/data-and-payloads/integrations/#thingsboard). The installer fills it from the device's secrets on every run; change it on the [Device page](https://docs.trafficmonitor.ai/dev/use/device-health/#tokens-and-keys), not here. Empty keeps the upload off.                               |
| `TM_PLATE_RECOGNIZER_TOKEN`                            | the token you set, or empty      | The API token for the [Plate Recognizer](https://docs.trafficmonitor.ai/dev/add-ons/plate-recognizer/index.md) add-on. Filled and changed the same way. Empty keeps plate reads off.                                                                                                                                                                                              |
| `TM_INTERNAL_TOKEN`                                    | generated on the device          | Lets the control app read Node-RED's state for the [Status page](https://docs.trafficmonitor.ai/dev/use/device-health/#the-status-page). The installer sets it on every run; leave it. Without it, the Status page can't read Node-RED's state.                                                                                                                                   |
| `TM_DATABASE_PATH_TMDB`                                | `/db/tmdb.sqlite`                | The database, as seen inside the container. On the device it's `/opt/traffic-monitor/node-red-tm/db/tmdb.sqlite`. Leave it; schema migrations and downloads expect this path.                                                                                                                                                                                                     |
| `TM_MQTT_BROKER_HOST`                                  | `localhost`                      | The MQTT broker that Node-RED hosts. Frigate and the air quality sensor publish to it. See [MQTT and ThingsBoard](https://docs.trafficmonitor.ai/dev/data-and-payloads/integrations/index.md).                                                                                                                                                                                    |
| `TM_MQTT_BROKER_PORT`                                  | `1883`                           | The broker's port.                                                                                                                                                                                                                                                                                                                                                                |
| `TM_MQTT_BROKER_USERNAME`                              | empty                            | The broker's login username. When it and the password are both set, the broker requires the login from every client, and port 1883 opens to the network. Letters, digits, `.`, `_`, and `-` only, with no quotes and no comment after the value. See [Connect from other devices](https://docs.trafficmonitor.ai/dev/data-and-payloads/integrations/#connect-from-other-devices). |
| `TM_MQTT_BROKER_PASSWORD`                              | empty                            | The broker's login password, with the same rules as the username.                                                                                                                                                                                                                                                                                                                 |
| `TM_RADAR_SERIAL_PORT_00` to `TM_RADAR_SERIAL_PORT_03` | `/dev/ttyACM0` to `/dev/ttyACM3` | The serial port of each radar. The variable's name is the radar's name in [config.yml](https://docs.trafficmonitor.ai/dev/configuration/node-red-config/#sensorsradars). The installer passes only the ports that exist at install time into the container, so after plugging in a radar rerun `bash traffic-monitor/script/tmsetup.sh -t node-red-tm`.                           |

## frigate.env

`/opt/traffic-monitor/frigate/frigate.env` is written from [this template](https://github.com/glossyio/traffic-monitor/blob/main/container/frigate/frigate.env.j2). After editing it, restart Frigate with `sudo systemctl restart frigate.service`.

| Variable                | Default                   | Meaning                                                                                                                                                                                                                                                                                                                                                              |
| ----------------------- | ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `FRIGATE_RTSP_PASSWORD` | `password`                | A password for cameras of your own: Frigate fills in `{FRIGATE_RTSP_PASSWORD}` in a camera's input path. The Traffic Monitor's own camera doesn't use it. The installer leaves it as you set it, unless you run it with `-f`.                                                                                                                                        |
| `PLUS_API_KEY`          | the key you set, or empty | The [Frigate+](https://docs.trafficmonitor.ai/dev/configuration/frigate-config/#better-models) API key. The installer fills it from the device's secrets on every run; change it on the [Detection page](https://docs.trafficmonitor.ai/dev/use/detection/#frigate-plus), not here. Empty means no key: Frigate can't submit snapshots or download a Frigate+ model. |

The other lines are the installer's. Leave them as they are:

- `FRIGATE_GO2RTC_RTSP_USER` and `FRIGATE_GO2RTC_RTSP_PASSWORD`: the login Frigate reads the device's camera stream with.
- `FRIGATE_PROXY_AUTH_SECRET`: lets Frigate trust who the device's [login](https://docs.trafficmonitor.ai/dev/use/control-app/index.md) says you are.
- `FRIGATE_MQTT_USER` and `FRIGATE_MQTT_PASSWORD`: Frigate's login to the MQTT broker, which follows the broker login in `node-red-tm.env`.
- `FRIGATE_HOME_DIR`, `FRIGATE_VERSION`, and `FRIGATE_BASE_PATH`: where Frigate's files are, its version, and the `/frigate/` path it's served at.
