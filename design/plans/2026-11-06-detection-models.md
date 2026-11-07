# The Detection page: Frigate models on the device, without SSH

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the control app a Detection page where an admin uploads a Frigate model (a Frigate+ pair, a package, or a local model), makes Frigate use it, downloads it as a package, and deletes it; where everyone sees which objects the running model recognises and which the device tracks; and where the Frigate+ key form now lives.

**Architecture:**
- A new `detection` module in the backend (`/api/v1/models`) treats Frigate's `model_cache` as the inventory: a model is a file directly in it plus a `.json` sidecar in Frigate+'s record shape. The module lists, hashes, uploads (one file per request, streamed from the raw body), places archive members, packages, and deletes, opening everything relative to a descriptor of `model_cache` with `O_NOFOLLOW`, as the set-secret job does for env files.
- "Use" builds the `model:` section from the sidecar, writes it through Frigate's own config API (`GET /api/config/raw`, a ruamel round-trip edit, `POST /api/config/save?save_option=saveonly`, so Frigate validates the whole config before anything is written), falls back to editing `config.yml` on disk when Frigate doesn't answer, and then restarts `frigate.service` through systemd, the way the Status page's Restart does. tm-control gains write access to Frigate's config directory for this, nothing else.
- The installer's default `model:` section becomes one dict in the role's vars, rendered by Frigate's config template and carried in the install manifest, so tm-control reads it from the manifest and nothing is duplicated.
- The UI gets a `detection` module: the page, an upload dialog with the form for a bare model file, label chips with Copy, and the `EnteredSecret` form for the Frigate+ key moved over from the Device page. Viewers get the page read-only.
- Infrastructure: the CSRF middleware admits `application/octet-stream` bodies, nginx gets one upload location with a 100 MB body limit and no request buffering, and the unit gets `ReadWritePaths={{ tmsetup_codedir }}/frigate/config`.

**Tech Stack:** Python 3.11 (FastAPI 0.162, pydantic 2, ruamel.yaml 0.19, `zipfile`/`tarfile`/`hashlib` from the standard library; no new dependency), Ansible (the tmsetup role), Jinja2, nginx, Vue 3 + Vuetify 3 + TypeScript (Vitest, `openapi-fetch`), Material for MkDocs, the dev-Pi tooling (`script/devpi/tmdev.py`). Frigate 0.18.1's behaviour is pinned from its source as noted in "What Frigate does".

