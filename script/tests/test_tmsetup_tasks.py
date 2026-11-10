"""Checks on the tmsetup role's task and handler files that guard against upgrade mistakes."""

import base64
import subprocess

import pytest
from tmsetup_render import REPO, ROLE, evaluate, load_role_yaml

# Every tag whose run renders the pod, revproxy, the broker login, tm-control, or Frigate's credentials. nginx's
# auth snippets need tm-control, so a single-tag run of any of them must install and start all of these.
EDGE_TAGS = {"podman", "frigate", "node-red-tm", "go2rtc", "revproxy", "tm-control"}


def test_revproxy_restarts_after_the_pod_so_port_80_is_free():
    names = [handler["name"] for handler in load_role_yaml("handlers/main.yml")]
    assert names.index("Restart revproxy.service") > names.index("Restart traffic-monitor.service")


def test_start_services_starts_the_reverse_proxy_after_the_pod():
    start = next(
        task for task in load_role_yaml("tasks/start_services.yml")
        if task["name"] == "TMSetup - Start Services - Start and enable traffic-monitor services"
    )
    assert start["loop"].index("revproxy.service") > start["loop"].index("traffic-monitor.service")


def secrets_tasks():
    return {task["name"]: task for task in load_role_yaml("tasks/secrets.yml")}


def test_every_task_that_touches_secret_values_hides_its_output():
    for name, task in secrets_tasks().items():
        if name != "TMSetup - Secrets - Create secrets directory":
            assert task.get("no_log") is True, name


def test_existing_secrets_are_never_regenerated():
    generate = secrets_tasks()["TMSetup - Secrets - Generate missing secrets"]["ansible.builtin.copy"]
    assert generate["force"] is False


def test_secrets_are_readable_only_by_root_and_the_code_owner():
    tasks = secrets_tasks()
    directory = tasks["TMSetup - Secrets - Create secrets directory"]["ansible.builtin.file"]
    generate = tasks["TMSetup - Secrets - Generate missing secrets"]["ansible.builtin.copy"]
    assert (directory["owner"], directory["group"], directory["mode"]) == ("root", "{{ tmsetup_codegroup }}", "0750")
    assert (generate["owner"], generate["group"], generate["mode"]) == ("root", "{{ tmsetup_codegroup }}", "0640")


def test_entered_secrets_start_empty_and_are_never_regenerated():
    """A person types these in on the Device page; tmsetup only makes sure each file exists, and an empty file
    means "not set"."""
    task = secrets_tasks()["TMSetup - Secrets - Create missing entered secrets as empty files"]
    create = task["ansible.builtin.copy"]
    assert create["content"] == ""
    assert create["force"] is False
    assert (create["owner"], create["group"], create["mode"]) == ("root", "{{ tmsetup_codegroup }}", "0640")
    assert create["dest"] == "{{ tmsetup_secrets_dir }}/{{ item }}"
    assert task["loop"] == "{{ tmsetup_entered_secret_names }}"
    assert task["no_log"] is True
    assert task["become"] is True
    names = list(secrets_tasks())
    assert names.index("TMSetup - Secrets - Generate missing secrets") < names.index(task["name"])
    assert names.index(task["name"]) < names.index("TMSetup - Secrets - Read secrets")


def test_both_secret_lists_are_read_into_one_fact():
    tasks = secrets_tasks()
    combined = "tmsetup_secret_names + tmsetup_entered_secret_names"
    assert tasks["TMSetup - Secrets - Read secrets"]["loop"] == "{{ " + combined + " }}"
    fact = tasks["TMSetup - Secrets - Set secrets fact"]["ansible.builtin.set_fact"]["tmsetup_secrets"]
    assert f"dict(({combined}) | zip(" in fact
    slurped = {"results": [{"content": "c2VjcmV0LXZhbHVlCg=="}, {"content": ""}]}
    assert evaluate(fact, tmsetup_secret_names=["generated"], tmsetup_entered_secret_names=["entered"],
                    tmsetup_secrets_slurp_register=slurped) == {"generated": "secret-value", "entered": ""}


def test_the_installer_takes_no_secret_value():
    """Entered secrets come from the Device page or the root-owned file, never from an installer variable."""
    defaults = load_role_yaml("defaults/main.yml")
    role_vars = load_role_yaml("vars/main.yml")
    assert "tmsetup_thingsboard_api_key" not in defaults
    for key in [*defaults, *role_vars]:
        assert not key.endswith(("_api_key", "_access_token")), key
    templates = [*(REPO / "container").rglob("*.j2"), *(ROLE / "templates").rglob("*.j2")]
    assert templates
    for template in templates:
        assert "tmsetup_thingsboard_api_key" not in template.read_text(), template


@pytest.mark.parametrize("task_file, key, secret, handler", [
    ("tasks/node-red-tm_setup.yml", "TM_THINGSBOARD_ACCESS_TOKEN", "thingsboard_access_token",
     "Restart node-red-tm.service"),
    ("tasks/node-red-tm_setup.yml", "TM_PLATE_RECOGNIZER_TOKEN", "plate_recognizer_token",
     "Restart node-red-tm.service"),
    ("tasks/plate-recognizer_setup.yml", "TOKEN", "plate_recognizer_token", "Restart plate-recognizer.service"),
    ("tasks/plate-recognizer_setup.yml", "LICENSE_KEY", "plate_recognizer_license_key",
     "Restart plate-recognizer.service"),
])
def test_entered_secret_env_lines_are_written_on_every_run(task_file, key, secret, handler):
    """Like TM_INTERNAL_TOKEN: an existing env file isn't rewritten without -f, so each entered secret's line goes
    in on every run, from the secrets directory."""
    assert secret in load_role_yaml("vars/main.yml")["tmsetup_entered_secret_names"]
    tasks = load_role_yaml(task_file)
    names = [task["name"] for task in tasks]
    (line,) = [task for task in tasks if task.get("ansible.builtin.lineinfile", {}).get("regexp") == f"^{key}="]
    (template,) = [task for task in tasks
                   if str(task.get("ansible.builtin.template", {}).get("dest", "")).endswith(".env")
                   or "node-red-tm.env" in task.get("loop", [])]
    (stat,) = [task for task in tasks
               if str(task.get("ansible.builtin.stat", {}).get("path", "")).endswith(".env")]
    env_path = stat["ansible.builtin.stat"]["path"]
    assert line["when"] == f"{stat['register']}.stat.exists"
    assert line["no_log"] is True
    assert line["become"] is True
    assert line["notify"] == handler
    assert line["ansible.builtin.lineinfile"]["path"] == env_path
    assert line["ansible.builtin.lineinfile"]["line"] == f"{key}={{{{ tmsetup_secrets['{secret}'] }}}}"
    assert "loop" not in line and "tags" not in line
    (quadlets,) = [i for i, task in enumerate(tasks)
                   if str(task.get("ansible.builtin.template", {}).get("dest", "")).startswith("/etc/containers/systemd/")]
    assert names.index(template["name"]) < names.index(stat["name"]) < names.index(line["name"]) < quadlets


def test_secrets_are_read_on_every_run():
    main = load_role_yaml("tasks/main.yml")
    names = [task["name"] for task in main]
    secrets = main[names.index("TMSetup - Main - Generate and read device secrets")]
    assert secrets["tags"] == ["always"]
    assert names.index("TMSetup - Main - Generate and read device secrets") == names.index("TMSetup - Main - Setup base") + 1


def test_tm_control_code_lives_outside_the_code_owners_directory():
    tm_control_dir = load_role_yaml("vars/main.yml")["tmsetup_tm_control_dir"]
    assert tm_control_dir.startswith("/usr/local/")
    assert not tm_control_dir.startswith(load_role_yaml("defaults/main.yml")["tmsetup_codedir"])


def test_tm_control_files_are_root_owned():
    for task in load_role_yaml("tasks/tm-control_setup.yml"):
        for module in ("ansible.builtin.file", "ansible.builtin.copy", "ansible.builtin.template"):
            if module in task:
                assert task[module]["owner"] == "root", task["name"]


def test_frigate_and_tm_control_tags_install_tm_control_before_frigate():
    main = load_role_yaml("tasks/main.yml")
    names = [task["name"] for task in main]
    tm_control = main[names.index("TMSetup - Main - Setup tm-control command line")]
    assert set(tm_control["tags"]) == EDGE_TAGS
    assert names.index("TMSetup - Main - Setup tm-control command line") < names.index("TMSetup - Main - Setup Frigate")


