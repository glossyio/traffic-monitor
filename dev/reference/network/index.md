# Network ports

Other computers reach the Traffic Monitor's apps through the [home page](https://docs.trafficmonitor.ai/dev/use/home-page/index.md) on port 80. The apps themselves, and the control app on port 8090, listen only on the device itself (loopback). The ports in the table below are the ones other computers can reach.

| Port       | Used for                                                                                                                                     |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 22         | SSH                                                                                                                                          |
| 80         | The [control app](https://docs.trafficmonitor.ai/dev/use/control-app/index.md) and every app behind its login                                |
| 1883       | MQTT, only when the broker has a login. See [MQTT and ThingsBoard](https://docs.trafficmonitor.ai/dev/data-and-payloads/integrations/#mqtt). |
| 5353 (UDP) | `<hostname>.local` names (mDNS)                                                                                                              |
| 8554       | The camera stream (RTSP), with a username and password                                                                                       |
| 9090       | Cockpit, with your Raspberry Pi login only. Use it if the home page doesn't load or the control app isn't answering.                         |

## The hotspot

When the device's Wi-Fi isn't on a network it knows, it runs a [hotspot](https://docs.trafficmonitor.ai/dev/use/wifi-hotspot/index.md) on the built-in radio (`wlan0`). The control app's [Network page](https://docs.trafficmonitor.ai/dev/use/wifi-hotspot/#the-network-page) shows the device's own addresses.

|         |                                                                                                                                                                                                                             |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Address | The device is `10.42.0.1`, on the network `10.42.0.0/24`. The address is fixed.                                                                                                                                             |
| DHCP    | The device gives each phone an address in that network.                                                                                                                                                                     |
| DNS     | The device answers every name with its own address, so a phone's connection test lands on the device and opens the control app's sign-in window.                                                                            |
| Ports   | The same as on your network, in the table above.                                                                                                                                                                            |
| Reach   | A phone on the hotspot reaches only the device. A firewall rule drops anything that would pass from the hotspot to another network, or back, so the hotspot has no internet and doesn't open your wired network to a phone. |

A request that reaches the device on the hotspot's address with any other name, such as the one a phone's connection test uses, gets a redirect to `http://10.42.0.1/`. A request for `10.42.0.1` or for the device's own name is answered as usual.

Whenever the device has a network, NetworkManager asks `connectivity-check.ubuntu.com` every 5 minutes whether the internet is reachable. The Status page's Internet check shows the answer. When an administrator [tests a Wi-Fi network](https://docs.trafficmonitor.ai/dev/use/wifi-hotspot/#put-the-unit-on-a-wi-fi-network) from the Network page, the device asks that network's DNS server for the address of `connectivity-check.ubuntu.com` (up to three times, a second apart) and makes one request to it through that network, to report whether the internet is reachable there.

## Camera stream login

The camera stream on port 8554 needs the username `frigate` and a password generated on the device at install. To play the stream in another program, such as VLC, read the password on the device:

```
sudo cat /etc/traffic-monitor/secrets/go2rtc_rtsp_password
```

Then open `rtsp://frigate:<password>@<device>:8554/picam_h265_detect`.
