# Wi-Fi plan 2: the Network page and the hotspot's settings

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Network page in the control app shows every signed-in user the unit's network details (names, MAC and IP addresses, gateway, DNS, internet), and lets an admin read the hotspot's password, rename the hotspot, change its password, hide its name, and turn it off or on, each with a plain warning and without SSH.

**Architecture:**
- tm-control stays unprivileged. It reads the network state with `nmcli` (no secrets asked for) and the hotspot password from its file in the secrets directory, which the code group can already read. `GET /network` is for any user and never carries a password; `GET /network/hotspot/password` is for admins.
- Every change goes through one new root job, `tm-job-network` (request `/run/tm-control/jobs/network.json`, action `hotspot`), in the pattern of `tm-job-set-secret`: it checks a hostile request, writes the password file first and the profile second, and re-activates the hotspot only when a setting that is on air changed while the hotspot is up. Plan 3 adds its short actions (Forget, Switch now, Cancel) to the same job.
- The job and `tm-network-retry` take one lock, so the timer never moves the radio in the middle of a change.
- The UI is a new `network` module: a read-only page for everyone, a settings component for admins, and a summary line per connected link on the Device page.

**Tech Stack:** Python 3 standard library (the root job), Python 3.11 + FastAPI + pydantic (tm-control), NetworkManager 1.52 (`nmcli`), Ansible (unit, polkit), Vue 3 + Vuetify 3 + TypeScript (Vitest), Material for MkDocs, the dev-Pi tooling (`script/devpi/tmdev.py`). No new Python or npm dependency.

