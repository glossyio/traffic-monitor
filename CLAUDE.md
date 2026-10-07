# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Traffic Monitor turns a Raspberry Pi 5 with a camera, OmniPreSense Doppler radar(s), and an optional AI accelerator (Coral TPU / Hailo-8L) into a roadway counter and speed monitor. Nothing is compiled off-device. The repo is:

- `script/`: `tmsetup.sh` plus one Ansible role (`script/ansible/roles/tmsetup`) that provisions the Pi. It installs apt packages, drivers, and host services, and a Podman pod whose images are built on the device.
- `container/`: Jinja templates per container (Containerfile, Podman Quadlet units, env/config files). `docker/` is a symlink to it.
- `container/node-red-tm/data/flows.json`: nearly all application logic (Node-RED flows).
- `utils/`: helper scripts and configs that get copied to `{{ tmsetup_codedir }}/utils` on the device.
- `docs/`: GitBook source for docs.trafficmonitor.ai (`.gitbook.yaml`). It uses GitBook markdown (`{% hint %}`, `"mention"` links).

## Commands

There's no CI. The off-device tests cover the tmdb schema (`container/node-red-tm/schema/tests`). Device tests (`script/devpi/tests`) check a bench Pi over SSH and run only through `tmdev.py test` (or with `TM_DEV_HOSTS` set). Install only works on a Raspberry Pi running Raspberry Pi OS 64-bit. The role reads the Pi serial number from devicetree, edits `/boot/firmware/config.txt`, builds kernel drivers, and may reboot, so never run `tmsetup.sh` against a dev machine.

Local checks (any Linux box):

```bash
# One dev venv (Ansible + pytest, from script/requirements-dev) for every check. Activate it in the same shell invocation.
python3 -m venv .venv && .venv/bin/pip install -r script/requirements-dev
. .venv/bin/activate

python -m pytest container/node-red-tm/schema/tests  # schema runner, migrations, and flows.json SQL vs. schema
(cd script/ansible && ansible-playbook -i localhost setup.yml --syntax-check)  # task/YAML structure; does not render templates
(cd script/ansible && ansible-playbook -i localhost setup.yml --list-tags)
python -c 'import sys,jinja2; e=jinja2.Environment(); [e.parse(open(f).read(), filename=f) for f in sys.argv[1:]]' $(git ls-files '*.j2')
python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null
bash -n script/tmsetup.sh
```

- In a non-interactive shell, Ansible may abort with "requires blocking IO". Run it with `</dev/null` and redirect output to a file.
- `ansible-lint` runs, but nothing configures or enforces it, and it currently reports about 10 basic-profile violations. It also deletes the tracked, empty `.ansible/.lock`; restore it with `git checkout -- .ansible/.lock`.

On a Pi (re-running a single tag is the closest thing to running a single test):

```bash
bash script/tmsetup.sh                    # full local install; -y skips prompts, -v for verbose Ansible
bash script/tmsetup.sh -T                 # list tags: base full_upgrade wifi go2rtc detectors podman frigate node-red-tm plate-recognizer revproxy
bash script/tmsetup.sh -t node-red-tm     # redeploy one component (-t can repeat)
bash script/tmsetup.sh -f                 # also overwrite user-editable configs from templates (timestamped backups kept)
bash script/tmsetup.sh -C plate_recognizer            # enable the optional Plate Recognizer container
bash script/tmsetup.sh -H <ip>[,<ip>] -l <user> -k    # from a dev machine: install to remote Pis over SSH
```

Always use `tmsetup.sh` rather than calling `ansible-playbook` directly. The script supplies extra vars the role depends on (e.g. `tmsetup_reboot_touch_file`) and handles the reboot prompt.

From a dev machine, against a bench Pi defined in the local dev-Pi inventory (`script/devpi/README.md`):

