# Installer options

`script/tmsetup.sh` in the repository installs and updates the Traffic Monitor. Run it from the device, or from another computer with `-H`. [Install the software](https://docs.trafficmonitor.ai/dev/software-installation/index.md) and [Update the software](https://docs.trafficmonitor.ai/dev/build-your-own-device-diy/update/index.md) show the usual runs.

```
bash traffic-monitor/script/tmsetup.sh [flags]
```

## Flags

| Flag             | Meaning                                                                                                                                                                                                                                                                                                                                                     |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-h`             | Show the usage text and exit.                                                                                                                                                                                                                                                                                                                               |
| `-y`             | Answer yes to every prompt, including the reboot.                                                                                                                                                                                                                                                                                                           |
| `-v`             | Verbose output. Repeat for more.                                                                                                                                                                                                                                                                                                                            |
| `-f`             | Replace the user-editable settings files with fresh copies from the templates. See [What `-f` replaces](#what-f-replaces).                                                                                                                                                                                                                                  |
| `-t TAG`         | Run one component, plus anything that has to change with it. Repeat for several. See [Tags](#tags).                                                                                                                                                                                                                                                         |
| `-T`             | List the tags and exit.                                                                                                                                                                                                                                                                                                                                     |
| `-C NAME[,NAME]` | Turn on an optional component: `plate_recognizer` (see [Plate Recognizer](https://docs.trafficmonitor.ai/dev/add-ons/plate-recognizer/index.md)), or `mqtt_lan`, which creates an MQTT broker login when there isn't one (see [Connect from other devices](https://docs.trafficmonitor.ai/dev/data-and-payloads/integrations/#connect-from-other-devices)). |
| `-u`             | Also upgrade the operating system's packages (`apt full-upgrade`).                                                                                                                                                                                                                                                                                          |
| `-d PATH`        | Install folder. Default `/opt/traffic-monitor`. The docs assume the default.                                                                                                                                                                                                                                                                                |
| `-o USER`        | Owner of the installed files and processes. Default `tmadmin`, created by the installer.                                                                                                                                                                                                                                                                    |
| `-g GROUP`       | Group of the installed files. Default `tmadmin`.                                                                                                                                                                                                                                                                                                            |
| `-z TIMEZONE`    | Time zone for the system and the dashboards, as a [tz database name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones). Default `America/Los_Angeles`.                                                                                                                                                                                          |
| `-L PATH`        | Where to write the installer's log.                                                                                                                                                                                                                                                                                                                         |
| `-a ARG`         | Pass an extra argument to the underlying Ansible run, without its leading hyphen.                                                                                                                                                                                                                                                                           |

Remote runs:

| Flag             | Meaning                                                                                                                 |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `-H HOST[,HOST]` | Install to these devices over SSH instead of the local machine. Separate several with commas.                           |
| `-l USER`        | The SSH username on the devices.                                                                                        |
| `-k`             | Ask for the SSH password.                                                                                               |
| `-K`             | Ask for the password for administrator rights (sudo). Needed on Raspberry Pi OS unless you've set up passwordless sudo. |

## Tags

Each tag reruns one part of the install. Without `-t`, everything runs. The pod and the reverse proxy have to change together, so the `podman`, `frigate`, `node-red-tm`, `go2rtc`, and `revproxy` tags each update both.

| Tag                | What it does                                                                                                                                                                                      |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `base`             | Operating system packages, the owner account, and Cockpit. It runs with every `-t`.                                                                                                               |
| `full_upgrade`     | The `apt full-upgrade`, when `-u` is given                                                                                                                                                        |
| `wifi`             | Wi-Fi setup                                                                                                                                                                                       |
| `go2rtc`           | The camera streaming service on the host, and the stream login Frigate uses to read it                                                                                                            |
| `detectors`        | Detects the Coral or Hailo accelerator, installs its driver, and writes the boot configuration. See [Add an accelerator later](#add-an-accelerator-later).                                        |
| `podman`           | The container runtime and the pod                                                                                                                                                                 |
| `frigate`          | Frigate's container, settings, and the devices it needs                                                                                                                                           |
| `node-red-tm`      | Node-RED's container, flows, settings, and the radars it needs. Rerun it after plugging in a radar.                                                                                               |
| `plate-recognizer` | The optional Plate Recognizer container                                                                                                                                                           |
| `revproxy`         | The home page and reverse proxy                                                                                                                                                                   |
| `tm-control`       | Installs the `tm-control` command, which updates settings files from earlier versions. The `frigate` and `go2rtc` tags install it too and run it to give Frigate's `config.yml` the stream login. |

## What `-f` replaces

Every run replaces the container images, service units, Node-RED flows, and the reverse proxy configuration. These files are kept unless you pass `-f`:

- `/opt/traffic-monitor/node-red-tm/config/config.yml`
- `/opt/traffic-monitor/node-red-tm/node-red-tm.env`
- `/opt/traffic-monitor/frigate/config/config.yml`, which holds zones and masks drawn in Frigate
- `/opt/traffic-monitor/frigate/frigate.env`
- `/opt/traffic-monitor/plate-recognizer/plate-recognizer.env`, if Plate Recognizer is installed

With `-f`, each is replaced by a fresh copy from its template, and the old file stays next to it with a timestamp in its name so you can copy your settings back. The MQTT broker login carries into the fresh `node-red-tm.env` and `frigate.env`. A fresh Frigate config has detection off and the sample zones, so afterwards turn detection on and redo your zones and masks, as in [First-time setup](https://docs.trafficmonitor.ai/dev/setup-guide/index.md).

## Add an accelerator later

After you add or change a Coral or Hailo accelerator, rerun two tags and reboot when the installer asks:

```
bash traffic-monitor/script/tmsetup.sh -t detectors -t frigate
```

That installs the driver and gives Frigate's container the device. Frigate's own `config.yml` still names the old detector, because the installer writes its `detectors:` and `model:` sections only when it creates the file. Either edit those two sections by hand to match the [template](https://github.com/glossyio/traffic-monitor/blob/main/container/frigate/config/config.yml.j2), or add `-f` to the command above and then redo your Frigate settings, as [What `-f` replaces](#what-f-replaces) describes.

## Reboots

The installer edits the boot configuration and installs kernel drivers, so it asks to reboot when needed. On the device, it prompts, and with `-y` it doesn't ask. Either way the reboot starts one minute later. Remote devices reboot by themselves. Services stay stopped until the reboot.
