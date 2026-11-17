# Node-RED developer mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `tmsetup.sh -C dev_mode` turns Node-RED Projects on for a unit and sets its project up once at the installed commit; every other unit has Projects off; each install run says so when a project's flows differ from the installed ones.

**Architecture:** One stdlib-only Python helper, `tm_nr_project.py`, does the git and file work and is the only code that reads Node-RED's `.config.projects.json`. The installer runs its `facts` command on the machine running `tmsetup.sh` and its `status`, `seed`, and `notice` commands on the device as the code owner. `settings.js` reads the on/off switch from `TM_NR_PROJECTS` in `node-red-tm.env`.

**Tech Stack:** Python 3 (stdlib, must run on 3.9), git, Ansible role `tmsetup`, pytest (`script/tests`), Node-RED 5.0.8 `settings.js`.

**Spec:** `design/specs/2026-11-17-node-red-developer-project-design.md` (issue #334). Read it first; this plan argues from it.

## Global Constraints

- **Order:** build after #333 (the #276 fix) and #335 (the spec and this plan) have merged into `dev`. #333 adds `script/tests/test_node_red_project.py` and the corrected `package.json`, and Tasks 3 and 4 depend on both. Branch `feature/node-red-dev-mode/334` from `dev`.
- **Never moves a project.** `seed` acts only when `data/projects/traffic-monitor` doesn't exist and `.config.projects.json` names no active project. No other command writes anything.
- **No address and no secret in any output:** not in helper stdout or stderr, the notice, the install log, or a test's failure text. `.config.projects.json` holds the project's `credentialSecret`; never print the file.
- **A failed clone never fails the install.** The helper exits 0 with `"result": "clone_failed"`. Exit 1 is for a bug or bad arguments only.
- Fixed values: project name `traffic-monitor`; `rootPath` `container/node-red-tm/data/`; upstream address `https://github.com/glossyio/traffic-monitor.git`; env line `TM_NR_PROJECTS` with values `1` and `0`; flag `dev_mode` (`tmsetup_bool_dev_mode`).
- Repo rules (`CLAUDE.md`): task names `TMSetup - Node-RED-TM Setup - <Action>`, FQCN modules, `become: true` per task, registered results end in `_register`, lines up to 120 characters, the commit trailer block instead of `Co-Authored-By`, no AI-provenance comments, docs follow "Writing docs" in `docs/development/contributing.md`.
- Open PRs #320 and #326 edit other parts of `settings.js` and append to `script/tests/test_node_red_settings.py`; #321 edits the token comments in `node-red-tm.env.j2`. Don't touch those lines or that test file.
- The maintainer reads commit messages and PR text before any push. Stop and show them.

## Review Focus

1. **An `origin` address with a login in it** (`https://user:token@github.com/x/y.git`): the device gets the address without the login, and neither part appears in any output. Tests in Tasks 1 and 3.
2. **The helper runs through `runuser` with root's environment** (`HOME=/root`, unreadable): git must not read a global or system config, and must not prompt for a password. Test in Task 3.
3. **A `.config.projects.json` that already has other projects or keys, or a project folder that already exists:** other entries survive a seed; an existing folder or active project means nothing is written; a second run changes nothing. Tests in Task 3.
4. **A clone that fails or times out partway:** no `data/projects/traffic-monitor` folder and no temporary folder is left, and the next run can try again. Test in Task 3.
5. **A project the helper can't read cleanly** (its flow file is missing, its `package.json` isn't valid JSON during a merge, it isn't a git checkout, its name isn't `traffic-monitor`): `status` and `notice` still answer and report the files as different. Tests in Task 2.

---

### Task 1: Helper skeleton, `facts`, and address cleaning

**Files:**
- Create: `container/node-red-tm/project/tm_nr_project.py`
- Test: `script/tests/test_node_red_project_helper.py` (load the helper with `importlib` from its path; mark git tests `@needs("git")` from `required_tools`)

