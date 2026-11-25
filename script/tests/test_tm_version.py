"""The form of tmsetup_tm_version: a release's version, or the next release's version with -dev on the end."""

import re

import pytest
from tmsetup_render import load_role_yaml

VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-dev)?")


def test_the_version_is_a_release_or_the_next_release_with_dev():
    version = load_role_yaml("vars/main.yml")["tmsetup_tm_version"]
    assert isinstance(version, str) and VERSION.fullmatch(version), version


@pytest.mark.parametrize("text", ["0.8", "v0.8.0", "0.8.0-rc1", "0.8.0-dev1", "0.8.0-DEV", "00.8.0", "0.8.0 ", ""])
def test_the_rule_refuses_other_forms(text):
    assert not VERSION.fullmatch(text)
