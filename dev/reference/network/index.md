# Network ports

Other computers reach the Traffic Monitor's apps through the [home page](https://docs.trafficmonitor.ai/dev/use/home-page/index.md) on port 80. The apps themselves accept connections only from the device.

| Port       | Used for                                                                                                                                     |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 22         | SSH                                                                                                                                          |
| 80         | The home page and every app it links to                                                                                                      |
| 1883       | MQTT, only when the broker has a login. See [MQTT and ThingsBoard](https://docs.trafficmonitor.ai/dev/data-and-payloads/integrations/#mqtt). |
| 5353 (UDP) | `<hostname>.local` names (mDNS)                                                                                                              |
| 8554       | The camera stream (RTSP), with a username and password                                                                                       |
| 9090       | Cockpit, with your Raspberry Pi login. Use it if the home page doesn't load.                                                                 |

When the device hosts its own Wi-Fi network, it also answers DHCP and DNS on it.

## Camera stream login

The camera stream on port 8554 needs the username `frigate` and a password generated on the device at install. To play the stream in another program, such as VLC, read the password on the device:

```
sudo cat /etc/traffic-monitor/secrets/go2rtc_rtsp_password
```

Then open `rtsp://frigate:<password>@<device>:8554/picam_h265_detect`.
