---
description: Set up to change the Traffic Monitor: the Node-RED flows, the database schema, and testing on a dev Pi.
---

# Dev environment

The Traffic Monitor is open source, so you can change your devices to suit your needs. If others would benefit, [join the community](../help-and-faq/where-can-i-get-support.md) and [contribute back](contributing.md).

The [repository](https://github.com/glossyio/traffic-monitor) is a monorepo with everything needed to run a device: the installer, the container definitions, the Node-RED flows, and these docs.

## Node-RED logic

[Node-RED](https://nodered.org/) runs the Traffic Monitor's logic: it receives events from Frigate and readings from the radar, pairs events with speeds, writes the database, serves the dashboards, and sends data on. The flows are in the repository at `container/node-red-tm/data/flows.json`, and the installer copies them to the device on every run, so changes made only in a device's editor are lost on the next update.

To develop on a device:

1. Log in to the device as the administrator, then open the Node-RED editor at `http://<device>/nr/`. The editor has no login of its own.
2. Create a new project and clone your fork of the repository. This replaces the flows on the device, so save any changes first.
3. In the project's settings, set the package file to `container/node-red-tm/data/package.json`. Node-RED finds the flow and credentials files beside it, so your edits land in the repository's files.
4. Switch to the branch the device was installed from, such as `dev`. A clone starts on your fork's default branch, and flows from another version may not match the rest of the device.
5. Commit your changes to a branch of your fork.
6. Open a pull request, following [Contributing](contributing.md).

## Database schema

The tables are defined by numbered SQL migrations in `container/node-red-tm/schema/migrations/`, not by the flows. Each time `node-red-tm.service` starts, it applies the migrations the database doesn't have yet, before Node-RED opens it. The `README.md` in the schema directory describes the whole process, from writing a migration to testing the upgrade on a Pi.

To change the schema:

1. Add the next numbered migration, regenerate `schema.sql`, and update the table docs under [Data](../data-and-payloads/data-overview.md).
2. Run the tests, using the dev environment from [Contributing](contributing.md):

    ```bash
    .venv/bin/python -m pytest container/node-red-tm/schema/tests
    ```

To try a migration on a dev device, apply it while Node-RED is stopped. Deploying from the Node-RED editor doesn't restart the service, so it doesn't apply migrations. These commands use the default owner (`tmadmin`) and install folder, and run the migration script from your Node-RED project's clone:

```bash
sudo systemctl stop node-red-tm.service
sudo runuser -u tmadmin -- python3 \
    /opt/traffic-monitor/node-red-tm/data/projects/<project>/container/node-red-tm/schema/tmdb_migrate.py \
    --db /opt/traffic-monitor/node-red-tm/db/tmdb.sqlite
sudo systemctl start node-red-tm.service
```

The database records each migration it applies. If you change a migration after applying it, restore the copy saved in `/opt/traffic-monitor/node-red-tm/db/backup/` and apply it again.

## Control app

The control app in `tm-control/` serves the home page and the login in front of every app. [tm-control](tm-control.md) describes its code, how the login reaches each app, and how to run it on a laptop without a Pi.

## Pinned versions

An install builds from pinned sources, so the same commit gives the same software on any day. A pin that moves changes what every device builds, so test it on a bench Pi before you merge it. Most pins are in `script/ansible/roles/tmsetup/vars/main.yml`, with a comment that says how to take a new value.

| What | Where it is pinned | How to change it |
|---|---|---|
| Base images: Debian, Frigate, Node-RED, Node, nginx | A version (Debian's tag has none) and a digest, `tmsetup_<name>_image_digest`, in `vars/main.yml`. Every `FROM` line names its registry and ends in the digest. | Change the version, then take the new tag's digest from the registry. The digest and the version change together. For Node-RED, also remake the lock below. |
| The Raspberry Pi ffmpeg that Frigate's image builds | `tmsetup_frigate_ffmpeg_commit`, a commit of the branch named in the comment above it | Take the branch's new head with the `git ls-remote` command in that comment. |
| The Coral model and its labels | `tmsetup_frigate_coral_model_release`, with a SHA-256 for each file | Change the release, download both files, and take their checksums with `sha256sum`. A file already on the device that matches is kept, and one that doesn't is replaced. |
| Node-RED's modules | `container/node-red-tm/data/package-lock.json`, installed with `npm ci` | Remake it after you change `package.json` or Node-RED's version, with the command in the [README beside it](https://github.com/glossyio/traffic-monitor/blob/main/container/node-red-tm/data/README.md). It runs inside the pinned Node-RED image. |
| The control app's Python packages | `tm-control/backend/requirements.lock`, with hashes, which `pip install --require-hashes` reads | Remake it with the `uv pip compile` command in the lock's first lines, which also names the Python version and platform of a device. Add `--upgrade` to move packages that aren't in `requirements.txt`. |
| The installer's Ansible | `script/requirements.lock`, made from `script/requirements` (`ansible==`) the same way | The same, from `script/requirements`. |
| The control app's web page packages | `tm-control/ui/package-lock.json` | See the [UI README](https://github.com/glossyio/traffic-monitor/blob/main/tm-control/ui/README.md). |
| go2rtc | A version and a SHA-256 for each architecture in `vars/main.yml` | Change them together. |
| Hailo | `tmsetup_hailo_version` in `vars/main.yml` | Change the version. |

Dependabot moves `requirements.txt` and `package.json` but not a Python lock, so a Dependabot pull request for the control app's packages needs the lock remade on its branch. A test fails until it is. The optional Plate Recognizer add-on's image isn't pinned. The operating system's packages (`apt`) and the packages the Containerfiles add with `apt-get` and `apk` aren't either.

Tests check each pin, and a weekly check on GitHub (the "Pinned sources" workflow, which also runs on a change to a pin and by hand) asks the registries and sources whether every digest, commit, and checksum still resolves. A registry can drop a digest when a tag is pushed again. To run those checks yourself, set `TM_TESTS_ONLINE=1` when you run `pytest`; without it, the tests that need the network are skipped.

### What the build cache depends on

You can skip this section unless you build images on a device. The device builds its images with Podman, and Podman reuses a step from an earlier build when the step and its inputs are the same. On a Raspberry Pi 5 with Podman 5.4.2, we measured two things that decide whether a build reuses or starts over:

* A `COPY` step's cache key reads the owner and group of the files it copies, not their modification times. Files with the same content but a different owner or group mean the copy and the steps after it aren't reused from the cache.
* `podman image prune` removes the first stage of a two-stage build, which has no tag. Frigate's `build-ffmpeg` stage and the revproxy's `ui` stage are such stages, so the next build of either starts over.

The build units run at every boot, so a build that starts over runs then, and it needs the internet to pull layers and packages. On the same Pi, Frigate's rebuild took about 8 to 13 minutes. Don't prune a device's images unless it is online and can take that wait.

## Testing on a dev Pi

`script/devpi/tmdev.py` deploys your working copy to a bench Pi over SSH, runs commands on it, and records a PR's Pi test plan as a checklist. Every deploy, command, and check goes into a run log on your machine, so you can see later what ran on which Pi and how it went.

The Pis are defined in an inventory file that lists each Pi's address, login, and SSH key, plus the hardware it should have. That file and the run log stay on your machine, outside the repository. `script/devpi/README.md` covers setup and use.

!!! warning

    Use these tools only with bench units, not field devices. Deploys pass `-y` to the installer, so the Pi reboots whenever the installer needs it.
