---
description: The network ports a Traffic Monitor opens, and the login the camera stream needs.
---

# Network ports

Other computers reach the Traffic Monitor's apps through the [home page](../use/home-page.md) on port 80. The apps themselves listen only on the device itself (loopback), and so does the control app, on port 8090.

| Port | Used for |
|---|---|
| 22 | SSH |
| 80 | The [control app](../use/control-app.md) and every app behind its login |
| 1883 | MQTT, only when the broker has a login. See [MQTT and ThingsBoard](../data-and-payloads/integrations.md#mqtt). |
| 5353 (UDP) | `<hostname>.local` names (mDNS) |
| 8554 | The camera stream (RTSP), with a username and password |
| 9090 | Cockpit, with your Raspberry Pi login only. Use it if the home page doesn't load or the control app isn't answering. |

When the device hosts its own Wi-Fi network, it also answers DHCP and DNS on it.

## Camera stream login

The camera stream on port 8554 needs the username `frigate` and a password generated on the device at install. To play the stream in another program, such as VLC, read the password on the device:

```bash
sudo cat /etc/traffic-monitor/secrets/go2rtc_rtsp_password
```

Then open `rtsp://frigate:<password>@<device>:8554/picam_h265_detect`.
