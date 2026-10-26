"""Render tmsetup role templates the way Ansible's template module does, so tests can check them off-device.

Uses Jinja2 with Ansible's filters, Ansible's trim_blocks default, and StrictUndefined, so a template
that needs a variable the test didn't pass fails loudly. Jinja's own `default`/`d` are kept because
ansible-core 2.19+ replaces them with versions that don't recognize plain Jinja undefined values.
"""

import functools
from pathlib import Path

import jinja2
import yaml
from ansible.plugins.filter import core, encryption, mathstuff, urls, urlsplit

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
    return env


def render(template, **variables):
    """Render a template given by its path relative to the repo root."""
    return _environment().get_template(template).render(**variables)


def load_role_yaml(relative_path):
    """Load a YAML file from the tmsetup role, e.g. 'vars/main.yml' or 'tasks/secrets.yml'."""
    return yaml.safe_load((ROLE / relative_path).read_text())
