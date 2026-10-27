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