def test_go2rtc_tag_gives_frigate_the_rtsp_login():
    """-t go2rtc turns on go2rtc's RTSP login, so the same run must hand it to Frigate."""
    main = load_role_yaml("tasks/main.yml")
    names = [task["name"] for task in main]
    credentials = main[names.index("TMSetup - Main - Give Frigate the go2rtc RTSP login")]
    assert set(credentials["tags"]) == EDGE_TAGS
    assert credentials["ansible.builtin.import_tasks"]["file"] == "frigate_credentials.yml"
    assert names.index("TMSetup - Main - Give Frigate the go2rtc RTSP login") == (
        names.index("TMSetup - Main - Setup Frigate") + 1
    )
    assert names.index("TMSetup - Main - Setup tm-control command line") < (
        names.index("TMSetup - Main - Give Frigate the go2rtc RTSP login")
    )


def frigate_tasks():
    return {task["name"]: task for task in load_role_yaml("tasks/frigate_setup.yml")}


def frigate_credentials_tasks():
    return {task["name"]: task for task in load_role_yaml("tasks/frigate_credentials.yml")}


FRIGATE_ENV_LINES = "TMSetup - Frigate Credentials - Add the go2rtc RTSP login, the proxy secret, and the Frigate+ key to frigate.env"


def test_frigate_credentials_skip_files_a_device_does_not_have_yet():
    """Under -t go2rtc alone, Frigate may not be installed yet."""
    tasks = frigate_credentials_tasks()
    names = list(tasks)
    stat = tasks["TMSetup - Frigate Credentials - Check for Frigate's settings files"]
    assert names[0] == "TMSetup - Frigate Credentials - Check for Frigate's settings files"
    assert stat["register"] == "tmsetup_frigate_settings_stat_register"
    assert stat["loop"] == [
        "{{ tmsetup_codedir }}/frigate/frigate.env",
        "{{ tmsetup_codedir }}/frigate/config/config.yml",
    ]
    env = tasks[FRIGATE_ENV_LINES]
    migrate = tasks["TMSetup - Frigate Credentials - Update Frigate config from older installs"]
    assert env["when"] == "tmsetup_frigate_settings_stat_register.results[0].stat.exists"
    assert migrate["when"] == "tmsetup_frigate_settings_stat_register.results[1].stat.exists"


def test_existing_frigate_env_gets_both_credentials_without_printing_them():
    task = frigate_credentials_tasks()[FRIGATE_ENV_LINES]
    assert task["no_log"] is True
    assert [item["key"] for item in task["loop"]][:2] == ["FRIGATE_GO2RTC_RTSP_USER", "FRIGATE_GO2RTC_RTSP_PASSWORD"]


def test_existing_frigate_env_gets_the_proxy_secret_without_printing_it():
    """-t frigate, -t revproxy, or any edge tag on a device whose frigate.env predates proxy auth (Review Focus 2)."""
    task = frigate_credentials_tasks()[FRIGATE_ENV_LINES]
    assert task["no_log"] is True
    item = next(item for item in task["loop"] if item["key"] == "FRIGATE_PROXY_AUTH_SECRET")
    assert item["value"] == "{{ tmsetup_secrets['frigate_proxy_secret'] }}"
    assert task["notify"] == "Restart frigate.service"


def test_existing_frigate_env_gets_the_frigate_plus_key_without_printing_it():
    """frigate.env isn't overwritten without -f, so every run writes the key set on the Device page into its line,
    and an empty secret blanks it. Entered Secrets has moved a typed key to the secrets file first."""
    task = frigate_credentials_tasks()[FRIGATE_ENV_LINES]
    assert task["no_log"] is True
    assert task["loop"][3] == {"key": "PLUS_API_KEY", "value": "{{ tmsetup_secrets['frigate_plus_api_key'] }}"}
    assert len(task["loop"]) == 4
    assert task["notify"] == "Restart frigate.service"


def test_frigate_config_update_counts_added_settings_as_a_change():
    """migrate prints "updated ..." for the camera inputs and "added proxy auth settings" alone when only those change.

    The line starts with the config's path, so a code dir whose name holds "added" or "updated" must not count.
    """
    task = frigate_credentials_tasks()["TMSetup - Frigate Credentials - Update Frigate config from older installs"]
    changed_when = task["changed_when"]
    for stdout, changed in [
        ("tm-control migrate: /c.yml: up to date", False),
        ("tm-control migrate: /srv/added-updated/c.yml: up to date", False),
        ("tm-control migrate: /c.yml: updated 1 camera input(s), added proxy auth settings (backup: /b)", True),
        ("tm-control migrate: /c.yml: added proxy auth settings (backup: /b)", True),
        ("tm-control migrate: /c.yml: updated 1 camera input(s) (backup: /b)", True),
    ]:
        assert evaluate("{{ %s }}" % changed_when, tmsetup_frigate_migrate_register={"stdout": stdout}) is changed


def test_frigate_env_template_hides_its_diff():
    """frigate.env.j2 renders the go2rtc RTSP password, and a -f run with -a diff would print it into ~/tmsetup-*.log."""
    task = frigate_tasks()["TMSetup - Frigate Setup - Create Frigate container configuration files"]
    assert task["diff"] is False


FRIGATE_TEMPLATE = "TMSetup - Frigate Setup - Create Frigate container configuration files"
MODEL_START = "TMSetup - Frigate Setup - Start with no model section to keep"
MODEL_STAT = "TMSetup - Frigate Setup - Check for an existing Frigate config"
MODEL_SLURP = "TMSetup - Frigate Setup - Read the model section -f keeps"
MODEL_BLOCK = "TMSetup - Frigate Setup - Carry the model section over -f"
MODEL_KEEP = "TMSetup - Frigate Setup - Keep the device's model section across -f"
FORCE = "tmsetup_force_configs | bool"
CORAL_FILE = load_role_yaml("vars/main.yml")["tmsetup_frigate_coral_model_file"]


def conditions(task):
    when = task.get("when", [])
    return when if isinstance(when, list) else [when]


def model_keep_task():
    return {task["name"]: task for task in frigate_tasks()[MODEL_BLOCK]["block"]}[MODEL_KEEP]


def kept_model(config_text):
    """Run the carry-over task's expression on a slurped config.yml, as Ansible would."""
    task = model_keep_task()
    slurped = {"content": base64.b64encode(config_text.encode()).decode()}
    (name, value), = task["vars"].items()
    current = evaluate(value, tmsetup_frigate_config_slurp_register=slurped)
    return evaluate(task["ansible.builtin.set_fact"]["tmsetup_frigate_model_keep"],
                    **{name: current, "tmsetup_frigate_coral_model_file": CORAL_FILE})


def test_the_model_section_is_read_only_under_force():
    """A plain run reads nothing: an operator's edit through Frigate's editor stays as it is (review focus 5)."""
    tasks = frigate_tasks()
    names = list(tasks)
    order = [MODEL_START, MODEL_STAT, MODEL_SLURP, MODEL_BLOCK]
    assert [names.index(name) for name in order] == sorted(names.index(name) for name in order)
    assert names.index(MODEL_BLOCK) < names.index(FRIGATE_TEMPLATE)

    start = tasks[MODEL_START]
    assert "when" not in start
    assert start["ansible.builtin.set_fact"] == {"tmsetup_frigate_model_keep": {}}

    stat = tasks[MODEL_STAT]
    assert conditions(stat) == [FORCE]
    assert stat["become"] is True
    assert stat["ansible.builtin.stat"] == {"path": "{{ tmsetup_codedir }}/frigate/config/config.yml", "get_checksum": False}
    assert stat["register"] == "tmsetup_frigate_config_stat_register"

    slurp = tasks[MODEL_SLURP]
    exists = "tmsetup_frigate_config_stat_register.stat.exists"
    assert conditions(slurp) == [FORCE, exists]  # in this order: the stat is skipped without -f
    assert slurp["become"] is True
    assert slurp["no_log"] is True
    assert slurp["ansible.builtin.slurp"] == {"src": "{{ tmsetup_codedir }}/frigate/config/config.yml"}
    assert slurp["register"] == "tmsetup_frigate_config_slurp_register"

    block = tasks[MODEL_BLOCK]
    assert conditions(block) == [FORCE, exists]
    assert model_keep_task()["no_log"] is True


@pytest.mark.parametrize("path", ["plus://abc", "/config/model_cache/mine.tflite"])
def test_a_chosen_model_section_is_kept(path):
    text = f"detectors:\n  coral:\n    type: edgetpu\nmodel:\n  path: {path}\n  width: 320\ncameras: {{}}\n"
    assert kept_model(text) == {"path": path, "width": 320}


