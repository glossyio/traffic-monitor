---
description: The device's home page and the apps it links to: dashboards, Frigate, Node-RED, camera feeds, and Cockpit.
---

# Home page and apps

Open `http://<device>/` in a browser on the same network. `<device>` is the hostname you set when you imaged the card, followed by `.local` (for example `http://tm-01.local/`), or the device's IP address.

The home page is the device's [control app](control-app.md). A new device first asks you to claim it with its setup code; after that, the home page and every app ask you to log in. The home page shows the device's name, software version, serial number, and time, and links to the apps your account can open. Its menu has your **Account**, the **Users** page for administrators, and **Log out**.

| Link | Path | What it is | Who can open it |
|---|---|---|---|
| Dashboard | `/dashboard/` | The Traffic Monitor dashboards: [Monitoring](../ui/monitoring.md), [Movements](../ui/movements.md), and [Data export](../ui/database.md), which opens first. Switch pages in the sidebar. | Any user. The Data export downloads need an administrator. |
| Frigate | `/frigate/` | Object detection: live view, detections with snapshots and clips, zones, masks, and the Frigate settings. See [Tune object detection](../configuration/frigate-config.md). | Any user. Frigate's settings need an administrator. |
| Legacy Dashboard | `/ui/` | The older dashboard, with the same counts and speed statistics as Monitoring. It's the only dashboard that shows [air quality](../add-ons/air-quality.md) readings, and the Monitoring dashboard's counts follow its camera and radar selection. Its System Settings tab shows the device's name, time zone, and software versions, and holds the ThingsBoard Backup & Restore section. | Any user |
| Node-RED editor | `/nr/` | The flow editor, for developers. See [Dev environment](../development/dev-environment.md). | Administrators |
| Camera feeds | `/feeds/` | The camera streams the Pi camera produces, for checking that the camera works. It's for watching only: go2rtc's settings, stream editor, and log pages aren't available here. | Administrators |
| Cockpit | `/system/` | Services, logs, containers, and a terminal. See [System administration](system-admin.md). | Administrators, who then log in with the Raspberry Pi user account |

??? note "Finding the device's address"

    * If you set a hostname in Raspberry Pi Imager, `http://<hostname>.local/` works from most computers and phones on the same network.
    * Otherwise, look the device up in your router's list of connected devices, or see [Find the IP address of your Raspberry Pi](https://www.raspberrypi.com/documentation/computers/remote-access.html#ip-address).
    * A pre-built unit may host its own Wi-Fi network. Connect to it and use the hostname or the gateway address. Your provider's instructions take precedence.

??? note "If the home page doesn't load"

    The apps accept connections only from the device, so they have no address of their own on your network. If the apps show a page saying the control app isn't answering, restart it as described in [If the control app is down](control-app.md#if-the-control-app-is-down). If nothing loads, open Cockpit at `http://<device>:9090`, log in with your Raspberry Pi user account, and check the services as described in [System administration](system-admin.md). [Network ports](../reference/network.md) lists what the device opens.
