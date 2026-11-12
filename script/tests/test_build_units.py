"""Each image build unit first runs a throwaway Podman command, which takes the boot's state refresh (#268)."""

import subprocess
from pathlib import Path

import pytest
from tmsetup_render import REPO, load_role_yaml, render

REFRESH = "/usr/bin/podman network exists podman"
BUILD_UNITS = sorted(path.relative_to(REPO).as_posix() for path in (REPO / "container").glob("*/*.build.j2"))
QUADLET = next((p for p in ("/usr/libexec/podman/quadlet", "/usr/lib/podman/quadlet") if Path(p).exists()), None)


def build_unit(template):
    return render(template, **dict(load_role_yaml("vars/main.yml"), tmsetup_codedir="/opt/traffic-monitor"))


def service_lines(text):
    """The [Service] section's lines, without comments and blank lines."""
    lines = []
    in_service = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_service = stripped == "[Service]"
        elif in_service and stripped and not stripped.startswith("#"):
            lines.append(stripped)
    return lines


def test_the_glob_finds_the_build_units():
    assert {Path(template).name for template in BUILD_UNITS} >= {
        "frigate-tm.build.j2", "node-red-tm.build.j2", "revproxy.build.j2", "plate-recognizer-tm.build.j2"}


def test_refresh_command_is_fixed_in_vars():
    assert load_role_yaml("vars/main.yml")["tmsetup_podman_refresh_command"] == REFRESH


@pytest.mark.parametrize("template", BUILD_UNITS)
def test_build_unit_runs_the_throwaway_command_first_and_nothing_else(template):
    """Only this line: a build unit that restarts itself blocks its container's start, and the installer,
    for as long as the build keeps failing."""
    assert service_lines(build_unit(template)) == [f"ExecStartPre=-{REFRESH}"]


def test_quadlet_keeps_the_line_in_every_build_service(tmp_path):
    if QUADLET is None:
        pytest.skip("no Quadlet generator on this machine (install podman)")
    for template in BUILD_UNITS:
        (tmp_path / Path(template).name.removesuffix(".j2")).write_text(build_unit(template))
    result = subprocess.run([QUADLET, "-dryrun"], env={"QUADLET_UNIT_DIRS": str(tmp_path), "PATH": "/usr/bin:/bin"},
                            capture_output=True, text=True)
    services = result.stdout.split("---")[1:]  # name, body, name, body, ...
    bodies = dict(zip(services[::2], services[1::2]))
    assert len(bodies) == len(BUILD_UNITS), result.stderr
    for name, body in bodies.items():
        lines = body.splitlines()
        assert f"ExecStartPre=-{REFRESH}" in lines, name
        assert [line for line in lines if line.startswith("ExecStart=/usr/bin/podman build ")], name