def test_the_installers_own_model_section_is_not_carried():
    """After a hardware change, -t detectors -t frigate -f must re-render the detector default (review focus 2)."""
    text = f"model:\n  model_type: yolo-generic\n  path: /config/model_cache/{CORAL_FILE}\n"
    assert kept_model(text) == {}


@pytest.mark.parametrize("text", [
    "model:\n  width: 320\n",
    "model: plus://abc\n",
    "cameras: {}\n",
    "model:\n  path: ''\n",
    "model:\n  path:\n",
    "model:\n  path: 7\n",
    "model:\n",
    "",
    "- model\n",
    "just text\n",
])
def test_a_model_section_without_a_path_or_not_a_mapping_is_not_carried(text):
    assert kept_model(text) == {}


def test_an_unparseable_frigate_config_keeps_the_templates_section():
    """The run that replaces a broken config.yml mustn't stop on it, and the message quotes nothing from it."""
    block = frigate_tasks()[MODEL_BLOCK]
    (keep, debug) = block["rescue"]
    assert keep["ansible.builtin.set_fact"] == {"tmsetup_frigate_model_keep": {}}
    msg = debug["ansible.builtin.debug"]["msg"]
    assert "{{" not in msg
    assert "YAML" in msg
    with pytest.raises(Exception):
        kept_model("model: [unclosed\n")


def test_the_coral_model_file_is_one_variable():
    downloads = frigate_tasks()["TMSetup - Frigate Setup - Coral TPU model - Download the open source yolov9 model"]
    get_url = downloads["ansible.builtin.get_url"]
    assert get_url["dest"] == "{{ tmsetup_codedir }}/frigate/config/model_cache/{{ tmsetup_frigate_coral_model_file }}"
    assert get_url["url"].endswith("/{{ tmsetup_frigate_coral_model_file }}")
    assert load_role_yaml("vars/main.yml")["tmsetup_frigate_coral_model"]["path"] == (
        "/config/model_cache/{{ tmsetup_frigate_coral_model_file }}")
    template = (REPO / "container/frigate/config/config.yml.j2").read_text()
    assert "tmsetup_frigate_coral_model | to_nice_yaml" in template
    # The role and the container templates name the file only through the variable; tm-control's own code and
    # fixtures are pinned to it by their tests
    holders = [
        path.relative_to(REPO).as_posix()
        for top in (ROLE, REPO / "container")
        for path in top.rglob("*")
        if path.is_file() and not path.is_symlink() and CORAL_FILE in path.read_text(errors="ignore")
    ]
    assert holders == ["script/ansible/roles/tmsetup/vars/main.yml"]


def test_existing_frigate_config_is_migrated_as_the_code_owner():
    task = frigate_credentials_tasks()["TMSetup - Frigate Credentials - Update Frigate config from older installs"]
    argv = task["ansible.builtin.command"]["argv"]
    assert argv[:4] == ["/usr/sbin/runuser", "-u", "{{ tmsetup_codeowner }}", "--"]
    assert argv[4:6] == ["/usr/local/bin/tm-control", "migrate"]
    assert task["notify"] == "Restart frigate.service"


def test_frigate_config_update_warnings_are_shown():
    """migrate warns on stderr and exits 0; Ansible hides a successful command's stderr without -v."""
    tasks = frigate_credentials_tasks()
    names = list(tasks)
    show = tasks["TMSetup - Frigate Credentials - Show warnings from the Frigate config update"]
    assert names.index("TMSetup - Frigate Credentials - Show warnings from the Frigate config update") == (
        names.index("TMSetup - Frigate Credentials - Update Frigate config from older installs") + 1
    )
    assert show["ansible.builtin.debug"]["msg"] == "{{ tmsetup_frigate_migrate_register.stderr_lines }}"
    assert "'WARNING' in tmsetup_frigate_migrate_register.stderr | default('')" in show["when"]


def entered_secrets_tasks():
    return {task["name"]: task for task in load_role_yaml("tasks/entered_secrets.yml")}


ENTERED_SECRETS_MOVE = "TMSetup - Entered Secrets - Move them to the secrets directory"
NODE_RED_CONFIG = "{{ tmsetup_codedir }}/node-red-tm/config/config.yml"
PLATE_RECOGNIZER_ENV = "{{ tmsetup_codedir }}/plate-recognizer/plate-recognizer.env"
FRIGATE_ENV = "{{ tmsetup_codedir }}/frigate/frigate.env"


def stat_results(*exists):
    return {"results": [{"stat": {"exists": value}} for value in exists]}


def test_every_tag_that_writes_plus_api_key_moves_a_typed_key_first():
    """frigate_setup.yml (frigate.env under -f) and frigate_credentials.yml (the PLUS_API_KEY line on every run) write
    the secret file's value over a key typed into frigate.env, so any tag that runs either must run the move too."""
    main = load_role_yaml("tasks/main.yml")
    imports = {task.get("ansible.builtin.import_tasks", {}).get("file"): (index, task)
               for index, task in enumerate(main)}
    position, entered = imports["entered_secrets.yml"]
    for writer in ("frigate_setup.yml", "frigate_credentials.yml"):
        index, task = imports[writer]
        assert set(task["tags"]) <= set(entered["tags"]), f"{writer}: {set(task['tags']) - set(entered['tags'])}"
        assert position < index, writer


def test_entered_secrets_move_before_any_config_template_renders():
    """-f replaces config.yml and plate-recognizer.env from templates, and -t plate-recognizer alone rewrites the env
    file's TOKEN and LICENSE_KEY lines from the secrets, so each value's only copy moves first (Review Focus 4)."""
    main = load_role_yaml("tasks/main.yml")
    names = [task["name"] for task in main]
    (entered,) = [task for task in main if task.get("ansible.builtin.import_tasks", {}).get("file") == "entered_secrets.yml"]
    service = main[names.index("TMSetup - Main - Setup tm-control service")]
    position = names.index(entered["name"])
    assert position == names.index("TMSetup - Main - Setup tm-control service") + 1
    for later in ("frigate_setup.yml", "node-red-tm_setup.yml", "plate-recognizer_setup.yml"):
        (task,) = [task for task in main if task.get("ansible.builtin.import_tasks", {}).get("file") == later]
        assert position < names.index(task["name"]), later
    assert entered["tags"] == service["tags"] + ["plate-recognizer"]
    assert "when" not in entered  # the add-on's env file may be there even after the add-on was turned off

    tasks = entered_secrets_tasks()
    order = list(tasks)
    stat = tasks["TMSetup - Entered Secrets - Check for config files that may hold one"]
    move = tasks[ENTERED_SECRETS_MOVE]
    show = tasks["TMSetup - Entered Secrets - Show warnings from the move"]
    reread = tasks["TMSetup - Entered Secrets - Re-read the entered secrets"]
    update = tasks["TMSetup - Entered Secrets - Update the secrets fact"]
    assert order == [stat["name"], move["name"], show["name"], reread["name"], update["name"]]

    assert stat["loop"] == [NODE_RED_CONFIG, PLATE_RECOGNIZER_ENV, FRIGATE_ENV]
    assert stat["register"] == "tmsetup_entered_secrets_stat_register"
    assert move["become"] is True and reread["become"] is True
    assert reread["no_log"] is True and update["no_log"] is True
    assert "no_log" not in move  # it prints no value, and its warnings must show
    notify = move["notify"]  # Ansible takes one handler as a string or a list
    assert (notify if isinstance(notify, list) else [notify]) == ["Restart node-red-tm.service"]
    assert move["register"] == "tmsetup_entered_secrets_migrate_register"

    argv = move["ansible.builtin.command"]["argv"]
    base = ["/usr/local/bin/tm-control", "migrate", "--secrets-dir", "/etc/traffic-monitor/secrets"]
    paths = {"tmsetup_codedir": "/opt/tm", "tmsetup_secrets_dir": "/etc/traffic-monitor/secrets"}
    for exists, options in [
        ((True, True, True), ["--node-red-config", "/opt/tm/node-red-tm/config/config.yml",
                              "--plate-recognizer-env", "/opt/tm/plate-recognizer/plate-recognizer.env",
                              "--frigate-env", "/opt/tm/frigate/frigate.env"]),
        ((True, True, False), ["--node-red-config", "/opt/tm/node-red-tm/config/config.yml",
                               "--plate-recognizer-env", "/opt/tm/plate-recognizer/plate-recognizer.env"]),
        ((True, False, False), ["--node-red-config", "/opt/tm/node-red-tm/config/config.yml"]),
        ((False, True, False), ["--plate-recognizer-env", "/opt/tm/plate-recognizer/plate-recognizer.env"]),
        ((False, False, True), ["--frigate-env", "/opt/tm/frigate/frigate.env"]),
    ]:
        rendered = evaluate(argv, tmsetup_entered_secrets_stat_register=stat_results(*exists), **paths)
        assert rendered == base + options, exists
        assert "runuser" not in " ".join(rendered)  # root writes the secret files
    for exists, runs in [((False, False, False), False), ((True, False, False), True), ((False, True, False), True),
                         ((False, False, True), True), ((True, True, True), True)]:
        assert evaluate("{{ %s }}" % move["when"],
                        tmsetup_entered_secrets_stat_register=stat_results(*exists)) is runs, exists

    reread_slurp = reread["ansible.builtin.slurp"]
    assert reread["loop"] == "{{ tmsetup_entered_secret_names }}"
    assert reread_slurp["src"] == "{{ tmsetup_secrets_dir }}/{{ item }}"
    fact = update["ansible.builtin.set_fact"]["tmsetup_secrets"]
    slurped = {"results": [{"content": "dGItcGxhY2Vob2xkZXItMzQ1Cg=="}, {"content": ""}]}  # tb-placeholder-345
    assert evaluate(fact, tmsetup_secrets={"generated": "kept", "thingsboard_access_token": ""},
                    tmsetup_entered_secret_names=["thingsboard_access_token", "plate_recognizer_token"],
                    tmsetup_entered_secrets_slurp_register=slurped) == {
        "generated": "kept", "thingsboard_access_token": "tb-placeholder-345", "plate_recognizer_token": ""}


