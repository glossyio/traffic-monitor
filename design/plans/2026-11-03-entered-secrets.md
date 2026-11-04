# Entered secrets: the mechanism, with the ThingsBoard token and the Plate Recognizer credentials as its first users

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin type the ThingsBoard access token and the Plate Recognizer API token and license key into the control app, store them with the device's other secrets, get each to its service as an environment variable, and take every secret slot out of `config.yml` on new installs and at upgrade, with one job and one request shape that the next entered secret reuses.

**Architecture:**
- The secrets directory gets a second kind of file. `tmsetup_entered_secret_names` lists secrets a person supplies; tmsetup creates each as an *empty* root-owned file, never a random string, and reads both lists into `tmsetup_secrets`. The three are `thingsboard_access_token`, `plate_recognizer_token`, and `plate_recognizer_license_key`. The installer takes no secret value: `tmsetup_thingsboard_api_key` goes.
- Env files are the only carrier, and every secret line in them is rendered from the secrets directory: `TM_THINGSBOARD_ACCESS_TOKEN` and `TM_PLATE_RECOGNIZER_TOKEN` in `node-red-tm.env`, `TOKEN` and `LICENSE_KEY` in `plate-recognizer.env` (template lines for new files, `lineinfile` on every run for existing ones, so `-f` keeps them). Node-RED reads both tokens from `env`; the ThingsBoard URL builder honours `protocol` (issue 95). `config.yml.j2` loses `access_token`, the `addons.plate_recognizer` section keeps only `url`, and the contract check warns when either secret key is still present.
- `tm-control migrate` gains `--node-red-config` and `--plate-recognizer-env`: it moves a token found in an existing `config.yml` (both keys, which it deletes) or a hand-entered `plate-recognizer.env` into the secret files, as root. A new task file, `entered_secrets.yml`, runs it before the node-red-tm and plate-recognizer tasks render anything, then re-reads the entered secrets.
- A second root job, `tm-job-set-secret.service`, takes `{"name", "value"}` from `/run/tm-control/jobs/set-secret.json`, refuses any name not in its fixed table, writes the secret file, rewrites the env lines in place, and restarts the listed units. A `secrets` module gives the API `GET /secrets` (the entered secrets this device has: the Plate Recognizer ones only when the add-on is installed), `POST /secrets/{name}`, and `DELETE /secrets/{name}` (admins; the last two start the job), and the Configuration check group gains `config.thingsboard`.
- The forms live on the Device page for now, one section listing every secret `GET /secrets` returns: set/not set with the last four characters where that's safe, a password field with a Show toggle, Save, and a confirmed Remove. The Sharing page (plan 4) and a later add-on page take the component over; moving it is cheap.

**Tech Stack:** Ansible (the tmsetup role, `community.general.random_string`, `lineinfile`, `slurp`), Jinja2 templates, Python 3.11 (FastAPI, pydantic, ruamel.yaml, the stdlib-only job script, pytest), Node-RED 5.0.8 flows (function, switch, and template nodes; the template node reads `{{env.NAME}}`, the switch node tests an `env` property), Vue 3 + Vuetify 3 + TypeScript (Vitest), Material for MkDocs.

**Spec:** the entered-secrets design (not yet published), all sections, with its "Amendments (2026-11-03)" section, which moves the Plate Recognizer row of section 7 into scope, drops the installer variable, and makes migrate delete the keys. Read it with this plan. Where this plan and the design still disagree, the "Decisions" list below says why; say so in the PR rather than picking one silently.

**Status:** written 2026-11-03 against `feature/tmdb-survey-id/250` at `7965a9d` (PR 277, plan 1, which contains PR 269 (M3), PR 261, and `dev` at `469b575`); amended the same day for the maintainer's scope answers (Plate Recognizer in, installer variable out, keys deleted). Branch: `feature/entered-secrets/95` (the issue this closes), stacked on plan 1's branch; this file was added in the PR that implements it.

**Decisions made while writing this plan** (each marked **(call)** in the sense of the design; 1 to 7 from the first draft, 8 to 11 from the 2026-11-03 scope answers):
1. **Base branch is plan 1's, not M3's.** Both plans edit `init config defaults` (`94136e5a6f092bb6`), `config.yml.j2`'s template, `test_node_red_flows.py`, `node-red-config.md`, `setup-guide.md`, and `CLAUDE.md`. A branch off M3 would conflict with PR 277 at merge, and plan 4 needs both anyway. The stacked-PR routine applies: retarget when 277 merges.
2. **The forms go on the Device page**, under one heading, until plan 4's Sharing page and an add-on page exist. The alternative, a backend-only PR with no way to enter a token without SSH, would leave goal 1 of the design unmet for one more PR.
3. **Remove is `DELETE /secrets/{name}`**, not a POST with an empty value. The job request is the design's (`value: ""`); only the HTTP verb differs, and it keeps "an empty POST is refused" simple.
4. **Each entered secret has its own value pattern**, in the job's table and the API's. The ThingsBoard token goes into a URL path, so the design's "printable ASCII, no whitespace" would let `/`, `?`, or `#` break the upload URL: it accepts `[A-Za-z0-9._~-]{1,256}` (URL-unreserved characters; ThingsBoard issues 20 alphanumerics). The Plate Recognizer token and license key go into a header and an env line, so they take the design's rule, `[\x21-\x7e]{1,256}`.
5. **The migrate step runs as root from its own task file, before any config template task**, not from `frigate_credentials.yml`. Root is needed to write the secret files; running first means `-f` on an upgrade can't throw away the only copy of a value; and tmsetup must re-read the secrets after the move, which the Frigate task's position doesn't allow. The step is still "the go2rtc credential step's pattern": `tm-control migrate`, a backup, no value printed.
6. **Migrated keys are deleted, not blanked** (the design said blanked; the maintainer chose the phase-out on 2026-11-03). `config.yml` ends with no secret slot at all; the contract check warns when a key is present with any value, since nothing reads it.
7. **`config_secret_values` in `diagnostics.py` goes.** Once no key exists, that code reads nothing; the secrets' files are in `DEVICE_SECRETS`, and `ENV_SECRET_KEY` catches every env line, so each value is redacted twice without it.
8. **The Plate Recognizer token and license key are entered secrets from the start**, rather than waiting for their page. Today the token sits in two files (`plate-recognizer.env` and `config.yml`), the license key in one, and `-f` wipes both; with this plan `config.yml` holds no secret and the env lines survive `-f`. The add-on gets no page of its own yet: its two rows appear in the Device page's section only when the manifest says the add-on is installed.
9. **`tmsetup_thingsboard_api_key` is removed** (defaults, template, docs; it was never documented and `tmsetup.sh` has no flag for it). The installer takes no secret value; the Device page and the root-owned file are the two ways in. Anyone passing it through `--extra-vars` loses that path; the release note says so.
10. **A hand-entered `plate-recognizer.env` is a migration source**: `TOKEN`/`LICENSE_KEY` values other than the template's placeholders (`YYYYY`, `XXXXX`) and empty move into the secret files once, at the first run of this version. After that the env file is rendered from the secrets, never read.
11. **`GET /secrets` carries what the UI needs to render each secret** (`title`, `restarts`), so the Device page loops over the answer and the component stays page-agnostic for plan 4.

