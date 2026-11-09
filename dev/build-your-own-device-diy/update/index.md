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

Every app asks for the device's login, and the Node-RED editor has no login of its own: it opens for the device's administrator. If the device has no administrator account yet, every page opens the setup page instead. Claim the device with the setup code from the end of the installer's output; until the device is claimed, `sudo cat /etc/traffic-monitor/setup-code` also shows it. [Control app and login](https://docs.trafficmonitor.ai/dev/use/control-app/index.md) walks through setup and adding accounts.

The installer printed `tm-control migrate: WARNING` or `ERROR`

The installer brings Frigate's configuration up to date, moves the ThingsBoard and Plate Recognizer tokens out of `config.yml` and the add-on's env file and a Frigate+ key out of `frigate.env`, and warns about what it can't change safely. An `ERROR` line means the installer stopped; the last item below covers the two causes. Each warning names the camera, stream, setting, or file. To find the warnings later:

```
grep -E 'tm-control migrate: (WARNING|ERROR)' ~/tmsetup-*.log
```

**A camera input or stream without a login.** A camera's input `path` in Frigate's configuration reads a stream on port 8554 without a login. If that path points at this device, for example by its IP address, add `{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@` before the host in Frigate's configuration editor. The [higher-resolution stream](https://docs.trafficmonitor.ai/dev/configuration/frigate-config/#higher-resolution-stream) section shows a complete path. If it points at another device, leave it as it is.

**An `auth`, `proxy`, or `tls` setting.** The installer adds the settings that turn off Frigate's own login and let Frigate trust the user and role that the device's login passes on. It leaves a section that's already there as it is, and warns when a setting in it would get in the way:

- `auth.enabled` or `tls.enabled` is true or missing: Frigate asks for its own login as well as the device's, or serves its port over TLS, which the device doesn't use.
- A `proxy` setting doesn't match, followed by `auth was not added` when the file had no `auth` section: Frigate could trust user and role headers the device doesn't set, so the installer leaves Frigate's own login on.

Change each named setting to match the [default Frigate config](https://github.com/glossyio/traffic-monitor/blob/main/container/frigate/config/config.yml.j2), in `/opt/traffic-monitor/frigate/config/config.yml` over SSH. Then run `bash script/tmsetup.sh -t frigate`, which adds what's still missing, and restart Frigate with `sudo systemctl restart frigate.service`.

**A token or key that wasn't moved.** The installer moves a ThingsBoard token, a Plate Recognizer token, and a license key that it finds in `config.yml` or in `plate-recognizer.env`, and a Frigate+ key typed into `frigate.env`, to the device's secrets, and deletes the keys from `config.yml`. It leaves a value that isn't text, or that has a character a token can't have, such as a space, and warns about it. A Frigate+ key moves only in the format Frigate+ shows it in, on its own or between double quotes; for a key it leaves, the installer writes the device's own key, or none, into `frigate.env`. It also warns when a value differs from the one the device already holds. The device keeps the value it holds, and `config.yml` and the env files are backed up with a timestamp, so the other value stays in the backup. Enter the token or key on the control app's [Device page](https://docs.trafficmonitor.ai/dev/use/device-health/#tokens-and-keys), and delete a key the installer left in `config.yml`.

**A file that is a symbolic link, or a YAML error (`ERROR`).** The installer refuses to change a `config.yml` or env file that is a symbolic link, and stops. Replace the link with the file itself, then run the installer again. A YAML error in Node-RED's `config.yml` also stops the installer, as one in Frigate's does. Fix the error in `/opt/traffic-monitor/node-red-tm/config/config.yml`, then run the installer again.

A Frigate configuration from a backup may lack the camera stream login and the proxy settings. After you restore one, run `bash script/tmsetup.sh -t frigate` to add them.

Port 1883 accepts MQTT connections only from the device itself unless the broker has a login. If a display board, Home Assistant, or another device on your network reads MQTT from this device, give the broker a login and give it to that device; see [Connect from other devices](https://docs.trafficmonitor.ai/dev/data-and-payloads/integrations/#connect-from-other-devices).

Open `http://<device>/`, log in, and check the [Monitoring dashboard](https://docs.trafficmonitor.ai/dev/ui/monitoring/index.md) for new counts.

To update several devices from your computer, use the remote form of the installer described in [Install the software](https://docs.trafficmonitor.ai/dev/software-installation/#install-from-another-computer).

## What an update changes

An update replaces the container images, service units, Node-RED flows, and the reverse proxy configuration. It keeps your settings files, the database, Frigate's recordings, and the device's accounts. With `-f`, it also replaces the settings files with fresh copies from the templates and keeps each old file beside the new one with a timestamp. [What `-f` replaces](https://docs.trafficmonitor.ai/dev/reference/tmsetup/#what-f-replaces) lists the files.

Use `-f` when a release changes the settings files and you want the new template. Afterwards, turn Frigate's detection back on and redo your settings from the timestamped copies: location and sensors in `config.yml`, and zones in Frigate. [First-time setup](https://docs.trafficmonitor.ai/dev/setup-guide/index.md) walks through each.

Node-RED flow changes made in the editor on the device are replaced on every update. Commit them to the repository instead; see [Dev environment](https://docs.trafficmonitor.ai/dev/development/dev-environment/index.md).

## Update one component

Each installer tag reruns one component, plus anything that has to change with it; see [Tags](https://docs.trafficmonitor.ai/dev/reference/tmsetup/#tags). For example, after plugging in a radar:

```
bash script/tmsetup.sh -t node-red-tm
```

[Installer options](https://docs.trafficmonitor.ai/dev/reference/tmsetup/index.md) lists the tags and flags.
