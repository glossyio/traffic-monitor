______________________________________________________________________

## description: How a device installs a new version without anyone at a keyboard: tm-update's two phases, its stages and reason codes, the files it keeps, the contract a later version must honor, restoring by hand, and running an update on a bench device.

# Software update

`tm-update` installs the version it ships with onto the device it runs on. It runs as root with no terminal, and it keeps the old version running while it downloads and builds everything the new one needs. A page in the control app that starts it, and the job that fetches and checks a new version, are planned. This page covers the installer side: what `tm-update` does, what it leaves on a device, and the files a later version must keep reading.

The command is [`script/tm-update`](https://github.com/glossyio/traffic-monitor/blob/main/script/tm-update), and its code is the [`tm_update` package](https://github.com/glossyio/traffic-monitor/tree/main/script/tm_update) beside it. The package imports only Python's standard library, because the device runs it with `/usr/bin/python3 -EP` before anything of the new version is installed. It never opens `tmdb.sqlite`, and it opens the control app's database only read-only, to copy it into the restore point.

`tm-update` doesn't go through `tmsetup.sh`. It runs the same Ansible role itself, from the new version's own tree, with a variables file it writes. The `tmsetup_update_mode` variable switches the role into update mode. The two share one lock, so an install and an update never run at once.

## The commands

| Command                                        | What it does                                                     |
| ---------------------------------------------- | ---------------------------------------------------------------- |
| `tm-update run --contract 1 --handover <file>` | Installs the tree the command lives in.                          |
| `tm-update resume --handover <file>`           | Carries a run on after the device restarted in the middle of it. |

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

| Stage           | What it does                                                    | If it fails, the run ends as                           |
| --------------- | --------------------------------------------------------------- | ------------------------------------------------------ |
| `prepare`       | Downloads and stages the files, and tries the settings changes. | `prepare_failed`, or the code the role's refusal names |
| `images`        | Builds the images and checks the nginx config.                  | `build_failed`                                         |
| `restore_point` | Saves the restore point.                                        | `prepare_failed`                                       |
| `switch`        | Stops the pod and the control app and installs.                 | `switch_failed`                                        |
| `reboot`        | Restarts the device when the installer asks for it.             | `switch_failed`                                        |
| `health`        | Waits for the new version to answer.                            | `health_failed`                                        |
| `cleanup`       | Removes what the update no longer needs.                        | Never fails the run                                    |

An error `tm-update` didn't expect ends the run with the code of the stage it was in. A run that a restart cut off before the switch can't know what it was doing, so `resume` ends it the same way.

## The reason codes

A failed run has a `reason`, always one of these codes and never a sentence. `detail` is a short text `tm-update` made itself, such as a step's name or a pair of numbers, never a line from Ansible, Podman, apt, or pip. The log holds their output.

| Code                       | When                                                                                                                                                                             | What the person does                                                                                                                                                                       |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `busy`                     | Another install or update holds the lock.                                                                                                                                        | Wait for it. This is the one code that isn't in the state file, because that file belongs to the run that holds the lock. `tm-update` writes `busy` to its log and to stderr, and exits 1. |
| `needs_manual_update`      | The manifest is missing, unreadable, or names root as the installing user, or a value in it is unusable.                                                                         | Run the full installer by hand.                                                                                                                                                            |
| `addon_needs_installer`    | The Plate Recognizer add-on is installed.                                                                                                                                        | Run the full installer by hand.                                                                                                                                                            |
| `reboot_pending`           | The device has a restart waiting (`/var/run/reboot-required`).                                                                                                                   | Restart it, then try again.                                                                                                                                                                |
| `low_space`                | Less than 8 GB plus 1.2 times the size of `tmdb.sqlite` is free where the update works, or at the switch, less than 1.2 times that size is free on the code folder's filesystem. | Free space. The detail gives both numbers in MB.                                                                                                                                           |
| `hardware_needs_installer` | An attached Hailo-8L or PCIe Coral has no driver yet, and an update installs none.                                                                                               | Run the full installer by hand.                                                                                                                                                            |
| `no_internet`              | One `HEAD` request to the go2rtc release address got no answer. GitHub's redirect counts as an answer.                                                                           | Connect the device and try again.                                                                                                                                                          |
| `settings_need_attention`  | The dry run of the settings changes failed.                                                                                                                                      | Look at the log.                                                                                                                                                                           |
| `prepare_failed`           | Anything else that fails in `prepare` or `restore_point`, including an unexpected error. Nothing in use has changed.                                                             | Look at the log.                                                                                                                                                                           |
| `build_failed`             | An image doesn't build, or the new nginx config fails its check.                                                                                                                 | Look at the log.                                                                                                                                                                           |
| `switch_failed`            | The stop, the installer, the restart request, or both attempts failed. The services were started again.                                                                          | Look at the log. Restore by hand if the device isn't working.                                                                                                                              |
| `health_failed`            | The new version didn't come up in five minutes. The detail names the first check that didn't pass (`manifest`, `tm-control`, `health endpoint`, or a unit).                      | Look at the log. The device stays on the new version.                                                                                                                                      |

The codes down to `build_failed` end the run before anything in use has changed, `low_space` at the switch included, because it is checked before the stop. `switch_failed` and `health_failed` come with the switch, which stops the services.

## The files

The update's files are under `/var/lib/traffic-monitor/`. Paths come from one `Paths` object in the code, whose root a test can move.

| Path                            | What it is                                                                                                                                                                 | Kept                                                           |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `update/lock`                   | The lock `tm-update` and `tmsetup.sh` both take with `flock`.                                                                                                              | Always                                                         |
| `update/state.json`             | The [state file](#the-state-file) (mode 0644).                                                                                                                             | Until the next run replaces it                                 |
| `update/log/<run>.log`          | One run's log (mode 0640, root and the code group).                                                                                                                        | The ten newest                                                 |
| `update/work/<run>/`            | The run's work folder: `vars.json`, `facts.json`, `stage/` (the downloads), `build/` (a folder for each image), `check-venv/`, `reason`, and the installer's restart flag. | Removed after the run has ended                                |
| `update/resume.json`            | The [resume marker](#the-resume-marker).                                                                                                                                   | From just before the switch stops anything, until the run ends |
| `restore/<time>-<commit>/`      | A [restore point](#the-restore-point), named for the UTC time (`YYYYMMDDTHHMMSSZ`) and the first 7 characters of the old commit. Mode 0700, root.                          | The two newest                                                 |
| `src/<commit>/`                 | A version's source tree. The caller makes it.                                                                                                                              | The running version and the one before it                      |
| `venv/ansible-<12 characters>/` | The Ansible environment of a tree, named for the first 12 characters of the SHA-256 of its `script/requirements.lock`.                                                     | The one the running tree's lock names                          |

At the start of every `run`, `tm-update` removes what a run that died left behind: other runs' work folders and any throwaway image tag.

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

| Key                 | Value                                                                                                             |
| ------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `schema`            | `1`.                                                                                                              |
| `run_id`, `channel` | From the hand-over.                                                                                               |
| `from`              | `version` and `commit` of what was installed, from the manifest (both `null` when the manifest couldn't be read). |
| `to`                | `version` (from `update.json`), `commit`, and `tag`.                                                              |
| `stage`             | One of the [stage ids](#the-stages), or `null` before the first.                                                  |
| `stages`            | A list of `{id, started_at, finished_at}`, in UTC.                                                                |
| `result`            | `null` while the run goes on, then `ok` or `failed`.                                                              |
| `reason`, `detail`  | `null` unless the run failed. `reason` is a [code](#the-reason-codes). `detail` is at most 200 characters.        |
| `reboot`            | `null` until the switch finishes, then whether the device was restarted.                                          |
| `boot_id`           | The boot's id just before the restart, which `resume` compares to know the restart has happened.                  |
| `restore_point`     | The restore point's folder, or `null` before it is saved.                                                         |
| `tmdb_backup`       | The migration runner's copy of the traffic database that this update made, or `null` when it made none.           |
| `switch_attempts`   | The number of times the switch has started, at most 2.                                                            |

### The resume marker

`update/resume.json` is `{"contract": 1, "tree": <path>, "handover": <path>}`. `tm-update` writes it just before the switch stops anything and removes it when the run ends, ok or failed. A unit that runs after a restart, which is planned, reads it to know which tree's `tm-update resume` to start and with which hand-over. `resume` takes the lock like `run`, and then:

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

It is built in a folder whose name ends in `.partial` and renamed when it is whole, so a folder with its final name is always complete. The folder, and each restore point in it, is mode 0700 and root's. `restore.json` in a restore point is mode 0600 and lists every copied file with its path, mode, and owner, and for a file that isn't a secret, its size and SHA-256 too. For a secret it records no size and no checksum. It also records the old and new commit, the old tree's folder in `src/` when it is still there (`previous_tree`, which is `null` when the manifest already named the new commit, as it does after a switch that failed late, because that folder is the new tree), the files it found missing, and `tmdb_backup`.

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

   Remove any `state.sqlite-wal` and `state.sqlite-shm` beside `/var/lib/tm-control/state.sqlite`, then run `sudo systemctl daemon-reload`. 3. When `tmdb_backup` isn't `null`, copy that file over `tmdb.sqlite` in Node-RED's `db/` folder, as the code owner (`tmadmin` unless the install chose another). Rows written since the migration are lost. When it is `null`, the runner made no copy, so there is nothing to put back. 4. Run the old tree's installer as the login that installed the device (`installing_user` in the manifest), from the tree `previous_tree` names: `bash script/tmsetup.sh -y -a "e tmsetup_source_commit=<old commit>"`. A tree made with `git archive` has no `.git`, so the commit has to be passed. This is a full install and needs the internet. If `previous_tree` is `null`, make the tree again with `git archive` from the commit under `from` in `restore.json`. 5. The installer starts the services. If it asks for a restart, restart the device.

## Run an update by hand on a bench device

Use this on a bench device only. It runs the real installer, which restarts the pod and the control app and may restart the device, so never run it on a device in the field. Run the commands through `tmdev.py run <host> -- ...` to keep them in the run log (see [Testing on a dev Pi](https://docs.trafficmonitor.ai/dev/development/dev-environment/#testing-on-a-dev-pi)).

1. Put the tree on the device, as `git archive` makes it, as root. The folder is named for the commit, which is where the clean-up looks for it:

   ```
   commit=$(git rev-parse HEAD)
   git archive --format=tar.gz --prefix="$commit/" "$commit" \
     | ssh <pi> 'sudo mkdir -p /var/lib/traffic-monitor/src && sudo tar -xzf - -C /var/lib/traffic-monitor/src'
   ```

1. Write a [hand-over file](#the-hand-over-file) on the device. The work folder, state file, and log are under `/var/lib/traffic-monitor/update/`:

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

   Save it as root, in the update folder (for example `/var/lib/traffic-monitor/update/handover.json`).

1. Start it as a transient service, so that stopping the control app or closing your session doesn't end it:

   ```
   sudo systemd-run --unit=tm-update-bench --collect \
     /var/lib/traffic-monitor/src/<commit>/script/tm-update run --contract 1 \
     --handover /var/lib/traffic-monitor/update/handover.json
   ```

1. Follow it in the state file, which anyone can read, and in the log, which root or the code group can:

   ```
   watch -n 5 cat /var/lib/traffic-monitor/update/state.json
   sudo tail -f /var/lib/traffic-monitor/update/log/20261125T101500Z.log
   ```

1. When the state's `stage` is `reboot`, the device restarts. Nothing starts `resume` for you yet, so after the restart run the same command with `resume --handover ...` in place of `run --contract 1 --handover ...`.

1. The run is over when `result` is `ok` or `failed`. Then run the device tests that check what an update leaves behind: `tmdev.py test <host> -- -k test_update`.

`tm-update` doesn't compare versions or commits: it installs the tree you give it, so the same commit can be installed again.