```bash
.venv/bin/python script/devpi/tmdev.py pi-login [--key <name>] [--shell]       # tmdev login for a new card (cloud-init) or running Pi
.venv/bin/python script/devpi/tmdev.py hosts                                   # dev Pis in the inventory
.venv/bin/python script/devpi/tmdev.py deploy <host> [--on-pi] -- -t <tag>     # tmsetup.sh with -y; may reboot the Pi
.venv/bin/python script/devpi/tmdev.py run <host>|local -- <command>           # run and log a command
.venv/bin/python script/devpi/tmdev.py check start|item|status|end ...         # record a PR's Pi test plan
.venv/bin/python script/devpi/tmdev.py test <host> [--disruptive] [-- -k <expr>]  # device tests vs. the host's tm_expect
.venv/bin/python script/devpi/tmdev.py log                                     # newest rows of the run log
```

The inventory and the run log live outside the repo. Never commit them, and keep device names and addresses out of commits and PR text. tmdev logs in as a key-only `tmdev` account with passwordless sudo, because Raspberry Pi OS 6.2 and later asks for a sudo password by default and `tmsetup.sh -K` can't be answered over SSH. Device tests that read `config.yml` or `tmdb.sqlite` run only on hosts marked `tm_expect.pii_free: true`.

Containers run as rootful, Quadlet-generated systemd units:

```bash
sudo systemctl status traffic-monitor.service   # the pod; also frigate, node-red-tm, revproxy, plate-recognizer, go2rtc_server
sudo journalctl -u node-red-tm.service -f
sudo podman ps
sudo systemctl restart frigate-tm-build.service  # re-run an image build (each <name>.build unit becomes <name>-build.service)
```

## Architecture

### Provisioning (Ansible → Podman Quadlets)

- `tasks/main.yml` imports one tagged task file per component. The tag list is duplicated in `_VALID_TAGS` in `script/tmsetup.sh`, which rejects unknown `-t` values. Optional components are gated on `tmsetup_bool_<name>`, which must also be listed in `_VALID_CUSTOM_VARS` for `-C` to accept it.
- The role's `templates/container` and `files/container` are symlinks to the top-level `container/`, and `files/utils` points to `utils/`. So `src: container/...` in a task means the top-level directory; edit files there.
- Each `container/<svc>/` follows one pattern:
  - `Containerfile.j2` defines the image, which is built on the device.
  - `<svc>.build.j2` and `<svc>.container.j2` are Quadlet units, rendered into `/etc/containers/systemd/`.
  - `*.env.j2` and `config/config.yml.j2` hold user-editable settings.

  Other rendered files land in `{{ tmsetup_codedir }}/<svc>/` (default `/opt/traffic-monitor`). When adding a component, copy `revproxy`, the newest complete example. That means a task file, an import in `tasks/main.yml` with its tag, a `Restart <svc>.service` handler, and the tag added to the `start_services.yml` import and to `_VALID_TAGS`.
- **Overwrite semantics:** the `config.yml` and `*.env` templates use `force: '{{ tmsetup_force_configs }}'`, so they're written only on first install or with `-f`. Changes to those templates won't reach existing devices otherwise. Containerfiles, Quadlet units, nginx files, Node-RED `flows.json`/`settings.js`/`package.json`, and the tmdb schema files from `container/node-red-tm/schema/` (all but `tests/`) are overwritten on every run. Flow edits made in a device's Node-RED editor are lost unless they're committed back here.
- **Hardware is detected at install time** and baked into rendered files.
  - `detectors_check.yml` probes for Coral USB/PCIe and Hailo-8L (`tmsetup_detectors` in `defaults/main.yml`). The results drive Frigate's `AddDevice` lines, the `detectors:`/`model:` sections of Frigate's `config.yml`, and `/boot/firmware/traffic-monitor-config.txt`.
  - Radars present at `/dev/ttyACM0-3` become `AddDevice` lines for node-red-tm.

  After a hardware change, re-run the relevant tags (`-t detectors -t frigate`, or `-t node-red-tm`). Frigate's `config.yml` only re-renders with `-f`.
