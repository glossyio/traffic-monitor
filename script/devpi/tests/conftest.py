"""Device tests: compare each dev Pi with what the dev-Pi inventory says it should have.

Run them with tmdev.py, which also picks the host:

    .venv/bin/python script/devpi/tmdev.py test tm-dev-01

They connect over SSH (pytest-testinfra) with the inventory's connection details. Each
run is written to the local run log as summary.md and results.jsonl. They run only when
TM_DEV_HOSTS names the hosts, which tmdev.py test sets; otherwise every test here is
skipped, so running the repo's other tests never touches a Pi.
"""

import collections
import json
import os
import re
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import devlog  # noqa: E402
from devpi_checks import (DEFAULT_CODEDIR, DEFAULT_CODEOWNER, read_root_file,  # noqa: E402
                          require_pii_free, validate_expect)

HERE = Path(__file__).resolve().parent
OUTCOME_ORDER = ("passed", "failed", "error", "skipped")
MAX_MESSAGE = 300
# testinfra puts a whole CommandResult in its errors; the summary keeps the command, exit code, and first stderr line.
COMMAND_RESULT = re.compile(r"exit_status=(?P<status>-?\d+), command=b(?P<q>['\"])(?P<command>.*?)(?P=q), "
                            r"_stdout=.*?, _stderr=b(?P<q2>['\"])(?P<stderr>.*?)(?P=q2)\)", re.DOTALL)
