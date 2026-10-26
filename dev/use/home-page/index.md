______________________________________________________________________

## description: The device's home page and the apps it links to: dashboards, Frigate, Node-RED, camera feeds, and Cockpit.

# Home page and apps

Open `http://<device>/` in a browser on the same network. `<device>` is the hostname you set when you imaged the card, followed by `.local` (for example `http://tm-01.local/`), or the device's IP address.

The home page links to every app on the device.

| Link                                  | Path          | What it is                                                                                                                                                                                                                                                                                                                                                                                                                    | Login                          |
| ------------------------------------- | ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| Dashboard                             | `/dashboard/` | The Traffic Monitor dashboards: [Monitoring](https://docs.trafficmonitor.ai/dev/ui/monitoring/index.md), [Movements](https://docs.trafficmonitor.ai/dev/ui/movements/index.md), and [Data export](https://docs.trafficmonitor.ai/dev/ui/database/index.md), which opens first. Switch pages in the sidebar.                                                                                                                   | None                           |
| Frigate                               | `/frigate/`   | Object detection: live view, detections with snapshots and clips, zones, masks, and the Frigate settings. See [Tune object detection](https://docs.trafficmonitor.ai/dev/configuration/frigate-config/index.md).                                                                                                                                                                                                              | None                           |
| Legacy Dashboard                      | `/ui/`        | The older dashboard, with the same counts and speed statistics as Monitoring. It's the only dashboard that shows [air quality](https://docs.trafficmonitor.ai/dev/add-ons/air-quality/index.md) readings, and the Monitoring dashboard's counts follow its camera and radar selection. Its System Settings tab shows the device's name, time zone, and software versions, and holds the ThingsBoard Backup & Restore section. | None                           |
| Node-RED admin console                | `/nr/`        | The flow editor, for developers. See [Dev environment](https://docs.trafficmonitor.ai/dev/development/dev-environment/index.md).                                                                                                                                                                                                                                                                                              | `admin` / `password`           |
| Go2RTC Feeds                          | `/feeds/`     | The camera streams the Pi camera produces, for checking that the camera works.                                                                                                                                                                                                                                                                                                                                                | None                           |
| Cockpit-Project system administration | `/system/`    | Services, logs, containers, and a terminal. See [System administration](https://docs.trafficmonitor.ai/dev/use/system-admin/index.md).                                                                                                                                                                                                                                                                                        | Your Raspberry Pi user account |

Finding the device's address

- If you set a hostname in Raspberry Pi Imager, `http://<hostname>.local/` works from most computers and phones on the same network.
- Otherwise, look the device up in your router's list of connected devices, or see [Find the IP address of your Raspberry Pi](https://www.raspberrypi.com/documentation/computers/remote-access.html#ip-address).
- A pre-built unit may host its own Wi-Fi network. Connect to it and use the hostname or the gateway address. Your provider's instructions take precedence.

Direct ports

Each app also answers on its own port, which is useful when the home page is down. Node-RED and the dashboards are on `1880` (the dashboards at `:1880/dashboard`, the legacy dashboard at `:1880/ui`), Frigate on `5000`, the camera feeds on `1984`, Cockpit on `9090`, and the MQTT broker on `1883`.
