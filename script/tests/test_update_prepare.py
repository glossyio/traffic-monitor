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
    """Every task of a list, blocks opened (a block's tasks, its rescue, its always), each with the blocks around it."""
    for task in tasks:
        if "block" in task:
            yield from walk(task["block"], enclosing + (task,))
            yield from walk(task.get("rescue", []), enclosing + (task,))
            yield from walk(task.get("always", []), enclosing + (task,))
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
    # the redirect to the signed download address is the answer: following it could meet a host that refuses a HEAD
    assert head["follow_redirects"] == "none"
    assert head["status_code"] == [200, 301, 302, 303, 307, 308]
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
        assert "--no-cache-dir" in argv
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


# The images half: build folders that give the build units' cache keys, the builds in the slice, each first stage's
# tag, and the nginx check on the new image.

BUILD = WORK + "/build"
NGINX_CHECK = "TMSetup - revproxy Setup - Check NGinx config before deploying it"
# The installer's own tasks that write each image's folder under tmsetup_codedir
SETUP_TASKS = {
    "frigate": "tasks/frigate_setup.yml",
    "node-red-tm": "tasks/node-red-tm_setup.yml",
    "revproxy": "tasks/revproxy_setup.yml",
}
WRITING = ("ansible.builtin.template", "ansible.builtin.copy", "ansible.builtin.unarchive", "ansible.builtin.file")


def images_tasks():
    return list(walk(load_role_yaml("tasks/update_images.yml")))


def imports_of(tasks, file):
    return [task for task in tasks if module_of(task) == "ansible.builtin.import_tasks" and task["ansible.builtin.import_tasks"] == {"file": file}]


def written(tasks, base, variables):
    """What tasks write under base, as {(module, path relative to base): [attributes]}: the source of a template or
    copy, owner, group, mode, and a directory's state. An unarchive of pack-ui-sources.sh's archive writes ui (its
    members are named ui/...; test_pack_ui_sources.py), and its source is the archive the run packed."""
    found = {}
    for task, _ in walk(tasks):
        module = module_of(task)
        if module not in WRITING or task[module].get("state") == "absent":
            continue
        for item in render_value(task.get("loop", [None]), variables):
            scope = dict(variables, item=item)
            args = task[module]
            path = render_value(args.get("dest", args.get("path")), scope)
            if path != base and not path.startswith(base + "/"):
                continue
            relative = path[len(base) + 1:] if path != base else "."
            keys = ["owner", "group", "mode"] + (["src"] if module in ("ansible.builtin.template", "ansible.builtin.copy") else [])
            attributes = {key: render_value(args.get(key), scope) for key in keys}
            if module == "ansible.builtin.file":
                attributes["state"] = args["state"]
            if module == "ansible.builtin.unarchive":
                relative = "ui" if relative == "." else relative + "/ui"
            found.setdefault((module, relative), []).append(attributes)
    return found


def copy_sources(folder):
    """The context paths a Containerfile's COPY lines read (a COPY --from reads another stage, not the context)."""
    text = (REPO / "container" / folder / "Containerfile.j2").read_text()
    sources = []
    for line in re.findall(r"(?m)^COPY\s+(.*)$", text):
        words = line.split()
        if any(word.startswith("--from") for word in words):
            continue
        sources += [word.rstrip("/") for word in words[:-1] if not word.startswith("--")]
    return sources


def test_the_images_half_sets_its_own_variables():
    # Prepare runs --tags images on its own, so nothing the stage half set is in memory
    first, second = load_role_yaml("tasks/update_images.yml")[:2]
    assert first["ansible.builtin.import_tasks"] == {"file": "set_vars.yml"}
    assert second["ansible.builtin.import_tasks"] == {"file": "detectors_check.yml"}


