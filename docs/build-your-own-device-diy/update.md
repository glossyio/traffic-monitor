---
description: Update the Traffic Monitor software on a device that is already installed, and what an update keeps and replaces.
---

# Update the software

An update reruns the installer from a newer copy of the repository. Your data and your settings stay; the containers are rebuilt.

## Before you update

* Read the [release notes](https://github.com/glossyio/traffic-monitor/releases). A release that needs a fresh image says so.
* Download a copy of the database from the [Data export](../ui/database.md#download-the-database) page. Open that page on Node-RED's port, as it explains, because downloads through the home page's `/dashboard/` path fail.
* Make sure the device has an internet connection. The update downloads packages and rebuilds the container images. Rebuilding Frigate's image compiles ffmpeg on the device, which can take about 20 minutes.

## Update

Connect to the device over SSH, then update the clone you installed from and rerun the installer:

```bash
cd traffic-monitor
git pull
bash script/tmsetup.sh
```

Restart when the installer asks. When the services come back, the Node-RED service applies any database schema changes before it opens the database. [Schema versions](../data-and-payloads/data-overview.md#schema-versions) describes the copy it saves first.

Open `http://<device>/` and check the [Monitoring dashboard](../ui/monitoring.md) for new counts.

To update several devices from your computer, use the remote form of the installer described in [Install the software](../software-installation.md#install-from-another-computer).

## What an update changes

An update replaces the container images, service units, Node-RED flows, and the reverse proxy configuration. It keeps your settings files, the database, and Frigate's recordings. With `-f`, it also replaces the settings files with fresh copies from the templates and keeps each old file beside the new one with a timestamp. [What `-f` replaces](../reference/tmsetup.md#what-f-replaces) lists the files.

Use `-f` when a release changes the settings files and you want the new template. Afterwards, turn Frigate's detection back on and redo your settings from the timestamped copies: location and sensors in `config.yml`, and zones in Frigate. [First-time setup](../setup-guide.md) walks through each.

Node-RED flow changes made in the editor on the device are replaced on every update. Commit them to the repository instead; see [Dev environment](../development/dev-environment.md).

## Update one component

Each installer tag reruns one component. For example, after plugging in a radar:

```bash
bash script/tmsetup.sh -t node-red-tm
```

[Installer options](../reference/tmsetup.md) lists the tags and flags.
