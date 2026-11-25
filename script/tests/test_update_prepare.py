"""What an update builds and installs: the image list in vars/main.yml, and the tasks and units that list must match."""

import json
import re

import yaml
from tmsetup_render import REPO, ROLE, _environment, evaluate, load_role_yaml, render

CODEDIR = "/opt/traffic-monitor"


def role_vars():
    return dict(load_role_yaml("vars/main.yml"), tmsetup_codedir=CODEDIR)


def images():
    variables = role_vars()
    return evaluate(variables["tmsetup_update_images"], **variables)


def test_every_build_unit_but_the_addons_is_in_the_image_list():
    units = {path.parent.name for path in (REPO / "container").glob("*/*.build.j2")} - {"plate-recognizer"}
    assert units == {image["dir"] for image in images()}


def test_each_listed_tag_is_the_one_its_build_unit_gives():
    for image in images():
        unit = render(f"container/{image['dir']}/{image['name']}.build.j2", **role_vars())
        assert f"ImageTag=localhost/{image['name']}:{image['tag']}\n" in unit, image["name"]
        assert f"SetWorkingDirectory={CODEDIR}/{image['dir']}\n" in unit, image["name"]


def test_every_named_stage_of_a_containerfile_is_listed_and_no_other():
    for image in images():
        text = (REPO / "container" / image["dir"] / "Containerfile.j2").read_text()
        # The image is not \S+: a template's FROM names its digest as {{ variable }}, with spaces inside the braces.
        assert re.findall(r"(?mi)^FROM\s+.+?\s+AS\s+(\S+)\s*$", text) == image["stages"], image["name"]


def test_podman_setup_installs_the_listed_packages():
    variables = role_vars()
    install = next(
        task for task in load_role_yaml("tasks/podman_setup.yml")
        if task["name"] == "TMSetup - Podman Setup - Install Podman packages"
    )
    assert install["ansible.builtin.apt"]["name"] == "{{ tmsetup_podman_packages }}"
    assert variables["tmsetup_podman_packages"] == ["podman-docker", "podman-compose"]


# The prepare playbook: what it downloads, what it refuses, and the settings it tries, all while the old version runs.

WORK = "/var/lib/traffic-monitor/update/work"
STAGE = WORK + "/stage"
REASON_FILE = WORK + "/reason"
BACKEND = "/role/files/tm-control/backend"
# apt keeps its own downloads here, and nothing else an update's prepare writes lives outside the work folder
APT_COMMANDS = {"apt-get"}
TASK_KEYWORDS = {
    "name", "become", "when", "tags", "register", "loop", "loop_control", "vars", "environment", "changed_when",
    "failed_when", "no_log", "notify", "block", "rescue", "always", "diff", "ignore_errors", "check_mode",
}


