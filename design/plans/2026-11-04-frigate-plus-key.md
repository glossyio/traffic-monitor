# The Frigate+ API key as an entered secret, with the model section kept across `-f` and a Frigate+ status check

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin set the Frigate+ API key on the Device page and keep it across `tmsetup.sh -f`, keep the `model:` section an operator chose in Frigate's `config.yml` across `-f` too, and tell the operator on the Status page when the key and the model aren't paired or when Frigate can't use the model it was given.

**Architecture:**
- The key is the fourth entered secret, `frigate_plus_api_key`: an empty root-owned file tmsetup creates, the `PLUS_API_KEY=` line in `frigate.env` rendered from it on every run (a template line for new files, the existing `lineinfile` loop for existing ones), one row in the `set-secret` job's table and the API's, and one more form in the Device page's "Tokens and keys" section, on every device. Saving or removing restarts `frigate.service` only. `tm-control migrate --frigate-env` moves a key typed into an existing `frigate.env` into the file once, at upgrade, from the same root task that moves the other entered secrets.
- `-f` keeps the device's model choice however it was made (Frigate's own picker, its configuration editor, or a hand edit): before the Frigate config template renders under `-f`, tmsetup reads the current `model:` section, and the template writes it back in place of the detector default when its `path` isn't the installer's own Coral model. Nothing else about `-f` changes.
- Two Status checks. The Apps group's Frigate check reports an error when Frigate's running config says `safe_mode: true`, which is how Frigate 0.18 answers a config error: it starts with no cameras and counts nothing while looking healthy. A new Configuration check, `config.frigate_plus`, reads `model.path` from Frigate's `config.yml` on disk, whether the key is set, and whether the model's two files are in `model_cache`, and says: key without a `plus://` model (warning), `plus://` model with no key and no cached files (error, with a link to the form), Frigate failed or fell into safe mode over the model (error, quoting the log's message), or which model runs (ok).
- Docs cover both halves of Frigate+: entering the key, submitting snapshots, using a model through Frigate's picker or the editor, which detector each model type needs, the offline pair of files, a local model's extra keys, and what `-f` now keeps.

**Tech Stack:** Ansible (the tmsetup role: `stat`, `slurp`, `set_fact` with `from_yaml`, `block`/`rescue`, `lineinfile`), Jinja2 (`to_nice_yaml`), Python 3.11 (FastAPI, pydantic, ruamel.yaml, the stdlib-only job script, pytest), Vue 3 + Vuetify 3 + TypeScript (Vitest), Material for MkDocs. Frigate 0.18.1's behaviour is pinned from its source: `frigate/plus.py` (the key's format), `frigate/detectors/detector_config.py` (`plus://` loading and caching), and `frigate/__main__.py` (safe mode).

**Spec:** [issue 279](https://github.com/glossyio/traffic-monitor/issues/279), the entered-secrets design (not yet published), section 7's Frigate+ row, and the maintainer's decisions of 2026-11-04 listed below. Read the issue with this plan. Where this plan goes beyond the issue, the "Decisions" list says why; say so in the PR rather than picking one silently.

**Status:** written 2026-11-04 against `feature/entered-secrets/95` at `d7a4ab5` (PR 278, which contains PR 277, PR 269, PR 261, and `dev`). Branch: `feature/frigate-plus-key/279`, stacked on PR 278's branch; this file is added in the PR that implements it. The stacked-PR routine applies: retarget when 278 merges.

**Decisions made while writing this plan** (the maintainer decided 1 to 4 on 2026-11-04; 5 to 10 are calls made here, open to change):
1. **The key gets a form now, on the Device page**, with the other entered secrets, not a Frigate page later. Frigate is always installed, so the row shows on every device.
2. **Docs cover the model too.** The key alone only submits snapshots; a Frigate+ model needs `model.path: plus://<id>` in Frigate's `config.yml`. Frigate's own picker (Settings, System, Detectors and model) does that for an online unit; an offline unit takes the model as two files in `model_cache` and the same `path`, which Frigate then loads without contacting Frigate+ (`check_and_load_plus_model` downloads only when a file is missing). A local model (`/config/model_cache/<file>` with the keys from Frigate's reference) is documented as well. An upload-and-pick page for offline units is a later feature with its own design, so the docs say "copy the files over SSH" without naming it.
3. **A key without a `plus://` model is a warning**, not just information, because the two belong together; the detail says what the key does on its own and how to pair it. A key set with the installer's default model is a valid state: the default stays until the operator picks a model.
4. **`-f` keeps the `model:` section** (the "carry-over"). Without it, picking a model in Frigate's UI is undone by the next `-f`, and the key would then sit beside the installer's model again. The rule is in decision 6.
5. **The key's value rule is Frigate's own.** `PlusApi.__init__` accepts only `[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}:[a-z0-9]{40}` and logs "Plus API Key is not formatted correctly" for anything else, so the API and the job refuse anything else too, and a mis-paste is caught on the page. `GET /secrets` shows the last four characters (77 characters long, so the ending gives nothing away).
6. **The carry-over rule:** the current `model:` section is kept when it is a mapping whose `path` is a non-empty string other than the installer's Coral default, `/config/model_cache/<tmsetup_frigate_coral_model_file>`. The installer's own section is therefore never carried, so `-t detectors -t frigate -f` after a hardware change still re-renders the detector default; a `plus://` or local model is carried whatever the hardware, and the Frigate+ check reports a mismatch. The section is read only when `tmsetup_force_configs` is true and the file exists; a `config.yml` that doesn't parse keeps the template's section, with a message, rather than stopping the run that replaces it.
7. **The carry-over lives in the role, not in `tm-control migrate`.** The template task runs as root with `backup: true`; reading the section first with `slurp` and `from_yaml` and rendering it with `to_nice_yaml` is a few tasks, where a migrate option would need the backup file's path (root-owned, which the code-owner migrate step can't read) threaded through two task files. Comments inside the section don't survive; the docs say so.
8. **Safe mode is reported by the Apps group's Frigate check**, whatever caused it, because Frigate in safe mode answers its API, has no cameras, and the camera and zone checks then pass with nothing to compare. The Frigate+ check adds the model-specific reason when the log names the model. Three checks (Apps, Configuration, and Hardware's detector) can report the same root cause; each statement is true, and the Frigate+ one names the fix.
9. **Log lines quoted in a check's detail** are limited to Frigate's `Message :` lines and the last line of a traceback, each at most `MESSAGE_MAX` characters, with anything shaped like a Frigate+ key replaced by `<key>` first. Nothing else from the journal reaches the page.
10. **The form says Frigate takes about a minute** and that traffic isn't counted meanwhile. The job's `systemctl restart` returns when the container is up, so the page's "restarted" comes sooner than detection does; the note covers the gap. The bench run (Task 9) measures the restart with the unit's detector and changes the wording if it's over ninety seconds.

