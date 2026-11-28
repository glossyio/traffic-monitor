______________________________________________________________________

## description: How a device installs a new version without anyone at a keyboard: the update job that fetches and checks a version, tm-update's two phases, the stages and reason codes, the files and units involved, the contract a later version must honor, restoring by hand, and running an update on a bench device.

# Software update

`tm-update` installs the version it ships with onto the device it runs on. It runs as root with no terminal, and it keeps the old version running while it downloads and builds everything the new one needs. An administrator starts an update from the **Software update** page of the control app. The page asks GitHub what a channel offers, and when the administrator confirms, the control app starts the update job, a small root program that fetches that version, checks it, and hands over to the version's own `tm-update`. This page covers the whole chain: the job, what `tm-update` does, what both leave on a device, and the files a later version must keep reading. The page and the API behind it are described in [tm-control](https://docs.trafficmonitor.ai/dev/development/tm-control/#the-update-module).

The command is [`script/tm-update`](https://github.com/glossyio/traffic-monitor/blob/main/script/tm-update), and its code is the [`tm_update` package](https://github.com/glossyio/traffic-monitor/tree/main/script/tm_update) beside it. The package imports only Python's standard library, because the device runs it with `/usr/bin/python3 -EP` before anything of the new version is installed. It never opens `tmdb.sqlite`, and it opens the control app's database only read-only, to copy it into the restore point.

`tm-update` doesn't go through `tmsetup.sh`. It runs the same Ansible role itself, from the new version's own tree, with a variables file it writes. The `tmsetup_update_mode` variable switches the role into update mode. The two share one lock, so an install and an update never run at once.

## The update job

The job is [`tm-control/jobs/tm-job-update`](https://github.com/glossyio/traffic-monitor/blob/main/tm-control/jobs/tm-job-update). It runs as root, as the unit `tm-job-update.service`, on the system's Python (`/usr/bin/python3 -EP`), because an update rewrites the control app's virtual environment while it runs. It imports only Python's standard library and nothing from the control app or from `tm-update`, so the job stays the release that installed it until an update replaces it. Every outside command is an argument list, never a shell string, and each step prints one plain line. The text git prints goes to the journal, and no rule reads it.

### What starts it

The control app starts the job when an administrator confirms an update, after it writes the request `/run/tm-control/jobs/update.json`. The control app runs as the code owner, so the job treats the request as hostile, as every job does: the jobs folder must be the code owner's and writable by no one else, the request a small plain file of the code owner's with one link, opened without following a symlink, and it is deleted once read. The request holds exactly four keys:

| Key       | Value                                                        |
| --------- | ------------------------------------------------------------ |
| `run_id`  | A UTC time, `YYYYMMDDTHHMMSSZ`, which the control app makes. |
| `channel` | `stable` or `development`.                                   |
| `commit`  | The full 40-character commit id of the version to install.   |
| `tag`     | A release tag such as `v0.8.1`, or `null`.                   |

The request never names an address or a ref. The one place the job fetches from is `https://github.com/<repo>.git`, where `<repo>` is `update.repo` in the manifest (`owner/name`, the rule the installer, `tm-update`, the control app, and the job all share). Everything the request says is checked against what the job fetched itself.

### The checks, in order

Each refusal ends the run `failed` with a [reason code](#the-reason-codes) and exits 1, except the first three, which write no state file.

| Step | What the job does                                                                                                                                                                                                             | If it refuses                                                                                                                                                                                                                                                                                             |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | Reads the manifest's code owner and the request.                                                                                                                                                                              | Prints one line and exits 64.                                                                                                                                                                                                                                                                             |
| 2    | Looks for a [resume marker](#a-run-that-was-cut-off-comes-first).                                                                                                                                                             | Not a refusal: the job becomes the launcher and finishes that run first.                                                                                                                                                                                                                                  |
| 3    | Takes the run lock that `tm-update` and `tmsetup.sh` take.                                                                                                                                                                    | Prints `busy` and exits 75.                                                                                                                                                                                                                                                                               |
| 4    | Reads the rest of the manifest, each value type-checked, then starts this run's state file.                                                                                                                                   | `needs_manual_update`. The state file is started anyway, with `version` and `commit` under `from` both `null`, because the manifest couldn't be read.                                                                                                                                                     |
| 5    | Stage `fetch`: fetches into [the mirror](#the-mirror).                                                                                                                                                                        | `fetch_failed`, or `prepare_failed` when the mirror can't be made.                                                                                                                                                                                                                                        |
| 6    | Stage `verify`: the commit is in the mirror, on the channel's branch, and for `stable` a `vX.Y.Z` tag names it; `development` takes no tag.                                                                                   | `stale_check`.                                                                                                                                                                                                                                                                                            |
| 7    | Forward only. When the mirror holds the installed commit, it must be an ancestor of the target and not the target. When it doesn't (or the manifest says `unknown`), `stable` compares versions and `development` is refused. | `not_forward`. The same commit again is allowed only after [a failed run that `tm-update` ran for](#running-the-same-version-again).                                                                                                                                                                      |
| 8    | Reads the tree's own `script/tm-update` and `script/update.json` from the mirror.                                                                                                                                             | `target_not_updatable` for no `script/tm-update`, no readable `update.json`, or on `stable` a version that isn't the tag's. `needs_manual_update` for a tree that [doesn't accept contract 1](#how-a-release-says-it-cant-be-installed-this-way). Keys of `update.json` the job doesn't read are ignored. |
| 9    | Opens `tmdb.sqlite` and the control app's `state.sqlite` read-only. Neither may be newer than the tree knows (`tmdb_schema` and `state_schema` in its `update.json`).                                                         | `schema_newer`.                                                                                                                                                                                                                                                                                           |
| 10   | Unpacks the tree into `src/<commit>.partial`, renames it, and writes the [hand-over](#the-hand-over-file) in a fresh `work/<run_id>/`.                                                                                        | `prepare_failed`, or `target_not_updatable` when the tree has no runnable `script/tm-update`.                                                                                                                                                                                                             |
| 11   | Lets go of the lock and becomes the tree's `script/tm-update run --contract 1 --handover <file>`.                                                                                                                             | Its exit status is the unit's from then on.                                                                                                                                                                                                                                                               |

An error the job didn't expect ends the run `prepare_failed`. Before step 10 nothing on the device changes but the mirror and the state file, and nothing in use changes before the switch.

The job's exit statuses stand beside `tm-update`'s 0, 1, and 2:

| Status  | Meaning                                                                                                                                                                                                                                                                         |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0, 1, 2 | `tm-update`'s, once the job has handed over; or 1 when the job's own check refused. 0 and 2 are also the launcher's, when a marker came first.                                                                                                                                  |
| 1       | Also, with no state written for the run: the launcher couldn't be started, the lock file or the state file couldn't be made or written, or `tm-update` couldn't be started after the job let go of the lock and another run then held it. The job prints one line saying which. |
| 64      | No usable request or manifest owner. The job writes none of its files.                                                                                                                                                                                                          |
| 75      | Another install or update holds the lock. The job writes none of its files.                                                                                                                                                                                                     |

For 64 and 75 the unit still runs its `ExecStopPost` commands as it ends, so it stops `tm-update.slice` (see [the units](#the-units)). That matters only for a run started by hand, which [the page can't see](#run-an-update-by-hand-on-a-bench-device).

The limits are 3600 seconds for the fetch, 120 for any other git command, and 600 for the unpack. A first full fetch of the repository, about 82 MB today, needs roughly 0.18 Mbit/s to finish inside its hour, so a slower connection never completes the first update. git also gives up on a transfer that stays under 1 kB/s for a minute.

### The mirror

The mirror is a bare repository, `/var/lib/traffic-monitor/src/repo.git`, that holds `main`, `dev`, and the `v*` tags of the one repository. It is root's, and only the job touches it, under the run lock. The job gives git no configuration but the mirror's own and asks nothing: it speaks only https, follows no redirect, checks every object it receives (`transfer.fsckObjects`), and never runs a hook.

Before each fetch the job tidies the mirror, because each of these makes git fail every later fetch:

- the lock files a killed fetch leaves (`packed-refs.lock`, `HEAD.lock`, `config.lock`, `shallow.lock`, and `refs/**/*.lock`);
- a file under `refs/` that doesn't hold exactly one commit id (40 lowercase hex characters and a newline), as a power cut just after a fetch can leave one empty; the fetch makes the ref again;
- the `tmp_pack_*` files in `objects/pack/` that a fetch that failed part-way leaves, which would otherwise stay and take space.

It is safe to do so, because the run lock means no other fetch is running. git also reads the mirror as bare (`core.bare=true`) whatever its `config` says, so an empty `config` doesn't stop a fetch either.

The trees the job unpacks, `src/<commit>/`, are root's too. `tm-update` installs from one, and the [clean-up](#the-clean-up) keeps the running version's and the one before it.

### A run that was cut off comes first

`tm-update` writes the [resume marker](#the-resume-marker) just before the switch stops anything, and removes it when the run ends. A marker the job finds means a run that a restart, a power cut, or a stop cut off. The job then does not start the request's run. It becomes the launcher, `tm-update-resume`, and finishes the cut-off run first, whatever the request names. The page shows that run as cut off and offers **Finish the update**.

### Running the same version again

`tm-update` doesn't compare versions or commits, but the job does, and it normally refuses the commit that is installed. It allows the same commit again only when the last state file names that commit as its target, the run ended `failed` or has no result (it was cut off), and its `stages` include one other than `fetch` and `verify`, which shows that `tm-update` ran for it. That is the case after a switch that failed late, which leaves the manifest naming the new commit. The job's own refusals write a state file too, and they never make a repeat allowed.

This has a cost. If a late switch failure is followed by a retry that fails at `fetch`, for example because the device is offline, the new state file holds only `fetch`, and the next try ends `not_forward`. Wait for the next version, or use the installer.

### How a release says it can't be installed this way

A tree's `script/update.json` lists the hand-over contracts it accepts. A release that must not be installed by an update, because it needs steps only a person at the installer can take, leaves `1` out of `contracts`. The job reads that from the mirror before it unpacks anything, ends the run `needs_manual_update`, and the page says to use the installer. A tree with no `script/tm-update` or no readable `update.json`, as every release before this one, is `target_not_updatable`, with the same advice.

## The units

Two units start the chain, both made by the installer's control app tag, and both stop the update's `tm-update.slice` when they end, so no build goes on without the run that started it (except after a kill of the whole unit, as the warning below says). Neither is in that slice themselves.

`tm-job-update.service` is static, so it is never enabled and runs only when it is started. The polkit rule lets the control app start it and nothing else: it is in `start_only_units`, not in the `units` that the control app may stop and restart, because stopping the job in the middle of a switch would leave a device half installed. It is a oneshot with `TimeoutStartSec=6h`, because a slow card builds images for hours, and no start limit. When it ends, by its own exit, a stop, a crash, or a kill of its main process, its `ExecStopPost` commands stop the slice and start `tm-update-resume.service`, which does nothing without a marker.

A kill of the whole unit

`systemctl kill --signal=KILL tm-job-update.service` kills every process in the unit's control group, and that ends the `ExecStopPost` commands too. Then neither the slice stop nor the resume start runs. A switch cut off that way waits for the next boot, or for `sudo systemctl start tm-update-resume.service`, which carries it on at once. To stop the job by hand, use `sudo systemctl stop tm-job-update.service`.

`tm-update-resume.service` is enabled, so it starts at boot, after the apps' units but without requiring them: an app that won't start is what a switch has to deal with. It runs only when `resume.json` exists (`ConditionPathExists`), has `TimeoutStartSec=3h`, and never starts itself again. It runs [`tm-update-resume`](https://github.com/glossyio/traffic-monitor/blob/main/tm-control/jobs/tm-update-resume), the launcher, on the system's Python.

The launcher reads the marker and uses it only when it is usable: the contract is the number 1, the tree is exactly `/var/lib/traffic-monitor/src/<40-hex commit>` and holds `script/tm-update`, and the hand-over is a file under `/var/lib/traffic-monitor/update/work/`. A usable marker makes the launcher become that tree's `tm-update resume --handover <file>`, whose exit status is the unit's. Any other marker is renamed to `resume.json.unusable` (an older one is replaced), the control app, the pod, and the revproxy are started again, and the exit status is 2. The launcher never prints the marker. With no marker it prints one line and exits 0.

While either unit is active, the installer stops at its first step and says that an update from the control app is running, because two installers would undo each other. A run from another computer connects first and is stopped by the role's first task; a local run is stopped even earlier, by the run lock. An update's own run of the installer isn't refused.

## What Check sends to GitHub

The control app asks GitHub only when an administrator presses **Check for updates**, and no more than once a minute. It sends requests to `api.github.com` over https, to one repository, `update.repo` in the manifest. The address holds that repository's name and, for the comparison, the installed commit's id. The device's public address reaches GitHub as it does with any request. Besides the address, each request carries a `User-Agent` that names the program (`traffic-monitor-update`), the GitHub API version it was written for, and, when it asks again for something GitHub answered before, the `ETag` of that answer, so GitHub can reply that nothing changed. The control app sends no cookie, token, device name, serial number, or location, and it follows no redirect, and it uses no proxy from the environment. An answer over 1 MiB is refused.

Check asks for the channel's newest version (the latest release for `stable`, the `dev` branch for `development`) and how it stands to the installed commit. When GitHub doesn't know the installed commit, for example a tree built by hand, `stable` falls back to comparing versions, and `development` can't tell, so it offers nothing.

The page's check and the job's checks use the same rules, but they look at different copies of the history. GitHub compares the installed commit with any commit it holds, and the job's mirror holds only `main`, `dev`, and the release tags. A device whose installed commit is on none of them, such as one built from a feature branch, can be offered an update that the job then refuses as `not_forward`, or on `stable` judges by version.

## The commands

| Command                                        | What it does                                                                                                    |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `tm-update run --contract 1 --handover <file>` | Installs the tree the command lives in.                                                                         |
| `tm-update resume --handover <file>`           | Carries a run on after the device restarted in the middle of it. At boot, `tm-update-resume.service` starts it. |

Both must run as root. Both read one [hand-over file](#the-hand-over-file) and write one state file and one log. `--contract` names the hand-over contract the caller speaks, and the tree must accept it (see [`update.json`](#updatejson)).

The exit status tells the caller what happened. The state file says why.

| Status | Meaning                                                                                                                           |
| ------ | --------------------------------------------------------------------------------------------------------------------------------- |
| 0      | The run ended `ok`, or it was handed over to a restart, or `resume` found nothing to carry on.                                    |
| 1      | The run ended `failed`, or another install or update holds the lock (`busy`), or the log can't be opened.                         |
| 2      | No usable hand-over, `update.json`, or resume marker; the tree doesn't accept the contract; or the command isn't running as root. |

## The two phases

|                             | Prepare                                   | Switch                                                              |
| --------------------------- | ----------------------------------------- | ------------------------------------------------------------------- |
| Needs the internet          | Yes                                       | No                                                                  |
| Runs while                  | The old version runs                      | The pod and the control app are stopped                             |
| Stages                      | `prepare`, `images`, then `restore_point` | `switch`, `reboot` (only when the installer asks for one), `health` |
| Changes the running version | Nothing                                   | Everything it installs                                              |

After a healthy switch a last stage, `cleanup`, tidies up. It never fails the run.

### What Prepare does

Prepare downloads and builds everything the switch would otherwise fetch, so the switch can run with no internet:

- The apt packages the role installs (`apt-get install --download-only`), from Debian and from backports, into apt's own package cache.
- The go2rtc binary, checked against its SHA-256.
- The Coral model and its labels, checked against their SHA-256, when a Coral is attached.
- The control app's package, as one archive.
- The control app's Python wheels, each checked against the lock's hash. Prepare then installs them into a throwaway virtual environment with no package index, which proves the switch's offline install works.
- A dry run of the new version's `tm-control migrate` against the device's settings files, so a settings change that would fail is found before anything stops.
- Every image from the new tree, built under a throwaway tag (`localhost/<name>:prepare-<first 7 of the commit>`), and a check of the new nginx config with `nginx -t` on the new revproxy image. See [the images](#the-images).
- The restore point, once nothing has refused ([see below](#the-restore-point)).

Prepare keeps its files in the update's work folder, and it leaves the running version alone: no service restarts, no settings change, and no installed file is replaced. It does write outside the work folder in these ways:

- apt's package index is refreshed and its package cache fills.
- The image store gets the throwaway tags, the stage tags, and the build cache.
- The update's systemd slice, `tm-update.slice`, gets low CPU and I/O weights (`CPUWeight=20` and `IOWeight=20`, runtime properties that a restart drops), so the running version keeps up while the images build.
- The nginx check makes a temporary folder in the revproxy's folder under the code folder and removes it afterwards.
- The restore point, the Ansible environment, and the other files in [the table below](#the-files) are made.

### What the switch does

The switch is `setup.yml` with `tmsetup_update_mode=true`, run from the new tree. In update mode the installer:

- keeps the owner, group, folder, installing user, and repository the manifest records, and records the new commit (a tree from `git archive` has no changes, so `git.modified` is false);
- never asks a question, and prints no setup code;
- skips the time zone, the Wi-Fi tasks, the detector driver installs, and every package index refresh or download;
- installs each downloaded file from the stage instead: packages from apt's cache, the go2rtc binary, the Coral files, the control app's package archive, and its wheels (`pip install --no-index`, still checked against the lock's hashes);
- starts the image build units rather than restarting them, so the running version isn't stopped for a build, and each build finds every step in the cache.

The order is: check that the migration runner's copy of the database has room, stop `traffic-monitor.service` and `tm-control.service`, run the installer, and check the installer's restart flag. If the installer wants a restart, the run records the stage `reboot`, restarts the device, and `resume` carries it on. Then the health check runs.

A switch cut off by a restart is run again by `resume`, at most twice in all. A repeated switch skips the database space check (the first one passed, and the runner replaces its copy), and any failure early in it is treated like a failure after the stop.

A failed switch starts the control app, the pod, and the revproxy again before the command exits, and ends as `switch_failed`. The device may then be partly updated. The [restore point](#restoring-by-hand) is how a person gets it back.

### The health check

For up to five minutes, in rounds five seconds apart, `tm-update` waits until all of these hold in the same round:

- the manifest's `git.commit` is the new commit;
- `tm-control.service` is active and started after the switch began, and `GET /api/v1/health` on the control app's loopback port answers 200;
- the pod, Frigate, Node-RED, the revproxy, and go2rtc are active.

A health check that runs after a restart can't know when the switch began, because that was in an earlier boot, so the control app only has to be active. If the check runs out of time, the run ends as `health_failed` and the device stays on the new version. After a healthy check, the newest copy of the traffic database that the migration runner made during the switch is recorded in the state file and the restore point (see [the restore point](#the-restore-point)).

## The stages

`stage` in the state file is the stage the run is in, or was in when it ended. Each stage also gets a row in `stages`, with its start and finish times. A stage that a restart cut off gets a second row when it begins again.

| Stage           | What it does                                                                                                                               | If it fails, the run ends as                                                                                     |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| `fetch`         | The update job fetches the version into [the mirror](#the-mirror). `tm-update` never writes it.                                            | `fetch_failed`                                                                                                   |
| `verify`        | The update job checks the version against the request, the installed one, and the databases, then unpacks it. `tm-update` never writes it. | `stale_check`, `not_forward`, `target_not_updatable`, `needs_manual_update`, `schema_newer`, or `prepare_failed` |
| `prepare`       | Downloads and stages the files, and tries the settings changes.                                                                            | `prepare_failed`, or the code the role's refusal names                                                           |
| `images`        | Builds the images and checks the nginx config.                                                                                             | `build_failed`                                                                                                   |
| `restore_point` | Saves the restore point.                                                                                                                   | `prepare_failed`                                                                                                 |
| `switch`        | Stops the pod and the control app and installs.                                                                                            | `switch_failed`                                                                                                  |
| `reboot`        | Restarts the device when the installer asks for it.                                                                                        | `switch_failed`                                                                                                  |
| `health`        | Waits for the new version to answer.                                                                                                       | `health_failed`                                                                                                  |
| `cleanup`       | Removes what the update no longer needs.                                                                                                   | Never fails the run                                                                                              |

A step that runs out of time ends the run with its stage's code and the detail `timed out after <n> min`. The limits are:

| Step                                                        | Limit       |
| ----------------------------------------------------------- | ----------- |
| Making the Ansible environment, and installing its packages | 15 min each |
| Prepare's playbook run (stage `prepare`)                    | 30 min      |
| The image builds (stage `images`)                           | 2 h         |
| The switch's installer run                                  | 45 min      |

Every outside command runs in a session of its own, so a command that runs out of time is ended with everything it started: its process group gets `TERM`, then `KILL` after 10 seconds. The image builds run in `tm-update.slice`, outside the playbook's process group, so a timeout there stops the slice as well.

An error `tm-update` didn't expect ends the run with the code of the stage it was in. A run that a restart cut off before the switch can't know what it was doing, so `resume` ends it the same way.

## The reason codes

A failed run has a `reason`, always one of these codes and never a sentence. `detail` is a short text `tm-update` made itself, such as a step's name or a pair of numbers, never a line from Ansible, Podman, apt, or pip. The log holds their output.

| Code                       | When                                                                                                                                                                                                                                                            | What the person does                                                                                                                                                                       |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `busy`                     | Another install or update holds the lock.                                                                                                                                                                                                                       | Wait for it. This is the one code that isn't in the state file, because that file belongs to the run that holds the lock. `tm-update` writes `busy` to its log and to stderr, and exits 1. |
| `fetch_failed`             | The job's `git fetch` failed or ran out of its 3600 seconds.                                                                                                                                                                                                    | Connect the device and try again.                                                                                                                                                          |
| `stale_check`              | The commit isn't in the mirror, isn't on the channel's branch, or a release tag doesn't name it.                                                                                                                                                                | Check again.                                                                                                                                                                               |
| `not_forward`              | The version isn't ahead of the installed one, or it is the installed commit and [isn't a repeat the job allows](#running-the-same-version-again).                                                                                                               | Check again.                                                                                                                                                                               |
| `target_not_updatable`     | The version has no `script/tm-update` or no readable `script/update.json`, or on `stable` its version isn't its tag's.                                                                                                                                          | Run the full installer by hand.                                                                                                                                                            |
| `schema_newer`             | `tmdb.sqlite` or the control app's database is newer than the version knows. The detail gives both numbers.                                                                                                                                                     | Install a newer version, or use the installer.                                                                                                                                             |
| `needs_manual_update`      | The manifest is missing, unreadable, or names root as the installing user, or a value in it is unusable, or the version doesn't accept contract 1 (see [how a release says it can't be installed this way](#how-a-release-says-it-cant-be-installed-this-way)). | Run the full installer by hand.                                                                                                                                                            |
| `addon_needs_installer`    | The Plate Recognizer add-on is installed.                                                                                                                                                                                                                       | Run the full installer by hand.                                                                                                                                                            |
| `reboot_pending`           | The device has a restart waiting (`/var/run/reboot-required`).                                                                                                                                                                                                  | Restart it, then try again.                                                                                                                                                                |
| `low_space`                | Less than 8 GB plus 1.2 times the size of `tmdb.sqlite` is free where the update works, or at the switch, less than 1.2 times that size is free on the code folder's filesystem.                                                                                | Free space. The detail gives both numbers in MB.                                                                                                                                           |
| `hardware_needs_installer` | An attached Hailo-8L or PCIe Coral has no driver yet, and an update installs none.                                                                                                                                                                              | Run the full installer by hand.                                                                                                                                                            |
| `no_internet`              | One `HEAD` request to the go2rtc release address got no answer. GitHub's redirect counts as an answer.                                                                                                                                                          | Connect the device and try again.                                                                                                                                                          |
| `settings_need_attention`  | The dry run of the settings changes failed.                                                                                                                                                                                                                     | Look at the log.                                                                                                                                                                           |
| `prepare_failed`           | Anything else that fails in the job or in `prepare` or `restore_point`, including an unexpected error. Nothing in use has changed.                                                                                                                              | Look at the log.                                                                                                                                                                           |
| `build_failed`             | An image doesn't build, or the new nginx config fails its check.                                                                                                                                                                                                | Look at the log.                                                                                                                                                                           |
| `switch_failed`            | The stop, the installer, the restart request, or both attempts failed. The services were started again.                                                                                                                                                         | Look at the log. Restore by hand if the device isn't working.                                                                                                                              |
| `health_failed`            | The new version didn't come up in five minutes. The detail names the first check that didn't pass (`manifest`, `tm-control`, `health endpoint`, or a unit).                                                                                                     | Look at the log. The device stays on the new version.                                                                                                                                      |

The job's five codes, and the codes down to `build_failed`, end the run before anything in use has changed, `low_space` at the switch included, because it is checked before the stop. `switch_failed` and `health_failed` come with the switch, which stops the services.

## The files

The update's files are under `/var/lib/traffic-monitor/`. Paths come from one `Paths` object in the code, whose root a test can move.

| Path                            | What it is                                                                                                                                                                                                       | Kept                                                           |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `update/lock`                   | The lock `tm-update` and `tmsetup.sh` both take with `flock`.                                                                                                                                                    | Always                                                         |
| `update/state.json`             | The [state file](#the-state-file) (mode 0644).                                                                                                                                                                   | Until the next run replaces it                                 |
| `update/log/<run>.log`          | One run's log (mode 0640, root and the code group).                                                                                                                                                              | The ten newest                                                 |
| `update/work/<run>/`            | The run's work folder: `handover.json` when the job made it, `vars.json`, `facts.json`, `stage/` (the downloads), `build/` (a folder for each image), `check-venv/`, `reason`, and the installer's restart flag. | Removed after the run has ended                                |
| `update/resume.json`            | The [resume marker](#the-resume-marker).                                                                                                                                                                         | From just before the switch stops anything, until the run ends |
| `restore/<time>-<commit>/`      | A [restore point](#the-restore-point), named for the UTC time (`YYYYMMDDTHHMMSSZ`) and the first 7 characters of the old commit. Mode 0700, root.                                                                | The two newest                                                 |
| `src/repo.git`                  | [The mirror](#the-mirror).                                                                                                                                                                                       | Always                                                         |
| `src/<commit>/`                 | A version's source tree. The update job makes it, or the caller by hand.                                                                                                                                         | The running version and the one before it                      |
| `venv/ansible-<12 characters>/` | The Ansible environment of a tree, named for the first 12 characters of the SHA-256 of its `script/requirements.lock`.                                                                                           | The one the running tree's lock names                          |

At the start of every `run`, `tm-update` first stops `tm-update.slice`, so a dead run's builds can't go on beside the new one. It then removes what that run left behind: other runs' work folders and any throwaway image tag.

## The contract

A later version of `tm-update` reads the files an earlier version wrote, and an earlier one reads what a later caller writes. These must stay readable. Add keys; don't remove one, rename it, or change what it means. When that can't be done, raise the contract number.

Every value read from one of these files is checked for its type before use: a number, `null`, or a list where text is expected is refused, never turned into text. An error names the key and never quotes the value.

### The hand-over file

The caller writes it, and `--handover` names it. It is JSON, with exactly these keys, all required:

| Key            | Value                                                                                    |
| -------------- | ---------------------------------------------------------------------------------------- |
| `contract`     | The number `1` (not `true`, not `1.0`).                                                  |
| `run_id`       | 1 to 64 letters, digits, `T`, `_`, and `-`. It names the work folder.                    |
| `channel`      | `stable` or `development`. It decides the branch the installer records: `main` or `dev`. |
| `commit`       | The full 40-character commit id of the tree.                                             |
| `tag`          | The release tag, or `null`.                                                              |
| `from_version` | The version that was running, as printable text up to 200 characters.                    |
| `work_dir`     | Exactly `/var/lib/traffic-monitor/update/work/<run_id>`. Any other path is refused.      |
| `state_path`   | Exactly `/var/lib/traffic-monitor/update/state.json`.                                    |
| `log_path`     | Exactly `/var/lib/traffic-monitor/update/log/<run_id>.log`.                              |

The caller owns the hand-over file. When it is kept in the work folder, it is removed with that folder when the run ends ok, and `resume` needs it until then.

### The state file

It is one JSON file that the control app can read while the run goes on. `tm-update` writes it to a temporary file beside it, syncs it, and renames it, so a reader sees the old file or the new one and never half of one. It holds codes and numbers, never a line from another program and never a secret.

| Key                 | Value                                                                                                                                                                                                                                         |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schema`            | `1`.                                                                                                                                                                                                                                          |
| `run_id`, `channel` | From the hand-over.                                                                                                                                                                                                                           |
| `from`              | `version` and `commit` of what was installed, from the manifest. When `tm-update` can't read the manifest, `version` is the hand-over's `from_version` and `commit` is `null`. A run the job refused because of the manifest has both `null`. |
| `to`                | `version` (from `update.json`), `commit`, and `tag`.                                                                                                                                                                                          |
| `stage`             | One of the [stage ids](#the-stages), or `null` before the first.                                                                                                                                                                              |
| `stages`            | A list of `{id, started_at, finished_at}`, in UTC.                                                                                                                                                                                            |
| `result`            | `null` while the run goes on, then `ok` or `failed`.                                                                                                                                                                                          |
| `reason`, `detail`  | `null` unless the run failed. `reason` is a [code](#the-reason-codes). `detail` is at most 200 characters.                                                                                                                                    |
| `reboot`            | `null` until the switch finishes, then whether the device was restarted.                                                                                                                                                                      |
| `boot_id`           | The boot's id just before the restart, which `resume` compares to know the restart has happened.                                                                                                                                              |
| `restore_point`     | The restore point's folder, or `null` before it is saved.                                                                                                                                                                                     |
| `tmdb_backup`       | The migration runner's copy of the traffic database that this update made, or `null` when it made none.                                                                                                                                       |
| `switch_attempts`   | The number of times the switch has started, at most 2.                                                                                                                                                                                        |

### The resume marker

`update/resume.json` is `{"contract": 1, "tree": <path>, "handover": <path>}`. `tm-update` writes it just before the switch stops anything and removes it when the run ends, ok or failed. `tm-update-resume.service` reads it after a restart to know which tree's `tm-update resume` to start and with which hand-over, and the update job reads it to know that a cut-off run comes first (see [the units](#the-units)). `resume` takes the lock like `run`, and then:

- with no marker, it does nothing and exits 0;
- with a marker it can't read, it removes it and exits 2, and with one that names another tree or hand-over, it exits 2 and leaves it for that run;
- with a run that has already ended, it removes the marker and exits 0;
- in the stage `reboot`, while the boot id is still the one recorded, it exits 0 and leaves the marker, because the restart hasn't happened yet;
- otherwise it carries on from `reboot` with the health check, from `switch` with another attempt (a run whose switch already started twice ends as `switch_failed`), from `health` with the check again, and from `cleanup` with the clean-up. A run cut off in an earlier stage ends with that stage's code. When the manifest can't be used, a run cut off in `switch` ends as `switch_failed` with the services started again, one in `reboot` or `health` ends as `health_failed`, and one in `cleanup` still runs the clean-up and ends `ok`.

### update.json

`script/update.json` is in every tree. It lets the caller read what a tree accepts without running it.

| Key            | Value                                                                             |
| -------------- | --------------------------------------------------------------------------------- |
| `contracts`    | The hand-over contracts the tree accepts, such as `[1]`.                          |
| `tm_version`   | The tree's version, which `tm-update` records as `to.version`.                    |
| `tmdb_schema`  | The number of the newest migration in `container/node-red-tm/schema/migrations/`. |
| `state_schema` | The number of the control app's database migrations.                              |

A test holds the last three to the real files, so a migration can't be added without updating this file.

## The images

The update builds every image in `tmsetup_update_images` (`vars/main.yml`): Frigate's, Node-RED's, and the revproxy's. The Plate Recognizer add-on isn't one of them, and a device that has it is refused.

Each builds in its own folder under the work folder, with the files the installer would write into the code folder, and with the same owner, group, and mode. A `COPY` step's cache key reads the owner and group of the files, so with the same owner and group the switch's build units find every step in the cache. The builds run in `tm-update.slice`.

Frigate's `build-ffmpeg` stage and the revproxy's `ui` stage are the first stages of two-stage builds. A first stage has no tag of its own, and `podman image prune` removes it, so the next build would start over (see [what the build cache depends on](https://docs.trafficmonitor.ai/dev/development/dev-environment/#what-the-build-cache-depends-on)). After each build, Prepare tags each first stage `localhost/<name>:stage-<stage>`. A tagged stage survives a prune, and so does everything under it.

Warning

Prepare moves the `stage-*` tags to the new version's stages during Prepare, not at the switch. If an update fails after its builds, the running version's first stages have no tag until the next update ends ok. A `podman image prune` run by hand in that time costs the running version its build cache, and its next build at boot takes minutes and needs the internet.

Danger

`podman untag <name>` with one argument removes every name of that image. To remove one tag, use `podman untag <image id> <full name>`, or `podman rmi <full name>`. `tm-update` always uses one of these.

## The clean-up

The clean-up runs after a healthy switch, and the update is already done by then. A step that fails is logged, with a note such as `step_failed:<name>`, and the next step runs. The steps, in order:

1. Remove the throwaway tags.
1. Remove the tags in the three image repositories that no build unit and no stage rule names. A tag that can't be removed stays, and the log says so (`podman rmi`, never forced).
1. Prune dangling images. The stage tags keep the first stages.
1. Remove base images of earlier versions that nothing uses: the images in the repositories the Containerfiles build `FROM` that no current `FROM` line names. It removes nothing unless it can find every current base.
1. Give the slice its low weights again (a restart drops them), then build each image once more from the staged folders to check that every step still comes from the cache. A miss rebuilds the image then, while the internet is probably there, and not at the next boot. The log notes it as `cache_rebuilt:<name>`.
1. Remove source trees but the running one and the one it replaced (none at all when the manifest already named the new commit before the run, as it does after a switch that failed late, because then it can't tell which tree came before), Ansible environments but the one the tree's lock names, and all but the ten newest run logs. The current run's log counts as one of the ten.

The run's state is then set to `ok`, the resume marker is removed, and last of all the work folder is removed, still under the lock. A restart before that leaves the folder for the next run to clear.

## The restore point

Before the switch, `tm-update` saves what an earlier version needs to be restored:

- the device's settings: Node-RED's and Frigate's `config.yml`, go2rtc's `go2rtc.yaml`, and the polkit rule;
- every `*.env` file in the code folder's component folders, and any `services/*.service` files there;
- the manifest;
- every secret file;
- the Quadlet units in `/etc/containers/systemd/` and the `tm-*` units in `/etc/systemd/system/`;
- a consistent copy of the control app's `state.sqlite`, made with SQLite's backup API, so it is whole while the control app keeps writing.

Making one writes one line to the run's log: its folder's name, the number of files, and the paths it found missing. A restore point is built in a folder whose name ends in `.partial` and renamed when it is whole, so a folder with its final name is always complete. The folder, and each restore point in it, is mode 0700 and root's. `restore.json` in a restore point is mode 0600 and lists every copied file with its path, mode, and owner, and for a file that isn't a secret, its size and SHA-256 too. For a secret it records no size and no checksum. It also records the old and new commit, the old tree's folder in `src/` when it is still there (`previous_tree`, which is `null` when the manifest already named the new commit, as it does after a switch that failed late, because that folder is the new tree), the files it found missing, and `tmdb_backup`.

The reference pictures an administrator kept are not in the restore point either. They are files beside `state.sqlite` (`/var/lib/tm-control/pictures/`), and the restore point holds only the database that lists them. Neither the installer nor an update touches them.

The traffic database, `tmdb.sqlite`, is not in the restore point, because it can be several gigabytes. When the new version has a schema change, the migration runner copies the database to `db/backup/` in Node-RED's folder before it applies the change. After the health check, `tmdb_backup` in the state file and the restore point names the newest copy made since the switch began. It is `null` when none was made.

The two newest restore points are kept. The one just made is always kept, whatever the clock said when it was named.

### Restoring by hand

There is no undo command.

Use the newest restore point, unless its `restore.json` has the same commit under `from` and under `to`. Such a restore point was made by a run that repeated an update whose switch had failed late, so the files it copied may already be partly changed, and it names no previous tree. Use the restore point before it instead: its `from` is the version to go back to.

To put a device back on the version it had, as a person at a shell:

1. Stop the pod, the control app, and the revproxy: `sudo systemctl stop traffic-monitor.service tm-control.service revproxy.service`.

1. Copy the files back. Under the restore point's `files/` folder, each file is at its own path. Copy each one listed in `restore.json` and give it the owner and group the list records. Don't copy the folders over `/`, because that would change the modes of the system's own folders. For example:

   ```
   sudo python3 - <<'EOF'
   import json, os, shutil
   point = "/var/lib/traffic-monitor/restore/<name>"
   for row in json.load(open(point + "/restore.json"))["files"]:
       os.makedirs(os.path.dirname(row["path"]), exist_ok=True)
       shutil.copy2(point + "/files" + row["path"], row["path"])
       os.chown(row["path"], row["uid"], row["gid"])
   EOF
   ```

   Remove any `state.sqlite-wal` and `state.sqlite-shm` beside `/var/lib/tm-control/state.sqlite`, then run `sudo systemctl daemon-reload`.

   The restored `state.sqlite` lists the pictures that were kept when the restore point was made. When the control app starts, it removes every picture folder the restored database doesn't list, so a picture kept since the restore point is deleted, and it drops the row for any listed picture whose files are gone, so a picture deleted since disappears from the Location page. The pictures kept before the restore point stay.

   If you restore a version older than the pictures, that version doesn't know about them. It leaves `/var/lib/tm-control/pictures/` on the card, and nothing lists or removes it until an update brings the pictures back, which then sweeps it as above. To free the space at once, or to remove the pictures for good, delete the folder yourself: `sudo rm -r /var/lib/tm-control/pictures`. 3. When `tmdb_backup` isn't `null`, copy that file over `tmdb.sqlite` in Node-RED's `db/` folder, as the code owner (`tmadmin` unless the install chose another). Rows written since the migration are lost. When it is `null`, the runner made no copy, so there is nothing to put back. 4. Run the old tree's installer as the login that installed the device (`installing_user` in the manifest), from the tree `previous_tree` names: `bash script/tmsetup.sh -y -a "e tmsetup_source_commit=<old commit>"`. A tree made with `git archive` has no `.git`, so the commit has to be passed. This is a full install and needs the internet. If `previous_tree` is `null`, make the tree again with `git archive` from the commit under `from` in `restore.json`. 5. The installer starts the services. If it asks for a restart, restart the device.

## Run an update by hand on a bench device

Use this on a bench device only. It runs the real installer, which restarts the pod and the control app and may restart the device, so never run it on a device in the field. To try the whole chain instead, start the update from the Software update page. These steps skip the update job and run `tm-update` directly, as the job would after its checks. Run the commands through `tmdev.py run <host> -- ...` to keep them in the run log (see [Testing on a dev Pi](https://docs.trafficmonitor.ai/dev/development/dev-environment/#testing-on-a-dev-pi)).

The Software update page can't see a run started by hand

Neither of the two units runs it, so while it goes on the page shows it as stopped (or cut off, once the switch has begun), and offers **Try again** or **Finish the update**. Don't press **Update** or **Try again** while a run started by hand goes on: the job is refused as `busy`, and as its unit ends it stops `tm-update.slice`, which stops that run's image builds.

1. Put the tree on the device, as `git archive` makes it, as root. The folder is named for the commit, which is where the clean-up looks for it:

   ```
   commit=$(git rev-parse HEAD)
   git archive --format=tar.gz --prefix="$commit/" "$commit" \
     | ssh <pi> 'sudo mkdir -p /var/lib/traffic-monitor/src && sudo tar -xzf - -C /var/lib/traffic-monitor/src'
   ```

1. Write a [hand-over file](#the-hand-over-file) on the device, inside the run's own work folder, as the job does. Then the resume marker names a hand-over the launcher accepts, and a restart in the middle of the run is carried on at boot. The work folder, state file, and log are under `/var/lib/traffic-monitor/update/`:

   ```
   {
     "contract": 1,
     "run_id": "20261125T101500Z",
     "channel": "development",
     "commit": "<the 40-character commit id>",
     "tag": null,
     "from_version": "<the version that runs now>",
     "work_dir": "/var/lib/traffic-monitor/update/work/20261125T101500Z",
     "state_path": "/var/lib/traffic-monitor/update/state.json",
     "log_path": "/var/lib/traffic-monitor/update/log/20261125T101500Z.log"
   }
   ```

   Make the work folder (`sudo install -d -m 755 /var/lib/traffic-monitor/update/work/20261125T101500Z`) and save the file in it as root, as `handover.json`.

1. Start it as a transient service, and only that way. Every command `tm-update` runs has a session of its own, so a dropped SSH session would leave Ansible running without the lock, and a second run could start beside it. Under `systemd-run`, stopping the control app or closing your session doesn't end it:

   ```
   sudo systemd-run --unit=tm-update-bench --collect \
     /var/lib/traffic-monitor/src/<commit>/script/tm-update run --contract 1 \
     --handover /var/lib/traffic-monitor/update/work/20261125T101500Z/handover.json
   ```

1. Follow it in the state file, which anyone can read, and in the log, which root or the code group can:

   ```
   watch -n 5 cat /var/lib/traffic-monitor/update/state.json
   sudo tail -f /var/lib/traffic-monitor/update/log/20261125T101500Z.log
   ```

1. When the state's `stage` is `reboot`, the device restarts, and `tm-update-resume.service` carries the run on at boot, because the marker is there. If the hand-over isn't under the work folder, the launcher sets the marker aside as `resume.json.unusable`, and you carry the run on yourself. Put the marker back first, because `resume` with no marker has nothing to carry on, then run the same command with `resume --handover ...` in place of `run --contract 1 --handover ...`:

   ```
   sudo mv /var/lib/traffic-monitor/update/resume.json.unusable /var/lib/traffic-monitor/update/resume.json
   ```

   6. The run is over when `result` is `ok` or `failed`. Then run the device tests that check what an update leaves behind: `tmdev.py test <host> -- -k test_update`.

`tm-update` doesn't compare versions or commits: it installs the tree you give it, so the same commit can be installed again. The update job does compare them; see [Running the same version again](#running-the-same-version-again).
