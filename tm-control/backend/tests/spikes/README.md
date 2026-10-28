# tm-control spikes

Before M2 depended on them, two behaviors were checked in throwaway local Podman containers on a dev machine, not on a Pi:

1. Node-RED accepts a custom admin token header, both on the admin API and on the `/comms` WebSocket upgrade.
2. Frigate, with its own login turned off, trusts the proxy's user and role headers only when the proxy secret is present.

Date: 2026-10-27. Podman 5.7.0 (rootless), x86-64.

This directory holds only this record. The spikes left no code behind.

## Node-RED token header

Image: `docker.io/nodered/node-red:5.0.8`
(`sha256:148cf534d628591aa605f808971153d7de03b5ea5ca84b569daeadd97dc52769`).
The container logged `Node-RED version: v5.0.8` and `Node.js version: v24.21.0`.

The container's `settings.js` set `adminAuth` with no users, `tokenHeader: "x-tm-nr-token"`, and a `tokens` function that accepts only the value `spike-ok`. The container published port 1880 as 127.0.0.1:1881 and ran with `--userns=keep-id`, so the rootless container could write to the bind-mounted `/data` directory.

| Probe | Expected | Observed |
| --- | --- | --- |
| `GET /settings` with no header | 401 | `401` |
| `GET /settings` with `x-tm-nr-token: spike-ok` | 200 | `200` |
| `GET /settings` with `x-tm-nr-token: nope` | 401 | `401` |
| `/comms` upgrade with `x-tm-nr-token: spike-ok` | 101, then a topic frame or no frame (no auth failure) | `HTTP/1.1 101 Switching Protocols`, then `[{"topic":"notification/runtime-state","data":{"state":"start"}},...` |
| Control: `/comms` upgrade with no header | not in the brief | `HTTP/1.1 101 Switching Protocols`, then `{"auth":"fail"}` |
| Control: `/comms` upgrade with `x-tm-nr-token: nope` | not in the brief | Socket closed with no HTTP response (empty read) |

**Result: pass.** The admin API and the `/comms` WebSocket both honor the token header. With a valid token, the editor's WebSocket is authenticated at the upgrade and doesn't need a separate `{"auth": ...}` message. The `?access_token=` fallback isn't needed.

## Frigate proxy auth

Image: `ghcr.io/blakeblackshear/frigate:0.18.1`
(`sha256:0171060cb020ba25e6e94746004842b04783c7482b76406d6a707a275bb187f4`).
The container logged `Starting Frigate (0.18.1-cf67f08)`.

The container's `config.yml` had these settings:

- `auth.enabled: false` and `tls.enabled: false`
- `proxy.header_map` mapping `user` to `x-forwarded-user` and `role` to `x-forwarded-groups`
- `proxy.auth_secret: spike-secret`, `proxy.default_role: viewer`, and `proxy.logout_url: /logout`
- MQTT disabled and an empty `cameras: {}` map

Frigate accepted the empty camera map, so the brief's fallback camera wasn't needed. On startup, Frigate migrated the config and appended `version: 0.18-0` to it. The container published its authenticated port 8971 as 127.0.0.1:8972.

In the table, "secret" means the request sent `x-proxy-secret: spike-secret`.

| Probe | Expected | Observed |
| --- | --- | --- |
| `GET /api/version` with no secret | 401 | `401` |
| `GET /api/config/raw` with the secret, user `v`, groups `viewer` | 403 | `403` |
| `GET /api/config/raw` with the secret, user `a`, groups `admin` | 200 | `200` |
| `GET /api/config/raw` with the secret, user `v`, groups `viewer`, plus `remote-role: admin` | 403 | `403` |
| `GET /api/profile` with the secret, user `a`, groups `admin` | username `a`, role `admin` | `{"username":"a","role":"admin","allowed_cameras":[]}` |
| Control: `GET /api/config/raw` with `x-proxy-secret: wrong`, groups `admin` | not in the brief | `401` |
| Control: `GET /api/profile` with only the secret, no user or groups headers | not in the brief | `{"username":"viewer","role":"viewer","allowed_cameras":[]}` (200) |

**Result: pass.** With `auth.enabled: false`, Frigate rejects any request that lacks the correct secret, including one with no secret header at all. It takes the role from `x-forwarded-groups`. It ignores a stray `remote-role` header when the mapped header names a role. If the secret is present but the user and role headers aren't, the request is served as `default_role` (viewer).

Two points carry into M2. nginx must always send the secret, and it should still clear `remote-role`. The `remote-role` probe only shows that the mapped header wins when both headers are present, not what Frigate does when only `remote-role` is sent.

## M3: time and power through polkit, on a bench Pi

Before M3's date and time, reboot, and shut-down actions depended on them, these were checked on a bench Pi from the dev-Pi inventory, running M2, with `script/devpi/tmdev.py run`. Nothing was rebooted and the clock wasn't changed: `set-ntp` was given its current value.

Date: 2026-10-28. Raspberry Pi 5, Debian GNU/Linux 13 (trixie), systemd 257 (257.13-1~deb13u1).

A temporary rule, `/etc/polkit-1/rules.d/49-tm-m3-spike.rules`, allowed the code owner (`tmadmin`) these seven action ids and nothing else. It was removed after the probes.

- `org.freedesktop.timedate1.set-time`, `set-timezone`, and `set-ntp`
- `org.freedesktop.login1.reboot`, `reboot-multiple-sessions`, `power-off`, and `power-off-multiple-sessions`

The probes ran as the code owner (`runuser -u tmadmin`), and again under the service's sandbox: `systemd-run --uid=tmadmin -p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes -p "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" --wait --pipe`.

| Probe | Without the rule | With the rule |
| --- | --- | --- |
| `timedatectl set-ntp <current value>` | `Failed to set ntp: Interactive authentication required.`, exit 1 | exit 0 |
| The same under the sandbox | not run | exit 0 |
| `busctl call org.freedesktop.login1 … CanReboot` | `s "challenge"` | `s "yes"`, also under the sandbox |
| `busctl call org.freedesktop.login1 … CanPowerOff` | `s "challenge"` | `s "yes"` |

Two login sessions were open, so logind evaluated the `-multiple-sessions` ids, and `yes` covers both. After the rule was removed, `CanReboot` answered `challenge` again.

| Probe | Observed |
| --- | --- |
| `vcgencmd get_throttled` as the code owner | `Can't open device file: /dev/vcio_gencmd`, exit 255 |
| The same under the sandbox with `SupplementaryGroups=video` | `throttled=0x0`, exit 0 (`/dev/vcio_gencmd` is `root:video`, mode 0660) |

**Result: pass.** The seven action ids are the complete list for the time, reboot, and power-off actions, and the `video` group is enough for `vcgencmd`.

Other observations that M3's tasks rely on:

- `ss -ltnH` under `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6` prints `Cannot open netlink socket: Address family not supported by protocol` on stderr, then falls back to `/proc/net/tcp` and lists the listening sockets, exit 0. The pod's published ports show as listening sockets (`127.0.0.1:1883` on this unit, whose broker had no login).
- `timedatectl show` prints `TimeUSec` and `RTCTimeUSec` as local time strings, such as `Wed 2026-10-28 14:41:35 PDT`, and systemd 257's `timedatectl` has no `--timestamp=` option.
- `/sys/class/media/` doesn't exist. Each media device's model name is in `/sys/bus/media/devices/mediaN/model` (one read `rpi-hevc-dec`), which the code owner can read, and `readlink -f /dev/rpi-hevc-dec` named the same `/dev/media0`.
- `/proc/modules` lists `apex` on this unit, which has a Coral PCIe.