def test_the_nginx_check_is_one_file_that_both_runs_include():
    check = [task for task, _ in walk(load_role_yaml("tasks/revproxy_nginx_check.yml"))]
    (container,) = [task for task in check if module_of(task) == "containers.podman.podman_container"]
    assert container["containers.podman.podman_container"]["image"] == "{{ tmsetup_revproxy_check_image }}"
    for name, image in (
        ("tasks/revproxy_setup.yml", "{{ tmsetup_revproxy_image }}"),
        ("tasks/update_images.yml", "localhost/revproxy:{{ tmsetup_update_build_tag }}"),
    ):
        tasks = [task for task, _ in walk(load_role_yaml(name))]
        assert not [task for task in tasks if module_of(task) == "containers.podman.podman_container"], name
        (include,) = imports_of(tasks, "revproxy_nginx_check.yml")
        assert include["vars"] == {"tmsetup_revproxy_check_image": image}, name


def test_the_normal_run_checks_nginx_where_it_did():
    tasks = load_role_yaml("tasks/revproxy_setup.yml")
    names = [task["name"] for task in tasks]
    at = names.index(NGINX_CHECK)
    assert imports_of([tasks[at]], "revproxy_nginx_check.yml") == [tasks[at]]
    assert names[at - 1] == "TMSetup - revproxy Setup - Remove NGinx check directories left by an interrupted run"
    assert names[at + 1] == "TMSetup - revproxy Setup - Create NGinx config file"
    # the block as it was: a throwaway directory beside the deployed config (the clean-up above finds it by its
    # prefix), always removed
    (block,) = load_role_yaml("tasks/revproxy_nginx_check.yml")
    assert block["name"] == NGINX_CHECK
    tempfile = block["block"][0]["ansible.builtin.tempfile"]
    assert (tempfile["path"], tempfile["prefix"], tempfile["state"]) == ("{{ tmsetup_codedir }}/revproxy", ".nginx-check.", "directory")
    assert [module_of(task) for task in block["always"]] == ["ansible.builtin.file"]


def test_each_build_folder_gets_the_installers_owner_group_and_modes():
    variables = prepare_vars()
    tasks = load_role_yaml("tasks/update_images.yml")
    required = {
        "frigate-tm": {"Containerfile"},
        "node-red-tm": {"Containerfile", "data/package.json", "data/package-lock.json"},
        "revproxy": {"Containerfile", ".containerignore", "ui"},
    }
    for image in variables["tmsetup_update_images"]:
        mine = written(tasks, f"{BUILD}/{image['name']}", variables)
        installer = written(load_role_yaml(SETUP_TASKS[image["dir"]]), f"{CODEDIR}/{image['dir']}", variables)
        paths = {path for _, path in mine}
        assert required[image["name"]] <= paths, image["name"]
        for key, (attributes,) in mine.items():
            assert attributes in installer.get(key, []), (image["name"], key, attributes)
        # every file a COPY reads from the context is in the folder
        for source in copy_sources(image["dir"]):
            assert any(source == path or source.startswith(path + "/") for path in paths), (image["name"], source)
        # the folder's own directory, as the installer creates it
        assert ("ansible.builtin.file", ".") in mine, image["name"]


def test_the_ui_sources_are_packed_as_the_installer_packs_them():
    variables = prepare_vars()
    tasks = [task for task, _ in images_tasks()]
    real = [task for task, _ in walk(load_role_yaml("tasks/revproxy_setup.yml"))]
    real_pack = by_name(real, "TMSetup - revproxy Setup - Pack the UI sources")
    (pack,) = [task for task in tasks if module_of(task) == "ansible.builtin.command" and "pack-ui-sources.sh" in json.dumps(task)]
    argv = argv_of(pack, variables)
    assert pack["ansible.builtin.command"]["argv"][:-1] == real_pack["ansible.builtin.command"]["argv"][:-1]
    # the same user packs, so the switch's run packs the same files
    assert pack["become"] is real_pack["become"] is False
    archive = argv[-1]
    assert archive.startswith(WORK + "/") and not archive.startswith(BUILD + "/")
    (unpack,) = [task for task in tasks if module_of(task) == "ansible.builtin.unarchive"]
    assert render_value(unpack["ansible.builtin.unarchive"]["src"], variables) == archive
    assert render_value(unpack["ansible.builtin.unarchive"]["dest"], variables) == BUILD + "/revproxy"
    assert unpack["become"] is True
    removals = [
        task for task in tasks
        if module_of(task) == "ansible.builtin.file" and "loop" not in task
        and render_value(task["ansible.builtin.file"]["path"], variables) == archive
    ]
    assert [task["ansible.builtin.file"]["state"] for task in removals] == ["absent"]


