# Location privacy: deployments, sharing, and the public map

- **Status:** decisions made 2026-10-26. This is the privacy design that tm-control's location/survey_id feature builds on. Nothing is built yet; the device change ships with that feature.
- **Tracking:** no issue yet. Related:
  - #250 and #254, which the deployment rewrite fixes.
  - #173, backup and restore.
  - #224, tm-control M1. Its platform spec lists "location/survey_id" among the features that get their own spec.
- **Scope:**
  - Where a unit's location is stored.
  - What leaves the device at each consent level.
  - What the public map shows.
  - Practices for the maintainer's server.

  The location feature's own spec covers screens, API endpoints, and flow details.
- **Decided by:** the maintainer decided the items marked **(maintainer)**. Items marked **(design call)** were chosen while writing this and are open to change.

## Why

A Traffic Monitor is usually mounted at the operator's home, so its location is the operator's home address. Today that location is handled like any other setting:

- The operator types `lat`/`lon`/`bearing` into Node-RED's `config.yml`.
- Node-RED copies them at full precision into the `deployment` table of `tmdb.sqlite`.
- The Data export page downloads that database whole. The docs call it "designed to be shareable" and "de-identified" with the default settings.
- With ThingsBoard on, the exact location also goes to the server as telemetry and attributes.

The project wants operators to be able to share data, with the maintainer, with researchers, and on a public map, without giving away where they live.

## Goals

1. `tmdb.sqlite` never holds an exact location, on any device, at any setting. **(maintainer)**
2. **Maximum privacy:** the operator can keep the location out of the database entirely and share nothing, and deployments are still tracked. **(maintainer)**
3. Sharing with the maintainer's server is opt-in. Sending the exact location there, for internal operations, is a second, separate opt-in. **(maintainer)**
4. Showing the unit on a public map is its own opt-in, and the map shows a block, not a house. **(maintainer)**
5. Every consent is recorded with the notice version and can be withdrawn where it was given.

## Non-goals

- Building the public map, or the server's handling of consent. That's the maintainer's server work, outside this repo; its practices are listed below.
- Hiding that a unit exists. It's visible from the street.
- Images and plate reads. Data and privacy in the docs already covers them, and the public map never shows images.

## Anti-goals (failures even if everything else works)

- An exact location in `tmdb.sqlite`, in a whole-database download, or in "Copy diagnostics".
- A consent box that's pre-checked, bundled with another, or can't be undone on the page where it was given.
- A public map that points at a house, or that shows when the operator is home. A unit at a house counts the operator's own car leaving and arriving.
- Random jitter instead of rounding. Averaging repeated jittered points recovers the true location.
- Anything here becoming a requirement for offline use. Map tiles and the server are optional extras.

## Constraints

- **tm-control platform:**
  - Works offline over plain HTTP. Operators never use SSH.
  - One login, at the reverse proxy.
  - tm-control is the only writer of `/var/lib/tm-control/state.sqlite`.
  - Node-RED is the only writer of `tmdb.sqlite`. tm-control shouldn't hold a connection to it either: `node-red-node-sqlite` sets no busy timeout, so a second reader's lock can make Node-RED's writes fail.
- Schema changes go through numbered migrations (`container/node-red-tm/schema/README.md`). A destructive migration needs a test and a release-notes line.
- `config.yml` is written only on first install or with `-f`. Existing devices won't have new keys, so their defaults must be the private choice.
- Browser geolocation needs HTTPS, which an offline unit on plain HTTP doesn't have. Typed coordinates and a map pin must keep working without it.

## How it works today (checked on `origin/dev`, 2026-10-26)

**Settings and consumers**
- `container/node-red-tm/config/config.yml.j2` has a top-level `deployment: {lat, lon, bearing}`. It's empty by default (`tmsetup_latitude`, `tmsetup_longitude`, and `tmsetup_bearing` in `script/ansible/roles/tmsetup/defaults/main.yml`).
- Any sensor can have its own `deployment:` block. "init config defaults" (`94136e5a6f092bb6`) copies the top-level values into each enabled sensor that lacks them.
- Node-RED watches `/config/config.yml` (watch node `5ffb7c9c38b8c5b0`) and re-reads it when it's saved.
- Only two parts of the device read lat/lon: the init-config node below and the ThingsBoard upload.

