# Wi-Fi plan 1: the hotspot that is always there, the radio rule, and the sign-in window

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every unit runs its own password-protected hotspot whenever its Wi-Fi radio isn't on a known network, a phone that joins it gets the control app in the phone's sign-in window, hotspot phones reach only the unit, and the old Wi-Fi check scripts are gone. No settings screen yet: the hotspot runs with its defaults.

**Architecture:**
- NetworkManager does the fallback itself: the installer creates (or adopts) a profile `tm-hotspot` with `autoconnect yes` and a negative `autoconnect-priority`, at the fixed address `10.42.0.1/24`. A root helper script, `tm-hotspot-setup`, holds the create/adopt/ensure logic so it can be tested off-device; the installer only calls it.
- A second root script, `tm-network-retry`, runs from a timer (90 s after boot, then every 5 minutes) and covers what NetworkManager doesn't: it starts the hotspot when the radio is idle, and moves from the hotspot to a saved network that is in range while no phone is joined, with a backoff for networks that fail.
- The sign-in window is one dnsmasq line (every name resolves to the unit) and one nginx rule (a request that arrives on the hotspot address with a foreign `Host` gets a 302 to `http://10.42.0.1/`). An nftables table, loaded by its own unit before NetworkManager starts, drops all forwarding to and from the hotspot's phones.
- `sudo tm-control card` is the one place to read a unit's hotspot name and password and its setup code: a root-only command, shown on the terminal at the end of a local install and never written to the installer's log.
- tm-control stays unprivileged and read-only here: a `network` module with four Status checks read through `nmcli` and `iw`, and `GET /setup/status` says when the page was reached on the hotspot address so the login and setup pages can show a note.

