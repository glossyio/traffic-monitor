"""script/update.json: what a tree says about itself, so an update can tell what it is about to install."""

import json
import re
import sys

from tmsetup_render import REPO, load_role_yaml

sys.path.insert(0, str(REPO / "tm-control" / "backend"))

from tm_control.core import state  # noqa: E402

UPDATE_JSON = REPO / "script" / "update.json"
MIGRATIONS = REPO / "container" / "node-red-tm" / "schema" / "migrations"


def data():
    return json.loads(UPDATE_JSON.read_text())


def test_update_json_has_exactly_its_four_keys():
    assert set(data()) == {"contracts", "tm_version", "tmdb_schema", "state_schema"}


def test_it_accepts_contract_1():
    assert data()["contracts"] == [1]


def test_its_version_is_the_roles():
    assert data()["tm_version"] == load_role_yaml("vars/main.yml")["tmsetup_tm_version"]


def test_its_tmdb_number_is_the_newest_migration_file():
    numbers = [int(match.group(1)) for path in MIGRATIONS.glob("*.sql") if (match := re.match(r"(\d{4})_", path.name))]
    assert data()["tmdb_schema"] == max(numbers)


def test_its_state_number_is_the_number_of_state_migrations():
    assert data()["state_schema"] == len(state.MIGRATIONS)