def podman_builds(variables, chdir=False):
    """Every podman build of the images half in the order it runs, as (task, argv), or (task, argv, chdir)."""
    found = []
    for task, _ in images_tasks():
        if module_of(task) != "ansible.builtin.command":
            continue
        for item in render_value(task.get("loop", [None]), variables):
            scope = dict(variables, item=item)
            argv = render_value(task["ansible.builtin.command"]["argv"], scope)
            if argv[:2] == ["podman", "build"]:
                where = render_value(task["ansible.builtin.command"].get("chdir"), scope)
                found.append((task, argv, where) if chdir else (task, argv))
    return found


def build_argv(name, tag):
    return ["podman", "build", "--pull=missing", "--cgroup-parent=tm-update.slice", "--tag", f"localhost/{name}:{tag}",
            "--file", "Containerfile"]


def test_every_build_runs_in_the_slice_and_pulls_only_what_is_missing():
    variables = prepare_vars()
    images = [argv for _, argv in podman_builds(variables) if "--target" not in argv]
    assert images == [build_argv(image["name"], "b1") + [f"{BUILD}/{image['name']}"] for image in variables["tmsetup_update_images"]]
    for task, argv, where in podman_builds(variables, chdir=True):
        assert task["become"] is True and task["changed_when"] is True
        # --file is relative, so each build runs in its own context
        assert where == argv[-1]


def test_each_first_stage_is_tagged_after_its_image_is_built():
    variables = prepare_vars()
    order = [argv for _, argv in podman_builds(variables)]
    expected = [
        (image["name"], stage)
        for image in variables["tmsetup_update_images"]
        for stage in image["stages"]
    ]
    assert expected == [("frigate-tm", "build-ffmpeg"), ("revproxy", "ui")]
    stages = [argv for argv in order if "--target" in argv]
    assert stages == [
        build_argv(name, f"stage-{stage}") + ["--target", stage, f"{BUILD}/{name}"] for name, stage in expected
    ]
    for name, stage in expected:
        image = build_argv(name, "b1") + [f"{BUILD}/{name}"]
        assert order.index(image) < order.index(build_argv(name, f"stage-{stage}") + ["--target", stage, f"{BUILD}/{name}"])


def test_the_slice_gets_its_weights_before_the_first_build():
    variables = prepare_vars()
    tasks = [task for task, _ in images_tasks()]
    (slice_task,) = [task for task in tasks if module_of(task) == "ansible.builtin.command" and "systemctl" in json.dumps(task)]
    assert argv_of(slice_task, variables) == ["systemctl", "set-property", "--runtime", "tm-update.slice", "CPUWeight=20", "IOWeight=20"]
    assert slice_task["become"] is True
    first_build = podman_builds(variables)[0][0]
    assert tasks.index(slice_task) < tasks.index(first_build)


def test_a_build_that_fails_refuses_with_build_failed():
    variables = prepare_vars()
    tasks = images_tasks()
    build_names = {task["name"] for task, _ in podman_builds(variables)}
    assert len(build_names) == 2
    blocks = [enclosing[-1] for task, enclosing in tasks if task["name"] in build_names]
    (check,) = [(task, enclosing) for task, enclosing in tasks if imports_of([task], "revproxy_nginx_check.yml")]
    blocks.append(check[1][-1])
    assert all(block is blocks[0] for block in blocks)
    assert [code for code, _ in refusals([(task, ()) for task in blocks[0]["rescue"]])] == ["build_failed"]


def test_the_nginx_check_runs_on_the_new_image():
    variables = prepare_vars()
    tasks = [task for task, _ in images_tasks()]
    (check,) = imports_of(tasks, "revproxy_nginx_check.yml")
    assert render_value(check["vars"]["tmsetup_revproxy_check_image"], variables) == "localhost/revproxy:b1"
    revproxy = next(task for task, argv in podman_builds(variables) if argv[-1] == BUILD + "/revproxy" and "--target" not in argv)
    assert tasks.index(revproxy) < tasks.index(check)
