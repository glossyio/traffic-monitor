# Update the software

An update reruns the installer from a newer copy of the repository. Your data and your settings stay; the containers are rebuilt.

## Before you update

- Read the [release notes](https://github.com/glossyio/traffic-monitor/releases). A release that needs a fresh image says so.
- Download a copy of the database from the [Data export](https://docs.trafficmonitor.ai/dev/ui/database/#download-the-database) page.
- Make sure the device has an internet connection. The update downloads packages and rebuilds the container images. Rebuilding Frigate's image compiles ffmpeg on the device, which can take about 20 minutes.

## Update

Connect to the device over SSH, then update the clone you installed from and rerun the whole installer:

```
cd traffic-monitor
git pull
bash script/tmsetup.sh
```

Run the whole installer rather than a single tag, because one version's changes can span several components.

Restart when the installer asks. When the services come back, the Node-RED service applies any database schema changes before it opens the database. [Schema versions](https://docs.trafficmonitor.ai/dev/data-and-payloads/data-overview/#schema-versions) describes the copy it saves first.

The installer printed `tm-control migrate: WARNING`

A camera's input `path` in Frigate's configuration reads a stream on port 8554 without a login. If that path points at this device, for example by its IP address, add `{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@` before the host in Frigate's configuration editor. The [higher-resolution stream](https://docs.trafficmonitor.ai/dev/configuration/frigate-config/#higher-resolution-stream) section shows a complete path. If it points at another device, leave it as it is. To find the warning later:

```
grep 'tm-control migrate: WARNING' ~/tmsetup-*.log
```

A Frigate configuration from a backup may lack the camera stream login. After you restore one, run `bash script/tmsetup.sh -t frigate` to add it.

Port 1883 accepts MQTT connections only from the device itself unless the broker has a login. If a display board, Home Assistant, or another device on your network reads MQTT from this device, give the broker a login and give it to that device; see [Connect from other devices](https://docs.trafficmonitor.ai/dev/data-and-payloads/integrations/#connect-from-other-devices).

Open `http://<device>/` and check the [Monitoring dashboard](https://docs.trafficmonitor.ai/dev/ui/monitoring/index.md) for new counts.

To update several devices from your computer, use the remote form of the installer described in [Install the software](https://docs.trafficmonitor.ai/dev/software-installation/#install-from-another-computer).

## What an update changes

An update replaces the container images, service units, Node-RED flows, and the reverse proxy configuration. It keeps your settings files, the database, and Frigate's recordings. With `-f`, it also replaces the settings files with fresh copies from the templates and keeps each old file beside the new one with a timestamp. [What `-f` replaces](https://docs.trafficmonitor.ai/dev/reference/tmsetup/#what-f-replaces) lists the files.

Use `-f` when a release changes the settings files and you want the new template. Afterwards, turn Frigate's detection back on and redo your settings from the timestamped copies: location and sensors in `config.yml`, and zones in Frigate. [First-time setup](https://docs.trafficmonitor.ai/dev/setup-guide/index.md) walks through each.

Node-RED flow changes made in the editor on the device are replaced on every update. Commit them to the repository instead; see [Dev environment](https://docs.trafficmonitor.ai/dev/development/dev-environment/index.md).

## Update one component

Each installer tag reruns one component, plus anything that has to change with it; see [Tags](https://docs.trafficmonitor.ai/dev/reference/tmsetup/#tags). For example, after plugging in a radar:

```
bash script/tmsetup.sh -t node-red-tm
```

[Installer options](https://docs.trafficmonitor.ai/dev/reference/tmsetup/index.md) lists the tags and flags.
