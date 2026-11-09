# tm-control M2 spikes

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
