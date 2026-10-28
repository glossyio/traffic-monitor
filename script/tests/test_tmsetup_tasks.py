"""Checks on the tmsetup role's task and handler files that guard against upgrade mistakes."""

from tmsetup_render import load_role_yaml


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
    assert set(tm_control["tags"]) == {"tm-control", "frigate", "go2rtc"}
    assert names.index("TMSetup - Main - Setup tm-control command line") < names.index("TMSetup - Main - Setup Frigate")


def test_go2rtc_tag_gives_frigate_the_rtsp_login():
    """-t go2rtc turns on go2rtc's RTSP login, so the same run must hand it to Frigate."""
    main = load_role_yaml("tasks/main.yml")
    names = [task["name"] for task in main]
    credentials = main[names.index("TMSetup - Main - Give Frigate the go2rtc RTSP login")]
    assert set(credentials["tags"]) == {"go2rtc", "frigate"}
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
    env = tasks["TMSetup - Frigate Credentials - Add go2rtc RTSP credentials to frigate.env"]
    migrate = tasks["TMSetup - Frigate Credentials - Update Frigate config from older installs"]
    assert env["when"] == "tmsetup_frigate_settings_stat_register.results[0].stat.exists"
    assert migrate["when"] == "tmsetup_frigate_settings_stat_register.results[1].stat.exists"


def test_existing_frigate_env_gets_both_credentials_without_printing_them():
    task = frigate_credentials_tasks()["TMSetup - Frigate Credentials - Add go2rtc RTSP credentials to frigate.env"]
    assert task["no_log"] is True
    assert [item["key"] for item in task["loop"]] == ["FRIGATE_GO2RTC_RTSP_USER", "FRIGATE_GO2RTC_RTSP_PASSWORD"]


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
    assert set(login["tags"]) == POD_AND_PROXY_TAGS
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
