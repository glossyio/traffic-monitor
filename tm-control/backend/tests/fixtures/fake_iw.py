#!/usr/bin/env python3
"""A stand-in for iw, for the tests of the root scripts that call it. Not a model of a radio.

State is a JSON file named by FAKE_IW_STATE: {"stations": ["<mac>", ...], "scan": ["<ssid>", ...], "fail": ["<verb>", ...]}.
Each call's argv is appended to the file named by FAKE_IW_LOG as one JSON list. Answers, in iw's layout:
  dev DEV station dump    one "Station <mac> (on DEV)" paragraph per station
  dev DEV scan [flush]    one "BSS ..." paragraph with an "SSID: <name>" line per network; a hidden one has an empty name.
                          A "scan_text" in the state is printed instead, as the scan's whole output
A verb in "fail" exits 240 (iw's busy) with a message on stderr. A verb in "fail_once" does the same for the first call
only (the entry is removed from the state file). A verb in "hang" sleeps for a minute before it answers.
"""

import json
import os
import sys
import time

argv = sys.argv[1:]
if os.environ.get("FAKE_IW_LOG"):
    with open(os.environ["FAKE_IW_LOG"], "a") as file:
        file.write(json.dumps(argv) + "\n")
with open(os.environ["FAKE_IW_STATE"]) as file:
    state = json.load(file)
if len(argv) < 3 or argv[0] != "dev" or argv[2] not in ("station", "scan"):
    print("command failed: not faked", file=sys.stderr)
    sys.exit(1)
device, verb = argv[1], argv[2]
if verb in state.get("fail_once", []):
    state["fail_once"].remove(verb)
    with open(os.environ["FAKE_IW_STATE"], "w") as file:
        json.dump(state, file)
    print("command failed: Device or resource busy (-16)", file=sys.stderr)
    sys.exit(240)
if verb in state.get("hang", []):
    time.sleep(60)
if verb in state.get("fail", []):
    print("command failed: Device or resource busy (-16)", file=sys.stderr)
    sys.exit(240)
if verb == "station" and argv[3:] == ["dump"]:
    for mac in state.get("stations", []):
        print(f"Station {mac} (on {device})\n\tinactive time:\t120 ms\n\tsignal:  \t-52 dBm")
elif verb == "scan" and argv[3:] in ([], ["flush"]) and "scan_text" in state:
    print(state["scan_text"], end="")
elif verb == "scan" and argv[3:] in ([], ["flush"]):
    for index, ssid in enumerate(state.get("scan", [])):
        print(f"BSS 02:00:00:00:00:{index:02x}(on {device})\n\tfreq: 2437\n\tSSID: {ssid}")
else:
    print("command failed: not faked", file=sys.stderr)
    sys.exit(1)