- Versions are pinned in `roles/tmsetup/vars/main.yml`. That covers `tmsetup_tm_version` (exposed to Node-RED as `TM_VERSION`), Frigate, Node-RED, nginx, go2rtc, and Hailo. User-tunable defaults live in `defaults/main.yml`. The role's `README.md` is outdated (wrong default paths and owner), so trust `defaults/main.yml`.
- Reboots: handlers notify `TMSetup - Flag for reboot`.
  - Locally, this writes `~/.tmsetup/reboot-required`, and `tmsetup.sh` reads it to prompt for a reboot.
  - Remote hosts reboot directly.
  - While a reboot is pending (`tmsetup_restart_required`), services are left stopped.

### Runtime topology

- All containers (frigate, node-red-tm, revproxy, optional plate-recognizer) run in one pod, `container/traffic-monitor.pod.j2`, which also lists the published ports. They share the pod's network namespace:
  - Frigate publishes MQTT to `localhost:1883`. That broker is Aedes, running inside Node-RED.
  - Node-RED calls `http://frigate:5000/api/...`.
  - nginx proxies to `127.0.0.1:<port>`.
- go2rtc runs on the host, not in the pod (`go2rtc_server.service`, config from `roles/tmsetup/files/go2rtc.yaml`), because it runs `rpicam-vid` to reach the Pi camera. Frigate reads `rtsp://host.containers.internal:8554/picam_h265_detect`. The pod's port 1984 (Frigate's bundled go2rtc) is published as host port 1964 because the host go2rtc already uses 1984.
- The Frigate image adds a Raspberry Pi ffmpeg fork compiled for hardware HEVC decoding (`-hwaccel drm`, `/dev/media3`, `/dev/video19`).
- UIs: Node-RED editor `:1880` (admin/password), legacy dashboard `:1880/ui`, Dashboard 2.0 `:1880/dashboard`, Frigate `:5000`, host go2rtc `:1984`.
- nginx (`revproxy`) serves a home page on `:80` and proxies `/dashboard`, `/frigate`, `/ui`, `/nr`, and `/feeds`. The `location` blocks and the home-page links are both generated from `tmsetup_proxies` in `vars/revproxy_vars.yml`. Frigate runs under a base path set by `FRIGATE_BASE_PATH` and `X-Ingress-Path`.

### Node-RED flows (application logic)

`flows.json` (~450 KB, 11 tabs) holds the TM logic. Node modules come from `data/package.json` and are installed when the node-red-tm image is built, so adding a module needs an image rebuild.

- `init-config` reads `/config/config.yml` (on the host: `{{ tmsetup_codedir }}/node-red-tm/config/config.yml`), applies defaults, and stores the result as `global.config`. It also records deployments (lat/lon/bearing) and hosts the Aedes broker. The config is read only when the flows start.
- `capture-radar` talks to OmniPreSense radars over serial (AN-010 API, 19200 baud). It sends setup commands at startup and writes the `radar_*` tables.
- `capture-events` handles Frigate `frigate/events` MQTT messages with `type: "end"`, keeping only moving objects from cameras enabled in config.yml.
  - Direction comes from the order of `zone_near`/`zone_far` in `entered_zones`.
  - Speed is the median `radar_dov` velocity for that direction, within the event window ±2 s.
  - Results go to the `events` table, then via link nodes to `plate-recognizer`, `ui-monitoring`, and `thingsboard`.
- `capture-aq` reads the air-quality sensor over MQTT `aq/#`. `system` collects OS and hardware metrics.
- `thingsboard` optionally uploads everything to a ThingsBoard IoT server. It also handles config backup/restore, which can push a Frigate config through Frigate's API.
- UI tabs:
  - `ui-monitoring` is the legacy node-red-dashboard (`/ui`) and also feeds the Dashboard 2.0 tabs.
  - `Dashboard 2 - Monitoring`, `ui-movements`, and `ui-database` are FlowFuse Dashboard 2.0 pages under `/dashboard`. The `ui-database` page handles data export and download.
