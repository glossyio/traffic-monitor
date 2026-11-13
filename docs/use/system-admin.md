---
description: Restart services, read logs, and find the files on a Traffic Monitor, in the browser with Cockpit or over SSH.
---

# System administration

## Cockpit

[Cockpit](https://cockpit-project.org/) is the device's system console in the browser. It shows the services and their logs, the Podman containers, system updates, and the user accounts, and it has a terminal, so most administration needs no SSH client.

Open `http://<device>:9090/`, with the same name or address you use for the home page, and log in with your Raspberry Pi user account. Administrators also have a **Cockpit** tile on the home page, which opens the same address and names the account to log in with.

Cockpit has its own port and its own login. It doesn't need the home page, the [control app](control-app.md), or the apps, so it still opens when they don't. Use it when:

* the home page doesn't load, or a page says the control app isn't answering
* you want to restart a service, or read its log
* you need a terminal and have no SSH client
* you want to install system updates or change the system password

!!! info "Who can open Cockpit"

    Anyone on your network can reach Cockpit's login page. Only the Raspberry Pi user account gets past it. The control app's accounts don't work there.

## Services

The Traffic Monitor runs as systemd services. The app containers run inside one Podman pod. nginx and the control app run on the host, outside the pod, so the home page and the login stay up when the pod is down.

Start with the control app's [Status page](device-health.md#the-status-page): it shows each service's state, and when one has stopped or keeps failing, its check has a **Restart** button. Use Cockpit or SSH for the rest, such as restarting the control app itself, or a service that looks running but misbehaves.

| Service | What it runs |
|---|---|
| `traffic-monitor.service` | The pod that holds Frigate, Node-RED, and Plate Recognizer if installed |
| `frigate.service` | Frigate, object detection |
| `node-red-tm.service` | Node-RED: the Traffic Monitor logic, dashboards, database, and MQTT broker |
| `tm-control.service` | The [control app](control-app.md): the home page's data, the login, the device's accounts, and the status checks. nginx asks it to check the login for every app. |
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
| Edit Node-RED's `config.yml` | Nothing. The Traffic Monitor reads the file again when you save it. If the change doesn't show, check the file for a YAML error. For the location, use the control app's [Location page](location.md) instead; [Edit the location by hand](../configuration/node-red-config.md#edit-the-location-by-hand) says what a hand edit does. |
| Edit `node-red-tm.env` | `sudo systemctl restart node-red-tm.service`. The container reads the file only when it starts. |
| Edit `frigate.env` | `sudo systemctl restart frigate.service`. |
| Change the MQTT broker login in `node-red-tm.env` | `bash traffic-monitor/script/tmsetup.sh -t node-red-tm`. A restart isn't enough; [Env file settings](../configuration/environment.md#node-red-tmenv) explains why. |
| Change Frigate's config in its UI | Choose **Save & Restart** in Frigate's config editor, or restart `frigate.service`. |
| Plug in a radar | Rerun the installer for Node-RED so the radar is passed to the container: `bash traffic-monitor/script/tmsetup.sh -t node-red-tm`. |
| Add or change an AI accelerator | Rerun the installer with `-t detectors -t frigate`, then update Frigate's detector settings. See [Add an accelerator later](../reference/tmsetup.md#add-an-accelerator-later). |
| See a page saying the control app isn't answering | `sudo systemctl restart tm-control.service`, or restart it in Cockpit on port 9090. See [If the control app is down](control-app.md#if-the-control-app-is-down). |
| Move the device to a new site | Choose **Deploy here** on the new place on the [Location page](location.md#move-or-turn-the-device), then adjust the zones as in [First-time setup](../setup-guide.md#3-adjust-the-zones). |

## Where things are

The settings and data live under `/opt/traffic-monitor/`.

| Path | Contents |
|---|---|
| `node-red-tm/config/config.yml` | Traffic Monitor settings. See [config.yml settings](../configuration/node-red-config.md). |
| `node-red-tm/node-red-tm.env` | Radar ports, database path, MQTT broker. See [Env file settings](../configuration/environment.md#node-red-tmenv). |
| `node-red-tm/db/tmdb.sqlite` | The database. `db/backup/` holds the copy saved before the most recent schema change. After the upgrade that rounded the stored coordinates, that copy still has the exact ones, so don't share it. |
| `frigate/config/config.yml` | Frigate's settings, including zones and masks. |
| `frigate/config/model_cache/` | The models Frigate runs, such as a [Frigate+](../configuration/frigate-config.md#better-models) model's two files. The control app's [Detection page](detection.md) uploads, downloads, and deletes them. |
| `frigate/frigate.env` | Frigate's environment, including the Frigate+ API key, which comes from the device's secrets. See [Env file settings](../configuration/environment.md#frigateenv). |
| `frigate/storage/` | Frigate's snapshots and recordings. |
| `plate-recognizer/plate-recognizer.env` | Plate Recognizer settings, if the add-on is installed. Its token and license key come from the device's secrets, which you set on the [Device page](device-health.md#tokens-and-keys). |

The control app and the installer keep a few files elsewhere. Read them, but don't edit them.

| Path | Contents |
|---|---|
| `/var/lib/tm-control/state.sqlite` | The control app's accounts, the license acceptance, and a log of account changes. Only the control app writes it. |
| `/etc/traffic-monitor/manifest.json` | What the installer installed and found, which the control app reads |
| `/etc/traffic-monitor/secrets/` | Passwords and keys the installer generated on the device, and the tokens and keys you enter on the [Device page](device-health.md#tokens-and-keys) and the [Detection page](detection.md#frigate-plus) |
| `/etc/traffic-monitor/setup-code` | The setup code, until the device is claimed |
