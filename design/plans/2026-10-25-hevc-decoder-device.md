# Stable HEVC decoder device for Frigate (#231) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Frigate gets the Raspberry Pi 5's HEVC decoder on every boot, whatever `/dev/media` number the kernel gives it, instead of the number found once at install time.

**Architecture:** A udev rule matches the media device whose model is `rpi-hevc-dec` and adds the symlink `/dev/rpi-hevc-dec`, tagged for systemd so a device unit exists for it. Frigate's Quadlet unit passes `AddDevice=/dev/rpi-hevc-dec` with no container path. Podman resolves the symlink when the container starts and creates the device in the container under its real name, `/dev/mediaN`, which is the name the ffmpeg fork needs. The unit waits for the device unit, so Frigate can't race the driver at boot. The install-time scan (`utils/find_hevc_device.sh`, `tmsetup_hevc_device` from `set_vars.yml`, `tmsetup_default_hevc_device`) goes away; `tmsetup_hevc_device` becomes the fixed symlink path in `vars/main.yml`.

**Tech Stack:** Ansible (tmsetup role), Podman 5.4.2 Quadlet and systemd 257 on Raspberry Pi OS Trixie, udev, pytest and pytest-testinfra (`script/devpi`).

**Spec:** GitHub issue #231, with the history in #179, #216, #218, and #219. The design was settled on 2026-10-25 from these facts, each checked at the source or on a bench Pi:
- The Frigate image's ffmpeg (`jc-kynesim/rpi-ffmpeg`, branch `test/8.1.2/main`, `libavcodec/v4l2_req_devscan.c`) enumerates the `media` subsystem through libudev, opens each device's kernel devnode (`/dev/mediaN`, from sysfs), skips ones it can't open, and finds the video node from the media topology by major:minor. It never looks at the model or driver name. So the decoder must appear inside the container under its host name for that boot.
- The decoder's driver (`drivers/media/platform/raspberrypi/hevc_dec/hevc_d.c`) sets the media model to `rpi-hevc-dec` and registers its video node as `/dev/video19` (`video_nr = 19`). Media minor numbers are handed out lowest-free at probe time (`drivers/media/mc/mc-devnode.c`), which is why the number moves.
- On two bench Pi 5s (kernel 6.18, Podman 5.4.2, systemd 257), the media devices live under `/sys/bus/media/devices/` (there is no `/sys/class/media`). Each media device has its own `model` attribute, so `SUBSYSTEM=="media", ATTR{model}=="rpi-hevc-dec"` matches it directly. The ISP back end (`pispbe`, platform device `1000880000.pisp_be`) owns two media numbers, the decoder (`1000800000.codec`) one, and the CSI front end (`rp1-cfe`, `1f00110000.csi`) one on units with a camera. One unit had the decoder at `media1`, the other at `media2`. No udev rule or symlink exists for it today. The candidate rule passes `udevadm verify` on the Pi.
- Podman 5.4 (`pkg/specgen/generate/config_linux.go`, `config_common.go`): a `--device` host path that is a symlink is resolved with `EvalSymlinks`, and when no container path is given the container path is the resolved path. A Quadlet dry run of `AddDevice=/dev/rpi-hevc-dec` gives `--device /dev/rpi-hevc-dec`, and `[Unit]` keys pass through.
- Quadlet's optional form `AddDevice=-/dev/...` checks that the path exists when the generator runs. At boot that is before udev and the drivers have created anything, so an optional device would be dropped on every boot. Don't use it.

## Global Constraints

- The symlink is `/dev/rpi-hevc-dec`. Its systemd device unit is `dev-rpi\x2dhevc\x2ddec.device` (`systemd-escape -p --suffix=device /dev/rpi-hevc-dec`).
- `/dev/video19` stays as it is: `AddDevice=/dev/video19:/dev/video19`.
- Keep this PR independent of #224 (`feature/edge-ports/201`). It doesn't touch `frigate.container.j2`, `set_vars.yml`, `defaults/main.yml`, `utils/`, or `test_cameras.py`. It does touch `tasks/frigate_setup.yml` (Task 7 inserts after "Create Frigate container configuration files"), `vars/main.yml` (appends `storefiles.conf` at the end), and CLAUDE.md (line 110). Task 1 adds its tasks at the top of `frigate_setup.yml`, its variable next to `tmsetup_hailo_driver_dir`, and Task 4 edits only line 108 of CLAUDE.md, so either branch merges cleanly after the other.
- `script/tests/` doesn't exist on `dev` yet. #224 creates it with `script/tests/tmsetup_render.py`. Task 1 adds a byte-identical copy of that file (md5 `ef5f3505e5c0d792c2a97eaa31209631`) and its own test module `test_frigate_hevc_device.py`, not #224's `test_tmsetup_templates.py`.
- Conventions, as in the M1 plan: task names `TMSetup - <Component> - <Action>`, FQCN modules, `become: true` per task, 2-space YAML; a fixed value shared by several files goes in `vars/main.yml`; Python indented with 4 spaces with a module docstring; test module basenames unique across the repo; no helper module named `helpers.py`; no AI-provenance comments.
- Device tests: synthetic expectations only, never device names or addresses in commits or PR text. Ask the person before a deploy, a reboot, or stopping services. Both dev Pis are `pii_free`, but nothing here reads `config.yml` or `tmdb.sqlite`.
- Commits: one per task, ending with CLAUDE.md's trailer block (`Assisted-by`, `AI-Model`, `AI-Effort`, `AI-Role`), not `Co-Authored-By`. Ask for the interface and effort level if unknown.
- Run checks from the repo root in the dev venv (`.venv`, from `script/requirements-dev`). For Ansible use `</dev/null` and send output to a file.