def test_a_typed_frigate_plus_key_moves_before_frigate_env_is_written():
    """Under -t frigate, frigate_setup.yml renders frigate.env (with -f) and frigate_credentials.yml writes its
    PLUS_API_KEY line from the secret, so a key typed into the file must be in the secret file by then."""
    main = load_role_yaml("tasks/main.yml")

    def position(file):
        (index,) = [index for index, task in enumerate(main)
                    if task.get("ansible.builtin.import_tasks", {}).get("file") == file]
        return index

    for file in ("entered_secrets.yml", "frigate_setup.yml", "frigate_credentials.yml"):
        assert "frigate" in main[position(file)]["tags"], file
    assert position("entered_secrets.yml") < position("frigate_setup.yml") < position("frigate_credentials.yml")


def test_entered_secrets_move_counts_any_moved_line_as_a_change():
    """One run prints a line per file; a change in either counts, whichever line comes last."""
    changed_when = entered_secrets_tasks()[ENTERED_SECRETS_MOVE]["changed_when"]
    for lines, changed in [
        (["tm-control migrate: /c.yml: up to date"], False),
        (["tm-control migrate: /c.yml: up to date", "tm-control migrate: /p.env: up to date"], False),
        (["tm-control migrate: /moved/c.yml: up to date"], False),
        (["tm-control migrate: /c.yml: moved thingsboard.access_token to the secrets file (backup: /b)",
          "tm-control migrate: /p.env: up to date"], True),
        (["tm-control migrate: /c.yml: up to date", "tm-control migrate: /p.env: moved TOKEN to the secrets files"],
         True),
        (["tm-control migrate: /c.yml: removed the empty thingsboard.access_token (backup: /b)"], True),
    ]:
        register = {"stdout_lines": lines, "stdout": "\n".join(lines)}
        assert evaluate("{{ %s }}" % changed_when, tmsetup_entered_secrets_migrate_register=register) is changed, lines


def test_entered_secrets_warnings_are_shown():
    """migrate warns on stderr and exits 0; Ansible hides a successful command's stderr without -v."""
    show = entered_secrets_tasks()["TMSetup - Entered Secrets - Show warnings from the move"]
    assert show["ansible.builtin.debug"]["msg"] == "{{ tmsetup_entered_secrets_migrate_register.stderr_lines }}"
    assert "'WARNING' in tmsetup_entered_secrets_migrate_register.stderr | default('')" in show["when"]


def test_frigate_setup_no_longer_handles_the_rtsp_login():
    assert not [name for name in frigate_tasks() if "RTSP credentials" in name or "older installs" in name]


def test_go2rtc_config_with_the_password_is_root_only_and_never_diffed():
    task = next(t for t in load_role_yaml("tasks/go2rtc_setup.yml") if t["name"] == "TMSetup - Go2rtc Setup - Setup go2rtc rpicam settings")
    template = task["ansible.builtin.template"]
    assert (template["src"], template["owner"], template["mode"]) == ("go2rtc.yaml.j2", "root", "0600")
    assert task["diff"] is False


def mqtt_broker_tasks():
    return {task["name"]: task for task in load_role_yaml("tasks/mqtt_broker.yml")}


POD_AND_PROXY_TAGS = {"podman", "frigate", "node-red-tm", "revproxy", "go2rtc"}


def test_the_pod_and_the_reverse_proxy_always_update_together():
    """On a device installed before M1, a single-tag run must not pair the new pod with the old in-pod nginx, or the reverse."""
    main = load_role_yaml("tasks/main.yml")
    names = [task["name"] for task in main]
    for name in ("TMSetup - Main - Setup Podman",
                 "TMSetup - Main - Read the MQTT broker login",
                 "TMSetup - Main - Setup NGinx Reverse Proxy"):
        assert POD_AND_PROXY_TAGS <= set(main[names.index(name)]["tags"]), name
    assert names.index("TMSetup - Main - Setup Podman") < names.index("TMSetup - Main - Setup NGinx Reverse Proxy")
    assert POD_AND_PROXY_TAGS <= set(main[names.index("TMSetup - Main - Start Services")]["tags"])


def test_broker_login_is_read_on_every_run_that_renders_the_pod():
    main = load_role_yaml("tasks/main.yml")
    names = [task["name"] for task in main]
    login = main[names.index("TMSetup - Main - Read the MQTT broker login")]
    assert set(login["tags"]) == EDGE_TAGS
    secrets = names.index("TMSetup - Main - Generate and read device secrets")
    assert names.index("TMSetup - Main - Read the MQTT broker login") == secrets + 1


def test_broker_login_tasks_hide_the_values():
    for name, task in mqtt_broker_tasks().items():
        if any(module in task for module in ("ansible.builtin.slurp", "ansible.builtin.set_fact", "ansible.builtin.lineinfile")):
            assert task.get("no_log") is True, name


def test_both_broker_keys_are_written_even_when_blank():
    """Node-RED keeps a missing variable's ${...} text, and the broker would then require it as the login."""
    task = mqtt_broker_tasks()["TMSetup - MQTT Broker - Write the broker login to node-red-tm.env"]
    assert [item["key"] for item in task["loop"]] == ["TM_MQTT_BROKER_USERNAME", "TM_MQTT_BROKER_PASSWORD"]
    assert "tmsetup_mqtt_lan_open" not in str(task.get("when", ""))


def test_a_login_change_restarts_both_ends():
    tasks = mqtt_broker_tasks()
    for name in ("TMSetup - MQTT Broker - Write the broker login to node-red-tm.env",
                 "TMSetup - MQTT Broker - Give Frigate the broker login"):
        assert set(tasks[name]["notify"]) == {"Restart frigate.service", "Restart node-red-tm.service"}, name


def test_node_red_env_template_hides_its_diff():
    """node-red-tm.env.j2 renders the broker login, and a -f run with -a diff would print it into ~/tmsetup-*.log."""
    task = next(t for t in load_role_yaml("tasks/node-red-tm_setup.yml")
                if t["name"] == "TMSetup - Node-RED-TM Setup - Create Node-RED-TM Configs")
    assert task["diff"] is False


def test_plate_recognizer_env_template_hides_its_diff():
    """plate-recognizer.env.j2 renders the token and license key; a -f run with -a diff would print them."""
    task = next(t for t in load_role_yaml("tasks/plate-recognizer_setup.yml")
                if t["name"] == "TMSetup - plate-recognizer Setup - Create plate-recognizer environment file")
    assert task["diff"] is False


