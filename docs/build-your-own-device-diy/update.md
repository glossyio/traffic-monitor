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

??? warning "The installer printed `tm-control migrate: WARNING` or `ERROR`"

    The installer brings Frigate's configuration up to date, moves the ThingsBoard and Plate Recognizer tokens out of `config.yml` and the add-on's env file and a Frigate+ key out of `frigate.env`, and warns about what it can't change safely. An `ERROR` line means the installer stopped; the last item below covers the two causes. Each warning names the camera, stream, setting, or file. To find the warnings later:

    ```bash
    grep -E 'tm-control migrate: (WARNING|ERROR)' ~/tmsetup-*.log
    ```

    **A camera input or stream without a login.** A camera's input `path` in Frigate's configuration reads a stream on port 8554 without a login. If that path points at this device, for example by its IP address, add `{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@` before the host in Frigate's configuration editor. The [higher-resolution stream](../configuration/frigate-config.md#higher-resolution-stream) section shows a complete path. If it points at another device, leave it as it is.

    **An `auth`, `proxy`, or `tls` setting.** The installer adds the settings that turn off Frigate's own login and let Frigate trust the user and role that the device's login passes on. It leaves a section that's already there as it is, and warns when a setting in it would get in the way:

    * `auth.enabled` or `tls.enabled` is true or missing: Frigate asks for its own login as well as the device's, or serves its port over TLS, which the device doesn't use.
    * A `proxy` setting doesn't match, followed by `auth was not added` when the file had no `auth` section: Frigate could trust user and role headers the device doesn't set, so the installer leaves Frigate's own login on.

    Change each named setting to match the [default Frigate config](https://github.com/glossyio/traffic-monitor/blob/main/container/frigate/config/config.yml.j2), in `/opt/traffic-monitor/frigate/config/config.yml` over SSH. Then run `bash script/tmsetup.sh -t frigate`, which adds what's still missing, and restart Frigate with `sudo systemctl restart frigate.service`.

    **A token or key that wasn't moved.** The installer moves a ThingsBoard token, a Plate Recognizer token, and a license key that it finds in `config.yml` or in `plate-recognizer.env`, and a Frigate+ key typed into `frigate.env`, to the device's secrets, and deletes the keys from `config.yml`. It leaves a value that isn't text, or that has a character a token can't have, such as a space, and warns about it. A Frigate+ key moves only in the format Frigate+ shows it in, on its own or between double quotes; for a key it leaves, the installer writes the device's own key, or none, into `frigate.env`. It also warns when a value differs from the one the device already holds. The device keeps the value it holds, and `config.yml` and the env files are backed up with a timestamp, so the other value stays in the backup. That backup's name ends in `.migrate.bak`, and it stays until you delete it. Enter the token on the control app's [Device page](../use/device-health.md#tokens-and-keys), or the Frigate+ key on its [Detection page](../use/detection.md#frigate-plus), and delete a key the installer left in `config.yml`.

    **A file that is a symbolic link, or a YAML error (`ERROR`).** The installer refuses to change a `config.yml` or env file that is a symbolic link, and stops. Replace the link with the file itself, then run the installer again. A YAML error in Node-RED's `config.yml` also stops the installer, as one in Frigate's does. Fix the error in `/opt/traffic-monitor/node-red-tm/config/config.yml`, then run the installer again.

A Frigate configuration from a backup may lack the camera stream login and the proxy settings. After you restore one, run `bash script/tmsetup.sh -t frigate` to add them.

Port 1883 accepts MQTT connections only from the device itself unless the broker has a login. If a display board, Home Assistant, or another device on your network reads MQTT from this device, give the broker a login and give it to that device; see [Connect from other devices](../data-and-payloads/integrations.md#connect-from-other-devices).

Open `http://<device>/`, log in, and check the [Monitoring dashboard](../ui/monitoring.md) for new counts. After an update from a version without the Location page, that first visit to the control app also sets up the device's places; see [Places after an update](#places-after-an-update).

To update several devices from your computer, use the remote form of the installer described in [Install the software](../software-installation.md#install-from-another-computer).

## Places after an update

An update from a version without the control app's Location page brings the location settings up to date:

* The installer adds `database_precision: '2'` to `config.yml`, so the database stores the location rounded to about 1 km. It removes any `lat` and `lon` under a camera or radar, because the location belongs to the whole device, and its output names each sensor.
* When Node-RED first starts, it saves a copy of the database, gives each location in the stored rows a place id, and rounds the stored coordinates to two decimal places, once. The copy keeps the exact rows until the next update that changes the database replaces it; see [Schema versions](../data-and-payloads/data-overview.md#schema-versions).

Then open the control app and log in, as any user. The first time its home page, Status page, or [Location page](../use/location.md) opens after Node-RED has started, the control app sets up the device's places:

* Each location in the saved copy becomes a used place, marked **Imported from your previous settings**.
* The place at the location in `config.yml` becomes the place in use, and the control app writes its id into `config.yml`, so the deployments running now carry on. If no imported place is at that location, for example because it changed while the device was off, the control app makes a new place from `config.yml`, and new deployments start.
* A device with no location in `config.yml` gets a new place in use with no location. Its past places are imported all the same.

!!! warning "Open the control app before the next update"

    The control app reads the past places from the saved copy, and the next update that changes the database replaces it. Open the control app before then, and keep the copy until the Location page lists the places. If Node-RED hasn't answered yet, the Status page's Location check says the places haven't been set up, and the control app tries again each time a page that shows the checks opens.

If there's no copy, or the control app can't read it, the control app skips the import and makes only the place in use, from `config.yml`. The past places' records stay in the database, grouped by place id, but the Location page doesn't list those places.

??? note "A device whose sensors had their own coordinates"

    The update gives each sensor's own location a place of its own. Once the control app writes the place in use into `config.yml`, each sensor whose location differed from the device's starts a new deployment there. Its earlier records stay with their own place, which the Location page lists as used.

## What an update changes

An update replaces the container images, service units, Node-RED flows, and the reverse proxy configuration. It keeps your settings files, the database, Frigate's recordings, and the device's accounts. With `-f`, it also replaces the settings files with fresh copies from the templates and keeps each old file beside the new one with a timestamp. [What `-f` replaces](../reference/tmsetup.md#what-f-replaces) lists the files.

Use `-f` when a release changes the settings files and you want the new template. Afterwards, turn Frigate's detection back on and redo your settings from the timestamped copies: the `sensors` section of `config.yml`, and zones in Frigate. [First-time setup](../setup-guide.md) walks through each. You don't need to copy back `survey_id`, `lat`, `lon`, `database_precision`, or the bearings: the next time the control app is opened, it puts back the place in use, its location, the precision you chose, and the way each sensor faces there; see [Edit the location by hand](../configuration/node-red-config.md#edit-the-location-by-hand).

Node-RED flow changes made in the editor on the device are replaced on every update. Commit them to the repository instead; see [Dev environment](../development/dev-environment.md).

## Update one component

Each installer tag reruns one component, plus anything that has to change with it; see [Tags](../reference/tmsetup.md#tags). For example, after plugging in a radar:

```bash
bash script/tmsetup.sh -t node-red-tm
```

[Installer options](../reference/tmsetup.md) lists the tags and flags.
