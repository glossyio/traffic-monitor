"""The Cameras page: sensors.cameras in config.yml kept in step with Frigate's cameras (/api/v1/cameras)."""

from tm_control.modules import Module
from tm_control.modules.cameras.router import router

module = Module("cameras", router)