## Review Focus

1. **An existing device upgraded with `tmsetup.sh -t frigate`.** The symlink must exist before Frigate restarts, without a reboot. Task 1's handler test checks that the udev reload handler runs before the Frigate restart handler and settles; Task 5 runs the upgrade on a Pi that has no symlink yet.
2. **Boot order.** Frigate must not start before the decoder's symlink exists. Task 2's test checks `Wants=` and `After=` on the device unit; Task 5's reboot runs the device test afterwards.
3. **A boot where the number changed.** Task 3's disruptive test forces a renumbering by unbinding and rebinding the drivers, then checks what the running container got through `podman inspect`, not just the unit text.
4. **A rule that silently matches nothing.** Task 1's test pins the exact match keys to the values read from the Pi; the device test compares the symlink's target with an independent `udevadm` scan.
5. **A Pi without the decoder** (not a Pi 5, or the module missing). Today Frigate fails at once on `stat /dev/media3`. With `Wants=` on a device unit that never appears, systemd waits `DefaultDeviceTimeoutSec` (90 s) and then starts Frigate, which fails the same way. That's acceptable and is noted in the unit's comment; no test, since no bench unit lacks the decoder.

---

### Task 1: The udev rule, the fixed symlink path, and removing the install-time scan

**Files:**
- Create: `script/ansible/roles/tmsetup/templates/60-traffic-monitor-hevc-dec.rules.j2`
- Create: `script/tests/tmsetup_render.py` (copied from #224, byte-identical)
- Create: `script/tests/test_frigate_hevc_device.py`
- Modify: `script/ansible/roles/tmsetup/vars/main.yml` (after `tmsetup_hailo_driver_dir`)
- Modify: `script/ansible/roles/tmsetup/tasks/frigate_setup.yml` (two tasks at the top, before "Create Frigate Directories")
- Modify: `script/ansible/roles/tmsetup/handlers/main.yml` (the `Reload udev rules and trigger` handler)
- Modify: `script/ansible/roles/tmsetup/tasks/set_vars.yml` (delete the two HEVC tasks, lines 25–35)
- Modify: `script/ansible/roles/tmsetup/defaults/main.yml` (delete `tmsetup_default_hevc_device`)
- Delete: `utils/find_hevc_device.sh`

**Interfaces:**
- Produces: `tmsetup_hevc_device: /dev/rpi-hevc-dec` in `vars/main.yml`, read by Task 2's unit and Task 3's device tests.
- Produces: `render(template, **variables)` and `load_role_yaml(relative_path)` in `script/tests/tmsetup_render.py`, as #224 defines them.

- [ ] **Step 1: Branch and copy the render helper**

```bash
git fetch origin dev feature/edge-ports/201
git switch -c bugfix/stable-hevc-device/231 origin/dev
mkdir -p script/tests
git show origin/feature/edge-ports/201:script/tests/tmsetup_render.py > script/tests/tmsetup_render.py
md5sum script/tests/tmsetup_render.py
```

Expected: `ef5f3505e5c0d792c2a97eaa31209631`. Don't edit the file; when #224 merges, git sees one identical file.

- [ ] **Step 2: Write the failing tests**

Create `script/tests/test_frigate_hevc_device.py`:

```python
"""The HEVC decoder reaches Frigate by a stable udev symlink, whatever /dev/media number it has (#231)."""

import shutil
import subprocess
from pathlib import Path

import pytest
from tmsetup_render import load_role_yaml, render

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "script" / "ansible" / "roles" / "tmsetup"
SYMLINK = "/dev/rpi-hevc-dec"
RULE = 'SUBSYSTEM=="media", ATTR{model}=="rpi-hevc-dec", SYMLINK+="rpi-hevc-dec", TAG+="systemd"'
RULE_DEST = "/etc/udev/rules.d/60-traffic-monitor-hevc-dec.rules"


def rule_lines():
    text = render("script/ansible/roles/tmsetup/templates/60-traffic-monitor-hevc-dec.rules.j2",
                  tmsetup_hevc_device=SYMLINK)
    return [line for line in text.splitlines() if line.strip() and not line.startswith("#")]


def udevadm_version():
    if not shutil.which("udevadm"):
        return 0
    return int(subprocess.run(["udevadm", "--version"], capture_output=True, text=True).stdout.split()[0])


def test_symlink_path_is_fixed_in_vars():
    assert load_role_yaml("vars/main.yml")["tmsetup_hevc_device"] == SYMLINK
    assert "tmsetup_default_hevc_device" not in load_role_yaml("defaults/main.yml")


def test_rule_matches_the_decoder_model_and_tags_it_for_systemd():
    assert rule_lines() == [RULE]


def test_rule_passes_udevadm_verify(tmp_path):
    if udevadm_version() < 254:
        pytest.skip("udevadm verify needs systemd 254 or newer")
    rule = tmp_path / "60-traffic-monitor-hevc-dec.rules"
    rule.write_text("\n".join(rule_lines()) + "\n")
    assert subprocess.run(["udevadm", "verify", str(rule)], capture_output=True, text=True).returncode == 0


def test_frigate_setup_installs_the_rule_then_restarts_frigate():
    tasks = {task["name"]: task for task in load_role_yaml("tasks/frigate_setup.yml")}
    task = tasks["TMSetup - Frigate Setup - Create udev rule for the HEVC decoder symlink"]
    template = task["ansible.builtin.template"]
    assert (template["src"], template["dest"], template["mode"]) == ("60-traffic-monitor-hevc-dec.rules.j2", RULE_DEST, "0644")
    assert task["notify"] == ["Reload udev rules and trigger", "Restart frigate.service"]
    handlers = [handler["name"] for handler in load_role_yaml("handlers/main.yml")]
    assert handlers.index("Reload udev rules and trigger") < handlers.index("Restart frigate.service")
    reload = next(h for h in load_role_yaml("handlers/main.yml") if h["name"] == "Reload udev rules and trigger")
    assert reload["ansible.builtin.shell"].split(" && ") == ["udevadm control --reload", "udevadm trigger", "udevadm settle"]
    cleanup = tasks["TMSetup - Frigate Setup - Remove the install-time HEVC scan script"]
    assert cleanup["ansible.builtin.file"] == {"path": "{{ tmsetup_codedir }}/utils/find_hevc_device.sh", "state": "absent"}


def test_install_time_scan_is_gone():
    names = [task["name"] for task in load_role_yaml("tasks/set_vars.yml")]
    assert "TMSetup - Main - Find HEVC hardware device" not in names
    assert "TMSetup - Main - Set HEVC device fact" not in names
    assert not (REPO / "utils" / "find_hevc_device.sh").exists()
    assert "hevc" not in (ROLE / "tasks" / "set_vars.yml").read_text().lower()
```

- [ ] **Step 3: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest script/tests/test_frigate_hevc_device.py -v`

Expected: 5 failed. `KeyError: 'tmsetup_hevc_device'`, `TemplateNotFound`, `KeyError` for the task name, and the scan tasks and script still present. (`udevadm verify` on this dev machine is systemd 259, so that test fails on `TemplateNotFound` too.)

- [ ] **Step 4: Add the variable, the rule template, the tasks, and the handler change**

In `vars/main.yml`, after the `tmsetup_hailo_driver_dir` line:

```yaml
# udev symlink to the Pi 5 HEVC decoder (model rpi-hevc-dec); its /dev/media number changes between boots (#231).
# Must match the SYMLINK in templates/60-traffic-monitor-hevc-dec.rules.j2 and the device unit in frigate.container.j2.
tmsetup_hevc_device: /dev/rpi-hevc-dec
```

Create `templates/60-traffic-monitor-hevc-dec.rules.j2`:

```
# Written by tmsetup.sh (frigate tag). The Pi 5 HEVC decoder's /dev/media number can change between
# boots, so Frigate is given this symlink instead. TAG+="systemd" gives it a device unit that
# frigate.service waits for.
SUBSYSTEM=="media", ATTR{model}=="rpi-hevc-dec", SYMLINK+="{{ tmsetup_hevc_device | basename }}", TAG+="systemd"
```

At the top of `tasks/frigate_setup.yml`, before "Create Frigate Directories", add two tasks. The first is an `ansible.builtin.template` with `src: 60-traffic-monitor-hevc-dec.rules.j2`, `dest: /etc/udev/rules.d/60-traffic-monitor-hevc-dec.rules`, `owner: root`, `group: root`, `mode: '0644'`, and `notify` as a two-item list, udev first. The second is an `ansible.builtin.file` with `state: absent` for `{{ tmsetup_codedir }}/utils/find_hevc_device.sh`, because `base_setup.yml` copies `utils/` without deleting (it never notifies anything). Both `become: true`.

In `handlers/main.yml`, change the udev handler's command to `udevadm control --reload && udevadm trigger && udevadm settle`, so the symlink exists before the Frigate restart handler runs.

Delete the "Find HEVC hardware device" and "Set HEVC device fact" tasks from `set_vars.yml`, `tmsetup_default_hevc_device` from `defaults/main.yml`, and `utils/find_hevc_device.sh` (`git rm`).

- [ ] **Step 5: Run the tests and the Ansible checks**

```bash
.venv/bin/python -m pytest script/tests -v
(cd script/ansible && ../../.venv/bin/ansible-playbook -i localhost setup.yml --syntax-check </dev/null > /tmp/syntax.log 2>&1; echo $?; tail -3 /tmp/syntax.log)
.venv/bin/python -c 'import sys,jinja2; e=jinja2.Environment(); [e.parse(open(f).read(), filename=f) for f in sys.argv[1:]]' $(git ls-files '*.j2') script/ansible/roles/tmsetup/templates/60-traffic-monitor-hevc-dec.rules.j2
```

Expected: 5 passed; syntax check exit 0; the Jinja parse prints nothing. `frigate.container.j2` still references `tmsetup_hevc_device`, which now resolves to the symlink; Task 2 changes that line.

- [ ] **Step 6: Commit**

```bash
git add script/tests/tmsetup_render.py script/tests/test_frigate_hevc_device.py \
    script/ansible/roles/tmsetup/templates/60-traffic-monitor-hevc-dec.rules.j2 \
    script/ansible/roles/tmsetup/vars/main.yml script/ansible/roles/tmsetup/defaults/main.yml \
    script/ansible/roles/tmsetup/tasks/frigate_setup.yml script/ansible/roles/tmsetup/tasks/set_vars.yml \
    script/ansible/roles/tmsetup/handlers/main.yml utils/find_hevc_device.sh
git commit -m "Give the HEVC decoder a udev symlink instead of scanning at install time" -m "<trailer block>"
```

---

### Task 2: Frigate's unit uses the symlink and waits for its device unit

**Files:**
- Modify: `container/frigate/frigate.container.j2` (`[Unit]` lines 3–4 and the `AddDevice` line 14)
- Test: `script/tests/test_frigate_hevc_device.py`

**Interfaces:**
- Consumes: `tmsetup_hevc_device` from Task 1.
- Produces: the rendered unit line `AddDevice=/dev/rpi-hevc-dec`, which Task 3's device test looks for verbatim.

- [ ] **Step 1: Write the failing tests**

Append to `script/tests/test_frigate_hevc_device.py`:

```python
DEVICE_UNIT = "dev-rpi\\x2dhevc\\x2ddec.device"
QUADLET = next((p for p in ("/usr/libexec/podman/quadlet", "/usr/lib/podman/quadlet") if Path(p).exists()), None)


def frigate_unit():
    return render("container/frigate/frigate.container.j2", tmsetup_detectors={},
                  tmsetup_hevc_device=SYMLINK, tmsetup_codedir="/opt/traffic-monitor").splitlines()


def test_frigate_gets_the_decoder_through_the_symlink():
    lines = frigate_unit()
    assert f"AddDevice={SYMLINK}" in lines, "no container path: Podman uses the resolved /dev/mediaN, the name ffmpeg needs"
    assert "AddDevice=/dev/video19:/dev/video19" in lines
    assert not [line for line in lines if line.startswith("AddDevice=-")], "optional devices are dropped at boot"


def test_frigate_waits_for_the_decoder_device_unit():
    lines = frigate_unit()
    assert f"Wants={DEVICE_UNIT}" in lines
    assert f"After={DEVICE_UNIT}" in lines
    if shutil.which("systemd-escape"):
        escaped = subprocess.run(["systemd-escape", "-p", "--suffix=device", SYMLINK], capture_output=True, text=True)
        assert escaped.stdout.strip() == DEVICE_UNIT


def test_quadlet_turns_the_symlink_into_a_device_flag(tmp_path):
    """A Quadlet dry run, with the image and pod references dropped since those units aren't rendered here."""
    if QUADLET is None:
        pytest.skip("no Quadlet generator on this machine (install podman)")
    unit = "\n".join(line for line in frigate_unit() if not line.startswith("Pod="))
    unit = unit.replace("Image=frigate-tm.build", "Image=localhost/frigate-tm:test")
    units = tmp_path / "units"
    units.mkdir()
    (units / "frigate.container").write_text(unit + "\n")
    result = subprocess.run([QUADLET, "-dryrun"], env={"QUADLET_UNIT_DIRS": str(units), "PATH": "/usr/bin:/bin"},
                            capture_output=True, text=True)
    exec_start = next(line for line in result.stdout.splitlines() if line.startswith("ExecStart="))
    assert f" --device {SYMLINK} " in exec_start
    assert f"After={DEVICE_UNIT}" in result.stdout.splitlines()
    assert "error" not in result.stderr.lower(), result.stderr
```

- [ ] **Step 2: Run the tests to check they fail**

Run: `.venv/bin/python -m pytest script/tests/test_frigate_hevc_device.py -v -k "symlink or device_unit or quadlet"`

Expected: 3 failed: the unit still renders `AddDevice=/dev/rpi-hevc-dec:/dev/rpi-hevc-dec` and has no `Wants=`.

- [ ] **Step 3: Change the unit**

In `container/frigate/frigate.container.j2`, make the `[Unit]` section:

```
[Unit]
Description=Frigate container for Traffic Monitor
After=go2rtc_server.service podman.socket
Wants=go2rtc_server.service
# The HEVC decoder's udev symlink (tmsetup_hevc_device) has a device unit, so Frigate waits for it at boot.
# Without the decoder, systemd gives up after DefaultDeviceTimeoutSec and Frigate fails on the missing device, as before.
After=dev-rpi\x2dhevc\x2ddec.device
Wants=dev-rpi\x2dhevc\x2ddec.device
```

The existing `After=` and `Wants=` lines stay as they are; the device unit gets its own two lines, so the diff is additions only and the tests can match whole lines.

and replace the `AddDevice={{ tmsetup_hevc_device }}:{{ tmsetup_hevc_device }}` line with:

```
# No container path: Podman follows the symlink and creates the device as /dev/mediaN, the name ffmpeg looks for.
AddDevice={{ tmsetup_hevc_device }}
```

- [ ] **Step 4: Run the tests and the local checks**

```bash
.venv/bin/python -m pytest script/tests -v
.venv/bin/python -c 'import sys,jinja2; e=jinja2.Environment(); [e.parse(open(f).read(), filename=f) for f in sys.argv[1:]]' $(git ls-files '*.j2')
```

Expected: 8 passed (the Quadlet test runs on this machine; podman 5.7 is installed), nothing from the Jinja parse.

- [ ] **Step 5: Commit**

```bash
git add container/frigate/frigate.container.j2 script/tests/test_frigate_hevc_device.py
git commit -m "Pass the HEVC decoder to Frigate through its symlink and wait for its device unit" -m "<trailer block>"
```

---

### Task 3: Device tests: the symlink follows the decoder, and Frigate got it on this boot

**Files:**
- Modify: `script/devpi/tests/devpi_checks.py` (after `role_defaults()`)
- Modify: `script/devpi/tests/test_cameras.py` (`FIND_HEVC` and `test_frigate_gets_the_hevc_decoder`)
- Modify: `script/devpi/tests/test_disruptive.py` (append)
- Modify: `script/devpi/README.md` (the `test_cameras.py` and `test_disruptive.py` rows of the module table)

**Interfaces:**
- Consumes: `tmsetup_hevc_device` from `vars/main.yml` (Task 1), the unit line `AddDevice=/dev/rpi-hevc-dec` (Task 2), and #215's `host` fixture, `wait_until_ready`, and `RESTART_TIMEOUT_SECONDS` in `test_disruptive.py`.
- Produces, in `devpi_checks.py`:
  - `role_vars() -> dict`: `vars/main.yml`, cached like `role_defaults()`.
  - `find_hevc_decoder(host) -> str`: the `/dev/mediaN` whose model is `rpi-hevc-dec`, by the same `udevadm` scan the old `utils/find_hevc_device.sh` used; fails the test if there is none.
  - `frigate_host_devices(host) -> list[str]`: `PathOnHost` of every device of the running `frigate` container, from `podman inspect` under `host.sudo()`.

- [ ] **Step 1: Write the device tests**

In `devpi_checks.py`, add `ROLE_VARS` next to `ROLE_DEFAULTS`, `role_vars()`, and the two probes. `find_hevc_decoder` runs this under `host.sudo()` and returns the first word of the output:

```python
FIND_HEVC = """for device in /dev/media*; do
  udevadm info -a -n "$device" 2>/dev/null | grep -q 'ATTR{model}=="rpi-hevc-dec"' && echo "$device"
done; true"""
```

`frigate_host_devices` runs `podman inspect frigate --format '{{range .HostConfig.Devices}}{{.PathOnHost}}{{"\n"}}{{end}}'` and splits the output into lines.

In `test_cameras.py`, delete `FIND_HEVC` and its comment, import `find_hevc_decoder, frigate_host_devices, role_vars` from `devpi_checks`, add `HEVC_SYMLINK = role_vars()["tmsetup_hevc_device"]`, and replace `test_frigate_gets_the_hevc_decoder` with two tests that don't take the `cameras` fixture, because every Pi 5 has the decoder:

```python
def test_hevc_decoder_symlink_follows_the_decoder(host):
    """udev's symlink points at the media device whose model is rpi-hevc-dec, whatever its number is on this boot (#231)."""
    decoder = find_hevc_decoder(host)
    target = host.run(f"readlink -f {HEVC_SYMLINK}").stdout.strip()
    assert target == decoder, f"{HEVC_SYMLINK} -> {target or 'missing'}, but the decoder is {decoder}; re-run tmsetup.sh -t frigate"


def test_frigate_gets_the_hevc_decoder(host):
    """The unit passes the symlink, and the running container got the decoder's device for this boot."""
    unit = host.file("/etc/containers/systemd/frigate.container").content_string.splitlines()
    assert f"AddDevice={HEVC_SYMLINK}" in unit, f"frigate.container lacks AddDevice={HEVC_SYMLINK}; re-run tmsetup.sh -t frigate"
    decoder = find_hevc_decoder(host)
    devices = frigate_host_devices(host)
    assert decoder in devices, f"the frigate container has {devices}, not the decoder {decoder} (started before the number changed?)"
```

Update the module docstring's first line to end "the HEVC decoder's symlink and the decoder passed to Frigate, and frames flowing end to end."

Append to `test_disruptive.py` (add `from devpi_checks import RESTARTING_UNITS, find_hevc_decoder, frigate_host_devices, role_vars` to its import):

```python
# Media numbers are handed out lowest-free, so unbinding the decoder and the ISP back end (which holds two)
# and rebinding them in the right order gives the decoder a different number, as a reboot sometimes does (#231).
DRIVERS = {"rpi-hevc-dec": "1000800000.codec", "pispbe": "1000880000.pisp_be"}
HEVC_SYMLINK = role_vars()["tmsetup_hevc_device"]


def bind(host, driver, action):
    host.check_output(f"echo {DRIVERS[driver]} > /sys/bus/platform/drivers/{driver}/{action}")


def test_frigate_follows_the_decoder_after_its_number_changes(host):
    """After the decoder's /dev/media number changes, the symlink and a restarted Frigate follow it."""
    before = find_hevc_decoder(host)
    with host.sudo():
        # go2rtc's rpicam-vid holds the ISP; Frigate holds the decoder.
        host.check_output("systemctl stop frigate.service go2rtc_server.service")
        # The minors these two drivers hold; the camera front end keeps its own and isn't touched.
        freed = sorted(int(line.split(":")[1]) for line in host.check_output(
            "cat /sys/bus/platform/devices/{1000800000.codec,1000880000.pisp_be}/media*/dev").splitlines())
        decoder_minor = int(host.check_output("cat /sys/bus/platform/devices/1000800000.codec/media*/dev").split(":")[1])
        try:
            bind(host, "rpi-hevc-dec", "unbind")
            bind(host, "pispbe", "unbind")
            # Bound first, a driver takes the lowest freed number. The decoder gets it unless it's the one it had;
            # then the ISP back end goes first and takes the two lowest.
            order = ["pispbe", "rpi-hevc-dec"] if decoder_minor == min(freed) else ["rpi-hevc-dec", "pispbe"]
            for driver in order:
                bind(host, driver, "bind")
            host.check_output("udevadm settle")
        finally:
            for driver in DRIVERS:
                if not host.file(f"/sys/bus/platform/drivers/{driver}/{DRIVERS[driver]}").exists:
                    bind(host, driver, "bind")
            host.check_output("systemctl start go2rtc_server.service frigate.service")
    after = find_hevc_decoder(host)
    assert after != before, f"the decoder is still {before}; the rebind didn't change its number"
    assert host.run(f"readlink -f {HEVC_SYMLINK}").stdout.strip() == after
    wait_until_ready(host, RESTART_TIMEOUT_SECONDS)
    assert after in frigate_host_devices(host), f"Frigate was restarted but got {frigate_host_devices(host)}, not {after}"
```

`freed` is read before the unbinds, while the devices still exist in sysfs. On the bench units it is three numbers: two from the ISP back end and one from the decoder. The numbering stays changed until the next reboot, which is the point: Frigate keeps working with it.

In `script/devpi/README.md`, change the two table rows to:

```
| `test_cameras.py` | CSI sensors, the HEVC decoder's udev symlink and the decoder passed to the running Frigate container, Frigate cameras producing frames, go2rtc streams, and `config.yml` camera entries |
| `test_disruptive.py` | The stack recovers after a pod restart and after a reboot: units active, and Frigate, Node-RED, and nginx answering; Frigate follows the HEVC decoder after its `/dev/media` number changes (`--disruptive` only) |
```

- [ ] **Step 2: Check the tests are collected and skip without a dev Pi**

```bash
.venv/bin/python -m pytest -q -p no:cacheprovider script/devpi/tests
.venv/bin/python -m pytest -q -p no:cacheprovider --collect-only script/devpi/tests | grep -c -E 'symlink_follows|gets_the_hevc_decoder|number_changes'
```

Expected: everything skipped (no `TM_DEV_HOSTS`), then `3`.

- [ ] **Step 3: Commit**

```bash
git add script/devpi/tests/devpi_checks.py script/devpi/tests/test_cameras.py script/devpi/tests/test_disruptive.py script/devpi/README.md
git commit -m "Device tests: the HEVC symlink follows the decoder and Frigate gets it on this boot" -m "<trailer block>"
```

---

### Task 4: CLAUDE.md

**Files:**
- Modify: `CLAUDE.md:108`

- [ ] **Step 1: Rewrite the HEVC line**

Replace line 108 (the bullet starting "The Frigate image adds a Raspberry Pi ffmpeg fork") with:

```
- The Frigate image adds a Raspberry Pi ffmpeg fork compiled for hardware HEVC decoding (`-hwaccel drm`, `/dev/video19`, and the decoder's `/dev/media*` device). The decoder's number can change between boots, so a udev rule (`templates/60-traffic-monitor-hevc-dec.rules.j2`) adds the symlink `/dev/rpi-hevc-dec` (`tmsetup_hevc_device` in `vars/main.yml`), and Frigate's unit passes that symlink with no container path. Podman resolves it to the real `/dev/mediaN`, which is the name ffmpeg scans for, so never give it a container path.
```

- [ ] **Step 2: Check nothing else names the old pieces**

Run: `grep -rn -E 'find_hevc_device|tmsetup_default_hevc_device|media3' --exclude-dir=.git --exclude-dir=.venv --exclude=flows.json . | grep -v '^./design/'`

Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "CLAUDE.md: the HEVC decoder reaches Frigate by udev symlink" -m "<trailer block>"
```

---

### Task 5: Pi test plan, through tmdev

`T` stands for `.venv/bin/python script/devpi/tmdev.py`, run from this branch's checkout. Use a dev Pi from the local inventory, never a field device. Ask the person before each deploy, the disruptive test, and the reboot. Keep device names and addresses out of commits and PR text.

Both inventory units are Pi 5s running Trixie with the decoder; one has a camera and a Coral PCIe, the other a Hailo and no camera. The one with the camera exercises go2rtc's hold on the ISP in the disruptive test, so prefer it. Run the plan on the second unit too if time allows; the test steps are the same.

- [ ] **Step 1: Open the check and record the baseline**

```bash
$T check start --host <host> --pr <PR number or 231> --title "#231: stable HEVC decoder device"
$T run <host> -- 'for m in /dev/media*; do echo "$m $(cat /sys/bus/media/devices/$(basename $m)/model)"; done; ls -l /dev/rpi-hevc-dec; grep AddDevice /etc/containers/systemd/frigate.container'
$T test <host> -- -k "hevc"
```

Expected: the listing shows the decoder's number for this boot and no symlink (`ls` fails). Of the device tests, `test_hevc_decoder_symlink_follows_the_decoder` fails (`-> missing`) and `test_frigate_gets_the_hevc_decoder` fails on the `AddDevice` line. Record an item: "New device tests fail on a Pi with the install-time scan" with the test run as evidence.

- [ ] **Step 2: Deploy the Frigate tag**

Ask the person first.

```bash
$T deploy <host> -- -t frigate
```

Expected: the run succeeds without a reboot. In the deploy's `tmsetup.log`: "Create udev rule for the HEVC decoder symlink" *changed*, "Remove the install-time HEVC scan script" *changed*, both handlers ran (udev reload first), and the Frigate unit was re-rendered. Record an item with the deploy as evidence.

- [ ] **Step 3: Check the device and the running container**

```bash
$T run <host> -- 'ls -l /dev/rpi-hevc-dec; systemctl list-units -t device --no-legend "dev-rpi*"; grep -n -E "AddDevice|After=|Wants=" /etc/containers/systemd/frigate.container; sudo systemctl show frigate.service -p After -p Wants; sudo podman inspect frigate --format "{{range .HostConfig.Devices}}{{.PathOnHost}} -> {{.PathInContainer}}; {{end}}"; sudo podman exec frigate ls -l /dev/media* /dev/video19; sudo podman exec frigate sh -c "ps -eo args | grep -o -m1 \"hwaccel [a-z]*\""; sudo journalctl -u frigate.service --since -10min --no-pager | grep -i -c -E "error|stat /dev"'
$T test <host>
```

Expected:
- The symlink points at the decoder's `/dev/mediaN`; the device unit `dev-rpi\x2dhevc\x2ddec.device` is `active plugged`; the unit has `AddDevice=/dev/rpi-hevc-dec` and the device unit in `After=` and `Wants=`.
- `podman inspect` shows the resolved path on both sides, `/dev/mediaN -> /dev/mediaN`, not the symlink. Inside the container only that `/dev/mediaN` and `/dev/video19` exist.
- On the camera unit, ffmpeg runs with `hwaccel drm` and the error count is `0`. On the unit without a camera there is no ffmpeg process; the error count is still `0`.
- Every device test passes, including both new ones and #215's. Record an item.

- [ ] **Step 4: Change the decoder's number and check Frigate follows**

Ask the person first: this stops Frigate and go2rtc for about a minute and leaves the media numbers changed until the next reboot.

```bash
$T test <host> --disruptive -- -k "number_changes"
$T run <host> -- 'for m in /dev/media*; do echo "$m $(cat /sys/bus/media/devices/$(basename $m)/model)"; done; ls -l /dev/rpi-hevc-dec; sudo podman inspect frigate --format "{{range .HostConfig.Devices}}{{.PathOnHost}} {{end}}"'
```

Expected: the test passes; the listing shows the decoder at a different number than in Step 1, the symlink pointing at it, and the container holding that number. If the unbind is refused with "Device or resource busy", find what holds the device (`sudo fuser -v /dev/media* /dev/video19`) and bring it to the person rather than killing it. Record an item.

- [ ] **Step 5: Reboot and re-check**

Ask the person first.

```bash
$T test <host> --disruptive -- -k "reboot_recovers"
$T test <host> -- -k "hevc or no_crash_restarts"
$T run <host> -- 'for m in /dev/media*; do echo "$m $(cat /sys/bus/media/devices/$(basename $m)/model)"; done; sudo journalctl -b -u frigate.service --no-pager | grep -i -c -E "stat /dev|no such file"'
```

Expected: the Pi comes back; both HEVC tests pass on the new boot with the number the kernel chose this time; `test_no_crash_restarts[frigate.service]` passes, which shows Frigate didn't fail on a missing symlink and retry; the journal count is `0`. Note in the item which number the decoder got on this boot compared with Steps 1 and 4.

- [ ] **Step 6: Close the check and open the PR**

```bash
$T check status
$T check end
```

Then write the PR against `dev` from the template: summary with the "why" (ffmpeg needs the kernel name, Podman resolves the symlink, the generator-time trap of `AddDevice=-`), the off-device checks from Tasks 1–4, the Pi plan's outcomes with placeholders for the unit, and the "AI assistance" section filled in. Show the person the commit list and the PR text before pushing.

---

## Follow-ups on `feature/edge-ports/201` (not in this PR)

The tm-control spec and M1 plan live on #224's branch. After this PR merges and #224 rebases, update there:
- `design/specs/2026-10-02-tm-control-platform-design.md`, "Builds on merged PRs": the #218/#219 row now reads that Frigate gets the decoder through the udev symlink `/dev/rpi-hevc-dec` (`tmsetup_hevc_device`); the #231 row moves to the merged list.
- Same spec, "Install facts" (line 240): `tmsetup_hevc_device` is the symlink path, not a scanned number.
- Same spec, M3's hardware checks (line 289): "present" probes `readlink -f /dev/rpi-hevc-dec` against the `udevadm` scan; "passed to Frigate" compares the decoder with the running container's `podman inspect` devices, as `test_frigate_gets_the_hevc_decoder` does, not with the unit text.
- M1 Task 7 inserts into `frigate_setup.yml` after "Create Frigate container configuration files"; this PR's two tasks sit above "Create Frigate Directories", so the rebase should apply cleanly. If git reports a conflict there, keep both.
- M1 Task 10 edits CLAUDE.md line 110; this PR edits line 108. Re-read both lines after the rebase.
