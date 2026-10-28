"""Render tmsetup role templates the way Ansible's template module does, so tests can check them off-device.

Uses Jinja2 with Ansible's filters and core tests, Ansible's trim_blocks default, and StrictUndefined, so a template
that needs a variable the test didn't pass fails loudly. Jinja's own `default`/`d` are kept because
ansible-core 2.19+ replaces them with versions that don't recognize plain Jinja undefined values.
"""

import functools
import re
from pathlib import Path

import jinja2
import yaml
from ansible.plugins.filter import core, encryption, mathstuff, urls, urlsplit
from ansible.plugins.test import core as core_tests

REPO = Path(__file__).resolve().parents[2]
ROLE = REPO / "script" / "ansible" / "roles" / "tmsetup"


@functools.cache
def _environment():
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(REPO)),
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        keep_trailing_newline=True,
    )
    for module in (core, encryption, mathstuff, urls, urlsplit):
        env.filters.update({name: f for name, f in module.FilterModule().filters().items() if name not in ("default", "d")})
    env.tests.update(core_tests.TestModule().tests())  # such as `is changed` on a registered result
    return env


def render(template, **variables):
    """Render a template given by its path relative to the repo root."""
    return _environment().get_template(template).render(**variables)


def evaluate(value, **variables):
    """Evaluate a task's argument the way Ansible's native templating does, for values that are a single
    {{ expression }}: dicts and lists recursively, each expression to its Python value, anything else unchanged."""
    if isinstance(value, dict):
        return {key: evaluate(item, **variables) for key, item in value.items()}
    if isinstance(value, list):
        return [evaluate(item, **variables) for item in value]
    if isinstance(value, str):
        match = re.fullmatch(r"\{\{(.*)\}\}", value.strip(), re.DOTALL)
        if match:
            return _environment().compile_expression(match.group(1).strip(), undefined_to_none=False)(**variables)
    return value


def load_role_yaml(relative_path):
    """Load a YAML file from the tmsetup role, e.g. 'vars/main.yml' or 'tasks/secrets.yml'."""
    return yaml.safe_load((ROLE / relative_path).read_text())