**Where M3 and plan 1 left things that this plan touches:**
- Root jobs: `core/jobs.py` has `JobRunner(settings, state, systemd)` with `start(name, request, user_id) -> Job` (writes `<runtime_dir>/jobs/<name>.json` 0600 with `O_EXCL`, 409 `job_running` while a request waits or the unit runs, starts `tm-job-<name>.service`) and `get(job_id)`; `JOB_NAMES = {"system-password"}`; `FakeJobRunner` keeps `last_request` and succeeds at once. `modules/jobs/router.py` is `GET /jobs/{id}` (admins). `modules/system/router.py`'s `POST /system/password` is the pattern for a route that starts a job: validate, `app_state.jobs.start(...)`, `Audit(app_state.state).record(admin.id, "system.password")`, return `{"id": job.id}` with 202.
- `tm-control/jobs/tm-job-system-password` is the job script to copy: stdlib only, `read_manifest`, `open_jobs_dir` (owner and mode checks), `read_request` (regular file, one link, `MAX_REQUEST` 4096, exact keys), `check`, `delete_request` in `finally`, `refused: ...` / `failed: <ExceptionName>` on stdout, exit 0/1, a `CHPASSWD` override ignored when euid is 0. Its tests run it through `tests/fixtures/run_job.py` (`TEST_ACCOUNTS`, a non-root euid). The unit template is `templates/tm-control/tm-job-system-password.service.j2` (oneshot, `-EP`, `Environment=TM_CONTROL_MANIFEST=`, `StartLimitIntervalSec=0`, no `[Install]`); `tm-control_service.yml` installs the units from a two-item loop; `tmsetup_tm_control_polkit.units` lists the seven units polkit allows.
- `core/secrets.py`: `NAMES` (the four tm-control needs to start), `DEVICE_SECRETS` (those plus `go2rtc_rtsp_password`; `tests/test_api_system_info.py::test_device_secrets_match_the_role` asserts it equals the role's `tmsetup_secret_names`), `Secrets.read` (cached, `MissingSecret` on an empty file), `FakeSecrets.read` returns `fake-<name>-not-secret`. `diagnostics.py`: `secret_values` reads every `DEVICE_SECRETS` name (skipping `MissingSecret`), `env_secret_values` (reads `node-red-tm.env`, `frigate.env`, `plate-recognizer.env`; `ENV_SECRET_KEY` matches `TOKEN` and `KEY`), and `config_secret_values` (config.yml's `access_token`, with two tests). `core/manifest.py`: `Manifest.options: dict[str, bool]` holds `plate_recognizer`; `modules/services/units.py::units_for` filters units by `manifest.options.get(unit.option, False)`.
- `core/migrate.py`: `run(frigate_config, dry_run)` for Frigate only; `cli.py`'s `migrate` requires `--frigate-config`. `adapters/yamlfile.py`: `RoundTripFile(path).data`, `.save()` (backup `config.yml.<stamp>.bak`, atomic, keeps mode and, as root, owner), `write_atomic(path, text)`. `frigate_credentials.yml` runs `tm-control migrate` through `runuser` as the code owner with `changed_when: "not ...stdout.endswith(': up to date')"` and a debug task that shows `WARNING` lines from stderr.
- `modules/apps/contracts.py`: `GROUP = CheckGroup("config", "Configuration", [cameras_in_config, zones, radar_names, location])`; `tests/test_contract_checks.py::test_cameras_match` asserts the exact id and title lists; `tests/fixtures/status_fake.json` lists the config group's four checks; `script/devpi/tests/test_web.py::CONFIG_CHECKS` names the four for the inventory test. `Check(id, title, status, detail, fix)` with `Fix(kind="link", text, href)`.
- `core/errors.py` strips `input` from 422 details; `CsrfMiddleware` covers every non-GET; uvicorn runs with `log_config=None`, and nothing logs request bodies.
- Role: `tasks/secrets.yml` has four tasks (directory, generate with `force: false`, slurp, set_fact), all but the first `no_log` (`test_every_task_that_touches_secret_values_hides_its_output`); `tmsetup_secret_names` has five names (`vars/main.yml`). `tasks/main.yml` order under the tags that matter: `tm-control_setup.yml` and `tm-control_service.yml` (tags podman, frigate, node-red-tm, go2rtc, revproxy, tm-control) → `frigate_setup.yml` → `frigate_credentials.yml` → `node-red-tm_setup.yml` (tag node-red-tm) → `plate-recognizer_setup.yml` (tag plate-recognizer, gated on `tmsetup_bool_plate_recognizer`). `node-red-tm_setup.yml` order: directories → static files → schema → Containerfile → "Create Node-RED-TM Configs" (template, `force: '{{ tmsetup_force_configs }}'`) → "Check for node-red-tm.env" (stat) → `TM_NR_TOKEN_KEY` lineinfile → `TM_INTERNAL_TOKEN` lineinfile → Quadlets → build. `plate-recognizer_setup.yml`: directories → "Create plate-recognizer environment file" (template, same `force`) → Containerfile → Quadlets → build, each notifying `Restart plate-recognizer.service`; no `lineinfile`, no `no_log`. `container/plate-recognizer/plate-recognizer.env.j2` is three literal lines (`TOKEN=YYYYY`, `LICENSE_KEY=XXXXX`, `WORKERS=2`); the container unit loads it with `EnvironmentFile=`. `defaults/main.yml`: `tmsetup_thingsboard_api_key: ''` (used only by `config.yml.j2`; no test or docs page names it), `tmsetup_thingsboard_server`, `_protocol`, `_port`; `tmsetup.sh -C` passes only `tmsetup_bool_*`. `config.yml.j2`'s `thingsboard:` block: `enabled`, `host`, `protocol`, commented `port`, `access_token: {{ tmsetup_thingsboard_api_key }}`; it has no `addons` section (the docs tell operators to add one by hand).
- Flows, `thingsboard` tab `f7932be9acc7391c`: `init config defaults` (`94136e5a6f092bb6`, `init-config` tab) builds `thingsboard.url` as `host[:port]` with no scheme, then rewrites `protocol` (`https` → `http`, `mqtts` → `mqtt`) for the switch `tb protocol?` (`9b8c2bcc16a637fd`, reads `global config.thingsboard.protocol`, `http` → `msg.type?` `dd3f9ef16332021c`, `mqtt` → nothing), and warns when `access_token` is undefined. `msg.type?` feeds template `telemetry msg.url` (`9c944328e288b2dc`) or `attributes msg.url` (`d739b10ce5fa8f40`), both `{{{global.config.thingsboard.url}}}/api/v1/{{{global.config.thingsboard.access_token}}}/...`, into http request `tb post http api` (`677a57bbf3619854`). The restore button `0372cefb5e2ec968` (ui_button) wires straight into http request `read config file from ThingsBoard` (`56cafb11de5348b2`), whose `url` is `{{global.config.thingsboard.url}}/api/v1/{{global.config.access_token}}/attributes?clientKeys=backup`; the http request node renders its URL against `msg` only, so that URL has rendered empty for as long as it has existed. The template node's mustache context resolves `env.NAME` (`80-template.js`). `plate-recognizer` tab: switch `is camera plate_recognizer enabled?` (`b8705f8be97656d3`) → switch `is there a plate_recognizer token?` (`5e642eb684a874ef`: `propertyType: "global"`, `property: "config.addons.plate_recognizer.token"`, one rule `nnull`) → `53d832d8012b843b`; function `format http request` (`ce5360091646c733`) reads `global.get("config.addons.plate_recognizer.token")` and `.url`, sets `msg.headers.Authorization = "Token " + token` and `msg.url = url + "/v1/plate-reader/"`; http request `plate-recognizer http api` (`e0ff592e8f562a10`) has empty `url` and `headers`. No other node reads `addons`. `test_node_red_flows.py` has `run_functions(steps, env, context)`, `named`, `new_device_config`, and `test_thingsboard_without_a_host_is_a_config_error` (gives the config an `access_token`).
- UI: `DevicePage.vue` has sections Software, then for admins Diagnostics and Power, and one `ConfirmDialog` for the power actions; `device-page.spec.ts` uses `signedIn(ADMIN|VIEWER, answers)`, `mountApp('/device')`, `headings`, `click`, `clickInDialog`, `dialogText`. `SetupPage.vue` polls `GET /jobs/{id}` every `JOB_POLL_MS` until `JOB_DEADLINE_MS` with a `left` flag cleared on unmount; `setup-flow.spec.ts` pins that behaviour with fake timers. `api/types.ts` exports `Job` from the schema; the openapi document is committed (`test_openapi_document.py`) and regenerated with `dump-openapi` + `npm run api:generate`. The fixture manifest has `options.plate_recognizer: false`.
- Device tests: `test_web.py::test_diagnostics_has_no_secret_value` and `test_no_secret_in_the_install_log` compare `tmsetup_secret_names` / `CONTROL_APP_SECRETS` with text on the Pi through `sudo test -s` and print `missing` for an empty file; `test_services.py` has the polkit tests and expects no Plate Recognizer on pii_free units; `test_disruptive.py` has `invocation`, `not_restarted`, `wait_until_ready`, and `test_restart_from_the_control_app` as the pattern for an action through the API.
- Docs that tell an operator to put a secret in a file today: `docs/add-ons/plate-recognizer.md` steps 2 to 4 (`TOKEN`/`LICENSE_KEY` in the env file, `addons.plate_recognizer.token` and `url` in `config.yml`, restart the add-on), `docs/configuration/node-red-config.md` (the `access_token` row, "the one secret in the file"; the `addons.plate_recognizer` section with a `token` row), `docs/configuration/environment.md` (the env table), `docs/use/system-admin.md` and `docs/reference/tmsetup.md` (list `plate-recognizer.env` among the credentials files `-f` replaces).

## Global Constraints

- No secret value ever appears in: a journal line, tm-control's log, the audit table, an API response, a test name or assertion message, a commit, or the PR. Every Ansible task that handles a value is `no_log: true`. Tests use placeholders of the form `tb-placeholder-<digits>` / `pr-placeholder-<digits>`; never a real token or key.
- The secrets directory stays `root:{{ tmsetup_codegroup }}` 0750 with files 0640; tm-control's own user never writes it (`ProtectSystem=strict`, no `ReadWritePaths=`); root work goes through the job.
- An empty secret file means "not set" everywhere: tmsetup renders an empty env value, `Secrets.read` raises `MissingSecret`, `is_set` is false, Node-RED turns the upload off and skips plate reads. The Plate Recognizer template's placeholders `YYYYY` and `XXXXX` count as empty wherever an env file is read.
- `config.yml` holds no secret after this plan: no key for one in the template, none left by migrate, and a warning on the Status page when a person puts one back.
- `flows.json` is edited programmatically and re-serialised with `json.dumps(flows, indent=4, ensure_ascii=False)` and no trailing newline; named node ids keep their ids; new nodes get fresh 16-hex ids; `python3 -m json.tool` must parse it.
- The job script imports only the standard library and nothing from `tm_control`; it runs from the root-owned copy with `python -EP`.
- Every commit ends with the trailer block from the repo's CLAUDE.md (Assisted-by / AI-Model / AI-Effort / AI-Role); never `Co-Authored-By`. Docs follow "Writing docs" in `docs/development/contributing.md`; `mkdocs build --strict` passes.
- Off-device checks before each commit, from the repo root in the dev venv: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`; for UI tasks also `cd tm-control/ui && npm test && npm run build`.

## Review Focus

1. A token that YAML read as a number (`access_token: 1234567890123456789`): migrate must move its text, not refuse it or write a float. Test in Task 3 (`test_moves_a_numeric_token_as_text`).
2. A value with a character the env line or the URL path can't carry (`/`, `?`, `#`, a space, a quote, a non-ASCII letter, a line break): the API answers 422 and the job refuses, so it never reaches an env file. Tests in Task 5 (`test_refuses_values_the_env_line_or_url_cannot_carry`) and Task 6 (`test_set_secret_enforces_the_value_pattern`).
3. The restart fails after the secret was written (a unit refuses to start): the job must report `failed` with a log line saying the secret is written, delete its request, and let the next Save run. Test in Task 5 (`test_a_failed_restart_is_reported_after_the_secret_is_written`).
4. `tmsetup.sh -f` on an upgrade: the old `config.yml` and `plate-recognizer.env` are replaced by templates, so each value's only copy must be moved first, and `-t plate-recognizer` alone must not blank a hand-entered env file. Tests in Task 3 (`test_entered_secrets_move_before_any_config_template_renders`, `test_plate_recognizer_env_values_move_once_and_placeholders_do_not`).
5. An older `config.yml` with no `thingsboard:` or `addons:` block, or one that isn't a mapping: migrate must print `up to date` and exit 0, not crash the installer. Test in Task 3 (`test_a_config_without_the_mappings_is_up_to_date`).

