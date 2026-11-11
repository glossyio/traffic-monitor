#!/usr/bin/env python3
"""A stand-in for nmcli, for the tests of the root scripts that call it. Not a model of NetworkManager.

State is a JSON file named by FAKE_NMCLI_STATE:
    {"profiles": {"<name>": {"<setting.property>": "<value>", ...}}, "active": ["<name>", ...], "fail": ["<verb>", ...]}
A profile's connection.uuid is made up on first use. Missing connection.type, .autoconnect and .timestamp read as
802-11-wireless, yes and 0. Verbs listed under "fail" exit 4 with a message that quotes the whole command line,
secrets included, as nmcli's own errors may, so a test can check that the caller keeps them out of what it prints.
Each call's argv is appended to the file named by FAKE_NMCLI_LOG as one JSON list; the value after an argument ending
in ".psk" is replaced by "***" when the call is `add` or `modify`.

Answers, like nmcli's, with ":" and "\\" in values escaped by a backslash (-t and -g):
  [-t] -f FIELDS connection show [--active]      one line per profile; FIELDS from NAME UUID TYPE AUTOCONNECT TIMESTAMP
  [-t] [-s] -g PROPS connection show REF         one line per property, empty when unset; psk only with -s. Like
                                                 nmcli, it leaves out a property whose setting (the part before the
                                                 first ".") the profile doesn't have: connection, ipv4, ipv6, the
                                                 profile's type, and any setting with a stored property are present
  connection add type wifi PROP VALUE ...        connection.id names the new profile; a connection.uuid it is given is
                                                 kept; `save no` lists the profile under the state's "unsaved" (a
                                                 `modify` takes it off that list)
  connection delete REF                          removes the profile, and from "active" and "unsaved"
  connection modify REF PROP VALUE ...           connection.id renames; activity follows the name
  connection up [--wait N] REF                   makes the profile the only active one; "up": {"<name>": "fail"} in the
                                                 state makes it exit 4 and leave nothing active (an idle radio), and
                                                 "up": {"<name>": "fail-started"} makes it exit 4 with the profile the
                                                 only active one (NetworkManager started it by itself meanwhile);
                                                 "fail-once" is "fail" for this call only (the entry is removed);
                                                 "timeout" exits 3 (nmcli's wait ran out) with the profile the only
                                                 active one; "up_delay": {"<name>": SECONDS} makes it sleep first;
                                                 "up_then_fail": {"<name>": N} lets `up` on that profile work N times
                                                 and then fail as its "up" entry says, or else like "fail"
  connection down REF                            removes the profile from "active"
  device show DEV  (-t -f GENERAL.STATE,GENERAL.CONNECTION,GENERAL.CON-UUID)   state 100 and the first active profile
                                                 (and its uuid), else 30, "--" and ""; "device_states": {"<name>": N}
                                                 gives the number while that profile is the first active one, and
                                                 "device_state": N in the state overrides both
  device show DEV  (-t -f IP4.ADDRESS,IP4.DNS)   IP4.ADDRESS[1] and IP4.DNS[1..n] of the first active profile, from
                                                 the state's "ip4": {"<name>": {"address": "192.168.1.57/24",
                                                 "dns": ["192.168.1.1"]}}; no lines for a profile not listed there
                                                 Either form exits 4 when it asks for a field listed in the state's
                                                 "fail_fields"
  radio wifi                                    the state's "radio", "enabled" unless set
  radio wifi on|off                              sets the state's "radio" to "enabled" or "disabled"
Any -f field that isn't listed above is read as a profile property. REF is `NAME`, `id NAME` or `uuid UUID`. A profile that doesn't exist is exit 10, as in nmcli.
"""

import json
import os
import sys
import time
import uuid

STATE, LOG = os.environ["FAKE_NMCLI_STATE"], os.environ.get("FAKE_NMCLI_LOG")
LISTED = {"UUID": "connection.uuid", "TYPE": "connection.type", "AUTOCONNECT": "connection.autoconnect",
          "TIMESTAMP": "connection.timestamp"}
