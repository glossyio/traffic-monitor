"""podman_events() in the device tests' helpers, against a fake host: how it reads Podman's journal entries (#268)."""

import contextlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

DEVPI_CHECKS = Path(__file__).resolve().parents[1] / "devpi" / "tests" / "devpi_checks.py"
_spec = importlib.util.spec_from_file_location("devpi_checks_under_test", DEVPI_CHECKS)
devpi_checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(devpi_checks)


class FakeHost:
    """Answers every command with one result, and keeps the commands."""

    def __init__(self, stdout="", rc=0, stderr=""):
        self.result = SimpleNamespace(stdout=stdout, rc=rc, stderr=stderr)
        self.commands = []

    def sudo(self):
        return contextlib.nullcontext()

    def run(self, command):
        self.commands.append(command)
        return self.result


def journal(*entries):
    return "".join(json.dumps(entry) + "\n" for entry in entries)


def test_each_field_is_a_string_even_when_the_journal_gives_null_bytes_or_nothing():
    host = FakeHost(journal(
        {"_CMDLINE": "/usr/bin/podman network exists podman", "_SYSTEMD_UNIT": "revproxy-build.service", "_PID": "1244"},
        {"_CMDLINE": None, "_SYSTEMD_UNIT": "tmnet-network.service", "_PID": "1250"},
        {"_CMDLINE": list(b"podman build ."), "_PID": "1251"},
    ))
    assert devpi_checks.podman_events(host, "refresh") == [
        {"_CMDLINE": "/usr/bin/podman network exists podman", "_SYSTEMD_UNIT": "revproxy-build.service", "_PID": "1244"},
        {"_CMDLINE": "", "_SYSTEMD_UNIT": "tmnet-network.service", "_PID": "1250"},
        {"_CMDLINE": "podman build .", "_SYSTEMD_UNIT": "", "_PID": "1251"},
    ]


def test_only_roots_podman_events_of_this_boot():
    host = FakeHost()
    assert devpi_checks.podman_events(host, "refresh") == []
    assert host.commands and all(word in host.commands[0].split() for word in ("-b", "_UID=0", "PODMAN_EVENT=refresh"))


def test_a_journalctl_that_fails_is_a_failure_not_an_empty_journal():
    host = FakeHost(rc=1, stderr="Failed to open journal: Permission denied")
    with pytest.raises(pytest.fail.Exception, match="Permission denied"):
        devpi_checks.podman_events(host, "refresh")
