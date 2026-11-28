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
    env.globals["lookup"] = _lookup
    return env


def _lookup(name, term):
    """Ansible's file lookup as a role's template uses it: the path is under the role's files/, read on the
    controller, with trailing whitespace stripped (the lookup's rstrip default). No other lookup is needed yet."""
    if name not in ("file", "ansible.builtin.file"):
        raise NotImplementedError(f"tmsetup_render has no {name} lookup")
    return (ROLE / "files" / term).read_text(encoding="utf-8").rstrip()


def render(template, **variables):
    """Render a template given by its path relative to the repo root.

    Like Ansible's template module, the result ends with at least as many newlines as the template file does, even
    where a block tag or a "-" stripped them: Ansible counts the file's own and adds back the difference."""
    source = (REPO / template).read_text(encoding="utf-8")
    result = _environment().get_template(template).render(**variables)
    missing = _trailing_newlines(source) - _trailing_newlines(result)
    return result + "\n" * missing if missing > 0 else result


def _trailing_newlines(text):
    return len(text) - len(text.rstrip("\n"))


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