def test_node_red_token_key_is_written_on_every_run_without_printing_it():
    """A node-red-tm.env from before the proxy login has no TM_NR_TOKEN_KEY, and -t node-red-tm doesn't rewrite
    the file without -f, so the key goes in on its own (Review Focus 4). A changed key restarts Node-RED."""
    tasks = load_role_yaml("tasks/node-red-tm_setup.yml")
    names = [task["name"] for task in tasks]
    (key,) = [task for task in tasks if task.get("ansible.builtin.lineinfile", {}).get("regexp") == "^TM_NR_TOKEN_KEY="]
    stat = tasks[names.index("TMSetup - Node-RED-TM Setup - Check for node-red-tm.env")]
    assert stat["ansible.builtin.stat"]["path"] == "{{ tmsetup_codedir }}/node-red-tm/node-red-tm.env"
    assert key["when"] == f"{stat['register']}.stat.exists"
    assert key["no_log"] is True
    assert key["become"] is True
    assert key["notify"] == "Restart node-red-tm.service"
    assert key["ansible.builtin.lineinfile"]["path"] == "{{ tmsetup_codedir }}/node-red-tm/node-red-tm.env"
    assert key["ansible.builtin.lineinfile"]["line"] == "TM_NR_TOKEN_KEY={{ tmsetup_secrets['node_red_token_key'] }}"
    assert "loop" not in key and "tags" not in key
    quadlets = names.index("TMSetup - Node-RED-TM Setup - Create Podman container and build Quadlets for tm-node-red")
    assert names.index(stat["name"]) < names.index(key["name"]) < quadlets
    main = load_role_yaml("tasks/main.yml")
    setup = next(task for task in main if task.get("ansible.builtin.import_tasks", {}).get("file") == "node-red-tm_setup.yml")
    assert "node-red-tm" in setup["tags"]


def test_node_red_env_gains_the_internal_token_on_every_run():
    """Like TM_NR_TOKEN_KEY: an existing node-red-tm.env isn't rewritten without -f, and Node-RED refuses every
    /tm-internal/ request without TM_INTERNAL_TOKEN, so the token goes in on every -t node-red-tm run."""
    assert "node_red_internal_token" in load_role_yaml("vars/main.yml")["tmsetup_secret_names"]
    tasks = load_role_yaml("tasks/node-red-tm_setup.yml")
    names = [task["name"] for task in tasks]
    (token,) = [task for task in tasks
                if task.get("ansible.builtin.lineinfile", {}).get("regexp") == "^TM_INTERNAL_TOKEN="]
    stat = tasks[names.index("TMSetup - Node-RED-TM Setup - Check for node-red-tm.env")]
    assert token["when"] == f"{stat['register']}.stat.exists"
    assert token["no_log"] is True
    assert token["become"] is True
    assert token["notify"] == "Restart node-red-tm.service"
    assert token["ansible.builtin.lineinfile"]["path"] == "{{ tmsetup_codedir }}/node-red-tm/node-red-tm.env"
    assert token["ansible.builtin.lineinfile"]["line"] == (
        "TM_INTERNAL_TOKEN={{ tmsetup_secrets['node_red_internal_token'] }}")
    assert "loop" not in token and "tags" not in token
    quadlets = names.index("TMSetup - Node-RED-TM Setup - Create Podman container and build Quadlets for tm-node-red")
    assert names.index(stat["name"]) < names.index(token["name"]) < quadlets


def test_installer_says_when_an_update_closes_mqtt_to_the_network():
    tasks = mqtt_broker_tasks()
    stat = tasks["TMSetup - MQTT Broker - Check for the installed pod unit"]
    assert stat["ansible.builtin.stat"]["path"] == "/etc/containers/systemd/traffic-monitor.pod"
    assert stat["register"] == "tmsetup_mqtt_pod_stat_register"
    read = tasks["TMSetup - MQTT Broker - Read the installed pod unit"]
    assert read["ansible.builtin.slurp"]["src"] == "/etc/containers/systemd/traffic-monitor.pod"
    assert read["register"] == "tmsetup_mqtt_pod_register"
    assert "tmsetup_mqtt_pod_stat_register.stat.exists" in str(read["when"])
    notice = tasks["TMSetup - MQTT Broker - Say that port 1883 closes to the network"]
    when = notice["when"] if isinstance(notice["when"], list) else [notice["when"]]
    assert "not tmsetup_mqtt_lan_open" in when
    assert "tmsetup_mqtt_pod_stat_register.stat.exists" in when
    assert "PublishPort=1883:1883" in str(when)
    assert "-t node-red-tm -C mqtt_lan" in notice["ansible.builtin.debug"]["msg"]
    names = list(tasks)
    assert names.index("TMSetup - MQTT Broker - Open port 1883 only with a login") < names.index(
        "TMSetup - MQTT Broker - Say that port 1883 closes to the network")


def main_tasks():
    return {task["name"]: task for task in load_role_yaml("tasks/main.yml")}


def tm_control_service_tasks():
    return {task["name"]: task for task in load_role_yaml("tasks/tm-control_service.yml")}


def tm_control_setup_tasks():
    return {task["name"]: task for task in load_role_yaml("tasks/tm-control_setup.yml")}


def test_everything_the_login_depends_on_renders_together():
    """A -t revproxy or -t frigate run on an M2 device must leave nginx's auth snippets a running tm-control."""
    main = main_tasks()
    for name in ["TMSetup - Main - Read the MQTT broker login", "TMSetup - Main - Setup Podman",
                 "TMSetup - Main - Setup tm-control command line", "TMSetup - Main - Setup tm-control service",
                 "TMSetup - Main - Give Frigate the go2rtc RTSP login", "TMSetup - Main - Setup NGinx Reverse Proxy",
                 "TMSetup - Main - Start Services", "TMSetup - Main - Show the setup code"]:
        assert EDGE_TAGS <= set(main[name]["tags"]), name


def test_tm_control_service_is_installed_before_frigate_and_after_the_package():
    main = main_tasks()
    names = list(main)
    service = names.index("TMSetup - Main - Setup tm-control service")
    assert service == names.index("TMSetup - Main - Setup tm-control command line") + 1
    assert service < names.index("TMSetup - Main - Setup Frigate")
    assert main["TMSetup - Main - Setup tm-control service"]["ansible.builtin.import_tasks"]["file"] == (
        "tm-control_service.yml")


def test_new_secrets_are_generated():
    names = load_role_yaml("vars/main.yml")["tmsetup_secret_names"]
    assert {"tm_control_session_key", "frigate_proxy_secret", "node_red_token_key"} <= set(names)
    assert "go2rtc_rtsp_password" in names


def test_start_services_starts_tm_control_before_the_reverse_proxy():
    start = next(
        task for task in load_role_yaml("tasks/start_services.yml")
        if task["name"] == "TMSetup - Start Services - Start and enable traffic-monitor services"
    )
    assert start["loop"] == ["go2rtc_server.service", "traffic-monitor.service", "tm-control.service", "revproxy.service"]


def test_tm_control_restart_handler_exists():
    handlers = {handler["name"]: handler for handler in load_role_yaml("handlers/main.yml")}
    restart = handlers["Restart tm-control.service"]["ansible.builtin.systemd_service"]
    assert restart["name"] == "tm-control.service"
    assert restart["daemon_reload"] is True
    assert restart["state"] == "{{ 'stopped' if tmsetup_restart_required else 'restarted' }}"


def test_changes_to_what_tm_control_reads_at_startup_restart_it():
    """tm-control reads its code, EULA, manifest, and units only when it starts."""
    setup, service = tm_control_setup_tasks(), tm_control_service_tasks()
    for name in ["TMSetup - tm-control Setup - Copy the tm_control package",
                 "TMSetup - tm-control Setup - Install pinned requirements",
                 "TMSetup - tm-control Setup - Install the tm-control command",
                 "TMSetup - tm-control Setup - Copy the job scripts"]:
        assert setup[name]["notify"] == "Restart tm-control.service", name
    for name in ["TMSetup - tm-control Service - Install the unit files",
                 "TMSetup - tm-control Service - Write the install manifest"]:
        assert service[name]["notify"] == "Restart tm-control.service", name


def test_tm_control_units_go_to_systemd_and_the_rules_to_polkit():
    tasks = tm_control_service_tasks()
    template = tasks["TMSetup - tm-control Service - Install the unit files"]["ansible.builtin.template"]
    assert (template["src"], template["dest"]) == ("tm-control/{{ item }}.j2", "/etc/systemd/system/{{ item }}")
    assert (template["owner"], template["mode"]) == ("root", "0644")
    rules = tasks["TMSetup - tm-control Service - Install the polkit rules"]["ansible.builtin.template"]
    assert rules["dest"] == "/etc/polkit-1/rules.d/50-traffic-monitor.rules"
    assert (rules["owner"], rules["mode"]) == ("root", "0644")
    assert "polkitd" in load_role_yaml("vars/main.yml")["tmsetup_packages"]


def test_both_job_units_are_installed():
    units = tm_control_service_tasks()["TMSetup - tm-control Service - Install the unit files"]
    assert units["loop"] == ["tm-control.service", "tm-job-system-password.service", "tm-job-set-secret.service"]


