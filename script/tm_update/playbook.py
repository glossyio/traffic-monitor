"""The installer's Ansible, run from the tree being installed: its own venv (named for the lock that built it), the
variables file the role reads, and one function that runs a playbook."""

import hashlib
import json
import shutil
from pathlib import Path

from . import proc
from .handover import Handover
from .installed import OPTIONS_PASSED_BACK, Installed
from .paths import Paths
from .state import REASONS, Failed

SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
_BRANCHES = {"stable": "main", "development": "dev"}
# Each step of the Ansible environment (the venv, then pip from the lock) gets this long
VENV_TIMEOUT = 900


def venv_path(lock: Path, paths: Paths) -> Path:
    """ansible-<first 12 of the lock file's SHA-256>: another lock, another environment."""
    return paths.venv_root / ("ansible-" + hashlib.sha256(Path(lock).read_bytes()).hexdigest()[:12])


def ensure_venv(tree: Path, paths: Paths, log) -> Path:
    """The tree's Ansible, installed from its hashed lock. A venv that is half made is removed and made again."""
    lock = Path(tree) / "script" / "requirements.lock"
    venv = venv_path(lock, paths)
    if (venv / "bin" / "ansible-playbook").exists():
        return venv
    env = {"PATH": SYSTEM_PATH}
    paths.venv_root.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(venv, ignore_errors=True)
    try:
        made = proc.run(["python3", "-m", "venv", str(venv)], env=env, log=log, timeout=VENV_TIMEOUT)
        if made.returncode == 0:
            made = proc.run([str(venv / "bin" / "pip"), "install", "--no-input", "--no-cache-dir",
                             "--disable-pip-version-check", "--require-hashes", "-r", str(lock)], env=env, log=log,
                            timeout=VENV_TIMEOUT)
    except proc.TimedOut as error:
        shutil.rmtree(venv, ignore_errors=True)
        raise Failed("prepare_failed", error.detail) from None
    if made.returncode != 0 or not (venv / "bin" / "ansible-playbook").exists():
        shutil.rmtree(venv, ignore_errors=True)
        raise Failed("prepare_failed", "ansible environment")
    return venv


def write_vars(handover: Handover, installed: Installed, tree: Path, *, update_mode: bool) -> Path:
    """<work>/vars.json: what the role keeps from the install, the tree's own commit, and where the update works.
    Nothing else: no time zone, no Wi-Fi country, no force."""
    work = str(handover.work_dir)
    data = {}
    for name in OPTIONS_PASSED_BACK:
        if installed.options.get(name) is True:
            data[f"tmsetup_bool_{name}"] = True
    data.update({
        "tmsetup_codedir": str(installed.codedir),
        "tmsetup_codeowner": installed.codeowner,
        "tmsetup_codegroup": installed.codegroup,
        "tmsetup_installing_user": installed.installing_user,
    })
    if installed.repo is not None:
        data["tmsetup_update_repo"] = installed.repo
    data.update({
        "tmsetup_source_commit": handover.commit,
        "tmsetup_source_branch": _BRANCHES[handover.channel],
        "tmsetup_source_modified": False,
        "tmsetup_tmp_dir": work,
        "tmsetup_reboot_touch_file": work + "/reboot-required",
        "tmsetup_update_work_dir": work,
        "tmsetup_update_stage_dir": work + "/stage",
        "tmsetup_update_reason_file": work + "/reason",
        "tmsetup_update_build_tag": "prepare-" + handover.commit[:7],
        "tmsetup_update_mode": update_mode,
    })
    target = handover.work_dir / "vars.json"
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    target.chmod(0o644)
    return target


def run_playbook(venv: Path, tree: Path, playbook: str, vars_file: Path, handover: Handover, log,
                 tags: "list[str] | None" = None, *, timeout: float) -> int:
    """Run a playbook of the tree's script/ansible folder with no terminal, its own home, and a plain environment.
    Past its timeout (seconds) it is ended with everything it started, and proc.TimedOut is raised."""
    scratch = handover.work_dir / "ansible-tmp"
    home = handover.work_dir / "home"
    for folder in (home, scratch):
        folder.mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": str(home), "ANSIBLE_LOCAL_TEMP": str(scratch), "ANSIBLE_REMOTE_TEMP": str(scratch),
        "ANSIBLE_NOCOLOR": "1", "ANSIBLE_FORCE_COLOR": "0", "LC_ALL": "C.UTF-8", "PATH": SYSTEM_PATH,
    }
    argv = [str(Path(venv) / "bin" / "ansible-playbook"), "-i", "localhost", playbook, "-e", f"@{vars_file}"]
    if tags:
        argv += ["--tags", ",".join(tags)]
    return proc.run(argv, env=env, log=log, timeout=timeout, cwd=Path(tree) / "script" / "ansible").returncode


def reason_from(handover: Handover, default: str) -> str:
    """The code the role's refusal wrote to <work>/reason when it is one of this version's codes, else the default."""
    try:
        with open(handover.work_dir / "reason", encoding="utf-8") as handle:
            code = handle.read(200).strip()
    except (OSError, ValueError):
        return default
    return code if code in REASONS else default
