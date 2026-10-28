---
description: Update the Traffic Monitor software on a device that is already installed, and what an update keeps and replaces.
---

# Update the software

An update reruns the installer from a newer copy of the repository. Your data and your settings stay; the containers are rebuilt.

## Before you update

* Read the [release notes](https://github.com/glossyio/traffic-monitor/releases). A release that needs a fresh image says so.
* Download a copy of the database from the [Data export](../ui/database.md#download-the-database) page.
* Make sure the device has an internet connection. The update downloads packages and rebuilds the container images. Rebuilding Frigate's image compiles ffmpeg on the device, which can take about 20 minutes.

## Update

Connect to the device over SSH, then update the clone you installed from and rerun the whole installer:

```bash
cd traffic-monitor
git pull
bash script/tmsetup.sh
```

Run the whole installer rather than a single tag, because one version's changes can span several components.

Restart when the installer asks. When the services come back, the Node-RED service applies any database schema changes before it opens the database. [Schema versions](../data-and-payloads/data-overview.md#schema-versions) describes the copy it saves first.

Every app asks for the device's login, and the Node-RED editor has no login of its own: it opens for the device's administrator. If the device has no administrator account yet, every page opens the setup page instead. Claim the device with the setup code from the end of the installer's output; until the device is claimed, `sudo cat /etc/traffic-monitor/setup-code` also shows it. [Control app and login](../use/control-app.md) walks through setup and adding accounts.

??? warning "The installer printed `tm-control migrate: WARNING`"

    The installer brings Frigate's configuration up to date, and warns about what it can't change safely. Each warning names the camera, stream, or setting. To find the warnings later:

    ```bash
    grep 'tm-control migrate: WARNING' ~/tmsetup-*.log
    ```

    **A camera input or stream without a login.** A camera's input `path` in Frigate's configuration reads a stream on port 8554 without a login. If that path points at this device, for example by its IP address, add `{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@` before the host in Frigate's configuration editor. The [higher-resolution stream](../configuration/frigate-config.md#higher-resolution-stream) section shows a complete path. If it points at another device, leave it as it is.

    **An `auth`, `proxy`, or `tls` setting.** The installer adds the settings that turn off Frigate's own login and let Frigate trust the user and role that the device's login passes on. It leaves a section that's already there as it is, and warns when a setting in it would get in the way:

    * `auth.enabled` or `tls.enabled` is true or missing: Frigate asks for its own login as well as the device's, or serves its port over TLS, which the device doesn't use.
    * A `proxy` setting doesn't match, followed by `auth was not added`: Frigate could trust user and role headers the device doesn't set, so the installer leaves Frigate's own login on.

    Change each named setting to match the [default Frigate config](https://github.com/glossyio/traffic-monitor/blob/main/container/frigate/config/config.yml.j2), in `/opt/traffic-monitor/frigate/config/config.yml` over SSH. Then run `bash script/tmsetup.sh -t frigate`, which adds what's still missing, and restart Frigate with `sudo systemctl restart frigate.service`.

A Frigate configuration from a backup may lack the camera stream login and the proxy settings. After you restore one, run `bash script/tmsetup.sh -t frigate` to add them.

Port 1883 accepts MQTT connections only from the device itself unless the broker has a login. If a display board, Home Assistant, or another device on your network reads MQTT from this device, give the broker a login and give it to that device; see [Connect from other devices](../data-and-payloads/integrations.md#connect-from-other-devices).

Open `http://<device>/`, log in, and check the [Monitoring dashboard](../ui/monitoring.md) for new counts.

To update several devices from your computer, use the remote form of the installer described in [Install the software](../software-installation.md#install-from-another-computer).

## What an update changes

An update replaces the container images, service units, Node-RED flows, and the reverse proxy configuration. It keeps your settings files, the database, Frigate's recordings, and the device's accounts. With `-f`, it also replaces the settings files with fresh copies from the templates and keeps each old file beside the new one with a timestamp. [What `-f` replaces](../reference/tmsetup.md#what-f-replaces) lists the files.

Use `-f` when a release changes the settings files and you want the new template. Afterwards, turn Frigate's detection back on and redo your settings from the timestamped copies: location and sensors in `config.yml`, and zones in Frigate. [First-time setup](../setup-guide.md) walks through each.

Node-RED flow changes made in the editor on the device are replaced on every update. Commit them to the repository instead; see [Dev environment](../development/dev-environment.md).

## Update one component

Each installer tag reruns one component, plus anything that has to change with it; see [Tags](../reference/tmsetup.md#tags). For example, after plugging in a radar:

```bash
bash script/tmsetup.sh -t node-red-tm
```

[Installer options](../reference/tmsetup.md) lists the tags and flags.