SKIP_REASON = pytest.StashKey[str]()
SUITE = pytest.StashKey[dict]()
HOST_PROBLEMS = pytest.StashKey[dict]()


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "disruptive: restarts services or reboots the Pi; runs only with TM_DEV_DISRUPTIVE=1")
    hosts = os.environ.get("TM_DEV_HOSTS")
    if not hosts:
        config.stash[SKIP_REASON] = "device tests run only through tmdev.py test (or with TM_DEV_HOSTS set)"
        return
    try:
        inventory = devlog.inventory_path()
    except devlog.DevPiError as exc:
        raise pytest.UsageError(str(exc)) from exc
    if not inventory.is_file():
        config.stash[SKIP_REASON] = f"no dev-Pi inventory at {inventory} (see script/devpi/README.md)"
        return
    # testinfra runs ansible-inventory and ansible from PATH; use the ones in this venv.
    os.environ["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])
    if config.option.ansible_inventory is None:
        config.option.ansible_inventory = str(inventory)
    if config.option.hosts is None:
        config.option.hosts = ",".join(f"ansible://{name}" for name in hosts.split(","))


def pytest_collection_modifyitems(config, items):
    reason = config.stash.get(SKIP_REASON, None)
    disruptive = os.environ.get("TM_DEV_DISRUPTIVE") == "1"
    for item in items:
        if not item.path.is_relative_to(HERE):
            continue
        if reason:
            item.add_marker(pytest.mark.skip(reason=reason))
        elif "disruptive" in item.keywords and not disruptive:
            item.add_marker(pytest.mark.skip(reason="disruptive; run with tmdev.py test --disruptive"))


# --- run log ---------------------------------------------------------------------------------

def report_message(report):
    message = ""
    if report.skipped and isinstance(report.longrepr, tuple):
        message = report.longrepr[2].removeprefix("Skipped: ")
    elif report.failed:
        crash = getattr(report.longrepr, "reprcrash", None)
        message = crash.message if crash else str(report.longrepr).strip().splitlines()[-1]
        if match := COMMAND_RESULT.search(message):
            command = match["command"].replace("\\'", "'")
            stderr = match["stderr"].split("\\n")[0].strip()
            message = f"`{command[:120]}` exited {match['status']}" + (f": {stderr}" if stderr else "")
    return message if len(message) <= MAX_MESSAGE else message[:MAX_MESSAGE] + "…"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    config = item.config
    logged = item.path.is_relative_to(HERE) and SKIP_REASON not in config.stash
    if logged and (report.when == "call" or not report.passed):
        if SUITE not in config.stash:
            host = os.environ["TM_DEV_HOSTS"]
            deploy = devlog.last_deploy(host)
            # The code under test is what the last deploy put on the Pi, not this checkout.
            code = devlog.Run.load(devlog.log_dir() / deploy["run"]).meta["code"] if deploy else None
            run = devlog.Run.start("suite", host.replace(",", "+"), code=code, deploy=deploy,
                                   disruptive=os.environ.get("TM_DEV_DISRUPTIVE") == "1",
                                   pytest_args=list(config.invocation_params.args))
            config.stash[SUITE] = {"run": run, "results": []}
        outcome = "error" if report.failed and report.when != "call" else report.outcome
        config.stash[SUITE]["results"].append({"test": item.nodeid.removeprefix("script/devpi/tests/"),
                                               "outcome": outcome, "seconds": round(report.duration, 1),
                                               "message": devlog.redact(report_message(report))})
    return report


def pytest_sessionfinish(session, exitstatus):
    suite = session.config.stash.get(SUITE, None)
    if suite is None:
        return
    run, results = suite["run"], suite["results"]
    counts = collections.Counter(result["outcome"] for result in results)
    summary = ", ".join(f"{counts[outcome]} {'errors' if outcome == 'error' and counts[outcome] > 1 else outcome}"
                        for outcome in OUTCOME_ORDER if counts[outcome])
    with open(run.dir / "results.jsonl", "w") as saved:
        saved.writelines(json.dumps(result) + "\n" for result in results)
    lines = [
        f"# Device tests: {run.meta['host']}",
        "",
        f"- Run directory: {run.dir}",
        f"- Code: {devlog.code_label(run.meta['code'])} ({run.meta['code']['worktree']}; "
        + ("from the last deploy)" if run.meta["deploy"] else "no deploy logged, so this checkout)"),
        *([f"- Tests: {devlog.code_label(run.meta['tool'])} ({run.meta['tool']['worktree']})"]
          if run.meta.get("tool") else []),
        f"- Started: {run.meta['started']}",
        f"- Last deploy to this host: {devlog.deploy_label(run.meta['deploy'])}",
        f"- Disruptive tests: {'included' if run.meta['disruptive'] else 'skipped'}",
        f"- Result: **{summary or 'no tests ran'}**",
        "",
        "| Test | Outcome | Seconds | Message |",
        "|---|---|---|---|",
    ]
    for result in results:
        cells = [result["test"], result["outcome"].upper(), str(result["seconds"]), result["message"]]
        lines.append("| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
    (run.dir / "summary.md").write_text("\n".join(lines) + "\n")
    run.finish(summary or "no tests ran", not (counts["failed"] or counts["error"]))
    print(f"\ntmdev: device-test log: {run.dir / 'summary.md'}")


# --- fixtures --------------------------------------------------------------------------------

def host_problem(host):
    """Why the tests can't use this host (no SSH, or sudo wants a password), or None."""
    try:
        host.run("true")
    except RuntimeError as exc:
        stderr = getattr(exc.args[0], "stderr", "") if exc.args else ""
        return "can't connect over SSH: " + (stderr.strip().splitlines() or [str(exc)])[-1]
    if host.run("sudo -n true").rc != 0:
        return ("sudo asks this login for a password; use a key-only login with passwordless sudo "
                "(tmdev.py pi-login, see script/devpi/README.md)")
    return None


@pytest.fixture(autouse=True)
def pi_ready(request):
    """Check each host once; if it can't be used, fail its tests at once with the reason."""
    if "host" not in request.fixturenames:
        return
    host = request.getfixturevalue("host")
    problems = request.config.stash.setdefault(HOST_PROBLEMS, {})
    name = host.backend.get_pytest_id()
    if name not in problems:
        problems[name] = host_problem(host)
    if problems[name]:
        pytest.fail(f"{name}: {problems[name]}", pytrace=False)


@pytest.fixture(scope="module")
def hostvars(host):
    return host.ansible.get_variables()


@pytest.fixture(scope="module")
def expect(hostvars):
    """The host's tm_expect from the inventory, checked, with defaults filled in."""
    return validate_expect(hostvars.get("tm_expect"))


@pytest.fixture(scope="module")
def codedir(hostvars):
    return hostvars.get("tmsetup_codedir", DEFAULT_CODEDIR)


@pytest.fixture(scope="module")
def codeowner(hostvars):
    return hostvars.get("tmsetup_codeowner", DEFAULT_CODEOWNER)


@pytest.fixture(scope="module")
def node_red_config(host, expect, codedir):
    """The Pi's Node-RED config.yml, parsed. Only on pii_free units."""
    require_pii_free(expect)
    return yaml.safe_load(read_root_file(host, f"{codedir}/node-red-tm/config/config.yml"))