**Where PR 278 left things that this plan touches:**
- `core/secrets.py`: `ENTERED_SECRETS = (THINGSBOARD_ACCESS_TOKEN, PLATE_RECOGNIZER_TOKEN, PLATE_RECOGNIZER_LICENSE_KEY)`, `VALUE_PATTERNS`, `VALUE_RULES`, `is_valid_value(name, value)`, `Secrets.is_set`, `Secrets.ends_with`, `FakeSecrets.entered`. `tests/test_secrets.py::test_generated_and_entered_names_match_the_role` asserts the tuples equal the role's lists, in order, and `test_every_entered_secret_has_a_value_pattern_and_its_rule_in_words` covers every name.
- `modules/secrets/router.py`: `ENTERED: dict[str, EnteredSecret]` in Device page order (`title`, `pattern`, `shows_ending`, `message`, `restarts`, `option`); `GET /secrets` lists the available ones; `POST`/`DELETE /secrets/{name}` start the `set-secret` job. `tm-control/jobs/tm-job-set-secret` has the matching `SECRETS` table (`pattern`, `env` as `[(file relative to codedir, KEY)]`, `restart`); `tests/test_job_set_secret.py::test_the_table_matches_the_api` and `test_the_restart_lists_match_the_api` keep the two the same; `tests/fixtures/run_job.py` runs the script.
- `core/migrate.py`: `run_plate_recognizer_env(env_path, secrets_dir, dry_run)` wraps `_run_plate_recognizer_env` with `_unexpected`; `ENV_SECRETS`, `ENV_PLACEHOLDERS`, `_env_values(text)`, `_read_secret`, `_write_secret`, `_same_backup`, `_warn_secret`, `PREFIX`. Output: `<path>: up to date`, `<path>: moved TOKEN, LICENSE_KEY to the secrets files`, `would move ...`; warnings on stderr start with `WARNING`. `cli.py`: `run_migrate(args)` runs each step given and returns the highest code; `main` errors with "give at least one of --frigate-config, --node-red-config, --plate-recognizer-env".
- Role: `vars/main.yml` has `tmsetup_entered_secret_names` (three names). `tasks/secrets.yml` creates each empty. `tasks/entered_secrets.yml` (imported in `main.yml` right after `tm-control_service.yml`, under its tags plus `plate-recognizer`) stats `node-red-tm/config/config.yml` and `plate-recognizer/plate-recognizer.env`, runs `tm-control migrate --secrets-dir ... [--node-red-config ...] [--plate-recognizer-env ...]` as root when either exists, shows `WARNING` lines, re-reads the entered secrets into `tmsetup_secrets`. `tasks/frigate_setup.yml` renders `frigate/config/config.yml` and `frigate/frigate.env` in one `template` loop with `force: '{{ tmsetup_force_configs }}'`, `backup: true`, `diff: false`, then downloads the Coral yolov9 model to `{{ tmsetup_codedir }}/frigate/config/model_cache/yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite` (a literal in the task and in `config.yml.j2`'s `model: path:`). `tasks/frigate_credentials.yml` runs after it: a stat of `frigate.env` and `config/config.yml`, a `no_log` `lineinfile` loop that writes `FRIGATE_GO2RTC_RTSP_USER`, `FRIGATE_GO2RTC_RTSP_PASSWORD`, and `FRIGATE_PROXY_AUTH_SECRET` into an existing `frigate.env` (notify `Restart frigate.service`), then `tm-control migrate --frigate-config` as the code owner. `container/frigate/frigate.env.j2` has a bare `PLUS_API_KEY=` line.
- `script/tests/tmsetup_render.py` renders templates with Ansible's filters (`to_nice_yaml`, `from_yaml`, `b64decode` included) and `StrictUndefined`; `evaluate()` evaluates a task argument; `load_role_yaml()` loads a role file. `test_tmsetup_tasks.py` has `frigate_tasks()`, `frigate_credentials_tasks()`, `entered_secrets_tasks()`, `stat_results(...)`, and `test_entered_secrets_move_before_any_config_template_renders`, which pins the stat loop, the argv for each combination of files, and the `when`. `test_tmsetup_templates.py` renders `frigate.env.j2` with a `tmsetup_secrets` dict (`SECRETS`, and a two-key dict in `test_frigate_env_carries_the_proxy_secret`) and `config.yml.j2` with `tmsetup_detectors={}`.
- Status: `core/checks.py` (`Check`, `Fix`, `CheckGroup`, `Context.probe`). `modules/apps/probes.py` memoizes Frigate's version, config (`/api/config`, which has `safe_mode`, `detectors`, `model`), and stats, and `config_yml(context)` reads Node-RED's `config.yml` from disk through `adapters/nodered.config(codedir) -> ConfigRead(data, problem, line, column)`. `modules/apps/checks.py::frigate` (`apps.frigate.reachable`), `ERRORS_SHOWN = 3`, `MESSAGE_MAX = 200`. `modules/apps/contracts.py` holds the Configuration group (`config.cameras`, `config.zones`, `config.radars`, `config.deployment`, `config.thingsboard`; `tests/test_contract_checks.py::test_cameras_match` pins the ids and titles in order), `thingsboard()` is the pattern for a check that reads `context.secrets.is_set` and links to `/device#tokens-and-keys`. `modules/services/units.py`: `unit_states(context)` (probe `SHOW_UNITS`, properties include `ActiveState`, `InvocationID`, `ActiveEnterTimestamp`), `active_since(values)`, `RUNNING`. `adapters/systemd.py`: `journal_lines(unit, since, limit=200, invocation_id=None)` (the first `limit` messages since; `since` such as `@<unix seconds>` or `-1h`) and `journal_tail(unit, lines)` (the last lines as journalctl prints them, or None). `tests/conftest.py::FakeApps` gives `apps.codedir`, `apps.answers`, `apps.json(url, value)`, `apps.edit_json`, `apps.secrets.entered`, `apps.context()`; `tests/test_hardware_checks.py` sets `context.probes[units.SHOW_UNITS]` by hand. `tests/fixtures/frigate_api_config.json` has `safe_mode: false` and one `edgetpu` detector named `coral`. `tests/fixtures/status_fake.json` lists the fake report's checks.
- UI: `components/EnteredSecret.vue` (`APPS`, `CONSEQUENCES`, `restartNote` by count of units, `SECRET_JOB_DEADLINE_MS`), `modules/device/DevicePage.vue` loops over `GET /secrets`; `tests/entered-secret.spec.ts` and `tests/device-page.spec.ts` (its `THREE_SECRETS`); the design note in `tm-control/ui/README.md`.
- Device tests: `script/devpi/tests/devpi_checks.py::set_secret_table()` reads the job's table, `entered_secret_states(host, codedir, names, expected)` compares each env line and secret file on the Pi; `test_web.py::test_env_secret_lines_match_the_secret_files` and `test_secrets_lists_only_the_installed_addons_values`; `test_disruptive.py` has `TOKEN`, `TOKEN_PLACEHOLDER`, `token_state(address, cookie)`, `set_token(host, address, cookie, value)` (waits for the job and the unit's new invocation through `invocation()` and `not_restarted()`), and `test_set_and_remove_the_thingsboard_token_from_the_control_app`.
- Frigate 0.18.1: `PLUS_ENV_VAR = "PLUS_API_KEY"`, `MODEL_CACHE_DIR = "/config/model_cache"` (the host's `{{ tmsetup_codedir }}/frigate/config/model_cache`, which Frigate's unit bind-mounts as `/config`). `ModelConfig.check_and_load_plus_model(plus_api, detector)`: for `path: plus://<id>` it sets `path` to `/config/model_cache/<id>`, downloads the file and `<id>.json` only if either is missing, fills `width`, `height`, `input_tensor`, `input_pixel_format`, `model_type`, and the labelmap from the JSON, and raises `ValueError("Model does not support detector type of <type>")` when the JSON's `supportedDetectors` lacks the detector. A `ValueError` becomes a pydantic `ValidationError`, which `__main__` prints as a `*** Config Validation Errors ***` block (`Line #`, `Key`, `Value`, `Message :` lines) before retrying with `safe_load=True`: a config with `safe_mode: True`, no cameras, MQTT off, and the file's `auth`, `proxy`, and `database`; it then prints `Starting Frigate in safe mode.`. A download failure (`raise Exception(r.text)` in `PlusApi`) isn't caught: Frigate exits with a traceback and the unit restarts on failure. The Frigate+ picker is Settings, System, Detectors and model; snapshots must be enabled to submit them (the template enables them).

## Global Constraints