def render_value(value, variables):
    """A task argument as Ansible's templating gives it: one {{ expression }} to its value, other text rendered."""
    if isinstance(value, dict):
        return {key: render_value(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [render_value(item, variables) for item in value]
    if isinstance(value, str) and "{{" in value:
        if re.fullmatch(r"\{\{(?:(?!\}\}).)*\}\}", value, re.DOTALL):
            return evaluate(value, **variables)
        return _environment().from_string(value).render(**variables)
    return value


def prepare_vars(**extra):
    raw = {}
    for name in ("defaults/main.yml", "vars/main.yml", "vars/aarch64_vars.yml"):
        raw.update(load_role_yaml(name))
    raw.update(
        tmsetup_codedir=CODEDIR,
        tmsetup_update_work_dir=WORK,
        tmsetup_update_stage_dir=STAGE,
        tmsetup_update_reason_file=REASON_FILE,
        tmsetup_update_build_tag="b1",
        role_path="/role",
        tmsetup_update_backend_dir=BACKEND,
        tmsetup_entered_secrets_stat_register={"results": [{"stat": {"exists": True}}] * 3},
        tmsetup_frigate_settings_stat_register={"results": [{"stat": {"exists": True}}] * 2},
        ansible_facts={"distribution_release": "trixie"},
        **extra,
    )
    for _ in range(3):
        raw = {name: render_value(value, raw) for name, value in raw.items()}
    return raw


def walk(tasks, enclosing=()):
    """Every task of a list, blocks opened (a block's tasks, then its rescue), each with the blocks around it."""
    for task in tasks:
        if "block" in task:
            yield from walk(task["block"], enclosing + (task,))
            yield from walk(task.get("rescue", []), enclosing + (task,))
        else:
            yield task, enclosing


def module_of(task):
    return next(key for key in task if key not in TASK_KEYWORDS)


def stage_tasks():
    return list(walk(load_role_yaml("tasks/update_stage.yml")))


def by_name(tasks, name):
    return next(task for task in tasks if task["name"] == name)


def refusals(tasks):
    """The include_tasks of update_refuse.yml among tasks, as (reason code, task)."""
    return [
        (task["vars"]["tmsetup_update_reason"], task)
        for task, _ in tasks
        if module_of(task) == "ansible.builtin.include_tasks" and task["ansible.builtin.include_tasks"] == "update_refuse.yml"
    ]


def argv_of(task, variables):
    args = task[module_of(task)]
    return render_value(args["argv"], variables)


def commands(variables, containing):
    return [
        (task, argv_of(task, variables))
        for task, _ in stage_tasks()
        if module_of(task) == "ansible.builtin.command" and containing in argv_of(task, variables)
    ]


def option(argv, flag):
    return argv[argv.index(flag) + 1]


def test_the_work_folder_settings_default_to_nothing():
    defaults = load_role_yaml("defaults/main.yml")
    for name in ("tmsetup_update_work_dir", "tmsetup_update_reason_file", "tmsetup_update_build_tag"):
        assert defaults[name] == "", name


def test_the_prepare_playbook_has_a_stage_half_and_an_images_half():
    (play,) = yaml.safe_load((REPO / "script/ansible/update_prepare.yml").read_text())
    assert (play["hosts"], play["connection"]) == ("localhost", "local")
    imports = [(task["tags"], task["ansible.builtin.import_role"]) for task in play["tasks"]]
    assert imports == [
        (["stage"], {"name": "tmsetup", "tasks_from": "update_stage.yml"}),
        (["images"], {"name": "tmsetup", "tasks_from": "update_images.yml"}),
    ]


def test_refusing_writes_the_code_before_it_fails():
    first, second = load_role_yaml("tasks/update_refuse.yml")
    assert module_of(first) == "ansible.builtin.copy" and module_of(second) == "ansible.builtin.fail"
    variables = prepare_vars(tmsetup_update_reason="no_internet")
    copy = render_value(first["ansible.builtin.copy"], variables)
    assert (copy["dest"], copy["mode"], copy["content"]) == (REASON_FILE, "0644", "no_internet\n")
    assert render_value(second["ansible.builtin.fail"]["msg"], variables) == "no_internet"


def test_a_detector_that_needs_its_driver_refuses():
    installs = [
        tuple(task["when"])
        for task in load_role_yaml("tasks/detectors_install.yml")
        if "block" in task
    ]
    assert len(installs) == 2
    found = refusals(stage_tasks())
    assert sorted(code for code, _ in found) == ["hardware_needs_installer"] * 2 + ["no_internet", "settings_need_attention"]
    assert [tuple(task["when"]) for code, task in found if code == "hardware_needs_installer"] == installs


def test_the_internet_is_asked_once_before_any_download():
    variables = prepare_vars()
    goes_online = None
    for task, enclosing in stage_tasks():
        module = module_of(task)
        args = task[module]
        text = json.dumps(args)
        if module in ("ansible.builtin.uri", "ansible.builtin.get_url") or (
            module == "ansible.builtin.command" and ("apt-get" in text or "pip" in text)
        ):
            goes_online = (task, enclosing)
            break
    task, enclosing = goes_online
    head = task["ansible.builtin.uri"]
    assert head["method"] == "HEAD" and head["timeout"] == 20
    go2rtc = by_name(load_role_yaml("tasks/go2rtc_setup.yml"), "TMSetup - Go2rtc Setup - Install go2rtc driver")
    assert render_value(head["url"], variables) == render_value(go2rtc["ansible.builtin.get_url"]["url"], variables)
    (block,) = enclosing
    assert [(code, True) for code, _ in refusals([(t, ()) for t in block["rescue"]])] == [("no_internet", True)]


def test_every_package_the_switch_installs_is_downloaded():
    variables = prepare_vars()
    main, backports = (argv for _, argv in commands(variables, "--download-only"))
    assert main[:4] == ["apt-get", "install", "--download-only", "--yes"]
    assert main[4:] == variables["tmsetup_packages"] + variables["tmsetup_podman_packages"]
    assert backports[:4] == ["apt-get", "install", "--download-only", "--yes"]
    assert option(backports, "--target-release") == "trixie-backports"
    names = [item for item in backports[4:] if item not in ("--target-release", "trixie-backports")]
    assert names == variables["tmsetup_packages_backports"]
    tasks = [task for task, _ in stage_tasks()]
    update = next(task for task in tasks if module_of(task) == "ansible.builtin.command" and task["ansible.builtin.command"]["argv"] == ["apt-get", "update"])
    assert tasks.index(update) < tasks.index(commands(variables, "--download-only")[0][0])
    assert all(task["changed_when"] is False for task, _ in commands(variables, "--download-only"))


def twins(variables):
    """What Task 3's update mode reads from the stage: the five paths its twin tasks name."""
    go2rtc = by_name(load_role_yaml("tasks/go2rtc_setup.yml"), "TMSetup - Go2rtc Setup - Install go2rtc driver from the update's stage")
    control = load_role_yaml("tasks/tm-control_setup.yml")
    unarchive = by_name(control, "TMSetup - tm-control Setup - Copy the tm_control package from the update's stage")
    pip = by_name(control, "TMSetup - tm-control Setup - Install pinned requirements")
    frigate = [task for task in load_role_yaml("tasks/frigate_setup.yml") if task["name"].endswith("from the update's stage")]
    assert len(frigate) == 2
    update_mode = dict(variables, tmsetup_update_mode=True)
    wheels = option(render_value(pip["ansible.builtin.command"]["argv"], update_mode), "--find-links")
    return {
        render_value(go2rtc["ansible.builtin.copy"]["src"], variables),
        render_value(unarchive["ansible.builtin.unarchive"]["src"], variables),
        *(render_value(task["ansible.builtin.copy"]["src"], variables) for task in frigate),
        wheels,
    }


def test_the_tm_control_code_comes_from_the_trees_own_files():
    fact = by_name([task for task, _ in stage_tasks()], "TMSetup - Update Stage - Find the tree's tm-control code")
    assert fact["ansible.builtin.set_fact"]["tmsetup_update_backend_dir"] == "{{ role_path }}/files/tm-control/backend"
    # the role's tm-control folder is the repo's, which holds the package and its lock
    assert (ROLE / "files/tm-control/backend/tm_control/__init__.py").is_file()


def test_the_stage_holds_what_the_switch_reads():
    variables = prepare_vars()
    tasks = [task for task, _ in stage_tasks()]
    get_urls = [render_value(task["ansible.builtin.get_url"], variables) for task in tasks if module_of(task) == "ansible.builtin.get_url"]
    (tar,) = [argv for task, argv in commands(variables, "--create")]
    (download,) = [argv for task, argv in commands(variables, "download")]
    mine = {get_url["dest"] for get_url in get_urls} | {option(tar, "--file"), option(download, "--dest")}
    assert len(mine) == 5
    assert mine == twins(variables)
    assert STAGE + "/go2rtc_linux_arm64" in mine and STAGE + "/tm_control.tar" in mine


def test_the_coral_files_are_staged_under_the_condition_that_reads_them():
    variables = prepare_vars()
    frigate = [task for task in load_role_yaml("tasks/frigate_setup.yml") if task["name"].endswith("from the update's stage")]
    staged = [task for task, _ in stage_tasks() if module_of(task) == "ansible.builtin.get_url" and "coral" in task["ansible.builtin.get_url"]["dest"]]
    assert len(staged) == 2
    for task in staged:
        assert task["when"] == frigate[0]["when"][1:]
        assert task["ansible.builtin.get_url"]["mode"] == "0644"
    originals = [t for t in load_role_yaml("tasks/frigate_setup.yml") if t["name"].startswith("TMSetup - Frigate Setup - Coral TPU model - Download") and not t["name"].endswith("stage")]
    for task, original in zip(sorted(staged, key=lambda t: t["ansible.builtin.get_url"]["url"]), sorted(originals, key=lambda t: t["ansible.builtin.get_url"]["url"])):
        mine = render_value(task["ansible.builtin.get_url"], variables)
        real = render_value(original["ansible.builtin.get_url"], variables)
        assert (mine["url"], mine["checksum"]) == (real["url"], real["checksum"])


def test_the_wheels_are_installed_offline_before_the_dry_run():
    variables = prepare_vars()
    lock = BACKEND + "/requirements.lock"
    assert (ROLE / "files/tm-control/backend/requirements.lock").is_file()
    download, = [argv for _, argv in commands(variables, "download")]
    install, = [argv for _, argv in commands(variables, "--no-index")]
    pip = WORK + "/check-venv/bin/pip"
    assert download[:2] == [pip, "download"] and install[:2] == [pip, "install"]
    for argv in (download, install):
        assert "--require-hashes" in argv and option(argv, "--requirement") == lock
    assert option(download, "--dest") == STAGE + "/wheels"
    assert option(install, "--find-links") == STAGE + "/wheels"
    venv, = [argv for _, argv in commands(variables, "venv")]
    assert venv == ["python3", "-m", "venv", WORK + "/check-venv"]
    order = [argv for _, argv in (
        (task, argv_of(task, variables)) for task, _ in stage_tasks() if module_of(task) == "ansible.builtin.command"
    )]
    assert order.index(venv) < order.index(download) < order.index(install) < order.index(
        commands(variables, "--dry-run")[0][1]
    )


def settings_stats(count_exists):
    return {"results": [{"stat": {"exists": exists}} for exists in count_exists]}


def test_the_dry_run_names_every_file_the_real_run_names():
    variables = prepare_vars()
    secrets_real = by_name(load_role_yaml("tasks/entered_secrets.yml"), "TMSetup - Entered Secrets - Move them to the secrets directory")
    frigate_real = by_name(load_role_yaml("tasks/frigate_credentials.yml"), "TMSetup - Frigate Credentials - Update Frigate config from older installs")
    (secrets_mine, secrets_argv), (frigate_mine, frigate_argv) = commands(variables, "--dry-run")
    assert secrets_mine["when"] == secrets_real["when"] and frigate_mine["when"] == frigate_real["when"]
    # the stats those conditions read are the real tasks' own
    for path, real_path in (("tasks/entered_secrets.yml", "tasks/entered_secrets.yml"), ("tasks/frigate_credentials.yml", "tasks/frigate_credentials.yml")):
        real_stat = next(t for t in load_role_yaml(real_path) if module_of(t) == "ansible.builtin.stat")
        mine = next(t for t, _ in stage_tasks() if module_of(t) == "ansible.builtin.stat" and t["register"] == real_stat["register"])
        assert (mine["loop"], mine["ansible.builtin.stat"]) == (real_stat["loop"], real_stat["ansible.builtin.stat"])
    python = [WORK + "/check-venv/bin/python", "-m", "tm_control"]
    for exists in ([True, True, True], [True, False, False], [False, True, False], [False, False, True]):
        scenario = dict(variables, tmsetup_entered_secrets_stat_register=settings_stats(exists), tmsetup_frigate_settings_stat_register=settings_stats(exists[:2]))
        real = render_value(secrets_real["ansible.builtin.command"]["argv"], scenario)
        mine = render_value(secrets_mine["ansible.builtin.command"]["argv"], scenario)
        assert real[:2] == ["/usr/local/bin/tm-control", "migrate"]
        assert mine == python + ["migrate", "--dry-run"] + real[2:]
    real = render_value(frigate_real["ansible.builtin.command"]["argv"], variables)
    mine = render_value(frigate_mine["ansible.builtin.command"]["argv"], variables)
    split = real.index("/usr/local/bin/tm-control")
    assert mine == real[:split] + python + ["migrate", "--dry-run"] + real[split + 2 :]
    assert real[:5] == ["/usr/sbin/runuser", "-u", variables["tmsetup_codeowner"], "--", "/usr/local/bin/tm-control"]
    # the real tasks change nothing the dry run was asked to try without, and the dry run can't write bytecode
    for task in (secrets_mine, frigate_mine):
        env = render_value(task["environment"], variables)
        assert env["PYTHONPATH"] == BACKEND and env["PYTHONDONTWRITEBYTECODE"] == "1"
        assert task["changed_when"] is False
        assert task["become"] is True


def test_a_failing_dry_run_refuses_with_settings_need_attention():
    variables = prepare_vars()
    names = {task["name"] for task, _ in commands(variables, "--dry-run")}
    blocks = [enclosing[-1] for task, enclosing in stage_tasks() if task["name"] in names]
    assert len(names) == 2 and len(blocks) == 2 and blocks[0] is blocks[1]
    assert {task["name"] for task in blocks[0]["block"]} == names
    assert [code for code, _ in refusals([(t, ()) for t in blocks[0]["rescue"]])] == ["settings_need_attention"]


def test_nothing_in_the_stage_half_writes_outside_the_work_folder():
    variables = prepare_vars(tmsetup_update_reason="a_code")
    reading = {
        "ansible.builtin.stat", "ansible.builtin.include_tasks", "ansible.builtin.import_tasks",
        "ansible.builtin.set_fact", "ansible.builtin.fail", "ansible.builtin.uri",
    }

    def is_inside(path):
        return path == REASON_FILE or path == WORK or path.startswith(WORK + "/")

    written = []
    for name in ("tasks/update_stage.yml", "tasks/update_refuse.yml"):
        for task, _ in walk(load_role_yaml(name)):
            module = module_of(task)
            if module in reading:
                continue
            for item in task.get("loop", [None]):
                args = render_value(task[module], dict(variables, item=render_value(item, variables)))
                if module != "ansible.builtin.command":
                    paths = [args[key] for key in ("dest", "path") if key in args]
                else:
                    argv = args["argv"]
                    if argv[0] in APT_COMMANDS:
                        continue
                    if argv[0] == "/usr/sbin/runuser":
                        argv = argv[argv.index("--") + 1 :]
                    # a command's own program, and the one place each of these two puts its output
                    paths = [argv[0]] if argv[0] not in ("tar", "python3") else []
                    if argv[0] == "tar":
                        paths.append(option(argv, "--file"))
                    if argv[0] == "python3":
                        paths.append(argv[-1])
                    if "--dest" in argv:
                        paths.append(option(argv, "--dest"))
                if "creates" in args:
                    paths.append(args["creates"])
                assert paths, task["name"]
                written += [(task["name"], path) for path in paths]
    assert not [(name, path) for name, path in written if not is_inside(path)]
    assert len(written) >= 14


def test_the_facts_file_has_the_port_and_every_image():
    variables = prepare_vars()
    tasks = [task for task, _ in stage_tasks()]
    (task,) = [t for t in tasks if module_of(t) == "ansible.builtin.template" and "facts.json" in t["ansible.builtin.template"]["dest"]]
    args = render_value(task["ansible.builtin.template"], variables)
    assert (args["dest"], args["mode"]) == (WORK + "/facts.json", "0644")
    facts = json.loads(render("script/ansible/roles/tmsetup/templates/" + args["src"], **variables))
    assert facts["tm_control_port"] == 8090
    assert facts["images"] == [
        {
            "name": image["name"],
            "repository": "localhost/" + image["name"],
            "tag": image["tag"],
            "build_tag": "b1",
            "stages": image["stages"],
            "context": WORK + "/build/" + image["name"],
        }
        for image in variables["tmsetup_update_images"]
    ]
