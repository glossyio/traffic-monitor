---
description: Restart services, read logs, and find the files on a Traffic Monitor, in the browser with Cockpit or over SSH.
---

# System administration

## Cockpit

Open `http://<device>/system/` and log in with your Raspberry Pi user account. [Cockpit](https://cockpit-project.org/) shows the services and their logs, the Podman containers, system updates, and a terminal, so most administration needs no SSH client.

## Services

The Traffic Monitor runs as systemd services. The containers run inside one Podman pod.

| Service | What it runs |
|---|---|
| `traffic-monitor.service` | The pod that holds the containers below |
| `frigate.service` | Frigate, object detection |
| `node-red-tm.service` | Node-RED: the Traffic Monitor logic, dashboards, database, and MQTT broker |
| `revproxy.service` | nginx, which serves the home page and the `/dashboard/`, `/frigate/`, and other paths |
| `plate-recognizer.service` | The optional [Plate Recognizer](../add-ons/plate-recognizer.md) add-on |
| `go2rtc_server.service` | go2rtc, which reads the Pi camera and streams it to Frigate. It runs on the host, not in the pod. |

Over SSH:

```bash
sudo systemctl status traffic-monitor.service   # or any service above
sudo systemctl restart node-red-tm.service      # after editing config.yml
sudo journalctl -u frigate.service -f           # follow a service's log
sudo podman ps                                  # running containers
```

## When to restart what

| After you | Do this |
|---|---|
| Edit Node-RED's `config.yml` or `node-red-tm.env` | `sudo systemctl restart node-red-tm.service`. The config is read only when the flows start. |
| Change Frigate's config in its UI | Choose **Save & Restart** in Frigate's config editor, or restart `frigate.service`. |
| Plug in a radar or an AI accelerator | Rerun the installer for that component so the device is passed to the container: `bash script/tmsetup.sh -t node-red-tm` for a radar, `-t detectors -t frigate` for an accelerator. See [Installer options](../reference/tmsetup.md). |
| Move the device to a new site | Follow [First-time setup](../setup-guide.md) again: adjust the zones and update the location. |

## Where things are

Everything the installer manages lives under `/opt/traffic-monitor/`.

| Path | Contents |
|---|---|
| `node-red-tm/config/config.yml` | Traffic Monitor settings. See [config.yml settings](../configuration/node-red-config.md). |
| `node-red-tm/node-red-tm.env` | Radar ports, database path, MQTT broker. See [node-red-tm.env settings](../configuration/environment.md). |
| `node-red-tm/db/tmdb.sqlite` | The database. `db/backup/` holds the copy saved before the most recent schema change. |
| `frigate/config/config.yml` | Frigate's settings, including zones and masks. |
| `frigate/storage/` | Frigate's snapshots and recordings. |
| `plate-recognizer/plate-recognizer.env` | Plate Recognizer credentials, if the add-on is installed. |
