---
description: Restart services, read logs, and find the files on a Traffic Monitor, in the browser with Cockpit or over SSH.
---

# System administration

## Cockpit

Log in to the device as the administrator, open **Cockpit** from the home page, and log in again with your Raspberry Pi user account. Cockpit also answers on `http://<device>:9090` with only the Raspberry Pi login, which works when the [control app](control-app.md) doesn't. [Cockpit](https://cockpit-project.org/) shows the services and their logs, the Podman containers, system updates, and a terminal, so most administration needs no SSH client.

## Services

The Traffic Monitor runs as systemd services. The app containers run inside one Podman pod. nginx and the control app run on the host, outside the pod, so the home page and the login stay up when the pod is down.

| Service | What it runs |
|---|---|
| `traffic-monitor.service` | The pod that holds Frigate, Node-RED, and Plate Recognizer if installed |
| `frigate.service` | Frigate, object detection |
| `node-red-tm.service` | Node-RED: the Traffic Monitor logic, dashboards, database, and MQTT broker |
| `tm-control.service` | The [control app](control-app.md): the home page's data, the login, and the device's accounts. nginx asks it to check the login for every app. |
| `revproxy.service` | nginx, which serves the home page and the `/dashboard/`, `/frigate/`, and other paths |
| `plate-recognizer.service` | The optional [Plate Recognizer](../add-ons/plate-recognizer.md) add-on |
| `go2rtc_server.service` | go2rtc, which reads the Pi camera and streams it to Frigate. It runs on the host, not in the pod. |

Over SSH:

```bash
sudo systemctl status traffic-monitor.service   # or any service above
sudo systemctl restart node-red-tm.service      # after editing node-red-tm.env
sudo journalctl -u frigate.service -f           # follow a service's log
sudo podman ps                                  # running containers
```

## When to restart what

| After you | Do this |
|---|---|
| Edit Node-RED's `config.yml` | Nothing. The Traffic Monitor reads the file again when you save it. If the change doesn't show, check the file for a YAML error. |
| Edit `node-red-tm.env` | `sudo systemctl restart node-red-tm.service`. The container reads the file only when it starts. |
| Change the MQTT broker login in `node-red-tm.env` | `bash traffic-monitor/script/tmsetup.sh -t node-red-tm`. A restart isn't enough; [node-red-tm.env settings](../configuration/environment.md) explains why. |
| Change Frigate's config in its UI | Choose **Save & Restart** in Frigate's config editor, or restart `frigate.service`. |
| Plug in a radar | Rerun the installer for Node-RED so the radar is passed to the container: `bash traffic-monitor/script/tmsetup.sh -t node-red-tm`. |
| Add or change an AI accelerator | Rerun the installer with `-t detectors -t frigate`, then update Frigate's detector settings. See [Add an accelerator later](../reference/tmsetup.md#add-an-accelerator-later). |
| See a page saying the control app isn't answering | `sudo systemctl restart tm-control.service`, or restart it in Cockpit on port 9090. See [If the control app is down](control-app.md#if-the-control-app-is-down). |
| Move the device to a new site | Follow [First-time setup](../setup-guide.md) again: adjust the zones and update the location. |

## Where things are

The settings and data live under `/opt/traffic-monitor/`.

| Path | Contents |
|---|---|
| `node-red-tm/config/config.yml` | Traffic Monitor settings. See [config.yml settings](../configuration/node-red-config.md). |
| `node-red-tm/node-red-tm.env` | Radar ports, database path, MQTT broker. See [node-red-tm.env settings](../configuration/environment.md). |
| `node-red-tm/db/tmdb.sqlite` | The database. `db/backup/` holds the copy saved before the most recent schema change. |
| `frigate/config/config.yml` | Frigate's settings, including zones and masks. |
| `frigate/storage/` | Frigate's snapshots and recordings. |
| `plate-recognizer/plate-recognizer.env` | Plate Recognizer credentials, if the add-on is installed. |

The control app and the installer keep a few files elsewhere. Read them, but don't edit them.

| Path | Contents |
|---|---|
| `/var/lib/tm-control/state.sqlite` | The control app's accounts, the license acceptance, and a log of account changes. Only the control app writes it. |
| `/etc/traffic-monitor/manifest.json` | What the installer installed and found, which the control app reads |
| `/etc/traffic-monitor/secrets/` | Passwords and keys the installer generated on the device |
| `/etc/traffic-monitor/setup-code` | The setup code, until the device is claimed |
