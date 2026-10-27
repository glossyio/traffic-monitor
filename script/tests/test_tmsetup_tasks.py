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
    assert set(tm_control["tags"]) == {"tm-control", "frigate"}
    assert names.index("TMSetup - Main - Setup tm-control command line") < names.index("TMSetup - Main - Setup Frigate")


def frigate_tasks():
    return {task["name"]: task for task in load_role_yaml("tasks/frigate_setup.yml")}


def test_existing_frigate_env_gets_both_credentials_without_printing_them():
    task = frigate_tasks()["TMSetup - Frigate Setup - Add go2rtc RTSP credentials to frigate.env"]
    assert task["no_log"] is True
    assert [item["key"] for item in task["loop"]] == ["FRIGATE_GO2RTC_RTSP_USER", "FRIGATE_GO2RTC_RTSP_PASSWORD"]


def test_frigate_env_template_hides_its_diff():
    """frigate.env.j2 renders the go2rtc RTSP password, and a -f run with -a diff would print it into ~/tmsetup-*.log."""
    task = frigate_tasks()["TMSetup - Frigate Setup - Create Frigate container configuration files"]
    assert task["diff"] is False


def test_existing_frigate_config_is_migrated_as_the_code_owner():
    task = frigate_tasks()["TMSetup - Frigate Setup - Update Frigate config from older installs"]
    argv = task["ansible.builtin.command"]["argv"]
    assert argv[:4] == ["/usr/sbin/runuser", "-u", "{{ tmsetup_codeowner }}", "--"]
    assert argv[4:6] == ["/usr/local/bin/tm-control", "migrate"]
    assert task["notify"] == "Restart frigate.service"


def test_frigate_config_update_warnings_are_shown():
    """migrate warns on stderr and exits 0; Ansible hides a successful command's stderr without -v."""
    names = list(frigate_tasks())
    show = frigate_tasks()["TMSetup - Frigate Setup - Show warnings from the Frigate config update"]
    assert names.index("TMSetup - Frigate Setup - Show warnings from the Frigate config update") == (
        names.index("TMSetup - Frigate Setup - Update Frigate config from older installs") + 1
    )
    assert show["ansible.builtin.debug"]["msg"] == "{{ tmsetup_frigate_migrate_register.stderr_lines }}"
    assert "WARNING" in show["when"]


def test_go2rtc_config_with_the_password_is_root_only_and_never_diffed():
    task = next(t for t in load_role_yaml("tasks/go2rtc_setup.yml") if t["name"] == "TMSetup - Go2rtc Setup - Setup go2rtc rpicam settings")
    template = task["ansible.builtin.template"]
    assert (template["src"], template["owner"], template["mode"]) == ("go2rtc.yaml.j2", "root", "0600")
    assert task["diff"] is False
