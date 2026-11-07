"""The Detection page's backend: Frigate's model_cache directory as a list of models, each a file with a sidecar in
Frigate+'s record shape."""

from tm_control.modules import Module
from tm_control.modules.detection.router import router

module = Module("detection", router)
