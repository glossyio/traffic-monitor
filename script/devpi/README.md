# Dev-Pi tools

`tmdev.py` deploys this checkout to development Raspberry Pis over SSH and runs commands on them. It also records PR checks. Everything it does is written to a run log on your machine, so you can see later what ran on which Pi, from which code, and how it went.

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

3. Give each Pi a `tmdev` login. It logs in with that key only (it has no password) and runs `sudo` without a password. `tmsetup.sh` needs root but can't type a password over SSH, and Raspberry Pi OS 6.2 and later asks for one by default. Your own account doesn't change and keeps its sudo password.

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

   Then check from your machine. This also accepts the Pi's host key, so do it before the first deploy. Deploys and `run` won't accept a new host key on their own:

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

   Set `tm_expect.pii_free: true` only for a unit that has never recorded real-world data and never had plate recognition enabled. That flag allows checks that read `config.yml` and `tmdb.sqlite`. Images, video clips, and secrets are never read.

   To test what `tmsetup.sh` does when sudo asks for a password, add a second entry for the same Pi that logs in as your own account. Use another name, such as `tm-dev-01-owner`.

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
.venv/bin/python script/devpi/tmdev.py run local -- .venv/bin/python -m pytest container/node-red-tm/schema/tests
```

`run` behaves like `ssh`: the command goes to the Pi's shell. With the host `local`, it runs on your machine instead.

Each command's output is shown and also saved as `cmd-NNN.out`. A line in `commands.log` records the command, the time, and the exit code. The files go into the open PR check, or into `adhoc/<date>/` when no check is open. `tmdev.py` exits with the command's exit code.

Output and logged commands have values that look like secrets replaced with `<redacted>`. That covers `KEY=value` and `"key": value` pairs whose key contains `pass`, `secret`, `token`, or `key`. It's a safety net, not a filter, so don't print secrets on purpose.

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

## The run log

The log lives on your machine, outside the repo, at `~/.local/state/traffic-monitor/dev-tests/` by default. It follows `$XDG_STATE_HOME` if you set that, and `TM_DEV_LOG_DIR` overrides it. Run `tmdev.py log --path` to print the exact location.

Every message and `checklist.md` gives the full path of its run directory. The `runs/...` links in `LOG.md` are relative to the log directory.

```text
~/.local/state/traffic-monitor/dev-tests/
  LOG.md          one row per deploy, check, or test run, newest last
  runs.jsonl      the same rows as JSON lines
  runs/<UTC time>-<kind>-<host>[-pr<N>]/
    meta.json     host, code under test (branch, commit, uncommitted files), tools if they differ, arguments, result
    tmsetup.log   deploys (on-Pi deploys also keep rsync.log)
    checklist.md  checks, with commands.log and cmd-NNN.out
  adhoc/<date>/   commands run while no check was open
```

To see how a Pi did:
- **Latest rows:** `tmdev.py log` shows them, and `tmdev.py log --path` prints where the log is.
- **One run:** open the row's directory. Each `checklist.md` also names the last deploy to that host, so you can tell which code the Pi was running.
