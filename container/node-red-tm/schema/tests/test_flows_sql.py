"""Every static SQL statement in flows.json must compile against the migrated schema.

This catches flows that use a table or column the migrations don't define, such as
a renamed column or a new INSERT without a matching migration. SQL that function
nodes build in JavaScript isn't covered.
"""

import json
import re
import sqlite3

import pytest

from helpers import FLOWS_JSON, migrate

MUSTACHE = re.compile(r"\{\{\{?[^}]*\}?\}\}")
NAMED_PARAMETER = re.compile(r"\$(\w+)")


def flow_statements():
    """SQL from prepared/fixed sqlite nodes and from the template/inject nodes that feed sqlite nodes."""
    flows = json.loads(FLOWS_JSON.read_text())
    tabs = {node["id"]: node.get("label") for node in flows if node.get("type") == "tab"}
    sqlite_ids = {node["id"] for node in flows if node.get("type") == "sqlite"}
    statements = []
    for node in flows:
        kind = node.get("type")
        if kind == "sqlite" and node.get("sqlquery") in ("prepared", "fixed"):
            sql = node.get("sql")
        elif kind in ("template", "inject") and any(t in sqlite_ids for wire in node.get("wires", []) for t in wire):
            sql = node.get("template") if kind == "template" else node.get("topic")
        else:
            continue
        if sql and sql.strip():
            label = f"{tabs.get(node.get('z'), node.get('z'))}/{node.get('name') or node['id']}"
            statements.append(pytest.param(sql, id=label))
    return statements


STATEMENTS = flow_statements()


@pytest.fixture(scope="module")
def schema(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "tmdb.sqlite"
    assert migrate("--db", path) == 0
    con = sqlite3.connect(path)
    yield con
    con.close()


def test_flows_contain_sql_to_check():
    # Guards against the collector silently finding nothing after a flows.json restructure.
    assert STATEMENTS


@pytest.mark.parametrize("sql", STATEMENTS)
def test_flow_sql_compiles_against_schema(schema, sql):
    sql = MUSTACHE.sub("0", sql).strip().rstrip(";")
    parameters = {name: None for name in NAMED_PARAMETER.findall(sql)}
    schema.execute("EXPLAIN " + sql, parameters)
