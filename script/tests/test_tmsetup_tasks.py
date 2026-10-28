"""Checks on the tmsetup role's task and handler files that guard against upgrade mistakes."""

import pytest
from tmsetup_render import evaluate, load_role_yaml

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
    env = tasks["TMSetup - Frigate Credentials - Add go2rtc RTSP credentials and the proxy secret to frigate.env"]
    migrate = tasks["TMSetup - Frigate Credentials - Update Frigate config from older installs"]
    assert env["when"] == "tmsetup_frigate_settings_stat_register.results[0].stat.exists"
    assert migrate["when"] == "tmsetup_frigate_settings_stat_register.results[1].stat.exists"


def test_existing_frigate_env_gets_both_credentials_without_printing_them():
    task = frigate_credentials_tasks()["TMSetup - Frigate Credentials - Add go2rtc RTSP credentials and the proxy secret to frigate.env"]
    assert task["no_log"] is True
    assert [item["key"] for item in task["loop"]][:2] == ["FRIGATE_GO2RTC_RTSP_USER", "FRIGATE_GO2RTC_RTSP_PASSWORD"]


def test_existing_frigate_env_gets_the_proxy_secret_without_printing_it():
    """-t frigate, -t revproxy, or any edge tag on a device whose frigate.env predates proxy auth (Review Focus 2)."""
    task = frigate_credentials_tasks()["TMSetup - Frigate Credentials - Add go2rtc RTSP credentials and the proxy secret to frigate.env"]
    assert task["no_log"] is True
    item = next(item for item in task["loop"] if item["key"] == "FRIGATE_PROXY_AUTH_SECRET")
    assert item["value"] == "{{ tmsetup_secrets['frigate_proxy_secret'] }}"
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
    units = tasks["TMSetup - tm-control Service - Install the unit files"]
    assert units["loop"] == ["tm-control.service", "tm-job-system-password.service"]
    template = units["ansible.builtin.template"]
    assert (template["src"], template["dest"]) == ("tm-control/{{ item }}.j2", "/etc/systemd/system/{{ item }}")
    assert (template["owner"], template["mode"]) == ("root", "0644")
    rules = tasks["TMSetup - tm-control Service - Install the polkit rules"]["ansible.builtin.template"]
    assert rules["dest"] == "/etc/polkit-1/rules.d/50-traffic-monitor.rules"
    assert (rules["owner"], rules["mode"]) == ("root", "0644")
    assert "polkitd" in load_role_yaml("vars/main.yml")["tmsetup_packages"]


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
    # Files only: an archive made from git's file list has no directory entries, so comparing directories would
    # delete ui/src and everything in it.
    assert tasks["TMSetup - revproxy Setup - Find the deployed UI sources"]["ansible.builtin.find"]["file_type"] == "file"
    deployed = {"files": [{"path": f"/opt/traffic-monitor/revproxy/ui/{name}"}
                          for name in ("package.json", "src/main.ts", "src/old.ts", "old-dir/x.ts")]}
    for unpacked in (["ui/package.json", "ui/src/main.ts"],  # from git's file list
                     ["ui/", "ui/package.json", "ui/src/", "ui/src/main.ts"]):  # from the directory, without git
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