**Interfaces:**
- Produces: constants `UPSTREAM_URL`, `PROJECT = "traffic-monitor"`, `ROOT_PATH = "container/node-red-tm/data/"`; `clean_url(raw: str) -> str`; `read_facts(repo: Path, version: str) -> dict` with keys `url`, `branch`, `commit`, `tag` (all strings, `""` when unknown); `git_env() -> dict`; `main(argv: list) -> int`; CLI `tm_nr_project.py facts --repo DIR --version X` printing that dict as one JSON line.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("raw, cleaned", [
    ("https://github.com/someone/traffic-monitor.git", "https://github.com/someone/traffic-monitor.git"),
    ("https://user:tok3n@github.com/someone/traffic-monitor.git", "https://github.com/someone/traffic-monitor.git"),
    ("https://tok3n@github.com/someone/traffic-monitor.git?x=1#y", "https://github.com/someone/traffic-monitor.git"),
    ("git@github.com:someone/traffic-monitor.git", helper.UPSTREAM_URL),
    ("ssh://git@github.com/someone/traffic-monitor.git", helper.UPSTREAM_URL),
    ("http://github.com/someone/traffic-monitor.git", helper.UPSTREAM_URL),
    ("/home/someone/traffic-monitor", helper.UPSTREAM_URL),
    ("", helper.UPSTREAM_URL),
])
def test_only_an_https_address_without_its_login_reaches_the_device(raw, cleaned): ...

def test_facts_from_a_checkout(checkout):        # url cleaned, branch name, 40-character commit, tag == ""
def test_facts_from_a_detached_checkout(checkout):   # branch == ""
def test_facts_without_an_origin(checkout):      # url == UPSTREAM_URL
def test_facts_outside_a_checkout(tmp_path):     # {"url": UPSTREAM_URL, "branch": "", "commit": "", "tag": "v0.7.1"}
def test_facts_inside_an_unrelated_checkout(tmp_path):   # a git repo that doesn't track the flows file: same as outside
def test_the_facts_command_prints_one_json_line_and_no_login(checkout):   # run the CLI; "tok3n" not in stdout + stderr
```

The `checkout` fixture makes a throwaway repository that tracks `container/node-red-tm/data/flows.json`, `package.json` (with `flowFile` `flows.json`, `credentialsFile` `flows_cred.json`), and `flows_cred.json`, with an `origin` that is a second local repository reached by path. Tests that need an `https://` origin set the URL without fetching.

- [ ] **Step 2: Run them and see them fail**

Run: `.venv/bin/python -m pytest script/tests/test_node_red_project_helper.py -q`. Expected: errors, the helper file doesn't exist.

- [ ] **Step 3: Write the helper's first part**

- `clean_url`: `urllib.parse.urlsplit`; keep it only when the scheme is `https` and there is a host; rebuild from host, port, and path alone.
- `read_facts`: a checkout counts only when `git -C repo rev-parse --show-toplevel` works **and** `git ls-files --error-unmatch container/node-red-tm/data/flows.json` works in that top folder (the unrelated-checkout case `files/pack-ui-sources.sh` also guards). Branch from `git symbolic-ref --short -q HEAD`, commit from `git rev-parse HEAD`, address from `git remote get-url origin`. No checkout: `tag` is `"v" + version`.
- `git_env()`: the current environment plus `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_TERMINAL_PROMPT=0`. Every git call in the helper uses it.
- `main`: `argparse` subcommands; this task adds `facts`.

- [ ] **Step 4: Run the tests and see them pass**
- [ ] **Step 5: Commit** (`Add the Node-RED project helper: installer facts and address cleaning`)

### Task 2: `status` and `notice`

**Files:**
- Modify: `container/node-red-tm/project/tm_nr_project.py`
- Test: `script/tests/test_node_red_project_helper.py`

**Interfaces:**
- Consumes: `git_env`, `PROJECT`, `main` from Task 1.
- Produces: `project_status(node_red_dir: Path) -> dict` with `active` (project name, `""` when none is active), `project_dirs` (sorted folder names under `data/projects`), `branch` and `commit` (7 characters) of the active project (`""` when unknown), `differs` (subset of `["flows.json", "package.json"]`, in that order); `build_notice(status: dict, projects_on: bool, seed_message: str) -> str`; CLI `status --node-red-dir DIR` (JSON line) and `notice --node-red-dir DIR --projects-on {0,1} [--seed-message TEXT]` (plain text, empty when there is nothing to say). `node_red_dir` is the device's `node-red-tm` folder, which holds `data/` and `node-red-tm.env`.

