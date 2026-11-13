# Apps start by themselves after a power loss (#268) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a power loss, Frigate, Node-RED, and the web proxy start by themselves, even when Podman crashes in the boot's first command.

**Architecture:** Each image build unit gets one `ExecStartPre=-` line that runs a harmless Podman command before the build. Whichever Podman command runs first after a boot does Podman's state refresh, and only that command can crash, so the crash lands in a command whose result systemd ignores, never in `podman build`. The network unit, the fourth unit that can be first, already restarts itself. No retries are added to the build units.

**Tech Stack:** Ansible (tmsetup role), Podman 5.4.2 Quadlet and systemd 257 on Raspberry Pi OS Trixie, pytest, pytest-testinfra (`script/devpi`).

**Spec:** GitHub issue #268. The design was settled on 2026-11-11 from these facts, each checked in Podman's source or on a bench Pi:

- **The bug is Podman's, fixed in 5.6.0.** Upstream issue 26469, fix commit `e4c810a8f1` ("fix panic on state refresh"). Trixie and trixie-backports carry only 5.4.2; testing has 5.8.6.
- **The mechanism (Podman 5.4.2 source).** The first Podman command of a boot finds no `alive` file under `/run/libpod` and runs `Runtime.refresh()` (`libpod/runtime.go`). After an unclean shutdown the lost boot's containers are still in Podman's state. Quadlet starts them with `--rm`, so the refresh removes them. Removing a container in a pod with `--exit-policy=stop` (Quadlet's pods) queues a pod stop on the runtime's work queue. The queue's worker starts at the end of runtime setup. The pod stop calls `parallel.Enqueue()`, which uses a semaphore that `cmd/podman/root.go` creates only later, after the engines are set up. When the worker gets there first, Podman dereferences nil and exits with status 2.
- **Only the command that does the refresh can crash,** and by then the refresh is complete: the `alive` file is written inside `refresh()`, before the worker starts. A later command never refreshes again. On the bench, the commands after a crash ran normally and `podman pod create --replace` removed the left-over pod.
- **A clean reboot can't trigger it:** stopped `--rm` containers are already gone, so nothing queues a pod stop.
- **Four units start together at boot** and race for the refresh: `frigate-tm-build`, `node-red-tm-build`, `revproxy-build`, and `tmnet-network` (plus `plate-recognizer-tm-build` when installed). On a bench Pi's journal, a build unit did the refresh in 19 of 26 boots.
- **Why an app stays down.** The build units are `Type=oneshot` with `Restart=no`, and each container unit `Requires=` its build unit. A crashed build fails the container's start job ("Dependency failed"), and `Restart=` doesn't apply to a failed dependency. `tmnet-network` has Quadlet's `Restart=on-failure`, and the pod only `Wants=` it: on a bench Pi it took this same panic on 2026-11-07 and everything came up a second later.
- **Retries on the build units were tried and dropped.** `Restart=on-failure` alone doesn't help: the container still fails on the dependency. With `RestartMode=direct` the container does wait, but a build that keeps failing then retries forever, and `systemctl start` on the container blocks (measured with throwaway units: 7 restarts in 40 s, still activating). The installer would hang on a broken Containerfile instead of failing. A start limit can't bound it either, because a build unit runs again on every start of its container (`RemainAfterExit=no`), so any limit tight enough to stop a broken build also cuts Frigate's and nginx's own restart loops.
- **`ExecStartPre=-` semantics.** With the `-` prefix, systemd ignores a non-zero exit and a kill by signal, then runs `ExecStart=`. Quadlet passes a `.build` file's `[Service]` lines through (dry run on Quadlet 5.7.0: the line appears above the generated `ExecStart=/usr/bin/podman build`).
- **The command.** `/usr/bin/podman network exists podman`: every Podman command except `help`, `completion`, and parent commands sets up the runtime, so it does the refresh. It reads only, prints nothing, and exits 0 because Podman's default network `podman` always exists. Checked as root on a bench Pi's 5.4.2: exit 0, no output.
- **Journal fields.** Podman's refresh event is a journal entry with `PODMAN_EVENT=refresh`, `_CMDLINE` (the Podman command), `_SYSTEMD_UNIT`, and `_PID`. A container removal is `PODMAN_EVENT=remove`.

## Global Constraints

- The line, in every `container/*/*.build.j2`: `ExecStartPre=-{{ tmsetup_podman_refresh_command }}`, rendered `ExecStartPre=-/usr/bin/podman network exists podman`.
- No `Restart=`, `RestartMode=`, `RestartSec=`, or `StartLimit*` in a build unit, and no new unit.
- Work in the worktree `~/code/tm-build-refresh`, branch `bugfix/podman-refresh-crash/268`, based on `origin/dev`. Another session uses the main checkout. The dev venv is `~/code/traffic-monitor/.venv`; run its `python` from the worktree's root.
- Conventions: task names `TMSetup - <Component> - <Action>`, 2-space YAML, Python indented with 4 spaces with a module docstring, test module basenames unique across the repo, no AI-provenance comments.
- Bench Pis are shared with another session. Ask the maintainer which Pi is free before a deploy, a reset, or a reboot, and say that the deploy puts `dev` plus this fix on it. Deploy to one host at a time and check the address in the PLAY RECAP.
- Never put device names or addresses in commits or PR text. Nothing here reads `config.yml` or `tmdb.sqlite`.
- Commits: one per task, local only, ending with CLAUDE.md's trailer block (`Assisted-by`, `AI-Model`, `AI-Effort`, `AI-Role`), not `Co-Authored-By`. Ask for the interface and effort level. No push and no PR until Task 3's check has passed and the maintainer has read the commit messages and the PR text. Say `PUBLIC push → glossyio/traffic-monitor (<branch / PR>)` before any remote write.
- The PR targets `dev`. `Closes #268` won't fire on a merge into `dev`, so the issue is closed by hand.

## Review Focus

1. **A new service's build unit without the line.** A copy of an older service would bring back the bug for that app only. Task 1's tests glob every `container/*/*.build.j2`, so a new build unit without the line fails.
2. **The throwaway command doesn't do the refresh.** Then a build still does it. Task 2's read-only device test fails on any boot whose refresh came from `podman build`; Task 3 runs it after every reset.
3. **The reset test isn't unclean.** If the reset left no containers behind, it proves nothing. Task 2's test asserts that the refresh's process removed containers.
4. **The reset test hangs on a dead SSH connection.** The Pi resets without closing it. Task 2 schedules the reset through PID 1 so the command returns first; Task 3 times the first run.
5. **A real crash.** The race can't be forced, so no test makes Podman panic. The tests prove that no build can be the command that crashes. Task 3 records whether a panic happened during its resets and, if one did, that every app still came up.

---

### Task 1: The line in every build unit

**Files:**
- Modify: `script/ansible/roles/tmsetup/vars/main.yml` (after `tmsetup_hevc_device`)
- Modify: `container/frigate/frigate-tm.build.j2`, `container/node-red-tm/node-red-tm.build.j2`, `container/revproxy/revproxy.build.j2`, `container/plate-recognizer/plate-recognizer-tm.build.j2`
- Create: `script/tests/test_build_units.py`
- Modify: `CLAUDE.md` (the `<svc>.build.j2` bullet under "Each `container/<svc>/` follows one pattern")

**Interfaces:**
- Produces: `tmsetup_podman_refresh_command: /usr/bin/podman network exists podman` in `vars/main.yml`, read by the four templates and by Task 2's device tests through `role_vars()`.

- [ ] **Step 1: Write the failing tests**

Create `script/tests/test_build_units.py`:

```python
"""Each image build unit first runs a throwaway Podman command, which takes the boot's state refresh (#268)."""

import subprocess
from pathlib import Path

import pytest
from tmsetup_render import REPO, load_role_yaml, render

REFRESH = "/usr/bin/podman network exists podman"
BUILD_UNITS = sorted(path.relative_to(REPO).as_posix() for path in (REPO / "container").glob("*/*.build.j2"))
QUADLET = next((p for p in ("/usr/libexec/podman/quadlet", "/usr/lib/podman/quadlet") if Path(p).exists()), None)


def build_unit(template):
    return render(template, **dict(load_role_yaml("vars/main.yml"), tmsetup_codedir="/opt/traffic-monitor"))


def service_lines(text):
    """The [Service] section's lines, without comments and blank lines."""


def test_the_glob_finds_the_build_units():
    assert {Path(template).name for template in BUILD_UNITS} >= {
        "frigate-tm.build.j2", "node-red-tm.build.j2", "revproxy.build.j2", "plate-recognizer-tm.build.j2"}


def test_refresh_command_is_fixed_in_vars():
    assert load_role_yaml("vars/main.yml")["tmsetup_podman_refresh_command"] == REFRESH


@pytest.mark.parametrize("template", BUILD_UNITS)
def test_build_unit_runs_the_throwaway_command_first_and_nothing_else(template):
    """Only this line: a build unit that restarts itself blocks its container's start, and the installer,
    for as long as the build keeps failing."""
    assert service_lines(build_unit(template)) == [f"ExecStartPre=-{REFRESH}"]


def test_quadlet_keeps_the_line_in_every_build_service(tmp_path):
    if QUADLET is None:
        pytest.skip("no Quadlet generator on this machine (install podman)")
    for template in BUILD_UNITS:
        (tmp_path / Path(template).name.removesuffix(".j2")).write_text(build_unit(template))
    result = subprocess.run([QUADLET, "-dryrun"], env={"QUADLET_UNIT_DIRS": str(tmp_path), "PATH": "/usr/bin:/bin"},
                            capture_output=True, text=True)
    services = result.stdout.split("---")[1:]  # name, body, name, body, ...
    bodies = dict(zip(services[::2], services[1::2]))
    assert len(bodies) == len(BUILD_UNITS), result.stderr
    for name, body in bodies.items():
        lines = body.splitlines()
        assert f"ExecStartPre=-{REFRESH}" in lines, name
        assert [line for line in lines if line.startswith("ExecStart=/usr/bin/podman build ")], name
```

`service_lines(text)` returns the lines between `[Service]` and the next section header or the end, dropping lines that are blank or start with `#`; a unit without `[Service]` gives `[]`.

- [ ] **Step 2: Run them to see them fail**

Run: `~/code/traffic-monitor/.venv/bin/python -m pytest script/tests/test_build_units.py -q`
Expected: `test_the_glob_finds_the_build_units` passes; `test_refresh_command_is_fixed_in_vars` fails with `KeyError`; the four parametrized tests fail with `[] == ['ExecStartPre=-…']`; the Quadlet test fails on the missing line (or skips without Podman).

- [ ] **Step 3: Add the variable**

In `vars/main.yml`, after `tmsetup_hevc_device`:

```yaml
# A harmless Podman command the image build units run first (ExecStartPre=-). After an unclean shutdown the boot's
# first Podman command clears the lost boot's containers, and Podman 5.4.2 can crash while it does (#268; fixed in
# Podman 5.6.0). This command takes that crash instead of the build.
tmsetup_podman_refresh_command: /usr/bin/podman network exists podman
```

- [ ] **Step 4: Add the line to the four build units**

Append to each `.build.j2`, after the `[Build]` section:

```ini

[Service]
# Takes Podman's first-command crash after a power loss, so the build doesn't (#268). "-" ignores its result.
ExecStartPre=-{{ tmsetup_podman_refresh_command }}
```

- [ ] **Step 5: Run the tests and the repo's local checks**

Run: `~/code/traffic-monitor/.venv/bin/python -m pytest script/tests -q`
Expected: all pass, with the seven new tests among them.

Run the Jinja parse and the Ansible syntax check from CLAUDE.md's "Local checks" (`</dev/null`, output to a file).
Expected: no errors.

- [ ] **Step 6: Update CLAUDE.md**

Extend the `<svc>.build.j2` bullet with: each `.build.j2` carries `ExecStartPre=-{{ tmsetup_podman_refresh_command }}`, because the boot's first Podman command can crash after a power loss (#268) and a crashed build leaves its container stopped; build units get no `Restart=`, since a build that keeps failing would block the installer. Keep it to two sentences in that file's style.

- [ ] **Step 7: Commit**

```bash
git add script/ansible/roles/tmsetup/vars/main.yml container/*/*.build.j2 script/tests/test_build_units.py CLAUDE.md
git commit   # "Keep Podman's first-command crash after a power loss out of the image builds"
```

---

### Task 2: Device tests

**Files:**
- Modify: `script/devpi/tests/devpi_checks.py` (one helper)
- Modify: `script/devpi/tests/test_services.py` (two tests, after `test_image_builds_succeeded`)
- Modify: `script/devpi/tests/test_disruptive.py` (one test, after `test_reboot_recovers`)
- Modify: `script/devpi/README.md` (the `test_services.py` and `test_disruptive.py` rows, and the list of what the disruptive tests do to the Pi)

**Interfaces:**
- Consumes: `tmsetup_podman_refresh_command` from Task 1, through `role_vars()` in `devpi_checks.py`.
- Produces: `podman_events(host, event) -> list[dict]` in `devpi_checks.py`: the journal entries with `PODMAN_EVENT=<event>` for the current boot, each a dict with `_CMDLINE`, `_SYSTEMD_UNIT`, and `_PID`, read with sudo through `journalctl -b -o json --output-fields=… --no-pager`. No entries gives `[]`, whatever `journalctl` exits with.

- [ ] **Step 1: Write the read-only tests**

In `test_services.py`:

```python
def test_build_units_run_the_throwaway_podman_command_first(host):
    listing = host.check_output("systemctl list-units --all --plain --no-legend '*-build.service'")
    units = [line.split()[0] for line in listing.splitlines() if line.strip()]
    assert units, "no *-build.service units found"
    command = role_vars()["tmsetup_podman_refresh_command"]
    missing = [unit for unit in units
               if f"argv[]={command} ; ignore_errors=yes" not in host.check_output(f"systemctl show -p ExecStartPre {unit}")]
    assert not missing, f"build units without 'ExecStartPre=-{command}': {missing}"


def test_no_image_build_did_the_boots_podman_refresh(host):
    """Only the Podman command that does a boot's state refresh can crash as in #268, so it must never be a build."""
    refreshes = podman_events(host, "refresh")
    if not refreshes:
        pytest.skip("this boot's Podman refresh is no longer in the journal")
    builds = [entry["_SYSTEMD_UNIT"] for entry in refreshes if " build " in f"{entry['_CMDLINE']} "]
    assert not builds, f"this boot's Podman refresh ran in an image build: {builds}"
```

- [ ] **Step 2: Write the disruptive test**

In `test_disruptive.py`:

```python
def test_stack_recovers_after_an_unclean_reset(host):
    """A reset with no shutdown leaves the pod's containers in Podman's state, as a power loss does. The next boot's
    refresh removes them, which is where Podman 5.4.2 can crash (#268). The sync keeps the test about Podman's
    leftovers, not about what the SD card loses."""
    unclean_reset(host)
    wait_until_ready(host, REBOOT_TIMEOUT_SECONDS)
    refreshes = podman_events(host, "refresh")
    assert len(refreshes) == 1, refreshes
    removed = [entry for entry in podman_events(host, "remove") if entry["_PID"] == refreshes[0]["_PID"]]
    assert removed, "the refresh removed no containers, so the reset wasn't unclean"
    assert " build " not in f"{refreshes[0]['_CMDLINE']} ", refreshes[0]
```

`unclean_reset(host)` reads `/proc/sys/kernel/random/boot_id`, schedules the reset through PID 1 so the SSH command returns before the Pi goes down (`systemd-run --on-active=2 /bin/sh -c 'sync; echo b > /proc/sysrq-trigger'`, with sudo), then polls until the boot ID differs, treating testinfra's `RuntimeError` as "still down", for at most `REBOOT_TIMEOUT_SECONDS`.

- [ ] **Step 3: Check that the tests collect and skip off-device**

Run: `~/code/traffic-monitor/.venv/bin/python -m pytest script/devpi/tests -q`
Expected: every test skipped (no `TM_DEV_HOSTS`), no collection errors.

- [ ] **Step 4: Update `script/devpi/README.md`**

Add to the `test_services.py` row: the image build units run the throwaway Podman command first, and no image build did the boot's Podman refresh. Add to the `test_disruptive.py` row: the stack recovers after a reset with no shutdown. In the list of what the disruptive tests do to the Pi, add that the reset test resets the Pi without shutting it down, after a `sync`.

- [ ] **Step 5: Commit**

```bash
git add script/devpi/tests script/devpi/README.md
git commit   # "Test that a reset with no shutdown brings every app back"
```

---

### Task 3: Bench check and the PR text

**Files:** none in the repo. The check is logged by `tmdev.py check`.

- [ ] **Step 1: Ask the maintainer for a free bench Pi**, and confirm it may be deployed to, reset, and power-cycled. Below, `<host>` is that Pi and `T` is `~/code/traffic-monitor/.venv/bin/python script/devpi/tmdev.py`, run from the worktree.

- [ ] **Step 2: Start the check and record the "before"**

```bash
$T check start --host <host> --pr 268 --title "Apps start by themselves after a power loss"   # the issue's number; there is no PR yet
$T run <host> -- 'sudo journalctl -q --no-pager -o with-unit PODMAN_EVENT=refresh | grep -o "[a-z0-9-]*[.]service\|[a-z0-9-]*[.]scope" | sort | uniq -c'
$T run <host> -- 'sudo /usr/bin/podman network exists podman; echo "exit $?"'
```

Pass the command to `tmdev.py run` as one quoted string, as here; `bash -c '…'` loses its quoting on the way.

Items: "Before the fix, image builds did the refresh in N of M boots" (pass, with the counts); "The throwaway command exits 0 as root on Podman 5.4.2 and prints nothing" (pass or fail).

- [ ] **Step 3: Deploy and run the read-only tests**

```bash
$T deploy <host>
$T test <host>
```

Items: "The installer finishes and the PLAY RECAP names the right host"; "Device tests pass, including the two new ones".

- [ ] **Step 4: Reset five times**

Run `$T test <host> --disruptive -- -k unclean_reset` five times, timing the first. After the last:

```bash
$T run <host> -- 'sudo journalctl -q --no-pager -o short-iso -g "panic: runtime error" --since "<deploy time>"'
$T run <host> -- 'sudo journalctl -q --no-pager -o with-unit PODMAN_EVENT=refresh --since "<deploy time>" | grep -o "[a-z0-9-]*[.]service\|[a-z0-9-]*[.]scope" | sort | uniq -c'
```

Items: "Five resets with no shutdown: every app came back each time"; "No refresh since the deploy came from `podman build`"; "Panics during the resets: <count>, and each time every app still came up" (a count of 0 is a pass; say so in the note).

- [ ] **Step 5: The rest of the disruptive suite, then the power cuts**

Run `$T test <host> --disruptive` once: a clean reboot and the other recovery tests still pass. Then record a `manual` item, "Power pulled and restored twice; device tests pass after each", and ask the maintainer to pull the power. Run `$T test <host>` after each cut and re-record the item as `pass --note "confirmed by <name>"`.

- [ ] **Step 6: End the check, draft the PR text, and stop**

`$T check end`. Draft the PR description from the template for the maintainer to read before anything is pushed:
- **Summary:** the cause in two sentences, the one line per build unit, and why not retries. `Closes #268` (closed by hand after the merge into `dev`).
- **Release note:** "After a power loss, the device's apps start by themselves again. A Podman crash at boot could leave Frigate, Node-RED, or the web pages stopped until someone restarted them."
- **Docs:** `CLAUDE.md` and `script/devpi/README.md`. No docs-site page changes: none describes the build units, and "starts again by itself after a power cut" in `docs/getting-started.md` is what this fixes.
- **Testing:** the check's items with their counts, with no device names or addresses.
- **AI assistance:** the template's section, with the models from the commit trailers.

- [ ] **Step 7: Draft the follow-up issue, to open once the PR has merged**

Draft it for the maintainer to read; open it only on their word, after the merge (`PUBLIC push → glossyio/traffic-monitor (new issue)`).
- **Title:** "Remove the image builds' throwaway Podman command once Podman has the refresh fix"
- **Body:** what the line is and why it's there (link #268 and the merged PR); the condition for removing it: every Raspberry Pi OS release the installer supports ships Podman 5.6.0 or later, or a Trixie update carries the upstream fix in 5.4.2; what goes: `tmsetup_podman_refresh_command`, the `[Service]` section of each `.build.j2`, `script/tests/test_build_units.py`, the two tests in `test_services.py`, the build assertion in the reset test (the reset test itself stays), and the lines in `CLAUDE.md` and `script/devpi/README.md`; and that leaving the line in on a fixed Podman is harmless, so nothing is urgent.

## Not in this plan

- Retries or start limits on the build units (see Spec).
- A newer Podman. When every supported Raspberry Pi OS release ships 5.6.0 or later, the line and its tests can go; Task 3 Step 7 drafts the issue that tracks it, and `#268` in the variable's comment and the tests finds them.
- Asking Debian to carry the upstream fix in Trixie's 5.4.2. That is the maintainer's call.
- What a power loss does to the SD card or to Podman's image store.
