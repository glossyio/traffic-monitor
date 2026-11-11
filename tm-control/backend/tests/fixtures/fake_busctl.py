#!/usr/bin/env python3
"""A stand-in for busctl, for the tests of the join job's NetworkManager checkpoint. Not a model of NetworkManager.

State is a JSON file named by FAKE_BUSCTL_STATE: {"checkpoints": {"<path>": {"active": [...]}}, "fail": ["<method>"]}.
CheckpointCreate remembers the fake nmcli's "active" list (it reads FAKE_NMCLI_STATE); CheckpointRollback puts that
list back in the fake nmcli's state and forgets the checkpoint. Each call's argv is appended to the file named by
FAKE_BUSCTL_LOG as one JSON list. Answers, in `--json=short` form:
  call ... GetDeviceByIpIface s DEV        {"type":"o","data":["/org/freedesktop/NetworkManager/Devices/3"]}
  call ... CheckpointCreate aouu 1 DEV 90 0
                                           {"type":"o","data":["/org/freedesktop/NetworkManager/Checkpoint/N"]}; fails
                                           (exit 1) while another checkpoint is pending, as NetworkManager does
  call ... CheckpointRollback o PATH       {"type":"a{su}","data":[{"<device path>":0}]}; an unknown path fails
  get-property ... Checkpoints             {"type":"ao","data":["<path>", ...]}
A method (or `Checkpoints`) listed under "fail" exits 1 with a message on stderr that quotes the whole command line.
"""

import json
import os
import sys

DEVICE = "/org/freedesktop/NetworkManager/Devices/3"
CHECKPOINT = "/org/freedesktop/NetworkManager/Checkpoint/"


def die(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def load(path, default):
    try:
        with open(path) as file:
            return json.load(file)
    except FileNotFoundError:
        return default


def save(path, state):
    with open(path, "w") as file:
        json.dump(state, file)


def main(argv):
    if os.environ.get("FAKE_BUSCTL_LOG"):
        with open(os.environ["FAKE_BUSCTL_LOG"], "a") as file:
            file.write(json.dumps(argv) + "\n")
    words = [arg for arg in argv if not arg.startswith("--")]
    if argv[:2] != ["--system", "--json=short"] or not words:
        die("Unknown options: " + " ".join(argv))
    state_path = os.environ["FAKE_BUSCTL_STATE"]
    state = load(state_path, {})
    checkpoints = state.setdefault("checkpoints", {})
    verb = words[0]
    if verb == "get-property" and words[1:] == ["org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager",
                                               "org.freedesktop.NetworkManager", "Checkpoints"]:
        if "Checkpoints" in state.get("fail", []):
            die("Failed to get property: " + " ".join(argv))
        print(json.dumps({"type": "ao", "data": list(checkpoints)}, separators=(",", ":")))
        return
    if verb != "call" or len(words) < 6:
        die("Unknown command: " + " ".join(argv))
    method, args = words[4], words[5:]
    if method in state.get("fail", []):
        die(f"Call failed: simulated failure of: {' '.join(argv)}")
    nmcli_path = os.environ["FAKE_NMCLI_STATE"]
    if method == "GetDeviceByIpIface" and args[:1] == ["s"] and len(args) == 2:
        answer = {"type": "o", "data": [DEVICE]}
    elif method == "CheckpointCreate" and args == ["aouu", "1", DEVICE, "90", "0"]:
        if checkpoints:
            die("Call failed: a checkpoint already exists for the device")
        number = state.get("next", 1)
        state["next"] = number + 1
        path = f"{CHECKPOINT}{number}"
        checkpoints[path] = {"active": load(nmcli_path, {}).get("active", [])}
        answer = {"type": "o", "data": [path]}
    elif method == "CheckpointRollback" and args[:1] == ["o"] and len(args) == 2:
        if args[1] not in checkpoints:
            die("Call failed: no such checkpoint")
        nmcli = load(nmcli_path, {})
        nmcli["active"] = checkpoints.pop(args[1])["active"]
        save(nmcli_path, nmcli)
        answer = {"type": "a{su}", "data": [{DEVICE: 0}]}
    else:
        die("Call failed: not faked: " + " ".join(argv))
    save(state_path, state)
    print(json.dumps(answer, separators=(",", ":")))


if __name__ == "__main__":
    main(sys.argv[1:])