- No secret value in any output: not in a job's log, a check's detail, a migrate line, an audit row, the install log, or a test's output. Checks quote only the redacted log lines decision 9 allows. Tests use placeholders; the key placeholder is `PLACEHOLDER_KEY = "tmdev000-0000-0000-0000-000000000001:0123456789abcdef0123456789abcdef01234567"` (77 characters, matching Frigate's pattern).
- The role: task names `TMSetup - <Component> - <Action>`, `tmsetup_` variables, registered results ending in `_register`, FQCN modules, `become: true` per task, two-space YAML. Tasks that handle a value set `no_log: true`.
- Node-RED, Frigate, and tm-control versions stay as pinned in `vars/main.yml`; nothing here needs a rebuild of an image.
- Docs follow "Writing docs" in `docs/development/contributing.md`; every changed page is already in `nav:`; `mkdocs build --strict` must pass. Don't name the later upload feature or any private planning item; say "planned" at most.
- Commits end with the trailer block from CLAUDE.md ("AI use in this repository"), not `Co-Authored-By`. Never run `tmsetup.sh` on a dev machine. Say `PUBLIC push →` before any push.
- Off-device checks before the PR: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`, `cd tm-control/ui && npm test && npm run build`, the Ansible syntax check, the Jinja parse of every `.j2`, `json.tool` on `flows.json`, `bash -n script/tmsetup.sh`, `mkdocs build --strict`.

## Review Focus

1. **A key typed into `frigate.env` that Frigate wouldn't accept** (uppercase, a space, a missing colon): migrate must leave it, warn, and back the file up, because the lineinfile that follows writes the empty secret over it. Task 2's `test_a_frigate_plus_key_that_frigate_would_reject_is_left_with_a_warning`.
2. **`-f` after a hardware change** with the old Coral default still in `config.yml`: the section must not be carried, or the new detector gets a model it can't run. Task 4's `test_the_installers_own_model_section_is_not_carried`.
3. **Frigate in safe mode looks healthy**: version answers, cameras check says "no enabled camera to compare". Task 5's `test_frigate_in_safe_mode_is_an_error_that_quotes_the_messages`.
4. **A key-shaped string in a quoted log line** must never reach the page. Task 5's `test_quoted_log_lines_never_hold_a_key`.
5. **A plain run, without `-f`, must read nothing and change nothing** about the model section, so an operator's edit through Frigate's editor is untouched and no `slurp` runs for nothing. Task 4's `test_the_model_section_is_read_only_under_force`.

---

### Task 1: The fourth entered secret in `core/secrets.py`, the API's table, the job's table, and the role's name list

**Files:**
- Modify: `tm-control/backend/tm_control/core/secrets.py` (constants, `ENTERED_SECRETS`, `VALUE_PATTERNS`, `VALUE_RULES`)
- Modify: `tm-control/backend/tm_control/modules/secrets/router.py` (`ENTERED`)
- Modify: `tm-control/jobs/tm-job-set-secret` (`SECRETS`, the docstring's "three names")
- Modify: `script/ansible/roles/tmsetup/vars/main.yml` (`tmsetup_entered_secret_names`)
- Test: `tm-control/backend/tests/test_secrets.py`, `tests/test_api_secrets.py`, `tests/test_job_set_secret.py`

**Interfaces:**
- Produces: `FRIGATE_PLUS_API_KEY = "frigate_plus_api_key"`; `ENTERED_SECRETS = (THINGSBOARD_ACCESS_TOKEN, FRIGATE_PLUS_API_KEY, PLATE_RECOGNIZER_TOKEN, PLATE_RECOGNIZER_LICENSE_KEY)`; `VALUE_PATTERNS[FRIGATE_PLUS_API_KEY] = r"[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{12}:[a-z0-9]{40}"`; `VALUE_RULES[FRIGATE_PLUS_API_KEY] = "36 characters, a colon, and 40 lowercase letters or digits, as Frigate+ shows it"`. The same order in the role's list. `ENTERED[FRIGATE_PLUS_API_KEY] = EnteredSecret(title="Frigate+ API key", shows_ending=True, message="A Frigate+ API key is 36 characters, a colon, and 40 lowercase letters or digits, as Frigate+ shows it.", restarts=("frigate.service",), option=None)`, listed second, after the ThingsBoard token. The job's row: `{"pattern": <the same>, "env": [("frigate/frigate.env", "PLUS_API_KEY")], "restart": ["frigate.service"]}`.

- [ ] **Step 1: Write the failing tests**

In `test_secrets.py`, extend `test_the_entered_names` to the four names in order, and add:

```python
def test_the_frigate_plus_key_takes_frigates_own_format():
    assert is_valid_value(FRIGATE_PLUS_API_KEY, PLACEHOLDER_KEY)
    for bad in (PLACEHOLDER_KEY.upper(), PLACEHOLDER_KEY.replace(":", ""), PLACEHOLDER_KEY[:-1],
                PLACEHOLDER_KEY + "0", PLACEHOLDER_KEY.replace("-", "_", 1), " " + PLACEHOLDER_KEY):
        assert not is_valid_value(FRIGATE_PLUS_API_KEY, bad), bad
```

In `test_api_secrets.py`: `test_get_secrets_is_admin_only_and_lists_the_available_ones` expects `["thingsboard_access_token", "frigate_plus_api_key"]` without the add-on and the four with it (`test_plate_recognizer_secrets_appear_only_with_the_addon`); add `test_the_frigate_plus_key_row` (title `Frigate+ API key`, `restarts == ["frigate.service"]`, `ends_with` is the placeholder's last four once set through the fake job) and `test_the_frigate_plus_key_is_refused_in_the_wrong_format` (a 422 whose message is the row's `message` and doesn't hold the value, for `PLACEHOLDER_KEY.upper()`).

In `test_job_set_secret.py`: `test_the_frigate_plus_key_rewrites_frigate_env_and_restarts_frigate_only` (a `frigate/frigate.env` with a `PLUS_API_KEY=` line; after the job: the secret file holds the placeholder, the line holds it, every other byte of the env file is unchanged, the stand-in systemctl saw exactly `restart frigate.service`).

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_secrets.py tm-control/backend/tests/test_api_secrets.py tm-control/backend/tests/test_job_set_secret.py -q`
Expected: the new tests fail on the missing name; `test_generated_and_entered_names_match_the_role` and `test_the_table_matches_the_api` fail as soon as one side gains the name.

- [ ] **Step 3: Add the name, pattern, rule, API row, job row, and role entry** as the Interfaces block says. Put `PLACEHOLDER_KEY` in `tests/conftest.py` so every test module shares it. Update the job's docstring ("the four names"). Keep the three existing rows untouched.

- [ ] **Step 4: Run the three test files and the role's name test**

Run: `python -m pytest tm-control/backend/tests/test_secrets.py tm-control/backend/tests/test_api_secrets.py tm-control/backend/tests/test_job_set_secret.py script/tests/test_tmsetup_tasks.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend/tm_control/core/secrets.py tm-control/backend/tm_control/modules/secrets/router.py tm-control/jobs/tm-job-set-secret script/ansible/roles/tmsetup/vars/main.yml tm-control/backend/tests
git commit -m "Add the Frigate+ API key as an entered secret"
```

### Task 2: `tm-control migrate --frigate-env` moves a key typed into `frigate.env`

**Files:**
- Modify: `tm-control/backend/tm_control/core/migrate.py` (`run_frigate_env`, a shared env-file step)
- Modify: `tm-control/backend/tm_control/cli.py` (the option, the "at least one" message, `run_migrate`)
- Test: `tm-control/backend/tests/test_entered_secrets_migration.py`, `tests/test_tm_control_cli.py`