def test_configuration_directory_is_root_and_the_code_group_only():
    """Like the secrets directory inside it: tm-control reads the manifest through the code group."""
    task = tm_control_service_tasks()["TMSetup - tm-control Service - Create the configuration directory"]
    directory = task["ansible.builtin.file"]
    assert (directory["path"], directory["state"]) == ("{{ tmsetup_etc_dir }}", "directory")
    assert (directory["owner"], directory["group"], directory["mode"]) == ("root", "{{ tmsetup_codegroup }}", "0750")


def test_setup_code_tasks_hide_the_code_and_write_a_root_only_file():
    tasks = tm_control_service_tasks()
    code_tasks = [n for n in tasks if "setup code" in n.lower() and "Check" not in n and "Remove" not in n]
    assert len(code_tasks) == 3
    for name in code_tasks:
        assert tasks[name].get("no_log") is True, name
    copy = tasks["TMSetup - tm-control Service - Generate a setup code"]["ansible.builtin.copy"]
    assert (copy["dest"], copy["owner"], copy["group"], copy["mode"]) == (
        "{{ tmsetup_etc_dir }}/setup-code", "root", "root", "0600")
    assert copy["force"] is False
    assert "community.general.random_string" in copy["content"]
    assert "ABCDEFGHJKLMNPQRSTUVWXYZ23456789" in copy["content"]


def test_setup_code_is_generated_only_while_unclaimed_and_missing():
    task = tm_control_service_tasks()["TMSetup - tm-control Service - Generate a setup code"]
    assert task["when"] == [
        "tmsetup_tm_control_claim_register.stdout == 'unclaimed'",
        "not tmsetup_tm_control_setup_code_stat_register.stat.exists",
    ]


def test_setup_code_is_removed_once_the_device_is_claimed():
    task = tm_control_service_tasks()["TMSetup - tm-control Service - Remove the setup code once the device is claimed"]
    assert task["ansible.builtin.file"] == {"path": "{{ tmsetup_etc_dir }}/setup-code", "state": "absent"}
    assert task["when"] == "tmsetup_tm_control_claim_register.stdout == 'claimed'"


def test_setup_code_is_pushed_to_tm_control_on_every_unclaimed_run():
    """A run that wrote the code file but failed before handing it over is repaired by the next run."""
    task = tm_control_service_tasks()["TMSetup - tm-control Service - Give tm-control the setup code"]
    command = task["ansible.builtin.command"]
    assert "creates" not in command and "removes" not in command
    assert command["argv"][-1] == "set-setup-code"
    assert command["stdin"] == "{{ tmsetup_tm_control_setup_code_register.content | b64decode | trim }}"
    assert task["when"] == "tmsetup_tm_control_claim_register.stdout == 'unclaimed'"
    assert task["changed_when"] is False


def test_claim_status_is_read_before_any_setup_code_task():
    tasks = tm_control_service_tasks()
    names = list(tasks)
    check = tasks["TMSetup - tm-control Service - Check whether the device is claimed"]
    assert check["register"] == "tmsetup_tm_control_claim_register"
    assert check["changed_when"] is False
    assert names.index("TMSetup - tm-control Service - Create the state directory") < names.index(
        "TMSetup - tm-control Service - Check whether the device is claimed")
    for name in names:
        if "setup code" in name.lower():
            assert names.index(name) > names.index("TMSetup - tm-control Service - Check whether the device is claimed")


def test_state_commands_run_as_the_code_owner():
    commands = [task["ansible.builtin.command"]["argv"] for task in tm_control_service_tasks().values()
                if "ansible.builtin.command" in task and "/usr/local/bin/tm-control" in task["ansible.builtin.command"]["argv"]]
    assert len(commands) == 2
    for argv in commands:
        assert argv[:5] == ["/usr/sbin/runuser", "-u", "{{ tmsetup_codeowner }}", "--", "/usr/local/bin/tm-control"]


def test_state_directory_belongs_to_the_code_owner():
    state = tm_control_service_tasks()["TMSetup - tm-control Service - Create the state directory"]["ansible.builtin.file"]
    assert (state["path"], state["state"], state["owner"], state["group"], state["mode"]) == (
        "/var/lib/tm-control", "directory", "{{ tmsetup_codeowner }}", "{{ tmsetup_codegroup }}", "0700")


def test_manifest_is_root_owned_and_readable_by_the_code_owner():
    manifest = tm_control_service_tasks()["TMSetup - tm-control Service - Write the install manifest"]
    template = manifest["ansible.builtin.template"]
    assert (template["src"], template["dest"]) == ("tm-control/manifest.json.j2", "{{ tmsetup_etc_dir }}/manifest.json")
    assert (template["owner"], template["group"], template["mode"]) == ("root", "{{ tmsetup_codegroup }}", "0640")


def test_git_facts_never_fail_the_install():
    """The repo may belong to another user, and git then refuses it (safe.directory); the manifest says unknown."""
    tasks = tm_control_service_tasks()
    for name in ["TMSetup - tm-control Service - Read the git commit", "TMSetup - tm-control Service - Read the git branch"]:
        task = tasks[name]
        assert task["become"] is False, name
        assert task["delegate_to"] == "localhost", name
        assert task["changed_when"] is False, name
        assert task["failed_when"] is False, name
        assert task["ansible.builtin.command"]["argv"][:3] == ["git", "-C", "{{ playbook_dir }}/../.."], name


def test_job_script_is_installed_root_owned_outside_codedir():
    tasks = tm_control_setup_tasks()
    copy = tasks["TMSetup - tm-control Setup - Copy the job scripts"]["ansible.builtin.copy"]
    libexec = load_role_yaml("vars/main.yml")["tmsetup_libexec_dir"]
    assert libexec == "/usr/local/libexec/traffic-monitor"
    assert copy["src"] == "tm-control/jobs/"
    assert copy["dest"] == "{{ tmsetup_libexec_dir }}/"
    assert (copy["owner"], copy["group"], copy["mode"]) == ("root", "root", "0755")
    assert "{{ tmsetup_libexec_dir }}" in tasks["TMSetup - tm-control Setup - Create install directories"]["loop"]


def test_setup_code_notice_is_the_last_task_and_runs_only_while_unclaimed():
    main = load_role_yaml("tasks/main.yml")
    notice = main[-1]
    assert notice["name"] == "TMSetup - Main - Show the setup code"
    assert [task["name"] for task in main][-2] == "TMSetup - Main - Start Services"
    assert notice["when"] == "tmsetup_tm_control_claim_register.stdout | default('') == 'unclaimed'"
    assert "no_log" not in notice  # the one place the installer shows the code, on purpose
    msg = notice["ansible.builtin.debug"]["msg"]
    assert "{{ tmsetup_tm_control_setup_code_register.content | b64decode | trim }}" in msg
    assert "The code works once." in msg


def revproxy_tasks():
    return {task["name"]: task for task in load_role_yaml("tasks/revproxy_setup.yml")}


def test_revproxy_renders_every_snippet_in_the_check_and_the_deployment():
    role_vars = load_role_yaml("vars/main.yml")
    snippets, locations = role_vars["tmsetup_revproxy_snippets"], role_vars["tmsetup_revproxy_locations"]
    tasks = revproxy_tasks()
    check_block = {task["name"]: task for task in tasks["TMSetup - revproxy Setup - Check NGinx config before deploying it"]["block"]}
    check = check_block["TMSetup - revproxy Setup - Render NGinx config for the check"]
    assert evaluate(check["loop"], tmsetup_revproxy_snippets=snippets, tmsetup_revproxy_locations=locations) == (
        ["nginx.conf"] + [f"tm/snippets/{name}" for name in snippets] + [f"tm/locations/{name}" for name in locations])
    deployed = tasks["TMSetup - revproxy Setup - Create NGinx config file"]
    assert evaluate(deployed["loop"], tmsetup_revproxy_snippets=snippets) == (
        ["revproxy/nginx.conf"] + [f"revproxy/tm/snippets/{name}" for name in snippets])
    assert deployed["ansible.builtin.template"]["src"] == "container/{{ item }}.j2"


def test_revproxy_no_longer_writes_the_hand_written_home_page():
    tasks = revproxy_tasks()
    names = list(tasks)
    assert "TMSetup - revproxy Setup - Create NGinx home page" not in names
    # nginx serves the bind-mounted html directory at once, so both run only after the check passed
    check = names.index("TMSetup - revproxy Setup - Check NGinx config before deploying it")
    assert check < names.index("TMSetup - revproxy Setup - Remove the old home page")
    assert check < names.index("TMSetup - revproxy Setup - Create the rescue page")
    assert tasks["TMSetup - revproxy Setup - Remove the old home page"]["ansible.builtin.file"] == {
        "path": "{{ tmsetup_codedir }}/revproxy/html/index.html", "state": "absent"}
    page = tasks["TMSetup - revproxy Setup - Create the rescue page"]["ansible.builtin.template"]
    assert (page["src"], page["dest"], page["mode"]) == (
        "container/revproxy/html/unavailable.html.j2", "{{ tmsetup_codedir }}/revproxy/html/unavailable.html", "0644")