**init-config node `689b64c16a889e0a`** ("capture deployment info, send diff sql queries")
- For each enabled sensor, it compares the open `deployment` row's `lat`/`lon`/`bearing` with config.
- When they differ, it closes the old row and inserts a new one, with the id `<ms>-<hex>-d` and `deviceName` taken from `global.deviceAttributes.deviceName` (the Pi serial).
- It sets `config.sensors.<type>.<name>.deployment.id`. Every data table (`events`, `radar_*`, `airquality`) stores that id as `deployment_id`.
- Known bugs:
  - A blank `lat`/`lon` produces a broken INSERT (#250).
  - Rows written at startup hold `deviceName` = `undefined` (#254).
  - It finds the open row by `sensorName` only, although the query groups by `sensorName, deviceName`. Not filed yet.

**ThingsBoard upload** (`thingsboard` tab)
- "format deployment telemetry" (`c6ff73faf6fa9e98`) sends the full deployment rows, exact location included.
- "set deployment client side attribute payload" (`9b0f7197fe82bbfa`) sends each sensor's lat/lon, plus the top level from `global.config.deployment`.
- "format system info client-side attributes" (`e507fdc9cbf67095`) sends the hostname, the Pi serial, versions, and the time zone.
  - It still has `ssid` and `ipv4Address` slots that nothing fills.
  - Older versions sent `system_ssid` and `system_ipv4Address`; comment node `fdb3962b458f90c2` shows how to delete those attributes on a server.
- "format init-config client-side attributes" (`9941048ea93dc79c`) sends the parsed `config.yml`, as "init config defaults" leaves it, as the `config_tm` attribute. That includes the top-level and per-sensor `deployment` blocks.
- The upload also sends system metrics, radar information, and, when asked, the Frigate config backup.
- Whether it uses HTTPS depends on how its URL gets a scheme (#95).

**Data export and storage**
- The Data export page streams the whole `/db/tmdb.sqlite` (`2398aa8b9ca25816`) or a JSON export of events, radar, and air quality readings.
- Node-RED's context store is memory-only (`container/node-red-tm/data/settings.js`).

## Decisions

### 1. Where the location lives

| What | Where | Who can see it |
|---|---|---|
| Exact lat/lon, bearing, and the deployment history | `/var/lib/tm-control/state.sqlite`; the current deployment also in `config.yml` | the unit's admins; the maintainer's server only with the exact-location opt-in |
| Rounded lat/lon (none, 1, or 2 decimal places) | `tmdb.sqlite`, table `deployment` | anyone the database is shared with; the maintainer's server with data sharing |
| Road segment and side of the street | chosen when the map opt-in is turned on | the public map |

- **No separate table inside `tmdb.sqlite`.** It would go wherever the file goes, including SD-card copies and backups that an export filter never sees. **(maintainer)**
- **No second database.** tm-control's `state.sqlite` already exists and is already private to the device. **(design call)**

### 2. Precision

- **`database_precision`:** `none`, `1` (the default), or `2` decimal places. Never finer. **(maintainer)**
  - The operator's "1 significant digit" means one decimal place; read literally, it would turn 45.52 into 50.
- Round to the nearest value at that precision; don't truncate or add noise. Record the decimal places used in a new `location_precision` column, NULL when nothing is stored, so whoever reads the data knows a point is approximate. **(design call)**
- What each precision means at 45.5°N (Portland):

  | Decimal places | Area | Scale | In `tmdb.sqlite`? |
  |---|---|---|---|
  | 1 | about 11 × 8 km | a city | yes, the default |
  | 2 | about 1.1 × 0.8 km | a neighborhood | the most it allows |
  | 3 | about 110 × 80 m | a block | no |
  | 4 | about 11 × 8 m | a house | no |

- **Legal benchmark.** Several US state privacy laws treat location as "precise geolocation" when it places someone within about 1,750–1,850 ft: 1,850 ft in California, and 1,750 ft in Virginia, which also requires opt-in consent. Two decimal places sits about at that line, and one decimal place is well outside it. These laws have size thresholds that may not apply to this project, so treat them as a benchmark, not legal advice.
- **Exact locations** are stored to 5 decimal places at most, about 1 m. Phone GPS is only good to a few meters anyway. **(design call)**
- **Lowering the precision:**
  - Choosing a coarser `database_precision`, or `none`, offers to rewrite the existing rows to match. A confirmation says it can't be undone.
  - tm-control asks Node-RED to do it through an internal endpoint, because tm-control doesn't write `tmdb.sqlite`.
  - Raising the precision affects only new deployments.

  This follows from goal 2: an operator who picks maximum privacy after entering a location shouldn't keep it in the database. **(design call)**

### 3. Deployments become explicit

- tm-control's "New deployment" action creates the deployment id and records:
  - the exact location: typed, a map pin when the browser is online, or browser geolocation over HTTPS
  - the bearing for each sensor, keeping today's per-sensor overrides
  - `survey_id`
  - `database_precision`

  **(design call)**
- tm-control keeps the history in `state.sqlite` and writes the current deployment to `config.yml`: id, exact location, bearing, `survey_id`, and `database_precision`.
- Node-RED acts on a new id when the watch node sees the file change. It closes the open rows and inserts new ones with rounded or NULL lat/lon, `location_precision`, and `survey_id`.
- The lat/lon comparison in `689b64c16a889e0a` goes away, which fixes #250, #254 (read `TM_RPI_SN` from the environment instead), and the `sensorName`-only match.
- Editing lat/lon by hand in `config.yml` without a new id doesn't start a deployment. tm-control is the way to move a unit, and the docs say so. **(design call)**

### 4. tmdb migration

- Add `location_precision` (INTEGER) and `survey_id` (TEXT) to `deployment`.
- Round the existing rows' `lat`/`lon` to 1 decimal place and set `location_precision = 1`. This is destructive, so it needs a migration test with synthetic rows and a release-notes line. **(design call)**
- The runner's pre-migration backup (`db/backup/tmdb-v1-*.sqlite`) keeps the exact rows until the next migration replaces it. The release notes say so.
- tm-control doesn't import the old exact history into `state.sqlite`. The backup is there for an operator who needs it. **(design call)**

### 5. What leaves the device

All location data leaves through one gate in the upload flow. It applies to every place a location leaves: deployment telemetry, per-sensor and top-level attributes, and `config_tm`. **(design call)**

| Consent | Sent to the maintainer's server |
|---|---|
| None (the default) | Nothing |
| Share data | Everything the upload sends today, with every location field replaced by the rounded value stored in `tmdb.sqlite`. That's events, readings, system metrics and info, radar information, `config_tm`, and the Frigate config backup when asked. Plus the consent flags and the notice version. **(design call)** |
| + Exact location (separate checkbox) **(maintainer)** | The current exact location as an attribute, sent when it changes. The server's exact history starts at opt-in. Withdrawing stops it. |
| + Public map (separate checkbox) | The map consent flag, plus the segment id and side of the street if they were picked on the device |

- The map opt-in doesn't require the exact-location opt-in: the operator picks their block on a map. **(design call)**

**Upload targets (maintainer)**
- The maintainer's server is built in: its address ships with the device, so an operator just ticks "Share".
  - Units the maintainer sells come with a token installed. DIY builders request one.
  - No provisioning secret goes in the repo, because the repo is public. **(design call)**
- Operators can point the upload at their own ThingsBoard instead. There's one target at a time.
- For an operator's own server:
  - Turning the upload on counts as the share-data choice, because the operator is the recipient.
  - The maintainer's notice and the map opt-in don't apply.
  - The exact-location checkbox still does, off by default.

  **(design call)**
- Consent is recorded per target, and changing the target clears it. **(design call)**
- Choosing a target needs a screen in tm-control. So this feature includes the target part of the platform spec's later "ThingsBoard settings" feature, or ships after it. **(design call)**
- `config_tm` is sent with its location fields replaced and without secrets. **(design call)**
- The exact-location checkbox is available only when the upload uses HTTPS, so this feature fixes #95. **(design call)**
- There's one upload target at a time, as today. **(design call)**
- Remove the unused `ssid` and `ipv4Address` slots from `e507fdc9cbf67095`. A Wi-Fi network name can be looked up in public Wi-Fi location databases. **(design call)**
- Keep sending the hostname. The consent example shows it, and the docs say how to change it. **(design call)**
  - Changing the hostname from tm-control is out of scope. It would need a polkit rule for hostname1, handling for the `.local` name changing mid-setup, and a rewrite of `TM_HOSTNAME`.

### 6. Consent in tm-control

- A step in first run, after the EULA, plus a Sharing page for changing the choices later.
- One checkbox per consent: share data, exact location, and public map.
  - Each is off by default, worded plainly, and shows an example of exactly what would be sent.
  - Each can be withdrawn on the same page.
- Recorded the way the EULA is: a versioned notice file, with the version, time, and user stored in `state.sqlite`.
- **A new notice version** asks again without pausing sharing. If the new version adds data, only the added data waits for consent. **(maintainer)**
- **Upgrading a unit that already uploads (maintainer):**
  - It keeps uploading at the share-data level, with the location rounded.
  - The exact location stops until an admin ticks its checkbox.
  - tm-control asks an admin to review sharing.
  - The record says sharing was on before the consent screens existed, and when the upgrade found it.
  - The release notes say that exact locations stop until someone opts in, including for operators who send to their own servers.
- An admin-only **Export exact locations** downloads the deployment history from `state.sqlite`, with a warning about what the file reveals. The whole-database download stays as it is, because it no longer holds exact locations.
- **Copy diagnostics** also strips the exact location, hostname, and serial. Backups (#173) treat `config.yml` and `state.sqlite` as private.

### 7. Public map **(maintainer)**

- **Block level.** The map highlights the street between two intersections, the way traffic-count reports name a count location: "Main St between 1st Ave and 2nd Ave". Segment shapes come from OpenStreetMap road data. The map shows no point and no house number.
- The operator picks the block, and the side of the street, on a map when turning on the map opt-in.
  - Which tool hosts that pick, tm-control when online or the server's own page, is left to the location spec.
  - Either way, the map never needs the exact location.
- **Short segments**, such as a cul-de-sac, narrow it down to a few homes. Merge them with the next segment or warn the operator. **(design call)**
- **Delayed totals:**
  - Daily and hourly counts by object type, and 85th-percentile speed (V85).
  - Published a day or more late, never live. **(design call on the delay)**
  - Hours with fewer than about 5 vehicles are hidden, because a single car on a quiet street can be identified by its neighbors. **(design call)**
  - No operator identity, serial, hostname, or images.
  - Consider capping each public view's date range, such as two weeks, and offering bulk data by agreement, to discourage scraping. **(design call)**

## Server-side practices (the maintainer's server, outside this repo)

"The maintainer's server" means the maintainer's ThingsBoard instance, or whatever replaces it.

- Keep exact locations in admin-only fields. Public dashboards read only public fields: the segment and the delayed totals.
- Honor the consent flags the device sends.
  - When exact-location consent is withdrawn, delete the exact history and keep the rounded one.
  - When map consent is withdrawn, take the unit off the map promptly.
- Keep sales records, which link a serial to a buyer and a shipping address, apart from telemetry, with access limited to those who need it.
- Delete the stale `system_ssid` and `system_ipv4Address` attributes that older versions sent.
- Publish a short privacy notice for operators, versioned like the EULA: what's sent, why, who sees it, how long it's kept, and how to withdraw.

## Until the location feature ships

- No code changes. If an operator enters a location, `tmdb.sqlite` holds it exactly.
  - The docs' Data and privacy page flags the `deployment` table as possibly identifying.
  - CONTRIBUTING.md says to blank or round lat/lon before sharing `config.yml`.
- Optional: a short docs tip on rounding the `deployment` table before sharing a database.

## Follow-ups, decided separately

- A random install ID in place of the Pi serial in `deviceName`. Anyone with the sales records can link the serial to a buyer's address, whatever the location setting.

## Left to the location feature spec

- Screens and API endpoints, and how tm-control writes `config.yml`: atomic replace, and keeping the operator's other settings.
- Where the block is picked, and where segment data comes from.
- How DIY builders request a token for the maintainer's server, and how sold units get theirs installed.
- The upload gate's payload shapes and attribute names, and how consent flags reach an operator's own server.
- What `survey_id` means and who assigns it.
- The wording of the privacy notice, a placeholder until the project supplies it, as with the EULA.

## Verification, when it's built

- `python -m pytest container/node-red-tm/schema/tests` covers:
  - rounding existing rows, NULLs, and the new columns
  - the flows' SQL against the schema
- Reserialize `flows.json` byte-for-byte as CLAUDE.md describes, check it with `python3 -m json.tool`, and run `mkdocs build --strict` for the docs changes.
- On a dev Pi with `pii_free: true`:
  1. A new deployment gives rounded rows with `location_precision` set.
  2. `none` stores NULL.
  3. No value in `tmdb.sqlite` is finer than 2 decimal places.
  4. The upload gate's output matches each consent level.
  5. Withdrawing a consent stops the matching data at once.

## Sources

- California's definition, 1,850 ft: [AB 322 and precise geolocation](https://calawyers.org/privacy-law/ab-322-an-attempt-to-place-guardrails-on-the-collection-of-precise-geolocation-information/) (California Lawyers Association)
- Virginia's 1,750 ft and its opt-in rule: [Precise geolocation: recent trends and enforcement](https://www.bclplaw.com/en-US/events-insights-news/precise-geolocation-recent-trends-and-enforcement.html) (Bryan Cave Leighton Paisner)