**Interfaces:**
- Consumes: `FRIGATE_PLUS_API_KEY`, `is_valid_value`, `VALUE_RULES` (Task 1).
- Produces: `migrate.run_frigate_env(env_path: Path, secrets_dir: Path, dry_run: bool = False) -> int`, with the same output and warning lines as `run_plate_recognizer_env` for the single entry `("PLUS_API_KEY", FRIGATE_PLUS_API_KEY)` and the placeholder set `{""}`: `<path>: up to date` (also when the file is missing), `<path>: moved PLUS_API_KEY to the secrets files`, `<path>: would move PLUS_API_KEY to the secrets files`; `WARNING` lines on stderr that name the key, never the value, for a value that differs from the secret file and for one that fails the pattern, each backing the env file up first. The CLI option `--frigate-env PATH` ("path to frigate.env: move a PLUS_API_KEY typed into it to the secret files"), run after the other three steps.

- [ ] **Step 1: Write the failing tests**

In `test_entered_secrets_migration.py`, with a `frigate_env(tmp_path, key=PLACEHOLDER_KEY)` helper that writes the template's lines with `PLUS_API_KEY=<key>` among them:

```python
def test_a_frigate_plus_key_typed_into_frigate_env_moves(tmp_path, secrets_dir, capsys): ...
    # exit 0; the secret file holds PLACEHOLDER_KEY + "\n", mode 0o640; the env file is unchanged (tmsetup rewrites
    # the line); stdout is "<path>: moved PLUS_API_KEY to the secrets files"; no backup is made
def test_an_empty_plus_api_key_line_is_up_to_date(tmp_path, secrets_dir, capsys): ...
def test_a_missing_frigate_env_is_up_to_date(tmp_path, secrets_dir, capsys): ...
def test_a_frigate_plus_key_that_frigate_would_reject_is_left_with_a_warning(tmp_path, secrets_dir, capsys): ...
    # PLACEHOLDER_KEY.upper(): exit 0, the secret file stays empty, a backup frigate.env.<stamp>.bak holds the
    # original text, stderr has one WARNING line naming PLUS_API_KEY and the backup, and never the value
def test_a_frigate_plus_key_that_differs_from_the_secret_file_is_kept_out_with_a_warning(...): ...
def test_frigate_env_dry_run_writes_nothing(tmp_path, secrets_dir, capsys): ...
```

In `test_tm_control_cli.py`: `test_migrate_frigate_env_moves_the_key` (through `main(["migrate", "--frigate-env", str(path), "--secrets-dir", str(secrets_dir)])`), and extend `test_migrate_requires_a_config_option` so the error names all four options and `test_migrate_runs_every_config_given` so four steps run.

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_entered_secrets_migration.py tm-control/backend/tests/test_tm_control_cli.py -q`
Expected: FAIL on the missing function and option.

- [ ] **Step 3: Implement `run_frigate_env`** by lifting the body of `_run_plate_recognizer_env` into `_run_env(env_path, secrets_dir, dry_run, entries, placeholders)` that both callers use, so the Plate Recognizer step's behaviour and messages don't change (its tests are the regression check). Add the CLI option and the dispatch.

- [ ] **Step 4: Run the two test files, then the whole backend suite**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend/tm_control/core/migrate.py tm-control/backend/tm_control/cli.py tm-control/backend/tests
git commit -m "Move a Frigate+ key typed into frigate.env to the secrets at upgrade"
```

### Task 3: tmsetup renders `PLUS_API_KEY` from the secret on every run and runs the move first

**Files:**
- Modify: `container/frigate/frigate.env.j2` (the `PLUS_API_KEY` line)
- Modify: `script/ansible/roles/tmsetup/tasks/frigate_credentials.yml` (the lineinfile loop)
- Modify: `script/ansible/roles/tmsetup/tasks/entered_secrets.yml` (the stat loop, the argv, the header comment)
- Test: `script/tests/test_tmsetup_templates.py`, `script/tests/test_tmsetup_tasks.py`

