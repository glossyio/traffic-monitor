"""The apps (Frigate, Node-RED, go2rtc, the MQTT broker) and the names their configs must agree on: the apps and
configuration checks in the status report. No API of its own."""

from fastapi import APIRouter

from tm_control.modules import Module
from tm_control.modules.apps import checks, contracts

module = Module("apps", APIRouter(), check_groups=(checks.GROUP, contracts.GROUP))