COPY_UI = "TMSetup - revproxy Setup - Copy the control app's UI sources"


def ui_copy_tasks():
    block = revproxy_tasks()[COPY_UI]
    return {task["name"]: task for task in block["block"] + block["always"]}


def test_node_image_for_the_ui_build_is_pinned():
    assert load_role_yaml("vars/main.yml")["tmsetup_node_image"] == "docker.io/library/node:22.23.4-alpine"


def test_rsync_is_not_installed_for_the_ui_copy():
    """The UI sources travel as an archive (synchronize can't use a sudo password), so nothing needs rsync."""
    assert "rsync" not in load_role_yaml("vars/main.yml")["tmsetup_packages"]


def test_ui_sources_are_copied_without_node_modules_before_the_image_build():
    names = list(revproxy_tasks())
    assert names.index(COPY_UI) < names.index("TMSetup - revproxy Setup - Create NGinx Containerfile")
    tasks = ui_copy_tasks()
    # The script's own behavior (git's file list, the no-git fallback, the exclusions) is in test_pack_ui_sources.py
    pack = tasks["TMSetup - revproxy Setup - Pack the UI sources"]
    assert pack["ansible.builtin.command"]["argv"] == [
        "bash",
        "{{ role_path }}/files/pack-ui-sources.sh",
        "{{ role_path }}/files/tm-control",
        "{{ tmsetup_revproxy_ui_archive_register['path'] }}",
    ]
    assert pack["changed_when"] is False
    unpack = tasks["TMSetup - revproxy Setup - Unpack the UI sources"]
    assert unpack["become"] is True
    assert unpack["ansible.builtin.unarchive"] == {
        "src": "{{ tmsetup_revproxy_ui_archive_register['path'] }}",
        "dest": "{{ tmsetup_codedir }}/revproxy",
        "owner": "{{ tmsetup_codeowner }}",
        "group": "{{ tmsetup_codegroup }}",
        "mode": "u=rwX,g=rX,o=",
        "list_files": True,
    }


def test_ui_archive_is_made_and_removed_on_the_controller_without_sudo():
    """A remote install's controller is a laptop: no sudo there, and the archive goes in its temp directory."""
    tasks = ui_copy_tasks()
    for name in ("TMSetup - revproxy Setup - Create a temporary file for the UI sources",
                 "TMSetup - revproxy Setup - Pack the UI sources",
                 "TMSetup - revproxy Setup - Remove the temporary UI sources file"):
        assert (tasks[name]["delegate_to"], tasks[name]["become"]) == ("localhost", False), name
    assert revproxy_tasks()[COPY_UI]["always"][0]["name"] == "TMSetup - revproxy Setup - Remove the temporary UI sources file"


def test_ui_sources_no_longer_in_the_repo_are_deleted_from_the_device():
    tasks = ui_copy_tasks()
    remove = tasks["TMSetup - revproxy Setup - Remove UI sources that are no longer in the repo"]
    assert remove["ansible.builtin.file"]["state"] == "absent"
    # Files only: the archive lists directories too, but only files are compared, so a directory is never deleted
    # with everything in it.
    assert tasks["TMSetup - revproxy Setup - Find the deployed UI sources"]["ansible.builtin.find"]["file_type"] == "file"
    deployed = {"files": [{"path": f"/opt/traffic-monitor/revproxy/ui/{name}"}
                          for name in ("package.json", "src/main.ts", "src/old.ts", "old-dir/x.ts")]}
    for unpacked in (["ui/package.json", "ui/src/main.ts"],  # files alone
                     ["ui/", "ui/package.json", "ui/src/", "ui/src/main.ts"]):  # files and their directories
        stale = evaluate(remove["loop"], tmsetup_codedir="/opt/traffic-monitor",
                         tmsetup_revproxy_ui_find_register=deployed,
                         tmsetup_revproxy_ui_unpack_register={"files": unpacked})
        assert sorted(stale) == ["ui/old-dir/x.ts", "ui/src/old.ts"]  # `difference` doesn't keep order


def test_ui_source_changes_restart_the_proxy():
    tasks = ui_copy_tasks()
    for name in ("TMSetup - revproxy Setup - Unpack the UI sources",
                 "TMSetup - revproxy Setup - Remove UI sources that are no longer in the repo"):
        assert tasks[name]["notify"] == "Restart revproxy.service", name


def test_build_context_ignore_file_is_copied_before_the_build():
    tasks = revproxy_tasks()
    names = list(tasks)
    copy = tasks["TMSetup - revproxy Setup - Create NGinx build ignore file"]["ansible.builtin.copy"]
    assert (copy["src"], copy["dest"]) == ("container/revproxy/.containerignore",
                                           "{{ tmsetup_codedir }}/revproxy/.containerignore")
    assert names.index("TMSetup - revproxy Setup - Create NGinx build ignore file") < names.index(
        "TMSetup - revproxy Setup - Build container")


BUILD_INPUTS = ("tmsetup_revproxy_ui_unpack_register", "tmsetup_revproxy_ui_stale_register",
                "tmsetup_revproxy_containerfile_register", "tmsetup_revproxy_containerignore_register")


@pytest.mark.parametrize("changed", BUILD_INPUTS)
def test_image_is_rebuilt_when_its_build_inputs_change(changed):
    """A .build unit that already ran stays active, so `started` alone would keep the old image until a reboot."""
    build = revproxy_tasks()["TMSetup - revproxy Setup - Build container"]["ansible.builtin.systemd_service"]
    registers = {name: {"changed": name == changed} for name in BUILD_INPUTS}
    assert evaluate(build["state"], **registers) == "restarted"


def test_image_build_is_only_started_when_nothing_changed():
    build = revproxy_tasks()["TMSetup - revproxy Setup - Build container"]["ansible.builtin.systemd_service"]
    assert evaluate(build["state"], **{name: {"changed": False} for name in BUILD_INPUTS}) == "started"
    tasks = revproxy_tasks()
    for name, register in (("TMSetup - revproxy Setup - Create NGinx Containerfile", BUILD_INPUTS[2]),
                           ("TMSetup - revproxy Setup - Create NGinx build ignore file", BUILD_INPUTS[3])):
        assert tasks[name]["register"] == register, name
    copy = ui_copy_tasks()
    assert copy["TMSetup - revproxy Setup - Unpack the UI sources"]["register"] == BUILD_INPUTS[0]
    assert copy["TMSetup - revproxy Setup - Remove UI sources that are no longer in the repo"]["register"] == BUILD_INPUTS[1]


def test_ui_source_directory_belongs_to_the_code_owner():
    directories = revproxy_tasks()["TMSetup - revproxy Setup - Create NGinx directory"]["loop"]
    assert {"path": "{{ tmsetup_codedir }}/revproxy/ui", "mode": "0750"} in directories


@pytest.mark.parametrize("line, found", [
    ("Bus 002 Device 002: ID 1a6e:089a Global Unichip Corp.", True),  # before the runtime loads the firmware
    ("Bus 002 Device 003: ID 18d1:9302 Google Inc.", True),  # after it (#217)
    ("Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub", False),
])
def test_coral_usb_probe_matches_both_usb_ids(line, found):
    """detectors_check.yml runs check_exists in a shell; here lsusb is a function that prints one synthetic line."""
    check_exists = load_role_yaml("defaults/main.yml")["tmsetup_detectors"]["edgetpu_usb"]["check_exists"]
    assert check_exists.startswith("lsusb | ")
    script = f'lsusb() {{ printf "%s\\n" "$LSUSB_LINE"; }}\n{check_exists} >/dev/null'
    result = subprocess.run(["bash", "-c", script], env={"LSUSB_LINE": line, "PATH": "/usr/bin:/bin"}, check=False)
    assert (result.returncode == 0) is found


def wifi_tasks():
    return {task["name"]: task for task in load_role_yaml("tasks/wifi_setup.yml")}


def wanted_country(given, read_rc, read_stdout):
    task = wifi_tasks()["TMSetup - WiFi Setup - Set the Wi-Fi country"]
    return evaluate(
        task["vars"]["tmsetup_wifi_country_wanted"],
        tmsetup_wifi_country=given,
        tmsetup_wifi_country_register={"rc": read_rc, "stdout": read_stdout},
    )


def test_a_given_country_wins_and_is_upper_cased():
    assert wanted_country("gb", 0, "US") == "GB"


