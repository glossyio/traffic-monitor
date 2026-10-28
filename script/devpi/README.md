# Dev-Pi tools

`tmdev.py` deploys this checkout to development Raspberry Pis over SSH and runs commands on them. It also records PR checks and runs the device tests in `tests/`. Everything it does is written to a run log on your machine, so you can see later what ran on which Pi, from which code, and how it went.

Use these tools only with bench units, not field devices.

## What stays on your machine

Two files name real devices or record what ran on them. Both live outside the repo, and the tools refuse paths inside any git work tree:

| What | Default location | Override |
|---|---|---|
| Dev-Pi inventory | `~/.config/traffic-monitor/dev-pis.yml` | `TM_DEV_INVENTORY` |
| Run log | `${XDG_STATE_HOME:-~/.local/state}/traffic-monitor/dev-tests/` | `TM_DEV_LOG_DIR` |

Keep device names, addresses, and log contents out of commits and PR text. Use placeholders.

## Setup

1. Set up the dev venv from [CONTRIBUTING.md](../../CONTRIBUTING.md#testing). It provides `ansible-inventory`, which `tmdev.py` uses to read the inventory.
   - Remote deploys run `tmsetup.sh` on your machine, and it creates its own venv with `python3 -m venv`. On Debian or Ubuntu that needs the `python3-venv` package.
   - On-Pi deploys need `rsync` on both machines.
2. Create an SSH key without a passphrase, once per dev machine:

   ```bash
   ssh-keygen -t ed25519 -N '' -f ~/.ssh/tm_dev -C tm-dev
   ```

   These steps use the name `tm_dev`, but any name works. With another name, pass it to `pi-login` as `--key <name>`, and set the inventory's `ansible_ssh_private_key_file` to it.

3. Give each Pi a `tmdev` login. It logs in with that key only (it has no password) and runs `sudo` without a password. `tmsetup.sh` and the tests need root but can't type a password over SSH, and Raspberry Pi OS 6.2 and later asks for one by default. Your own account doesn't change and keeps its sudo password.

   - **New card** (Raspberry Pi OS Trixie images from 24 November 2025 on, written with Raspberry Pi Imager 2.0 or later): set up the card in Imager as usual. Then, before the Pi's first boot, open the card's boot partition and add the `tmdev` entry to the `users:` list in `user-data`. Cloud-init creates the login at first boot, so you never have to log in to the Pi.

     ```bash
     .venv/bin/python script/devpi/tmdev.py pi-login                       # prints the entry, with ~/.ssh/tm_dev.pub filled in
     .venv/bin/python script/devpi/tmdev.py pi-login --key my_pi_key      # another key in ~/.ssh, or a path to one
     ```

     `--key` takes a key name in `~/.ssh` or a path to the key. Either way, only the `.pub` file is read. Given an inventory host, as in `pi-login tm-dev-01`, it uses that host's login and key.

     Keep a single `users:` list, and match its indentation. A second `users:` key replaces the first, including your own user. `user-data` also holds your password (or its hash) from Imager, so don't share the file.
   - **A Pi that's already running**, or an older image: print the setup commands, then run them on the Pi while logged in as your own account.

     ```bash
     .venv/bin/python script/devpi/tmdev.py pi-login --shell [--key <name>]
     ```

   Then check from your machine. This also accepts the Pi's host key, so do it before the first deploy. Deploys, `run`, and the tests won't accept a new host key on their own:

   ```bash
   ssh -i ~/.ssh/tm_dev tmdev@<pi> sudo -n true && echo ok      # use your key's name
   ```

   Whoever holds that private key has root on the Pi, so use this only on bench units. To remove the login, run `sudo userdel -r tmdev`. Then also do one of these:
   - for a login made with `--shell`: `sudo rm /etc/sudoers.d/090-tmdev`;
   - for a cloud-init login: delete its line with `sudo visudo -f /etc/sudoers.d/90-cloud-init-users`.
4. Copy the template, fill it in, and check it:

   ```bash
   mkdir -p ~/.config/traffic-monitor
   cp script/devpi/dev-pis.example.yml ~/.config/traffic-monitor/dev-pis.yml
   chmod 600 ~/.config/traffic-monitor/dev-pis.yml
   .venv/bin/python script/devpi/tmdev.py hosts
   ```

   Set `tm_expect.pii_free: true` only for a unit that has never recorded real-world data, never had plate recognition enabled, and still has the blank `thingsboard.access_token` it was installed with (the one secret in `config.yml`). The flag allows checks, including ones an AI assistant runs, that read `config.yml` and `tmdb.sqlite` under `/opt/traffic-monitor`. It's the only exception to CLAUDE.md's rule against reading that path on a Pi. Images, video clips, plate reads, and secrets are never read.

   To test what `tmsetup.sh` does when sudo asks for a password, add a second entry for the same Pi that logs in as your own account. Use another name, such as `tm-dev-01-owner`.

   Once you've claimed the Pi (open `http://<pi>/setup` and use the setup code the installer printed), add its administrator login as `tm_control_login`, with `username` and `password`. The device tests log in with it to check the login in front of the apps. Without it, those checks are skipped. The tests make their own viewer account, `tmdev-viewer-<random>`, and delete it afterwards.

## Deploying

```bash
.venv/bin/python script/devpi/tmdev.py deploy tm-dev-01 -- -t revproxy           # remote: tmsetup.sh -H from this machine
.venv/bin/python script/devpi/tmdev.py deploy tm-dev-01 --on-pi -- -t base       # on-Pi: tmsetup.sh run on the Pi itself
```

The two modes:
- **Remote** runs this checkout's `tmsetup.sh` with `-H`, `-l`, and `--private-key`, all taken from the inventory.
- **On-Pi** copies the working tree, including uncommitted changes, to `~/tm-src` on the Pi, then runs `tmsetup.sh` there as a local install. Use it when a test plan calls for a run on the device, such as a sudo prompt or a non-root run.
  - The copy leaves out `.git`, `docs/`, `static/`, and git-ignored files.

Both modes:
- pass everything after `--` to `tmsetup.sh`;
- add `-y`, so **the Pi reboots** if the installer flags a reboot;
- pass `-d` when the inventory sets `tmsetup_codedir`.

## Running commands

```bash
.venv/bin/python script/devpi/tmdev.py run tm-dev-01 -- 'systemctl is-active frigate.service node-red-tm.service'
.venv/bin/python script/devpi/tmdev.py run local -- python -m pytest container/node-red-tm/schema/tests
```

`run` behaves like `ssh`: the words after `--` are joined with spaces and go to the Pi's shell, so quote a compound command as one word (`-- 'cmd1; cmd2'`). With the host `local`, bash runs it on your machine instead, with tmdev's venv first on `PATH`, so `python` is the dev venv's even in a `--src` worktree that has no `.venv`.

Each command's output is shown and also saved as `cmd-NNN.out`. A line in `commands.log` records the command, the time, and the exit code. The files go into the open PR check, or into `adhoc/<date>/` when no check is open. `tmdev.py` exits with the command's exit code.

Output, logged commands, and saved deploy logs have values that look like secrets replaced with `<redacted>`. That covers:
- `KEY=value` and `"key": value` pairs where a part of the key, split at `_`, `.`, or `-`, is `password`, `pass`, `pwd`, `secret`, `token`, `api_key`, `access_key`, or `credential`;
- `Authorization:` headers and `Bearer` tokens;
- passwords in URLs, such as `mqtt://user:<redacted>@host`.

It's a safety net, not a filter, so don't print secrets on purpose.

## PR checks

A check turns a PR's "On a Raspberry Pi" test plan into a logged checklist:

```bash
T=".venv/bin/python script/devpi/tmdev.py"
$T check start --host tm-dev-01 --pr 212 --title "Cockpit at /system/"
$T run tm-dev-01 -- 'curl -sS -o /dev/null -w "%{http_code} %{redirect_url}\n" http://localhost/system/'   # cmd-001
$T check item "/system/ shows the Cockpit login without an HTTPS redirect" pass --evidence cmd-001
$T check item "Logging in and the Terminal page work through the proxy" manual --note "needs the Pi user's password"
$T check status        # the checklist so far
$T check end           # closes the check and adds its row to the log
```

The statuses are `pass`, `fail`, `skip`, and `manual`. Use `manual` for an item that's waiting on a person, such as a password, a visual check, or a physical action.

Recording an item again replaces its status. For example, record `pass --note "confirmed by <name>"` once the person has done it. To do that after `check end`, run `check reopen <run dir>`. Ending the check again adds a new row to the log.

The check's result is:
- **fail** if any item failed;
- **pending** if any item is still `manual`;
- **pass** otherwise.

### Testing another branch

The tools can test a branch that doesn't contain them, such as an open PR that this one isn't based on. Add a worktree for that branch and open the check with `--src`:

```bash
git worktree add ../tm-pr210 feature/switch_nginxconf_from_dict
$T check start --host tm-dev-01 --pr 210 --title "revproxy location files" --src ../tm-pr210
$T deploy tm-dev-01 -- -t revproxy          # deploys ../tm-pr210, logged as PR 210
$T run local -- bash -n script/tmsetup.sh   # local commands run in ../tm-pr210
```

While that check is open:
- `deploy` uses its `--src` checkout and PR number, unless you pass `--src` or `--pr`.
- `run local` runs in that checkout.
- `checklist.md` names the code under test, and also the checkout the tools ran from.

`--src` must be the top of a git work tree containing `script/tmsetup.sh`.

Reading `tmdb.sqlite` while Node-RED runs can make a Node-RED write fail if it lands at the same moment, because `node-red-node-sqlite` sets no busy timeout. That includes `tmdb_migrate.py --check`. It's acceptable on a bench unit, but keep reads short.

## Device tests

The tests in `tests/` compare a Pi with its `tm_expect` entry. Each one checks some of the following:
- **Expected:** what the inventory says the Pi has.
- **Present:** what's actually attached.
- **Configured:** what the installer rendered.
- **Working:** the runtime APIs and data.

A failure therefore tells you whether to look at the hardware, the inventory, or the installer.

```bash
.venv/bin/python script/devpi/tmdev.py test tm-dev-01                          # one Pi
.venv/bin/python script/devpi/tmdev.py test                                    # every Pi in the inventory
.venv/bin/python script/devpi/tmdev.py test tm-dev-01,tm-dev-02                # several Pis
.venv/bin/python script/devpi/tmdev.py test tm-dev-01 -- -k radar              # pytest options after --
.venv/bin/python script/devpi/tmdev.py test tm-dev-01 --disruptive             # also restart services and reboot the Pi
```

| Module | Checks |
|---|---|
| `test_platform.py` | Pi 5, 64-bit OS, no throttling or under-voltage, free space, SoC temperature |
| `test_services.py` | Host services, `tm-control.service`, and pod containers active, image builds succeeded and the UI's build unit finished, no crash restarts, no Plate Recognizer on `pii_free` units; polkit refuses the control app's user any unit not on its list and any transient unit; PID 1 logs how each start job ended, which the control app reads for its jobs |
| `test_web.py` | `nginx -t`; every location in the running proxy config answers; Node-RED, Frigate, go2rtc, and control app ports on the Pi, and the control app listening on 127.0.0.1 only; the home page from your machine; from your machine, the app ports are closed, `/feeds/` is view-only, and the camera stream asks for a login; Frigate's API doesn't show the camera stream's password; data export errors; Frigate logged in to the MQTT broker; and, on `pii_free` units, a failed download ending, a failed database copy answering with an error, the database download tarring a copy, and MQTT on port 1883 open only with a broker login that the broker enforces |
| `test_web.py` (login) | Without a session every app path redirects to the login page (or to `/setup` while unclaimed); the login check's own paths and the rescue page are hidden; redirects are relative; repeated wrong logins back off. With `tm_control_login`: the admin opens every app; a viewer gets 403 on the admin apps; Frigate ignores roles a client sends and knows who's logged in; the Node-RED editor opens without its own login. On `pii_free` units, Frigate's config and the install logs don't show the control app's secrets |
| `test_ai_coprocessor.py` | The expected co-processor and no other, its device and driver, Frigate's `AddDevice`, and a detector process (that has run an inference, with `live_traffic`) |
| `test_radars.py` | Expected serial ports and no extras, Node-RED's `AddDevice` lines, and the `TM_RADAR_SERIAL_PORT_*` names in `node-red-tm.env` and `config.yml` |
| `test_cameras.py` | CSI sensors, the HEVC decoder's udev symlink and the decoder passed to the running Frigate container, Frigate cameras producing frames, go2rtc streams, and `config.yml` camera entries |
| `test_environmental.py` | Air-quality monitors enabled in `config.yml` and writing recent readings |
| `test_dataflow.py` | `tmdb_migrate.py --check` passes (skipped for code from before #208), no plate reads, and new radar and event rows (with `live_traffic`) |
| `test_disruptive.py` | The stack recovers after a pod restart and after a reboot: units active, and Frigate, Node-RED, nginx, and the control app answering; Frigate follows the HEVC decoder after its `/dev/media` number changes; the home page loads with the pod stopped; the pod starts after its network unit fails once; with the control app stopped, app paths answer 503 with the rescue page; on `pii_free` units with `tm_control_login`, `sudo tm-control reset-admin` sends app paths to `/setup`, and claiming the Pi again with the inventory's login works (`--disruptive` only) |

Some checks need a particular setup. Without it they're skipped, and the summary says why:
- **`pii_free`:** checks that read `config.yml`, `node-red-tm.env`, or `tmdb.sqlite`, that write into the Pi's data folder, that compare the Pi's secrets with what it shows (on the Pi, so no value leaves it), or that reset the control app's accounts.
- **`tm_control_login`:** checks that log in to the control app. They're also skipped, with a message, while the Pi is unclaimed.
- **`live_traffic`:** checks for new radar and event rows, and that the detector has run an inference.
- **The relevant hardware in `tm_expect`:** the radar, camera, and environmental checks.

Each run is logged as `summary.md` and `results.jsonl`. Their code is what the last deploy to that host put on the Pi (with several hosts, the summary lists each one's last deploy), which can be another checkout (see [Testing another branch](#testing-another-branch)). `tmdev.py test` turns off pytest's cache, because its entries would name the host inside the repo.

The tests run only when `TM_DEV_HOSTS` names the hosts. `tmdev.py test` sets it; if you run pytest yourself, set it. Otherwise every device test is skipped, so running the repo's other tests never touches a Pi. If it's set but the inventory is missing, pytest stops with an error instead of skipping.

Before any test runs, each host is checked once for an SSH connection and passwordless sudo. If either is missing, that host's tests fail right away with the reason.

## The run log

The log lives on your machine, outside the repo, at `~/.local/state/traffic-monitor/dev-tests/` by default. It follows `$XDG_STATE_HOME` if you set that, and `TM_DEV_LOG_DIR` overrides it. Run `tmdev.py log --path` to print the exact location.

Every message, `summary.md`, and `checklist.md` gives the full path of its run directory. The `runs/...` links in `LOG.md` are relative to the log directory.

```text
~/.local/state/traffic-monitor/dev-tests/
  LOG.md          one row per deploy, check, or test run, newest last
  runs.jsonl      the same rows as JSON lines
  runs/<UTC time>-<kind>-<host>[-pr<N>]/
    meta.json     host, code under test (branch, commit, uncommitted files), tools if they differ, arguments, result
    tmsetup.log   deploys (on-Pi deploys also keep rsync.log)
    summary.md    device-test runs, with results.jsonl
    checklist.md  checks, with commands.log and cmd-NNN.out
  adhoc/<date>/   commands run while no check was open
```

To see how a Pi did:
- **Latest rows:** `tmdev.py log` shows them, and `tmdev.py log --path` prints where the log is.
- **One run:** open the row's directory. Each `summary.md` and `checklist.md` also names the last deploy to that host, so you can tell which code the Pi was running.
