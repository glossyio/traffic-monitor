"""GET /models: the detector, the model Frigate runs, what is in model_cache, and the two label lists, for any logged-in
user. A model's listing carries the fields below and nothing else from its sidecar; the per-camera counts a Frigate+
record keeps are never read."""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from tm_control import fake
from tm_control.adapters import frigate
from tm_control.adapters.yamlfile import ConfigRead
from tm_control.core.auth import User
from tm_control.core.manifest import Manifest
from tm_control.core.settings import Settings
from tm_control.modules.auth.deps import current_user
from tm_control.modules.detection.inventory import Model, installer_default, inventory, model_cache_dir
from tm_control.modules.detection.labels import recognised, tracked
from tm_control.modules.detection.picker import Running, detector_type, running_model

router = APIRouter(prefix="/models", tags=["models"])


class ModelFileOut(BaseModel):
    name: str
    size: int
    sha256: str | None


class ModelOut(BaseModel):
    name: str
    kind: Literal["frigate_plus", "local", "installer_default"]
    title: str  # the sidecar's name, or the file's name
    trained_at: str | None
    type: str | None
    detectors: list[str]
    width: int | None
    height: int | None
    files: list[ModelFileOut]
    complete: bool
    running: bool
    usable: bool | None  # whether the device's detector is one the model supports; None when that can't be told
    deletable: bool
    problem: str | None


class RunningOut(BaseModel):
    name: str | None
    kind: Literal["frigate_plus", "local", "installer_default", "frigate_default"] | None
    source: Literal["frigate", "config_file"] | None


class LabelsOut(BaseModel):
    recognised: list[str] | None
    source: Literal["frigate", "sidecar", "labels_file"] | None
    tracked: list[str]


class ModelsState(BaseModel):
    detector: str | None
    frigate_answers: bool
    default: Literal["installer_default", "frigate_default"] | None  # what using the default would apply here
    running: RunningOut
    models: list[ModelOut]
    labels: LabelsOut


def _state(request: Request) -> tuple[Settings, Manifest, Path]:
    """The settings, the manifest, and the code directory: the device's, or in fake mode the fake directory, so that
    nothing under the manifest's real path is read."""
    app_state = request.app.state
    settings, manifest = app_state.settings, app_state.manifest
    return settings, manifest, settings.state_dir.parent if settings.fake else Path(manifest.codedir)


def _frigate(request: Request) -> tuple[dict | None, ConfigRead]:
    """Frigate's running config (None when it doesn't answer) and its config.yml as the host has it."""
    settings, _, codedir = _state(request)
    if settings.fake:
        return fake.frigate_answer(settings)
    return frigate.config(), frigate.config_file(codedir)


def _model_out(model: Model, running: Running, detector: str | None) -> ModelOut:
    sidecar = model.sidecar
    is_running = model.name == running.name
    return ModelOut(
        name=model.name,
        kind=model.kind,
        title=(sidecar.name if sidecar and sidecar.name else model.name),
        trained_at=sidecar.trained_at if sidecar else None,
        type=sidecar.type if sidecar else None,
        detectors=list(sidecar.detectors) if sidecar else [],
        width=sidecar.width if sidecar else None,
        height=sidecar.height if sidecar else None,
        files=[ModelFileOut(name=file.name, size=file.size, sha256=file.sha256) for file in model.files],
        complete=model.complete,
        running=is_running,
        usable=None if sidecar is None or detector is None else detector in sidecar.detectors,
        deletable=not is_running and model.kind != "installer_default",
        problem=model.problem,
    )


@router.get("", response_model=ModelsState)
def get_models(request: Request, user: User = Depends(current_user)):
    settings, manifest, codedir = _state(request)
    frigate_config, config_file = _frigate(request)
    installer = installer_default(manifest, codedir)
    models = inventory(model_cache_dir(settings, manifest), installer)
    detector = detector_type(frigate_config, config_file)
    running = running_model(frigate_config, config_file, installer, models)
    labels, source = recognised(frigate_config, running, models, installer)
    if detector is None:
        default = None
    else:
        default = "installer_default" if detector == "edgetpu" and installer is not None else "frigate_default"
    return ModelsState(
        detector=detector,
        frigate_answers=frigate_config is not None,
        default=default,
        running=RunningOut(name=running.name, kind=running.kind, source=running.source),
        models=[_model_out(model, running, detector) for model in models],
        labels=LabelsOut(recognised=labels, source=source, tracked=tracked(frigate_config)),
    )
