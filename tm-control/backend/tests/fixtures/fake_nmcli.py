#!/usr/bin/env python3
"""A stand-in for nmcli, for the tests of the root scripts that call it. Not a model of NetworkManager.

State is a JSON file named by FAKE_NMCLI_STATE:
    {"profiles": {"<name>": {"<setting.property>": "<value>", ...}}, "active": ["<name>", ...], "fail": ["<verb>", ...]}
A profile's connection.uuid is made up on first use. Missing connection.type, .autoconnect and .timestamp read as
802-11-wireless, yes and 0. Verbs listed under "fail" exit 4 with a message that quotes the whole command line,
secrets included, as nmcli's own errors may, so a test can check that the caller keeps them out of what it prints.
Each call's argv is appended to the file named by FAKE_NMCLI_LOG as one JSON list; the value after an argument ending
in "psk" is replaced by "***" when the call is `add` or `modify`.

Answers, like nmcli's, with ":" and "\\" in values escaped by a backslash (-t and -g):
  [-t] -f FIELDS connection show [--active]      one line per profile; FIELDS from NAME UUID TYPE AUTOCONNECT TIMESTAMP
  [-t] [-s] -g PROPS connection show REF         one line per property, empty when unset; psk only with -s
  connection add type wifi PROP VALUE ...        connection.id names the new profile
  connection modify REF PROP VALUE ...           connection.id renames; activity follows the name
REF is `NAME`, `id NAME` or `uuid UUID`. A profile that doesn't exist is exit 10, as in nmcli.
"""

import json
import os
import sys
import uuid

STATE, LOG = os.environ["FAKE_NMCLI_STATE"], os.environ.get("FAKE_NMCLI_LOG")
LISTED = {"UUID": "connection.uuid", "TYPE": "connection.type", "AUTOCONNECT": "connection.autoconnect",
          "TIMESTAMP": "connection.timestamp"}
DEFAULTS = {"connection.type": "802-11-wireless", "connection.autoconnect": "yes", "connection.timestamp": "0"}


def escape(value):
    return value.replace("\\", "\\\\").replace(":", "\\:")


def die(code, message):
    print(message, file=sys.stderr)
    sys.exit(code)


def load():
    with open(STATE) as file:
        state = json.load(file)
    for name, props in state["profiles"].items():
        props.setdefault("connection.uuid", str(uuid.uuid5(uuid.NAMESPACE_DNS, name)))
    return state


def save(state):
    with open(STATE, "w") as file:
        json.dump(state, file)


def find(state, ref):
    kind, value = ref if len(ref) == 2 else ("id", ref[0])
    for name, props in state["profiles"].items():
        if (props["connection.uuid"] if kind == "uuid" else name) == value:
            return name
    die(10, f"Error: unknown connection '{value}'.")


def value_of(name, props, key):
    return name if key == "connection.id" else props.get(key, DEFAULTS.get(key, ""))


def pairs(items):
    if len(items) % 2:
        die(2, "Error: a property without a value.")
    return dict(zip(items[::2], items[1::2]))


def main(argv):
    flags, positional, fields, index = set(), [], None, 0
    while index < len(argv):
        arg = argv[index]
        if arg in ("-g", "-f"):
            fields, index = (arg, argv[index + 1]), index + 1
        elif arg == "--active" or (arg.startswith("-") and not positional):  # later, "-100" is a value
            flags.add(arg)
        else:
            positional.append(arg)
        index += 1
    if positional[:1] != ["connection"] or len(positional) < 2:
        die(2, "Error: only `connection` commands are faked.")
    verb, rest = positional[1], positional[2:]
    log, hide = [], False
    for arg in argv:
        log.append("***" if hide else arg)
        hide = verb in ("add", "modify") and arg.endswith("psk")
    if LOG:
        with open(LOG, "a") as file:
            file.write(json.dumps(log) + "\n")
    state = load()
    if verb in state.get("fail", []):
        die(4, "Error: simulated failure of: " + " ".join(argv))

    if verb == "show" and not rest:
        if "--active" in flags:
            names = state.get("active", [])
        else:
            names = list(state["profiles"])
        for name in names:
            props = state["profiles"].get(name, {})
            wanted = fields[1].split(",") if fields else ["NAME"]
            print(":".join(escape(name if f == "NAME" else value_of(name, props, LISTED[f])) for f in wanted))
    elif verb == "show":
        name = find(state, rest)
        props = state["profiles"][name]
        for key in fields[1].split(","):
            secret = key.endswith(".psk") and "-s" not in flags
            print("" if secret else escape(value_of(name, props, key)))
    elif verb == "modify":
        ref = rest[:2] if rest[0] in ("id", "uuid") else rest[:1]
        name = find(state, ref)
        changes = pairs(rest[len(ref):])
        props = state["profiles"].pop(name)
        new_name = changes.pop("connection.id", name)
        props.update(changes)
        state["profiles"][new_name] = props
        state["active"] = [new_name if n == name else n for n in state.get("active", [])]
    elif verb == "add":
        changes = pairs(rest)
        if changes.pop("type", None) != "wifi" or "connection.id" not in changes:
            die(2, "Error: only `add type wifi` with connection.id is faked.")
        name = changes.pop("connection.id")
        if name in state["profiles"]:
            die(1, f"Error: the connection '{name}' exists.")
        state["profiles"][name] = {**changes, "connection.uuid": str(uuid.uuid4())}
    else:
        die(2, f"Error: `connection {verb}` is not faked.")
    save(state)


if __name__ == "__main__":
    main(sys.argv[1:])