---

### Task 1: Entered secrets in `core/secrets.py`, and diagnostics stop reading `config.yml` for a token

**Files:**
- Modify: `tm-control/backend/tm_control/core/secrets.py`, `tm-control/backend/tm_control/modules/system/diagnostics.py`
- Test: `tm-control/backend/tests/test_api_system_info.py`, `tm-control/backend/tests/test_secrets.py` (new)

**Interfaces:**
- Produces: `THINGSBOARD_ACCESS_TOKEN = "thingsboard_access_token"`, `PLATE_RECOGNIZER_TOKEN = "plate_recognizer_token"`, `PLATE_RECOGNIZER_LICENSE_KEY = "plate_recognizer_license_key"`; `GENERATED_SECRETS` (the five names, in the role's order); `ENTERED_SECRETS = (THINGSBOARD_ACCESS_TOKEN, PLATE_RECOGNIZER_TOKEN, PLATE_RECOGNIZER_LICENSE_KEY)`; `DEVICE_SECRETS = GENERATED_SECRETS + ENTERED_SECRETS`; `NAMES` unchanged. `Secrets.read(name)` caches generated names only, so an entered secret the job just wrote is read fresh. `Secrets.is_set(name) -> bool` (a readable file with non-whitespace content; never raises for an entered name, and `ValueError` for a bad name as `read` does). `Secrets.ends_with(name, count=4) -> str | None` (the last `count` characters of the stripped value, or `None` when not set). `FakeSecrets.entered: dict[str, str]` (initially every entered name → `""`); its `read` returns the entered value or raises `MissingSecret` for an entered name, and `fake-<name>-not-secret` for the rest; `is_set`/`ends_with` follow it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_secrets.py
def test_generated_and_entered_names_match_the_role(): ...
    # list(GENERATED_SECRETS) == vars["tmsetup_secret_names"]; list(ENTERED_SECRETS) == vars["tmsetup_entered_secret_names"]
    # (the role's list is Task 2; write this test now, it fails until then); set(NAMES) <= set(GENERATED_SECRETS)

def test_is_set_and_ends_with_follow_the_file(tmp_path): ...
    # empty file → is_set False, ends_with None; "tb-placeholder-9876\n" → True, "9876"; "ab" → True, "ab"
    # a missing file → False; read() raises MissingSecret while empty, returns the value once written (no cache)

def test_read_caches_generated_names_only(tmp_path): ...
    # write session key, read, overwrite the file → read returns the first value; same for the token → the new value

def test_fake_secrets_entered_values(): ...
    # FakeSecrets().is_set(name) is False for each of ENTERED_SECRETS; set entered[...] = "tb-placeholder-0001" → True, "0001"
```

In `test_api_system_info.py`: replace `test_device_secrets_match_the_role`'s body with the two-list assertion above (keep its name), change `test_diagnostics_never_contains_a_secret_value` to write the entered files too and expect `len(values) == 8`, delete `test_diagnostics_redacts_the_thingsboard_access_token` and `test_a_blank_or_short_thingsboard_access_token_redacts_nothing`, and add:

```python
def test_diagnostics_redacts_an_entered_secret(device_client, login, host): ...
    # secrets_dir / "plate_recognizer_token" holds "pr-placeholder-345"; journal plants it twice → absent, "<redacted>" present

def test_diagnostics_skips_an_empty_entered_secret(device_client, login, host): ...
    # the file is empty → 200, and "abc stays" in a planted journal line stays
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_secrets.py tm-control/backend/tests/test_api_system_info.py -k "secret or diagnostics" -v`
Expected: FAIL (`ENTERED_SECRETS` missing; `config_secret_values` still imported).

- [ ] **Step 3: Change `secrets.py` and `diagnostics.py`**

Add the names and the two methods; `read` keeps its cache for `GENERATED_SECRETS` and reads an entered name every time. Delete `config_secret_values` and its call in `secret_values`; the `nodered` import goes if nothing else uses it; the module docstring's parenthesis about `config.yml`'s token becomes "and the entered secrets' values".

- [ ] **Step 4: Run the backend suite**

Run: `python -m pytest tm-control/backend/tests -v`
Expected: PASS except `test_generated_and_entered_names_match_the_role` (the role's list comes in Task 2; commit it failing only if the Task 2 commit follows at once, otherwise mark it `xfail(strict=True)` with reason "Task 2" and remove the mark there).

- [ ] **Step 5: Commit**

"Add entered secrets to core/secrets.py and stop reading config.yml for a token".

---

### Task 2: tmsetup creates and reads entered secrets, renders every secret env line from them, and takes no secret value

**Files:**
- Modify: `script/ansible/roles/tmsetup/vars/main.yml`, `defaults/main.yml`, `tasks/secrets.yml`, `tasks/node-red-tm_setup.yml`, `tasks/plate-recognizer_setup.yml`, `container/node-red-tm/node-red-tm.env.j2`, `container/node-red-tm/config/config.yml.j2`, `container/plate-recognizer/plate-recognizer.env.j2`
- Test: `script/tests/test_tmsetup_tasks.py`, `script/tests/test_tmsetup_templates.py`, `script/tests/test_tm_control_install.py`

**Interfaces:**
- Produces: `tmsetup_entered_secret_names: [thingsboard_access_token, plate_recognizer_token, plate_recognizer_license_key]` in `vars/main.yml`, under the generated list, with a comment saying these are typed in and start empty. `tmsetup_thingsboard_api_key` removed from `defaults/main.yml`. `tmsetup_secrets` holds both lists' values (an entered one may be `''`). On the device: one empty root:codegroup 0640 file per entered name. `node-red-tm.env` has `TM_THINGSBOARD_ACCESS_TOKEN=<value>` and `TM_PLATE_RECOGNIZER_TOKEN=<value>`; `plate-recognizer.env` has `TOKEN=<value>` and `LICENSE_KEY=<value>` (template lines for new files; `lineinfile` on every run for existing ones, like `TM_INTERNAL_TOKEN`, the plate-recognizer ones notifying `Restart plate-recognizer.service`). `config.yml.j2`'s `thingsboard:` block has no `access_token` key and a comment saying where the token lives.

- [ ] **Step 1: Write the failing tests**

In `test_tmsetup_tasks.py`, next to the secrets tests:

```python
def test_entered_secrets_start_empty_and_are_never_regenerated(): ...
    # task "TMSetup - Secrets - Create missing entered secrets as empty files": ansible.builtin.copy with content "",
    # force False, owner root, group "{{ tmsetup_codegroup }}", mode "0640", loop "{{ tmsetup_entered_secret_names }}", no_log

def test_both_secret_lists_are_read_into_one_fact(): ...
    # the slurp's loop and the set_fact's dict both use "tmsetup_secret_names + tmsetup_entered_secret_names"

def test_the_installer_takes_no_secret_value(): ...
    # "tmsetup_thingsboard_api_key" not in defaults; no key of defaults or vars ends with _api_key or _access_token;
    # no template under container/ or the role's templates/ mentions tmsetup_thingsboard_api_key

@pytest.mark.parametrize("task_file, key, secret, handler", [
    ("tasks/node-red-tm_setup.yml", "TM_THINGSBOARD_ACCESS_TOKEN", "thingsboard_access_token", "Restart node-red-tm.service"),
    ("tasks/node-red-tm_setup.yml", "TM_PLATE_RECOGNIZER_TOKEN", "plate_recognizer_token", "Restart node-red-tm.service"),
    ("tasks/plate-recognizer_setup.yml", "TOKEN", "plate_recognizer_token", "Restart plate-recognizer.service"),
    ("tasks/plate-recognizer_setup.yml", "LICENSE_KEY", "plate_recognizer_license_key", "Restart plate-recognizer.service"),
])
def test_entered_secret_env_lines_are_written_on_every_run(task_file, key, secret, handler): ...
    # as test_node_red_env_gains_the_internal_token_on_every_run: regexp f"^{key}=", line f"{key}={{{{ tmsetup_secrets['{secret}'] }}}}",
    # no_log, become, notify, `when` names a stat of the env file, after the template task and before the quadlets
```

`test_every_task_that_touches_secret_values_hides_its_output` already covers the new secrets task.

In `test_tmsetup_templates.py`: `render_node_red_env` passes the three entered placeholders in `tmsetup_secrets`;

```python
def test_node_red_env_template_carries_the_entered_tokens(): ...
    # "TM_THINGSBOARD_ACCESS_TOKEN=tb-placeholder-0001" and "TM_PLATE_RECOGNIZER_TOKEN=pr-placeholder-0002" in lines, each
    # preceded by a "# " comment naming the Device page

def test_plate_recognizer_env_template_renders_from_the_secrets(): ...
    # render plate-recognizer.env.j2 with tmsetup_secrets → lines == ["TOKEN=pr-placeholder-0002", "LICENSE_KEY=pr-placeholder-0003", "WORKERS=2"]
    # plus comment lines; "YYYYY" and "XXXXX" absent

def test_node_red_config_template_has_no_secret_key(): ...
    # render config.yml.j2 as new_device_config does (defaults + lat/lon/bearing); "access_token" and "addons" not in text;
    # yaml.safe_load(text)["thingsboard"] keys == {"enabled", "host", "protocol"}
```

In `test_tm_control_install.py`: `install()` also writes each `tmsetup_entered_secret_names` file empty; `test_tm_control_starts_with_only_the_files_tmsetup_writes` unchanged (it must still pass with empty entered files).

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest script/tests -k "entered or secret_lists or no_secret or every_run or plate_recognizer_env" -v`
Expected: FAIL.

- [ ] **Step 3: Change the role and the templates**

`secrets.yml`: the create task after "Generate missing secrets", then the read tasks over the combined list (the `zip` in the set_fact over the same combined list). `defaults/main.yml`: delete `tmsetup_thingsboard_api_key`. `node-red-tm.env.j2`: a comment and the two lines after the MQTT block. `plate-recognizer.env.j2`: a header comment (values come from the secrets directory; set them on the Device page) and the two rendered lines before `WORKERS=2`. `node-red-tm_setup.yml`: the two lineinfiles after the `TM_INTERNAL_TOKEN` one, with the same `when`, `no_log`, `become`, and `notify`. `plate-recognizer_setup.yml`: a stat of the env file after the template task, then the two lineinfiles (`when` the file exists, `no_log`, `become`, `notify: Restart plate-recognizer.service`), before the quadlet task. `config.yml.j2`: drop the `access_token` line and add, under `thingsboard:`, the comment `# The access token isn't kept in this file. Set it on the control app's Device page.`

- [ ] **Step 4: Run every off-device check**

Run: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests -v && (cd script/ansible && ansible-playbook -i localhost setup.yml --syntax-check </dev/null >/dev/null)`
Expected: PASS, including Task 1's list test (remove its `xfail` if it was added). `test_thingsboard_without_a_host_is_a_config_error` still passes (it sets `access_token` on its own dict; Task 4 changes that).

- [ ] **Step 5: Commit**

"Create entered secrets empty in tmsetup, render every secret env line from them, and drop tmsetup_thingsboard_api_key".

---

### Task 3: `tm-control migrate` moves the secrets out of `config.yml` and a hand-entered `plate-recognizer.env`

**Files:**
- Modify: `tm-control/backend/tm_control/core/migrate.py`, `tm-control/backend/tm_control/cli.py`, `script/ansible/roles/tmsetup/tasks/main.yml`
- Create: `script/ansible/roles/tmsetup/tasks/entered_secrets.yml`
- Test: `tm-control/backend/tests/test_entered_secrets_migration.py` (new), `tm-control/backend/tests/test_tm_control_cli.py`, `script/tests/test_tmsetup_tasks.py`

**Interfaces:**
- Produces: `migrate.run_node_red(config_path: Path, secrets_dir: Path, dry_run: bool = False) -> int` and `migrate.run_plate_recognizer_env(env_path: Path, secrets_dir: Path, dry_run: bool = False) -> int`. Output lines start with `PREFIX`; for `config.yml` the success lines are `<path>: up to date`, `<path>: moved thingsboard.access_token to the secrets file (backup: <bak>)`, `... moved addons.plate_recognizer.token ...`, `<path>: removed thingsboard.access_token from config.yml, which the secrets file already holds (backup: <bak>)`, several joined with `, ` as the Frigate step does, and with `--dry-run` `would move ...` / `would remove ...`. For the env file: `<path>: up to date`, `<path>: moved TOKEN, LICENSE_KEY to the secrets files` (no backup: the file is rendered again by tmsetup on the same run; its value lines are left as they are), `would move ...`. Warnings go to stderr as `WARNING ...` and name the key only. Both functions delete the moved key from `config.yml` (`addons.plate_recognizer` keeps `url`; an `addons` or `addons.plate_recognizer` mapping left empty is deleted too). The CLI: `migrate [--frigate-config PATH] [--node-red-config PATH] [--plate-recognizer-env PATH] [--secrets-dir DIR] [--dry-run]`; at least one config option, else exit 2 with argparse's error; `--secrets-dir` defaults to `TM_CONTROL_SECRETS_DIR` or `/etc/traffic-monitor/secrets`; with several options, each runs and the exit code is the highest.
- `tasks/entered_secrets.yml` (header comment: why it runs first, and as root): `TMSetup - Entered Secrets - Check for config files that may hold one` (stat of `config.yml` and `plate-recognizer.env`, loop, register `tmsetup_entered_secrets_stat_register`), `TMSetup - Entered Secrets - Move them to the secrets directory` (become, `ansible.builtin.command` argv `/usr/local/bin/tm-control migrate --secrets-dir {{ tmsetup_secrets_dir }}` plus `--node-red-config <path>` and/or `--plate-recognizer-env <path>` for the files that exist, `when` at least one exists, register `tmsetup_entered_secrets_migrate_register`, `changed_when` as the Frigate step, `notify` both `Restart node-red-tm.service` and `Restart plate-recognizer.service`), a warnings debug task as the Frigate one, `TMSetup - Entered Secrets - Re-read the entered secrets` (slurp, loop over `tmsetup_entered_secret_names`, `no_log`), and `TMSetup - Entered Secrets - Update the secrets fact` (set_fact `tmsetup_secrets: "{{ tmsetup_secrets | combine(dict(tmsetup_entered_secret_names | zip(<decoded, trimmed values>))) }}"`, `no_log`). `tasks/main.yml` imports it right after `tm-control_service.yml` with that import's tags plus `plate-recognizer`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_entered_secrets_migration.py
# Fixtures: config_yml(tmp_path) writes the fixture node_red_config_ok.yml plus an addons block as the test says;
# secrets_dir(tmp_path) with the three entered files empty, dir 0750, files 0640; env_file(tmp_path) with the template's
# three lines, values as the test says.
TOKEN, PR_TOKEN, PR_KEY = "tb-placeholder-345", "pr-placeholder-346", "pr-placeholder-347"

def test_moves_both_tokens_into_the_empty_files_and_deletes_the_keys(config_yml, secrets_dir, capsys): ...
    # run_node_red → 0; files hold TOKEN + "\n" and PR_TOKEN + "\n"; config: no access_token key, no addons.plate_recognizer.token,
    # addons.plate_recognizer.url kept, the rest byte-identical apart from those lines; one .bak; stdout has both "moved" phrases;
    # no value in stdout + stderr
def test_an_addons_block_left_empty_is_removed(config_yml, secrets_dir): ...  # addons: {plate_recognizer: {token: X}} → no addons key
def test_running_twice_is_up_to_date(config_yml, secrets_dir, capsys): ...
def test_a_set_file_wins_over_a_different_key(config_yml, secrets_dir, capsys): ...
    # file "tb-placeholder-111", key "tb-placeholder-222" → file unchanged, key deleted, stderr WARNING names the key
    # and says the secrets file is kept; neither value in the output
def test_the_same_value_in_both_removes_the_key_quietly(config_yml, secrets_dir, capsys): ...  # "removed ..." line, no WARNING
def test_moves_a_numeric_token_as_text(config_yml, secrets_dir): ...  # access_token: 1234567890123456789 → file "1234567890123456789\n"
@pytest.mark.parametrize("block", ["", "thingsboard: 7\n", "thingsboard:\n  enabled: false\n", "thingsboard:\n  access_token:\n",
                                   "addons: 3\n", "addons:\n  plate_recognizer: x\n"])
def test_a_config_without_the_mappings_is_up_to_date(tmp_path, secrets_dir, block, capsys): ...  # 0, "up to date"
def test_a_missing_secret_file_is_created_with_the_directorys_group(config_yml, secrets_dir): ...
    # unlink the token file → after run: exists, mode 0o640, gid == secrets_dir's gid (owner check only when euid 0)
def test_dry_run_changes_nothing(config_yml, secrets_dir, capsys): ...  # "would move", files empty, keys intact, no .bak
def test_an_unreadable_secrets_dir_is_an_error(config_yml, tmp_path, capsys): ...  # missing dir → 1, "ERROR", config untouched
def test_a_yaml_error_is_reported_without_the_text(tmp_path, secrets_dir, capsys): ...  # as the Frigate tests: line/column, no content

def test_plate_recognizer_env_values_move_once_and_placeholders_do_not(env_file, secrets_dir, capsys): ...
    # TOKEN=PR_TOKEN, LICENSE_KEY=XXXXX → token file holds PR_TOKEN, key file stays empty, stdout "moved TOKEN"; a second run: "up to date";
    # TOKEN=YYYYY LICENSE_KEY= → up to date, nothing written
def test_plate_recognizer_env_does_not_overwrite_a_set_file(env_file, secrets_dir, capsys): ...  # file set, env differs → WARNING names TOKEN, file kept
def test_plate_recognizer_env_missing_or_unreadable(tmp_path, secrets_dir, capsys): ...  # missing → "up to date" 0 (the add-on isn't installed); a directory → ERROR 1
```

`test_tm_control_cli.py`: `test_migrate_requires_a_config_option` replaces `test_migrate_requires_the_frigate_config_option` (`main(["migrate"])` exits 2); `test_migrate_node_red_config_moves_the_tokens`; `test_migrate_plate_recognizer_env_moves_the_values`; `test_migrate_runs_every_config_given`.

`test_tmsetup_tasks.py`:

```python
def test_entered_secrets_move_before_any_config_template_renders(): ...
    # main.yml: the entered_secrets.yml import comes after tm-control_service.yml and before frigate_setup.yml, node-red-tm_setup.yml,
    # and plate-recognizer_setup.yml; its tags == tm-control_service's tags + ["plate-recognizer"]
    # entered_secrets.yml: the move task is become True with no runuser, argv[:2] == ["/usr/local/bin/tm-control", "migrate"],
    # "--secrets-dir" in argv, notify lists both restart handlers; re-read and update are no_log True; order stat < move < warnings < re-read < update
def test_entered_secrets_warnings_are_shown(): ...  # as test_frigate_config_update_warnings_are_shown, for tmsetup_entered_secrets_migrate_register
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_entered_secrets_migration.py tm-control/backend/tests/test_tm_control_cli.py script/tests/test_tmsetup_tasks.py -k "entered or migrate" -v`
Expected: FAIL (`run_node_red` undefined).

- [ ] **Step 3: Write the two functions, the CLI options, and the task file**

`run_node_red`: load with `RoundTripFile`; for each of `("thingsboard", "access_token", THINGSBOARD_ACCESS_TOKEN)` and `("addons", "plate_recognizer", "token", PLATE_RECOGNIZER_TOKEN)`: the parent must be a mapping holding a non-`None`, non-empty value, else nothing to do for that key. The key's text is `str(value).strip()` for `str`, `int`, and `float` values; a `bool` or container prints `WARNING <key path> isn't text; left as it is` and is skipped. Read the file (strip); missing → create empty with the directory's gid and 0640 (as root, owner root) before going on; an unreadable or missing directory → `ERROR` and 1. Then: file empty → write the text plus `\n` with `write_atomic` and delete the key; file equal → delete the key; file different → delete the key and warn. Delete empty `addons.plate_recognizer` and `addons` mappings afterwards. Save (backup); print the line. `--dry-run` prints `would ...` and writes nothing. `run_plate_recognizer_env`: read the file as `KEY=value` lines; for `TOKEN` → `PLATE_RECOGNIZER_TOKEN` and `LICENSE_KEY` → `PLATE_RECOGNIZER_LICENSE_KEY`, a value that is empty or one of `YYYYY`/`XXXXX` is "unset"; the secret file empty and the env value set → write it; both set and different → warn, file kept; otherwise nothing. The env file itself is not rewritten (tmsetup's lineinfile does that on the same run). A missing env file is `up to date`.

`cli.py`: the three config options optional, `--secrets-dir` with the default above, the "at least one" check with `parser.error`, dispatch in the order Frigate, Node-RED, Plate Recognizer. The task file and the `main.yml` import as the Interfaces block says.

- [ ] **Step 4: Run every off-device check** (as Task 2 Step 4). Expected: PASS.

- [ ] **Step 5: Commit**

"Move the ThingsBoard and Plate Recognizer secrets out of config.yml and the add-on's env file with tm-control migrate, before tmsetup renders them".

---

### Task 4: Node-RED reads both tokens from the environment and builds the ThingsBoard URL from `protocol`

**Files:**
- Modify: `container/node-red-tm/data/flows.json`: function `94136e5a6f092bb6` (`init-config` tab), templates `9c944328e288b2dc` and `d739b10ce5fa8f40`, http request `56cafb11de5348b2`, ui_button `0372cefb5e2ec968` (its wire), one new template node (`thingsboard` tab `f7932be9acc7391c`); switch `5e642eb684a874ef` and function `ce5360091646c733` (`plate-recognizer` tab).
- Test: `script/tests/test_node_red_flows.py`

**Interfaces:**
- Produces, in `init config defaults`'s `thingsboard` section: `enabled` as today; when enabled and `host` is missing or empty, the existing `node.error(..., msg)` and `enabled = false`; otherwise `url` = `host` as-is when it matches `/^https?:\/\//i`, else `` `${protocol}://${host}` `` with `protocol` defaulting to `https` when missing or empty, then `:port` when `port` is set; then the existing `protocol` normalisation for the switch (unchanged); then `const token = env.get("TM_THINGSBOARD_ACCESS_TOKEN") || ""` and, when enabled and `token` is empty, `node.warn("Node-RED config.yml enables ThingsBoard, but TM_THINGSBOARD_ACCESS_TOKEN is not set in node-red-tm.env. Set the token on the control app's Device page. Disabling ThingsBoard.")` and `enabled = false`. The `access_token` warning goes; the key is neither read nor defaulted. The function doesn't touch `addons`.
- The two URL templates: `{{{global.config.thingsboard.url}}}/api/v1/{{{env.TM_THINGSBOARD_ACCESS_TOKEN}}}/telemetry` and `.../attributes`. New template node `backup read msg.url` (`field: "url"`, `fieldType: "msg"`, `syntax: "mustache"`) with `{{{global.config.thingsboard.url}}}/api/v1/{{{env.TM_THINGSBOARD_ACCESS_TOKEN}}}/attributes?clientKeys=backup`, wired from `0372cefb5e2ec968` to `56cafb11de5348b2`, whose `url` becomes `""`.
- Plate Recognizer: switch `5e642eb684a874ef` becomes `propertyType: "env"`, `property: "TM_PLATE_RECOGNIZER_TOKEN"`, one rule `{"t": "nempty"}` (name unchanged); function `ce5360091646c733` reads `const token = env.get("TM_PLATE_RECOGNIZER_TOKEN") || ""` and still `global.get("config.addons.plate_recognizer.url")`.

- [ ] **Step 1: Write the failing tests**

```python
TB_ENV = {"TM_THINGSBOARD_ACCESS_TOKEN": "tb-placeholder-0001"}

@needs_node
@pytest.mark.parametrize("given, url", [
    ({"host": "tb.example.invalid"}, "https://tb.example.invalid"),                           # protocol from the template
    ({"host": "tb.example.invalid", "protocol": "http"}, "http://tb.example.invalid"),
    ({"host": "tb.example.invalid", "protocol": "https", "port": 8443}, "https://tb.example.invalid:8443"),
    ({"host": "http://tb.example.invalid", "protocol": "https"}, "http://tb.example.invalid"),  # a scheme in host wins (#95)
    ({"host": "HTTPS://tb.example.invalid"}, "HTTPS://tb.example.invalid"),
])
def test_thingsboard_url_honours_protocol(given, url): ...
    # new_device_config() with thingsboard = {"enabled": True, **given}; run with env=TB_ENV →
    # payload.thingsboard.url == url, enabled True, no error or warn logged

@needs_node
def test_thingsboard_is_off_without_a_token(): ...
    # enabled True, host set, env {} → enabled False; exactly one warn, naming TM_THINGSBOARD_ACCESS_TOKEN; no error
    # enabled False, env {} → no warn at all

@needs_node
def test_thingsboard_switch_still_sees_http_for_https(): ...  # protocol "https" → payload.thingsboard.protocol == "http" after the function

def test_thingsboard_url_nodes_take_the_token_from_the_environment(): ...
    # templates 9c944328e288b2dc, d739b10ce5fa8f40 and named(flows, "backup read msg.url") contain
    # "{{{env.TM_THINGSBOARD_ACCESS_TOKEN}}}" and "{{{global.config.thingsboard.url}}}"; the backup template has field "url";
    # 0372cefb5e2ec968 wires only to it, it wires only to 56cafb11de5348b2, whose url == ""

@needs_node
def test_plate_recognizer_token_comes_from_the_environment(): ...
    # run ce5360091646c733 with env {"TM_PLATE_RECOGNIZER_TOKEN": "pr-placeholder-0002"}, context config.addons.plate_recognizer.url
    # "http://plate-recognizer:8080", a msg with frigate_event.frame_time and frigate_event_api_thumbnail →
    # headers.Authorization == "Token pr-placeholder-0002", url == "http://plate-recognizer:8080/v1/plate-reader/"
    # switch 5e642eb684a874ef: propertyType "env", property "TM_PLATE_RECOGNIZER_TOKEN", rules == [{"t": "nempty"}], wires unchanged

def test_no_flow_reads_a_secret_from_config(): ...
    # no node's func, template, url, or property contains "access_token" or "addons.plate_recognizer.token"
```

Change `test_thingsboard_without_a_host_is_a_config_error` to pass `env=TB_ENV` and drop `"access_token"` from its dict; its assertions stay.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest script/tests/test_node_red_flows.py -k "thingsboard or plate_recognizer or secret_from_config" -v`
Expected: FAIL.

- [ ] **Step 3: Edit the flows**

With a throwaway script in the scratch directory: rewrite the `thingsboard` section of the function's `func`, the two template strings, add the template node (fresh id, `z` the thingsboard tab, placed between the button and the request), rewire, blank the request's `url`, change the switch and the Plate Recognizer function, re-serialise.

- [ ] **Step 4: Run every off-device check** (as Task 2 Step 4, plus `python3 -m json.tool container/node-red-tm/data/flows.json >/dev/null`). Expected: PASS.

- [ ] **Step 5: Commit**

"Read the ThingsBoard and Plate Recognizer tokens from the environment in Node-RED, and build the upload URL from protocol (#95)".

---

### Task 5: The `set-secret` root job: script, unit, polkit, and the job name

**Files:**
- Create: `tm-control/jobs/tm-job-set-secret` (executable), `script/ansible/roles/tmsetup/templates/tm-control/tm-job-set-secret.service.j2`
- Modify: `tm-control/backend/tm_control/core/jobs.py` (`JOB_NAMES`), `script/ansible/roles/tmsetup/vars/main.yml` (`tmsetup_tm_control_polkit.units`), `tasks/tm-control_service.yml` (the unit loop)
- Test: `tm-control/backend/tests/test_job_set_secret.py` (new), `tm-control/backend/tests/test_jobs.py`, `script/tests/test_tmsetup_templates.py`, `script/tests/test_tmsetup_tasks.py`

**Interfaces:**
- Consumes: the request `/run/tm-control/jobs/set-secret.json` as `{"name": "<entered secret>", "value": "<text or empty>"}`; `TM_CONTROL_MANIFEST` (for `codedir` and `codeowner`), `TM_CONTROL_SECRETS_DIR` (set by the unit; default `/etc/traffic-monitor/secrets`), `SYSTEMCTL` (tests only; ignored when euid is 0, like `CHPASSWD`).
- Produces: the script's table, the allow-list and the only place a secret's rules live on the device:

```python
SECRETS = {
    "thingsboard_access_token": {
        "pattern": r"[A-Za-z0-9._~-]{1,256}",             # goes into a URL path
        "env": [("node-red-tm/node-red-tm.env", "TM_THINGSBOARD_ACCESS_TOKEN")],  # relative to the manifest's codedir
        "restart": ["node-red-tm.service"],
    },
    "plate_recognizer_token": {
        "pattern": r"[\x21-\x7e]{1,256}",                 # a header value and an env line
        "env": [("plate-recognizer/plate-recognizer.env", "TOKEN"), ("node-red-tm/node-red-tm.env", "TM_PLATE_RECOGNIZER_TOKEN")],
        "restart": ["plate-recognizer.service", "node-red-tm.service"],
    },
    "plate_recognizer_license_key": {
        "pattern": r"[\x21-\x7e]{1,256}",
        "env": [("plate-recognizer/plate-recognizer.env", "LICENSE_KEY")],
        "restart": ["plate-recognizer.service"],
    },
}
```

  Functions, as the password job's: `read_manifest(path) -> (codedir, owner_uid)`, `open_jobs_dir`, `read_request`, `check(request) -> (name, value)` (exact keys, strings, name in `SECRETS`, value empty or `fullmatch` of the pattern), `open_secrets_dir(path) -> fd` (a directory owned by uid 0, not group- or world-writable, else `Refused`), `check_env_files(codedir, entries)` (every env file of the secret must be a regular file, else `Refused("<file> is missing; the add-on isn't installed")`, checked before anything is written), `write_secret(dir_fd, name, value)` (a temporary file created `O_EXCL` 0640 in the directory, chowned to uid 0 and the directory's gid when euid is 0, the value plus `\n` or nothing for empty, fsync, `os.replace` over the name), `set_env_line(path, key, value)` (the first `^KEY=` line is replaced, or the line appended after a trailing newline; every other byte kept; written to a temporary file beside it with the original's mode, uid, and gid, then replaced), `restart(units)` (`systemctl restart <unit>` each, 120 s timeout), `delete_request`, `main`. Stdout lines: `set secret <name>` or `removed secret <name>`, `updated <env file name>` per file, `restarted <unit>` per unit; `refused: <reason>`; `failed: restart of <unit> exited <n>; the secret is written` (exit 1, the request deleted). The value is never printed; refusal messages name the rule, not the value.
- `JOB_NAMES = {"system-password", "set-secret"}`. `tm-job-set-secret.service.j2`: the password unit's shape with `Environment=TM_CONTROL_SECRETS_DIR={{ tmsetup_secrets_dir }}` added and the description "Traffic Monitor job: set an entered secret". `tmsetup_tm_control_polkit.units` gains `tm-job-set-secret.service`; the install loop gains the unit.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_job_set_secret.py, with fixtures as test_job_system_password.py's: manifest (codeowner = me), jobs_dir,
# a codedir under tmp_path with node-red-tm/node-red-tm.env holding "A=1\nTM_THINGSBOARD_ACCESS_TOKEN=\nB=2\n" (0640) and
# plate-recognizer/plate-recognizer.env holding "TOKEN=\nLICENSE_KEY=\nWORKERS=2\n", secrets_dir (0750, euid-owned:
# open_secrets_dir accepts the test's own uid when not root — the job checks uid 0 only as root, documented in the script),
# and a fake systemctl that records each argv and exits with systemctl.exit if present.
# run_job(request, ...) runs the script through fixtures/run_job.py with TM_CONTROL_SECRETS_DIR, SYSTEMCTL, TM_CONTROL_MANIFEST.
VALUE = "tb-placeholder-0001"

def test_the_job_is_executable(): ...
def test_sets_the_secret_rewrites_the_env_line_and_restarts(...): ...
    # file == VALUE + "\n", mode 0o640; env == "A=1\nTM_THINGSBOARD_ACCESS_TOKEN=tb-placeholder-0001\nB=2\n", mode kept;
    # systemctl argv == [["restart", "node-red-tm.service"]]; stdout has "set secret thingsboard_access_token"; VALUE not in output;
    # request deleted; exit 0
def test_a_secret_with_two_env_files_updates_both_and_restarts_both(...): ...
    # plate_recognizer_token "pr-placeholder-0002" → both files' lines; systemctl argv == [["restart", "plate-recognizer.service"], ["restart", "node-red-tm.service"]]
def test_an_empty_value_removes_the_secret(...): ...  # file empty, env line "TM_THINGSBOARD_ACCESS_TOKEN=", "removed secret ..."
def test_a_missing_env_line_is_appended(...): ...     # env "A=1" (no newline) → "A=1\nTM_THINGSBOARD_ACCESS_TOKEN=tb-placeholder-0001\n"
@pytest.mark.parametrize("name, value", [("thingsboard_access_token", v) for v in ["a b", "a/b", "a?b", "a#b", "a=b", 'a"b', "é", "x" * 257, "a\nb", "\x00"]]
                                      + [("plate_recognizer_token", v) for v in ["a b", "é", "x" * 257, "a\nb", "\x00"]])
def test_refuses_values_the_env_line_or_url_cannot_carry(...): ...  # exit 1, files and env untouched, no restart, request deleted
def test_plate_recognizer_values_may_hold_url_characters(...): ...  # plate_recognizer_license_key "a/b?c=d#e" is accepted
@pytest.mark.parametrize("request_body", [{"name": "session_key", "value": VALUE}, {"name": "../x", "value": VALUE},
    {"name": "thingsboard_access_token"}, {"name": "thingsboard_access_token", "value": 1}, ["x"], "not json", ""])
def test_refuses_bad_requests_and_deletes_them(...): ...
def test_a_failed_restart_is_reported_after_the_secret_is_written(...): ...
    # systemctl.exit 1 → exit 1; file and env written; stdout "failed: restart of node-red-tm.service exited 1; the secret is written";
    # request deleted
def test_refuses_a_secret_whose_env_file_is_missing(...): ...  # unlink plate-recognizer.env → plate_recognizer_token: exit 1, "isn't installed", secret file untouched, no restart
def test_refuses_a_group_writable_secrets_dir(...): ...  # chmod 0770 → exit 1, nothing written
def test_refuses_a_symlink_and_leaves_its_target(...), test_refuses_a_hardlinked_request(...),
def test_refuses_a_jobs_directory_reached_through_a_symlink(...): ...  # as the password job's
def test_root_ignores_systemctl_from_the_environment(monkeypatch, tmp_path): ...  # as test_root_ignores_chpasswd_from_the_environment
def test_the_table_matches_the_api(): ...  # SECRETS keys == ENTERED_SECRETS, each pattern == the router's, each restart list == the router's (Task 6; xfail(strict) until then)
```

`test_jobs.py`: `test_unknown_job_name_is_refused` asserts `JOB_NAMES == {"system-password", "set-secret"}`.

`test_tmsetup_templates.py`: parametrize `tm_job_unit` over both unit files (`test_job_unit_is_a_root_oneshot_without_install`, `test_job_unit_never_hits_a_start_limit`), and `test_set_secret_unit_names_the_secrets_dir` (`Environment=TM_CONTROL_SECRETS_DIR=/etc/traffic-monitor/secrets` in the unit); `test_polkit_rules_allow_only_named_units_for_the_code_owner` also asserts `'"tm-job-set-secret.service"'`.

`test_tmsetup_tasks.py`: `test_both_job_units_are_installed` (the "Install the unit files" loop == the three units) and, in `test_polkit_allowlist_covers_the_traffic_monitor_units_only` (templates file), the expected unit set gains the new unit.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_job_set_secret.py tm-control/backend/tests/test_jobs.py script/tests -k "job or polkit or secret" -v`
Expected: FAIL (no script, `JOB_NAMES` short, unit missing).

- [ ] **Step 3: Write the script, the unit, and the lists**

The script copies the password job's structure and docstring style (what it treats as hostile, and why). `open_secrets_dir` opens with `O_DIRECTORY | O_NOFOLLOW`; as root it requires `st_uid == 0`, otherwise the test's own uid; either way `mode & 0o022 == 0`. Check the env files, then write the secret, then the env lines, then restart, so a failure leaves the device no worse than before that step; say which step failed.

- [ ] **Step 4: Run every off-device check** (as Task 2 Step 4). Expected: PASS (Task 5's table test `xfail` until Task 6).

- [ ] **Step 5: Commit**

"Add the set-secret root job: writes an entered secret, rewrites its env lines, restarts its units".

---

### Task 6: The secrets API, the audit rows, fake mode, and the `config.thingsboard` check

**Files:**
- Create: `tm-control/backend/tm_control/modules/secrets/__init__.py`, `modules/secrets/router.py`
- Modify: `tm-control/backend/tm_control/modules/__init__.py` (`MODULES`, after `jobs`), `modules/apps/contracts.py`, `tests/fixtures/status_fake.json`, `tm-control/ui/src/api/openapi.json` and `schema.d.ts` (regenerated)
- Test: `tm-control/backend/tests/test_api_secrets.py` (new), `tests/test_contract_checks.py`, `tests/test_job_set_secret.py` (the table test)

**Interfaces:**
- Produces: `modules/secrets/router.py` with `ENTERED: dict[str, EnteredSecret]` where `EnteredSecret(title: str, pattern: re.Pattern, shows_ending: bool, message: str, restarts: tuple[str, ...], option: str | None)`:
  - `thingsboard_access_token`: title `ThingsBoard access token`, the pattern from Task 5, `shows_ending=True`, message `A ThingsBoard access token is 1 to 256 letters, digits, dots, dashes, underscores, or tildes.`, restarts `("node-red-tm.service",)`, option `None`;
  - `plate_recognizer_token`: title `Plate Recognizer API token`, `shows_ending=True`, message `A Plate Recognizer value is 1 to 256 printable characters with no spaces.`, restarts `("plate-recognizer.service", "node-red-tm.service")`, option `"plate_recognizer"`;
  - `plate_recognizer_license_key`: title `Plate Recognizer license key`, `shows_ending=False`, the same message, restarts `("plate-recognizer.service",)`, option `"plate_recognizer"`.

  Models `SecretState(name: str, title: str, set: bool, ends_with: str | None, restarts: list[str])` and `SecretsState(secrets: list[SecretState])`. A secret is *available* when its `option` is `None` or `manifest.options.get(option)` is true.
  - `GET /secrets` (admin) → `SecretsState`, the available ones in `ENTERED` order; `ends_with` is `None` unless `shows_ending` and set.
  - `POST /secrets/{name}` body `SecretValue(value: str = Field(max_length=1024))` → 202 `{"id": job.id}`; 404 `not_found` for a name not in `ENTERED` or not available; 422 `validation` "Enter a value, or leave this as it is." for an empty or whitespace-only value; 422 with the secret's `message` when the pattern doesn't match. The job request is `{"name": name, "value": value}`. Audit `secrets.set` with `detail=name`.
  - `DELETE /secrets/{name}` → 202 `{"id"}`; request `{"name": name, "value": ""}`; audit `secrets.removed`, `detail=name`.
  - In fake mode, after the job starts, `app_state.secrets.entered[name] = value` so the page round-trips.
- `contracts.thingsboard(context)` → `Check(id="config.thingsboard", title="ThingsBoard upload", ...)`, appended to `GROUP`. Reads `probes.config_yml` and `context.secrets.is_set(THINGSBOARD_ACCESS_TOKEN)`. `unknown` when config.yml can't be read; `error` when `enabled` is set but not a boolean, when enabled with an empty or missing `host`, or when `protocol` is present and not `http`/`https`; `warn` when `thingsboard.access_token` or `addons.plate_recognizer.token` is present with any value ("config.yml still holds <key>, which nothing reads. Remove it; the value is set on the Device page."), when enabled and the token isn't set ("The upload is on in config.yml, but no access token is set, so Node-RED keeps it off." with `Fix(kind="link", text="Set the token", href="/device")`), or when `host` starts with `http://`/`https://` ("thingsboard.host starts with a scheme, so the protocol key is ignored for it. Put only the hostname in host."); `ok` "The upload is off." or "The upload is on, with a token set." Several problems of one status are joined with a space, as the other checks do, and the `fix` link is kept whenever the missing-token sentence is among them. Details never include `host`'s value.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api_secrets.py (claimed_client is fake mode; FakeSecrets.entered starts empty; the fixture manifest has no add-on)
def test_secrets_module_is_registered(): ...
def test_get_secrets_is_admin_only_and_lists_the_available_ones(claimed_client, login): ...
    # viewer → 403; admin → {"secrets": [{"name": "thingsboard_access_token", "title": "ThingsBoard access token", "set": False,
    #   "ends_with": None, "restarts": ["node-red-tm.service"]}]}
def test_plate_recognizer_secrets_appear_only_with_the_addon(settings, login): ...
    # a client whose manifest copy has options.plate_recognizer true → three entries, in order, the license key with shows no ending
    # once set; without the add-on, POST and DELETE on either → 404
def test_set_secret_starts_the_job_and_the_state_follows(claimed_client, login): ...
    # POST value "tb-placeholder-0001" → 202 with id; jobs.last_request == {"name": ..., "value": "tb-placeholder-0001"};
    # GET /jobs/{id} succeeded; GET /secrets → set True, ends_with "0001"
def test_set_secret_refuses_an_empty_value(claimed_client, login): ...
    # "" and "   " → 422 with "Enter a value, or leave this as it is."; last_request stays None
@pytest.mark.parametrize("value", ["a b", "a/b", "a?b", "é", "x" * 257])
def test_set_secret_enforces_the_value_pattern(claimed_client, login, value): ...  # 422, the message names the rule, no job
def test_unknown_secret_is_404(claimed_client, login): ...  # POST and DELETE /secrets/session_key → 404; GET lists nothing of it
def test_remove_secret_sends_an_empty_value(claimed_client, login): ...
    # set, then DELETE → 202; last_request value ""; GET set False; DELETE again → 202 (idempotent)
def test_secret_actions_are_audited_without_the_value(claimed_client, login, settings): ...
    # rows hold (admin.id, "secrets.set", "thingsboard_access_token") and (..., "secrets.removed", ...); the value is not in the dump
def test_validation_errors_do_not_echo_the_value(claimed_client, login): ...  # 422 body text lacks the submitted value
def test_viewer_cannot_set_or_remove(claimed_client, login): ...  # 403 on POST and DELETE, no job
```

`test_contract_checks.py`: `test_cameras_match` lists gain `"config.thingsboard"` / `"ThingsBoard upload"`; then

```python
def test_thingsboard_off_is_ok(apps): ...                                    # the fixture: enabled false → ok, "off" in detail
def test_thingsboard_on_without_a_token_is_a_warning_with_a_link(apps): ...  # enabled true → warn, fix.href == "/device"
def test_thingsboard_on_with_a_token_is_ok(apps): ...                        # FakeSecrets.entered set → ok (apps.context() must expose the secrets: add a `secrets` attribute to FakeApps)
@pytest.mark.parametrize("key", ["thingsboard.access_token", "addons.plate_recognizer.token"])
def test_a_secret_left_in_config_yml_is_a_warning(apps, key): ...            # value "tb-placeholder-9" → warn naming the key; value not in detail
@pytest.mark.parametrize("edit, status", [(no host, "error"), (protocol "ftp", "error"), (enabled "yes", "error"), (host "https://x", "warn")])
def test_thingsboard_block_values(apps, edit, status): ...
def test_two_warnings_are_joined_in_one_detail(apps): ...  # enabled, no token, and a token left in the file → one warn whose detail holds both sentences
# test_every_check_is_unknown_when_config_yml_has_a_yaml_error already covers the new check: it asserts every status is unknown
```

`status_fake.json`: add `{"id": "config.thingsboard", "title": "ThingsBoard upload", "status": "ok", "detail": "The upload is off."}` to the config group. Remove the `xfail` from Task 5's table test and import `ENTERED` there.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tm-control/backend/tests/test_api_secrets.py tm-control/backend/tests/test_contract_checks.py tm-control/backend/tests/test_job_set_secret.py -v`
Expected: FAIL (no module, no check).

- [ ] **Step 3: Write the module and the check, then regenerate the API document**

The router follows `system/router.py`'s password route. Give `FakeApps.context()` a `secrets` field (default `FakeSecrets()`) so the contract tests can set the entered value. Then:

Run: `PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json && (cd tm-control/ui && npm ci && npm run api:generate)`

- [ ] **Step 4: Run every off-device check** (as Task 2 Step 4). Expected: PASS, including `test_openapi_document.py` and `test_api_status.py`.

- [ ] **Step 5: Commit**

"Add the secrets API, the audit rows, and the ThingsBoard configuration check".

---

### Task 7: The forms on the Device page

**Files:**
- Create: `tm-control/ui/src/components/jobs.ts`, `tm-control/ui/src/components/EnteredSecret.vue`
- Modify: `tm-control/ui/src/modules/device/DevicePage.vue`, `tm-control/ui/src/modules/device/index.ts` (the comment), `tm-control/ui/src/modules/setup/SetupPage.vue` (uses `jobs.ts`), `tm-control/ui/README.md` ("How the code is laid out": the two new files; a design note on the Device page section)
- Test: `tm-control/ui/tests/entered-secret.spec.ts` (new), `tests/device-page.spec.ts`, `tests/setup-flow.spec.ts` (unchanged, must still pass)

**Interfaces:**
- `jobs.ts`: `export const JOB_POLL_MS`, `JOB_DEADLINE_MS` (the values SetupPage has today) and `export function followJob(id: string): { done: Promise<Job | null>; cancel(): void }`: polls `GET /jobs/{id}` until `succeeded`/`failed` (resolves with the job), the deadline (resolves `null`), or `cancel()` (resolves `null`); errors reject. SetupPage switches to it, keeping its wording and its `onBeforeUnmount` cancel.
- `EnteredSecret.vue` props `secret: SecretState` (from the schema), emits `changed` after a job finishes so the page reloads `GET /secrets`. It shows: an `h3` with the title; a state line (`Set, ending in 0001.` / `Set.` when `ends_with` is null / `Not set.`); a `v-text-field` labelled with the title (`type` toggles between `password` and `text` with an eye icon button labelled `Show`/`Hide`, `autocomplete="off"`, empty on every load, rule "Enter a value, or leave this as it is."); `Save` (primary; loading while the job runs); `Remove` (outlined, only when set) opening a `ConfirmDialog` (title `Remove the ${title}?`, text `${restartNote} ${consequence}`, confirm `Remove`), where `restartNote` is built from `restarts` with the unit→name map `{ 'node-red-tm.service': 'Node-RED', 'plate-recognizer.service': 'Plate Recognizer' }` as `Node-RED restarts, which takes about thirty seconds.` / `Plate Recognizer and Node-RED restart, which takes about a minute.`, and `consequence` is `The upload to ThingsBoard stops until a token is set again.` for the ThingsBoard token and `Plates aren't read until it's set again.` for the add-on's two; after a job: success alert `Saved. ${restarted}.` / `Removed. ${restarted}.`, failure alert `The value wasn't saved.` plus the job's log lines, timeout warning `The device hasn't reported whether the value was saved. Reload this page in a minute to check.`; API errors through `messageOf`. The field is cleared after Save.
- `DevicePage.vue`: a new admin section after Software and before Diagnostics, heading `Tokens and keys`, one paragraph: `Credentials this device uses, kept with its other secrets. A value is never shown back; saving or removing one restarts the app that uses it, and counting pauses meanwhile.`, then one `<EnteredSecret>` per entry of `GET /secrets`, loaded on mount and reloaded on `changed`; a load error shows a `v-alert` with Try again, as the page's own load does.

- [ ] **Step 1: Write the failing tests**

```ts
// tests/entered-secret.spec.ts (mountAlone with a SecretState prop; fakeApi answers)
it('says when the value is not set, and offers no Remove')
it('shows the ending of a set token and the Remove button')
it('shows "Set." without an ending for a license key')
it('refuses an empty submit without calling the API')          // the rule text appears; sent is empty
it('saves: posts the value, polls the job, clears the field, emits changed')  // fake timers as setup-flow.spec; body {value}
it('removes only after the confirm, with DELETE')              // dialogText has "Remove the ThingsBoard access token?"
it('names every app that restarts')                            // restarts two units → "Plate Recognizer and Node-RED restart"
it('shows the job log when the job fails')                     // log line "refused: ..." in text; "Saved." absent
it('warns when the job never reports')                         // advance past JOB_DEADLINE_MS
it('toggles between hidden and shown text')                    // input type password → text after "Show"
// tests/device-page.spec.ts
it('shows a viewer no Tokens and keys section')                // headings lacks it; existing viewer test's button list stays []
it('shows an admin one form per secret the API lists, before Diagnostics') // GET /secrets with three → three h3s; headings order: Software, Tokens and keys, Diagnostics, Power
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd tm-control/ui && npm test`
Expected: FAIL (no component).

- [ ] **Step 3: Write the helper, the component, and the section**

Keep to the conventional Vuetify the UI README describes (outlined fields, `text-h6` section headings, `v-alert` for results). `index.ts`'s comment gains "and the entered secrets (GET/POST/DELETE /secrets)".

- [ ] **Step 4: Run the UI checks and look at it**

Run: `cd tm-control/ui && npm test && npm run build`, then fake mode as the UI README says (`tm-control fake-reset`, `serve`, `npm run dev`): claim, open `/device`, save a placeholder token, see "ending in", remove it; run once more with `TM_CONTROL_MANIFEST` pointing at a copy of the fixture manifest with `plate_recognizer: true` and see three forms. Check at 375 px. Record the result in the PR's Testing section.

- [ ] **Step 5: Commit**

"Add the Tokens and keys section to the Device page".

---

### Task 8: Docs, CLAUDE.md, and the dev-Pi README

**Files:**
- Modify: `docs/configuration/node-red-config.md` (the `thingsboard` table, the `addons.plate_recognizer` section), `docs/add-ons/plate-recognizer.md` (the Install steps), `docs/configuration/environment.md` (the env table), `docs/data-and-payloads/integrations.md` (the ThingsBoard section), `docs/use/device-health.md` (the Device page), `docs/use/system-admin.md` (the credentials files row), `docs/development/tm-control.md` (secrets paragraph, "Root jobs and polkit", the modules listing), `docs/reference/tmsetup.md` ("What `-f` replaces"), `CLAUDE.md`, `script/devpi/README.md`

- [ ] **Step 1: Write the pages**

- `node-red-config.md`: drop the `access_token` row; `host`: "The server's hostname. If it starts with `http://` or `https://`, that is used and `protocol` is ignored." Under the table: "The device's access token isn't in this file. Set it on the control app's [Device page](../use/device-health.md#tokens-and-keys); it's kept with the device's other secrets." In `addons.plate_recognizer`: drop the `token` row and say the token and license key are set on the Device page; only `url` stays here.
- `plate-recognizer.md`: step 2 becomes "Enter your API token and license key on the control app's Device page, under Tokens and keys. Saving each one restarts the add-on." Step 3 keeps only `plate_recognizer: true` per camera and `addons.plate_recognizer.url`; step 4 (restart by hand) goes, since the page restarts the add-on and Node-RED picks up `config.yml` on its own. A note for upgrades: a token and key already in the add-on's env file, and a token in `config.yml`, are moved to the device's secrets by the installer.
- `environment.md`: rows for `TM_THINGSBOARD_ACCESS_TOKEN` and `TM_PLATE_RECOGNIZER_TOKEN` ("filled by the installer from the device's secrets on every run; change it on the Device page, not here"); the `NODE_RED_CREDENTIAL_SECRET` row unchanged.
- `integrations.md`: "Turn it on in the `thingsboard` section of config.yml with the server's hostname, and enter the device's access token on the control app's Device page. Saving the token restarts Node-RED, which takes about thirty seconds." Keep the rest.
- `device-health.md`: a `### Tokens and keys` subsection after "Download diagnostics": which values appear (the ThingsBoard token always; the Plate Recognizer token and license key when the add-on is installed), that a value is never shown back (only its last four characters, and not for a license key), Save and Remove, the restart, and that values already in `config.yml` or the add-on's env file moved to the device's secrets at upgrade so uploads and plate reads keep working.
- `system-admin.md` and `tmsetup.md`: the credentials-file rows say `plate-recognizer.env`'s values come from the device's secrets; the `-f` paragraph adds "including the ThingsBoard token and the Plate Recognizer token and license key you entered", and the tmsetup reference says the installer takes no secret value.
- `tm-control.md`: the secrets bullet says there are two kinds (five generated once; three entered, created empty, written by the `set-secret` job), `GENERATED_SECRETS`/`ENTERED_SECRETS` match the role's two lists; "Root jobs and polkit" describes the second job and its table; the modules list gains `secrets`; the sandbox section gains "tm-control never writes the secrets directory; the job does".
- `CLAUDE.md`: the secrets bullet (five generated plus three entered, two lists, two constants, the job, `entered_secrets.yml` runs first under the pod tags and `plate-recognizer`), the overwrite-semantics bullet (entered secrets' env lines are re-applied with `lineinfile`), the `config.yml` sentence in "AI use" ("the one secret in `config.yml`" → "`config.yml` holds no secret; a pii_free unit keeps its entered secret files empty"), and the `init-config` sentence mentions the env tokens.
- `script/devpi/README.md`: the `pii_free` paragraph (empty entered secret files instead of the blank key) and the module table rows for Task 9's tests.

- [ ] **Step 2: Build the docs**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: no warnings.

- [ ] **Step 3: Commit**

"Document the Tokens and keys section and the entered secrets".

---

### Task 9: Device tests and the Pi plan

**Files:**
- Modify: `script/devpi/tests/test_web.py`, `script/devpi/tests/test_services.py`, `script/devpi/tests/test_disruptive.py`
- The Pi plan is recorded with `tmdev.py check`, not committed.

- [ ] **Step 1: Add device tests**

```python
# test_services.py
def test_set_secret_job_unit_is_static(host): ...  # UnitFileState of tm-job-set-secret.service == "static"; the script is root-owned 0755 in the libexec dir

# test_web.py (pii_free)
def test_config_yml_holds_no_secret_key(host, expect, codedir, node_red_config): ...  # neither thingsboard.access_token nor addons.plate_recognizer.token present
def test_env_secret_lines_match_the_secret_files(host, expect, codedir): ...
    # a script on the Pi prints "<key> equal|different|missing" for each (env file, key, secret) of the job's table whose env file
    # exists, comparing with sudo; every line must say equal
def test_secrets_lists_only_the_installed_addons_values(address, expect, admin_session): ...
    # GET /secrets names == ["thingsboard_access_token"] when the inventory has no Plate Recognizer (pii_free units), else all three
# test_diagnostics_has_no_secret_value and test_no_secret_in_the_install_log: check both lists, and skip an entered secret whose file is empty

# test_disruptive.py (pii_free, tm_control_login)
def test_set_and_remove_the_thingsboard_token_from_the_control_app(host, address, expect, codedir, tm_login): ...
    # POST /secrets/thingsboard_access_token {"value": "tmdev-placeholder-0001"} → 202; poll /jobs/{id} to succeeded within
    # UNIT_RESTART_SECONDS; node-red-tm.service has a new InvocationID; on the Pi the file holds the value and the env line
    # equals it; GET /secrets → set True, ends_with "0001"; DELETE → succeeded; file empty; env line empty; GET set False
```

- [ ] **Step 2: The Pi plan (`tmdev.py check start` with these items, run before the PR opens)**

1. On a pii_free bench unit at current `dev`-plus-plan-1, put a placeholder token (`tb-placeholder-upgrade`) into `config.yml`'s `access_token` by hand; upgrade from this branch (full run, no `-f`): the journal shows `moved thingsboard.access_token to the secrets file (backup: ...)`, the key is gone, the secret file holds the placeholder (checked with `sudo test`), `node-red-tm.env` has both lines, Node-RED's status reports no config error, the Status page's `config.thingsboard` says the upload is off (enabled false) and nothing else warns.
2. Enable the upload in `config.yml` with `host: tb.example.invalid`: Node-RED's journal shows the upload URL as `https://tb.example.invalid/api/v1/...` failing with a DNS error (not `tb.example.invalid/api/...`); set `protocol: http` → `http://...`; set `host: http://tb.example.invalid` with `protocol: https` → `http://...`. Put `access_token: x` back for a moment: the Status page warns that nothing reads it. Disable it again and remove the key.
3. The Device page: Save `tb-placeholder-ui-0002` → the job succeeds within a minute, Node-RED restarts, the form says "ending in 0002", the file and env line hold it; Remove → empty; submit empty → refused in place; a viewer sees no section; download diagnostics while set → no placeholder in the text; `GET /secrets` lists only the ThingsBoard token (no add-on on this unit).
4. Upgrade with `-f` on the same unit with the token set: the token survives (file unchanged, fresh env has the lines, fresh `config.yml` has no key).
5. Fresh install on a second card: all three secret files empty, `config.yml` has no secret key, the install log holds no `tmsetup_thingsboard_api_key` reference or value.
6. A unit with the add-on (`-C plate_recognizer`, a bench unit or the second card): put placeholder values into `plate-recognizer.env` and a token into `config.yml`'s `addons.plate_recognizer.token` by hand as the old docs said, run the installer: the journal shows both moved, the env file's lines equal the secret files, `config.yml` keeps only `url`, `GET /secrets` lists three, the Device page shows three forms, saving the license key restarts only the add-on and saving the token restarts both; `-t plate-recognizer` alone keeps the values.
7. `tmdev.py test <host> --disruptive -k "secret or thingsboard or diagnostics or install_log"`: passes.

- [ ] **Step 3: Commit**

"Add device tests for the entered secrets and the set-secret job".

---

### Task 10: Pull request

- Target `feature/tmdb-survey-id/250` (retarget per the stacked-PR routine as 277 and 269 merge).
- Body: the release-note paragraph ("The ThingsBoard access token and the Plate Recognizer token and license key moved out of config.yml and the add-on's env file into the device's secrets. The installer moves existing values; to change one, use the Device page or edit the secrets file as root. The installer no longer takes `tmsetup_thingsboard_api_key`."), issue 95's fix in one sentence, the Pi plan's results, the UI screenshots at 375 px, the "Docs" list from Task 8, and the "AI assistance" section. Say which of the "Decisions" above the reviewer should look at (2, 4, 8, 9), that the forms move to the Sharing page and an add-on page in later PRs, and that the MQTT login, Frigate+ key, and Wi-Fi password have no form yet.
- No value of any secret, placeholders only.