- [ ] **Step 1: Write the failing tests**

```python
def test_status_with_no_data_folder(tmp_path):       # active "", project_dirs [], differs []
def test_status_of_a_project_that_matches_the_installed_files(unit):   # differs == []
def test_status_reports_each_file_that_differs(unit):   # edit the project's flows.json -> ["flows.json"]; both -> both, in order
def test_status_counts_uncommitted_edits(unit):      # working-tree content is what is compared
def test_status_follows_the_projects_own_name_and_root_path(unit):   # active "my-fork", rootPath "" -> compares the clone's top folder
def test_status_of_a_project_it_cannot_read(unit):   # missing flow file, package.json "<<<<<<<", no .git:
                                                     # no exception; that file is in differs; branch and commit ""
def test_status_never_prints_the_credential_secret(unit):   # CLI output lacks the secret written into .config.projects.json
def test_notice_when_the_project_differs():
    text = helper.build_notice({"active": "traffic-monitor", "project_dirs": ["traffic-monitor"], "branch": "my-feature",
                                "commit": "1a2b3c4", "differs": ["flows.json", "package.json"]}, True, "")
    assert text.splitlines() == [
        'Node-RED on this device runs the project "traffic-monitor" (branch my-feature at 1a2b3c4),',
        "not the flows this install copied. The installer never changes a project.",
        "Differs: flows.json, package.json.",
        "To run the installed flows, switch the project to the installed version in the editor.",
        "The image's modules come from the installed package.json, so a module the project adds needs an image rebuild.",
    ]
def test_notice_is_empty_when_the_project_matches():
def test_notice_when_projects_is_off_but_a_project_is_on_disk():
    # 'A Node-RED project is on this device (traffic-monitor), but Projects is off, so the installed flows run.'
    # 'To use it, run: bash script/tmsetup.sh -t node-red-tm -C dev_mode'
def test_notice_puts_the_seed_message_first():       # seed_message, then the lines above when they apply
def test_notice_without_git_details():               # branch "" -> '(not a git checkout)' in place of the branch and commit
```

The `unit` fixture builds `<tmp>/node-red-tm` with `data/flows.json`, `data/package.json`, `node-red-tm.env` (a `NODE_RED_CREDENTIAL_SECRET=placeholder-secret` line), a project cloned from the Task 1 `checkout`, and a `.config.projects.json` naming it active.

- [ ] **Step 2: Run them and see them fail**
- [ ] **Step 3: Implement.** The project's files are found the way Node-RED finds them: `data/projects/<active>/<rootPath>/package.json`, and the flow file is `<rootPath>` joined to that file's `node-red.settings.flowFile`. Compare bytes with the installed `data/flows.json` and `data/package.json`. The last notice line appears only when `package.json` is in `differs`.
- [ ] **Step 4: Run the tests and see them pass**
- [ ] **Step 5: Commit** (`Report which Node-RED project a unit runs and whether its flows differ`)

### Task 3: `seed`

**Files:**
- Modify: `container/node-red-tm/project/tm_nr_project.py`
- Test: `script/tests/test_node_red_project_helper.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: `seed_project(node_red_dir: Path, url: str, branch: str, commit: str, tag: str, timeout: int = 900) -> dict` with `result` (`"seeded"`, `"exists"`, `"clone_failed"`, `"not_activated"`), `exact` (bool), `branch`, `commit` (7 characters, `""` when nothing was cloned), `message` (text for the notice, `""` when there is nothing to say); CLI `seed --node-red-dir DIR --url U [--branch B] [--commit C] [--tag T]` printing that dict as one JSON line, exit 0 for all four results.

- [ ] **Step 1: Write the failing tests**

```python
def test_seed_checks_out_the_installed_commit_on_the_installers_branch(seedable):
    # result "seeded", exact True; the project's HEAD == commit; branch == the installer's branch, tracking origin's