def test_the_devices_own_country_is_kept():
    assert wanted_country("", 0, "DE") == "DE"


def test_a_device_without_a_country_gets_us():
    assert wanted_country("", 1, "") == "US"


def test_the_wifi_tools_are_installed_before_anything_uses_them():
    names = list(wifi_tasks())
    assert names[0] == "TMSetup - WiFi Setup - Install the Wi-Fi tools"


def wifi_task_list():
    return load_role_yaml("tasks/wifi_setup.yml")


HOTSPOT_TASK = "TMSetup - WiFi Setup - Create or adopt the hotspot"
RADIO_TASK = "TMSetup - WiFi Setup - Turn the Wi-Fi radio on"


def test_the_old_wifi_check_is_removed_from_upgraded_devices():
    tasks = wifi_task_list()
    cron = next(t for t in tasks if "ansible.builtin.cron" in t)
    assert cron["ansible.builtin.cron"]["state"] == "absent"
    assert cron["ansible.builtin.cron"]["name"] == "Traffic Monitor Wifi Check"
    sudoers = next(t for t in tasks if "community.general.sudoers" in t)
    assert sudoers["community.general.sudoers"]["state"] == "absent"
    removed = [
        t for t in tasks
        if "ansible.builtin.file" in t and t["ansible.builtin.file"].get("state") == "absent"
    ]
    assert len(removed) == 1
    assert removed[0]["ansible.builtin.file"]["path"] == "{{ tmsetup_codedir }}/utils/{{ item }}"
    assert sorted(removed[0]["loop"]) == ["network-wlan-ap", "wlan_check.sh"]


def test_the_old_wifi_scripts_are_gone_from_the_repo():
    assert not (REPO / "utils" / "wlan_check.sh").exists()
    assert not (REPO / "utils" / "network-wlan-ap").exists()
    for path in ("tasks/wifi_setup.yml", "handlers/main.yml"):
        for task in load_role_yaml(path):
            text = str(task)
            if "state': 'absent'" in text:
                continue
            assert "wlan_check" not in text and "network-wlan-ap" not in text, task["name"]


def test_the_firewall_and_dns_files_come_before_the_hotspot_profile():
    tasks = wifi_task_list()
    index = {t["name"]: i for i, t in enumerate(tasks)}

    def dest_of(task):
        for module in ("ansible.builtin.template", "ansible.builtin.copy"):
            if module in task:
                return task[module]["dest"]
        return None

    position = {dest_of(t): i for i, t in enumerate(tasks) if dest_of(t)}
    hotspot = index[HOTSPOT_TASK]
    assert position["{{ tmsetup_etc_dir }}/hotspot-firewall.nft"] < hotspot
    assert position["/etc/NetworkManager/dnsmasq-shared.d/tm-hotspot.conf"] < hotspot
    assert position["/etc/systemd/system/tm-hotspot-firewall.service"] < hotspot
    assert position["{{ tmsetup_libexec_dir }}/tm-hotspot-setup"] < hotspot
    assert index[RADIO_TASK] > hotspot


def test_the_hotspot_task_hides_its_output_and_reports_change_from_the_helper():
    task = wifi_tasks()[HOTSPOT_TASK]
    assert task["no_log"] is True
    assert task["register"] == "tmsetup_wifi_hotspot_register"
    assert "from_json" in task["changed_when"] and "changed" in task["changed_when"]
    argv = task["ansible.builtin.command"]["argv"]
    assert argv[:3] == ["/usr/bin/python3", "-EP", "{{ tmsetup_libexec_dir }}/tm-hotspot-setup"]
    assert "{{ tmsetup_secrets_dir }}/hotspot_password" in argv
    assert "{{ tmsetup_hotspot_address }}/{{ tmsetup_hotspot_subnet.split('/')[1] }}" in argv


def test_the_radio_is_turned_on_only_when_the_hotspot_is_wanted():
    conditions = wifi_tasks()[RADIO_TASK]["when"]
    text = " ".join(conditions) if isinstance(conditions, list) else conditions
    assert "autoconnect" in text
    assert "tmsetup_wifi_hotspot_register" in text


def test_no_wifi_task_restarts_networkmanager_except_the_two_conf_files():
    notifying = {
        t["name"] for t in wifi_task_list() if "Restart NetworkManager service" in (t.get("notify") or [])
        or t.get("notify") == "Restart NetworkManager service"
    }
    assert notifying == {
        "TMSetup - WiFi Setup - Copy wifi powersave config",
        "TMSetup - WiFi Setup - Copy network connectivity check config",
    }


def test_the_firewall_unit_is_started_with_the_services():
    task = next(
        t for t in load_role_yaml("tasks/start_services.yml") if "tm-hotspot-firewall.service" in str(t)
    )
    systemd = task["ansible.builtin.systemd_service"]
    assert systemd["name"] == "tm-hotspot-firewall.service"
    assert systemd["state"] == "started"
    assert systemd["enabled"] is True


def test_a_changed_firewall_file_reloads_rather_than_restarts():
    handler = next(h for h in load_role_yaml("handlers/main.yml") if h["name"] == "Reload the hotspot firewall")
    assert handler["ansible.builtin.systemd_service"]["state"] == "reloaded"
    assert handler["ansible.builtin.systemd_service"]["name"] == "tm-hotspot-firewall.service"
    firewall = next(t for t in wifi_task_list() if "hotspot-firewall.nft" in str(t.get("ansible.builtin.template", {})))
    assert firewall["notify"] == "Reload the hotspot firewall" or "Reload the hotspot firewall" in firewall["notify"]
    unit = (ROLE / "templates/network/tm-hotspot-firewall.service.j2").read_text()
    assert "ExecReload=" in unit


def test_the_firewall_unit_is_started_before_the_hotspot_profile_exists():
    tasks = wifi_task_list()
    names = [t["name"] for t in tasks]
    start = next(
        i for i, t in enumerate(tasks)
        if t.get("ansible.builtin.systemd_service", {}).get("name") == "tm-hotspot-firewall.service"
    )
    systemd = tasks[start]["ansible.builtin.systemd_service"]
    assert systemd["state"] == "started"
    assert systemd["enabled"] is True
    assert systemd["daemon_reload"] is True
    assert start > names.index("TMSetup - WiFi Setup - Install the hotspot firewall unit")
    assert start > names.index("TMSetup - WiFi Setup - Install the hotspot firewall rules")
    assert start < names.index(HOTSPOT_TASK)


def test_a_refusal_from_the_helper_stops_the_install_with_its_sentence():
    tasks = wifi_task_list()
    names = [t["name"] for t in tasks]
    helper = tasks[names.index(HOTSPOT_TASK)]
    assert helper["no_log"] is True
    assert helper["failed_when"] is False
    stop_name = "TMSetup - WiFi Setup - Stop if the hotspot couldn't be set up"
    assert names.index(stop_name) == names.index(HOTSPOT_TASK) + 1
    stop = tasks[names.index(stop_name)]
    assert "no_log" not in stop
    assert "tmsetup_wifi_hotspot_register.stderr" in stop["ansible.builtin.fail"]["msg"]
    assert stop["when"] == "tmsetup_wifi_hotspot_register.rc != 0"


def test_nothing_parses_the_helpers_output_when_it_refused():
    register = {"rc": 1, "stdout": "", "stderr": "No Wi-Fi device wlan0."}
    helper = wifi_tasks()[HOTSPOT_TASK]
    assert evaluate("{{ " + helper["changed_when"] + " }}", tmsetup_wifi_hotspot_register=register) is False
    ok = {"rc": 0, "stdout": '{"changed": true, "autoconnect": true}', "stderr": ""}
    assert evaluate("{{ " + helper["changed_when"] + " }}", tmsetup_wifi_hotspot_register=ok) is True
    radio = wifi_tasks()[RADIO_TASK]["when"]
    assert radio[0] == "tmsetup_wifi_hotspot_register.rc == 0"


def test_the_hotspots_dns_directory_is_created_before_the_dns_file():
    tasks = wifi_task_list()
    names = [t["name"] for t in tasks]
    made = tasks[names.index("TMSetup - WiFi Setup - Create the hotspot's DNS directory")]
    directory = made["ansible.builtin.file"]
    assert directory["path"] == "/etc/NetworkManager/dnsmasq-shared.d"
    assert directory["state"] == "directory"
    assert (directory["owner"], directory["group"], directory["mode"]) == ("root", "root", "0755")
    assert made["become"] is True
    assert names.index(made["name"]) < names.index("TMSetup - WiFi Setup - Make every name on the hotspot resolve to this device")