**Interfaces:**
- Consumes: `tmsetup_secrets['frigate_plus_api_key']` (Task 1's role entry makes `secrets.yml` create and read it), `--frigate-env` (Task 2).
- Produces: `frigate.env.j2` renders `PLUS_API_KEY={{ tmsetup_secrets['frigate_plus_api_key'] }}` under a comment saying it's set on the Device page. The lineinfile task, renamed `TMSetup - Frigate Credentials - Add the go2rtc RTSP login, the proxy secret, and the Frigate+ key to frigate.env`, gains `{ key: PLUS_API_KEY, value: "{{ tmsetup_secrets['frigate_plus_api_key'] }}" }` as its fourth item. `entered_secrets.yml` stats `'{{ tmsetup_codedir }}/frigate/frigate.env'` as its third path and adds `--frigate-env <that path>` to the argv when `results[2].stat.exists`.

- [ ] **Step 1: Write the failing tests**

`test_tmsetup_templates.py`: `test_frigate_env_renders_the_frigate_plus_key_from_the_secrets` (render with `tmsetup_secrets` holding `frigate_plus_api_key: PLACEHOLDER_KEY`; `PLUS_API_KEY=<placeholder>` is a line; with an empty value the line is `PLUS_API_KEY=`). Add `frigate_plus_api_key` to the `tmsetup_secrets` dicts the two existing `frigate.env` tests pass, since `StrictUndefined` rejects the missing key.

`test_tmsetup_tasks.py`: `test_existing_frigate_env_gets_the_frigate_plus_key_without_printing_it` (the renamed task is `no_log`, its fourth item is `PLUS_API_KEY` with the value above, `notify` is `Restart frigate.service`); rename the task in the two existing tests. Extend `test_entered_secrets_move_before_any_config_template_renders`: the stat loop is `[NODE_RED_CONFIG, PLATE_RECOGNIZER_ENV, FRIGATE_ENV]`, `stat_results` takes three flags, and the argv cases include `(True, True, True)` (all three options, in the order node-red, plate-recognizer, frigate-env) and `(False, False, True)` (`--frigate-env` alone); the `when` is true for any one file. Add a test that `main.yml` imports `entered_secrets.yml` before `frigate_setup.yml` and `frigate_credentials.yml` under the `frigate` tag (the existing position test already asserts it precedes `frigate_setup.yml`; add `frigate_credentials.yml`).

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest script/tests/test_tmsetup_templates.py script/tests/test_tmsetup_tasks.py -q`
Expected: FAIL

- [ ] **Step 3: Make the template, loop, and stat changes.** In `entered_secrets.yml`'s header comment, add that a Frigate+ key typed into `frigate.env` moves too, and that Frigate isn't restarted for a move because `frigate_credentials.yml` writes the same value back into the line on this run. In `frigate_credentials.yml`'s header, add the Frigate+ key to what the loop writes.

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
git add container/frigate/frigate.env.j2 script/ansible/roles/tmsetup/tasks/frigate_credentials.yml script/ansible/roles/tmsetup/tasks/entered_secrets.yml script/tests
git commit -m "Render PLUS_API_KEY from the secrets on every run and move a typed key first"
```

### Task 4: `-f` keeps the model section Frigate's `config.yml` has

**Files:**
- Modify: `script/ansible/roles/tmsetup/vars/main.yml` (`tmsetup_frigate_coral_model_file`)
- Modify: `script/ansible/roles/tmsetup/tasks/frigate_setup.yml` (four tasks before the template task; the download tasks use the variable)
- Modify: `container/frigate/config/config.yml.j2` (the `model:` section)
- Test: `script/tests/test_tmsetup_templates.py`, `script/tests/test_tmsetup_tasks.py`

**Interfaces:**
- Produces: `tmsetup_frigate_coral_model_file: yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite` in `vars/main.yml`; the template's Coral `path:` is `/config/model_cache/{{ tmsetup_frigate_coral_model_file }}` and the download task's `dest` ends with `/frigate/config/model_cache/{{ tmsetup_frigate_coral_model_file }}`. A fact `tmsetup_frigate_model_keep` (a mapping, `{}` when there's nothing to keep) that the template renders as the `model:` section, before the detector default, when it isn't empty:

```jinja
{% if tmsetup_frigate_model_keep | default({}) %}
# The model this device had before tmsetup -f replaced the file (see "What -f replaces" in the installer docs)
model:
{{ tmsetup_frigate_model_keep | to_nice_yaml(indent=2) | indent(2, first=True) }}
{% elif pci_available or usb_available %}
```

The tasks, in this order, each `when: tmsetup_force_configs | bool` where noted, and all before `TMSetup - Frigate Setup - Create Frigate container configuration files`:
1. `TMSetup - Frigate Setup - Start with no model section to keep` (`set_fact` `tmsetup_frigate_model_keep: {}`, always).
2. `TMSetup - Frigate Setup - Check for an existing Frigate config` (`become`, `stat` of `{{ tmsetup_codedir }}/frigate/config/config.yml`, `get_checksum: false`, register `tmsetup_frigate_config_stat_register`, when force).
3. `TMSetup - Frigate Setup - Read the model section -f keeps` (`become`, `no_log`, `slurp`, register `tmsetup_frigate_config_slurp_register`, when force and `tmsetup_frigate_config_stat_register.stat.exists`).
4. A `block` with the same `when` holding `TMSetup - Frigate Setup - Keep the device's model section across -f` (`no_log`, `set_fact` of `tmsetup_frigate_model_keep` from the slurped text by the rule in decision 6: `from_yaml` of the decoded content, its `model` key, kept when it is a mapping whose `path` is a non-empty string other than `'/config/model_cache/' ~ tmsetup_frigate_coral_model_file`, else `{}`), and a `rescue` with `set_fact` `tmsetup_frigate_model_keep: {}` and a `debug` whose `msg` says the current Frigate config couldn't be read as YAML, so the template's model section is used (no content from the file).

- [ ] **Step 1: Write the failing tests**

`test_tmsetup_templates.py`, with `CORAL_FILE = load_role_yaml("vars/main.yml")["tmsetup_frigate_coral_model_file"]` and `CORAL_PCI = {"edgetpu_pci": {"dev_path_available": True, "exists": True, "frigate_type": "edgetpu", "frigate_device": "pci", "dev_path": "/dev/apex_0"}}`:

```python
KEPT = {"path": "plus://0123456789abcdef0123456789abcdef", "labelmap": {2: "vehicle"}}

def test_a_kept_model_section_replaces_the_detector_default():
    config = yaml.safe_load(render("container/frigate/config/config.yml.j2", tmsetup_detectors=CORAL_PCI,
                                   tmsetup_frigate_coral_model_file=CORAL_FILE, tmsetup_frigate_model_keep=KEPT))
    assert config["model"] == KEPT  # a plus:// path, a nested labelmap, an int key: all round-trip

def test_without_a_kept_section_the_coral_default_names_the_installers_model():
    config = yaml.safe_load(render(..., tmsetup_detectors=CORAL_PCI, tmsetup_frigate_coral_model_file=CORAL_FILE))
    assert config["model"]["path"] == f"/config/model_cache/{CORAL_FILE}"

def test_without_a_kept_section_and_without_a_coral_there_is_no_model_section():
    assert "model" not in yaml.safe_load(render(..., tmsetup_detectors={}))
```

`test_tmsetup_tasks.py`, with `keep = frigate_tasks()["TMSetup - Frigate Setup - Keep the device's model section across -f"]` found inside the block, and `evaluate()` on its `set_fact` expression:

```python
def test_the_model_section_is_read_only_under_force(): ...
    # the stat, slurp, and block each have "tmsetup_force_configs | bool" in their when; the slurp also needs the
    # stat's .stat.exists; the four tasks precede the template task; the slurp and the set_fact are no_log; the
    # first task sets {} with no when
def test_a_chosen_model_section_is_kept(): ...
    # slurped content = b64 of "model:\n  path: plus://abc\n  width: 320\n" -> {"path": "plus://abc", "width": 320}
    # and the same for a local path "/config/model_cache/mine.tflite"
def test_the_installers_own_model_section_is_not_carried(): ...
    # path == "/config/model_cache/" + the vars file's tmsetup_frigate_coral_model_file -> {}
def test_a_model_section_without_a_path_or_not_a_mapping_is_not_carried(): ...
    # "model:\n  width: 320\n" -> {}; "model: plus://abc\n" -> {}; "cameras: {}\n" -> {}; path "" -> {}
def test_an_unparseable_frigate_config_keeps_the_templates_section(): ...
    # the block's rescue sets {} and its debug msg holds no "{{" that renders the file's content
def test_the_coral_model_file_is_one_variable(): ...
    # the two download tasks' dest/url and the template use tmsetup_frigate_coral_model_file; the literal file name
    # appears in vars/main.yml only
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest script/tests/test_tmsetup_templates.py script/tests/test_tmsetup_tasks.py -q`
Expected: FAIL

- [ ] **Step 3: Add the variable, the four tasks, and the template branch.** The `set_fact` expression is the one decision the tests pin: write it with a task-level `vars:` entry for the parsed `model` value so the rule reads in one line. Keep the template's detector default byte-for-byte apart from the variable.

- [ ] **Step 4: Run the role tests, the syntax check, and the Jinja parse** as in Task 3 Step 4.
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add script/ansible/roles/tmsetup/vars/main.yml script/ansible/roles/tmsetup/tasks/frigate_setup.yml container/frigate/config/config.yml.j2 script/tests
git commit -m "Keep the model section Frigate's config.yml has across tmsetup -f"
```

### Task 5: Status: Frigate's safe mode, and the `config.frigate_plus` check

**Files:**
- Modify: `tm-control/backend/tm_control/adapters/yamlfile.py` (`ConfigRead`, `read_config(path)`)
- Modify: `tm-control/backend/tm_control/adapters/nodered.py` (`config()` delegates; `ConfigRead` re-exported)
- Modify: `tm-control/backend/tm_control/adapters/frigate.py` (`config_file(codedir)`)
- Modify: `tm-control/backend/tm_control/modules/apps/probes.py` (`frigate_config_file`, `frigate_journal`)
- Modify: `tm-control/backend/tm_control/modules/apps/checks.py` (`frigate`: safe mode)
- Modify: `tm-control/backend/tm_control/modules/apps/contracts.py` (`frigate_plus`, `GROUP`)
- Modify: `tm-control/backend/tests/fixtures/status_fake.json` (one `config.frigate_plus` row, ok, "Frigate+ isn't in use.")
- Test: `tm-control/backend/tests/test_yamlfile.py`, `tests/test_app_checks.py`, `tests/test_contract_checks.py`

**Interfaces:**
- Consumes: `FRIGATE_PLUS_API_KEY`, `VALUE_PATTERNS` (Task 1); `unit_states`, `active_since`, `RUNNING` from `modules/services/units.py`; `systemd.journal_lines`, `systemd.journal_tail`.
- Produces:
  - `yamlfile.read_config(path: Path) -> ConfigRead`: the parse `nodered.config` does today, moved; `nodered.config(codedir)` calls it; `frigate.config_file(codedir) -> ConfigRead` reads `<codedir>/frigate/config/config.yml`.
  - `probes.frigate_config_file(context) -> ConfigRead` (key `FRIGATE_CONFIG_FILE = "frigate.config_file"`); `probes.frigate_journal(context) -> list[str]` (key `FRIGATE_JOURNAL = "frigate.journal"`): when `unit_states(context)["frigate.service"]` is in `RUNNING`, `journal_lines("frigate.service", since, 400, invocation_id)` with `since = f"@{int(active_since(values).timestamp()) - 60}"` (or `"-1h"` with no time) and the unit's `InvocationID` (or None when empty); otherwise `journal_tail("frigate.service", 400) or []`.
  - In `contracts.py`: `MODEL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")`, `KEY_SHAPED = re.compile(VALUE_PATTERNS[FRIGATE_PLUS_API_KEY])`, `redact(line: str) -> str` (key-shaped substrings become `<key>`, then the line is cut to `MESSAGE_MAX`), `validation_messages(lines) -> list[str]` (the text after `Message : ` on such lines, redacted, at most `ERRORS_SHOWN`), `traceback_last_line(lines) -> str | None` (the last line matching `^\w+(\.\w+)*(Error|Exception)\b.*`, redacted), `model_path(config_file: ConfigRead) -> str | None`, `plus_model_id(path) -> str | None` (the part after `plus://` when it matches `MODEL_ID`), `model_cached(codedir, model_id) -> bool` (both `<codedir>/frigate/config/model_cache/<id>` and `<id>.json` are regular files), `frigate_plus(context) -> list[Check]` with id `config.frigate_plus`, title `Frigate+`, appended to `GROUP`.
  - `checks.frigate` adds, after the version is known: when `probes.frigate_config(context)` is a dict with `safe_mode` true, an error whose detail is `Frigate <version> started in safe mode, with no cameras, because its config has an error, so nothing is counted. <messages>Fix it in Frigate's configuration editor (Settings, Configuration editor), then choose Save & Restart.` where `<messages>` is `Its log says: <m1>; <m2>. ` from `validation_messages(frigate_journal(context))` or empty, and no fix button.
  - `frigate_plus` decision table, in this order (details are the fixed sentences below; `<id>` is the model id):
    1. `frigate_config_file(context).data is None` → `unknown`: "Frigate's config.yml is missing / can't be read / has a YAML error, so its model and the Frigate+ key can't be compared." (one wording per problem, as `CONFIG_YML_PROBLEM` does).
    2. The path isn't `plus://…` and the key isn't set → `ok`: "Frigate+ isn't in use."
    3. The path isn't `plus://…` and the key is set → `warn`: "A Frigate+ key is set, so snapshots can be submitted from Frigate's Explore page, but Frigate runs {the installer's model|a local model} rather than a Frigate+ model. Once a model is trained, pick it under Settings, System, Detectors and model in Frigate, or set model.path to plus://<model id> in its configuration editor." ("the installer's model" when `path` is empty or ends with `tmsetup_frigate_coral_model_file`'s name; otherwise "a local model").
    4. The path is `plus://` but the id doesn't match `MODEL_ID` → `error`: "model.path in Frigate's config names a Frigate+ model id with characters a model id can't have. Check the id in Frigate's configuration editor."
    5. `plus://<id>`, not cached, key not set → `error`: "Frigate's config names the Frigate+ model <id>, but no key is set and the model's files aren't on the device, so Frigate can't download it. Set the key, or copy <id> and <id>.json into Frigate's model_cache directory." with `Fix(kind="link", text="Set the key", href="/device#tokens-and-keys")`.
    6. `plus://<id>` and Frigate answers with `safe_mode` true and `validation_messages` has a message whose text contains `Model does not support detector type of <type>` → `error`: "Frigate couldn't use the Frigate+ model <id> and started in safe mode, with no cameras: it isn't built for the <type> detector. Pick a model made for <type> in Frigate+, then set it in Frigate." Any other message that mentions `model` → `error`: "Frigate couldn't use the model <id> and started in safe mode, with no cameras. Its log says: <message>." Safe mode with no message about the model → leave it to the Apps check: fall through to 8.
    7. `plus://<id>` and Frigate doesn't answer: when `unit_states` says `frigate.service` isn't in `RUNNING` and `traceback_last_line` is not None → `error`: "Frigate stopped while fetching the Frigate+ model <id>, so it isn't running. Its log ends with: <line>. Check the key on the Device page and the model id in Frigate's config, and that the device is online; a model's files copied into model_cache need no download." Otherwise `unknown`: "Frigate isn't answering, so whether it loaded the Frigate+ model <id> is unknown."
    8. `plus://<id>` otherwise → `ok`: "Frigate runs the Frigate+ model <id>." plus " Snapshots can be submitted." when the key is set, or " It was loaded from the files on the device; set a key to submit snapshots." when not.

- [ ] **Step 1: Write the failing tests**

`test_yamlfile.py`: `test_read_config_reports_missing_unreadable_and_invalid_with_the_line`, the cases `test_app_checks.py` runs against `nodered.config` today (around its line 600), which keep passing unchanged through the delegation.

The `apps.context()` fixture builds a fresh `Context` with `settings=None` on each call, so a check that reaches `unit_states` or the journal would fail there; `config_group(apps)` can't preset probes either. Add `config_group_with(apps, probes: dict) -> dict[str, Check]` to `test_contract_checks.py` (and the same for the apps group in `test_app_checks.py`): build `context = apps.context()`, `context.probes.update(probes)`, run the group. Tests that involve the journal preset `probes.FRIGATE_JOURNAL`; the rule 7 tests preset `units.SHOW_UNITS` too; only the probe test lets `frigate_journal` run, with `units.SHOW_UNITS` preset and the two `systemd` functions monkeypatched.

`test_app_checks.py`:

```python
def test_frigate_in_safe_mode_is_an_error_that_quotes_the_messages(apps): ...
    # apps.edit_json(FRIGATE_CONFIG, lambda c: c.update(safe_mode=True)); context.probes["frigate.journal"] =
    # FIXTURE_LINES (the banner, "Line #  : 3", "Key     : model -> path", "Value   : plus://abc",
    # "Message : Value error, Model does not support detector type of edgetpu", "Starting Frigate in safe mode.");
    # status error, "safe mode" and the message in the detail, no fix
def test_frigate_in_safe_mode_without_journal_lines_still_errors(apps): ...
def test_frigate_not_in_safe_mode_is_ok_as_before(apps): ...
```

`test_contract_checks.py`: `test_cameras_match` lists six ids and titles (`config.frigate_plus`, `Frigate+`); the YAML-error test still gives every check `unknown`, so the Frigate+ check's rule 1 must also fire when Frigate's file is fine but Node-RED's isn't? No: it reads Frigate's file only. Change that test to expect `config.frigate_plus` ok, since Frigate's config in the fixture has no `plus://` path and no key. Then, with helpers `frigate_config_file(apps, text)` (writes `apps.codedir/frigate/config/config.yml`), `cache_model(apps, model_id)` (writes the two files), and `apps.secrets.entered[FRIGATE_PLUS_API_KEY] = PLACEHOLDER_KEY`:

```python
def test_frigate_plus_not_in_use_is_ok(apps): ...
def test_a_key_without_a_plus_model_is_a_warning_naming_the_installers_model(apps): ...  # the Coral default path
def test_a_key_with_a_local_model_is_a_warning_naming_a_local_model(apps): ...
def test_a_plus_model_with_a_bad_id_is_an_error(apps): ...  # "plus://../x"
def test_a_plus_model_without_a_key_or_cached_files_is_an_error_with_a_link(apps): ...
def test_a_cached_plus_model_without_a_key_is_ok_and_says_so(apps): ...
def test_a_plus_model_with_a_key_is_ok(apps): ...
def test_a_plus_model_frigate_rejected_for_the_detector_names_the_type(apps): ...  # safe_mode + the journal fixture
def test_a_plus_model_frigate_rejected_for_another_reason_quotes_the_message(apps): ...
def test_safe_mode_for_an_unrelated_reason_is_left_to_the_apps_check(apps): ...  # message about cameras -> rule 8
def test_a_plus_model_and_frigate_stopped_with_a_traceback_is_an_error(apps): ...
    # apps.answers[FRIGATE_VERSION] = (None, None); context.probes[units.SHOW_UNITS] = {"frigate.service":
    # {"ActiveState": "activating", "SubState": "auto-restart", ...}}; journal tail ends with
    # 'Exception: {"message":"Unauthorized"}'
def test_a_plus_model_and_frigate_silent_is_unknown(apps): ...
def test_a_missing_or_invalid_frigate_config_is_unknown(apps): ...
def test_quoted_log_lines_never_hold_a_key(apps): ...
    # a Message line and a traceback line each containing PLACEHOLDER_KEY: neither detail contains it; both hold <key>
def test_the_journal_probe_reads_the_current_run_when_frigate_runs_and_the_tail_when_it_doesnt(apps, monkeypatch): ...
    # monkeypatch systemd.journal_lines / journal_tail to record their arguments; RUNNING with ActiveEnterTimestamp
    # "@1700000000" and InvocationID "abc" -> journal_lines("frigate.service", "@1699999940", 400, "abc");
    # "failed" -> journal_tail("frigate.service", 400)
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_yamlfile.py tm-control/backend/tests/test_app_checks.py tm-control/backend/tests/test_contract_checks.py -q`
Expected: FAIL

- [ ] **Step 3: Implement** the adapter move, the two probes, the safe-mode branch, and `frigate_plus` with its helpers, as the Interfaces block says. Add the fixture row to `status_fake.json`.

- [ ] **Step 4: Run the backend suite and the fake-mode OpenAPI test**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS (the status fixture test and `test_openapi_document` included).

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit -m "Report Frigate's safe mode and whether the Frigate+ key and model are paired"
```

### Task 6: The form on the Device page

**Files:**
- Modify: `tm-control/ui/src/components/EnteredSecret.vue` (`APPS`, `CONSEQUENCES`, the restart note)
- Modify: `tm-control/ui/tests/entered-secret.spec.ts`, `tm-control/ui/tests/device-page.spec.ts`
- Modify: `tm-control/ui/README.md` (the design note)

**Interfaces:**
- Consumes: `GET /secrets` rows with `restarts: ["frigate.service"]` (Task 1).
- Produces: `APPS['frigate.service'] = 'Frigate'`; `RESTART_SECONDS: Record<string, number> = { 'node-red-tm.service': 30, 'plate-recognizer.service': 30, 'frigate.service': 60 }`; `describe(seconds)`: up to 30 "about thirty seconds", up to 60 "about a minute", up to 90 "about a minute and a half", otherwise "about two minutes"; `restartNote` = `${apps} restart${one ? 's' : ''}, which takes ${describe(sum)}.` followed by ` Traffic isn't counted while it does.` when `frigate.service` is among the units. The existing notes for the three other secrets must come out byte-for-byte as before. `CONSEQUENCES.frigate_plus_api_key = "Snapshots can't be sent to Frigate+ until a key is set again. A Frigate+ model already on the device keeps running."`

- [ ] **Step 1: Write the failing tests**

`entered-secret.spec.ts`: `it('says Frigate restarts in about a minute and that traffic is not counted')` (a secret with `restarts: ['frigate.service']`: the Saving alert's text is `Saving. Frigate restarts, which takes about a minute. Traffic isn't counted while it does.`, and the success alert ends `Frigate restarted.`); `it('keeps the other secrets' notes as they were')` (the ThingsBoard and Plate Recognizer token notes, verbatim as today). `device-page.spec.ts`: add the Frigate+ row (`name: 'frigate_plus_api_key', title: 'Frigate+ API key', set: false, ends_with: null, restarts: ['frigate.service']`) to the list the page is given and update the count and titles the tests assert.

- [ ] **Step 2: Run them to see them fail**

Run: `cd tm-control/ui && npm test`
Expected: the new tests fail.

- [ ] **Step 3: Implement** the three constants and the note. Update the README's Tokens and keys note (the list of secrets, the Frigate wording).

- [ ] **Step 4: Run the UI tests and the build**

Run: `cd tm-control/ui && npm test && npm run build`
Expected: PASS, and `vue-tsc` finds no type error.

- [ ] **Step 5: Commit**

```bash
git add tm-control/ui
git commit -m "Show the Frigate+ API key form on the Device page"
```

### Task 7: Docs, CLAUDE.md, and the dev-Pi README

**Files:**
- Modify: `docs/configuration/frigate-config.md` ("Better models")
- Modify: `docs/configuration/environment.md` (a `frigate.env` section)
- Modify: `docs/use/device-health.md` (Configuration row, Tokens and keys)
- Modify: `docs/reference/tmsetup.md` ("What `-f` replaces", "Add an accelerator later")
- Modify: `docs/build-your-own-device-diy/update.md` (the migrate warning admonition)
- Modify: `docs/use/system-admin.md` (the files table)
- Modify: `docs/development/tm-control.md` (the secrets paragraph, the jobs table, the Configuration checks)
- Modify: `CLAUDE.md` (overwrite semantics, the secrets list, the Frigate+ check)
- Modify: `script/devpi/README.md` (`pii_free`, the test tables)

**Interfaces:** none; the pages describe Tasks 1 to 6.

- [ ] **Step 1: Write the pages**

"Better models" in `frigate-config.md` becomes a section with these parts, in prose for operators: what Frigate+ is and that it's paid and separate from the Traffic Monitor; **Enter the key** on the Device page's Tokens and keys (the key's shape, Frigate restarts, about a minute); **Submit snapshots** from Frigate's Explore page (snapshots are on by default; the key alone does this); **Use a model**: Frigate's picker (Settings, System, Detectors and model) for a device that's online, or the editor with a `model:` section of only `path: plus://<model id>` (every other key removed, since Frigate+ supplies them), which Frigate downloads on restart; a model must be built for the device's detector: Coral is `edgetpu`, Hailo is `hailo8l`, none is `cpu`, and `yolov9` is the type to choose (`mobiledet` is legacy); **A device without internet**: download the model on another computer (Frigate+ gives the two files, `<id>` and `<id>.json`), copy both into `/opt/traffic-monitor/frigate/config/model_cache/` over SSH, set the same `path`, and Frigate loads them without contacting Frigate+; the key is then only needed for snapshots; **A model of your own**: a file in `model_cache`, `path: /config/model_cache/<file>`, and the `width`, `height`, `input_tensor`, `input_pixel_format`, `input_dtype`, `model_type`, and `labelmap_path` keys from Frigate's [reference config](https://docs.frigate.video/configuration/advanced/reference), which `plus://` models don't need; **What the installer keeps**: `-f` keeps a `model:` section that isn't the installer's default, comments in it excepted, and after changing the accelerator the kept model may not match (the Status page says); **The Status page's Frigate+ check** and what each state means, with a sentence on Frigate's safe mode.

`environment.md`: a `frigate.env` section with a table of `FRIGATE_RTSP_PASSWORD` (your own cameras' password, untouched by the installer), `PLUS_API_KEY` (set on the Device page; filled from the device's secrets on every run; empty means no Frigate+), and a line saying the `FRIGATE_GO2RTC_*`, `FRIGATE_PROXY_AUTH_SECRET`, and `FRIGATE_MQTT_*` lines are the installer's.

`device-health.md`: the Configuration row gains the Frigate+ sentence; Tokens and keys lists the Frigate+ API key on every device, says Frigate restarts in about a minute and traffic isn't counted meanwhile, and adds the key to the paragraph about values the installer moves. `tmsetup.md`: the `-f` list says the fresh Frigate config keeps the `model:` section you chose, and the secrets paragraph names the key and `frigate.env`; "Add an accelerator later" says `-f` keeps a chosen model, which may not match the new accelerator. `update.md`: the moved values include a Frigate+ key typed into `frigate.env`. `system-admin.md`: a row for `frigate/frigate.env`. `tm-control.md`: four entered secrets, the job's four names and `frigate.env`, the two new check behaviours in the checks list. `CLAUDE.md`: the entered secrets' env lines include `PLUS_API_KEY`; nine device secrets, four entered; `-f` keeps Frigate's `model:` section when its path isn't the installer's default (the role reads it before the template renders); `entered_secrets.yml` takes `--frigate-env`. `script/devpi/README.md`: `pii_free` names the four empty entered secret files; the `test_web.py (status)` and `test_disruptive.py` rows mention the Frigate+ key; "The token test" note gets a sibling for the key test.

- [ ] **Step 2: Build the docs strictly**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: no warnings, exit 0.

- [ ] **Step 3: Commit**

```bash
git add docs CLAUDE.md script/devpi/README.md
git commit -m "Document the Frigate+ key, models, and what -f keeps"
```

### Task 8: Device tests

**Files:**
- Modify: `script/devpi/tests/test_web.py`
- Modify: `script/devpi/tests/test_disruptive.py`

**Interfaces:**
- Consumes: `set_secret_table()`, `entered_secret_states()`, `invocation()`, `not_restarted()`, `wait_for_job()`.
- Produces: in `test_disruptive.py`, `secret_state(address, cookie, name)` and `set_secret(host, address, cookie, name, value, restarts: list[str], untouched: list[str])` generalising `token_state`/`set_token` (which become one-line wrappers), and `KEY_PLACEHOLDER` equal to Task 1's placeholder.

- [ ] **Step 1: Write the tests**

`test_web.py`: `test_secrets_lists_only_the_installed_addons_values` expects `["thingsboard_access_token", "frigate_plus_api_key"]` without the add-on and the four names with it; `test_env_secret_lines_match_the_secret_files` also asserts `frigate/frigate.env:PLUS_API_KEY` isn't `absent`; a new `test_frigate_plus_check_is_on_the_status_page` (admin session: the Configuration group has `config.frigate_plus`, and its status is `ok` or `warn`, never `error` or `unknown`, on a unit the inventory marks healthy).

`test_disruptive.py`: `test_set_and_remove_the_frigate_plus_key_from_the_control_app` as the ThingsBoard test, for `pii_free` units: skip when a key is set; Save writes the file and the `frigate.env` line and gives `frigate.service` a new invocation while `node-red-tm.service` keeps its own; `GET /secrets` shows `(True, KEY_PLACEHOLDER[-4:])`; Remove empties both and restarts Frigate again; the `finally` puts the key back to empty. Note in its docstring that the placeholder has Frigate's format, so Frigate accepts it and never contacts Frigate+ while no `plus://` model is set and no snapshot is submitted.

- [ ] **Step 2: Check them off-device**

Run: `python -m pytest script/devpi/tests --collect-only -q 2>&1 | tail -3` (collection only; they run on a Pi in Task 9).
Expected: the two new tests are collected, no errors.

- [ ] **Step 3: Commit**

```bash
git add script/devpi/tests
git commit -m "Check the Frigate+ key on a device"
```

### Task 9: The Pi plan

Run through `tmdev.py check start|item|status|end` so it's logged, on the dev Pis from the inventory (see `script/devpi/README.md`); one host at a time. Every value is a placeholder; compare files on the Pi by hash or equality, never print one.

- [ ] **Bench A** (Pi 5, Coral, camera, upgraded from PR 278):
  1. Type `PLUS_API_KEY=<KEY_PLACEHOLDER>` into `frigate.env` by hand, then a full upgrade without `-f`: the secret file holds it, the env line equals the file, the install log has `moved PLUS_API_KEY`, no value in the log (`test_no_secret_in_the_install_log` covers it), Frigate wasn't restarted by the move alone (compare invocations), `GET /secrets` lists four rows on a unit with the add-on or two without, the Status page's Frigate+ check warns "a key is set … the installer's model".
  2. Measure the restart: from `POST /secrets/frigate_plus_api_key` to `/api/stats` showing the Coral detector's `pid` again, through `journalctl` times. Record it in the PR; if it's over 90 s, change Task 6's `RESTART_SECONDS['frigate.service']` and the docs' "about a minute".
  3. In Frigate's configuration editor, set `model:` to only `path: plus://tmdevplaceholder0001` and Save & Restart: with the placeholder key, Frigate+ refuses the download and Frigate stops with a traceback. Record the unit's state and the last journal lines; the Status page's Frigate+ check must say "stopped while fetching … model tmdevplaceholder0001" with the redacted last line, the Services row must show the failure, and the detail must not contain the placeholder key. If the journal's shape differs from the plan's assumption (a `Config Validation Errors` block instead of a traceback, or the unit staying active), adjust Task 5's rules 6 and 7 and their tests, and say so in the PR.
  4. Remove the key on the Device page while that `plus://` section stays: the check becomes rule 5's error with the "Set the key" link (not cached). Then run the installer with `-f`: `config.yml` is fresh but keeps `model: path: plus://tmdevplaceholder0001` and the key line is empty; restore `model:` to the Coral default section by hand (from the backup), restart Frigate, and check the Frigate+ check reads "isn't in use".
  5. Safe mode: through the editor set `detectors: coral: type: nope`, Save & Restart; Frigate starts in safe mode; the Apps Frigate check errors and quotes the message, the camera check says nothing to compare, the Frigate+ check is rule 2 or 3. Restore the config.
  6. `-f` with a non-default local model section (`path: /config/model_cache/mine.tflite` plus the Coral default's other keys, the file absent): the section is carried; put the default back.
  7. If a real Frigate+ key and a model built for `edgetpu` are available to the maintainer: set the key on the page, set `plus://<id>`, confirm the check reads ok and Frigate detects; copy the two files aside, remove the key, restart Frigate, confirm the model still loads from `model_cache` and the check says so. Otherwise record that this path wasn't run.
  8. Device tests: `tmdev.py test <host> --disruptive -- -k "secret or frigate_plus or thingsboard or install_log"`, then the full non-disruptive suite.
- [ ] **Bench B** (Pi 5, Hailo, no camera, fresh card): a fresh install creates the four empty files; `GET /secrets` lists the key; `-f` with no `model:` section carries nothing and renders no section; `-f` with `path: plus://tmdevplaceholder0001` carries it; the full suite with the expected skips.
- [ ] Record each item's outcome with `tmdev.py check item`, and end the plan with `tmdev.py check end`.

### Task 10: Pull request

- [ ] Run every off-device check in Global Constraints once more on the final branch; `npm run build` so the UI's build matches.
- [ ] Open the PR against `feature/entered-secrets/95` with the template filled in: the release-note paragraph ("The Frigate+ API key is set on the Device page and kept in the device's secrets; the installer moves a key typed into frigate.env. tmsetup -f now keeps the model section chosen in Frigate's config.yml. The Status page says when Frigate runs in safe mode and whether the Frigate+ key and model are paired."), "Closes #279", the decisions to look at (3, 4, 6, 8, 10), a "Limits" list (`-t frigate` alone on a unit still running an older tm-control fails on the unknown `--frigate-env`, as PR 278 says for its options; comments inside a kept `model:` section don't survive `-f`; the wrong-detector path was or wasn't run with a real model), the Pi plan's results with the measured restart time, the UI screenshot of the new form at 375 px (fake mode), the Docs list from Task 7, and the "AI assistance" section with the tool, model, and effort used. Say `PUBLIC push →` before pushing, and show the maintainer the commit messages and the PR text first.