**Tech Stack:** Ansible (the tmsetup role), Bash (`tmsetup.sh`), Python 3 standard library (the two root scripts), NetworkManager 1.52 (`nmcli`), `iw`, nftables, dnsmasq (NetworkManager's own), nginx, Python 3.11 + FastAPI (tm-control), Vue 3 + Vuetify 3 + TypeScript (Vitest), Material for MkDocs, the dev-Pi tooling (`script/devpi/tmdev.py`). No new Python or npm dependency.

**Spec:** the design summarised in the stub issue, [#289](https://github.com/glossyio/traffic-monitor/issues/289). Its "(maintainer)" items stand; its "(call)" items are kept or changed in "Decisions" below, which says why. Where this plan goes beyond the design, say so in the PR rather than picking silently. Joining a network and the Network page are planned separately.

**Status:** written 2026-11-09 against `dev` at `e1b353f` (the merge of PR 286). No open PRs, so nothing to stack on. Tasks 0 and 1 done 2026-11-10: the stub issue is [#289](https://github.com/glossyio/traffic-monitor/issues/289), the branch `feature/wifi-hotspot/289` is in the worktree `../tm-wifi-hotspot` at `e1b353f`, and the bench answers are in the "Bench answers" note at the top of each task they change. Branch: `feature/wifi-hotspot/<n>`, where `<n>` is the public stub issue Task 0 opens.

**Decisions made while writing this plan** (calls made here on 2026-11-09, open to change; Task 1 confirms the ones marked "bench" before any code depends on them):
1. **The hotspot profile is made by a root helper script, not by Ansible tasks.** Adoption (which access-point profile, in what order, when the password is copied) is an algorithm; as Ansible loops it can't be tested off-device. `tm-hotspot-setup` is about 150 lines of standard-library Python, tested against a fake `nmcli` the way `tm-job-system-password` is tested against a fake `chpasswd`. The installer runs it and reads one JSON line back.
2. **The retry script also starts the hotspot when the radio is idle.** The design leaves the fallback to NetworkManager's autoconnect and adds "a small retry timer". NetworkManager stops retrying a profile after repeated failures, so the timer's script covers that case too: radio idle and the hotspot not turned off means "bring the hotspot up". This is also what the Status check's "Restart the hotspot" button runs, and it makes the design's fallback (a root service that holds the rule) a matter of one profile setting if Task 1 finds the boot order unreliable.
3. **The timer first runs 90 s after boot**, then every 5 minutes. That bounds the case the design left untested (the hotspot winning the first autoconnect before the first scan finishes) to 90 s on a unit nobody has joined.
4. **The firewall rule is scoped to the hotspot's subnet as well as its interface, and stays loaded.** The bench rule was `iifname "wlan0" drop; oifname "wlan0" drop`. Left in place while `wlan0` is the unit's uplink, the second half would drop the pod's own outbound traffic (ThingsBoard uploads, Frigate+), because container traffic leaves through the forward hook. With `ip saddr`/`ip daddr 10.42.0.0/24` added, the table can be loaded once at boot, before NetworkManager, by its own unit; there is no window where the hotspot is up without it, and tm-control can see the unit's state. Limit: on a Wi-Fi network that itself uses `10.42.0.x`, containers can't reach that network's other hosts. (bench)
5. **"Built-in radio only" is the name `wlan0` plus a guard.** The profile, the firewall rule, and the scripts name `wlan0` (`tmsetup_wifi_device`). The scripts and the Status check look at `/sys/class/net/wlan0/device/subsystem`; when it is a USB device they leave the hotspot off and the check says so. A USB adapter then can't take the hotspot's place; making the hotspot follow the built-in radio to another name is not built.
6. **The Wi-Fi country is `tmsetup.sh -w CODE`.** `-C` takes booleans only, so the "custom variable" is a new option beside `-z TIMEZONE`, setting `tmsetup_wifi_country`. A local run without `-w` asks when the country isn't set (`iw reg get` shows `country 00`), with `US` on Enter; `-y` and remote runs don't ask, and the role sets `US` only when the device has none.
7. **tm-control reads Wi-Fi state with `nmcli` and the country with `iw reg get`.** `nmcli` talks D-Bus and works in today's sandbox. `iw` needs a netlink socket, so the unit's `RestrictAddressFamilies` gains `AF_NETLINK`. The alternative, the kernel command line, shows the country only after a reboot. (bench)
8. **The page knows it is on the hotspot from nginx.** nginx sets `X-TM-Hotspot: 1` on API requests whose `$server_addr` is the hotspot address (and clears whatever the client sent); `GET /setup/status`, which both pages already load, gains `hotspot: {local_name} | null`. A phone that reaches the unit by name on the hotspot gets the note too.
9. **"Restart the hotspot" starts `tm-network-retry.service`** through the existing `POST /services/{unit}/restart`, which gains a short list of units a check's fix may start that aren't rows in the Services list. The polkit unit list gains that one name. The firewall unit is not in the list: polkit's verbs include `stop`.
10. **The check model has no "info" status**, so the design's info rows ("off by choice", "no saved networks", every `network.internet` result) are `ok` with the detail carrying the words.
11. **The hotspot password is generated by the helper, not by `tasks/secrets.yml`'s loop**, because adoption has to look at the device before a password exists. It still lives in `{{ tmsetup_secrets_dir }}/hotspot_password` (root, code group, 0640). An empty file means "adopted without a password; leave its security alone".
12. **The retry's backoff state is in `/run/traffic-monitor/network-retry.json`** (root-owned, world-readable, no secret in it). It is lost at reboot, when NetworkManager tries every saved network itself anyway.
13. **The hotspot password and the setup code are read in one place, `sudo tm-control card`, and the installer never logs the password.** (maintainer, 2026-11-09) The design first had the installer print both in its closing notice. Unlike the setup code, the hotspot password keeps working, and `tmsetup.sh` copies its output to `~/tmsetup-*.log`. So: a root-only command prints the unit's card (name, addresses, hotspot name and password, setup code or "already claimed"), with `--json` for a seller's label script. A local `tmsetup.sh` run shows the card on the terminal at the end, written to `/dev/tty` so it bypasses the log; a remote run and the log get one line saying how to show it. The existing setup-code notice stays as it is (the code works once) and gains that line.
14. **A fresh profile sets no channel** (NetworkManager's 2.4 GHz default) and `802-11-wireless.cloned-mac-address permanent`.
15. **The generated password is 12 characters in three groups, `XXXX-XXXX-XXXX`, and the hyphens are part of it.** (maintainer, 2026-11-09) The design first had 10 characters. A WPA2 password can be attacked offline once someone records a phone joining; 10 characters from a 32-symbol alphabet is 50 bits, within reach of a rented GPU rig in about a month, and 12 is 60 bits, a thousand times that. A phone's Wi-Fi dialog takes the password exactly as typed, so unlike the setup code the hyphens can't be decoration: the password is the 14 characters as printed.
16. **firewalld is its own design, after this.** (maintainer, 2026-11-09) The maintainer wants the device's firewall to be firewalld, so Cockpit can show and manage it. That is a device-wide change (every LAN port declared before it starts, Podman's networking under it, a guard against locking a unit out) and gets its own design and PR; the hotspot's rule then becomes a firewalld zone and this plan's nftables unit is retired. Here the rule stays a table of its own, which firewalld leaves alone. It is planned. Task 1 J is the spike that design needs.


**Where `dev` at `e1b353f` leaves the things this plan touches:**
- Role: `tasks/wifi_setup.yml` (tag `wifi`) copies `utils/88-z-wifi-powersave-off.conf` and `utils/82-nm-connectivity-check.conf` into `/etc/NetworkManager/conf.d/` (both notify `Restart NetworkManager service`), adds the sudoers entry named `{{ tmsetup_codeowner }}` (`/usr/bin/systemctl restart NetworkManager.service`, the only sudoers entry in the role), and the cron entry "Traffic Monitor Wifi Check". `tasks/base_setup.yml` copies `utils/` to `{{ tmsetup_codedir }}/utils/`. `tasks/set_vars.yml` sets `tmsetup_raspberry_pi_serial` under `always`. `tasks/secrets.yml` (under `always`) creates `{{ tmsetup_secrets_dir }}` root:codegroup 0750. `tasks/tm-control_setup.yml` copies all of `tm-control/jobs/` to `{{ tmsetup_libexec_dir }}` (root, 0755) under the tm-control tags. `tasks/tm-control_service.yml` renders the polkit rules from `tmsetup_tm_control_polkit`, the units, and the manifest fact; `tasks/main.yml` ends with "Show the setup code" (a `debug`, when `tmsetup_tm_control_claim_register.stdout | default('') == 'unclaimed'`). `tasks/start_services.yml` runs under `wifi` too.
- `tmsetup.sh`: options `fhkKTuvya:d:g:H:l:L:o:t:z:C:`; `_add_var key val`; `_confirm_cont` reads with `read -p`; `_CONFIRM=true` under `-y`; `_tmsetup_local` and `_tmsetup_remote`; `--tags <tag>` is appended to `_EXTRA_ARGS` per `-t`.
- nginx: `container/revproxy/nginx.conf.j2` is the whole `http` block with one `server` (`listen 80 default_server`, `absolute_redirect off`, the locations include); it renders today with no variables (`script/tests/test_tmsetup_templates.py` lines 198 and 207, and `test_nginx_config_parses.py::render_config` with `ROLE_VARS`). `tm/locations/tm-control-api.conf.j2` has `location /api/` with `proxy_set_header X-TM-Required-Role ""`. revproxy runs on the host network, so `$server_addr` is the address the request arrived on.
- tm-control backend: `modules/__init__.py` (`Module(id, router, root_router, check_groups)`, `MODULES`), `core/checks.py` (`Check(id, title, status, detail, fix)`, `Fix(kind="restart"|"rescan"|"link"|"hint", text, unit, href)`, statuses `ok|warn|error|unknown`, `CheckGroup(id, title, fns)`, `Context.probe(key, fn)`), `modules/time/` as the smallest module with a check group, `adapters/command.py::run(argv, timeout=…) -> CommandResult(returncode, stdout, stderr, timed_out)`, `adapters/systemd.py::show_unit(name, properties)`, `modules/services/units.py` (`UNITS`, `units_for`, `restart_fix`, `restart_or_log`) and `services/router.py::restart` (404 unless the unit is a restartable row), `modules/setup/router.py::status` (open; returns `claimed`, `eula`, `theme`), `modules/system/router.py::hostname(app_state)`, `core/manifest.py` (`Manifest` with `frigate: FrigateInfo`; unknown keys ignored), `tests/fixtures/manifest.json` and `status_fake.json` (fake mode's whole status report), `tests/fixtures/run_job.py`. The unit has `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6` (pinned by `test_tm_control_runs_as_the_code_owner_in_a_sandbox`); the polkit list is pinned by `test_polkit_allowlist_covers_the_traffic_monitor_units_only`; the manifest's fields by `script/tests/test_tm_control_install.py::test_manifest_has_the_same_fields_as_tm_controls_fixture`.
- tm-control UI: `stores/session.ts` loads `GET /api/v1/setup/status` into `session.status` (`SetupStatus` in `api/types.ts`); `modules/auth/LoginPage.vue`, `modules/setup/SetupPage.vue`; `tests/fake-api.ts::status(claimed, accepted)`, `tests/mount.ts`; `modules/status/restarts.ts::restartFor(unit)` has a default for an unknown unit.
- Docs: `docs/reference/network.md` (line 18 already says a device hosting its own Wi-Fi answers DHCP and DNS), `docs/reference/tmsetup.md` (the tag table, line 49 `wifi`), `docs/use/home-page.md` line 24, the FAQ's Android 17 entry, `docs/use/device-health.md` (the Status groups), `docs/development/tm-control.md`. Nav section "Use the device"; the `llmstxt` plugin already lists `use/*.md`.
- Device tests: `script/devpi/tests/` (`conftest.py`: `host`, `expect`, `codedir`, `codeowner`, `address`, `tm_login`), `test_services.py` (polkit and unit tests), `test_web.py`.

## Global Constraints

- The fixed values, copied from the design: profile `tm-hotspot`; device `wlan0`; address `10.42.0.1/24`; name `TM-` plus the last four characters of the Pi's serial number, upper case; password 12 characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` in three hyphenated groups, `XXXX-XXXX-XXXX` (decision 15); WPA2 personal (`wpa-psk`, `rsn`, `ccmp`); 2.4 GHz; IPv6 off on the hotspot; `autoconnect-priority -100`.
- No Wi-Fi password, of the hotspot or of a saved network, in any log line, task output, test name, state file, or API answer. Every Ansible task that handles one sets `no_log: true`. Tests and the bench use placeholders.
- Nothing here restarts NetworkManager or any service because the internet is unreachable.
- The installer never re-activates a hotspot that is up, and a `-t wifi` run that changes nothing leaves a joined phone joined.
- Root scripts: standard library only, no `tm_control` imports, argv lists (never a shell), run as `/usr/bin/python3 -EP` from the root-owned `{{ tmsetup_libexec_dir }}`.
- The role: task names `TMSetup - <Component> - <Action>`, `tmsetup_` variables, registered results ending `_register`, FQCN modules, `become: true` per task, two-space YAML.
- Docs follow "Writing docs" in `docs/development/contributing.md`; the new page is in `nav:`; `mkdocs build --strict` passes. Don't name later features; say "planned" at most. Nothing public names a device or its address.
- Commits end with the trailer block from the public repo's CLAUDE.md, not `Co-Authored-By`. Never run `tmsetup.sh` on a dev machine. Say `PUBLIC push →` before any push.
- Off-device checks before the PR: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`, `cd tm-control/ui && npm test && npm run build`, the Ansible syntax check, the Jinja parse of every `.j2`, `bash -n script/tmsetup.sh`, `mkdocs build --strict`.

## Review Focus

1. **An upgrade run over a hand-made hotspot that someone is installing through**: the profile is adopted and changed on disk, the hotspot is not re-activated, and its name and password still work. Task 3's `test_an_active_adopted_hotspot_is_changed_but_never_reactivated`.
2. **The radio is the unit's uplink** (`wlan0` joined to a Wi-Fi network, no Ethernet): container traffic out through `wlan0` still passes the hotspot's firewall table. Task 4's `test_the_firewall_drops_only_the_hotspot_subnet`, and the bench item that checks it for real.
3. **A saved network whose password changed**: one failed join per run at most, the hotspot comes back, and the next tries wait 5, 15, then 60 minutes. Task 5's `test_a_failed_join_backs_off_and_the_hotspot_returns`.
4. **A request on the hotspot address for the API with a foreign `Host`** (a phone's connection test, or a page on another site aiming at `10.42.0.1`): redirected like any other path, never proxied; the same `Host` on the Ethernet address is untouched. Task 6's `test_a_foreign_host_is_redirected_only_on_the_hotspot_address`.
5. **`nmcli` or `iw` missing, slow, or printing something unexpected** (no Wi-Fi device, NetworkManager stopped, a network name with a colon or a backslash in it): every network check is `unknown` with a plain sentence, and the rest of the report is unaffected. Task 7's `test_unreadable_wifi_state_is_unknown_not_an_error` and `test_network_names_with_colons_are_read_whole`.
6. **A phone is joined when the timer fires**: no scan, no switch. Task 5's `test_nothing_is_scanned_or_switched_while_a_phone_is_joined`.

---

### Task 0: Base branch and the public stub issue

- [x] `git fetch origin`, confirm `origin/dev` is still `e1b353f` or later with no open PR touching `wifi_setup.yml`, `tmsetup.sh`, `nginx.conf.j2`, or `modules/services/`; `gh pr list --state open`. If something overlaps, stop and say so.
- [x] Draft the public stub issue for the maintainer to read before it is posted: title "Wi-Fi hotspot on every unit, with a sign-in window", three sentences from the design's Problem and goals 1, 2, and 5. Say `PUBLIC push →` and post it only when the maintainer says so.
- [x] Work in a worktree: `git worktree add ../tm-wifi-hotspot -b feature/wifi-hotspot/<n> origin/dev`. Never switch the shared checkout.

### Task 1: Bench spike: what the design left to confirm

No repo code. Through `tmdev.py check start|item|end` from the worktree, one host at a time (`script/devpi/README.md`). Throwaway names and passwords only; nothing printed that is a password. Each item records the command and its output, and what the plan does if the answer is the other one. Restore both Pis afterwards and say so in the record.

- [x] **A. Boot order.** Give a bench Pi a hotspot profile as in Global Constraints (by hand, `nmcli connection add`) and one saved network in range (a second Pi's hotspot or a phone hotspot). Reboot five times. Record which the radio is on 60 s after boot each time, and how long the hotspot takes to start with the saved network switched off. *If the hotspot wins while the network is in range:* keep the design's build; decision 3's 90 s timer corrects it; record the measured time for the docs. *If the hotspot doesn't start by itself at all:* set `autoconnect no` on it in Task 3 and let the retry script own the start (decision 2); tell the maintainer before going on.
- [x] **B. The country.** On a unit with none set: `iw reg get`; `sudo raspi-config nonint get_wifi_country; echo $?`; `sudo raspi-config nonint do_wifi_country US`; then `iw reg get`, `rfkill list wifi`, `nmcli radio wifi`, and which files changed (`/boot/firmware/cmdline.txt`, `/etc/wpa_supplicant/wpa_supplicant.conf`). Does the hotspot start without a reboot? *If a reboot is needed:* the role's "Set the Wi-Fi country" task notifies `TMSetup - Flag for reboot`.
- [x] **C. `iw` and `nmcli` inside tm-control's sandbox.** `sudo systemd-run --pipe --wait -p User=<code owner> -p NoNewPrivileges=yes -p ProtectSystem=strict -p "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" iw reg get` (expect a failure), the same with `AF_NETLINK` added (expect the country), and with `nmcli -t -f GENERAL.STATE,GENERAL.CONNECTION device show wlan0`, `nmcli -g connection.autoconnect,802-11-wireless.ssid,802-11-wireless-security.key-mgmt connection show tm-hotspot`, and `nmcli -s -g 802-11-wireless-security.psk connection show tm-hotspot` (expect no password for a non-root user). *If `iw` still fails with `AF_NETLINK`:* `wifi_country()` reads `cfg80211.ieee80211_regdom=` from `/boot/firmware/cmdline.txt` instead, and decision 7's sandbox change is dropped.
- [x] **D. nginx on the arrival address.** With the hotspot up and the map from Task 6 pasted into the device's `nginx.conf` by hand (restore it after): `curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' -H 'Host: connectivitycheck.gstatic.com' http://10.42.0.1/generate_204` (expect `302 http://10.42.0.1/`), the same against the Ethernet address (expect 200), and with `Host: 10.42.0.1`, the hostname, and `<hostname>.local` against `10.42.0.1` (expect 200). Then both phones: the sign-in window still opens.
- [x] **E. The firewall table.** Load Task 4's table by hand. From a phone on the hotspot: the control app opens; a host on the wired network and the pod's bridge address don't answer. Then put `wlan0` on a Wi-Fi network with Ethernet unplugged (reach the Pi over that Wi-Fi) and run `sudo podman exec node-red-tm wget -q -O- http://connectivity-check.ubuntu.com` (expect an answer). `sudo nft list ruleset | grep -c tm_hotspot` after a reboot with the unit enabled, and after `systemctl restart traffic-monitor.service` (the table survives Podman's own rules). *If the pod loses its way out:* stop; decision 4 needs the maintainer.
- [x] **F. The retry's tools.** As root with the hotspot up and one phone joined: `iw dev wlan0 station dump | grep -c ^Station` (expect 1), `iw dev wlan0 scan | grep 'SSID:'` (expect the neighbours; note the seconds and whether the phone stays joined). With no phone: `nmcli --wait 45 connection up <saved network>` with a wrong password; record the seconds to fail and whether NetworkManager brings the hotspot back by itself and how fast. From an idle radio: `nmcli connection up tm-hotspot`.
- [x] **G. The MAC address.** `nmcli -g 802-11-wireless.cloned-mac-address connection show <an Imager-made profile>`, `nmcli -g GENERAL.HWADDR device show wlan0` while idle, on a network, and on the hotspot, against `ethtool -P wlan0`. Record for plan 2; nothing here depends on it.
- [x] **H. The dnsmasq file.** Add `/etc/NetworkManager/dnsmasq-shared.d/tm-hotspot.conf` while the hotspot is up: confirm names don't resolve to the unit until the hotspot next starts, and do after.
- [x] **I. The iPhone and `http://10.42.0.1/`** (the design's open question 1): fresh join, Safari first by address, then by name, then a second browser; record each result and the order.
- [x] **J. firewalld, for the design that follows** (decision 16; nothing in this plan depends on the answers). On one bench Pi, with the hotspot up and Task 4's table loaded by hand: record the versions of `firewalld`, `netavark`, and `podman` the OS offers, then `sudo apt install firewalld` (Debian starts it at once with the `public` zone, which keeps SSH). Record, each with its command and output:
  1. `firewall-cmd --get-active-zones`: which zone Ethernet, the hotspot, and the Podman bridge land in (expected and unconfirmed: the hotspot in NetworkManager's `nm-shared`).
  2. From a computer on the wired network: which of ports 80, 9090, 8554, 1883, and the `.local` name still answer.
  3. From a phone on the hotspot: whether the sign-in window still opens.
  4. The pod: `sudo podman exec node-red-tm wget -q -O- http://connectivity-check.ubuntu.com`, and whether Frigate still reads the camera stream from the host, both again after `systemctl restart traffic-monitor.service` and after `sudo firewall-cmd --reload`.
  5. `sudo nft list tables`: whether `inet tm_hotspot` survives the install and a reload. With that table deleted by hand: whether a hotspot phone reaches a wired host (does firewalld refuse the forwarding by itself?).
  6. A hand-made zone `tm-hotspot` (services `http`, `ssh`, `dhcp`, `dns`, `mdns`; ports 9090 and 8554) set on the profile with `connection.zone`: whether the sign-in window opens again after the hotspot restarts.
  7. Whether Cockpit's Networking page now shows its firewall section, and what it lists.

  Then `sudo apt purge firewalld`, reboot, and confirm ports 80 and 9090 answer and the pod is up. Keep a summary of the answers for the firewalld design.
- [x] End the check. Write the answers that change a later task into this plan's "Bench answers" note at the top of that task before starting it.

**Bench record (2026-11-10):** three checks, one host at a time, from the worktree at `e1b353f`: `20261110T045947Z` (A, C to I; pass, 17 items), `20261110T054217Z` (B, on the second Pi; pass), `20261110T054518Z` (J; "fail" only because J2 and J3 record firewalld's expected breakage as fails, the convention of the design's bench). The second Pi served as the "saved network" (a throwaway hotspot on `10.43.0.1/24` sharing its Ethernet, which also gave E its Wi-Fi uplink) and as a scripted hotspot station for E, F, and J (probes bound to `wlan0`). Phones: Pixel 7 on Android 17, iPhone on iOS 18.7. Throwaway passwords were generated on the Pis and never printed. Both Pis were restored and rebooted (no Wi-Fi profiles, radio off as found, original `cmdline.txt` and `nginx.conf`, firewalld and its six dependencies purged, bench files deleted); recorded as the last item of the third check.

Answers in short (details in each task's note):
- **A.** With a saved network in range the unit joined it at boot 5 times out of 5. With none, NetworkManager started the hotspot about 13 s after boot; when a joined network vanished, about 70 s later. NetworkManager never leaves the hotspot for a saved network that comes back (it doesn't scan in AP mode). Decision 2's fallback (`autoconnect no`) is not needed; decisions 2 and 3 stand.
- **B.** Setting the country needs no reboot, and also turns the radio on. **Not having a country does not block the hotspot**: it started on channel 6 on the world domain. The design's sentence to the contrary was wrong on this OS and is corrected; Task 7's row is a warning now (maintainer, 2026-11-10).
- **C.** `AF_NETLINK` is needed and enough. Decision 7 stands.
- **D.** The map works as written, including upper case and `:80` in the Host. Both phones' sign-in windows opened.
- **E.** The scoped table blocks a hotspot station from the wired network, the internet, and the pod, and leaves the pod's own way out over Wi-Fi alone. It loads before NetworkManager and survives a pod restart. Decision 4 confirmed. Without it, a hotspot station reached Node-RED at the pod's address.
- **F.** Station count and AP-mode scan work as planned; a wrong password fails in 25.4 s, exit 4, and NetworkManager restores the hotspot by itself about 1 s later.
- **G.** The built-in MAC is used everywhere, with or without `cloned-mac-address`. No Imager-made profile was available; plan 2 should check one.
- **H.** The dnsmasq file applies at the hotspot's next start, not before. No handler, as planned.
- **I.** The iPhone's Firefox opened `http://10.42.0.1/` and the `.local` name after the sign-in window. Safari wasn't on the bench iPhone, so the design's open question 1 is answered for Firefox only.
- **J.** For the firewalld design: installing firewalld closes 80, 9090, 8554, and mDNS on the LAN at once, puts the hotspot in `nm-shared` (no HTTP, so no sign-in window), and does not stop hotspot forwarding by itself; a hand-made zone restores the sign-in window; the pod and Frigate's stream are unaffected.

### Task 2: Role variables, packages, and the Wi-Fi country

**Bench answers (Task 1 B, 2026-11-10):**
- `raspi-config nonint do_wifi_country XX` applies the country at once (`iw reg set`) and rewrites `cfg80211.ieee80211_regdom=` in `/boot/firmware/cmdline.txt`. No reboot is needed, so the set task notifies no reboot handler. There is no `wpa_supplicant.conf` on Trixie.
- It also switches the radio on (`nmcli radio wifi on` while NetworkManager runs) and writes `WirelessEnabled=true` and the rfkill state. That is harmless (it runs only when the country changes, and "hotspot off" is the profile's autoconnect, not the radio), but don't write a test that expects the radio to stay off after it.
- `get_wifi_country` reads only `cmdline.txt` here (no crda), falling back to `iw reg get`; with no country it exits 1, as `wanted_country` expects.
- `iw reg get` prints a `global` block (`country 00: DFS-UNSET` when unset) and always a second `phy#0` block with `country 99: DFS-UNSET` (the radio regulates itself). `_ask_wifi_country`'s `^country [A-Z]{2}:` matches only the global line, as wanted.
- With no country the hotspot still starts (world domain, channel 6), so the prompt is about the legal setting, not about the hotspot working. Its words stay: "A Wi-Fi hotspot needs to know which country it is in."

**Files:**
- Modify: `script/ansible/roles/tmsetup/vars/main.yml`, `script/ansible/roles/tmsetup/defaults/main.yml`
- Modify: `script/ansible/roles/tmsetup/tasks/wifi_setup.yml`
- Modify: `script/tmsetup.sh`
- Test: `script/tests/test_tmsetup_tasks.py`, `script/tests/test_tmsetup_script.py`

**Interfaces:**
- Produces, in `vars/main.yml`:
  ```yaml
  # The hotspot (tasks/wifi_setup.yml): the built-in radio it runs on, its NetworkManager profile, and its fixed
  # address. nginx's sign-in rule, the firewall table, and tm-control's manifest read the same values.
  tmsetup_wifi_device: wlan0
  tmsetup_hotspot_profile: tm-hotspot
  tmsetup_hotspot_address: 10.42.0.1
  tmsetup_hotspot_subnet: 10.42.0.0/24
  tmsetup_wifi_packages:
    - iw
    - nftables
    - dnsmasq-base
  ```
  and in `defaults/main.yml`: `tmsetup_wifi_country: ''` with the comment "Two-letter Wi-Fi country (tmsetup.sh -w). Empty: keep the device's, or set US when it has none."
- Produces, at the top of `wifi_setup.yml`, three tasks: "TMSetup - WiFi Setup - Install the Wi-Fi tools" (`ansible.builtin.apt`, `tmsetup_wifi_packages`, `state: present`); "TMSetup - WiFi Setup - Read the Wi-Fi country" (`raspi-config nonint get_wifi_country`, `changed_when: false`, `failed_when: false`, register `tmsetup_wifi_country_register`); "TMSetup - WiFi Setup - Set the Wi-Fi country" (`raspi-config nonint do_wifi_country <wanted>`, run when `<wanted>` differs from what was read). `<wanted>` is `tmsetup_wifi_country | upper` when it is set; else what was read when the read's `rc` is 0; else `US`.
- Produces, in `tmsetup.sh`: option `-w CODE` (getopts string gains `w:`; refused with "Invalid Wi-Fi country: <CODE>. Use a two-letter code such as US or GB." and exit 1 unless it matches `^[A-Za-z]{2}$`; upper-cased; `_add_var tmsetup_wifi_country`; sets `_WIFI_COUNTRY`), a `_usage` line `"-w CODE" "Set the Wi-Fi COUNTRY, a two-letter code (asked for when the device has none; default US)"`, and `_ask_wifi_country`, called in `_tmsetup_local` after the continue prompt. It returns at once when `_WIFI_COUNTRY` is set, when `_CONFIRM` is true, when `_EXTRA_ARGS` has `--tags` without `--tags wifi`, or when `iw reg get` prints a line matching `^country [A-Z]{2}:`. Otherwise it prints "A Wi-Fi hotspot needs to know which country it is in." and reads "Wi-Fi country code [US]: " until the answer is empty (nothing added; the role's `US` applies) or two letters.

- [ ] **Step 1: Write the failing tests**

`test_tmsetup_tasks.py`:
```python
def wifi_tasks():
    return {task["name"]: task for task in load_role_yaml("tasks/wifi_setup.yml")}

def wanted_country(given, read_rc, read_stdout):
    task = wifi_tasks()["TMSetup - WiFi Setup - Set the Wi-Fi country"]
    # the task's vars: block holds the expression under tmsetup_wifi_country_wanted
    return evaluate(task["vars"]["tmsetup_wifi_country_wanted"], tmsetup_wifi_country=given,
                    tmsetup_wifi_country_register={"rc": read_rc, "stdout": read_stdout})

def test_a_given_country_wins_and_is_upper_cased():
    assert wanted_country("gb", 0, "US") == "GB"

def test_the_devices_own_country_is_kept():
    assert wanted_country("", 0, "DE") == "DE"

def test_a_device_without_a_country_gets_us():
    assert wanted_country("", 1, "") == "US"

def test_the_wifi_tools_are_installed_before_anything_uses_them():
    names = list(wifi_tasks())
    assert names[0] == "TMSetup - WiFi Setup - Install the Wi-Fi tools"
```
`test_tmsetup_script.py` (run as the normal user with `-T` last, which prints the tags and exits 2 once the options before it parsed): `test_a_wifi_country_must_be_two_letters` (`-w USA -T` exits 1 with "Invalid Wi-Fi country: USA" and no "Valid Tags"), `test_a_two_letter_wifi_country_is_accepted` (`-w gb -T` exits 2 with "Valid Tags"), `test_usage_lists_the_wifi_country_option` (`-h` output has `-w CODE`).

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest script/tests/test_tmsetup_tasks.py script/tests/test_tmsetup_script.py -q -k "country or wifi"`
Expected: FAIL

- [ ] **Step 3: Add the variables, the three tasks (the set task with `vars: tmsetup_wifi_country_wanted`), and the option and prompt in `tmsetup.sh`.** `_ask_wifi_country`'s locals are plain lowercase and declared `local`.

- [ ] **Step 4: Run the role tests and the shell and syntax checks**

Run:
```bash
python -m pytest script/tests -q
bash -n script/tmsetup.sh
(cd script/ansible && ansible-playbook -i localhost setup.yml --syntax-check </dev/null)
```
Expected: PASS, no output, "playbook: setup.yml".

- [ ] **Step 5: Commit**

```bash
git add script/ansible/roles/tmsetup/vars/main.yml script/ansible/roles/tmsetup/defaults/main.yml script/ansible/roles/tmsetup/tasks/wifi_setup.yml script/tmsetup.sh script/tests
git commit -m "Set the Wi-Fi country at install, asked for when the device has none"
```

### Task 3: `tm-hotspot-setup`: create, adopt, and keep the hotspot profile

**Files:**
- Create: `tm-control/jobs/tm-hotspot-setup`
- Create: `tm-control/backend/tests/fixtures/fake_nmcli.py` (shared with Task 5)
- Test: `tm-control/backend/tests/test_hotspot_setup.py`

**Interfaces:**
- Produces the command `tm-hotspot-setup --profile tm-hotspot --device wlan0 --address 10.42.0.1/24 --ssid TM-AB12 --password-file <path> --group <code group>`. It prints one JSON line and exits 0:
  `{"changed": bool, "created": bool, "adopted": "<old profile name>" | null, "ssid": str, "secured": bool, "autoconnect": bool, "active": bool}`.
  A refusal exits 1 with one sentence on stderr. The password is never printed. `NMCLI` in the environment names the `nmcli` to run and is ignored when running as root (as `CHPASSWD` is in `tm-job-system-password`).
- Produces, importable for the tests (`importlib` by path, as `test_job_system_password.py` does): `ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"`, `PRIORITY = "-100"`, `new_password() -> str` (three groups of four from `ALPHABET` joined by hyphens, each character from `secrets.choice`), `choose_adoptee(profiles: list[dict]) -> dict | None`, `main(argv: list[str]) -> int`.
- What it does, in order:
  1. Read every Wi-Fi profile (`nmcli -t -f NAME,UUID,TYPE,AUTOCONNECT,TIMESTAMP connection show`, then `802-11-wireless.mode` per Wi-Fi profile). `nmcli -t` escapes `:` and `\` in values; unescape them.
  2. The target is the profile named `--profile` if it exists. Otherwise `choose_adoptee` over the profiles in `ap` mode: those with autoconnect on, the highest timestamp first; if none has autoconnect on, the highest timestamp of all; `None` when there is none.
  3. **Create** (no target): write a new password to the file first, then `nmcli connection add` with `connection.id`, `connection.interface-name`, `connection.autoconnect yes`, `connection.autoconnect-priority -100`, `802-11-wireless.mode ap`, `.ssid`, `.band bg`, `.hidden no`, `.cloned-mac-address permanent`, `802-11-wireless-security.key-mgmt wpa-psk`, `.proto rsn`, `.pairwise ccmp`, `.group ccmp`, `.psk`, `ipv4.method shared`, `ipv4.addresses`, `ipv6.method disabled`. The PSK is an `nmcli` argument, as for anyone who uses `nmcli`: it is in that process's argv while it runs, visible only to accounts on the unit, which are the installing user (who has sudo) and the code owner (who can read the file). Nothing logs it.
  4. **Adopt** (a target under another name): when the password file doesn't exist, read the profile's PSK (`nmcli -s -g 802-11-wireless-security.psk`) and write it to the file, empty when the profile has none. Rename the profile to `--profile` and set `connection.autoconnect yes`. Set `connection.autoconnect no` on every other `ap` profile.
  5. **Ensure**, for every target: compare each of `connection.interface-name`, `connection.autoconnect-priority`, `802-11-wireless.mode`, `ipv4.method`, `ipv4.addresses`, `ipv6.method` with its wanted value and `modify` only those that differ. When the password file is non-empty and the profile's `key-mgmt` is `wpa-psk`, compare the PSK with the file and set it when it differs. Never touched after creation: the name on air, `hidden`, the band, `autoconnect` (step 4 aside), and the security of an adopted profile.
  6. Never `connection up` or `down`. `active` reports whether the target is in `nmcli -t -f NAME connection show --active`.
- The password file is written with `O_CREAT|O_EXCL|O_NOFOLLOW` to a temporary name in the same directory and renamed, mode 0640, owner root, group `--group`; an existing file is never rewritten by create or adopt.
- `fake_nmcli.py` is an executable stand-in: it keeps profiles as a JSON file named by `FAKE_NMCLI_STATE`, appends each call's argv to `FAKE_NMCLI_LOG` with the value after any `…psk` argument replaced by `***`, and answers the calls listed above plus Task 5's (`device show`, `connection up`, with per-profile results set in the state file). Keep it under 150 lines; it answers only what the two scripts call.

- [ ] **Step 1: Write the failing tests** (`test_hotspot_setup.py`; `run(tmp_path, profiles=…, password=None)` writes the state, runs the script through `fixtures/run_job.py` with a non-root euid, and returns the JSON line, the profiles after, the password file's text, and the call log)

```python
def test_a_unit_without_a_hotspot_gets_one(tmp_path):
    out, profiles, password, log = run(tmp_path, profiles=[])
    assert out == {"changed": True, "created": True, "adopted": None, "ssid": "TM-AB12",
                   "secured": True, "autoconnect": True, "active": False}
    hotspot = profiles["tm-hotspot"]
    assert hotspot["ipv4.addresses"] == "10.42.0.1/24" and hotspot["ipv4.method"] == "shared"
    assert hotspot["connection.autoconnect-priority"] == "-100" and hotspot["ipv6.method"] == "disabled"
    assert hotspot["802-11-wireless-security.key-mgmt"] == "wpa-psk"
    assert re.fullmatch(f"[{ALPHABET}]{{4}}-[{ALPHABET}]{{4}}-[{ALPHABET}]{{4}}", password)
    assert hotspot["802-11-wireless-security.psk"] == password

def test_a_second_run_changes_nothing(tmp_path): ...            # changed False; the log has no add, modify, up, or down
def test_the_password_file_is_the_source_of_truth(tmp_path): ...  # file "NEWPLACEHOLDER1", profile differs -> one modify of the psk
def test_a_hand_made_hotspot_is_adopted_with_its_name_and_password(tmp_path): ...
    # one ap profile "Hotspot", ssid "Depot", psk "placeholder-psk", autoconnect no, address unset ->
    # renamed tm-hotspot, ssid still "Depot", file == "placeholder-psk", autoconnect yes, ipv4.addresses set, adopted "Hotspot"
def test_adoption_never_overwrites_an_existing_password_file(tmp_path): ...
def test_among_several_the_one_that_starts_by_itself_is_adopted(tmp_path): ...  # the others end with autoconnect no
def test_an_open_hand_made_hotspot_is_adopted_as_it_is(tmp_path): ...  # secured False, file exists and is empty, no security modify
def test_an_active_adopted_hotspot_is_changed_but_never_reactivated(tmp_path): ...  # active True; the log has no "up"/"down"
def test_a_hotspot_turned_off_stays_off(tmp_path): ...           # tm-hotspot with autoconnect no -> still no, changed False
def test_the_password_is_in_no_output(tmp_path): ...             # not in stdout, stderr, or the fake's log
def test_names_with_colons_and_backslashes_are_read_whole(tmp_path): ...  # an ap profile named 'a:b\\c' is adopted by that name
def test_a_failing_nmcli_is_a_refusal_not_a_traceback(tmp_path): ...  # exit 1, one line on stderr
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_hotspot_setup.py -q`
Expected: FAIL (no such script)

- [ ] **Step 3: Write `fake_nmcli.py` and `tm-hotspot-setup`.** The script's docstring says what it is for and lists the six steps, as the other job scripts' docstrings do.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tm-control/backend/tests/test_hotspot_setup.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tm-control/jobs/tm-hotspot-setup tm-control/backend/tests/fixtures/fake_nmcli.py tm-control/backend/tests/test_hotspot_setup.py
git commit -m "Add the root helper that creates or adopts the hotspot profile"
```

### Task 4: The installer sets the hotspot up: firewall, DNS, profile, radio, and the old scripts removed

**Bench answers (Task 1 A, E, H, 2026-11-10):**
- The firewall unit exactly as specified below (no `DefaultDependencies=no`) is active before NetworkManager at boot (9.3 s against 10.7 s; NetworkManager waits on `network-pre.target`, which waits on the unit). The table survives `systemctl restart traffic-monitor.service` and `firewall-cmd --reload`; `systemctl reload` replaces it; loading the file twice works.
- With the table loaded and Wi-Fi as the only uplink (Ethernet unplugged), `node-red-tm` and `frigate` reach the internet. With the table, a hotspot station reaches the unit (`10.42.0.1` and its Ethernet address) and nothing else; without it, the wired gateway, the internet, and Node-RED at the pod's address.
- A profile with `autoconnect yes` and priority -100 starts by itself: about 13 s after boot with no saved network in range, about 70 s after a joined network vanishes. Keep `autoconnect yes`.
- The dnsmasq file takes effect only when the hotspot next starts, so "files before the helper" is what makes a newly created hotspot use it. No handler.

**Files:**
- Create: `script/ansible/roles/tmsetup/templates/network/tm-hotspot-firewall.nft.j2`, `tm-hotspot-firewall.service.j2`, `tm-hotspot-dns.conf.j2`
- Modify: `script/ansible/roles/tmsetup/tasks/wifi_setup.yml`, `tasks/base_setup.yml` (the two removed files), `tasks/start_services.yml`
- Delete: `utils/wlan_check.sh`, `utils/network-wlan-ap`
- Test: `script/tests/test_tmsetup_templates.py`, `script/tests/test_tmsetup_tasks.py`

**Interfaces:**
- Consumes: Task 2's variables; Task 3's command and its JSON line.
- Produces `/etc/traffic-monitor/hotspot-firewall.nft` (root, 0644), the one file a later sharing switch would replace:
  ```nft
  #!/usr/sbin/nft -f
  # Phones on the hotspot reach this device and nothing behind it. Loaded by tm-hotspot-firewall.service.
  table inet tm_hotspot
  delete table inet tm_hotspot
  table inet tm_hotspot {
      chain forward {
          type filter hook forward priority filter - 10; policy accept;
          iifname "{{ tmsetup_wifi_device }}" ip saddr {{ tmsetup_hotspot_subnet }} drop
          oifname "{{ tmsetup_wifi_device }}" ip daddr {{ tmsetup_hotspot_subnet }} drop
      }
  }
  ```
- Produces `tm-hotspot-firewall.service`: `Before=NetworkManager.service network-pre.target`, `Wants=network-pre.target`, `Type=oneshot`, `RemainAfterExit=yes`, `ExecStart=/usr/sbin/nft -f {{ tmsetup_etc_dir }}/hotspot-firewall.nft`, `ExecReload=` the same command, `ExecStop=/usr/sbin/nft delete table inet tm_hotspot`, `WantedBy=multi-user.target`. `start_services.yml` gets its own task that enables and starts it, whatever `tmsetup_restart_required` says. A change to the `.nft` file notifies a new handler, "Reload the hotspot firewall" (`state: reloaded`): the file replaces the table in one transaction, so there is no moment without the rule, which a restart would have.
- Produces `/etc/NetworkManager/dnsmasq-shared.d/tm-hotspot.conf` (root, 0644): a comment and `address=/#/{{ tmsetup_hotspot_address }}`. No handler: dnsmasq reads it when the hotspot next starts.
- Produces, in `wifi_setup.yml` after Task 2's tasks and the two `conf.d` copies (which stay), in this order: remove the cron entry (`state: absent`, same `name` and `user`); remove the sudoers entry (`community.general.sudoers`, same `name`, `state: absent`); remove `{{ tmsetup_codedir }}/utils/wlan_check.sh` and `network-wlan-ap`; create `{{ tmsetup_etc_dir }}` and `{{ tmsetup_libexec_dir }}` if absent (same owners and modes as the tm-control tasks give them); install the firewall file and unit and the DNS file; copy `tm-control/jobs/tm-hotspot-setup` to `{{ tmsetup_libexec_dir }}` (root, 0755); "TMSetup - WiFi Setup - Create or adopt the hotspot" (`/usr/bin/python3 -EP {{ tmsetup_libexec_dir }}/tm-hotspot-setup` with the six arguments, `--ssid` `TM-{{ tmsetup_raspberry_pi_serial[-4:] | upper }}`, `no_log: true`, register `tmsetup_wifi_hotspot_register`, `changed_when` from the JSON's `changed`); "TMSetup - WiFi Setup - Turn the Wi-Fi radio on" (`nmcli radio wifi on`, when the JSON's `autoconnect` is true and `nmcli radio wifi` reads `disabled`).
- The firewall file and the DNS file come before the helper, so a hotspot that NetworkManager starts the moment the profile exists already has both.

- [ ] **Step 1: Write the failing tests**

`test_tmsetup_templates.py`: `test_the_firewall_drops_only_the_hotspot_subnet` (rendered with the role's vars: exactly two rules, both `drop`, one `iifname "wlan0" ip saddr 10.42.0.0/24`, one `oifname "wlan0" ip daddr 10.42.0.0/24`; no rule without an `ip saddr`/`ip daddr` match; `policy accept`); `test_the_firewall_file_can_be_loaded_twice` (it declares the table before deleting it); `test_the_firewall_unit_loads_before_networkmanager` (`Before=` names `NetworkManager.service`; `RemainAfterExit=yes`; `ExecStart` names the rendered path); `test_every_name_on_the_hotspot_resolves_to_the_unit` (`address=/#/10.42.0.1`).

`test_tmsetup_tasks.py`: `test_the_old_wifi_check_is_removed_from_upgraded_devices` (the cron task has `state: absent` and the old name; the sudoers task `state: absent`; a file task removes both utils paths); `test_the_old_wifi_scripts_are_gone_from_the_repo` (neither file exists under `utils/`; no task or handler names `wlan_check`); `test_the_firewall_and_dns_files_come_before_the_hotspot_profile` (task order); `test_the_hotspot_task_hides_its_output_and_reports_change_from_the_helper` (`no_log` true; `changed_when` reads the JSON); `test_the_radio_is_turned_on_only_when_the_hotspot_is_wanted` (the `when` names the JSON's `autoconnect`); `test_no_wifi_task_restarts_networkmanager_except_the_two_conf_files` (only the two `conf.d` copies notify the handler); `test_the_firewall_unit_is_started_with_the_services` (`start_services.yml`, and its `state` is the plain word `started`); `test_a_changed_firewall_file_reloads_rather_than_restarts` (the handler's `state` is `reloaded`, and the unit has `ExecReload`).

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest script/tests -q -k "firewall or hotspot or wifi or resolves"`
Expected: FAIL

- [ ] **Step 3: Write the three templates and the tasks; delete the two `utils/` files** (`git rm`). `82-nm-connectivity-check.conf` and `88-z-wifi-powersave-off.conf` stay.

- [ ] **Step 4: Run the role tests, the syntax check, and the Jinja parse**

Run:
```bash
python -m pytest script/tests -q
(cd script/ansible && ansible-playbook -i localhost setup.yml --syntax-check </dev/null)
python -c 'import sys,jinja2; e=jinja2.Environment(); [e.parse(open(f).read(), filename=f) for f in sys.argv[1:]]' $(git ls-files '*.j2')
```
Expected: PASS, "playbook: setup.yml", no output.

- [ ] **Step 5: Commit**

```bash
git add -A script/ansible/roles/tmsetup utils script/tests
git commit -m "Give every unit a hotspot at install and remove the old Wi-Fi check"
```

### Task 5: `tm-network-retry`: keep the radio on a known network or on the hotspot

**Bench answers (Task 1 A, F, 2026-11-10):**
- NetworkManager stayed on the hotspot for 10+ minutes after the saved network came back in range. Moving back is this script's job, as planned.
- `iw dev wlan0 station dump` has one `Station <mac> (on wlan0)` line per phone. `iw dev wlan0 scan` works on the hotspot (exit 0, about 4 s, `SSID: ` lines), and a joined phone stays joined.
- A wrong password: `nmcli --wait 45 connection up` fails after 25.4 s with exit 4 ("Secrets were required, but not provided"), and NetworkManager brings the hotspot back by itself about 1 s later. The 15 s wait in step 9 normally ends at once; the explicit `connection up tm-hotspot` is the fallback. `JOIN_WAIT = 45` fits.
- When a joined network vanishes, NetworkManager retries it once (two 25 s association timeouts) before the hotspot: about 70 s in all. An idle radio to the hotspot with `nmcli connection up tm-hotspot`: 1.4 s.

**Files:**
- Create: `tm-control/jobs/tm-network-retry`
- Create: `script/ansible/roles/tmsetup/templates/network/tm-network-retry.service.j2`, `tm-network-retry.timer.j2`
- Create: `tm-control/backend/tests/fixtures/fake_iw.py`
- Modify: `script/ansible/roles/tmsetup/tasks/wifi_setup.yml`, `tasks/start_services.yml` (the timer, enabled and started)
- Test: `tm-control/backend/tests/test_network_retry.py`, `script/tests/test_tmsetup_templates.py`

**Interfaces:**
- Consumes: `fake_nmcli.py` from Task 3.
- Produces the command `tm-network-retry`, configured by `TM_WIFI_DEVICE`, `TM_HOTSPOT_PROFILE`, and `TM_NETWORK_STATE` (default `/run/traffic-monitor/network-retry.json`); `NMCLI`, `IW`, and `TM_SYS_NET` (default `/sys/class/net`) are honoured only when not root. It prints one line, the outcome, and exits 0 unless the hotspot profile is missing or `nmcli` can't be run (1).
- Produces, importable: `BACKOFF = (300, 900, 3600)`, `JOIN_WAIT = 45`, `due(entry: dict | None, now: float) -> bool` (no entry, or `now - entry["last_failure"] >= BACKOFF[min(entry["failures"], 3) - 1]`), `run(now: float) -> str`.
- One run, in order; the first line that applies ends it with that outcome:
  1. `wlan0` has no `wireless` directory under `TM_SYS_NET` → `no-radio`. Its `device/subsystem` link resolves to a path ending `/usb` → `usb-radio`.
  2. `nmcli radio wifi` isn't `enabled` → `radio-off`.
  3. The device's connection (`nmcli -t -f GENERAL.STATE,GENERAL.CONNECTION device show wlan0`) is a profile other than the hotspot and its state is 100 → forget that profile's backoff entry; `on-network`. State 40 to 90 → `busy`.
  4. The hotspot profile is missing → exit 1, "no hotspot profile; run the installer".
  5. The radio isn't on the hotspot: when the hotspot's `connection.autoconnect` is `yes`, `nmcli --wait 30 connection up tm-hotspot` → `hotspot-started` (exit 1 if that fails); when `no` → `hotspot-off`.
  6. On the hotspot with a station joined (`iw dev wlan0 station dump` has a line starting `Station `) → `phone-joined`. Nothing else is run.
  7. The saved networks are the Wi-Fi profiles in `infrastructure` mode with autoconnect on, ordered by `connection.autoconnect-priority` (higher first), then `connection.timestamp` (newer first). Keep those that are `due`. When the list is empty → `nothing-to-try`, with no scan.
  8. One scan (`iw dev wlan0 scan`, the `SSID: ` lines). The candidate is the first saved network whose name is in the scan or whose profile has `802-11-wireless.hidden yes`. None → `nothing-in-range`.
  9. `nmcli --wait 45 connection up uuid <uuid>`. Success → forget its entry; `joined`. Failure → its entry becomes `{"name", "failures": n + 1, "last_failure": now}`; wait up to 15 s for the hotspot to be the device's connection again, and if it isn't, `nmcli --wait 30 connection up tm-hotspot`; `join-failed`.
- The state file: `{"networks": {"<uuid>": {"name": str, "failures": int, "last_failure": float}}, "last_run": {"at": "<ISO 8601>", "outcome": str}}`, written to a temporary name and renamed, mode 0644. Unreadable or malformed state is treated as empty. No password is read anywhere in this script (no `nmcli -s`).
- Produces `tm-network-retry.service` (`Type=oneshot`, `After=NetworkManager.service`, `StartLimitIntervalSec=0`, `Environment=TM_WIFI_DEVICE={{ tmsetup_wifi_device }} TM_HOTSPOT_PROFILE={{ tmsetup_hotspot_profile }}`, `RuntimeDirectory=traffic-monitor`, `RuntimeDirectoryPreserve=yes`, `ExecStart=/usr/bin/python3 -EP {{ tmsetup_libexec_dir }}/tm-network-retry`) and `tm-network-retry.timer` (`OnBootSec=90s`, `OnUnitActiveSec=5min`, `AccuracySec=10s`, `WantedBy=timers.target`). `wifi_setup.yml` copies the script and both units; `start_services.yml` enables and starts the timer in the same task as the firewall unit.

- [ ] **Step 1: Write the failing tests** (`test_network_retry.py`; a `world(tmp_path, …)` helper builds a fake `/sys/class/net`, the fake `nmcli` state, and the fake `iw`'s stations and scan, runs the script through `run_job.py`, and returns the outcome, the call log, and the state file)

```python
def test_an_idle_radio_gets_the_hotspot(tmp_path): ...            # "hotspot-started"; the log has `connection up tm-hotspot`
def test_a_hotspot_turned_off_is_left_off(tmp_path): ...          # "hotspot-off"; no `up`
def test_a_radio_on_a_saved_network_is_left_alone(tmp_path): ...  # "on-network"; no scan, no `up`
def test_nothing_is_scanned_or_switched_while_a_phone_is_joined(tmp_path): ...  # "phone-joined"; the iw log has no scan
def test_a_saved_network_in_range_is_joined_when_nobody_is_on_the_hotspot(tmp_path): ...  # "joined"
def test_the_saved_order_decides_between_two_in_range(tmp_path): ...  # priority first, then the newer timestamp
def test_a_saved_hidden_network_is_tried_blind(tmp_path): ...
def test_a_saved_network_out_of_range_is_not_tried(tmp_path): ...  # "nothing-in-range"
def test_a_failed_join_backs_off_and_the_hotspot_returns(tmp_path):
    # the fake fails the join and leaves the radio idle
    first = world(tmp_path, now=1000, join="fail")
    assert first.outcome == "join-failed" and first.state["networks"][UUID]["failures"] == 1
    assert first.log[-1][-3:] == ["connection", "up", "tm-hotspot"]
    assert world(tmp_path, now=1000 + 299).outcome == "nothing-to-try"     # no scan either
    assert world(tmp_path, now=1000 + 300, join="fail").state["networks"][UUID]["failures"] == 2
    assert world(tmp_path, now=1300 + 899).outcome == "nothing-to-try"
    # the third wait is 3600 s, and so is every later one
def test_a_join_that_works_clears_the_backoff(tmp_path): ...
def test_a_usb_adapter_named_wlan0_never_gets_the_hotspot(tmp_path): ...  # "usb-radio"; nmcli is not called
def test_a_unit_without_a_radio_does_nothing(tmp_path): ...       # "no-radio"
def test_a_garbled_state_file_is_started_over(tmp_path): ...
def test_a_missing_hotspot_profile_is_an_error(tmp_path): ...     # exit 1
def test_no_call_asks_networkmanager_for_secrets(tmp_path): ...   # no `-s` in any logged argv
```
`test_tmsetup_templates.py`: `test_the_retry_runs_after_boot_and_every_five_minutes` (`OnBootSec=90s`, `OnUnitActiveSec=5min`); `test_the_retry_keeps_its_state_between_runs` (`RuntimeDirectoryPreserve=yes`); `test_the_retry_runs_the_root_owned_copy_with_the_system_python` (`ExecStart`).

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_network_retry.py script/tests/test_tmsetup_templates.py -q -k "retry or radio or hotspot or join or saved or phone or state or usb"`
Expected: FAIL

- [ ] **Step 3: Write `fake_iw.py`, the script, the two units, and the tasks.**

- [ ] **Step 4: Run both suites**

Run: `python -m pytest script/tests tm-control/backend/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tm-control/jobs/tm-network-retry tm-control/backend/tests script/ansible/roles/tmsetup script/tests
git commit -m "Return to a saved Wi-Fi network from the hotspot, and start the hotspot when the radio is idle"
```

### Task 6: nginx: the sign-in redirect and the hotspot header

**Bench answers (Task 1 D, 2026-11-10):** the map and the `if` below, pasted by hand with the bench hostname, pass `nginx -t` (the lookahead is fine in the image's PCRE). On `10.42.0.1` a foreign `Host` gets `302 http://10.42.0.1/`, `/api/` paths too; the unit's own names get 200, also in upper case and with `:80` (`$host` is lower-cased and has no port); the same foreign `Host` on the Ethernet address or `127.0.0.1` gets 200. Both phones' sign-in windows opened through it (`/generate_204` and `/hotspot-detect.html` answered 302).

**Files:**
- Modify: `container/revproxy/nginx.conf.j2`, `container/revproxy/tm/locations/tm-control-api.conf.j2`
- Test: `script/tests/test_tmsetup_templates.py`, `script/tests/test_nginx_config_parses.py`

**Interfaces:**
- Produces, in the `http` block of `nginx.conf.j2`, before `server`:
  ```nginx
  # The sign-in window. On its hotspot the unit answers every name (dnsmasq), so a phone's connection test arrives
  # here with a foreign Host; the redirect is what makes the phone open its sign-in window on the control app.
  # Only for requests that arrived on the hotspot address. Never answer such a test with success: an Android 17
  # phone has no other way in.
  map "$server_addr $host" $tm_sign_in {
      default 0;
      "~^{{ tmsetup_hotspot_address | regex_escape }} (?!({{ tmsetup_hotspot_address | regex_escape }}|{{ ansible_facts['hostname'] | lower | regex_escape }}(\.local)?)$)" 1;
  }
  map $server_addr $tm_on_hotspot {
      default "";
      {{ tmsetup_hotspot_address }} 1;
  }
  ```
  and, first in the `server` block: `if ($tm_sign_in) { return 302 http://{{ tmsetup_hotspot_address }}/; }`.
- Produces, in `location /api/` only: `proxy_set_header X-TM-Hotspot $tm_on_hotspot;` (nginx sends no header for an empty value, and a client's own `X-TM-Hotspot` is replaced either way).
- `nginx.conf.j2` now needs `tmsetup_hotspot_address` and `ansible_facts['hostname']`; the three places that render it in the tests pass `ansible_facts={"hostname": "tm-ab12"}`.

- [ ] **Step 1: Write the failing tests**

`test_tmsetup_templates.py`, with a helper `sign_in(server_addr, host)` that takes the first map's pattern from the rendered file and applies it with Python's `re` to `f"{server_addr} {host}"`:
```python
@pytest.mark.parametrize("host", ["connectivitycheck.gstatic.com", "captive.apple.com", "example.com", "_",
                                  "10.42.0.10", "tm-ab12.local.example.com", "xtm-ab12", "10.42.0.1.example.com"])
def test_a_foreign_host_is_redirected_only_on_the_hotspot_address(host):
    assert sign_in("10.42.0.1", host)
    assert not sign_in("192.168.1.57", host)
    assert not sign_in("127.0.0.1", host)

@pytest.mark.parametrize("host", ["10.42.0.1", "tm-ab12", "tm-ab12.local"])
def test_the_units_own_names_are_served_on_the_hotspot(host):
    assert not sign_in("10.42.0.1", host)

def test_the_redirect_goes_to_the_hotspot_address_before_any_location(): ...  # the `if` precedes the locations include; 302; absolute URL
def test_a_hostname_with_regex_characters_is_escaped(): ...   # hostname "tm.ab12": "tmxab12" is foreign
def test_the_api_learns_from_nginx_whether_the_request_came_over_the_hotspot(): ...
    # location /api/ sets X-TM-Hotspot from $tm_on_hotspot; no other location sets it
```
`test_nginx_config_parses.py::render_config` passes the hostname fact, so `nginx -t` checks the maps and the `if`.

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest script/tests/test_tmsetup_templates.py script/tests/test_nginx_config_parses.py -q`
Expected: FAIL

- [ ] **Step 3: Add the two maps, the `if`, and the header.**

- [ ] **Step 4: Run the role tests** (with Podman available, so the `nginx -t` test runs rather than skips; say so in the PR if it was skipped)

Run: `python -m pytest script/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add container/revproxy script/tests
git commit -m "Open the phone's sign-in window on the control app"
```

### Task 7: tm-control: the Network checks

**Bench answers (Task 1 B, C, G, 2026-11-10):**
- In tm-control's sandbox, `iw reg get` fails without `AF_NETLINK` ("Failed to connect to generic netlink.") and prints the country with it. `nmcli` reads the device and the profile without it, and `nmcli -s` gives the code owner an empty PSK. Decision 7 stands.
- `wifi_country()` reads the `global` block's line, the first `country` line: the `phy#0` block that follows always says `country 99`.
- `nmcli -g` escapes `:` as `\:` too (seen in `GENERAL.HWADDR`), so `unescape` applies to `-g` output as well as `-t`.
- **Changed (maintainer, 2026-11-10):** with no country the radio is not blocked and the hotspot starts (Task 1 B), so the `network.wifi_country` row for `""` is `warn`, "Not set. The radio uses limited worldwide settings until the country is set.", with the same hint. The table below already says so, and the design's section 1 was corrected to match.

**Files:**
- Create: `tm-control/backend/tm_control/adapters/network.py`
- Create: `tm-control/backend/tm_control/modules/network/__init__.py`, `checks.py`
- Modify: `tm-control/backend/tm_control/modules/__init__.py` (`network.module` after `hardware.module`)
- Modify: `tm-control/backend/tm_control/core/manifest.py`, `tm-control/backend/tests/fixtures/manifest.json`, `tests/fixtures/status_fake.json`
- Modify: `tm-control/backend/tm_control/modules/services/units.py`, `services/router.py`
- Modify: `script/ansible/roles/tmsetup/tasks/tm-control_service.yml` (the manifest fact), `vars/main.yml` (the polkit unit list), `templates/tm-control/tm-control.service.j2`
- Modify: `tm-control/ui/src/modules/status/restarts.ts`
- Test: `tm-control/backend/tests/test_network_checks.py`, `test_api_services.py`, `test_settings_and_manifest.py`, `script/tests/test_tmsetup_templates.py`, `script/tests/test_tm_control_install.py`

**Interfaces:**
- Produces, in `manifest.py`: `@dataclass(frozen=True) class NetworkInfo: wifi_device: str = "wlan0"; hotspot_profile: str = "tm-hotspot"; hotspot_address: str = "10.42.0.1"` and `Manifest.network: NetworkInfo = NetworkInfo()` (an older manifest without the key loads with the defaults). The role's manifest fact gains `network: {wifi_device, hotspot_profile, hotspot_address}` from Task 2's variables; the fixture gains the same object.
- Produces, in `adapters/network.py` (every function returns `None` when its command is missing, times out after `TIMEOUT = 3` seconds, or exits non-zero; none raises):
  ```python
  RadioKind = Literal["builtin", "usb", "missing"]
  def radio_kind(device: str, sys_net: Path = Path("/sys/class/net")) -> RadioKind
  def radio_enabled() -> bool | None                      # nmcli radio wifi
  @dataclass(frozen=True)
  class Device: state: int; connection: str | None        # nmcli -t -f GENERAL.STATE,GENERAL.CONNECTION device show
  def device(name: str) -> Device | None
  @dataclass(frozen=True)
  class Hotspot: autoconnect: bool; ssid: str; key_mgmt: str   # key_mgmt "" when the profile has no security
  def hotspot(profile: str) -> Hotspot | None | Literal[False]  # False: NetworkManager answered and has no such profile
  def signal(name: str) -> int | None                     # the in-use row of nmcli -t -f IN-USE,SIGNAL device wifi list ifname <name> --rescan no
  def saved_networks() -> int | None                      # Wi-Fi profiles in infrastructure mode
  def connectivity() -> str | None                        # nmcli -t -f CONNECTIVITY general: full | limited | portal | none | unknown
  def wifi_country() -> str | None                        # iw reg get's first "country XX:" line; "" for 00
  def unescape(field: str) -> str                         # nmcli -t's \: and \\
  ```
- Produces, in `modules/network/checks.py`: `GROUP = CheckGroup("network", "Network", [hotspot, wifi, internet, wifi_country])`, `RETRY_UNIT = "tm-network-retry.service"`, `FIREWALL_UNIT = "tm-hotspot-firewall.service"`, `RESTART_HOTSPOT = Fix(kind="restart", text="Restart the hotspot", unit=RETRY_UNIT)`, `RUN_INSTALLER = Fix(kind="hint", text="Run the installer again (tmsetup.sh -t wifi).")`. The module is `Module("network", APIRouter(prefix="/network", tags=["network"]), check_groups=(GROUP,))`, with no routes yet.
- The checks and their exact words (`<name>` is the hotspot's name on air, `<address>` the manifest's):

  | id, title | When | Status, detail, fix |
  |---|---|---|
  | `network.hotspot`, "Hotspot" | any read is `None` | `unknown`, "The Wi-Fi state couldn't be read." |
  | | radio `missing` | `unknown`, "No built-in Wi-Fi radio was found." |
  | | radio `usb` | `error`, "A USB Wi-Fi adapter has taken the built-in radio's place, so the hotspot stays off. Unplug it and reboot." |
  | | no profile | `error`, "The hotspot isn't set up.", `RUN_INSTALLER` |
  | | autoconnect off | `ok`, "Off by choice. This unit has no wireless way in when its Wi-Fi network is missing." |
  | | radio not enabled | `error`, "The Wi-Fi radio is switched off, so the hotspot can't start.", `RUN_INSTALLER` |
  | | on the hotspot, `key_mgmt` empty | `error`, "On as <name>, with no password: anyone nearby can join it.", hint "See Wi-Fi and the hotspot in the docs to set one." |
  | | on the hotspot, `key_mgmt` not `wpa-psk` | `warn`, "On as <name>, secured with <key_mgmt> rather than WPA2." |
  | | on the hotspot, the firewall unit not `active` | `error`, "On as <name>, but its firewall isn't loaded, so phones on it may reach your other networks. Reboot the device.", `RUN_INSTALLER` |
  | | on the hotspot otherwise | `ok`, "On as <name>, at http://<address>/." |
  | | on another connection, state 100 | `ok`, "Standing by. It starts when <connection> is out of reach." |
  | | state 40 to 90 | `ok`, "The radio is joining a network." |
  | | otherwise | `error`, "The hotspot should be on and isn't.", `RESTART_HOTSPOT` |
  | `network.wifi`, "Wi-Fi network" | joined (not the hotspot), state 100 | `ok`, "<connection>, signal <n>%." (without the signal clause when it can't be read) |
  | | not joined, no saved networks | `ok`, "No saved networks." |
  | | not joined, n saved | `ok`, "None of the <n> saved networks is in reach." ("The saved network isn't in reach." for one) |
  | | unreadable | `unknown`, "The Wi-Fi state couldn't be read." |
  | `network.internet`, "Internet" | `full` | `ok`, "Reachable." |
  | | `portal` | `ok`, "This network needs a sign-in page, so the unit has no internet." |
  | | `limited`, `none` | `ok`, "Not reachable. That's normal for an offline unit." |
  | | `unknown` or unreadable | `unknown`, "Not checked yet." |
  | `network.wifi_country`, "Wi-Fi country" | a code | `ok`, "<CODE>." |
  | | `""` | `warn`, "Not set. The radio uses limited worldwide settings until the country is set.", hint "Run the installer again (tmsetup.sh -t wifi); it asks for the country." |
  | | `None` | `unknown`, "The Wi-Fi country couldn't be read." |

  Within a check, the first row that applies is the answer. The four functions share one read per report through `context.probe` (keys `network.device`, `network.hotspot`, `network.radio`). The firewall's state is `adapters.systemd.show_unit(FIREWALL_UNIT, ["ActiveState"])`.
- Produces, in `services/units.py`: `FIX_UNITS = ("tm-network-retry.service",)`, "units a check's fix may start that aren't rows in the Services list". `services/router.py::restart` accepts a unit in `FIX_UNITS` as well, audits it the same way, and answers the same 202.
- Produces: `tmsetup_tm_control_polkit.units` gains `tm-network-retry.service` (last); `tm-control.service.j2`'s `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK`, with a header-comment clause "AF_NETLINK: iw reads the Wi-Fi country for the Network checks" (dropped if Task 1 C chose the command-line fallback).
- Produces, in `restarts.ts`: `'tm-network-retry.service': { notice: 'The unit checks its Wi-Fi radio and starts the hotspot if it should be on.', result: 'Starting the hotspot. Check again in a minute.' }`.
- `status_fake.json` gains a `network` group after `hardware` with the four checks in their happy wording (the hotspot "On as TM-AB12, at http://10.42.0.1/.").

- [ ] **Step 1: Write the failing tests**

`test_network_checks.py` monkeypatches the adapter's functions (as `test_hardware_checks.py` patches `hardware`) and runs `run_group(GROUP, context)`; one test per table row, named for the row, for example:
```python
def test_the_hotspot_is_on(net):
    net.device = Device(100, "tm-hotspot"); net.hotspot = Hotspot(True, "TM-AB12", "wpa-psk"); net.firewall = "active"
    assert check(net, "network.hotspot") == ("ok", "On as TM-AB12, at http://10.42.0.1/.", None)

def test_a_hotspot_that_should_be_on_offers_a_restart(net):
    net.device = Device(30, None); net.hotspot = Hotspot(True, "TM-AB12", "wpa-psk")
    assert check(net, "network.hotspot") == ("error", "The hotspot should be on and isn't.", RESTART_HOTSPOT)

def test_internet_is_never_a_warning_or_an_error(net):
    for value in ("full", "portal", "limited", "none"):
        net.connectivity = value
        assert check(net, "network.internet")[0] == "ok"

def test_unreadable_wifi_state_is_unknown_not_an_error(net):
    net.device = None; net.hotspot = None; net.radio = None; net.connectivity = None; net.country = None
    assert {c.status for c in report(net).checks} == {"unknown"}
```
and for the adapter, against a fake `nmcli` and `iw` on `PATH`: `test_network_names_with_colons_are_read_whole` (`GENERAL.CONNECTION:Caf\:e \\ 5G` → `Caf:e \ 5G`); `test_a_missing_nmcli_reads_as_none`; `test_a_slow_nmcli_reads_as_none` (the fake sleeps past a patched `TIMEOUT`); `test_no_such_profile_is_false_not_none` (exit 10 from `connection show`); `test_country_00_is_unset`; `test_a_usb_radio_is_told_from_the_built_in_one` (a fake `/sys/class/net`).

`test_api_services.py`: `test_a_fix_unit_can_be_restarted_but_is_not_a_service_row` (`POST /services/tm-network-retry.service/restart` as admin is 202 and audited; `GET /services` doesn't list it; a viewer gets 403; `tm-hotspot-firewall.service` is 404). `test_settings_and_manifest.py`: `test_an_older_manifest_without_network_loads_the_defaults`. `script/tests`: the polkit list test gains the new last name; the sandbox test's line becomes the four families; `test_the_manifest_carries_the_hotspot_values` and the fields-in-step test.

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests script/tests -q -k "network or hotspot or fix_unit or manifest or polkit or sandbox"`
Expected: FAIL

- [ ] **Step 3: Write the adapter, the module, and the changes listed.** If the OpenAPI document changes (a new tag), regenerate it: `python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json && (cd tm-control/ui && npm run api:generate)`.

- [ ] **Step 4: Run every off-device suite**

Run: `python -m pytest script/tests tm-control/backend/tests -q && (cd tm-control/ui && npm test)`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tm-control script/ansible/roles/tmsetup script/tests
git commit -m "Show the hotspot, Wi-Fi, internet, and Wi-Fi country on the Status page"
```

### Task 8: The hotspot note on the login and setup pages

**Files:**
- Modify: `tm-control/backend/tm_control/modules/setup/router.py`
- Create: `tm-control/ui/src/components/HotspotNote.vue`
- Modify: `tm-control/ui/src/api/types.ts`, `src/modules/auth/LoginPage.vue`, `src/modules/setup/SetupPage.vue`, `tests/fake-api.ts`, `tm-control/ui/README.md` (one design note)
- Test: `tm-control/backend/tests/test_api_setup.py`, `tm-control/ui/tests/hotspot-note.spec.ts`

**Interfaces:**
- Consumes: Task 6's `X-TM-Hotspot` header; `modules/system/router.py::hostname(app_state)`.
- Produces: `GET /setup/status` gains `"hotspot": {"local_name": "<hostname>.local"}` when the request has `X-TM-Hotspot: 1`, else `"hotspot": null`. `SetupStatus` in `types.ts` gains `hotspot: { local_name: string } | null`; `fake-api.ts::status(claimed, accepted, hotspot = null)`.
- Produces `HotspotNote.vue`: no props; reads `useSession().status?.hotspot`; renders nothing when it is null, else a tonal info `v-alert` with exactly: "You're on this unit's hotspot. It has no internet. On an iPhone, open http://<local_name>/ in Safari to save downloaded files." The address is text, not a link: inside the sign-in window a link would open in the window. `LoginPage.vue` shows it above the form; `SetupPage.vue` above the stepper on every step.

- [ ] **Step 1: Write the failing tests**

Backend: `test_status_says_when_the_page_came_over_the_hotspot` (with the header: `{"local_name": "<FAKE_HOSTNAME>.local"}`; without it, and with `X-TM-Hotspot: 0` or `true`: `None`). UI: `the login page shows the hotspot note with the unit's .local name`, `the setup page shows it on every step`, `neither page shows it off the hotspot`, `the address in the note is not a link`.

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_api_setup.py -q && (cd tm-control/ui && npx vitest run tests/hotspot-note.spec.ts)`
Expected: FAIL

- [ ] **Step 3: Add the field, the component, and its two uses.** Load `frontend-design` first, and keep to conventional Vuetify per `tm-control/ui/README.md`; add one line there under Copy for the note.

- [ ] **Step 4: Run the suites and build**

Run: `python -m pytest tm-control/backend/tests -q && (cd tm-control/ui && npm test && npm run build)`
Expected: PASS, a clean build.

- [ ] **Step 5: Commit**

```bash
git add tm-control
git commit -m "Say on the login and setup pages when the phone is on the unit's hotspot"
```

### Task 9: `sudo tm-control card`, and the installer shows it

**Files:**
- Create: `tm-control/backend/tm_control/core/card.py`
- Modify: `tm-control/backend/tm_control/cli.py`
- Modify: `script/tmsetup.sh`, `script/ansible/roles/tmsetup/tasks/main.yml` (the setup-code notice's last sentence)
- Test: `tm-control/backend/tests/test_card_cli.py`, `script/tests/test_tmsetup_tasks.py`, `script/tests/test_tmsetup_script.py`

**Interfaces:**
- Consumes: Task 7's `Manifest.network` and `adapters.network.hotspot(profile)`; `core/claim_cli.py`'s `CommandError`, `open_state`, and `run`; `Settings.setup_code_file` and `Settings.secrets_dir`.
- Produces the command `tm-control card [--json] [--unclaimed-only]` (help: "print the device's card: its hotspot name and password and its setup code (run with sudo)"), run through `claim_cli.run(card.card, settings, as_json=…, unclaimed_only=…)`.
- Produces, in `core/card.py`:
  ```python
  @dataclass(frozen=True)
  class Card:
      hostname: str
      local_url: str                 # http://<hostname>.local/
      hotspot_name: str | None       # None: no hotspot profile
      hotspot_password: str | None   # None: no password file; "" : an adopted hotspot without a password
      hotspot_url: str               # http://<manifest.network.hotspot_address>/
      claimed: bool
      setup_code: str | None         # None once claimed, or when the file is missing

  def read_card(settings: Settings) -> Card
  def render(card: Card) -> str
  def card(settings: Settings, as_json: bool = False, unclaimed_only: bool = False) -> int
  ```
  `card` refuses unless root ("card must run as root: sudo tm-control card", exit 2, as `reset-admin` does). `read_card` reads the manifest, the hotspot's name, `<secrets_dir>/hotspot_password`, and the setup-code file while still root, and only then calls `open_state` for the claim state, because `open_state` drops to the state directory's owner and root never opens the database. With `unclaimed_only`, a claimed device prints nothing and exits 3, the status `set-setup-code` already uses for "claimed".
- The card's text, exactly (two spaces, the labels padded to one column):
  ```text
  Traffic Monitor tm-ab12
    Open on your network   http://tm-ab12.local/
    Hotspot name           TM-AB12
    Hotspot password       ABCD-EFGH-JKLM
    Open on the hotspot    http://10.42.0.1/ (a phone that joins opens it by itself)
    Setup code             WXYZ-2345 (works once)
  ```
  The variants: "Hotspot name           Not set up. Run tmsetup.sh -t wifi." (and no password line); "Hotspot password       None. Anyone nearby can join."; "Setup code             Already claimed."; "Setup code             Missing. Run tmsetup.sh again to get one." `--json` prints `{"hostname", "local_url", "hotspot": {"name", "password", "url"} | null, "claimed", "setup_code"}`.
- Produces, in `tmsetup.sh`: `_show_card`, called at the end of `_tmsetup_local` when the run succeeded and `/usr/local/bin/tm-control` exists. When `/dev/tty` can be written, it runs `sudo /usr/local/bin/tm-control card --unclaimed-only > /dev/tty` and, when that exits 0, prints to the log "The device's card (hotspot password and setup code) was shown on the terminal and is not in this log." Whatever the exit status, it prints "Show the card any time with: sudo tm-control card" and the install's own exit status is unchanged. The script never captures the card's text in a variable or a file.
- Produces, in `main.yml`: the setup-code notice ends with one more sentence, "For the device's hotspot name and password, run sudo tm-control card on it." No Ansible task reads the hotspot password.

- [ ] **Step 1: Write the failing tests**

`test_card_cli.py` (the command run as a subprocess with `TM_CONTROL_*` pointing into `tmp_path`, a fake `nmcli` on `PATH`, and the root check patched as `test_claim_cli.py` does for `reset-admin`):
```python
def test_an_unclaimed_unit_prints_the_whole_card(device): ...
    # the six lines above, with the fixture's hostname, "TM-AB12", the placeholder password, and the placeholder code
def test_a_claimed_unit_says_so_and_prints_no_code(device): ...     # even when the setup-code file is still there
def test_unclaimed_only_prints_nothing_for_a_claimed_unit(device): ...  # exit 3, empty stdout
def test_json_has_the_same_values(device): ...
def test_a_unit_without_a_hotspot_profile_says_how_to_get_one(device): ...
def test_an_open_hotspot_is_named_as_open(device): ...               # an empty password file
def test_card_refuses_without_root(device): ...                      # exit 2, "sudo tm-control card", nothing else printed
def test_the_database_is_never_opened_as_root(device): ...           # the files are read before open_state is called
def test_a_missing_password_file_is_not_a_traceback(device): ...
```
`test_tmsetup_tasks.py`: `test_no_installer_task_reads_the_hotspot_password` (no task in the role names `hotspot_password` except the helper's `--password-file` argument); `test_the_setup_code_notice_points_at_the_card`. `test_tmsetup_script.py`: `test_the_card_goes_to_the_terminal_not_the_log` (the script's text sends `tm-control card` to `/dev/tty` and nowhere else, and no variable is assigned from it).

- [ ] **Step 2: Run them to see them fail.** Run: `python -m pytest tm-control/backend/tests/test_card_cli.py script/tests -q -k "card or hotspot_password or notice"`. Expected: FAIL
- [ ] **Step 3: Write `card.py`, the subcommand, `_show_card`, and the notice's sentence.**
- [ ] **Step 4: Run the suites and the shell check.** Run: `python -m pytest script/tests tm-control/backend/tests -q && bash -n script/tmsetup.sh`. Expected: PASS, no output.
- [ ] **Step 5: Commit**

```bash
git add tm-control/backend script/tmsetup.sh script/ansible/roles/tmsetup/tasks/main.yml script/tests
git commit -m "Add the device card: hotspot password and setup code from one root-only command"
```

### Task 10: Docs, CLAUDE.md, and the READMEs

**Bench answers (Task 1, 2026-11-10), the times for "When the hotspot runs":** with a saved network in range, the unit joins it at boot; with none, the hotspot is up about 15 seconds after the unit starts; when its Wi-Fi network disappears, the hotspot is up about a minute later (70 s measured); a wrong saved password takes about 25 seconds to fail, and the hotspot is back about a second after. iPhone: the sign-in window opened on the login, and Firefox opened both `http://10.42.0.1/` and the `.local` name afterwards; Safari was not tested, so keep the Safari wording from the design. Task 12 re-measures these on the built code.

**Files:**
- Create: `docs/use/wifi-hotspot.md`
- Modify: `mkdocs.yml` (nav "Use the device", after `use/control-app.md`: "Wi-Fi and the hotspot")
- Modify: `docs/setup-guide.md`, `docs/software-installation.md`, `docs/reference/network.md`, `docs/reference/tmsetup.md`, `docs/use/system-admin.md`, `docs/help-and-faq/frequently-asked-questions.md`, `docs/use/home-page.md`, `docs/use/device-health.md`, `docs/development/tm-control.md`
- Modify: `CLAUDE.md`, `script/devpi/README.md`

**Interfaces:** none; prose for operators per "Writing docs". No device names. Later work is "planned" at most.

- [ ] **Step 1: Write the pages**

`wifi-hotspot.md`, "Wi-Fi and the hotspot":
- **What it is.** When the unit's Wi-Fi isn't on a network it knows, the unit runs its own hotspot, `TM-` and four characters, also when it is on Ethernet. It is how you reach a unit at the roadside.
- **Join it.** The name and password (on the unit's card; `sudo tm-control card` on the unit prints it again, with the setup code while the unit is unclaimed); the phone's sign-in window opens the control app by itself; the address `http://10.42.0.1/` and the `.local` name. The hotspot has no internet and phones on it reach only the unit.
- **Phones.** Android 17: the sign-in window is the way in, and browsers can't open the unit on its hotspot. iPhone: the sign-in window shows a downloaded file's contents rather than saving it, so open the `.local` name in Safari for downloads; an iPhone leaves a hotspot without internet about a minute after the screen locks. A "Tested with" list: Pixel 7 on Android 17, iPhone on iOS 18.7, and the date.
- **When the hotspot runs and when it doesn't.** At boot it joins a saved network in range, otherwise the hotspot starts (use Task 1 A's measured time). When the network disappears the hotspot starts; while nobody is joined the unit looks for its saved networks every 5 minutes; a network that won't join is tried less often (5, 15, then 60 minutes).
- **The password.** How it is made (on the unit, at random, different on every unit, never from the serial number), where to read it (`sudo tm-control card`, over Ethernet or SSH if you are locked out of the hotspot), how to change it today (write 8 to 63 characters to `/etc/traffic-monitor/secrets/hotspot_password`, run `tmsetup.sh -t wifi`, reboot or wait for the hotspot's next start; phones rejoin with the new one), and that a screen for this is planned. The installer shows the card on the terminal and keeps the password out of its log.
- **For sellers.** `sudo tm-control card --json` gives the same values for a label or a packing slip.
- **A hotspot you set up by hand** is kept: its name and password stay. One without a password shows as a problem on the Status page, with the `nmcli` line that sets one.
- **Who can see it.** A hotspot on a pole is visible to anyone passing, and public Wi-Fi maps record where names are seen.
- **The Wi-Fi country**, and why a hotspot needs it; `tmsetup.sh -w`.
- **Limits.** A network that itself uses `10.42.0.x`; a USB Wi-Fi adapter.

The others: `setup-guide.md` and `software-installation.md` get the new-unit path (join the hotspot, the window opens on setup) and the installer's country question; `reference/network.md` gets the hotspot's fixed address, DHCP and DNS on it, the same ports as on the LAN, "phones on the hotspot reach only the unit", and one sentence that NetworkManager asks `connectivity-check.ubuntu.com` every 5 minutes whenever the unit has a network; `reference/tmsetup.md` gets `-w`, what the `wifi` tag now does, and the card the installer shows at the end; `use/system-admin.md` gets `sudo tm-control card` beside `reset-admin`; the FAQ's Android 17 entry gets "on the unit's own hotspot, use the sign-in window", and a new entry says that a hotspot whose name is hidden (one set up by hand that way) must be added on Android with "Hidden network" ticked; `home-page.md` line 24 points at the new page; `device-health.md` gets the Network group's four checks; `tm-control.md` gets the `network` module, the two root scripts and the timer, `FIX_UNITS`, the polkit name, `AF_NETLINK`, and the manifest's `network`. `CLAUDE.md`: the `utils/` line, the `wifi` tag in the tag list's meaning, a Runtime topology bullet for the hotspot (profile, fixed address, firewall unit, retry timer, the sign-in rule in `nginx.conf.j2` and why it must never answer a connection test with success), and the role's `templates/network/`. `script/devpi/README.md`: the rows for Task 11's tests.

- [ ] **Step 2: Build the docs strictly.** Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`. Expected: no warnings, exit 0.
- [ ] **Step 3: Commit**

```bash
git add docs mkdocs.yml CLAUDE.md script/devpi/README.md
git commit -m "Document Wi-Fi and the hotspot"
```

### Task 11: Device tests

**Files:**
- Create: `script/devpi/tests/test_network.py`
- Modify: `script/devpi/tests/test_services.py`, `test_web.py`

**Interfaces:**
- Consumes: `host`, `codedir`, `codeowner`, `address`, `tm_login`, and `test_web.py`'s session helpers. A module fixture `radio(host)` returns `"hotspot"`, `"network"`, or `"idle"` from `nmcli -t -f GENERAL.CONNECTION device show wlan0`; tests that need the hotspot up skip otherwise, saying why.

- [ ] **Step 1: Write the tests**

`test_network.py`: `test_the_hotspot_profile_has_the_fixed_address_and_yields_to_saved_networks` (`sudo nmcli -g ipv4.method,ipv4.addresses,connection.autoconnect-priority,connection.interface-name,ipv6.method connection show tm-hotspot`); `test_the_hotspot_password_file_is_for_root_and_the_code_group` (`stat`: root, the code group, 640; never its contents); `test_the_hotspot_firewall_is_loaded` (`sudo nft list table inet tm_hotspot` has both `drop` rules; the unit is `active` and `enabled`); `test_every_name_resolves_to_the_unit_on_the_hotspot` (the dnsmasq file's line); `test_the_retry_timer_is_waiting` (`systemctl is-active tm-network-retry.timer`; the service's last result is `success`; the state file is valid JSON without the word `psk`); `test_the_wifi_country_is_set` (`iw reg get`); `test_the_old_wifi_check_is_gone` (no "Traffic Monitor Wifi Check" in `sudo crontab -l -u <code owner>`; no `/etc/sudoers.d/<code owner>`; neither file in `<codedir>/utils`); `test_a_foreign_host_is_redirected_only_on_the_hotspot_address` (needs the hotspot: on the Pi, `curl` with `Host: example.com` to `http://10.42.0.1/` is `302` to `http://10.42.0.1/`, to `http://127.0.0.1/` is 200, and with `Host: 10.42.0.1` is 200); `test_setup_status_names_the_hotspot_only_on_its_address` (needs the hotspot: `curl http://10.42.0.1/api/v1/setup/status` has `hotspot.local_name`; over `127.0.0.1` it is null, also when the request sends its own `X-TM-Hotspot: 1`).

`test_the_device_card_names_the_hotspot_and_never_reaches_the_log` (`sudo tm-control card --json | python3 -c` a one-liner that prints only the keys and the password's length, so no value enters the test log: the keys are the five named, the length is 14 on a unit whose password the installer made; without `sudo` the command exits 2).

`test_services.py`: the polkit test's unit list gains `tm-network-retry.service`; `test_tm_control_can_read_the_wifi_country` (the unit's `RestrictAddressFamilies` has `AF_NETLINK`). `test_web.py`: `test_the_status_report_has_the_network_checks` (the group `network` has exactly the four ids, and none is `unknown` on a healthy unit).

- [ ] **Step 2: Check them off-device.** Run: `python -m pytest script/devpi/tests --collect-only -q 2>&1 | tail -3`. Expected: collected, no errors.
- [ ] **Step 3: Commit**

```bash
git add script/devpi/tests
git commit -m "Check the hotspot, its firewall, and the sign-in redirect on a device"
```

### Task 11a: Data downloads from the phone's sign-in window

**Status:** design note written and approved by the maintainer on 2026-11-10.

**Design note**

*The finding (Task 12, Bench A item 2).* Android's sign-in window fetches a download twice. The window's own request carries the `tm_session` cookie and gets the file's headers. Android then hands the address to a download helper, which requests it again without the cookie: verify answers 401, nginx redirects, and the phone saves the login page. This is older than this branch. It matters now because an Android 17 phone has no way in on the hotspot except that window, and fetching the data at the roadside is what the hotspot is for.

*What changes the weighing.* The helper's request can only come after the first request's headers, and the download flow sends its headers with the first chunk, which is after the database copy ("a minute or two" for a large database, per the Data export page). So whatever lets the second request in has to outlive the copy: minutes, not the 60 seconds first assumed. This is read from the flow and from how a WebView hands a download off; the bench database was under 1 MB, so the gap itself was never seen. Step 11 records it.

*Two ways to let the second request in:*
- **A, a download link.** The page asks tm-control for a link just before it navigates. The link is the usual address plus a random one-time token. verify lets a request without a session through when its token is good.
- **B, a grant by address.** When verify passes a logged-in `/storefiles` request, it remembers the client's address and the address requested, and lets one cookieless repeat from that address through.

*Chosen: A.*
- B has no secret. While a grant lives, any cookieless request from the same address for the same file gets the whole database, and the database's address is the same on every unit. "The same address" is every app on the admin's phone, and everyone behind the same NAT or tunnel. With a 60-second grant that was arguable; with the ten minutes a copy needs, it isn't.
- B's draw was that it needs no page change, so it could cover Frigate's pages too. It would do that by letting any address someone just fetched be fetched once more without a login, and Frigate's downloads are footage.
- A costs more: one route, one branch in verify, one nginx line, two Dashboard templates.

*The calls inside A* (each open to change before approval):
1. **The token goes in the query, as the last parameter, named `tm_token`.** The helper replays only the address, so the token has to be in it, and nginx's access log then holds it; a path segment would be logged just the same. Accepted, because of who can read it and what it is worth: the log is the journal (root and the `systemd-journal` group, who can read the database file itself); the diagnostics download, which does leave the device, already hides the value after any key ending in `token` (the reason for the name; a test pins it); and a logged token is spent or expired within ten minutes and useless from another address. Masking it in nginx's own log is possible (a `map` over `$request` and a custom `log_format`, about 8 lines and one more thing every later log change must keep), and is not planned.
2. **Bound to the client's address.** A link works only from the address it was made for. On the hotspot that is the phone's lease; nginx listens on IPv4 only, so the address can't differ between the page and the helper. verify doesn't see the browser's address today (the `/_auth` locations send no `X-Forwarded-For`), so both gain one header line. That is this task's change to the verify contract's request side.
3. **It lives 600 seconds,** on the monotonic clock (the device's wall clock can jump). Long enough for a copy four or five times slower than the documented one; a copy that takes longer saves the login page, as today.
4. **It works once.** The first request without a session that presents the token spends it, whether or not the rest matched. The window's own request has a session and leaves it alone.
5. **Only `/storefiles`, only admins.** The token names the `files` value it was made for. verify's answer for a link carries `X-TM-User` and `X-TM-Role` and nothing else: no Frigate secret, no Node-RED token, no cookie. A link is checked like a session: the user must still exist, be an admin, and have the same session epoch, and the current license agreement must be accepted.
6. **Frigate's downloads are out of scope.** Frigate's pages make their own links, so a link from tm-control can't reach them without rewriting Frigate's pages in nginx. tm-control's own downloads (diagnostics, a model) are a third case: its pages fetch the file and save it from memory, which a sign-in window probably can't save either. Neither was tried on the bench. Step 11 records what happens for both, and the docs say what was seen.
7. **The file's name.** The bench file was saved as `…_tmdb.bin`, not `.tar.gz`. Android most likely drops an extension that doesn't match the response's type (`application/octet-stream`). Unverified. The flow will send `application/gzip`, which is what the file is; Step 11 records the saved name, and if it still ends in `.bin` the type goes back and the docs say to rename the file.
8. **Not solved here.** The sign-in window makes the unit copy the database twice (once for each request), so the wait before the download starts doubles. A plain logout doesn't cancel a link (it doesn't end a copied cookie either; "log out everywhere" and a password change end both). A download the helper retries after a dropped connection gets the login page. These go in the PR's Limits.

*If the bench disagrees:* if nginx's log shows the helper sending more than one cookieless request per download (a probe first, or a retry), stop and report. "Once" is not to be loosened without the maintainer.

**Files:**
- Modify: `tm-control/backend/tm_control/core/auth.py`, `tm_control/app.py`, `tm_control/modules/auth/router.py`
- Modify: `tm-control/ui/src/api/openapi.json` and the types generated from it
- Modify: `container/revproxy/tm/locations/tm-control-auth.conf.j2`
- Modify: `container/node-red-tm/data/flows.json`: ui-templates `26223a9168dd0050` ("Button to trigger download request") and `70073189458c7166` ("redirect to storefiles URL"), function `857384c653c6a46c` ("download chunks")
- Modify: `CLAUDE.md`, `docs/development/tm-control.md`
- Test: `tm-control/backend/tests/test_auth_core.py`, `test_api_auth.py`, `test_redact.py`; `script/tests/test_tmsetup_templates.py`, `test_node_red_flows.py`; `script/devpi/tests/test_web.py`

**Interfaces:**
- Consumes: `session_user`, `client_ip`, `require_admin` (`modules/auth/deps.py`); `Users`, `Device`, `User`, `Backoff` as the pattern for an in-memory store with a lock (`core/auth.py`); `safe_next` and `verify` (`modules/auth/router.py`); `redact` (`adapters/redact.py`). uvicorn already runs with `proxy_headers=True, forwarded_allow_ips="127.0.0.1"`, so `client_ip` is what nginx puts in `X-Forwarded-For`.
- Produces, in `core/auth.py`:
  ```python
  DOWNLOAD_PATH = "/storefiles"  # the one path a download link opens
  DOWNLOAD_TOKEN = "tm_token"    # its query parameter. The name ends in "token" so that redact() hides its value.

  class DownloadGrant(NamedTuple):
      uid: int
      epoch: int      # the user's session_epoch when the link was made
      address: str    # the browser's address when the link was made
      files: str      # the files value the link is for, decoded
      expires: float  # on time.monotonic()'s clock

  class DownloadGrants:
      TTL = 600.0  # seconds a link lives: longer than the database copy that runs before a download's first byte
      LIMIT = 32   # links kept; making one more forgets the oldest

      def issue(self, user: User, address: str, files: str, now: float) -> str: ...
      def redeem(self, token: str, address: str, files: str, now: float) -> DownloadGrant | None: ...
      def __len__(self) -> int: ...
  ```
  `issue` forgets expired grants, then the oldest beyond `LIMIT`, and returns `secrets.token_urlsafe(32)`. Grants are kept under the token's SHA-256, not the token. `redeem` removes the grant whatever it answers, and returns it only when `now < expires` and the address and files are equal. One lock around both, as in `Backoff`. `now` is always passed in.
- Produces, in `app.py`: `app.state.download_grants = DownloadGrants()`.
- Produces, in `modules/auth/router.py`:
  - `POST /api/v1/auth/download-link`, `Depends(require_admin)`, body `{"files": str}` (1 to 2048 characters), answer `{"url": "/storefiles?files=<quote(files, safe='/,')>&tm_token=<token>"}`. It calls `issue(admin, client_ip(request), body.files, time.monotonic())` and logs `download link made for <username> from <address>` at info. The route is under `/api/`, so the cross-site check already applies.
  - `without_download_token(uri: str) -> str`: the URI with every `tm_token` pair cut from its query, the rest as sent.
  - verify, where it finds no session: a request passes as the grant's user when all of these hold: `X-TM-Required-Role` is `admin`; `urlsplit(X-Original-URI).path` is exactly `/storefiles`; `parse_qsl(query, keep_blank_values=True)` holds exactly one `files` and one `tm_token` and nothing else; `redeem(token, client_ip(request), files, time.monotonic())` returns a grant; `Users.get(grant.uid)` exists, has the grant's epoch, and is an admin; the current EULA is accepted. `redeem` is called only when the checks before it passed. The answer is 200 with `X-TM-User` and `X-TM-Role` only, and one info line, `download link used by <username> from <address>`. Anything else is the 401 it gives today, with `next` built from `without_download_token(uri)`. A request with a session never reaches this.
  - No log line, error, or audit row ever holds a token.
- Produces, in `tm-control-auth.conf.j2`, in both `/_auth` and `/_auth_admin`:
  ```nginx
      # The browser's address, which a download link is checked against. $remote_addr only: nothing the client sent
      proxy_set_header X-Forwarded-For $remote_addr;
  ```
- Produces, in `flows.json`. Both templates get the same function body (the test compares them):
  ```js
      // Android's sign-in window hands a download to a helper that sends no login cookie, so ask the control app
      // for a link that works once without one. With no link (not an admin, or the control app doesn't answer),
      // the plain address still works wherever the browser downloads the file itself.
      const plain = `/storefiles?files=${files}`;
      try {
          const response = await fetch('/api/v1/auth/download-link', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ files }),
              signal: AbortSignal.timeout(5000),
          });
          return response.ok ? (await response.json()).url : plain;
      } catch (err) {
          return plain;
      }
  ```
  - `26223a9168dd0050`: the `<a :href>` goes. The template is `<v-btn class="v-btn--block" @click="download">Download Database</v-btn>`, and its script is `export default { methods: { async downloadUrl(files) { <the body> }, async download() { window.location.href = await this.downloadUrl(this.msg.payload.filename); } } }`.
  - `70073189458c7166`: keeps its plain `<script>` and its filter of empty names. It gains `async function downloadUrl(files) { <the body> }`, the socket handler becomes `async`, and its last line is `window.location.href = await downloadUrl(filenames);`.
  - `857384c653c6a46c`: `res.setHeader('Content-Type', 'application/gzip');` in place of `application/octet-stream`.
  - Edit `flows.json` with a script and write it back as CLAUDE.md says (`json.dumps(flows, indent=4, ensure_ascii=False)`, no trailing newline), so the diff is those three nodes.

- [ ] **Step 1: Write the failing tests for the grants** (`test_auth_core.py`)

```python
ADMIN_USER = User(id=1, username="admin", role="admin", session_epoch=7, created_at="2026-11-10T00:00:00+00:00")
PHONE, FILES = "10.42.0.23", "/db/tmdb.sqlite"

def test_a_download_link_works_once_from_its_address_for_its_files():
    grants = DownloadGrants()
    token = grants.issue(ADMIN_USER, PHONE, FILES, now=100.0)
    grant = grants.redeem(token, PHONE, FILES, now=699.9)
    assert (grant.uid, grant.epoch) == (1, 7)
    assert grants.redeem(token, PHONE, FILES, now=699.9) is None
    assert len(grants) == 0

@pytest.mark.parametrize("address, files, now", [
    ("10.42.0.24", FILES, 101.0),       # another address
    (PHONE, "events.json", 101.0),      # other files
    (PHONE, FILES, 700.0),              # 600 seconds on
])
def test_a_link_presented_wrongly_is_refused_and_spent(address, files, now):
    grants = DownloadGrants()
    token = grants.issue(ADMIN_USER, PHONE, FILES, now=100.0)
    assert grants.redeem(token, address, files, now) is None
    assert grants.redeem(token, PHONE, FILES, 101.0) is None

def test_an_unknown_token_is_refused():
    assert DownloadGrants().redeem("no-such-token", PHONE, FILES, now=1.0) is None

def test_links_are_bounded_and_expired_ones_are_forgotten():
    grants = DownloadGrants()
    first = grants.issue(ADMIN_USER, PHONE, FILES, now=0.0)
    for n in range(DownloadGrants.LIMIT):
        grants.issue(ADMIN_USER, PHONE, FILES, now=1.0 + n)
    assert len(grants) == DownloadGrants.LIMIT
    assert grants.redeem(first, PHONE, FILES, now=40.0) is None   # the oldest went
    grants.issue(ADMIN_USER, PHONE, FILES, now=5000.0)
    assert len(grants) == 1

def test_tokens_differ_and_are_long():
    grants = DownloadGrants()
    tokens = {grants.issue(ADMIN_USER, PHONE, FILES, now=1.0) for _ in range(8)}
    assert len(tokens) == 8 and all(len(token) == 43 for token in tokens)
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_auth_core.py -q`
Expected: FAIL (`DownloadGrants` can't be imported)

- [ ] **Step 3: Add `DownloadGrant` and `DownloadGrants` to `core/auth.py`, and the grants to `app.state`.** Run Step 2's command. Expected: PASS.

- [ ] **Step 4: Write the failing tests for the route and verify** (`test_api_auth.py`, with its `verify`, `other_client`, `login_next`, `set_cookie_headers`, `add_viewer`; `test_redact.py`)

```python
def link(client, files="/db/tmdb.sqlite"):
    return client.post("/api/v1/auth/download-link", json={"files": files}, headers=ORIGIN)

def admin_link(client, login, files="/db/tmdb.sqlite"):
    login(client, *ADMIN)
    return link(client, files).json()["url"]

def test_an_admin_gets_a_link_with_the_token_last(claimed_client, login):
    url = admin_link(claimed_client, login)
    assert url.startswith("/storefiles?files=/db/tmdb.sqlite&tm_token=")
    assert len(url.rpartition("=")[2]) == 43

def test_a_links_files_are_encoded(claimed_client, login):
    files = "a b.json,c&d=e.json"
    query = parse_qs(urlsplit(admin_link(claimed_client, login, files)).query)
    assert list(query) == ["files", "tm_token"] and query["files"] == [files]

def test_a_link_needs_an_admin_on_the_devices_own_page(claimed_client, login):
    assert link(claimed_client).status_code == 401
    login(claimed_client, *ADMIN)
    assert claimed_client.post("/api/v1/auth/download-link", json={"files": "x.json"}).status_code == 403  # no Origin
    add_viewer(claimed_client)
    viewer = other_client(claimed_client)
    login(viewer, *VIEWER)
    assert link(viewer).status_code == 403

@pytest.mark.parametrize("files", ["", "x" * 2049])
def test_a_link_needs_files(claimed_client, login, files):
    login(claimed_client, *ADMIN)
    assert link(claimed_client, files).status_code == 422

def test_a_link_passes_verify_once_without_a_cookie(claimed_client, login):
    url = admin_link(claimed_client, login)
    helper = other_client(claimed_client)
    r = verify(helper, url, role="admin")
    assert r.status_code == 200
    assert (r.headers["X-TM-User"], r.headers["X-TM-Role"]) == ("admin", "admin")
    assert "X-TM-Frigate-Secret" not in r.headers and "X-TM-NR-Token" not in r.headers
    assert set_cookie_headers(r) == []
    assert verify(helper, url, role="admin").status_code == 401

def test_a_request_with_a_session_leaves_the_link_unused(claimed_client, login):
    url = admin_link(claimed_client, login)
    r = verify(claimed_client, url, role="admin")
    assert r.status_code == 200 and "X-TM-Frigate-Secret" in r.headers
    assert verify(other_client(claimed_client), url, role="admin").status_code == 200

@pytest.mark.parametrize("change", [
    lambda url: url.replace("/storefiles?", "/storefiles/?"),
    lambda url: url.replace("/storefiles?", "/dashboard/?"),
    lambda url: url.replace("/storefiles?", "/frigate/../storefiles?"),
    lambda url: url + "&files=events.json",
    lambda url: url + "&other=1",
    lambda url: url + "&tm_token=" + url.rpartition("=")[2],
    lambda url: url.replace("tmdb.sqlite", "tmdb.sqlite-wal"),
])
def test_verify_refuses_a_link_that_was_changed(claimed_client, login, change):
    url = admin_link(claimed_client, login)
    assert verify(other_client(claimed_client), change(url), role="admin").status_code == 401

def test_a_link_opens_no_viewer_location(claimed_client, login):
    url = admin_link(claimed_client, login)
    assert verify(other_client(claimed_client), url, role="viewer").status_code == 401

def test_verify_refuses_a_link_from_another_address_and_spends_it(claimed_client, login):
    url = admin_link(claimed_client, login)
    elsewhere = TestClient(claimed_client.app, base_url=BASE, client=("10.42.0.24", 50000))
    assert verify(elsewhere, url, role="admin").status_code == 401
    assert verify(other_client(claimed_client), url, role="admin").status_code == 401

def test_a_link_ends_with_the_users_sessions(claimed_client, login):
    url = admin_link(claimed_client, login)
    users = Users(claimed_client.app.state.state)
    users.bump_epoch(users.by_username("admin").id)
    assert verify(other_client(claimed_client), url, role="admin").status_code == 401

def test_a_link_waits_for_the_license_agreement_like_a_session(claimed_client, login, monkeypatch): ...
    # the EULA version changed after the link was made (as test_verify_blocks_everyone_until_... does): 401

def test_the_login_redirect_leaves_the_token_out(claimed_client):
    r = verify(claimed_client, "/storefiles?files=x.json&tm_token=PLACEHOLDER", role="admin")
    assert r.status_code == 401 and login_next(r) == "/storefiles?files=x.json"

def test_no_log_line_holds_the_token(claimed_client, login, caplog):
    caplog.set_level(logging.INFO)
    url = admin_link(claimed_client, login)
    verify(other_client(claimed_client), url, role="admin")
    assert "download link made" in caplog.text and "download link used" in caplog.text
    assert url.rpartition("=")[2] not in caplog.text
```

`test_redact.py` (passes before and after; it pins why the parameter is named as it is):
```python
def test_a_download_links_token_in_nginxs_log_is_hidden():
    line = '10.42.0.23 - - [10/Nov/2026:08:11:15 +0000] "GET /storefiles?files=/db/tmdb.sqlite&tm_token=PLACEHOLDER HTTP/1.1" 200 394000'
    out = redact(line, [])
    assert "PLACEHOLDER" not in out and "files=/db/tmdb.sqlite&tm_token=" in out and ' HTTP/1.1" 200' in out
```

- [ ] **Step 5: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_api_auth.py tm-control/backend/tests/test_redact.py -q`
Expected: the new `test_api_auth.py` tests FAIL (404 for the route); the redact test passes.

- [ ] **Step 6: Add the route, `without_download_token`, and verify's branch. Regenerate the API document.** Update verify's docstring and the module's: the link answer is part of the contract.

Run: `PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json`, then `npm run api:generate` in the pinned Node image (`tm-control/ui/README.md`), then `python -m pytest tm-control/backend/tests -q`
Expected: PASS

- [ ] **Step 7: nginx: the failing test, then the line** (`test_tmsetup_templates.py`)

```python
@pytest.mark.parametrize("name", ["/_auth", "/_auth_admin"])
def test_verify_is_told_the_browsers_address_and_nothing_the_client_sent(name):
    block = location_block(location("tm-control-auth.conf"), f"location = {name} {{")
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in block
    assert "$proxy_add_x_forwarded_for" not in block and "$http_x_forwarded_for" not in block
```

Run: `python -m pytest script/tests/test_tmsetup_templates.py script/tests/test_nginx_config_parses.py -q` (with Podman, so `nginx -t` runs). Expected: FAIL, then PASS with the two lines added.

- [ ] **Step 8: The flows: failing tests, then the three nodes** (`test_node_red_flows.py`)

```python
LINK_PAGES = {"26223a9168dd0050": "async downloadUrl(files) {", "70073189458c7166": "async function downloadUrl(files) {"}

def download_url_body(node): ...   # the text between the opening line in LINK_PAGES and its closing brace

def test_both_download_pages_ask_the_control_app_for_a_link():
    bodies = {download_url_body(by_id[node]) for node in LINK_PAGES}
    assert len(bodies) == 1
    [body] = bodies
    assert "'/api/v1/auth/download-link'" in body and "JSON.stringify({ files })" in body
    for node in LINK_PAGES:
        assert ":href" not in by_id[node]["format"]
        assert "window.location.href = await" in by_id[node]["format"]

@needs_node
@pytest.mark.parametrize("answer, expected", [
    ('{"ok": true, "json": async () => ({"url": "/storefiles?files=a.json&tm_token=T"})}', "/storefiles?files=a.json&tm_token=T"),
    ('{"ok": false}', "/storefiles?files=a.json"),      # a viewer's 403
    ("null", "/storefiles?files=a.json"),               # fetch throws: the control app doesn't answer
])
def test_a_download_falls_back_to_the_plain_address(answer, expected): ...
    # run the body in node as an async function of (files, fetch) with files "a.json" and a fetch that returns
    # `answer` (or throws for null); also assert fetch was called once with method POST, a JSON content type,
    # and the body {"files":"a.json"}

def test_a_download_says_it_is_gzip():
    assert "'Content-Type', 'application/gzip'" in by_id["857384c653c6a46c"]["func"]
    assert "octet-stream" not in by_id["857384c653c6a46c"]["func"]
```

Run: `python -m pytest script/tests/test_node_red_flows.py -q` and `python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null`
Expected: FAIL, then PASS. `git diff --stat` shows `flows.json` changed in those three nodes only. Check the template syntax against the docs of the Dashboard version in `data/package.json` (methods under `export default`, `this.msg`); Step 11 is where it runs for real.

- [ ] **Step 9: The device test** (`script/devpi/tests/test_web.py`; no file is downloaded, so it runs on any host)

`test_a_download_link_works_once_without_the_cookie(address, admin_session)`: from this machine, `POST /api/v1/auth/download-link` with the admin cookie, an `Origin` of the device's own address, and `{"files": "tmdev-missing.json"}` answers 200 with a `url`. `GET` that `url` without a cookie is 404 (Node-RED's "not found", so the login check passed); the same `GET` again is a 302 to `/login`, whose `next` has no `tm_token`. A second link, fetched on the Pi itself with `curl` to the same address (so from another address), is a 302. No assertion message prints a link.

Run: `python -m pytest script/devpi/tests --collect-only -q 2>&1 | tail -3`. Expected: collected, no errors.

- [ ] **Step 10: The contract in the repo's docs, then every off-device check in Global Constraints**

`CLAUDE.md`, in the verify bullets: `POST /api/v1/auth/download-link` (admins) makes a one-time link for `/storefiles`; verify passes a request without a session whose `tm_token` is good (600 seconds, once, the same client address and `files`, admin locations only) with `X-TM-User` and `X-TM-Role` only; the `/_auth` locations send the browser's address as `X-Forwarded-For $remote_addr`; the two Dashboard templates ask for the link and fall back to the plain address; the parameter's name is what keeps it out of the diagnostics. `docs/development/tm-control.md`: the same, in its "nginx checks every app path" section, written for a contributor.

Commit, in this order:
```bash
git add tm-control container/revproxy script/tests/test_tmsetup_templates.py CLAUDE.md docs/development/tm-control.md
git commit -m "Let a download link pass the login check once without the cookie"
git add container/node-red-tm/data/flows.json script/tests/test_node_red_flows.py
git commit -m "Ask the control app for a link before a data download"
git add script/devpi/tests/test_web.py
git commit -m "Check a download link on a device"
```

- [ ] **Step 11: The bench** (the Bench A unit, through `tmdev.py check start|item|end`; the maintainer does the phone steps by hand)

1. `tmdev.py deploy <host> -- -t tm-control -t revproxy -t node-red-tm`, then `tmdev.py test <host> -- -k "download or data_export or verify or login"`, then the full non-disruptive suite.
2. Pixel 7, Android 17, in the hotspot's sign-in window, logged in as the admin: **Download Database**. A file is saved; record its name and size. The size is that of the archive, not 713 bytes. Read nginx's two log lines with the token cut out, so no link enters the record: `sudo journalctl -u revproxy.service --since -5min | grep 'GET /storefiles' | sed -E 's/tm_token=[^ ]+/tm_token=…/'`. Expected: two requests a moment apart, both 200, the second with the helper's user agent and the archive's size. Record the gap between them, and stop if there are more than two.
3. The saved file's name ends in `.tar.gz` (call 7). If it ends in `.bin`: put `application/octet-stream` back, with its test, and note it for Task 11b's docs.
4. The same page's JSON export from the sign-in window saves too (the other template).
5. Press **Download Database** again: it saves again (a new link each time).
6. A computer's browser on the wired network: both downloads work as before, with one request each in the log.
7. A viewer on the Data export page: **Download Database** shows the same refusal as before the change.
8. Recorded only, no fix here: in the Pixel's sign-in window, **Download diagnostics** on the Device page and one export from Frigate. For each, whether a file was saved and its size. Nobody opens the Frigate file.
9. iPhone, after **Use Without Internet**, in Safari: **Download Database** saves, and the file's name is unchanged by step 3's type.

Not benched: a database large enough that its copy takes minutes. The 600 seconds are sized for it from the Data export page's figures; say so in the PR.

- [ ] **Step 12: For the PR (Task 13).** Release note: "A database or JSON download now saves from an Android phone's sign-in window." Decisions to look at: this task's calls 1, 2, 3, and 6. Limits: call 8's three, call 6's two (as seen in Step 11), and "not benched" above.

### Task 11b: The bench's docs items, and one more scan

**Is a second scan worth it?** Yes, if a short wait is enough, which Step 1 measures first. On the bench, `iw dev wlan0 scan` failed with "Invalid exchange (-52)" in 3 of about 12 scanning runs, each soon after the hotspot had started. A failed scan harms nothing (`scan-failed`, the hotspot stays, the next run scans), but it costs a unit that could be back on its saved network five more minutes on the hotspot. A second try is about ten lines. It is on any failed scan, never on the error's text.

**Files:**
- Modify: `tm-control/jobs/tm-network-retry`, `tm-control/backend/tests/test_network_retry.py`, `tm-control/backend/tests/fixtures/fake_iw.py`
- Modify: `docs/use/wifi-hotspot.md`, `docs/ui/database.md`, `tm-control/ui/src/components/HotspotNote.vue`, `tm-control/ui/tests/hotspot-note.spec.ts`

**Interfaces:**
- `tm-network-retry`: `SCAN_RETRY_WAIT = 5` (seconds; tests set `TM_SCAN_RETRY_WAIT`, read through `trusted()` like the others). In step 8, a scan that exits non-zero is run once more after the wait, and the second scan's answer is the run's. When the second one worked, the run's line gains the reason the first failed, as `nothing-in-range (scan retried: iw exit 204: …)`; the state file still keeps the outcome alone. The docstring's step 8 says so.
- `fake_iw.py`: a state key `"fail_once": ["scan"]` fails that verb once and removes it from the state file. `world()` in `test_network_retry.py` gains `iw_fail_once=()` for it.

- [ ] **Step 1: Measure on the bench unit** (no phone joined, at least one saved network): five times, `sudo nmcli connection up tm-hotspot`, then `sudo iw dev wlan0 scan >/dev/null; echo $?` every 2 seconds for 30 seconds, recording each exit status with its offset. If a scan succeeds within 10 seconds of the first failure in at least 4 of the 5 starts that showed a failure, set `SCAN_RETRY_WAIT` to the smallest of 3, 5, and 10 that covers them and go on. If no start shows a failure, or the failures last longer, skip Steps 2 to 4, change no code, and put the measurement in the ledger for the final review.

- [ ] **Step 2: The failing tests** (`test_network_retry.py`, with `TM_SCAN_RETRY_WAIT=0`)

```python
def test_a_scan_that_fails_once_is_tried_again(tmp_path):
    result = world(tmp_path, iw_fail_once=("scan",))      # a saved network "Home" is heard on the second scan
    assert result.iw == [["dev", "wlan0", "station", "dump"], ["dev", "wlan0", "scan"], ["dev", "wlan0", "scan"]]
    assert result.outcome.startswith("joined (scan retried: iw exit 240")

def test_a_scan_that_fails_twice_leaves_the_hotspot_alone(tmp_path): ...
    # the existing test_a_scan_that_fails_leaves_the_hotspot_alone, with two scans in result.iw and no third
```

- [ ] **Step 3: Run to fail, implement, run to pass.** Run: `python -m pytest tm-control/backend/tests/test_network_retry.py -q`

- [ ] **Step 4: On the bench:** `tmdev.py deploy <host> -- -t tm-control -t wifi`, repeat Step 1's five starts with `sudo systemctl start tm-network-retry.service` in place of the scans, and record each run's line from the journal. Commit: `git commit -m "Scan once more when the first scan after a hotspot start fails"`.

- [ ] **Step 5: The docs**

`docs/use/wifi-hotspot.md`:
- **Phones, Android 17:** downloads on the Data export page save from the sign-in window; the unit prepares the database twice there, so the wait before the download starts is about double. One sentence each for the control app's own downloads and Frigate's, saying what Task 11a's Step 11 item 8 saw. If the file's name ended in `.bin` there: rename it to end in `.tar.gz`.
- **Phones, iPhone:** to stay on the hotspot and save downloads, tap **Cancel** on the sign-in sheet and choose **Use Without Internet**, then open `http://10.42.0.1/` or the `.local` name in Safari. Without that choice the iPhone goes back to another network it knows, and a download in progress is cut off. Keep the sentence about the locked screen only if the bench record still supports it.
- **"When the hotspot runs", from the built code's bench:** with a saved network in range the unit is on it within a minute of starting (5 of 5 starts); the network disappears: the hotspot is up about 75 seconds later (73 measured); a saved network with the wrong password: the hotspot is away for about a minute while the unit tries (63 measured), then comes back. "About 15 seconds" for a start with no saved network stays; it was measured before the build and not again.
- **The waits after a failed join:** a wait now counts from when the try ended, and the unit looks every 5 minutes, so the next tries come about 10 minutes, then about 20, then about 65 minutes after a failure, not 5, 15, and 60. Check the bench record's times for the first of these before writing it.

`docs/ui/database.md`, "Download the database": one sentence pointing at the hotspot page's Phones section for downloads on a phone.

`HotspotNote.vue` and its test: "You're on this unit's hotspot. It has no internet. On an iPhone, tap Cancel, choose Use Without Internet, then open http://{name}/ in Safari to save downloaded files."

- [ ] **Step 6:** `~/.venvs/tm-docs/bin/mkdocs build --strict` and the UI's `npm test && npm run build`. Expected: no warnings; PASS. Commit: `git commit -m "Say how downloads work on each phone, with the bench's times"`.

### Task 12: The Pi plan

Through `tmdev.py check start|item|status|end`, one host at a time, from the worktree. A full `tmdev.py deploy <host>` first (a new version needs the whole installer), then single-tag runs where an item says so. Throwaway names and passwords; nothing printed that is a password; no real network's name in the record.

- [ ] **Bench A** (Ethernet, no hand-made hotspot, upgraded from `dev`):
  1. The deploy: the country (`-w` given once, defaulted once on a unit reset to none), the radio turned on, the hotspot up as `TM-` and the serial's last four at `10.42.0.1`, the firewall unit active, the timer waiting, the old cron and sudoers entries and the two utils files gone, and the installer's log has no line holding the hotspot password (`grep -c` for it on the Pi, the password read into a shell variable and never echoed).
  1a. On a unit reset to unclaimed, a local install over SSH with a terminal (`tmdev.py deploy <host> --on-pi`): the card appears on the terminal at the end with the setup code, the log says it was shown, and `sudo tm-control card` prints it again. After claiming: "Already claimed.", and `--unclaimed-only` prints nothing and exits 3.
  2. Pixel 7, Android 17: join; the sign-in window opens on the login (or setup) with the note; log in; Status shows the Network group all ok; Frigate's live view; a data download saves. Close and reopen the window: still logged in.
  3. iPhone: the same; then the `.local` name in Safari and a download there; `http://10.42.0.1/` as Task 1 I left it.
  4. From a phone on the hotspot: a wired-network host and the pod's bridge address don't answer.
  5. With a phone joined: `tmdev.py deploy <host> -- -t wifi`, twice. The phone stays joined (the station's connected time in `iw dev wlan0 station dump` keeps growing) and the second run reports no change in the hotspot task.
  6. A saved network (a second Pi's hotspot or a phone hotspot, throwaway): five reboots with it in range, recording where the radio is at 60 s and at 120 s; then the network switched off: the time until the hotspot is up; switched on again with no phone joined: back on the network within one timer period; with a phone joined: stays on the hotspot.
  7. The saved network's password changed at its source: one failed join (seconds recorded), the hotspot back, the state file's `failures` 1; the next run within 5 minutes tries nothing; the one after tries again.
  8. `sudo nmcli connection down tm-hotspot` with no saved network: the Status page's Hotspot row turns red with "Restart the hotspot"; the button brings it back and the row goes green.
  9. The radio as the uplink (Ethernet unplugged, reached over the saved Wi-Fi): `sudo podman exec node-red-tm wget -q -O- http://connectivity-check.ubuntu.com` answers; the Status page's Internet row says "Reachable."
  10. A reboot: `systemctl show -p ActiveEnterTimestampMonotonic tm-hotspot-firewall.service NetworkManager.service` puts the firewall first; the table is listed.
  11. `tmdev.py test <host> -- -k "network or hotspot or polkit or status"`, then the full non-disruptive suite.
- [ ] **Bench B** (a hand-made hotspot before the upgrade: `nmcli device wifi hotspot` with a throwaway name and password, autoconnect left off):
  1. Deploy while a phone is joined to it: the phone stays joined; the profile is now `tm-hotspot` with the old name on air; the password file equals the old password (compare by `sha256sum` on the Pi, never printed); autoconnect is on.
  2. Reboot: the hotspot comes up under the old name and password at `10.42.0.1`; the sign-in window opens.
  3. Make the profile open (`nmcli connection modify tm-hotspot remove 802-11-wireless-security`) and restart it: the Status row is an error naming the missing password; set a password again as the docs say.
  4. The suite with its skips.
- [ ] Remove the throwaway profiles and networks, leave both Pis on their hotspot defaults, and say so. Record each item with `tmdev.py check item`; end with `tmdev.py check end`. Put the measured times (boot to hotspot, failed join, back to a saved network) in `wifi-hotspot.md` where it says "about".

### Task 13: Pull request

- [ ] Run every off-device check in Global Constraints once more on the final branch; `git grep` the branch for device names, addresses, and the bench's throwaway names.
- [ ] Add Task 11a's Step 12 to the PR draft below: its release-note sentence, its decisions to look at, and its limits.
- [ ] Copy this plan to `design/plans/2026-11-09-wifi-hotspot.md` and commit it ("Add the Wi-Fi hotspot plan").
- [ ] Draft the PR against `dev` with the template filled in: the release-note paragraph ("Every unit now runs its own Wi-Fi hotspot whenever its Wi-Fi isn't on a network it knows, including units on Ethernet. A phone that joins it gets the control app in its sign-in window. Phones on the hotspot reach only the unit. The installer asks for the Wi-Fi country when the device has none, `sudo tm-control card` prints a unit's hotspot password and setup code in one place, and the five-minute Wi-Fi check that restarted NetworkManager is removed."), "Closes #<n>", the decisions to look at (4, 5, 7, 9, 13, 15), a "Limits" list (no settings screen yet; a network using `10.42.0.x`; a USB adapter named `wlan0` turns the hotspot off; the firewall rule is a table of its own until the device gets a managed firewall, which is planned; the boot result from Task 1 A), the upgrade notes (the radio is switched on; a hand-made hotspot is adopted; `wlan_check.sh` and its cron and sudoers entries are removed), the Pi plan's results with the measured times, the Docs list from Task 10, and the "AI assistance" section. Say `PUBLIC push →` before pushing, and show the maintainer the commit messages and the PR text first.
