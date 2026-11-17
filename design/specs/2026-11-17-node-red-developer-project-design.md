# Node-RED Projects: set up by the installer on developer units, off everywhere else

- **Status:** decisions made 2026-11-17. Nothing here is built yet.
- **Tracking:** #334. Related:
  - #276 and its fix, #333: a project loaded no flows after a branch switch. This design assumes that fix has merged.
  - #101 (closed): the earlier Projects problem, from when `package.json` was a template.
  - [node-red/node-red#2084](https://github.com/node-red/node-red/issues/2084): the Projects welcome window can't be turned off while Projects is on.
- **Scope:** the installer flag, the switch in `settings.js`, the one-time project setup, the notice, and the docs. Not in scope: where the flows live in the repository.
- **Decided by:** the maintainer decided the items marked **(maintainer)**. Items marked **(design call)** were chosen while writing this and are open to change.
- **Checked:** items marked **(tested)** were run on 2026-11-17 against the pinned Node-RED image (5.0.8) in safe mode on a laptop, with a clone of `dev` as the project. Items marked **(source)** were read in Node-RED 5.0.8's code. Nothing here was run on a Pi.

## Why

A contributor who edits flows on a device uses the editor's Projects feature. The project is a clone of this repository in `node-red-tm/data/projects/<name>/`. Four things go wrong today.

1. **Every clone asks where `package.json` is.** Projects looks for it in the clone's top folder, and ours is in `container/node-red-tm/data/`. Node-RED saves the answer on the device, in its `.config.projects.json`, never in the repository, so each new clone asks again. **(source)**
2. **A clone starts on the wrong version.** It checks out the fork's default branch, `main`, which is the last release. On a unit installed from `dev`, the flows are then older than the database schema, the control app, and the image's modules beside them.
3. **A project silently wins over the installer.** While a project is active, Node-RED runs the clone's `flows.json` and ignores `node-red-tm/data/flows.json`, the file the installer updates. A unit with a project keeps its old flows through every later install, and nothing says so. **(tested)**
4. **Every unit shows the Projects welcome window.** Projects is on for all units, so the window comes up each time an admin opens the editor on a unit with no project. "Not right now" isn't remembered, and no setting turns the window off while Projects is on. **(source)**

## Goals

1. One installer flag turns a unit into a developer unit: Projects on, with a project already in place, on the version that was installed, with its files and credential key set. **(maintainer)**
2. The installer sets the project up once and never changes it afterwards. **(maintainer)**
3. Every install run says so when Node-RED is running a project whose flows differ from the installed ones. **(maintainer)**
4. A unit without the flag has Projects off. Nobody who opens the editor there gets the welcome window, and the installer's flows are the ones that run. **(maintainer)**
5. A unit that already uses a project keeps working after the upgrade. **(maintainer)**

Not goals:

- Moving a project forward on later installs.
- Setting up the contributor's fork, git name, or git login. The editor already asks for those.
- A Status page check for "running a project". The install notice is the first step; the check can come later. **(design call)**

What would make this a failure even if it works:

- The installer overwrites, moves, or deletes a contributor's branch or uncommitted work.
- A git address with a login in it reaches the device's files or the install log.
- A field unit ends up running a project's flows without anyone choosing that.

## Design

### 1. The flag, and Projects off by default

- `tmsetup.sh -C dev_mode` sets `tmsetup_bool_dev_mode`, added to `_VALID_CUSTOM_VARS` and `defaults/main.yml` like `mqtt_lan`. **(maintainer: the name)** Node-RED Projects is the only thing the flag turns on today; a later developer-only setting can use the same switch.
- `settings.js` reads the switch from the environment: `projects.enabled` is true only when `TM_NR_PROJECTS` is `1`. With it off and a project still on disk, Node-RED runs `data/flows.json`. With it on, the same files bring the project back. **(tested)**
- `node-red-tm.env` gets a `TM_NR_PROJECTS=` line. The installer writes `1` when the flag is given and otherwise keeps what the file has, so the choice survives later runs and `-f`. This is how `tasks/mqtt_broker.yml` handles the broker login: read the file first, then decide. A unit with no line gets `0`.
- **Units that already use a project keep it.** On the first run with this change, a unit whose `.config.projects.json` names an active project is treated as if the flag were given. **(maintainer)**
- Turning it off again is an edit of the env line and a restart of `node-red-tm.service`. The docs say so. There is no flag for it. **(design call)**
- The flag acts only in a run that includes the `node-red-tm` tag: a full run, or `-t node-red-tm`. In any other run it does nothing, and the docs say so. **(design call)**

### 2. Setting the project up, once

This runs under the `node-red-tm` tag, only when Projects is on for the unit, and only when both are true: `data/projects/` has no `traffic-monitor` folder, and `.config.projects.json` names no active project. Otherwise the installer changes nothing and goes to the notice (section 3).

1. **Read three facts from the checkout the installer runs from**, on the machine running `tmsetup.sh`, as `files/pack-ui-sources.sh` does for the UI sources: the `origin` address, the current branch, and the commit. With no checkout (an unpacked archive), use the upstream address and the tag for `tmsetup_tm_version`. The project is the committed state. Uncommitted edits in the installer's checkout are copied to the device as always but aren't put in the project, and the notice then reports the difference. **(design call)**
2. **Clean the address.** Only an `https://` address is used, with any `user:password@` part removed. Anything else (ssh, a local path) becomes the upstream address, `https://github.com/glossyio/traffic-monitor.git`. The tasks that carry the raw address are `no_log`.
3. **Clone on the device**, as the code owner, into `node-red-tm/data/projects/traffic-monitor`. `git` is already in the installer's packages. It is a full clone, about 70 MB of history and 30 MB of files, so the contributor has every branch to switch to.
4. **Check out the installed commit** on a branch with the installer's branch name, when the clone has that commit. An installer checkout with no branch (a tag, a detached commit) gets the branch `installed-<short commit>`. **(design call)** When the clone doesn't have the commit because it was never pushed, the project stays on the remote's branch of that name, or the default branch, and the run says which commit it started on and why. **(maintainer)**
5. **Check the clone's `package.json`.** `flowFile` and `credentialsFile` must be plain file names. A fallback branch from before the #276 fix has paths there and would load no flows, so the project is then left on disk but not made active, and the run says so. **(design call)**
6. **Write `.config.projects.json`** with the project's entry, and mark it active:

    ```json
    {
        "projects": {
            "traffic-monitor": {
                "credentialSecret": "<NODE_RED_CREDENTIAL_SECRET from node-red-tm.env>",
                "rootPath": "container/node-red-tm/data/"
            }
        },
        "activeProject": "traffic-monitor"
    }
    ```

    This is the file Node-RED writes itself after a contributor clones by hand and chooses the package file. Node-RED started from a file written this way, found the project, and loaded all 738 nodes. **(tested)** If the file exists with other content, the entry is merged in and the rest is kept.
7. **Restart `node-red-tm.service`** through the existing handler.

A failed clone (no internet, a private fork) must not fail the install. The run reports it and leaves no half-made folder, and the unit runs the installed flows until the next run tries again.

The steps on the device are one helper script rather than a row of Ansible tasks, so the tests can run it against a throwaway git repository on any machine. **(design call; the builder may choose otherwise)**

### 3. The notice

On every run under the `node-red-tm` tag, after the files are copied, when Projects is on and a project is active:

- Compare the project's `flows.json` and `package.json`, as files on disk with uncommitted edits included, with the installed copies in `node-red-tm/data/`. Comparing content rather than commits gives a true answer for an unpushed commit, an archive install, and uncommitted work alike. **(design call)**
- When they differ, the run ends with a notice beside the setup-code notice in `tasks/main.yml`:

    ```text
    Node-RED on this device runs the project "traffic-monitor" (branch my-feature at 1a2b3c4),
    not the flows this install copied. The installer never changes a project.
    Differs: flows.json, package.json.
    To run the installed flows, switch the project to the installed version in the editor.
    ```

    A `package.json` difference adds one line: the image's modules come from the installed copy, so a module the project adds needs an image rebuild.
- When a project folder exists but Projects is off, one line says the project is there and how to turn Projects on.
- The notice holds no address and no secret. Branch names and short commits are fine in the log.

### 4. The editor's windows

| Window | Where it is handled |
|---|---|
| Update-notification question | #333: `telemetry` is off in `settings.js`. |
| Welcome tour | Already off: `editorTheme.tours` is `false` in `settings.js`. |
| Projects welcome | Here. Not shown on an ordinary unit because Projects is off, and not shown on a developer unit because a project is active. |

### 5. Docs and tests

- `docs/development/dev-environment.md`: the device steps become "install with `-C dev_mode`, then open the editor". The project's `origin` is the address the installer's checkout came from, so the page says to add a fork as a second remote when that isn't the contributor's own. Cloning by hand stays as a short collapsed note. `docs/reference/tmsetup.md` lists the flag.
- `CLAUDE.md`: the flag, the env line, and "an active project wins over the installed flows".
- Off-device tests:
  - the helper against a throwaway repository: first run, a second run that changes nothing, a commit that isn't on the remote, an address with a login, a failed clone
  - `settings.js` with and without `TM_NR_PROJECTS`
  - the env line's three cases: the flag, an existing `1`, neither
  - the notice's text has no address
- Device test, on a bench Pi with the flag: the project folder is at the installed commit, `.config.projects.json` names it, and Node-RED's internal status answers. The editor itself is a manual check.

### Size and upkeep

Medium: about 100 lines of Ansible and helper, one line in `settings.js`, and the tests and docs. What stays to maintain:

- The shape of `.config.projects.json`. Node-RED doesn't document it, so a Node-RED upgrade needs the device test re-run.
- One more thing a `-C` flag does, and one more env line.

## Alternatives considered

- **Copy the project from the installer's own checkout** (a git bundle sent to the device) instead of cloning from GitHub. It is always the exact installed commit, even an unpushed one, and needs no internet. Dropped for now: it sends 70 MB over SSH on remote installs, needs a case for shallow or missing checkouts, and the clone has one branch until the contributor fetches. Worth another look if "commit not on the remote" turns out to be common.
- **A `package.json` in the repository's top folder**, so a hand-made clone needs no choice. Dropped: modules added in the editor would land in that file, not the one the image builds from.
- **Keep Projects on everywhere and only add the setup.** Dropped: the welcome window stays on every ordinary unit, and a project made by accident on a field unit would freeze its flows.
- **Move the project forward on later installs when it is untouched.** Dropped by the maintainer: set it up once, then only tell.
- **Flows in their own repository or a submodule.** Dropped: flows, schema, control app, and their tests could no longer change in one pull request.