**Spec:** the design summarised in the stub issue, [#292](https://github.com/glossyio/traffic-monitor/issues/292): the Network page without its "Wi-Fi networks" part, the hotspot's settings and their warnings, the split of the network work into a short job (this plan) and a long join job (planned). Its "(maintainer)" items stand; its "(call)" items are kept or changed in "Decisions" below. Joining, saved and nearby networks, and the saved order are planned separately.

**Status:** Task 0 done 2026-11-10: the stub issue is [#292](https://github.com/glossyio/traffic-monitor/issues/292), the branch `feature/network-page/292` is in the worktree `../tm-network-page` at `4a2970a`. Task 1 done 2026-11-11; its answers are in the "Bench answers" notes of Tasks 2, 3 (one line), and 5. Written 2026-11-10 against `feature/wifi-hotspot/289` at `4a2970a` (PR [#290](https://github.com/glossyio/traffic-monitor/pull/290), open against `dev`, mergeable, the only open PR). This plan needs that branch's code, so it stacks on it. Tasks 2 to 11 done 2026-11-11; the PR has the bench summary.

**Decisions made while writing this plan** (calls made here; the maintainer accepted them on 2026-11-10, with decision 5 as revised below; sizes are the code each adds):
1. **One job, `tm-job-network`, with an `action` key.** The design names it and gives it the hotspot settings now and three short actions in plan 3. Its request here is `{"action": "hotspot", ...}` with any of `enabled`, `name`, `password`, `hidden`. About 250 lines, standard library only, repeating `tm-job-set-secret`'s request checks rather than importing them, as the other root scripts do.
2. **The lock comes now, not in plan 3.** Plan 1's notes left it to plan 3. This job is the first thing besides the timer that changes what the timer reads: a "turn off" that lands while the timer's join attempt is failing would be followed by the timer starting the hotspot again, and the Status page would then say "Off by choice" over a hotspot that is on. `flock` on `/run/traffic-monitor/network.lock`: the timer skips its run when the lock is held (outcome `locked`); the job waits 10 seconds, then refuses with "try again in a minute". About 15 lines in each script. Plan 3's join job takes the same lock.
3. **A new password always makes the hotspot WPA2 personal.** The job sets `key-mgmt wpa-psk`, `proto rsn`, `pairwise ccmp`, `group ccmp`, and the password in one `modify`. That is how an adopted hotspot without a password gets one (plan 1's "Set a password" hint becomes a link to this page). An adopted hotspot with other security becomes WPA2 when its password is changed here; the design's table says the hotspot is WPA2.
4. **The page asks for the password only when Show is tapped** (`GET /network/hotspot/password`, admins, `Cache-Control: no-store`, an audit row each time). It is never in `GET /network`, so a viewer's page and a cached answer can't hold it.
5. **The new-password field shows what is typed, and there is no second field to type it again.** (maintainer, 2026-11-10: shown, with a confirmation if that is best practice) Typing a password twice exists to catch typos in a field that hides them; in a field that shows them it adds work and catches nothing, and current guidance prefers showing the password. This admin can already read the current password on the same page, so hiding the new one protects nothing, and a typo costs a trip with an Ethernet cable. The confirmation is the dialog itself: it shows the new password, says to write it down and that every phone must rejoin with it, and its button names the action ("Change password").
6. **No wait is built into the restart.** tm-control answers 202 as soon as the job is queued (`systemctl start --no-block`), so the answer reaches a phone on the hotspot before the hotspot restarts. The page then follows the job; when it loses the unit after a change that restarts or stops the hotspot, it says to rejoin instead of showing an error. After rejoining, the page shows the unit's values, which is the result.
7. **A change that is already in place changes nothing and restarts nothing.** The job compares each value with the profile first. Changes made while the hotspot is down (the radio is on a saved network) are saved and apply when it next starts.
8. **Turning the hotspot on also switches the radio on and starts the hotspot when the radio is idle**; turning it off takes it down. Neither touches a radio that is on a saved network. The job never starts the hotspot on a USB adapter named `wlan0` (plan 1's guard).
9. **Rules for the two typed values.** Name: 1 to 32 bytes of UTF-8, no control characters, no space at either end. Password: 8 to 63 printable ASCII characters, no space at either end. The API refuses others with the rule in words; the job repeats the rules, and a test keeps the two the same.
10. **The Device page asks `GET /network` itself** for its summary lines, so `GET /system/info` doesn't change. When that read fails, the Device page shows its card without the lines.
11. **IPv4 only on the page.** The design asks for "IP address, gateway, DNS servers"; IPv6 addresses are left out until someone needs them.
12. **The hotspot password joins the values diagnostics redacts.** tm-control reads it now, so the diagnostics file strips it like the other secrets, though nothing logs it.

**Where `feature/wifi-hotspot/289` at `4a2970a` leaves the things this plan touches:**
- `tm-control/backend/tm_control/adapters/network.py`: read-only `nmcli`/`iw` probes that return `None` on any failure: `radio_kind`, `radio_enabled`, `device(name) -> Device(state, connection)`, `hotspot(profile) -> Hotspot(autoconnect, ssid, key_mgmt) | None | False` (one `nmcli -g` call per property; `False` is "no such profile"), `signal`, `saved_networks`, `connectivity`, `wifi_country`, `unescape`. Its `run` is `adapters.command.run`, which tests replace.
- `modules/network/__init__.py` has an empty router and the check group (`checks.py`: `hotspot`, `wifi`, `internet`, `wifi_country`; `SET_A_PASSWORD` is a hint). `core/manifest.py` has `NetworkInfo(wifi_device, hotspot_profile, hotspot_address)`. `core/card.py` reads the password file with its own `_read`. `core/secrets.py` doesn't know the hotspot password; `modules/system/diagnostics.py::secret_values` redacts `DEVICE_SECRETS`.
- Jobs: `core/jobs.py` (`JOB_NAMES = {"system-password", "set-secret"}`, `JobRunner.start(name, request, user_id)`, `FakeJobRunner.last_request`), `modules/secrets/router.py` as the newest job-starting router, `tm-control/jobs/tm-job-set-secret` as the newest job (`read_manifest`, `open_jobs_dir`, `read_request`, `open_secrets_dir`, `_replace`, `delete_request`), `tests/fixtures/run_job.py`, `tests/fixtures/fake_nmcli.py` (verbs: `connection show|add|modify|up`, `device show`, `radio wifi`), `tests/test_job_set_secret.py`.
- `tm-control/jobs/tm-network-retry`: `run(now)` reads the state file, calls `decide`, writes the state; `trusted(name, default)` reads a test setting only when not root; its unit has `RuntimeDirectory=traffic-monitor` with `RuntimeDirectoryPreserve=yes`.
- Fake mode: `tm_control/fake.py` (`FakeClock`, kept as `app.state.fake_clock`), `tests/fixtures/status_fake.json`, `tests/fixtures/manifest.json`.
- Role: `templates/tm-control/tm-job-set-secret.service.j2`; `tasks/tm-control_service.yml` loops over the three unit files; `vars/main.yml::tmsetup_tm_control_polkit.units`; `tasks/tm-control_setup.yml` copies all of `tm-control/jobs/`. Pinned by `script/tests/test_tmsetup_tasks.py` (line 732, the loop), `script/tests/test_tmsetup_templates.py` (`JOBS`, line 854; the polkit list, line 934), `tm-control/backend/tests/test_jobs.py` (line 211).
- UI: `src/modules/index.ts` (`MODULES`, in menu order), `modules/device/DevicePage.vue` (`facts`, `StatusCard` with a default slot), `components/EnteredSecret.vue` (the job-following form), `components/jobs.ts::followJob` (rejects when a request fails), `components/clipboard.ts::copyText`, `components/ConfirmDialog.vue`, `stores/session.ts` (`session.isAdmin`, `session.status.hotspot`), `tests/fake-api.ts`, `tests/mount.ts`. `src/api/openapi.json` and `schema.d.ts` are generated (`ui/README.md`, step 4).
- Docs: `docs/use/wifi-hotspot.md` tells people to turn the hotspot off with `nmcli` and to change the password with `sudoedit` and the installer, and says a screen is planned. `docs/use/device-health.md` has the Network group's table. `docs/development/tm-control.md` has "The Network module and the hotspot".

## Global Constraints

- The fixed values, from the design: profile `tm-hotspot`; device `wlan0`; address `10.42.0.1`; the password file `{{ tmsetup_secrets_dir }}/hotspot_password`, mode 0640, owner root, the directory's group. An empty file means "no password". The file is the source of truth: file first, profile second.
- No Wi-Fi password in any log line, job output, audit row, test name, state file, or API answer, except the body of `GET /network/hotspot/password`. Tests and the bench use placeholders, such as `placeholder-pass-1`.
- A hotspot that is up restarts only when its name, password, or hidden setting changed. Nothing here restarts NetworkManager.
- No change may leave the radio on neither a network nor the hotspot, unless an admin turned the hotspot off after the warning.
- The root job: standard library only, no `tm_control` imports, argv lists (never a shell), a refusal is one sentence with no value from the request in it, and the request is deleted whatever happens.
- The warnings' words are the design's (section 2). Turning off: "With the hotspot off, this unit has no wireless way in when its Wi-Fi network is missing. You would need an Ethernet cable." Hiding: "The hotspot is still on and can still be found by scanning. Only its name is hidden."
- Viewers see the page read-only and never a password or a control.
- UI: conventional Vuetify components, no custom CSS beyond spacing and theme, icons from `@mdi/js`, works offline, logic in the backend. The implementer of Tasks 8 and 9 loads `frontend-design:frontend-design`, `superpowers:test-driven-development`, and `superpowers:verification-before-completion`, writes a "Network" section in `tm-control/ui/README.md`'s design notes, and screenshots the page in fake mode at phone and desktop width.
- The role: task names `TMSetup - <Component> - <Action>`, `tmsetup_` variables, FQCN modules, `become: true` per task, two-space YAML.
- Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` passes. Nothing public names a device; later features are "planned" at most.
- Commits end with the trailer block from the public repo's CLAUDE.md, not `Co-Authored-By`. Never run `tmsetup.sh` on a dev machine. Say `PUBLIC push →` before any push. The maintainer reads commit messages and the PR text before anything is pushed.
- Off-device checks before the PR: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`, the UI's `npm ci && npm run build && npm test` in the pinned Node image, the Ansible syntax check, the Jinja parse of every `.j2`, `mkdocs build --strict`.

## Review Focus

1. **An admin changes the hotspot while joined to it**, the usual case at the roadside: the 202 arrives, the page then loses the unit and says to rejoin (with the new name), never a raw error, and after rejoining it shows the new values. Task 9's `says to rejoin when the page loses the unit after a change that restarts the hotspot`, and Task 11's phone items.
2. **The profile refuses the change after the password file was written**: the file gets its old content back, so the card and the hotspot never disagree. Task 5's `test_a_profile_that_will_not_change_puts_the_old_password_back`.
3. **A name with a colon, a backslash, or characters that take more than one byte**: read whole from `nmcli`, counted in bytes against 32 in the page, the API, and the job. Task 2's `test_a_name_with_a_colon_and_a_backslash_is_read_whole`, Task 4's `test_a_name_is_counted_in_bytes`, Task 9's `refuses a name over 32 bytes`.
4. **A viewer or a logged-out browser asks for the password**: 403 or 401, and `GET /network` never carries it for anyone. Task 4's `test_only_an_admin_reads_the_hotspot_password` and Task 3's `test_the_state_never_holds_a_password`.
5. **The timer fires during a change, or a change arrives during the timer's join attempt**: one of them waits or gives way; the hotspot never ends up on after "off". Task 6's two tests and Task 11's lock item.
6. **NetworkManager doesn't answer, or the unit has no built-in radio**: the page still shows the names and says what couldn't be read, and a change is refused in a sentence. Task 3's `test_a_silent_networkmanager_is_not_an_error` and Task 5's `test_a_missing_profile_is_refused`.

---

### Task 0: Base branch and the public stub issue

- [ ] `git fetch origin`; `gh pr list --state open`. If #290 is still open, the base is `origin/feature/wifi-hotspot/289`; if it has merged, the base is `origin/dev`. If any other open PR touches `modules/network/`, `core/jobs.py`, `tm-network-retry`, or `DevicePage.vue`, stop and say so.
- [ ] Draft the public stub issue for the maintainer to read before it is posted: title "Network page: network details and the hotspot's settings", three sentences from the Goal above, no private references. Say `PUBLIC push →` and post it only when the maintainer says so.
- [ ] Work in a worktree: `git worktree add ../tm-network-page -b feature/network-page/<n> <base>`. Never switch the shared checkout.

### Task 1: Bench spike: what the parsers and the restart depend on

No repo code. Through `tmdev.py check start|item|end` from the worktree, one host at a time. Throwaway names and passwords only, generated on the Pi and never printed. Restore the Pi afterwards and say so in the record.

- [ ] **A. What tm-control can read.** As the code owner inside the unit's sandbox (`sudo systemd-run --pipe --wait -p User=<code owner> -p Group=<code group> -p NoNewPrivileges=yes -p ProtectSystem=strict -p "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK" <command>`), record the exact output of: `nmcli -t -f DEVICE,TYPE device status`; `nmcli -t -f GENERAL.HWADDR,GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS device show eth0`, and the same for `wlan0` on the hotspot, on a saved network, and with the radio off; `nmcli -t -f IN-USE,SIGNAL,SSID device wifi list ifname wlan0 --rescan no` on a saved network; `test -r /etc/traffic-monitor/secrets/hotspot_password; echo $?` (expect 0). *If a field is named or escaped differently from Task 2's fixtures:* correct the fixtures and the parser to the recorded output before writing Task 2.
- [ ] **B. Re-activation.** With the second Pi joined to the hotspot as a station: `nmcli connection modify tm-hotspot 802-11-wireless.ssid <throwaway>` (expect the station to stay and `iw dev wlan0 info` to show the old name), then `nmcli --wait 30 connection up tm-hotspot` (expect the new name on air; record the seconds and that the station dropped). Repeat for the password and for `802-11-wireless.hidden yes`. *If `up` on an active profile doesn't apply the change:* Task 5's restart is `connection down` followed by `connection up`.
- [ ] **C. Off and on.** `connection.autoconnect no` and `nmcli connection down tm-hotspot`: the radio is idle, NetworkManager starts nothing, and a run of `tm-network-retry.service` logs `hotspot-off`. After a reboot the hotspot is still off. Then `autoconnect yes` and `connection up`.
- [ ] **D. From open to WPA2.** On a throwaway access-point profile without security, one `modify` with `key-mgmt wpa-psk`, `proto rsn`, `pairwise ccmp`, `group ccmp`, and a password; the station joins with it after the next start.
- [ ] **E. The MAC address of an Imager-made profile** (left open by plan 1's item G), only if a card imaged with Wi-Fi settings is at hand: `nmcli -g 802-11-wireless.cloned-mac-address connection show <profile>` and `GENERAL.HWADDR` while joined. Otherwise record "not checked"; the page shows the device's current address either way.
- [ ] End the check. Write the answers that change a later task into a "Bench answers" note at the top of that task before starting it.

**Bench record (2026-11-11):** check `20261111T023737Z`, from the worktree at `4a2970a`. Both Pis ran #290's install with their hotspot up. The second Pi was the scripted station; throwaway names and passwords were generated on the first Pi, copied Pi to Pi over SSH, and never printed. A, B, C (with a reboot, approved), D, and E pass (8 passed; the one "skipped" row is an early "E not checked" that the later E row replaces). The first Pi is restored (saved name, not hidden, autoconnect on, profile password equal to the file, file unchanged, bench files and profiles deleted); the second was re-imaged by the maintainer for E, so it now runs a fresh Trixie card with no Traffic Monitor install, joined to the LAN by Ethernet and by Wi-Fi: Task 11 needs a full deploy there, not `-t tm-control`. E: an Imager-made Wi-Fi profile is netplan's (`netplan-wlan0-<ssid>`, kept in `/etc/netplan/90-NM-<uuid>.yaml` with its password and generated into `/run/NetworkManager/system-connections/`), with `cloned-mac-address` unset; joined, it uses the permanent address, so the page's device address is what the network sees. This closes plan 1's item G. Answers that change later tasks:
- Task 2: `-t` output differs from the fixtures in three ways (see its note).
- Task 3: `device status` also lists podman's `veth0` as `ethernet` and sorts by state, so "the first `ethernet` device" needs a physical-device test (see its note).
- Task 5: `connection up` on the active profile applies a new name, password, or hidden setting (3.9 s, the station drops), so the restart stays `connection up`. Turning on races NetworkManager's own auto-activation (see its note).
- Decision 3 works: one `modify` makes an open access point WPA2, and a station joins with the password after the next start.
- Turning off (autoconnect no, `down`) survives a reboot, and the retry logs `hotspot-off`.

### Task 2: Read the links, the joined network, and the hidden setting

**Bench answers (Task 1 A, 2026-11-11):** recorded as the code owner inside tm-control's sandbox, NetworkManager 1.52:
- `nmcli -t ... device show` does **not** escape the colons in `GENERAL.HWADDR` (`GENERAL.HWADDR:2C:CF:67:00:AB:11`); only `-g` does. Splitting at the first colon reads it whole either way; the fixtures below are corrected to the recorded form.
- An empty value is empty, not `--`: idle (state 30) and radio off (state 20) give `GENERAL.CONNECTION:` and `IP4.GATEWAY:`. On the hotspot `IP4.GATEWAY:` is empty and there is no `IP4.DNS` line. Keep reading `--` as nothing too.
- `device status` is sorted by state, not by name (`wlan0` before `eth0` here; with the radio off `wlan0` drops below `lo`), and podman's `veth0` has type `ethernet`. Only real devices have `/sys/class/net/<name>/device`, so this task also adds `physical(name, sys_net=Path("/sys/class/net")) -> bool` (that path exists), in the manner of `radio_kind`'s `sys_net`, for Task 3.
- `wifi list --rescan no` on a saved network: `*:81:<ssid>`; on the hotspot it lists the hotspot itself as `*:0:<own name>`, so `wifi_network` means something only when the device is on a saved network (Task 3 calls it only then).

**Files:**
- Modify: `tm-control/backend/tm_control/adapters/network.py`
- Create: `tm-control/backend/tests/test_network_adapter.py`
- Modify: `tm-control/backend/tests/test_network_checks.py`, `tm-control/backend/tests/test_card_cli.py` (their `Hotspot(...)` values gain `hidden`)

**Interfaces:**
- Produces, in `adapters/network.py`, all returning `None` when `nmcli` is missing, times out, or exits non-zero:
  ```python
  @dataclass(frozen=True)
  class Hotspot:  # gains the last field
      autoconnect: bool
      ssid: str
      key_mgmt: str
      hidden: bool

  @dataclass(frozen=True)
  class Link:
      state: int                # NetworkManager's device state, as Device.state
      connection: str | None    # the active profile's name
      mac: str | None           # upper case, colons
      addresses: tuple[str, ...]  # IPv4, without the prefix length
      gateway: str | None
      dns: tuple[str, ...]

  def devices() -> list[tuple[str, str]] | None    # (name, type) per device: ("eth0", "ethernet"), ("wlan0", "wifi")
  def link(name: str) -> Link | None
  def wifi_network(name: str) -> tuple[str, int | None] | None | Literal[False]  # (SSID, signal); False: on none
  def physical(name: str, sys_net: Path = Path("/sys/class/net")) -> bool          # /sys/class/net/<name>/device exists (no nmcli)
  ```

- [ ] **Step 1: Write the failing tests** in `test_network_adapter.py`, each replacing `network.run` with a function that answers from a dict of argv to `CommandResult`:

```python
ETH = (
    "GENERAL.HWADDR:2C:CF:67:00:AB:11\nGENERAL.STATE:100 (connected)\n"
    "GENERAL.CONNECTION:Wired connection 1\nIP4.ADDRESS[1]:192.168.1.57/24\nIP4.GATEWAY:192.168.1.1\n"
    "IP4.DNS[1]:192.168.1.1\nIP4.DNS[2]:9.9.9.9\n"
)

def test_a_connected_link_has_its_mac_addresses_gateway_and_dns(nm):
    nm.answer("device", "show", "eth0", out=ETH)
    assert network.link("eth0") == network.Link(
        100, "Wired connection 1", "2C:CF:67:00:AB:11", ("192.168.1.57",), "192.168.1.1", ("192.168.1.1", "9.9.9.9"))

def test_an_unplugged_link_keeps_its_mac_and_has_nothing_else(nm):
    nm.answer("device", "show", "eth0", out="GENERAL.HWADDR:2C:CF:67:00:AB:11\nGENERAL.STATE:20 (unavailable)\nGENERAL.CONNECTION:\nIP4.GATEWAY:\n")
    assert network.link("eth0") == network.Link(20, None, "2C:CF:67:00:AB:11", (), None, ())

def test_a_dash_dash_value_also_reads_as_nothing(nm):   # older nmcli prints "--"
    nm.answer("device", "show", "eth0", out="GENERAL.HWADDR:2C:CF:67:00:AB:11\nGENERAL.STATE:20 (unavailable)\nGENERAL.CONNECTION:--\nIP4.GATEWAY:--\n")
    assert network.link("eth0") == network.Link(20, None, "2C:CF:67:00:AB:11", (), None, ())

def test_only_a_device_with_hardware_behind_it_is_physical(tmp_path):   # eth0 has device/, veth0 not
    ...
    assert network.physical("eth0", tmp_path) and not network.physical("veth0", tmp_path)

def test_devices_lists_each_name_with_its_type(nm):
    nm.answer("device", "status", out="eth0:ethernet\nwlan0:wifi\nlo:loopback\n")
    assert network.devices() == [("eth0", "ethernet"), ("wlan0", "wifi"), ("lo", "loopback")]

def test_a_name_with_a_colon_and_a_backslash_is_read_whole(nm):
    nm.answer("device", "wifi", "list", out=" :40:Other\n*:72:Caf\\\\e\\: 2\n")
    assert network.wifi_network("wlan0") == ("Caf\\e: 2", 72)

def test_a_radio_on_no_network_reads_as_false(nm):
    nm.answer("device", "wifi", "list", out=" :40:Other\n")
    assert network.wifi_network("wlan0") is False

def test_the_hotspot_read_includes_hidden(nm):   # four -g reads: autoconnect, ssid, key-mgmt, hidden
    ...
    assert network.hotspot("tm-hotspot") == network.Hotspot(True, "TM-AB12", "wpa-psk", True)

def test_a_failed_read_is_none_for_every_probe(nm):   # run raises FileNotFoundError, times out, exits 1
    assert network.devices() is None and network.link("eth0") is None and network.wifi_network("wlan0") is None
```

- [ ] **Step 2:** Run `python -m pytest tm-control/backend/tests/test_network_adapter.py -v`. Expected: FAIL, `AttributeError: ... has no attribute 'link'`.
- [ ] **Step 3: Implement.** `devices()` runs `nmcli -t -f DEVICE,TYPE device status`. `link(name)` runs `nmcli -t -f GENERAL.HWADDR,GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS device show <name>`; a key is the text before the first colon with any `[n]` removed; `--` and an empty value read as nothing; a `link` whose state line is missing is `None`. `wifi_network(name)` runs `nmcli -t -f IN-USE,SIGNAL,SSID device wifi list ifname <name> --rescan no` and splits each line at its first two colons, so the SSID keeps its own. `hotspot()` adds a fourth read, `802-11-wireless.hidden`, `yes` meaning hidden.
- [ ] **Step 4:** Run the adapter tests and `test_network_checks.py`, `test_card_cli.py`. Expected: PASS.
- [ ] **Step 5: Commit** ("Read each link's addresses, the joined network, and the hotspot's hidden setting").

### Task 3: `GET /network`: the state for the page

**Files:**
- Create: `tm-control/backend/tm_control/modules/network/state.py`, `tm-control/backend/tm_control/modules/network/router.py`
- Modify: `tm-control/backend/tm_control/modules/network/__init__.py`, `tm-control/backend/tm_control/fake.py`, `tm-control/backend/tm_control/app.py`
- Create: `tm-control/backend/tests/test_api_network.py`
- Regenerate: `tm-control/ui/src/api/openapi.json`, `tm-control/ui/src/api/schema.d.ts`

**Interfaces:**
- Consumes: Task 2's `devices`, `link`, `wifi_network`, `hotspot`, `physical`; `radio_kind`, `radio_enabled`, `connectivity`; `modules/system/router.py::hostname(app_state)`.
- Produces, in `state.py`:
  ```python
  class Link(BaseModel):
      connected: bool
      mac: str | None
      addresses: list[str]
      gateway: str | None
      dns: list[str]

  class Wifi(Link):
      mode: Literal["network", "hotspot", "joining", "idle", "off"]
      network: str | None     # the joined network's name; None unless mode is "network"
      signal: int | None      # percent

  class HotspotState(BaseModel):
      enabled: bool           # starts by itself
      active: bool            # up now
      name: str
      hidden: bool
      security: Literal["wpa2", "none", "other"]
      address: str            # the manifest's hotspot address

  class NetworkState(BaseModel):
      hostname: str
      local_name: str         # "<hostname>.local"
      readable: bool          # False: NetworkManager didn't answer, and the rest is empty
      ethernet: Link | None   # None: the unit has no Ethernet device
      wifi: Wifi | None       # None: no built-in Wi-Fi radio
      internet: Literal["reachable", "not_reachable", "sign_in_page", "unknown"]
      hotspot: HotspotState | None  # None: not set up

  def read_state(app_state, hostname: str) -> NetworkState
  ```
- Produces, in `fake.py`: `class FakeNetwork` with `hotspot: dict` (the `HotspotState` fields; starts enabled, active, `TM-AB12`, not hidden, `wpa2`), `password: str | None` (starts `ABCD-EFGH-JKLM`), and `apply(change: dict) -> None`, which sets `enabled`, `name`, `hidden`, and `password` from a job request (a password also sets `security` to `wpa2`; `enabled` also sets `active`). `app.state.fake_network` holds one in fake mode, else `None`. In fake mode `read_state` returns Ethernet connected at `192.168.1.57` and the Wi-Fi on its hotspot, with the fake hotspot's values.
- Produces: `GET /api/v1/network`, `response_model=NetworkState`, for any logged-in user (`current_user`).

Rules for `read_state` on a device:
- `devices()` is `None`: `readable=False`, `ethernet=None`, `wifi=None`, `hotspot=None`, `internet="unknown"`.
- Ethernet is the first device of type `ethernet` that is `physical` (Task 1 A: podman's `veth0` is also `ethernet`, and the list is sorted by state). A link's `connected` is state 100, for Ethernet and Wi-Fi alike (the hotspot counts).
- Wi-Fi is the manifest's `wifi_device`, and only when `radio_kind` is `builtin`. `mode`: `off` when `radio_enabled()` is `False`; `hotspot` when state 100 on the hotspot profile; `network` when state 100 on another profile (then `network` and `signal` from `wifi_network`, falling back to the profile's name); `joining` for states 40 to 90; else `idle`.
- `internet`: `full` is `reachable`, `portal` is `sign_in_page`, `limited` and `none` are `not_reachable`, anything else `unknown`.
- `hotspot`: `None` when `network.hotspot()` is `False` or `None`; `security` is `wpa2` for `wpa-psk`, `none` for an empty `key_mgmt`, else `other`; `active` as the Wi-Fi's `hotspot` mode.

- [ ] **Step 1: Write the failing tests** in `test_api_network.py`. Device cases use `device_client` with the adapter's functions replaced (a small `FakeLinks` class in the test file, in the manner of `test_network_checks.FakeNetwork`):

```python
def test_anyone_logged_in_reads_the_network_state(claimed_client, login):          # fake mode, as a viewer
    body = claimed_client.get("/api/v1/network").json()
    assert body["hostname"] and body["local_name"] == body["hostname"] + ".local"
    assert body["wifi"]["mode"] == "hotspot" and body["hotspot"]["name"] == "TM-AB12"

def test_no_login_no_state(claimed_client):                                         # 401
def test_the_state_never_holds_a_password(claimed_client, login):
    text = claimed_client.get("/api/v1/network").text
    assert "password" not in text and "ABCD-EFGH-JKLM" not in text

def test_a_unit_on_a_saved_network(device_client, login, links):                    # mode "network", name and signal
def test_a_unit_with_its_radio_off(device_client, login, links):                    # mode "off", the MAC still shown
def test_a_unit_without_ethernet_or_a_built_in_radio(device_client, login, links):  # ethernet None; usb radio: wifi None
def test_a_silent_networkmanager_is_not_an_error(device_client, login, links):
    links.devices = None
    body = device_client.get("/api/v1/network").json()
    assert body["readable"] is False and body["hostname"] and body["internet"] == "unknown"
def test_a_hotspot_without_a_password_is_security_none(device_client, login, links)
```

- [ ] **Step 2:** Run the file. Expected: FAIL with 404 on `/api/v1/network`.
- [ ] **Step 3: Implement** `state.py`, the `GET` in `router.py`, `FakeNetwork`, `app.state.fake_network`, and point `modules/network/__init__.py` at the new router (its docstring says what the module now serves).
- [ ] **Step 4:** Regenerate the API description as `tm-control/ui/README.md` step 4 says (`dump-openapi`, then the schema types). Run `python -m pytest tm-control/backend/tests`. Expected: PASS, including `test_committed_openapi_document_matches_the_app`.
- [ ] **Step 5: Commit** ("Serve the unit's network state to the control app").

### Task 4: The hotspot password and the change request

**Files:**
- Modify: `tm-control/backend/tm_control/core/secrets.py`, `core/card.py`, `core/jobs.py`, `modules/network/router.py`, `modules/network/checks.py`, `modules/system/diagnostics.py`
- Modify: `tm-control/backend/tests/test_api_network.py`, `test_jobs.py`, `test_network_checks.py`, `test_secrets.py`, the diagnostics test in `test_api_system.py`
- Regenerate: `tm-control/ui/src/api/openapi.json`, `schema.d.ts`

**Interfaces:**
- Produces, in `core/secrets.py`: `HOTSPOT_PASSWORD = "hotspot_password"` and `read_hotspot_password(directory: Path) -> str | None` (the file's text without its line end; `None` when it can't be read). `card.py` uses it in place of its `_read` for the password. It is not added to `GENERATED_SECRETS` (a test ties that list to the role's).
- Produces, in `core/jobs.py`: `JOB_NAMES = {"system-password", "set-secret", "network"}`.
- Produces, in `modules/network/router.py`:
  ```python
  NAME_MAX_BYTES = 32
  NAME_PATTERN = r"[^\x00-\x20\x7f](?:[^\x00-\x1f\x7f]*[^\x00-\x20\x7f])?"       # no control characters, no space at either end
  PASSWORD_PATTERN = r"[\x21-\x7e][\x20-\x7e]{6,61}[\x21-\x7e]"                  # 8 to 63 printable ASCII
  NAME_MESSAGE = "A hotspot name is 1 to 32 characters (fewer with accents or emoji), with no space at either end."
  PASSWORD_MESSAGE = "A hotspot password is 8 to 63 letters, digits, and symbols, with no space at either end."

  class HotspotChange(BaseModel):
      enabled: bool | None = None
      name: str | None = Field(default=None, max_length=128)
      password: str | None = Field(default=None, max_length=128)
      hidden: bool | None = None
  ```
  - `GET /network/hotspot/password` (admins): `{"password": str | None}` with `Cache-Control: no-store`; audit `network.hotspot_password_shown`. Fake mode answers `fake_network.password`.
  - `POST /network/hotspot` (admins), 202 `{"id": <job id>}`: starts job `network` with `{"action": "hotspot", ...}` holding only the fields that were sent. 422 `validation` when no field was sent ("Nothing to change.") or a value breaks its rule (the rule's message); 409 `no_hotspot` ("The hotspot isn't set up. Run the installer again (tmsetup.sh -t wifi).") when `network.hotspot()` is `False`. Audit `network.hotspot` with the changed fields' names, comma-separated, never a value. Fake mode calls `fake_network.apply(request)`.
- Produces, in `checks.py`: `SET_A_PASSWORD = Fix(kind="link", text="Set a password", href="/network")`.
- Produces, in `diagnostics.py::secret_values`: the hotspot password, when the file has one, among the values.

- [ ] **Step 1: Write the failing tests:**

```python
def test_only_an_admin_reads_the_hotspot_password(claimed_client, login):
    # viewer: 403; admin: 200, {"password": "ABCD-EFGH-JKLM"}, Cache-Control "no-store", one audit row
    # "network.hotspot_password_shown"; logged out: 401
def test_a_missing_password_file_reads_as_null_and_an_empty_one_as_empty(device_client, login, settings)
def test_a_change_starts_the_network_job_with_only_what_was_sent(claimed_client, login):
    r = claimed_client.post("/api/v1/network/hotspot", json={"name": "TM-ROAD"}, headers={"Origin": ORIGIN})
    assert r.status_code == 202
    assert claimed_client.app.state.jobs.last_request == {"action": "hotspot", "name": "TM-ROAD"}
def test_a_viewer_cannot_change_the_hotspot(claimed_client, login)                  # 403, no job
@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": " TM"}, {"name": "a" * 33}, {"name": "TM\n1"},
                                  {"password": "short12"}, {"password": "x" * 64}, {"password": "pässwörd1"},
                                  {"password": " leading-space"}])
def test_a_change_is_refused_before_any_job(claimed_client, login, body)            # 422; last_request is None
def test_a_name_is_counted_in_bytes(claimed_client, login):
    # eleven three-byte characters (33 bytes): 422; ten of them and "ab" (32 bytes): 202
def test_the_audit_names_what_changed_and_never_the_password(claimed_client, login) # detail "name, password"
def test_no_hotspot_profile_is_a_409(device_client, login, links)
def test_fake_mode_shows_the_change(claimed_client, login)                          # GET /network has the new name
def test_the_hotspot_password_is_redacted_from_diagnostics(device_client, login, settings)
def test_a_hotspot_without_a_password_links_to_the_network_page(net)                # test_network_checks.py
```
and `test_jobs.py`'s names line becomes the three names.

- [ ] **Step 2:** Run them. Expected: FAIL (404 on the two routes).
- [ ] **Step 3: Implement** the interfaces above. The name's byte length is checked apart from the pattern.
- [ ] **Step 4:** Regenerate the API description. Run `python -m pytest tm-control/backend/tests`. Expected: PASS.
- [ ] **Step 5: Commit** ("Let an admin read the hotspot password and ask for a change").

### Task 5: The root job `tm-job-network`

**Bench answers (Task 1 B, C, 2026-11-11):**
- `nmcli --wait 30 connection up tm-hotspot` on the active profile applies a changed name, password, or hidden setting: 3.9 s, and the joined station drops (its NetworkManager logs `supplicant-timeout` about 7 s later). A `modify` alone changes nothing on air and the station stays. Step 8's restart stays `connection up`, with no `down` before it.
- **Turning on races NetworkManager.** A `modify` that sets `connection.autoconnect yes` while the device is idle makes NetworkManager auto-activate the profile at once; a `connection up` right after it failed in 0.16 s with exit 4, "The base network connection was interrupted", and the hotspot came up anyway. So step 8's "turned on" branch: when `up` fails, read the device until it is state 100 on the hotspot profile (every half second, up to `UP_WAIT`); that counts as `turned the hotspot on`. Only a device that never gets there is `failed: start the hotspot (...)`. Add `test_turning_it_on_counts_the_hotspot_that_networkmanager_started_itself` (the fake's `up` fails with exit 4 while its device reads as on the hotspot).
- Right after that `modify`, `sudo nmcli -s -g 802-11-wireless-security.psk` read an empty value twice in about two minutes, then the right one. An empty read only makes a requested password look different, which costs one restart and is safe; the file, not this read, is what step 7 puts back.
- Off (autoconnect no, then `down`) leaves the radio idle, NetworkManager starts nothing, a retry run logs `hotspot-off`, and it stays off after a reboot.

**Files:**
- Create: `tm-control/jobs/tm-job-network`
- Modify: `tm-control/backend/tests/fixtures/fake_nmcli.py` (add `connection down REF`, which removes the profile from `active`, and `radio wifi on|off`, which sets `radio`; say so in its docstring)
- Create: `tm-control/backend/tests/test_job_network.py`

**Interfaces:**
- Consumes: the request Task 4 writes; the manifest's `codeowner` and `network.wifi_device` / `network.hotspot_profile` (defaults `wlan0`, `tm-hotspot` when the manifest has no `network` key).
- Produces: `tm-job-network [REQUEST]`, run as root by `tm-job-network.service`. Exit 0 with one line per thing done; exit 1 with `refused: <sentence>` or `failed: <step> (<error type>)`, ending `; the settings are saved` once the profile was changed. Constants: `REQUEST = "/run/tm-control/jobs/network.json"`, `MANIFEST`, `SECRETS_DIR`, `NMCLI`, `SYS_NET`, `LOCK = "/run/traffic-monitor/network.lock"`, `LOCK_WAIT = 10`, `UP_WAIT = 30`, `NAME_MAX_BYTES`, `NAME_PATTERN`, `PASSWORD_PATTERN` (the same text as Task 4's). Tests set `TM_CONTROL_MANIFEST`, `TM_CONTROL_SECRETS_DIR`, `NMCLI`, `TM_SYS_NET`, `TM_NETWORK_LOCK`, and `TM_NETWORK_LOCK_WAIT`, each ignored when running as root.

What one run does, in order:
1. Read the manifest; open the jobs directory and the request with `tm-job-set-secret`'s checks (the code owner's directory, a small plain file of the code owner's with one link, a JSON object).
2. Check the request: `action` is `hotspot`; the other keys are a non-empty subset of `enabled`, `name`, `password`, `hidden`; the booleans are booleans; the name and password meet their rules. A refusal names the rule, never the value.
3. Take the lock: `flock` on `LOCK` (its directory is made when missing, mode 0755), tried every half second for `LOCK_WAIT` seconds. Still held: `refused: the unit is trying a saved network right now; try again in a minute`.
4. Read the profile as root: autoconnect, name, hidden, `key-mgmt`, and the password (`nmcli -s`). No profile (exit status 10): `refused: there is no hotspot profile; run the installer`. Every password the job learns goes through a scrubber before anything is printed, as in `tm-hotspot-setup`.
5. Work out what differs. A password differs when it isn't the profile's or the profile isn't `wpa-psk`; it then sets the five WPA2 properties (decision 3). Nothing differs: print `nothing to change`, exit 0.
6. A new password: write the password file first (a new file, mode 0640, owner root, the directory's group, renamed over the old one), keeping the old content in memory.
7. One `nmcli connection modify` with every change. If it fails, write the old password back and exit 1.
8. Then, the first that applies:
   - The hotspot was turned off: `nmcli connection down` if it is up. Print `turned the hotspot off`.
   - The name, password, or hidden setting changed and the hotspot is up: `nmcli --wait 30 connection up` (or what Task 1 B found). Print `restarted the hotspot`.
   - The hotspot was turned on: when the radio is the built-in one, `nmcli radio wifi on` if it is off, then `connection up` if the device has no connection and isn't joining one. Print `turned the hotspot on`.
   - Otherwise print `saved; the change applies when the hotspot next starts`.
9. Delete the request, whatever happened.

- [ ] **Step 1: Write the failing tests** in `test_job_network.py`, run through `fixtures/run_job.py` against the fake `nmcli`, with fixtures in the manner of `test_job_set_secret.py` (a manifest naming the test's own user, a 0700 jobs directory, a 0750 secrets directory holding `hotspot_password` with `placeholder-pass-1`, a fake `/sys/class/net`, the fake's call log):

```python
def test_a_new_name_is_set_and_a_hotspot_that_is_up_restarts(world):
    result = world.run({"action": "hotspot", "name": "TM-ROAD"})
    assert result.returncode == 0 and "restarted the hotspot" in result.stdout
    assert world.profile()["802-11-wireless.ssid"] == "TM-ROAD"
    assert world.calls("modify") == 1 and world.calls("up") == 1

def test_a_change_while_the_hotspot_is_down_waits_for_its_next_start(world)       # active=(); no "up" call
def test_the_password_goes_to_the_file_first_then_the_profile(world):
    # the file holds the new password, mode 0640; the modify comes after the file's mtime changed;
    # the new password is in neither stdout nor stderr
def test_a_password_on_an_open_hotspot_makes_it_wpa2(world)                       # the five properties in one modify
def test_a_profile_that_will_not_change_puts_the_old_password_back(world):
    world.fail("modify")
    result = world.run({"action": "hotspot", "password": "placeholder-pass-2"})
    assert result.returncode == 1 and world.password_file() == "placeholder-pass-1"
    assert "placeholder-pass" not in result.stdout + result.stderr                 # the fake's error quotes the argv
def test_turning_it_off_stops_it_starting_and_takes_it_down(world)                # autoconnect no; one "down"
def test_turning_it_on_switches_the_radio_on_and_starts_it_when_idle(world)
def test_turning_it_on_leaves_a_joined_network_alone(world)                       # no "up"
def test_a_usb_adapter_never_gets_the_hotspot_started(world)                      # modified, no "up", no "radio"
def test_values_already_set_change_nothing_and_restart_nothing(world)             # "nothing to change"; no modify
@pytest.mark.parametrize("request_", [
    {"action": "forget"}, {"action": "hotspot"}, {"action": "hotspot", "name": "x", "extra": 1},
    {"action": "hotspot", "enabled": "yes"}, {"action": "hotspot", "name": "a" * 33},
    {"action": "hotspot", "name": "TM\n1"}, {"action": "hotspot", "password": "short12"},
    {"action": "hotspot", "password": "x" * 64}, {"name": "TM-ROAD"}])
def test_a_request_is_refused_unless_it_is_exactly_a_hotspot_change(world, request_)  # exit 1, no nmcli call
def test_the_request_must_be_tm_controls_own_plain_file(world)                    # a symlink; a second link
def test_a_missing_profile_is_refused(world)
def test_the_request_is_deleted_whatever_happens(world)
def test_a_held_lock_refuses_after_the_wait(world)                                # the test holds the flock; wait 0.2 s
def test_the_rules_are_the_same_as_tm_controls()                                  # the job's three constants == the router's
```

- [ ] **Step 2:** Run the file. Expected: FAIL (no such script).
- [ ] **Step 3: Implement** `tm-job-network` as the run above describes, with a docstring in the manner of `tm-job-set-secret`'s that says what is trusted and what isn't.
- [ ] **Step 4:** Run `python -m pytest tm-control/backend/tests/test_job_network.py tm-control/backend/tests/test_hotspot_setup.py tm-control/backend/tests/test_network_retry.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** ("Add the root job that changes the hotspot's settings").

### Task 6: The timer gives way to a change

**Files:**
- Modify: `tm-control/jobs/tm-network-retry`
- Modify: `tm-control/backend/tests/test_network_retry.py`

**Interfaces:**
- Consumes: Task 5's `LOCK` path and `TM_NETWORK_LOCK`.
- Produces: a run that finds the lock held prints `locked`, exits 0, runs no `nmcli` or `iw`, and leaves the state file as it was. A run that gets the lock holds it until it ends. The docstring's list of outcomes gains `locked`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_a_run_while_a_network_job_holds_the_lock_does_nothing(tmp_path):
    # the test holds flock(LOCK_EX) on the lock file; world(...) returns outcome "locked", no calls, state file absent
def test_the_lock_is_free_again_after_a_run(tmp_path):
    # after world(...), flock(LOCK_EX | LOCK_NB) on the lock file succeeds
```

- [ ] **Step 2:** Run them. Expected: FAIL (the outcome is `phone-joined` or another, not `locked`).
- [ ] **Step 3: Implement:** in `main()`, before `run()`, open the lock file (creating its directory as `write_state` does) and take `flock(LOCK_EX | LOCK_NB)`; on `BlockingIOError` print `locked` and return 0.
- [ ] **Step 4:** Run `test_network_retry.py` and `test_job_network.py`. Expected: PASS.
- [ ] **Step 5: Commit** ("Skip the Wi-Fi retry while a network job is changing the hotspot").

### Task 7: Install the job: unit, polkit, device tests

**Files:**
- Create: `script/ansible/roles/tmsetup/templates/tm-control/tm-job-network.service.j2`
- Modify: `script/ansible/roles/tmsetup/tasks/tm-control_service.yml`, `script/ansible/roles/tmsetup/vars/main.yml`
- Modify: `script/tests/test_tmsetup_tasks.py`, `script/tests/test_tmsetup_templates.py`
- Modify: `script/devpi/tests/test_services.py`, `script/devpi/tests/test_web.py`, `script/devpi/tests/test_disruptive.py`

**Interfaces:**
- Produces: `tm-job-network.service`, a static root oneshot like `tm-job-set-secret.service`, with `StartLimitIntervalSec=0`, `After=NetworkManager.service`, `Environment=TM_CONTROL_MANIFEST=…` and `TM_CONTROL_SECRETS_DIR=…`, `RuntimeDirectory=traffic-monitor`, `RuntimeDirectoryPreserve=yes` (the lock's directory, shared with the retry unit), and `ExecStart={{ tmsetup_tm_control_dir }}/venv/bin/python -EP {{ tmsetup_libexec_dir }}/tm-job-network`. Its name is in the unit loop and in `tmsetup_tm_control_polkit.units`.

- [ ] **Step 1: Write the failing tests:** in `test_tmsetup_templates.py`, `JOBS` gains `"network"` and the polkit list `"tm-job-network.service"`; add `test_the_network_job_shares_the_retry_units_runtime_directory` (both units have `RuntimeDirectory=traffic-monitor` and `RuntimeDirectoryPreserve=yes`). In `test_tmsetup_tasks.py`, the unit loop gains the file.
- [ ] **Step 2:** Run `python -m pytest script/tests -k "job or polkit or unit" -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the template, the loop entry, and the polkit entry.
- [ ] **Step 4: Device tests** (they run in Task 11): in `test_services.py`, the network job's unit is static and its script root-owned, after `SET_SECRET_UNIT`'s test; in `test_web.py`, `test_the_network_page_reports_the_radios_own_address` (as the admin, `GET /api/v1/network`: `wifi.mac` equals `/sys/class/net/wlan0/address` in upper case, and the body has no `password` key) and `test_a_viewer_cannot_read_the_hotspot_password` (403); in `test_disruptive.py`, `test_the_hotspot_name_changes_through_the_job_and_back` (POST a placeholder name, follow the job, `nmcli -g 802-11-wireless.ssid connection show tm-hotspot` reads it, then POST the old name back in a `finally`).
- [ ] **Step 5:** Run `python -m pytest script/tests`, the Ansible syntax check, and the Jinja parse. Expected: PASS.
- [ ] **Step 6: Commit** ("Install the network job's unit and let tm-control start it").

### Task 8: The Network page, read-only, and the Device page's summary

**Files:**
- Create: `tm-control/ui/src/modules/network/index.ts`, `NetworkPage.vue`, `summary.ts`
- Create: `tm-control/ui/src/components/CopyButton.vue`
- Modify: `tm-control/ui/src/modules/index.ts`, `tm-control/ui/src/modules/device/DevicePage.vue`, `tm-control/ui/README.md`
- Modify: `tm-control/ui/tests/fake-api.ts`, `tests/device-page.spec.ts`, `tests/router.spec.ts`
- Create: `tm-control/ui/tests/network-page.spec.ts`, `tests/network-summary.spec.ts`

**Interfaces:**
- Consumes: `GET /api/v1/network` (`components['schemas']['NetworkState']`), `copyText`.
- Produces:
  - `modules/network/index.ts`: `{ id: 'network', routes: [{ path: '/network', component: NetworkPage }], nav: [{ title: 'Network', to: '/network', icon: mdiLan }] }`, placed after `device` in `MODULES`.
  - `summary.ts`: `wifiLine(wifi, hotspot): string` ("HomeNet, signal 72%", "On its hotspot (TM-AB12)", "Joining a network", "Not connected", "Switched off"), `internetLine(internet): string` ("Reachable", "Not reachable", "Needs a sign-in page", "Not checked yet"), and `summaryFacts(state): { label: string; value: string }[]`: one entry per connected link, `Ethernet` as "192.168.1.57 · 2C:CF:67:00:AB:11" and `Wi-Fi` as "HomeNet · 192.168.1.60 · <MAC>" or "Its hotspot TM-AB12 · 10.42.0.1 · <MAC>".
  - `CopyButton.vue`: props `{ text: string; label: string }`; an icon button with `aria-label="Copy <label>"` that shows a check for two seconds after a copy, and "Select the text to copy it." beside it when the browser refuses.
  - `tests/fake-api.ts`: `NETWORK_STATE` (Ethernet connected, Wi-Fi on its hotspot `TM-AB12`) and `networkState(changes)`, typed from the schema.
  - `NetworkPage.vue` renders the section "This device" for everyone, with a `CopyButton` beside every name, MAC address, IP address, gateway, and DNS server, and a `Hotspot` section that is read-only here (On or Off, the name, "Name hidden" yes or no, `http://10.42.0.1/` and `http://<local_name>/`); Task 9 replaces it for admins. The Device page appends `summaryFacts` to its facts and puts a "Network details" link to `/network` in the card's slot.

- [ ] **Step 1: Write the failing tests:**

```ts
// network-page.spec.ts
it('shows this device: its names, each link with its MAC and addresses, and the internet line')
it('says "On its hotspot (TM-AB12)" with the hotspot address when the radio runs the hotspot')
it('shows the joined network with its signal, gateway, and DNS servers')
it('leaves Ethernet out on a unit without it, and says "No built-in Wi-Fi radio" without one')
it('copies a MAC address when its Copy button is tapped')              // execCommand stubbed, as device-page.spec.ts does
it('shows a viewer the hotspot read-only, with no password row and no controls')
it("warns that the network state couldn't be read when NetworkManager didn't answer")   // readable: false
it('offers Try again when the page fails to load')
// router.spec.ts
it('lets a viewer open the Network page, and lists it in the menu after Device')
// network-summary.spec.ts
it('gives one line per connected link and none for a link that is down')
// device-page.spec.ts
it('adds a line per connected link and a link to the Network page')
it("still shows the card when the network state can't be read")
```

- [ ] **Step 2:** Run `npm test` in `tm-control/ui`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement**, after writing the "Network" design notes in `ui/README.md` (layout of the label and value rows at phone width, where Copy sits, how a read-only viewer's page differs).
- [ ] **Step 4:** Run `npm run build && npm test`. Expected: PASS. Screenshot the page in fake mode at phone and desktop width, as an admin and as a viewer, and fix what the review shows.
- [ ] **Step 5: Commit** ("Add the Network page with the unit's network details").

### Task 9: The hotspot's settings for admins

**Files:**
- Create: `tm-control/ui/src/modules/network/HotspotSettings.vue`, `HotspotField.vue`
- Modify: `tm-control/ui/src/modules/network/NetworkPage.vue`, `tm-control/ui/README.md`
- Create: `tm-control/ui/tests/hotspot-settings.spec.ts`

**Interfaces:**
- Consumes: `GET /api/v1/network/hotspot/password`, `POST /api/v1/network/hotspot`, `followJob`, `ConfirmDialog`, `session.status.hotspot`.
- Produces:
  - `HotspotField.vue`: a dialog with one text field. Props `{ title: string; label: string; warning: string; rule: (value: string) => true | string; confirmText: string }`, `v-model` for open, emits `save: [value: string]`. The field shows what is typed, and there is no field to type it again (decision 5); the button reads `confirmText` ("Change name", "Change password", "Set password") and stays disabled until the rule passes.
  - `HotspotSettings.vue`: props `{ hotspot: HotspotState; localName: string; onHotspot: boolean }`, emits `changed`. Rows: a switch labelled "Hotspot on"; the name with **Change**; the password as dots with **Show** (then **Hide**) and **Change**, or "None. Anyone nearby can join." with **Set a password** when `security` is `none`; a switch labelled "Hide the name"; the two addresses; and the visibility paragraph.
  - `NetworkPage.vue` shows `HotspotSettings` to admins (reloading the state on `changed`) and Task 8's read-only section to viewers, with "An administrator can change the hotspot here."

Exact words:
- Before a change to the name, password, or hidden setting while the hotspot is up: "The hotspot restarts, and phones on it are disconnected. Each phone must rejoin by hand."
- Turning off: the design's sentence (Global Constraints). Hiding: the design's sentence, then "On Android, add the network by hand and tick Hidden network, or the phone never connects."
- In the password dialog, above the restart warning: "Write the new password down before you save. Every phone needs it to rejoin."
- When `onHotspot`: each warning ends "You're on the hotspot now, so this page stops answering when you save."
- When the page loses the unit after such a change: "This page lost the unit, which is expected when your phone is on the hotspot. Join <name> again, then reload this page." For turning off: "The hotspot is off. Reach the unit on its Wi-Fi network or by Ethernet."
- Under the section: "A hotspot on a pole is visible to anyone passing, and public Wi-Fi maps record where network names are seen. Hiding the name reduces that; only turning the hotspot off prevents it."
- The rules' messages are Task 4's.

- [ ] **Step 1: Write the failing tests:**

```ts
it('shows the password only after Show, asks the device each time, and forgets it on Hide')
it('changes the name after a warning that phones must rejoin')                       // POST body { name: 'TM-ROAD' }
it('refuses a name over 32 bytes and a password under 8 characters before asking the device')
it('shows the new password as it is typed, in one field, and says to write it down')   // input type "text"; one field in the dialog
it('asks before turning the hotspot off, with the Ethernet warning')                 // POST body { enabled: false }
it('turns the hotspot on without asking')                                            // POST body { enabled: true }
it('warns that a hidden name can still be found and that Android needs Hidden network')  // POST body { hidden: true }
it('says to rejoin when the page loses the unit after a change that restarts the hotspot')
    // GET /jobs/{id} rejects with a network error: the rejoin text names TM-ROAD, and no error alert shows
it('adds that this page stops answering when it was opened over the hotspot')
it('reloads the state when the job succeeds, and shows the job log when it fails')
it('offers Set a password on a hotspot without one')
it('saves without the restart warning while the hotspot is not up')
```

- [ ] **Step 2:** Run `npm test`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** One change at a time: every control is disabled while a job runs. A failed job shows its log lines, as `EnteredSecret.vue` does; a log line ending `the settings are saved` gets "The settings were saved, but the hotspot didn't restart." above it. The name's bytes are counted with `TextEncoder`. Add the settings to the README's "Network" notes.
- [ ] **Step 4:** Run `npm run build && npm test`. Expected: PASS. Screenshot each dialog in fake mode at phone width and fix what the review shows.
- [ ] **Step 5: Commit** ("Let an admin change the hotspot's name, password, and visibility").

### Task 10: Docs

**Files:**
- Modify: `docs/use/wifi-hotspot.md`, `docs/use/device-health.md`, `docs/use/system-admin.md`, `docs/development/tm-control.md`, `docs/reference/network.md`, `CLAUDE.md`

- [ ] `wifi-hotspot.md`: a section "The Network page" (what it shows; who sees what; find the MAC address there for a network that admits listed devices only). "Turn the hotspot off" becomes steps on the page, with the warning. "Change the password" becomes steps on the page, says the hotspot restarts and each phone rejoins by hand, and keeps `sudo tm-control card` as the way to read a lost password over Ethernet; the `sudoedit` recipe and "A screen ... is planned" go. A new part on renaming and on hiding the name (still found by scanning; Android needs **Hidden network**). "A hotspot you set up by hand": setting a password is **Set a password** on the page. "Who can see the hotspot" gains the hidden option and that only off prevents it.
- [ ] `device-health.md`: the Hotspot row's fix is the **Set a password** link; the Device page's part says the card lists each connected link's address and links to the Network page; the first list names the Network page.
- [ ] `system-admin.md`: where it lists what the secrets directory holds, say the Network page shows the hotspot password to admins.
- [ ] `reference/network.md`: one sentence that the Network page shows the unit's addresses.
- [ ] `docs/development/tm-control.md`: "The Network module and the hotspot" gains the three routes, `state.py`, the job (request shape, the order file then profile, when it restarts), the lock shared with the retry, and that tm-control reads the hotspot password file for admins only; the jobs table gains `tm-job-network`; the polkit sentence names it.
- [ ] `CLAUDE.md`: `tm-control/`'s line gains the Network page (`modules/network`, the `/network` routes); the tm-control install bullets gain the job and the lock; the secrets paragraph says the hotspot password is read by `GET /network/hotspot/password` for admins and written only by `tm-hotspot-setup` and `tm-job-network`.
- [ ] Run `~/.venvs/tm-docs/bin/mkdocs build --strict`. Expected: no warnings.
- [ ] Commit ("Document the Network page and the hotspot's settings").

### Task 11: Bench run

Through `tmdev.py check start|item|end` from the worktree (`check start --src <worktree>`), one host at a time, with the off-device checks logged through `tmdev run local`. Ask before a reboot. Passwords are throwaways generated on the Pi and compared by hash, never printed.

- [ ] Off-device checks (Global Constraints), logged.
- [ ] First Pi (installed from #290's branch): a full `tmdev deploy <host>`; second Pi: `tmdev deploy <host> -- -t tm-control`. Then `tmdev test <host>` on both and `tmdev test <host> --disruptive` on one.
- [ ] Over Ethernet, as an admin, with the second Pi as a scripted station on the hotspot:
  1. The page's MAC and IP addresses match `ip -br addr` and `/sys/class/net/*/address`.
  2. Rename: the job succeeds, the station drops, a scan from the second Pi shows the new name, and the page shows it.
  3. Password: the station rejoins with the new one and not with the old; the file is 0640 root and the code group; the sha256 of `sudo tm-control card --json`'s password equals the file's.
  4. Hide: a scan shows the hotspot without its name; un-hide brings the name back.
  5. Off: the radio is idle, the Status page says "Off by choice", a retry run logs `hotspot-off`, and it stays off after a reboot and after `tmsetup.sh -t wifi`. On: the hotspot is up within the job.
  6. With the unit on a saved network (the second Pi's throwaway hotspot): a rename succeeds with "the change applies when the hotspot next starts", and the hotspot comes up under the new name when that network goes away.
  7. The lock: give the unit a saved network with a wrong password, start `tm-network-retry.service` so a join is under way, and POST "off" during it: the job refuses with "try again in a minute", and the hotspot is back afterwards.
  8. As a viewer: no password, no controls; `GET /api/v1/network/hotspot/password` is 403.
- [ ] Phones, by the maintainer (`manual` items): on the Pixel 7 in the sign-in window and on the iPhone in a browser, rename the hotspot from the hotspot itself: the page says to rejoin, the phone rejoins by hand under the new name, and the page shows it. **Show** shows the password, and **Copy** copies a MAC address, in the Android sign-in window and on the iPhone.
- [ ] Restore both Pis (hotspot on, its installed name, not hidden, no saved networks, radio as found) and record it. End the check.
- [ ] Fix what the bench finds, each fix with its test, and re-run the items it touches.

### Task 12: Final review and the PR

- [ ] Whole-branch review in a fresh context on the most capable model: the diff against the base, this plan, the design's sections 2 and 5, and the six Review Focus lines.
- [ ] Copy this plan to `design/plans/2026-11-10-network-page.md` and commit it ("Add the Network page plan").
- [ ] Draft the PR for the maintainer to read before it is pushed. Base: `feature/wifi-hotspot/289` while #290 is open, else `dev`. The template filled in: the release-note paragraph ("The control app has a Network page. It shows the unit's MAC and IP addresses, gateway, DNS servers, and whether the internet is reachable. An admin can read the hotspot's password there, rename the hotspot, change its password, hide its name, or turn it off, without SSH."), the decisions to look at (2, 3, 5, 6), "Limits" (IPv4 only; joining a Wi-Fi network from the page is planned; a change made from the hotspot itself ends that page's connection), the bench summary with device names replaced, the docs pages changed, and the "AI assistance" section. `PUBLIC push →` before the push; the stub issue is closed by hand when the PR merges into `dev`.