- Storage is one SQLite DB at `/db/tmdb.sqlite` in the container (`TM_DATABASE_PATH_TMDB`). The schema is defined by numbered SQL migrations in `container/node-red-tm/schema/migrations/`, not by the flows. `tmdb_migrate.py` applies pending ones as `ExecStartPre` of `node-red-tm.service`, before Node-RED opens the DB, and records the version in `PRAGMA user_version` (see that directory's README). A schema change needs a new migration and a regenerated `schema.sql`; never add `CREATE`/`ALTER TABLE` nodes to the flows. Tables and payloads are documented in `docs/data-and-payloads/`; keep them in sync.

**Cross-component name contracts.** A mismatch fails silently:
- Frigate camera names (default `picam_h265`) must match `sensors.cameras.<name>` in the Node-RED `config.yml`. Events from cameras that are missing or disabled there are not recorded.
- Frigate zone names are hard-coded in the flows: `zone_capture` (counts), `zone_radar` (speed), `zone_near`/`zone_far` (direction).
- Radar names are the env var names `TM_RADAR_SERIAL_PORT_00..03` from `node-red-tm.env`. They're used as keys under `sensors.radars` and as `camera_radar` values.

**Editing `flows.json`:**
- The documented workflow is the Node-RED editor's Projects feature (`docs/development/dev-environment.md`), but direct edits work too.
- Function code is a JSON-escaped string in each node's `func`. Nodes connect through `wires`. Across tabs they connect through `link in`/`link out` nodes, whose `links` arrays hold node ids.
- Edit programmatically and re-serialize the way Node-RED does, to keep diffs minimal. Either of these reproduces the current file byte-for-byte:
  - JS `JSON.stringify(flows, null, 4)`, with no trailing newline.
  - Python `json.dumps(flows, indent=4, ensure_ascii=False)`.
- `flows_cred.json` is encrypted with `NODE_RED_CREDENTIAL_SECRET` from `node-red-tm.env`; don't hand-edit it.

## Conventions

- PRs target `dev`; `main` tracks the latest stable release. Branch names follow `{feature|refactor|bugfix|hotfix}/{short-summary}/{issue-id}`.
- Line endings are LF (`.gitattributes`). CONTRIBUTING.md says to indent with 4 spaces, but the Ansible YAML uses 2, so match the file you're editing.
- Ansible style:
  - Task names look like `TMSetup - <Component> - <Action>`.
  - Role variables are prefixed `tmsetup_`, and registered results end in `_register`.
  - Modules use FQCNs (`ansible.builtin.*`, `community.general.*`).
  - `become: true` is set per task.

## AI use in this repository

The policy is "Use of AI tools" in CONTRIBUTING.md: AI may draft, but a person reviews, tests, and owns every change.

- Keep drafts small enough for a person to review line by line, and say what you're unsure about.
- Device data follows "Use of AI tools" in CONTRIBUTING.md. Never read images, video clips, or plate reads. Before reading a copy of `tmdb.sqlite`, confirm with the user that the device operator consented and that plate recognition was never enabled. Never ask for real passwords, API keys, or tokens; work with placeholders. Don't read anything under `/opt/traffic-monitor` on a Pi. `.claude/settings.json` blocks that path and asks before database reads.
- End commit messages with this trailer block instead of `Co-Authored-By`; in this repo `Co-authored-by` means a human co-author. Take the version from `claude --version` and the model from your own model ID. If you don't know the interface or effort level, ask; never guess a value.

  ```text
  Assisted-by: Claude Code <version> (<CLI | VS Code | JetBrains | desktop app | web>)
  AI-Model: <model name> (<model id>)
  AI-Effort: <effort level>
  AI-Role: drafted | review only
  ```

  Don't use Claude Code's `attribution` setting for this: empty strings there turn off all commit attribution, this block included.

- In pull requests, fill in the template's "AI assistance" section instead of adding a "Generated with Claude Code" footer.
- Don't add AI-provenance comments to code.