**Spec:** the Detection page design of 2026-11-04 (summarised in [issue 283](https://github.com/glossyio/traffic-monitor/issues/283)), all sections; its "(maintainer)" items stand, and the "(call)" items are either kept or changed in the "Decisions" list below, which says why. Where this plan goes beyond the design, say so in the PR rather than picking silently.

**Status:** written 2026-11-06 against `feature/frigate-plus-key/279` at `fac2e57` (PR 280, which contains PR 278, PR 277, PR 269, PR 261, and `dev`). Implemented on `feature/detection-page/283`, stacked on PR 280's branch; [issue 283](https://github.com/glossyio/traffic-monitor/issues/283) tracks the work. The stacked-PR routine applies: retarget as 280 and the PRs under it merge. The page's layout was reshaped after the maintainer's review of 2026-11-06; see `2026-11-06-detection-page-layout.md`.

**Decisions made while writing this plan** (the maintainer's decisions of 2026-11-04 are in the design; these are calls made here on 2026-11-06, open to change):
1. **Frigate is restarted through systemd after a save, not by Frigate itself.** The design had `save_option=restart` (Frigate exits 143 and systemd starts it again). PR 280's decision 12 now counts two of Frigate's own restarts within 120 s as a failure loop, so an admin picking a model, then picking the installer's default a minute later, would turn the Services row yellow until a hand restart. A restart through `restart_or_log("frigate.service")` is counted as a hand restart, resets `NRestarts`, and is the same path the disk fallback needs anyway. `save_option` is any value but `restart` (Frigate's handler restarts only on that exact word; `saveonly` is used for readability). Measured on the bench for PR 280: a systemd restart of Frigate takes about 16 s to a new invocation and about 20 s until Frigate answers.
2. **Raw-body uploads mean the CSRF middleware admits `application/octet-stream`.** `core/csrf.py` refuses every non-GET body that isn't `application/json`. `application/octet-stream` is not a CORS-safelisted type either (a cross-origin `fetch` with it is preflighted and an HTML form can't send it), so admitting it keeps the check's reasoning: a body type a cross-site page can't produce, plus the Origin check. The UI client sets JSON only when a request has no Content-Type already.
3. **The installer's default `model:` section is one dict in the role's vars, `tmsetup_frigate_coral_model`, carried in the manifest as `frigate.coral_model`.** The design proposed a literal in tm-control pinned to the template by a test in `script/tests`; that test would have to import tm-control from the role's suite. A static dict doesn't suffer from the problem that ruled out rendering the section in the manifest (the probe results are absent under the tags that write it): which detector applies is decided when the section is used, from the device's detector type. The template renders the dict for the Coral branch, so the two can't drift, and `contracts.py`'s `CORAL_MODEL_FILE` literal (PR 280) goes, read from the manifest instead.
4. **The running model's label map comes from Frigate's running config.** `GET /api/config` puts each detector's merged label map at `detectors.<name>.model.labelmap` (checked on the Coral bench unit on 2026-11-06: 91 entries for the installer's model). So "what the model recognises" is right for every model Frigate runs, Frigate's built-in default included, and the design's section 7 fallbacks (the sidecar, the installer's labels file) are used only while Frigate doesn't answer. Nothing reads `/labelmap.txt` from the image.
5. **The detector type is read in this order:** Frigate's running config (`detectors`, the first entry's `type`); otherwise Frigate's `config.yml` on disk (`detectors`, the first entry's `type`; `cpu` when the file parses and has no `detectors` key, as Frigate defaults); otherwise unknown, and Use is refused with a 409 rather than guessing. The manifest's probe settings don't say what was found.
6. **The disk fallback stays** (the design's open question 2): when Frigate doesn't answer, the same edit goes to `config.yml` through `RoundTripFile` (backup, atomic, owner kept) and the restart follows. It's the one route out of a bad pick without SSH, which PR 280's docs promised as "a planned update", and with decision 1 both routes end in the same restart; only who validated the text differs. `ReadWritePaths` therefore names Frigate's config directory, not `model_cache` alone.
7. **An upload is an archive by its name and its first bytes.** `.zip` must start with `PK\x03\x04`, `.tar.gz` and `.tgz` with `\x1f\x8b`; a mismatch is refused. Any other name is a sidecar when it ends in `.json`, else a model file. The design said "told apart by its first bytes" alone; a model file's first four bytes are arbitrary (a TFLite file starts with a flatbuffer offset), so the name decides and the magic confirms.
8. **A package is written as a temporary file in tm-control's state directory and deleted after it's sent**, with `ZIP_STORED` (no compression: the files are already compressed or binary, and a Pi shouldn't deflate 100 MB per download). `PrivateTmp=yes` makes `/tmp` private but possibly small; the state directory is on the same disk as the models.
9. **Fake mode runs the real inventory against `.tm-control-fake/model_cache`**, seeded by `fake-reset` with two synthetic pairs, and a fake Frigate whose "running model" is a file in that directory that Use rewrites. The fixture manifest's `codedir` is `/opt/traffic-monitor`, which a laptop doesn't have.
10. **No overwrite on upload** (the design's open question 1 stands): a name already in use is refused; the admin deletes first.
11. **`GET /models` is for every signed-in user; `GET /secrets` stays admin-only.** The page asks for the secrets only when the user is an admin; a viewer sees the Frigate+ section's text without the form.
12. **One Use at a time:** while `frigate.service` is `activating` or `deactivating`, Use and the default answer 409 `restarting`. Nothing else is locked; a second upload during a restart is fine.
13. **The sidecar the form writes** has `name` equal to the file name, `supportedDetectors` equal to the device's detector type, no `id`, no `trainDate`, and the eight fields Frigate reads. So a model made from the form is always a local model, never mistaken for a Frigate+ pair.
14. **The SHA-256 of each file is cached in memory by name, size, and mtime**, so `GET /models` doesn't rehash 100 MB on every poll.

**What Frigate 0.18.1 does** (pinned from its source on 2026-11-06, `frigate/api/app.py`, `frigate/detectors/detector_config.py`, `frigate/const.py`, `frigate/plus.py`; the internal port's behaviour checked on the Coral bench unit the same day):
- `GET /api/config/raw` and `POST /api/config/save` carry `require_role(["admin"])`; the internal port 5000 answers 200 to both with no header, as PR 280's bench `POST /api/restart` did. `/config/raw` returns the file's text as a `JSONResponse`, so the body is a JSON string literal (`"# see https…"`), to be `json.loads`-ed. `/config/save` takes `save_option` as a query parameter and the body as `text/plain`; an empty body is a 400; it parses the text with ruamel and `FrigateConfig.parse_yaml` before writing; a `ValidationError` is a 400 whose JSON `message` starts with `Your configuration is invalid.\nSee the official documentation at docs.frigate.video.` followed by one `Line N: key -> path - message` per error; any other exception is a 400 whose message holds a traceback; on success it opens the config file with `"w"` (same inode, so the owner stays) and answers 200; only `save_option == "restart"` calls `restart_frigate()`.
- `GET /api/config` has `detectors.<name>.model.{path, width, height, input_tensor, input_pixel_format, input_dtype, model_type, labelmap_path, labelmap}` with `labelmap` the merged map (keys are decimal strings), `objects.track` at the top level and under each camera, `plus.enabled`, and a top-level `model` with `path` and the rest. For a `plus://` model Frigate rewrites `path` to `/config/model_cache/<id>` before this is answered.
- `ModelConfig` has `extra="forbid"`: `model:` admits only `path`, `labelmap_path`, `width`, `height`, `labelmap`, `attributes_map`, `input_tensor` (`nchw|nhwc|hwnc|hwcn`), `input_pixel_format` (`rgb|bgr|yuv`), `input_dtype` (`float|float_denorm|int`), `model_type` (`dfine|rfdetr|ssd|yolox|yolonas|yolo-generic`). `check_and_load_plus_model` reads `width`, `height`, `inputShape`, `pixelFormat`, `type`, optional `inputDataType`, and `labelMap` (keys cast to int) from `<id>.json`, downloads only a missing file, and raises `ValueError("Model does not support detector type of <type>")` when `supportedDetectors` lacks the detector. `MODEL_CACHE_DIR = "/config/model_cache"`.

**Where PR 280 and the PRs under it left things that this plan touches:**
- Backend layout: `app.py` mounts each `modules.MODULES` entry's router under `API_PREFIX = "/api/v1"` and adds `CsrfMiddleware`; `modules/__init__.py` has `Module(id, router, root_router=None, check_groups=())` and `MODULES` (auth, setup, account, jobs, secrets, status, services, apps, hardware, system, time). Writes take `admin: User = Depends(require_admin)` (`modules/auth/deps.py`; `current_user` for any user). `core/errors.py::ApiError(status, code, message, detail=None)`. `Audit(app_state.state).record(user_id, action, detail=None)` (`core/auth.py`); existing actions are `secrets.set`, `services.restart`, and so on, with the object in `detail`. `core/csrf.py::_problem` refuses a Content-Type other than `application/json` ("not JSON"); `tests/test_api_csrf.py::test_post_with_another_content_type_is_forbidden` pins `text/plain`, `multipart/form-data`, and an empty type.
- `modules/secrets/router.py` is the pattern for a module with a dataclass table, pydantic response models, `_start` with an audit row and a fake-mode side effect; `GET /secrets` is admin-only and the Frigate+ row is `FRIGATE_PLUS_API_KEY` with `restarts=("frigate.service",)`.
- `adapters/httpjson.py`: `get(url, headers, timeout) -> (status, bytes)` and `get_json`, loopback-only, `TIMEOUT = 3`, `MAX_BODY = 8 MiB`, no proxy. `adapters/frigate.py`: `BASE = "http://127.0.0.1:5000/api"`, `version()`, `config()`, `stats()`, `config_file(codedir) -> ConfigRead`. `adapters/yamlfile.py`: `read_config(path) -> ConfigRead(data, problem, line, column)`, `RoundTripFile(path, mapping_indent=2)` with `.data`, `.save()` (backup `<name>.<stamp>.bak`, `write_atomic`, keeps mode, keeps the owner only as root, `ConcurrentEditError`), `write_atomic(path, text)`.
- `modules/services/units.py`: `restart_or_log(unit)` (a `BackgroundTasks` task in `services/router.py::restart`, which audits `services.restart` first), `unit_states(context)`, `restart_causes`, `last_restart_cause`, `restart_loop`, `RESTART_LOOP_SPACING = 120`, `Unit` with `restarts_itself_with="143"` for Frigate. `adapters/systemd.py`: `restart_unit(name)` (`systemctl restart --no-block`), `show_unit`, `show_units`.
- `modules/apps/probes.py`: `frigate_version`, `frigate_config`, `frigate_stats`, `frigate_config_file`, `frigate_journal`, `frigate_safe_mode`, `mapping`. `modules/apps/contracts.py`: `PLUS_SCHEME`, `MODEL_ID`, `CORAL_MODEL_FILE = "yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite"` (pinned to the role by `tests/test_contract_checks.py::test_the_installers_model_file_matches_the_role`), `SET_THE_KEY = Fix(kind="link", text="Set the key", href="/device#tokens-and-keys")`, `WAYS_OUT`, `model_path`, `plus_model_id`, `model_cached(codedir, model_id)`, `frigate_plus(context)` with its rule 3 wording "the installer's model" when the path ends with `CORAL_MODEL_FILE`.
- `core/manifest.py`: `Manifest(manifest_version, tm_version, git, installing_user, codedir, codeowner, components, options, revproxy_locations, probes: Probes(detectors, radar_paths, hevc_device), homepage)`, unknown keys ignored, `load_manifest(path)`. The role builds it in `tasks/tm-control_service.yml` ("Collect the install manifest", a `set_fact`, written root:codegroup 0640 to `{{ tmsetup_etc_dir }}/manifest.json`); `tests/fixtures/manifest.json` is fake mode's and `script/tests/test_tm_control_install.py::test_manifest_has_the_same_fields_as_tm_controls_fixture` keeps the two in step. `core/settings.py`: `Settings(state_dir, runtime_dir, secrets_dir, manifest_path, host, port, fake, eula_path, setup_code_file)`, `FAKE_DIR = ".tm-control-fake"` (state at `<fake_dir>/state`). `fake.py::reset(settings)` seeds fake mode; `FAKE_UNIT_STATES` has Frigate `failed`.
- Role: `vars/main.yml` has `tmsetup_frigate_coral_model_file`; `container/frigate/config/config.yml.j2` lines 40 to 55 render `tmsetup_frigate_model_keep` (PR 280's carry-over) or, with a Coral, the literal section `model_type: yolo-generic`, `width: 512`, `height: 512`, `path: /config/model_cache/{{ tmsetup_frigate_coral_model_file }}`, `labelmap_path: /config/labels-coco17.txt`; `tasks/frigate_setup.yml` creates `model_cache` (codeowner:codegroup 0750), downloads the Coral model and `labels-coco17.txt` into `{{ tmsetup_codedir }}/frigate/config/` as root (0644, root-owned), and renders `config.yml` codeowner:codegroup 0640. On the bench unit: `frigate/config` and `model_cache` are the code owner's, `config.yml` is the code owner's 0640, the Coral model file is root's 0644. `templates/tm-control/tm-control.service.j2`: `User={{ tmsetup_codeowner }}`, `ProtectSystem=strict`, `PrivateTmp=yes`, `StateDirectory=tm-control`, no `ReadWritePaths`; `script/tests/test_tmsetup_templates.py::test_tm_control_has_no_write_paths_outside_its_state` (line 788) and `test_tm_control_service_has_the_video_group` (769) assert that, and `tm_control_unit()` (753) renders without `tmsetup_codedir`. `tmsetup_tm_control_polkit.units` includes `frigate.service`. nginx: `container/revproxy/tm/locations/tm-control-api.conf.j2` has `location /api/` (proxy to `127.0.0.1:8090/api/`, `proxy-common`, `proxy_buffering off`, `X-TM-Required-Role ""`), the `/api/v1/auth/verify` 404, and `/logout`; no `client_max_body_size` anywhere (nginx's 1 MB default applies); `test_api_and_logout_are_proxied_to_tm_control_on_loopback` (274) pins the file.
- UI: `src/modules/index.ts` (`NavItem`, `Module`, `MODULES = [home, status, device, time, account, auth, setup]` in menu order), `router.ts` (`meta.adminOnly`), `modules/device/index.ts` as the module pattern. `DevicePage.vue`: `SECRETS_ID = 'tokens-and-keys'`, `loadSecrets()` (`GET /api/v1/secrets`), the `v-expansion-panels` section rendering `<EnteredSecret v-for … @changed="loadSecrets">` for every row, `copyText` (lines 189 to 212, `navigator.clipboard` with an `execCommand` fallback), the diagnostics download (150 to 177: `parseAs: 'text'`, `Content-Disposition`, a Blob and an `<a download>`). `components/EnteredSecret.vue` (`secret: SecretState` prop, `changed` emit), `components/ConfirmDialog.vue` (`v-model`, `title`, `text`, `confirmText`, `confirm`), `components/jobs.ts::followJob`, `components/CheckList.vue` renders link fixes as `router-link`. `src/api/client.ts`'s `errors` middleware sets `Content-Type: application/json` on every non-GET; `tests/fake-api.ts` `JSON.parse`s every non-GET body; `tests/mount.ts` has `mountApp`, `mountAlone`, `field`, `button`, `click`, `clickInDialog`, `dialogText`; `tests/device-page.spec.ts` has `FOUR_SECRETS`. The committed `src/api/openapi.json` is pinned by `backend/tests/test_openapi_document.py` and regenerated with `python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json && npm run api:generate`. `tm-control/ui/README.md` has the design notes (Color, Type, Layout, Copy, Principles) and the Tokens and keys note.
- Tests: `tests/conftest.py` (`settings`, `client`, `claimed_client`, `login`, `device_client`, `FakeApps`/`apps` with `codedir`, `answers`, `json()`, `edit_json()`, `context()`, `ADMIN`, `VIEWER`, `ORIGIN`), `tests/fixtures/frigate_api_config.json`, `tests/placeholders.py::PLACEHOLDER_KEY`. 1013 backend tests, 478 in `script/tests`, about 115 UI cases.
- Docs: `docs/use/` (`control-app.md`, `device-health.md` with "Tokens and keys" and the "Set the key" sentence at line 45, `home-page.md`, `system-admin.md`); `docs/configuration/frigate-config.md` "Better models" (Enter the key, Submit snapshots, Use a model, A device without internet, A model of your own, What the installer keeps, The Frigate+ check, If Frigate stops over a model, closing with "A planned update to the control app will let you change the model while Frigate is down."); `docs/development/tm-control.md` (Backend layout, Root jobs and polkit, Status checks, What the sandbox allows, Run it on a laptop, Add a module); `mkdocs.yml` nav "Use the device" (home-page, control-app, device-health, Dashboards, frigate-config, system-admin); the `llmstxt` section already lists `use/*.md`. Links to `#tokens-and-keys` that mean the Frigate+ key: `frigate-config.md` lines 69 and 153, `device-health.md`.
- Device tests: `script/devpi/tests/test_web.py` (`admin_session`, `expect`, `codedir`, `CONFIG_CHECKS`), `test_services.py` (polkit and unit tests), `test_disruptive.py` (`invocation`, `not_restarted`, `wait_until_ready`, `set_secret`), `devpi_checks.py`. The inventory's `ai` is `edgetpu_pci` on the Coral unit and `hailo8` on the Hailo unit.

## Global Constraints

- No secret value in any output, and no sidecar's `verifiedCounts` in any API answer, log line, or test name. The maintainer's real sidecar stays out of every repo; tests and fake mode use `tests/fixtures/model_sidecar.json`, a synthetic record with made-up camera names (Task 3 writes it).
- tm-control writes only inside `model_cache` and Frigate's `config.yml` (plus its own state directory), always relative to a directory descriptor opened `O_DIRECTORY|O_NOFOLLOW`, with `O_NOFOLLOW` on every file and `O_EXCL` on every temporary name; nothing is written through a name from a request until `valid_name` passes.
- Caps: 100 MB per request and per model file (`MODEL_FILE_MAX`), 2 MB per sidecar (`SIDECAR_MAX`), 3 archive members, and a refusal when free space after the upload would fall under `FREE_SPACE_MIN` (512 MB, the Device check's problem threshold).
- The role: task names `TMSetup - <Component> - <Action>`, `tmsetup_` variables, FQCN modules, `become: true` per task, two-space YAML. Nothing here rebuilds an image or changes a pinned version.
- Docs follow "Writing docs" in `docs/development/contributing.md`; every new page is in `nav:`; `mkdocs build --strict` passes. Don't name later features; say "planned" at most. Nothing public names a device.
- Commits end with the trailer block from the public repo's CLAUDE.md, not `Co-Authored-By`. Never run `tmsetup.sh` on a dev machine. Say `PUBLIC push →` before any push.
- Off-device checks before the PR: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests`, `cd tm-control/ui && npm test && npm run build`, the Ansible syntax check, the Jinja parse of every `.j2`, `bash -n script/tmsetup.sh`, `mkdocs build --strict`, and the regenerated `openapi.json` committed.

## Review Focus

1. **An archive member with a path, a link, or a device entry** (`../x`, `model_cache/../../etc/x`, a symlink named `m.tflite`): nothing is written anywhere, the archive is refused. Task 6's `test_archive_members_with_paths_links_or_devices_are_refused`.
2. **A body that runs past its cap, or past its `Content-Length`**: the temporary file is removed, no model appears, the answer is 413. Task 5's `test_a_body_over_the_cap_is_cut_off_and_leaves_nothing`.
3. **Use with a sidecar built for another detector**, Frigate answering or not: refused with both types named, and neither Frigate's API nor `config.yml` sees a write. Task 7's `test_a_model_for_another_detector_is_refused_before_any_write`.
4. **Frigate refuses the save** (a 400 with its message): nothing written to disk, no restart queued, the page gets Frigate's lines without the two header lines, and never a key. Task 7's `test_frigates_refusal_is_shown_and_nothing_is_restarted`.
5. **One bad file in `model_cache`** (a sidecar that isn't JSON, a file the code owner can't read, a 300-character name, a dangling symlink): the rest of the inventory still lists, with that entry absent or marked incomplete, and `GET /models` is 200. Task 3's `test_one_bad_file_does_not_blank_the_inventory`.
6. **Delete of the running model while Frigate is down**: the running model is then known from `config.yml` on disk, and the delete is still a 409. Task 5's `test_the_running_model_cannot_be_deleted_even_when_frigate_is_down`.

---

### Task 1: The installer's default model section is one dict, in the template and the manifest

**Files:**
- Modify: `script/ansible/roles/tmsetup/vars/main.yml` (`tmsetup_frigate_coral_model`)
- Modify: `container/frigate/config/config.yml.j2` (the Coral branch)
- Modify: `script/ansible/roles/tmsetup/tasks/tm-control_service.yml` (the manifest fact)
- Modify: `tm-control/backend/tm_control/core/manifest.py` (`FrigateInfo`, `Manifest.frigate`)
- Modify: `tm-control/backend/tests/fixtures/manifest.json`
- Modify: `tm-control/backend/tm_control/modules/apps/contracts.py` (`CORAL_MODEL_FILE` goes; rule 3 reads the manifest)
- Test: `script/tests/test_tmsetup_templates.py`, `script/tests/test_tm_control_install.py`, `tm-control/backend/tests/test_manifest.py` (or the file that tests `load_manifest` today), `tests/test_contract_checks.py`

**Interfaces:**
- Produces, in `vars/main.yml`, right after `tmsetup_frigate_coral_model_file`:
  ```yaml
  # The model section Frigate's config gets on a device with a Coral; tm-control puts it back from the manifest.
  tmsetup_frigate_coral_model:
    model_type: yolo-generic
    width: 512
    height: 512
    path: '/config/model_cache/{{ tmsetup_frigate_coral_model_file }}'
    labelmap_path: /config/labels-coco17.txt
  ```
  The template's Coral branch becomes `model:` followed by `{{ tmsetup_frigate_coral_model | to_nice_yaml(indent=2, sort_keys=False) | indent(2, first=True) -}}`, as the kept-section branch renders. The manifest fact gains `frigate: { coral_model: '{{ tmsetup_frigate_coral_model }}' }` after `options`.
- Produces, in `manifest.py`: `@dataclass(frozen=True) class FrigateInfo: coral_model: dict | None = None` and `Manifest.frigate: FrigateInfo = FrigateInfo()` (an older manifest without the key loads with `None`). The fixture manifest gets the same `frigate` object with the five keys and the Coral file name.
- Produces, in `contracts.py`: `installer_model_file(manifest) -> str | None` (the base name of `manifest.frigate.coral_model["path"]`, or None); rule 3's wording test uses it in place of `CORAL_MODEL_FILE`, which is removed with its test.

- [ ] **Step 1: Write the failing tests**

`test_tmsetup_templates.py`: `test_the_coral_default_section_renders_from_the_vars_dict` (render `config.yml.j2` with `CORAL_PCI`, `tmsetup_frigate_coral_model_file`, and `tmsetup_frigate_coral_model` loaded from the vars file with its `path` expanded to `/config/model_cache/<CORAL_FILE>`, as Ansible's lazy templating would; `config["model"]` equals that dict, keys in the vars file's order). Also assert the vars file's dict has exactly the five keys and its `path` names `tmsetup_frigate_coral_model_file`. The two existing Coral tests pass the dict too (StrictUndefined). `test_tm_control_install.py`: extend the manifest-fields test with `frigate.coral_model` and add `test_the_manifest_carries_the_coral_model_section` (the fact's `frigate.coral_model` evaluates to the vars dict).

Backend: `test_an_older_manifest_without_frigate_loads_with_no_coral_model` and `test_the_fixture_manifest_names_the_coral_model` (`installer_model_file(manifest) == "yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite"`). In `test_contract_checks.py`, replace `test_the_installers_model_file_matches_the_role` with `test_the_installers_model_comes_from_the_manifest` (the fixture's path gives rule 3's "the installer's model" wording; a manifest with `coral_model: None` gives "a local model" for the same path).

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest script/tests/test_tmsetup_templates.py script/tests/test_tm_control_install.py tm-control/backend/tests -q -k "coral or manifest or installers_model"`
Expected: FAIL

- [ ] **Step 3: Add the dict, change the template branch, extend the fact, the model, the fixture, and `contracts.py`.** Keep the template's rendered YAML equal in value to today's (the order of the five keys as listed).

- [ ] **Step 4: Run the role tests, the backend suite, the syntax check, and the Jinja parse**

Run:
```bash
python -m pytest script/tests tm-control/backend/tests -q
(cd script/ansible && ansible-playbook -i localhost setup.yml --syntax-check </dev/null)
python -c 'import sys,jinja2; e=jinja2.Environment(); [e.parse(open(f).read(), filename=f) for f in sys.argv[1:]]' $(git ls-files '*.j2')
```
Expected: PASS, "playbook: setup.yml", no output.

- [ ] **Step 5: Commit**

```bash
git add script/ansible/roles/tmsetup/vars/main.yml container/frigate/config/config.yml.j2 script/ansible/roles/tmsetup/tasks/tm-control_service.yml tm-control/backend script/tests
git commit -m "Carry the installer's Coral model section in the manifest"
```

### Task 2: tm-control may write Frigate's config directory, nginx streams model uploads, and bodies may be octet-stream

**Files:**
- Modify: `script/ansible/roles/tmsetup/templates/tm-control/tm-control.service.j2` (`ReadWritePaths`, the header comment)
- Modify: `container/revproxy/tm/locations/tm-control-api.conf.j2` (the upload location)
- Modify: `tm-control/backend/tm_control/core/csrf.py` (`BODY_TYPES`)
- Modify: `docs/development/tm-control.md` ("What the sandbox allows"), `CLAUDE.md` (the sandbox sentence)
- Test: `script/tests/test_tmsetup_templates.py`, `tm-control/backend/tests/test_api_csrf.py`

**Interfaces:**
- Produces: the unit line `ReadWritePaths={{ tmsetup_codedir }}/frigate/config` after `ProtectSystem=strict`, with a comment: Frigate's `model_cache` and `config.yml`, for the Detection page; the header comment says the unit writes its state and runtime directories and Frigate's config directory. In the nginx file, before `location /api/`:
  ```nginx
  # Model uploads for the Detection page: up to 100 MB, streamed to tm-control as they arrive
  location ^~ /api/v1/models/upload/ {
      include tm/snippets/proxy-common.conf;
      proxy_pass http://127.0.0.1:8090/api/v1/models/upload/;
      proxy_set_header X-TM-Required-Role "";
      proxy_buffering off;
      proxy_request_buffering off;
      client_max_body_size 100m;
  }
  ```
  In `csrf.py`: `BODY_TYPES = frozenset({"application/json", "application/octet-stream"})`, the problem string "not JSON or a byte stream", and the module docstring saying why octet-stream is as safe (not CORS-safelisted, so a cross-site page can't send it without a preflight).

- [ ] **Step 1: Write the failing tests**

`test_tmsetup_templates.py`: `tm_control_unit()` passes `tmsetup_codedir="/opt/traffic-monitor"`; `test_tm_control_has_no_write_paths_outside_its_state` becomes `test_tm_control_writes_only_its_state_and_frigates_config` (exactly one `ReadWritePaths=` line, equal to `/opt/traffic-monitor/frigate/config`); `test_model_uploads_stream_to_tm_control_with_a_larger_body_limit` (the rendered API location file has the `^~ /api/v1/models/upload/` block with `client_max_body_size 100m`, `proxy_request_buffering off`, a `proxy_pass` to `127.0.0.1:8090`, and no other `client_max_body_size` in any location file). `test_api_csrf.py`: `test_an_octet_stream_body_from_this_origin_is_allowed` and keep `text/plain`, multipart, and empty refused.

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest script/tests/test_tmsetup_templates.py tm-control/backend/tests/test_api_csrf.py -q`
Expected: FAIL

- [ ] **Step 3: Make the three changes and the two doc sentences.** `tm-control.md`'s sandbox list: "writes its state and runtime directories and Frigate's config directory (`ReadWritePaths`), for the models the Detection page manages"; `CLAUDE.md`'s sandbox sentence likewise.

- [ ] **Step 4: Run the role tests, the backend suite, and `nginx -t` if Podman is available**

Run: `python -m pytest script/tests tm-control/backend/tests -q` (and `script/tests/test_nginx_config_parses.py` runs when Podman is there).
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add script/ansible/roles/tmsetup/templates/tm-control/tm-control.service.j2 container/revproxy/tm/locations/tm-control-api.conf.j2 tm-control/backend docs/development/tm-control.md CLAUDE.md script/tests
git commit -m "Let tm-control write Frigate's config directory and stream model uploads"
```

### Task 3: The inventory: names, sidecars, hashes, and what's in `model_cache`

**Files:**
- Create: `tm-control/backend/tm_control/modules/detection/__init__.py` (`module = Module("detection", router)`, registered in `modules/__init__.py` after `secrets`)
- Create: `tm-control/backend/tm_control/modules/detection/inventory.py`
- Create: `tm-control/backend/tests/fixtures/model_sidecar.json`
- Test: `tm-control/backend/tests/test_detection_inventory.py`

**Interfaces:**
- Produces, in `inventory.py`:
  - `NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")`, `PLUS_ID = re.compile(r"[0-9a-f]{32}")`, `MODEL_FILE_MAX = 100 * 1024 * 1024`, `SIDECAR_MAX = 2 * 1024 * 1024`, `SIDECAR = ".json"`.
  - `valid_name(name: str) -> bool`: `NAME.fullmatch`, not ending in `.json`, not `.` or `..`.
  - `class SidecarError(ValueError)` with fixed messages: "The sidecar isn't a JSON object.", "The sidecar lacks <field>.", "The sidecar's <field> has the wrong type.", "The sidecar's supportedDetectors is empty.", "The sidecar's labelMap keys must be decimal strings."
  - `@dataclass(frozen=True) class Sidecar: id: str | None; name: str | None; trained_at: str | None; type: str; detectors: tuple[str, ...]; width: int; height: int; input_shape: str; pixel_format: str; input_dtype: str | None; labels: tuple[str, ...]` (labels in label-map index order). `parse_sidecar(data: bytes) -> Sidecar` checks exactly the eight fields the design lists (`inputDataType` optional), `bool` is not an `int`, every other field is ignored, `verifiedCounts` is never kept.
  - `@dataclass(frozen=True) class ModelFile: name: str; size: int; sha256: str | None` (None while the hash isn't known yet, see below).
  - `@dataclass(frozen=True) class Model: name: str; kind: Literal["frigate_plus", "local", "installer_default"]; sidecar: Sidecar | None; files: tuple[ModelFile, ...]; complete: bool; problem: str | None` (a sidecar's `SidecarError` message, for an incomplete pair whose `.json` is bad).
  - `@dataclass(frozen=True) class InstallerDefault: section: dict; file: str; labels_file: Path | None`; `installer_default(manifest, codedir) -> InstallerDefault | None` from `manifest.frigate.coral_model` (`file` is the path's base name; `labels_file` is `host_path(codedir, section["labelmap_path"])`).
  - `host_path(codedir, container_path: str) -> Path | None`: `/config/<rest>` → `<codedir>/frigate/config/<rest>`; None for any other prefix or a `rest` with `..`.
  - `model_cache_dir(settings, manifest) -> Path`: `<codedir>/frigate/config/model_cache`, or `settings.state_dir.parent / "model_cache"` in fake mode.
  - `open_cache(path: Path) -> int` (`O_DIRECTORY|O_NOFOLLOW|O_RDONLY`; the caller closes), `open_in(dir_fd, name, flags, mode=0o644) -> int` (adds `O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK`), `stat_in(dir_fd, name) -> os.stat_result | None` (`follow_symlinks=False`; None when missing).
  - `kind_of(name, sidecar) -> str`: `frigate_plus` when `PLUS_ID.fullmatch(name)` and `sidecar.id == name`, else `local`.
  - `HASHES: dict[tuple[str, int, int], str]` and `sha256_in(dir_fd, name, stat) -> str` (keyed by name, size, `st_mtime_ns`; reads in 1 MiB blocks).
  - `inventory(cache: Path, installer: InstallerDefault | None) -> list[Model]`: regular files directly in the cache, by name; a `.json` is the sidecar of the name before it; every other file with a valid name is a model entry; files with invalid names, directories, and symlinks are skipped; a pair is `complete` when both exist and the sidecar parses; the installer's file, when present, is listed first as `installer_default` with no sidecar, `complete=True`, and its one file. A file that can't be read gives its entry `sha256=None` and `problem="The file can't be read."` rather than an exception. Sorted: installer's default, then names ascending.

- [ ] **Step 1: Write the fixture and the failing tests**

`model_sidecar.json`: `id` `0123456789abcdef0123456789abcdef`, `name` "Test site yolov9", `isBaseModel` false, `trainDate` `2026-10-01T12:00:00Z`, `baseModel` `yolov9-s`, `type` `yolo-generic`, `supportedDetectors` `["edgetpu"]`, `width` 320, `height` 320, `inputShape` `nhwc`, `pixelFormat` `rgb`, `labelMap` `{"0": "person", "1": "bicycle", "2": "car"}`, `verifiedCounts` `{"front_door_cam": 12, "driveway_cam": 3}`.

```python
# tests/test_detection_inventory.py, with a cache(tmp_path) fixture that creates model_cache, SIDECAR = fixture bytes,
# and helpers pair(cache, name, sidecar=SIDECAR, size=4096) writing <name> of `size` zero bytes and <name>.json
def test_valid_names(): ...               # ok: "a", "x.tflite", "0123…ef"; refused: ".hidden", "a.json", "..", "a/b", "a" * 129, ""
def test_parse_sidecar_keeps_the_eight_fields_and_drops_the_rest(): ...   # labels == ("person","bicycle","car"); no verifiedCounts attribute
def test_parse_sidecar_refuses_each_missing_or_mistyped_field(): ...      # parametrized: each required field removed or mistyped, width True, labelMap {"a": "x"}, empty detectors, a list document
def test_a_frigate_plus_pair_is_told_from_a_local_model_by_the_id(): ...  # the fixture id as name -> frigate_plus; "mine.tflite" with the same sidecar -> local; the id as name with id "x" in the sidecar -> local
def test_inventory_lists_pairs_halves_and_the_installers_default(): ...   # a pair, a bare model, a bare sidecar, the installer's file: kinds, complete flags, order
def test_subdirectories_symlinks_and_bad_names_are_skipped(): ...         # hailo/ dir, a symlink to the pair's file, ".DS_Store", a 200-char name
def test_one_bad_file_does_not_blank_the_inventory(): ...                  # a sidecar "bad.tflite.json" holding "{", a model file chmod 000 (skip as root): the good pair still listed; bad has problem set
def test_hashes_are_cached_by_name_size_and_mtime(): ...                  # same stat -> one read (monkeypatch open_in counter); touch -> rehash
def test_host_path_stays_under_frigates_config(): ...                     # /config/labels-coco17.txt -> codedir/frigate/config/labels-coco17.txt; /config/../x -> None; /etc/x -> None
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_detection_inventory.py -q`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement `inventory.py` and the module skeleton** (a `router.py` with an empty `APIRouter(prefix="/models", tags=["models"])` so the module registers; Task 4 fills it).

- [ ] **Step 4: Run the file and the backend suite**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS (`test_openapi_document` unchanged, since the router has no route yet).

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend
git commit -m "Read Frigate's model_cache as an inventory of model pairs"
```

### Task 4: `GET /models`: the detector, the running model, the inventory, and the label lists

**Files:**
- Create: `tm-control/backend/tm_control/modules/detection/picker.py` (the read half: `detector_type`, `running_model`; Task 7 adds the write half)
- Create: `tm-control/backend/tm_control/modules/detection/labels.py`
- Modify: `tm-control/backend/tm_control/modules/detection/router.py`
- Modify: `tm-control/backend/tm_control/fake.py` (`seed_model_cache`, `FAKE_RUNNING_MODEL`)
- Modify: `tm-control/ui/src/api/openapi.json` (regenerated), `tm-control/ui/src/api/schema.d.ts`
- Test: `tm-control/backend/tests/test_api_models.py`, `tests/test_detection_picker.py`

**Interfaces:**
- Consumes: `inventory`, `installer_default`, `model_cache_dir`, `Model`, `Sidecar` (Task 3); `frigate.config()`, `frigate.version()`, `frigate.config_file(codedir)`; `probes.mapping`.
- Produces, in `picker.py`: `detector_type(frigate_config: dict | None, config_file: ConfigRead) -> str | None` (decision 5); `@dataclass(frozen=True) class Running: name: str | None; kind: Literal["frigate_plus", "local", "installer_default", "frigate_default"] | None; path: str | None; source: Literal["frigate", "config_file"] | None`; `running_model(frigate_config, config_file, installer: InstallerDefault | None, models: list[Model]) -> Running`: from Frigate's running config, the first detector's `model.path` (falling back to the top-level `model.path`); from the file, `model.path` with `plus://<id>` read as `/config/model_cache/<id>`; `name` is the base name when the path is directly under `/config/model_cache/`, matched against `models` for its `kind` (`installer_default` when it equals the installer's file; `frigate_default` when the path is None, empty, or elsewhere); a `name` under `model_cache` with no inventory entry keeps the name with `kind="local"`.
- Produces, in `labels.py`: `recognised(frigate_config, running: Running, models, installer) -> tuple[list[str] | None, str | None]`: Frigate's first detector's `model.labelmap` sorted by integer key, source `"frigate"`; else the running model's sidecar labels, source `"sidecar"`; else, for the installer's default, its labels file one label per line (blank lines dropped), source `"labels_file"`; else `(None, None)`. `tracked(frigate_config) -> list[str]`: the top-level `objects.track` followed by each camera's entries not yet seen, in order; `[]` without Frigate.
- Produces, in `router.py`, pydantic models `ModelFileOut(name, size, sha256: str | None)`, `ModelOut(name, kind, title: str, trained_at: str | None, type: str | None, detectors: list[str], width: int | None, height: int | None, files: list[ModelFileOut], complete: bool, running: bool, usable: bool | None, deletable: bool, problem: str | None)` (`title` is the sidecar's `name` or the file name; `usable` is `detector in detectors`, None when the detector is unknown or the entry has no sidecar; `deletable` is not running and not the installer's), `RunningOut(name, kind, source)`, `LabelsOut(recognised: list[str] | None, source: str | None, tracked: list[str])`, `ModelsState(detector: str | None, frigate_answers: bool, running: RunningOut, models: list[ModelOut], labels: LabelsOut)`, and `GET /models` (`current_user`) answering it. Also `_state(request) -> tuple[Settings, Manifest, Path]` and `_frigate(request) -> tuple[dict | None, ConfigRead]` helpers Tasks 5 to 7 reuse; in fake mode `_frigate` answers the fixture `frigate_api_config.json` with the first detector's `model.path` set to the fake running model's path (decision 9).
- Produces, in `fake.py`: `FAKE_RUNNING_MODEL = "running-model"`; `seed_model_cache(settings)` called by `reset`: creates `<fake_dir>/model_cache`, writes the fixture sidecar's pair (`0123…ef` as 4096 zero bytes and its `.json`) and `mine.tflite` (2048 bytes) with the same sidecar minus `id` and `name` "My model", and `running-model` holding `0123…ef`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_detection_picker.py
def test_detector_type_prefers_frigates_answer_then_the_file_then_cpu(): ...   # answer edgetpu; file hailo8l; file without detectors -> cpu; unreadable file -> None
def test_running_model_from_frigate_names_the_pair_and_its_kind(): ...        # path /config/model_cache/<id> -> frigate_plus; the installer's file -> installer_default; /cpu_model.tflite -> frigate_default
def test_running_model_from_the_file_reads_plus_paths(): ...                   # plus://<id> -> name id, source config_file
def test_recognised_prefers_frigates_merged_labelmap(): ...                    # 91-entry map sorted by int key; without Frigate, the sidecar; installer default -> labels file
def test_tracked_is_the_ordered_union_of_global_and_camera_lists(): ...

# tests/test_api_models.py (claimed_client is fake mode with temp directories; a `seeded` fixture calls fake.seed_model_cache(settings), so the cache is <state_dir>/../model_cache under tmp_path)
def test_get_models_is_for_viewers_and_admins_and_not_for_the_signed_out(): ...   # 401; viewer 200; admin 200
def test_get_models_lists_the_seeded_pairs_with_running_and_usable(): ...        # two models, running == the plus pair, usable True for edgetpu, detector "edgetpu"
def test_get_models_never_carries_verified_counts(): ...                          # "verifiedCounts" and "front_door_cam" absent from the JSON text
def test_get_models_without_frigate_falls_back_to_the_file(device_client, ...): ...  # device_client: Frigate answers nothing; config.yml with plus://<id>; running.source == "config_file", frigate_answers False, labels.source == "sidecar"
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_detection_picker.py tm-control/backend/tests/test_api_models.py -q`
Expected: FAIL

- [ ] **Step 3: Implement the two modules, the route, and the fake seed.** Regenerate the OpenAPI document and the UI schema (`python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json && (cd tm-control/ui && npm run api:generate)`).

- [ ] **Step 4: Run the backend suite**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS, `test_openapi_document` included.

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend tm-control/ui/src/api
git commit -m "Answer GET /models with the detector, the running model, the inventory, and the labels"
```

### Task 5: Upload one file, the bare-file form's sidecar, and Delete

**Files:**
- Create: `tm-control/backend/tm_control/modules/detection/upload.py`
- Modify: `tm-control/backend/tm_control/modules/detection/router.py`
- Modify: `tm-control/ui/src/api/openapi.json`, `schema.d.ts` (regenerated)
- Test: `tm-control/backend/tests/test_detection_upload.py`, `tests/test_api_models.py`

**Interfaces:**
- Consumes: Task 3's `valid_name`, `open_cache`, `open_in`, `stat_in`, `parse_sidecar`, `SidecarError`, `MODEL_FILE_MAX`, `SIDECAR_MAX`, `inventory`; Task 4's `_state`, `_frigate`, `running_model`, `detector_type`.
- Produces, in `upload.py`: `FREE_SPACE_MIN = 512 * 1024 * 1024` (the Device check's problem threshold; import it if it's a named constant in `modules/system/checks.py`, else define it here with that comment); `class UploadError(Exception)` with `status` and `message` (fixed strings: "That name isn't allowed." 422, "A model named <name> is already on the device; delete it first." 409, "The file is larger than 100 MB." 413, "The sidecar is larger than 2 MB." 413, "The device would have less than 512 MB free." 507, "The body ended before Content-Length." 400); `kind_of_upload(filename: str) -> Literal["archive", "sidecar", "model"]` (decision 7: `.zip`, `.tar.gz`, `.tgz` are archives; `.json` a sidecar; else a model); `MAGIC = {"zip": b"PK\x03\x04", "gzip": b"\x1f\x8b"}`; `free_space_ok(cache: Path, needed: int) -> bool` (`os.statvfs`); `async receive(stream, dir_fd, temp_name: str, limit: int, declared: int | None) -> int` (writes through a descriptor from `open_in(dir_fd, temp_name, O_WRONLY|O_CREAT|O_EXCL, 0o644)`, stops at `limit + 1` bytes and raises the 413, raises the 400 when the stream ends short of `declared`, fsyncs, returns the size; on any exception unlinks the temp name); `temp_name(name) -> str` (`.upload-<8 random hex>-<name>`, cut to 200 characters; the leading dot keeps it out of the inventory while it's written); `place(dir_fd, temp, final)` (`os.rename` with both `dir_fd`s, then fsync the directory).
- Produces, in `router.py`:
  - `PUT /models/upload/{filename}` (admin; `Request` body streamed; the `filename` must pass `valid_name` or, for a sidecar, `valid_name(filename[:-5])`): refuses before reading when the name exists (either half of a pair), when `Content-Length` is over the kind's cap, or when free space would fall under the floor; streams to the temp name; a sidecar is parsed before it's placed (a `SidecarError` is a 422 with its message and the temp file removed); a model file must be non-empty; an archive's magic must match (422 "The file isn't a <zip|tar.gz> archive.") and is handed to Task 6's `place_archive`. Answers 201 with the `ModelOut` of the entry touched (complete or not). Audit `models.upload` with the name placed.
  - `POST /models/{name}/sidecar` (admin), body `SidecarForm(model_type: str, width: int, height: int, input_tensor: str, input_pixel_format: str, input_dtype: str | None = None, labels: list[str])` (constrained: `width`/`height` 1 to 8192, labels 1 to 1000 entries of 1 to 64 characters, the enum fields 1 to 32 characters; Frigate validates the values at save): 404 when the model file isn't there, 409 when a sidecar exists; writes `<name>.json` in the Frigate+ shape per decision 13 through a temp name; answers the `ModelOut`. Audit `models.sidecar`.
  - `DELETE /models/{name}` (admin): 404 when neither file exists; 409 "That model is running; use another model first." when `running_model(...).name == name`; 409 "That's the installer's model." for the installer's file; otherwise unlinks both files that exist (`os.unlink(name, dir_fd=...)`), answers 204. Audit `models.delete`.
  - Every route re-reads the inventory after its write; the fake-mode `_frigate` keeps answering.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_detection_upload.py (asyncio tests use an async generator as the stream)
def test_kind_of_upload_by_name(): ...
def test_receive_writes_exactly_the_body_and_fsyncs(): ...
def test_a_body_over_the_cap_is_cut_off_and_leaves_nothing(): ...        # limit 10, 11 bytes -> UploadError 413, no file in the directory, not even the temp name
def test_a_body_shorter_than_content_length_leaves_nothing(): ...
def test_free_space_floor(): ...                                            # monkeypatch os.statvfs

# tests/test_api_models.py (admin, fake mode, the seeded cache), with put(client, name, data, content_type="application/octet-stream")
def test_upload_a_sidecar_then_its_model_completes_the_pair(): ...         # first answer complete False; second complete True, kind local
def test_upload_a_bare_model_then_the_form_writes_a_sidecar(): ...         # POST sidecar -> complete; the written JSON has supportedDetectors ["edgetpu"], name == file name, no id
def test_uploads_refuse_bad_names_existing_names_oversize_and_json_bodies(): ...  # "../x" 422 (also as %2E%2E), "mine.tflite" 409, Content-Length 101 MB 413, a text/plain body 403 from the CSRF check
def test_a_sidecar_that_does_not_parse_is_refused_and_removed(): ...
def test_viewers_cannot_upload_or_delete(): ...                             # 403
def test_delete_removes_both_files_and_refuses_the_running_and_installers(): ...
def test_the_running_model_cannot_be_deleted_even_when_frigate_is_down(device_client, ...): ...  # config.yml names plus://<id>; DELETE <id> -> 409
def test_audit_rows_name_the_model(): ...                                   # models.upload / models.sidecar / models.delete with detail == name
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_detection_upload.py tm-control/backend/tests/test_api_models.py -q`
Expected: FAIL

- [ ] **Step 3: Implement `upload.py` and the three routes** (the archive branch calls a `place_archive` stub that raises 422 "Archives aren't accepted yet" until Task 6). Regenerate the OpenAPI document and schema.

- [ ] **Step 4: Run the backend suite**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend tm-control/ui/src/api
git commit -m "Upload a model file or its sidecar, write a sidecar from the form, and delete a model"
```

### Task 6: Archives in, packages out

**Files:**
- Create: `tm-control/backend/tm_control/modules/detection/archives.py`
- Create: `tm-control/backend/tm_control/modules/detection/package.py`
- Modify: `tm-control/backend/tm_control/modules/detection/router.py`
- Modify: `tm-control/ui/src/api/openapi.json`, `schema.d.ts` (regenerated)
- Test: `tm-control/backend/tests/test_detection_archives.py`, `tests/test_api_models.py`

**Interfaces:**
- Consumes: Task 3's names and descriptors, `parse_sidecar`, `sha256_in`; Task 5's `UploadError`, `temp_name`, `place`.
- Produces, in `archives.py`: `MEMBERS_MAX = 3`, `SUMS_NAME = "SHA256SUMS"`, `class ArchiveError(ValueError)` (fixed messages: "The archive has no model file and sidecar pair.", "The archive holds more than a model, its sidecar, and SHA256SUMS.", "An archive member has a path, or isn't a plain file.", "An archive member is larger than its cap.", "SHA256SUMS doesn't match the files.", "The archive can't be read."); `@dataclass class Member: name: str; size: int; open: Callable[[], BinaryIO]`; `members(path: Path, kind: Literal["zip", "gzip"]) -> list[Member]` (zip through `zipfile`, tar through `tarfile` with `r:gz`; drops directory entries, names starting with `.`, and anything under `__MACOSX/`; refuses a member whose name has `/` or `\` left after that, a tar member that isn't `isfile()`, a zip member whose external attributes say symlink, and more than `MEMBERS_MAX` members); `extract(path, kind, dir_fd) -> tuple[str, str, bool]`: the members must be one model name passing `valid_name`, its `<name>.json`, and optionally `SHA256SUMS`; each is copied through a temp name reading no more than its cap plus one byte (the 413 message when exceeded), the sidecar is parsed, the sums file, when present, must list both files with matching hashes (`sha256sum` format: `<hex>  <name>` per line, `*` before the name allowed); the two temp names are placed only after both are complete; returns `(model, sidecar, sums_checked)`. `place_archive(temp_path, kind, dir_fd) -> str` wraps it for the router (the model name), deleting the archive's temp file in `finally`, and refuses the model's name when either half already exists (Task 5's 409).
- Produces, in `package.py`: `write_package(dir_fd, name, out: BinaryIO) -> None`: a `ZipFile(out, "w", ZIP_STORED)` with `<name>`, `<name>.json`, and `SHA256SUMS` (both hashes, `sha256sum` format, newline-terminated), each file read through `open_in` in 1 MiB blocks; the zip entries carry the files' mtimes. `GET /models/{name}/package` (admin): 404 unless the pair is complete; writes the zip to `<state_dir>/packages/<name>-<random>.zip` (`O_EXCL`, directory created 0700), answers it as `FileResponse` with `Content-Disposition: attachment; filename="<name>.zip"` and a `BackgroundTask` that unlinks it; audit `models.download`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_detection_archives.py, with make_zip(tmp_path, {name: bytes}) and make_tgz(...) helpers, SIDECAR from the fixture
def test_a_zip_or_tgz_with_a_pair_is_placed_as_a_pair(): ...
def test_a_package_from_write_package_round_trips_with_sums_checked(): ...   # write_package -> extract into a second cache: same bytes, sums_checked True
def test_a_wrong_sum_is_refused_and_nothing_is_placed(): ...
def test_archive_members_with_paths_links_or_devices_are_refused(): ...      # "../m.tflite", "sub/m.tflite", a tar symlink, a tar chrdev, a zip symlink: ArchiveError, directory unchanged
def test_dot_files_macosx_and_directories_are_ignored(): ...
def test_more_than_three_members_or_no_pair_is_refused(): ...
def test_a_member_over_its_cap_is_refused_without_reading_it_all(): ...       # declared size 101 MB in the header: refused before extraction
def test_a_corrupt_archive_is_refused(): ...

# tests/test_api_models.py
def test_upload_a_zip_package_and_download_it_back(): ...   # PUT x.zip -> 201 complete; GET package -> 200 attachment; its members' bytes equal; the temp file is gone afterwards
def test_a_tgz_whose_bytes_are_not_gzip_is_refused(): ...
def test_a_package_of_an_incomplete_pair_is_404(): ...
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_detection_archives.py tm-control/backend/tests/test_api_models.py -q`
Expected: FAIL

- [ ] **Step 3: Implement both modules, replace Task 5's stub, add the package route.** Regenerate the OpenAPI document and schema.

- [ ] **Step 4: Run the backend suite**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend tm-control/ui/src/api
git commit -m "Accept a model as a zip or tar.gz and package one for download with its sums"
```

### Task 7: Use a model, or the installer's default

**Files:**
- Modify: `tm-control/backend/tm_control/adapters/httpjson.py` (`post`)
- Modify: `tm-control/backend/tm_control/adapters/frigate.py` (`config_raw`, `save_config`)
- Modify: `tm-control/backend/tm_control/modules/detection/picker.py` (the write half)
- Modify: `tm-control/backend/tm_control/modules/detection/router.py`
- Modify: `tm-control/backend/tm_control/fake.py` (Use rewrites the running-model file)
- Modify: `tm-control/ui/src/api/openapi.json`, `schema.d.ts` (regenerated)
- Test: `tm-control/backend/tests/test_httpjson.py` (or where `get` is tested), `tests/test_detection_picker.py`, `tests/test_api_models.py`

**Interfaces:**
- Consumes: `RoundTripFile`, `restart_or_log`, `systemd.show_unit`, Task 3's `Model`, `InstallerDefault`, Task 4's `detector_type`, `running_model`.
- Produces, in `httpjson.py`: `post(url, body: bytes, content_type: str, headers=None, timeout=None) -> tuple[int | None, bytes | None]`, loopback-only like `get`, same error handling. In `frigate.py`: `config_raw() -> str | None` (`GET {BASE}/config/raw`, 200 and a body that `json.loads` to a `str`; None otherwise) and `save_config(text: str) -> tuple[int | None, str | None]` (`POST {BASE}/config/save?save_option=saveonly`, `text/plain`, a 30 s timeout since Frigate validates the whole config; returns the status and the JSON `message`, or None for each when missing).
- Produces, in `picker.py`: `class UseError(Exception)` with `status`, `code`, `message`; `model_section(model: Model) -> dict` (a Frigate+ pair: `{"path": "plus://<name>"}`; a local pair: `path` `/config/model_cache/<name>`, `width`, `height`, `input_tensor`, `input_pixel_format`, `model_type`, `input_dtype` when the sidecar has one, and `labelmap` as `{index: label}` with int keys; nothing else, since `ModelConfig` forbids extras); `default_section(detector: str, installer: InstallerDefault | None) -> dict | None` (the installer's section when `detector == "edgetpu"` and there is one; None otherwise, meaning "no `model:` key"); `replace_model_section(doc, section: dict | None) -> None` (ruamel `CommentedMap`: assign, or insert after `detectors` when absent, or delete when `section` is None); `FRIGATE_HEADER = "Your configuration is invalid."`; `refusal_lines(message: str) -> str` (the message's lines after the two header lines, stripped, joined with `; `, cut to 500 characters, passed through `apps.checks.redact`); `apply(section: dict | None, codedir) -> Literal["frigate", "file"]`: `config_raw()`; with text, round-trip load (`ruamel.yaml.YAML()`, `preserve_quotes=True`), `replace_model_section`, dump, `save_config`; 200 → `"frigate"`; 400 → `UseError(422, "frigate_refused", "Frigate refused the config: " + refusal_lines(message))`; any other status → `UseError(502, "frigate_error", "Frigate answered <status> to the save.")`; no text (Frigate not answering) → `RoundTripFile(<codedir>/frigate/config/config.yml)`, `replace_model_section(file.data, section)`, `file.save()` → `"file"` (a `ConcurrentEditError` or `OSError` → `UseError(500, "config_write", "Frigate's config.yml couldn't be written: <error class>")`). `check_usable(model: Model, detector: str | None)` → `UseError(409, "detector_unknown", "Frigate's detector type can't be determined, so a model can't be checked against it.")` when None; `UseError(422, "wrong_detector", "This model is built for <a, b>; this device detects with <type>.")` when not supported; `UseError(422, "incomplete", "This model is missing its sidecar.")` for an incomplete pair.
- Produces, in `router.py`: `POST /models/{name}/use` and `POST /models/default/use` (admin; `default` is reserved, so `valid_name` is checked after that match), both: 409 `restarting` "Frigate is restarting; try again in a minute." when `systemd.show_unit("frigate.service", ["ActiveState"])` is `activating` or `deactivating` (skipped in fake mode); the checks above; `apply`; audit `models.use` with the name or `default`; `background.add_task(restart_or_log, "frigate.service")` (not in fake mode; fake mode writes the running-model file); answers 202 `UseQueued(name: str, applied: Literal["frigate", "file"], restarts: list[str])`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_detection_picker.py
def test_model_section_for_a_plus_pair_is_only_the_path(): ...
def test_model_section_for_a_local_pair_translates_the_sidecar(): ...        # labelmap keys are ints, input_dtype present only when given, no other keys
def test_default_section_is_the_installers_for_edgetpu_and_nothing_otherwise(): ...
def test_replace_model_section_keeps_comments_and_the_rest(): ...            # a config text with comments and a kept section: only model changes; insertion after detectors; deletion
def test_refusal_lines_drop_the_header_and_redact(): ...                     # Frigate's two header lines gone; PLACEHOLDER_KEY in a line -> <key>
def test_apply_saves_through_frigate_when_it_answers(monkeypatch): ...       # config_raw returns a JSON string literal of YAML text; save_config sees the edited text as text/plain with save_option=saveonly; result "frigate"; the file on disk untouched
def test_apply_edits_the_file_when_frigate_is_silent(tmp_path, monkeypatch): ...   # config_raw None; RoundTripFile backup exists; result "file"
def test_frigates_refusal_is_shown_and_nothing_is_restarted(monkeypatch): ...      # save_config -> (400, message): UseError 422 with the lines; the file untouched

# tests/test_api_models.py
def test_use_a_model_answers_202_and_queues_a_restart(): ...                 # fake mode: running-model file rewritten; GET /models shows it running
def test_a_model_for_another_detector_is_refused_before_any_write(): ...     # sidecar with ["hailo8l"] on the edgetpu fake: 422 naming both; no apply call (monkeypatch picker.apply to fail the test if called)
def test_use_default_puts_the_installers_section_back(): ...
def test_use_is_409_while_frigate_restarts(device_client, systemctl, ...): ...   # systemctl.units frigate ActiveState activating
def test_use_is_admin_only_and_unknown_names_are_404(): ...
def test_use_audits_the_name_and_default(): ...
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest tm-control/backend/tests/test_detection_picker.py tm-control/backend/tests/test_api_models.py -q`
Expected: FAIL

- [ ] **Step 3: Implement the adapters, the picker's write half, the two routes, and the fake-mode write.** Regenerate the OpenAPI document and schema.

- [ ] **Step 4: Run the backend suite**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tm-control/backend tm-control/ui/src/api
git commit -m "Make Frigate use a model through its config API, or the file when it is down, then restart it"
```

### Task 8: The Status check's link and the Frigate+ wording point at the Detection page

**Files:**
- Modify: `tm-control/backend/tm_control/modules/apps/contracts.py` (`SET_THE_KEY`, `WAYS_OUT`, rule 5's and rule 3's text)
- Modify: `tm-control/backend/tests/fixtures/status_fake.json` (if a detail changes there)
- Test: `tm-control/backend/tests/test_contract_checks.py`

**Interfaces:**
- Produces: `SET_THE_KEY = Fix(kind="link", text="Set the key", href="/detection#frigate-plus")`; rule 5's sentence ends "Set the key, or upload <id> and <id>.json on the Detection page."; rule 3's advice ends "pick it under Settings, System, Detectors and model in Frigate, or upload it on the Detection page and choose Use."; `WAYS_OUT` becomes "enter the right key on the Detection page, upload the model's two files there, or choose Use the installer's model on the Detection page, which works while Frigate is down". The ThingsBoard fix keeps `/device#tokens-and-keys`.

- [ ] **Step 1: Change the tests' expected details** (`test_a_plus_model_without_a_key_or_cached_files_is_an_error_with_a_link`, the rule 3 tests, and every test asserting `WAYS_OUT`, which read the constant and so need only the link's href asserted), run them, see the href assertion fail.
- [ ] **Step 2: Make the changes; run the backend suite; PASS.**
- [ ] **Step 3: Commit** `git commit -m "Point the Frigate+ check at the Detection page"`.

### Task 9: The Detection page: list, labels, and the key form; the Device page says where the key went

**Files:**
- Create: `tm-control/ui/src/modules/detection/index.ts`, `DetectionPage.vue`, `LabelChips.vue`
- Create: `tm-control/ui/src/components/clipboard.ts` (`copyText`, moved from `DevicePage.vue`)
- Modify: `tm-control/ui/src/modules/index.ts` (`detection` after `device`), `src/modules/device/DevicePage.vue`, `src/api/client.ts`
- Modify: `tm-control/ui/tests/fake-api.ts` (parse a JSON body only when the request's Content-Type is JSON)
- Modify: `tm-control/ui/README.md` (a "Detection" design note; the Tokens and keys note)
- Test: `tm-control/ui/tests/detection-page.spec.ts`, `tests/device-page.spec.ts`

**Interfaces:**
- Consumes: `GET /api/v1/models` (`ModelsState`), `GET /api/v1/secrets` (admins), `EnteredSecret`, `ConfirmDialog`, `followJob` is not used here.
- Produces: the module `{ id: 'detection', routes: [{ path: '/detection', component: DetectionPage }], nav: [{ title: 'Detection', to: '/detection', icon: mdiCubeScan }] }`. The page's sections, as `h2`s in order: "Object detection" (the detector in a sentence: "This device detects with <edgetpu|hailo8l|cpu>." or "Frigate's detector is unknown."; the running model's title and kind in words: "Frigate runs <title>, a Frigate+ model | a local model | the installer's model | Frigate's built-in model."; while `frigate_answers` is false: "Frigate isn't answering; this is what its config file says."; the list of models as `v-list` items with the sidecar's name, the file name when they differ, `trained <date>`, `type`, `for <detectors>`, `<w>×<h>`, each file's size and the first 12 characters of its hash with the full hash in a `title`, and a chip "running" or "can't run on this detector" or "incomplete"), "What the model recognises" (two `LabelChips`: "Recognises" with `labels.recognised` or the sentence "Frigate isn't answering, and the running model has no sidecar on the device." when null; "Tracked by this device" with `labels.tracked`), and "Frigate+" (`id="frigate-plus"`, two sentences on the two routes, then for admins the `EnteredSecret` for the `frigate_plus_api_key` row from `GET /secrets`; for viewers the sentences only). `LabelChips` props `{ title: string; labels: string[] }`, a Copy button that calls `copyText(labels.join(', '))` and shows "Copied." for 2 s. Admin actions (Upload, Use, Download, Delete) are Task 10's; this task renders the page read-only for everyone, with the actions' slots empty.
- The Device page's Tokens and keys section filters out `frigate_plus_api_key` and ends with the line "The Frigate+ API key is on the [Detection page](/detection#frigate-plus)." as a `router-link`; its heading count in the tests drops by one. `client.ts`: set `Content-Type: application/json` only when the request has none. `fake-api.ts`: `body` is parsed JSON for a JSON Content-Type, the raw text's length for `application/octet-stream`, null otherwise.
- Load the `frontend-design` skill before writing the page and keep to the UI README's conventional Vuetify (outlined fields, `text-h6` section headings, `v-alert` for results); the design note in the README says what the page shows at 375 px (the list items wrap to two lines; the hash is hidden under its prefix).

- [ ] **Step 1: Write the failing tests**

```ts
// tests/detection-page.spec.ts, with MODELS (the fake seed as GET /models would answer it) and signedIn(ADMIN|VIEWER, answers)
it('lists the models with the running one marked and the detector named')
it('shows a viewer the page without the key form or any action')         // no button at all; "Frigate+" heading present
it('shows an admin the Frigate+ key form from GET /secrets')             // only the frigate_plus_api_key row's title appears
it('copies the recognised labels as comma-separated text')               // navigator.clipboard.writeText stubbed; called with "person, bicycle, car"
it('says when Frigate is not answering and the labels are unknown')
it('is linked from the menu after Device')
// tests/device-page.spec.ts
it('no longer shows the Frigate+ key and points at the Detection page')  // FOUR_SECRETS given; three forms; the link's href is /detection#frigate-plus
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd tm-control/ui && npm test`
Expected: FAIL (no module).

- [ ] **Step 3: Write the module, the page, `LabelChips`, `clipboard.ts`, the Device page change, the client and fake changes, and the README note.**

- [ ] **Step 4: Run the UI checks and look at it**

Run: `cd tm-control/ui && npm test && npm run build`, then fake mode as the README says (`TM_CONTROL_FAKE=1 PYTHONPATH=tm-control/backend python -m tm_control fake-reset`, `serve`, `npm run dev`): claim, open `/detection` as the admin and as a viewer, at 375 px too. Record the result in the PR's Testing section.

- [ ] **Step 5: Commit**

```bash
git add tm-control/ui
git commit -m "Add the Detection page with the model list, the label lists, and the Frigate+ key form"
```

### Task 10: Upload, Use, Download, and Delete on the page

**Files:**
- Create: `tm-control/ui/src/modules/detection/UploadModel.vue`, `ModelFields.vue`
- Create: `tm-control/ui/src/components/download.ts` (`saveBlob(blob, filename)`, lifted from `DevicePage.vue`'s diagnostics download, which then uses it)
- Modify: `tm-control/ui/src/modules/detection/DetectionPage.vue`, `src/modules/device/DevicePage.vue`
- Test: `tm-control/ui/tests/detection-page.spec.ts`, `tests/upload-model.spec.ts`, `tests/device-page.spec.ts` (the download still works)

**Interfaces:**
- Consumes: `PUT /api/v1/models/upload/{filename}` (body a `File`, `Content-Type: application/octet-stream`, through `api.PUT(..., { body: file, bodySerializer: (b) => b, headers: { 'Content-Type': 'application/octet-stream' } })`), `POST /models/{name}/sidecar`, `POST /models/{name}/use`, `POST /models/default/use`, `GET /models/{name}/package` (`parseAs: 'blob'`), `DELETE /models/{name}`, `ConfirmDialog`.
- Produces: `UploadModel` (a `v-file-input`, multiple, accepting `.zip,.tar.gz,.tgz,.json,.tflite,.hef,.onnx`; one archive, or a model file with or without its `.json`; it sends the sidecar first, then the model; a `v-progress-linear` while sending; a bare model file opens `ModelFields` right after the upload answers `complete: false` and no `.json` was chosen; emits `uploaded`); `ModelFields` (the form: `model_type` select over Frigate's six types, `width`, `height`, `input_tensor` select, `input_pixel_format` select, `input_dtype` select with "not set", a labels textarea one per line; prefilled for the device's detector with Frigate's documented example for `edgetpu` (`yolo-generic`, 320×320, `nhwc`, `rgb`) and `hailo8l` (`yolo-generic`, 640×640, `nhwc`, `rgb`), empty for `cpu`; Save posts the sidecar; emits `saved`). On the page: an "Upload a model" button above the list (admins) opening `UploadModel` in a dialog; per entry "Use" (hidden for the running one; disabled with the reason when `usable` is false or the entry is incomplete), "Download" (complete entries), "Delete" (when `deletable`); a "Use the installer's model" button under the list when the running kind isn't `installer_default` and the manifest has one, else "Use Frigate's built-in model" on a device without a Coral; Use and Delete go through `ConfirmDialog` with the titles "Use <title>?" / "Delete <title>?" and the texts "Frigate restarts, which takes about a minute. Traffic isn't counted while it does." / "Both of its files are removed from the device. This can't be undone."; after a Use's 202 the page shows a `v-alert` "Frigate is restarting." and polls `GET /models` every 3 s until `running.name` is the pick and `frigate_answers` is true (then "Frigate runs <title>."), or 90 s pass (then "Frigate hasn't come back yet; see the Status page." with a link). An `ApiError` from any action shows its message in the alert (Frigate's refusal lines included). Errors with status 0 use the client's offline message.
- `DevicePage.vue`'s diagnostics download calls `saveBlob`.

- [ ] **Step 1: Write the failing tests**

```ts
// tests/upload-model.spec.ts (mountAlone)
it('sends an archive as one PUT with an octet-stream body')
it('sends a pair as two PUTs, the sidecar first')
it('opens the fields form after a bare model file and posts the sidecar')
it('shows the API message when an upload is refused')
// tests/detection-page.spec.ts
it('uses a model after the confirm and polls until it runs')     // fake timers; GET /models answers change on the third poll
it('says when Frigate has not come back after ninety seconds')
it('downloads a package as a blob named <name>.zip')
it('deletes after the confirm and reloads the list')
it('disables Use for a model built for another detector, with the reason')
it('offers the installer\'s model when another one runs')
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd tm-control/ui && npm test`
Expected: FAIL

- [ ] **Step 3: Write the two components, `download.ts`, and the page's actions.**

- [ ] **Step 4: Run the UI checks and look at it in fake mode** (upload the fixture pair as two files and as a zip made from them, use it, use the installer's model, download, delete; 375 px). Take the PR's screenshots: the page as admin, as viewer, the upload dialog with the fields form, the Use confirmation.

- [ ] **Step 5: Commit**

```bash
git add tm-control/ui
git commit -m "Upload, use, download, and delete models from the Detection page"
```

### Task 11: Docs, CLAUDE.md, and the dev-Pi README

**Files:**
- Create: `docs/use/detection.md`
- Modify: `mkdocs.yml` (nav: "Use the device", after `use/device-health.md`)
- Modify: `docs/configuration/frigate-config.md` ("Better models": Enter the key, A device without internet, A model of your own, If Frigate stops over a model, the closing admonition)
- Modify: `docs/use/device-health.md` (Tokens and keys; the Status check sentence at line 45)
- Modify: `docs/use/control-app.md` (the pages list, if it has one)
- Modify: `docs/development/tm-control.md` (the module list, the routes, the nginx location, the manifest field, the sandbox line from Task 2)
- Modify: `CLAUDE.md` (tm-control's description, the sandbox sentence, the manifest field)
- Modify: `script/devpi/README.md` (the test tables for Task 12)

**Interfaces:** none; prose for operators per "Writing docs"; no device names.

- [ ] **Step 1: Write the pages**

`detection.md`, "The Detection page": what's on it (the detector, the running model, the list), who sees what (viewers read; admins act); **Upload a model**: a package from whoever trained it (zip or tar.gz, with the model file and its `.json` sidecar), the two files themselves, or a model file alone, after which the page asks for the settings Frigate needs (with a sentence on where to find them: the model's documentation or Frigate's reference config) and writes the sidecar; a model must be built for the device's detector, and the page says when it isn't; take models only from a source you trust, since a model is code the detector runs; **Use**: Frigate checks the config and restarts, about a minute, nothing counted meanwhile; if Frigate refuses the change the page shows its reason and nothing changes; "Use the installer's model" puts the default back and works even while Frigate is down; **Download**: a zip with the two files and `SHA256SUMS`, byte for byte, so the same model can go on another device or into a backup; **Delete**: not the running model nor the installer's; **What the model recognises**: the two lists and Copy; **Frigate+**: the key form moved here, the online route (Frigate's picker) and the offline route (download on another computer, upload here).

`frigate-config.md`: "Enter the key" points at the Detection page; "A device without internet" becomes "upload the two files on the Detection page and choose Use" (drop the SSH copy); "A model of your own" says the Detection page writes the keys for you from a sidecar or the form, and keeps the hand-edit as an alternative; "If Frigate stops over a model": the way out is "Use the installer's model" on the Detection page, with the SSH recipe kept as a last resort; the closing admonition's "planned update" sentence goes. `device-health.md`: Tokens and keys says the Frigate+ key is on the Detection page; the Status sentence says the link opens the Detection page. `tm-control.md`: the `detection` module and its seven routes, `ReadWritePaths`, the upload location, `frigate.coral_model` in the manifest, the fake-mode seed. `CLAUDE.md`: the tm-control paragraph (the Detection page and the `models` routes in a clause), the sandbox sentence, the manifest field, `tmsetup_frigate_coral_model`. `script/devpi/README.md`: the rows for Task 12's tests.

- [ ] **Step 2: Build the docs strictly**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: no warnings, exit 0.

- [ ] **Step 3: Commit**

```bash
git add docs mkdocs.yml CLAUDE.md script/devpi/README.md
git commit -m "Document the Detection page"
```

### Task 12: Device tests

**Files:**
- Modify: `script/devpi/tests/test_web.py`, `test_services.py`, `test_disruptive.py`

**Interfaces:**
- Consumes: `admin_session`, `viewer_session` (if one exists; else log a viewer in as the secrets test does), `expect`, `codedir`, `invocation`, `not_restarted`, `set_secret`.

- [ ] **Step 1: Write the tests**

`test_web.py`: `test_models_lists_the_device_detector_and_the_running_model` (any unit: `GET /models` as admin and as viewer is 200; `detector` equals `edgetpu` when the inventory's `ai` starts with `edgetpu`, `hailo8l` for `hailo8`, else `cpu`; `frigate_answers` true when the inventory marks Frigate healthy; `labels.tracked` is non-empty; on a Coral unit the installer's default is listed with one file whose `sha256` is 64 hex characters); `test_models_answers_no_verified_counts` (the JSON text has no `verifiedCounts`). `test_services.py`: `test_tm_control_may_write_frigates_config_directory` (`systemctl show -p ReadWritePaths tm-control.service` equals `<codedir>/frigate/config`); `test_model_uploads_are_proxied_with_the_larger_limit` (a 2 MB `PUT /api/v1/models/upload/x.tflite` through nginx with no session and no Origin is 403 from tm-control's cross-site check, not nginx's 413; the same body to `PUT /api/v1/secrets/x` is 413). `test_disruptive.py` (pii_free): `test_upload_package_and_delete_a_model_from_the_control_app`: PUT a sidecar built from the fixture with `supportedDetectors` set to the unit's detector and `name` "tmdev placeholder", then PUT `tmdev-placeholder.tflite` of 16 bytes; the pair is listed complete and `usable`; GET its package, unzip in memory, both members equal what was sent and `SHA256SUMS` checks; DELETE; gone; Frigate's invocation unchanged throughout. No Use in the device tests: a 16-byte model would break Frigate; the bench covers Use.

- [ ] **Step 2: Check them off-device**

Run: `python -m pytest script/devpi/tests --collect-only -q 2>&1 | tail -3`
Expected: collected, no errors.

- [ ] **Step 3: Commit**

```bash
git add script/devpi/tests
git commit -m "Check the Detection page's API on a device"
```

### Task 13: The Pi plan

Through `tmdev.py check start|item|status|end`, one host at a time, from a worktree (`script/devpi/README.md`). Deploy with `tmdev.py deploy <host> -- -t tm-control -t revproxy -t frigate` (the unit, the nginx location, and the manifest; `-t frigate` for the manifest and, on a `-f` item, the template). Every value a placeholder; no file contents printed; no real sidecar in any log.

- [ ] **Bench A** (the Coral unit, camera, upgraded from PR 280):
  1. After the deploy: `systemctl show -p ReadWritePaths`, the manifest has `frigate.coral_model`, `GET /models` lists the installer's default as running, `recognised` has 91 labels from Frigate, `tracked` matches `config.yml`'s lists; the Device page no longer shows the key; the Status page's Frigate+ link opens `/detection#frigate-plus`.
  2. A real local model, from the installer's own file: `sudo cp` the Coral model to `/tmp` as `copy.tflite` (read-only copy, nothing private), write a sidecar for it by hand from `labels-coco17.txt` (`type: yolo-generic`, 512×512, `nhwc`, `rgb`, `supportedDetectors: ["edgetpu"]`), zip both on the dev machine, upload the zip on the page: listed complete and usable, hashes equal `sha256sum` on the Pi. **Use** it: the confirm, the 202, Frigate restarts once through systemd (`NRestarts` stays 0, a new invocation), the page shows it running within 90 s, `config.yml`'s `model:` has the translated keys and the rest of the file (comments included) is unchanged against the backup, detection works (events keep arriving). Measure the time from the 202 to `frigate_answers` true; record it.
  3. "Use the installer's model": the section is the manifest's, Frigate restarts, running is the installer's default again.
  4. A model for another detector: edit the sidecar's `supportedDetectors` to `["hailo8l"]`, upload under another name: Use is disabled on the page with the reason and `POST .../use` answers 422 naming both types; delete it.
  5. Frigate's refusal: upload a pair whose sidecar says `type: nope`; Use → 422 with Frigate's `Line N: model -> model_type …` line, nothing changed on disk, no restart (invocation unchanged).
  6. The disk fallback: over SSH set `model: {path: plus://tmdevplaceholder0001}` and restart Frigate (the crash loop from PR 280's bench); on the page "Use the installer's model" → 202 with `applied: "file"`, a `.bak` beside `config.yml`, Frigate restarted by systemd, running again within 90 s; the Status page clears.
  7. Download the pair from item 2, upload it on the Hailo unit (bench B item 3) and compare `SHA256SUMS`.
  8. The key form: set and remove the placeholder key from the Detection page (as PR 280's bench did from the Device page); the Status check's link lands on the form.
  9. Viewer session: the page lists, no buttons, `PUT`/`POST`/`DELETE` are 403.
  10. Caps: a 101 MB `PUT` through nginx → 413 before the body is read (`dd if=/dev/zero` on the dev machine); a 1.5 MB JSON sidecar → 413 from tm-control.
  11. Device tests: `tmdev.py test <host> --disruptive -- -k "models or detection or write"`, then the full non-disruptive suite.
  12. Delete the uploads; restore the installer's section; remove the backups; the key unset.
- [ ] **Bench B** (the Hailo unit, no camera): fresh deploy; `GET /models` lists no installer's default and running kind `frigate_default` (no `model:` section) with `recognised` from Frigate; "Use Frigate's built-in model" is what the page offers; upload the pair from A7, Use is disabled (built for `edgetpu`); delete; the suite with its skips.
- [ ] Record each item with `tmdev.py check item`, and end with `tmdev.py check end`. If item 2's measured time is over 90 s, change the page's deadline and the docs' "about a minute" and say so in the PR.

### Task 14: Pull request

- [ ] Run every off-device check in Global Constraints once more on the final branch; `npm run build` so the UI's build matches; `git grep` the branch for device names.
- [ ] Copy this plan to `design/plans/2026-11-06-detection-models.md` with the Status paragraph pointing at issue 283, and commit it ("Add the Detection page plan").
- [ ] Open the PR against `feature/frigate-plus-key/279` with the template filled in: the release-note paragraph ("The control app gains a Detection page: upload a Frigate model as a package, a Frigate+ pair, or a local file, make Frigate use it, download it for another device, and see which objects the running model recognises and the device tracks. The Frigate+ API key moved there from the Device page. tm-control may now write Frigate's config directory, and uploads up to 100 MB pass through the proxy."), "Closes #283", the decisions to look at (1, 2, 3, 6), a "Limits" list (no overwrite; one Use at a time; a model Frigate can't load that reaches it from disk still needs "Use the installer's model"; the label lists need Frigate answering for Frigate's built-in model; the page shows no Frigate+ account models online), the Pi plan's results with the measured Use time, the screenshots from Task 10, the Docs list from Task 11, and the "AI assistance" section. Say `PUBLIC push →` before pushing, and show the maintainer the commit messages and the PR text first.