def test_seed_names_a_branch_for_a_detached_installer(seedable):   # branch "" -> "installed-<7 characters>"
def test_seed_from_a_tag(seedable):                         # commit "", tag "v0.7.1" -> that tag's commit, branch "installed-<7>", exact True
def test_seed_when_the_commit_is_not_on_the_remote(seedable):
    # exact False; on origin's branch of that name, else the default branch; message ==
    # "The Node-RED project started on <branch> at <7>, not the installed commit <7>, because that commit isn't on the "
    # "project's remote. Push it, then switch the project to it in the editor."
def test_seed_writes_the_project_entry_and_keeps_the_rest(seedable):
    # existing {"projects": {"other": {"credentialSecret": "x"}}, "extra": 1} -> "other" and "extra" kept;
    # projects["traffic-monitor"] == {"credentialSecret": "placeholder-secret", "rootPath": "container/node-red-tm/data/"};
    # activeProject == "traffic-monitor"; the file's mode is unchanged (0640 when the file is new)
def test_seed_changes_nothing_when_the_folder_exists(seedable):     # result "exists"; folder and config byte-for-byte the same
def test_seed_changes_nothing_when_a_project_is_active(seedable):   # any active project name
def test_a_second_seed_changes_nothing(seedable):
def test_a_failed_clone_leaves_nothing_behind(seedable):
    # url -> a path that doesn't exist: result "clone_failed"; no data/projects/traffic-monitor; no temporary folder;
    # config untouched; message == "The Node-RED project wasn't set up: the clone failed. The installed flows run. "
    # "The next install run tries again."
def test_a_clone_that_times_out_is_a_failed_clone(seedable):        # seed_project(..., timeout=0)
def test_a_project_with_paths_in_package_json_is_not_turned_on(seedable):
    # the remote's package.json has "/data/flows.json": result "not_activated"; folder kept; config untouched; message ==
    # "The Node-RED project was cloned to data/projects/traffic-monitor but not turned on: its package.json names its "
    # "flow files by path. Switch it to a branch with the flow-file fix, then open it in the editor."
def test_seed_works_with_roots_home(seedable):              # run the CLI with HOME set to a folder the user can't read
def test_seed_output_never_holds_the_address_or_the_secret(seedable):   # CLI stdout + stderr, in the seeded and failed cases
def test_seed_refuses_a_branch_name_git_would_not_accept(seedable): # branch "-x" or "a..b" is treated as no branch
```

The `seedable` fixture is Task 2's `unit` without the project folder and without `.config.projects.json`, with the Task 1 `checkout` as the remote.

- [ ] **Step 2: Run them and see them fail**
- [ ] **Step 3: Implement.** Decisions the tests don't make:
  - Clone into `data/.tm-project-seed.tmp` (removed first if a dead run left one), and `os.rename` it to `data/projects/traffic-monitor` only after the checkout. Remove it on any failure, including a timeout.
  - The checkout target is `commit`, else `tag`. It counts as present when `git cat-file -e <target>^{commit}` works in the clone.
  - A branch name is valid when `git check-ref-format --branch <name>` accepts it.
  - The credential key is the value of the `NODE_RED_CREDENTIAL_SECRET=` line in `node-red-tm.env`. No such line is a bug in the caller: raise, and exit 1.
  - Write `.config.projects.json` to a temporary file beside it, then rename.
  - Git's stderr is never passed through; the messages above are the whole report.
- [ ] **Step 4: Run the tests and see them pass**
- [ ] **Step 5: Commit** (`Set up the Node-RED project once, at the installed commit`)

### Task 4: The switch in `settings.js` and `node-red-tm.env`

**Files:**
- Modify: `container/node-red-tm/data/settings.js` (the `projects:` block, `enabled: true`)
- Modify: `container/node-red-tm/node-red-tm.env.j2` (two lines directly after the `TM_INTERNAL_TOKEN=` line)
- Test: `script/tests/test_node_red_project.py`, `script/tests/test_tmsetup_templates.py`

**Interfaces:**
- Consumes: the Ansible fact `tmsetup_node_red_projects_on` (bool), which Task 5 sets before the template renders.
- Produces: `editorTheme.projects.enabled` is true exactly when `process.env.TM_NR_PROJECTS === "1"`; the env template renders `TM_NR_PROJECTS=1` or `TM_NR_PROJECTS=0`.

- [ ] **Step 1: Write the failing tests**

```python
@needs("node")
@pytest.mark.parametrize("value, enabled", [("1", True), ("0", False), ("", False), ("true", False), (None, False)])
def test_projects_is_on_only_when_the_env_line_says_1(value, enabled): ...   # None means the variable is unset