DEFAULTS = {"connection.type": "802-11-wireless", "connection.autoconnect": "yes", "connection.timestamp": "0",
            "connection.autoconnect-priority": "0", "802-11-wireless.mode": "infrastructure",
            "802-11-wireless.hidden": "no"}


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
        if arg == "--wait":  # a global option with a value; the fake never waits
            index += 1
        elif arg in ("-g", "-f"):
            fields, index = (arg, argv[index + 1]), index + 1
        elif arg == "--active" or (arg.startswith("-") and not positional):  # later, "-100" is a value
            flags.add(arg)
        else:
            positional.append(arg)
        index += 1
    if positional[:1] not in (["connection"], ["device"], ["radio"]) or len(positional) < 2:
        die(2, "Error: only `connection`, `device show` and `radio wifi` are faked.")
    group, verb, rest = positional[0], positional[1], positional[2:]
    log, hide = [], False
    for arg in argv:
        log.append("***" if hide else arg)
        hide = verb in ("add", "modify") and arg.endswith(".psk")  # not wpa-psk
    if LOG:
        with open(LOG, "a") as file:
            file.write(json.dumps(log) + "\n")
    state = load()
    if verb in state.get("fail", []):
        die(4, "Error: simulated failure of: " + " ".join(argv))

    if group == "radio" and verb == "wifi":
        if rest:
            if rest != ["on"] and rest != ["off"]:
                die(2, "Error: only `radio wifi on|off` is faked.")
            state["radio"] = "enabled" if rest == ["on"] else "disabled"
            save(state)
        else:
            print(state.get("radio", "enabled"))
        return
    if group == "device" and verb == "show":
        if set(fields[1].split(",")) & set(state.get("fail_fields", [])):
            die(4, "Error: simulated failure of: " + " ".join(argv))
        active = state.get("active", [])
        number = state.get("device_state", state.get("device_states", {}).get(active[0], 100) if active else 30)
        values = {"GENERAL.STATE": f"{number} (fake)", "GENERAL.CONNECTION": active[0] if active else "--",
                  "GENERAL.CON-UUID": state["profiles"].get(active[0], {}).get("connection.uuid", "") if active else ""}
        ip4 = state.get("ip4", {}).get(active[0], {}) if active else {}
        for key in fields[1].split(","):
            if key == "IP4.ADDRESS":
                if ip4.get("address"):
                    print(f"IP4.ADDRESS[1]:{escape(ip4['address'])}")
            elif key == "IP4.DNS":
                for index, server in enumerate(ip4.get("dns", []), start=1):
                    print(f"IP4.DNS[{index}]:{escape(server)}")
            else:
                print(f"{key}:{escape(values[key])}")
        return
    if group != "connection":
        die(2, f"Error: `{group} {verb}` is not faked.")
    if verb == "show" and not rest:
        if "--active" in flags:
            names = state.get("active", [])
        else:
            names = list(state["profiles"])
        for name in names:
            props = state["profiles"].get(name, {})
            wanted = fields[1].split(",") if fields else ["NAME"]
            print(":".join(escape(name if f == "NAME" else value_of(name, props, LISTED.get(f, f))) for f in wanted))
    elif verb == "show":
        name = find(state, rest)
        props = state["profiles"][name]
        present = {"connection", "ipv4", "ipv6", value_of(name, props, "connection.type")}
        present |= {key.split(".")[0] for key in props}
        for key in fields[1].split(","):
            if key.split(".")[0] not in present:
                continue
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
        state["unsaved"] = [n for n in state.get("unsaved", []) if n != name]
        state["active"] = [new_name if n == name else n for n in state.get("active", [])]
    elif verb == "up":
        name = find(state, rest[:2] if rest[0] in ("id", "uuid") else rest[:1])
        time.sleep(state.get("up_delay", {}).get(name, 0))
        outcome = state.get("up", {}).get(name)
        works = state.get("up_then_fail", {}).get(name)
        if works is not None:
            state["up_then_fail"][name] = max(works - 1, 0)
            outcome = None if works > 0 else outcome or "fail"
        if outcome == "fail-once":
            del state["up"][name]
        state["active"] = [] if outcome in ("fail", "fail-once") else [name]
        save(state)
        if outcome in ("fail", "fail-once", "fail-started"):
            die(4, f"Error: Connection activation failed for '{name}'.")
        if outcome == "timeout":
            die(3, f"Error: Timeout expired while activating '{name}'.")
    elif verb == "down":
        name = find(state, rest[:2] if rest[0] in ("id", "uuid") else rest[:1])
        state["active"] = [n for n in state.get("active", []) if n != name]
    elif verb == "delete":
        name = find(state, rest[:2] if rest[0] in ("id", "uuid") else rest[:1])
        del state["profiles"][name]
        state["active"] = [n for n in state.get("active", []) if n != name]
        state["unsaved"] = [n for n in state.get("unsaved", []) if n != name]
    elif verb == "add":
        changes = pairs(rest)
        if changes.pop("type", None) != "wifi" or "connection.id" not in changes:
            die(2, "Error: only `add type wifi` with connection.id is faked.")
        name = changes.pop("connection.id")
        if name in state["profiles"]:
            die(1, f"Error: the connection '{name}' exists.")
        if changes.pop("save", "yes") == "no":
            state.setdefault("unsaved", []).append(name)
        state["profiles"][name] = {**changes, "connection.uuid": changes.get("connection.uuid") or str(uuid.uuid4())}
    else:
        die(2, f"Error: `connection {verb}` is not faked.")
    save(state)


if __name__ == "__main__":
    main(sys.argv[1:])
