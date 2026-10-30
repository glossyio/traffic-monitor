"""The hardware: the AI accelerators, the HEVC decoder, and the radars, in the status report's hardware checks. No
API of its own."""

from fastapi import APIRouter

from tm_control.modules import Module
from tm_control.modules.hardware import checks

module = Module("hardware", APIRouter(), check_groups=(checks.GROUP,))