def test_node_red_env_template_carries_the_projects_switch():
    # rendered with tmsetup_node_red_projects_on=True: the line "TM_NR_PROJECTS=1", with a "# " comment line above it;
    # with False: "TM_NR_PROJECTS=0"
```

Extend the existing `render_node_red_env` helper in `test_tmsetup_templates.py` so every render passes `tmsetup_node_red_projects_on` (default `False`).

- [ ] **Step 2: Run them and see them fail**
- [ ] **Step 3: Make the two edits.** The env comment: `# Node-RED Projects, for editing flows on this device: 1 turns it on (tmsetup.sh -t node-red-tm -C dev_mode).` and a second line `# With 0, Node-RED runs the installed flows, even when a project is on the device.`
- [ ] **Step 4: Run the tests and see them pass**, plus `script/tests/test_node_red_settings.py`
- [ ] **Step 5: Commit** (`Turn Node-RED Projects on only where node-red-tm.env says so`)

### Task 5: Installer wiring

**Files:**
- Modify: `script/tmsetup.sh` (`_VALID_CUSTOM_VARS`), `script/ansible/roles/tmsetup/defaults/main.yml` (`tmsetup_bool_dev_mode: false`, with a comment like `mqtt_lan`'s)
- Modify: `script/ansible/roles/tmsetup/tasks/node-red-tm_setup.yml`, `script/ansible/roles/tmsetup/tasks/main.yml`
- Test: `script/tests/test_tmsetup_tasks.py`, `script/tests/test_tmsetup_script.py`

**Interfaces:**
- Consumes: the helper's four commands (Tasks 1–3); `tmsetup_mqtt_env_stat_register` and `tmsetup_mqtt_env_register` from `tasks/mqtt_broker.yml`, which already reads `node-red-tm.env` earlier in every run that has the `node-red-tm` tag.
- Produces: the fact `tmsetup_node_red_projects_on`; the register `tmsetup_node_red_project_notice_register` (its `stdout_lines` are the notice).

Tasks to add to `node-red-tm_setup.yml`, in this order. Each device command is `/usr/sbin/runuser -u {{ tmsetup_codeowner }} -- /usr/bin/python3 {{ tmsetup_codedir }}/node-red-tm/project/tm_nr_project.py …` with `become: true`, as the migration runner in `node-red-tm.container.j2` is run.

1. Add `{{ tmsetup_codedir }}/node-red-tm/project` to the directories loop.
2. `Copy the Node-RED project helper`: after the static files copy; `src: container/node-red-tm/project/tm_nr_project.py`, mode `0644`, no handler.
3. `Read the Node-RED project state`: `status --node-red-dir {{ tmsetup_codedir }}/node-red-tm`; `changed_when: false`; register `tmsetup_node_red_project_status_register`.
4. `Decide whether Projects is on`: `set_fact`, `no_log: true` (the env text holds secrets), before `Create Node-RED-TM Configs`:

    ```yaml
    vars:
      env_text: "{{ tmsetup_mqtt_env_register.content | b64decode if tmsetup_mqtt_env_stat_register.results[0].stat.exists else '' }}"
      env_value: "{{ (env_text | regex_search('(?m)^TM_NR_PROJECTS=.*$') or '') | regex_replace('^TM_NR_PROJECTS=', '') | trim }}"
      env_has_line: "{{ env_text is regex('^TM_NR_PROJECTS=', multiline=true) }}"
      active_project: "{{ (tmsetup_node_red_project_status_register.stdout | from_json).active }}"
    ansible.builtin.set_fact:
      tmsetup_node_red_projects_on: >-
        {{ (tmsetup_bool_dev_mode | default(false) | bool) or env_value == '1'
           or (not (env_has_line | bool) and active_project != '') }}
    ```

5. `Add the Projects switch to node-red-tm.env`: `lineinfile`, beside the `TM_NR_TOKEN_KEY` task and with its `when`; `regexp: '^TM_NR_PROJECTS='`; notifies `Restart node-red-tm.service`.
6. `Read the installer's checkout`: `delegate_to: localhost`, `become: false`, `changed_when: false`, `when: tmsetup_node_red_projects_on | bool`; argv `{{ ansible_playbook_python }}`, `{{ role_path }}/files/container/node-red-tm/project/tm_nr_project.py`, `facts`, `--repo`, `{{ role_path }}`, `--version`, `{{ tmsetup_tm_version }}`; register `tmsetup_node_red_project_facts_register`. The helper cleans the address before printing it, so no task ever carries the raw one.
7. `Set up the Node-RED project`: `seed` with `--url`, `--branch`, `--commit`, `--tag` from the facts JSON, passed as `argv` items; same `when`; `changed_when: (… .stdout | from_json).result == 'seeded'`; notifies `Restart node-red-tm.service`; register `tmsetup_node_red_project_seed_register`. Place it after the env tasks, so the credential key's line exists on a first install.
8. `Compose the Node-RED project notice`: `notice --node-red-dir … --projects-on {{ '1' if tmsetup_node_red_projects_on | bool else '0' }} --seed-message "{{ (tmsetup_node_red_project_seed_register.stdout | default('{}') | from_json).message | default('') }}"` (the seed task is skipped when Projects is off, so its register has no `stdout`); `changed_when: false`; register `tmsetup_node_red_project_notice_register`. Last task in the file.

In `main.yml`, directly **before** `TMSetup - Main - Show the setup code` (tests pin that one as the last task): `TMSetup - Main - Say which flows Node-RED runs`, tag `node-red-tm` only, `when: tmsetup_node_red_project_notice_register.stdout | default('') != ''`, `ansible.builtin.debug` with `msg: "{{ tmsetup_node_red_project_notice_register.stdout_lines }}"`.

- [ ] **Step 1: Write the failing tests** (in the style of the broker-login tests, `test_tmsetup_tasks.py` near `mqtt_broker_tasks()`)

```python
def test_dev_mode_is_a_flag_tmsetup_accepts():       # every tmsetup_bool_* in defaults/main.yml is in _VALID_CUSTOM_VARS, and back
@pytest.mark.parametrize("flag, env_text, active, expected", [
    (True,  "TM_NR_PROJECTS=0\n", "", True),                 # the flag wins
    (False, "TM_NR_PROJECTS=1\n", "", True),                 # kept from an earlier run, and through -f
    (False, "TM_NR_PROJECTS=0\n", "traffic-monitor", False), # turned off by hand stays off
    (False, "OTHER=1\n", "traffic-monitor", True),           # upgrade: a unit that already uses a project keeps it
    (False, "OTHER=1\n", "", False),
    (False, "", "", False),                                  # first install, no env file
    (False, "TM_NR_PROJECTS=true\n", "", False),
])
def test_projects_stays_on_only_where_it_was_chosen(flag, env_text, active, expected): ...   # evaluate() the set_fact
def test_the_decision_comes_before_the_env_template():        # task order in node-red-tm_setup.yml
def test_the_project_is_set_up_after_the_env_file_exists():   # seed's index > the template's and the lineinfile's
def test_project_commands_run_as_the_code_owner():            # status, seed, notice argv start with runuser -u {{ tmsetup_codeowner }}
def test_the_installers_checkout_is_read_on_the_machine_running_tmsetup():   # delegate_to localhost, become false
def test_setting_up_a_project_restarts_node_red_only_when_it_made_one():     # changed_when and notify
def test_the_notice_is_shown_before_the_setup_code_and_only_with_the_node_red_tag():
def test_no_project_task_can_print_the_env_file():            # the set_fact is no_log; no task echoes env_text
```

- [ ] **Step 2: Run them and see them fail**
- [ ] **Step 3: Make the edits above**
- [ ] **Step 4: Run** `.venv/bin/python -m pytest script/tests -q`, `(cd script/ansible && ansible-playbook -i localhost setup.yml --syntax-check </dev/null)`, `bash -n script/tmsetup.sh`. Expected: all pass.
- [ ] **Step 5: Commit** (`Add tmsetup.sh -C dev_mode: Node-RED Projects with the project set up by the installer`)

### Task 6: Docs and the device test

**Files:**
- Modify: `docs/development/dev-environment.md`, `docs/reference/tmsetup.md` (the `-C` row), `CLAUDE.md`
- Modify: `script/devpi/tests/devpi_checks.py` (`validate_expect`: a `dev_mode` key, bool, default `False`), `script/devpi/dev-pis.example.yml`, `script/devpi/README.md` (the key)
- Create: `script/devpi/tests/test_node_red_project.py`

- [ ] **Step 1: Device tests** (they run only through `tmdev.py test`; each calls the helper's `status` on the Pi through `runuser`, never reads `.config.projects.json` or the env file itself)

```python
def test_a_developer_unit_runs_its_project(usable_host, expect, codedir, codeowner):
    # skip unless expect["dev_mode"]; status: active == "traffic-monitor", "traffic-monitor" in project_dirs,
    # differs == [] (right after an install with the flag, the project is the installed version)
def test_an_ordinary_unit_runs_the_installed_flows(usable_host, expect, codedir):
    # skip when expect["dev_mode"]; `sudo grep -c '^TM_NR_PROJECTS=1$'` on the env file prints 0
    # (the count only, never the file's lines)
```

- [ ] **Step 2: Docs.**
  - `dev-environment.md`, "Node-RED logic": the device steps become: install with `bash script/tmsetup.sh -t node-red-tm -C dev_mode`; open the editor, where the project `traffic-monitor` is already open on the installed version; its `origin` is the address the installer's checkout came from, so add your fork as a second remote when that isn't yours; commit to a branch; open a pull request. Then two short paragraphs: an active project's flows win over the installed ones and the installer says so at the end of each run when they differ; to turn Projects off, set `TM_NR_PROJECTS=0` in `/opt/traffic-monitor/node-red-tm/node-red-tm.env` and restart `node-red-tm.service`. Keep cloning by hand as a collapsed `???` note, with the package-file step from #333. Update the schema section's project path if it changes.
  - `tmsetup.md`: add `dev_mode` to the `-C` row, linking to the dev-environment section; say it acts only in a run that includes `node-red-tm`.
  - `CLAUDE.md`: the `-C dev_mode` command line; in "Provisioning", one bullet on the helper, the env line, seed-once, and the notice; in "Editing `flows.json`", that an active project wins over the installed flows.
- [ ] **Step 3: Run** `~/.venvs/tm-docs/bin/mkdocs build --strict` and `.venv/bin/python -m pytest script/tests container/node-red-tm/schema/tests tm-control/backend/tests -q`. Expected: both pass.
- [ ] **Step 4: Commit** (`Document Node-RED developer mode, and test it on a bench Pi`)

### Task 7: Bench check, then hand over

Not code. Follow `script/devpi/README.md` and the repo's dev-Pi rules: one bench Pi, ask the maintainer before the deploy, record it with `tmdev.py check`, keep device names out of the PR.

- [ ] **Step 1:** Stop and show the maintainer the commits. The exact-commit case needs the branch on GitHub, so ask whether to push before the bench run.
- [ ] **Step 2:** On a bench Pi with `tm_expect.dev_mode: true`, deploy with `-t node-red-tm -C dev_mode`, then run `tmdev.py test`. Before the deploy, check only whether `data/projects/` already has folders (`ls`); never read `.config.projects.json`. Check items: the run prints no project notice (the project matches); a second deploy without the flag changes nothing in `data/projects/traffic-monitor` (compare `git rev-parse HEAD` and `git status --short` before and after); editing the project's `flows.json` on the Pi and deploying again prints the notice; setting `TM_NR_PROJECTS=0` and restarting makes Node-RED log `Flows file : /data/flows.json`.
- [ ] **Step 3:** Manual items for the maintainer, in a browser: the editor on the developer unit opens with the project and no window; the editor on an ordinary unit opens with no Projects welcome window.
- [ ] **Step 4:** Draft the PR text from the template (`Closes` can't be used against `dev`; say #334 needs closing by hand), and stop for the maintainer to read it.
