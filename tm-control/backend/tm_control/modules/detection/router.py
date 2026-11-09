"""GET /models: the detector, the model Frigate runs, what is in model_cache, and the two label lists, for any logged-in
user. A model's listing carries the fields below and nothing else from its sidecar; the per-camera counts a Frigate+
record keeps are never read.

An admin can also upload a model file, its sidecar, or a zip or tar.gz of both (PUT /models/upload/{filename}), write a
sidecar for a bare model file from a form (POST /models/{name}/sidecar), download a model as a zip of both files and
SHA256SUMS (GET /models/{name}/package), and delete a model (DELETE /models/{name}). Each writes only inside
model_cache, through the directory's descriptor, or tm-control's own state directory, and audits the name of what it
wrote, sent, or removed, never a file's content.

Using a model (POST /models/{name}/use) or the installer's default (POST /models/default/use) sets the `model:` section
of Frigate's config.yml, through Frigate's config API or, when Frigate doesn't answer, in the file, then restarts
frigate.service through systemd. Fake mode only changes which model the fake Frigate runs.
"""

import json
import os
import stat
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from tm_control import fake
from tm_control.adapters import frigate, systemd
from tm_control.adapters.yamlfile import ConfigRead
from tm_control.core.auth import Audit, User
from tm_control.core.errors import ApiError
from tm_control.core.manifest import Manifest
from tm_control.core.settings import Settings
from tm_control.modules.apps import probes
from tm_control.modules.auth.deps import current_user, require_admin
from tm_control.modules.detection import archives, package, picker, upload
from tm_control.modules.detection.inventory import (
    MODEL_FILE_MAX,
    SIDECAR,
    SIDECAR_MAX,
    InstallerDefault,
    Model,
    SidecarError,
    default_files,
    forget,
    installer_default,
    inventory,
    model_cache_dir,
    open_cache,
    parse_sidecar,
    stat_in,
    valid_name,
)
from tm_control.modules.detection.labels import of_model, recognised, tracked
from tm_control.modules.detection.picker import Running, UseError, detector_type, running_model
from tm_control.modules.detection.upload import UploadError
from tm_control.modules.services.units import restart_or_log

router = APIRouter(prefix="/models", tags=["models"])


class ModelFileOut(BaseModel):
    name: str
    size: int
    sha256: str | None


class ModelOut(BaseModel):
    name: str
    kind: Literal["frigate_plus", "local", "installer_default", "frigate_default"]
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
    labels: list[str] | None  # what this model recognises, from its sidecar or the installer's labels file


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
    frigate_safe_mode: bool  # Frigate couldn't use its config and runs a stand-in; the rest is read from config.yml
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


def _frigate_answer(request: Request) -> tuple[dict | None, ConfigRead]:
    """Frigate's running config (None when it doesn't answer) and its config.yml as the host has it."""
    settings, _, codedir = _state(request)
    if settings.fake:
        return fake.frigate_answer(settings)
    return frigate.config(), frigate.config_file(codedir)


def _frigate(request: Request) -> tuple[dict | None, ConfigRead]:
    """What the detector, the running model, and the labels are read from: Frigate's answer, unless Frigate started
    in safe mode. Its config then is a stand-in (a cpu detector, no model, no cameras) rather than config.yml's, so
    it's treated as no answer and the file is read instead, which is what Frigate will run once its config is
    usable again."""
    frigate_config, config_file = _frigate_answer(request)
    return (None if probes.frigate_safe_mode(frigate_config) else frigate_config), config_file


def _model_out(model: Model, running: Running, detector: str | None, installer: InstallerDefault | None) -> ModelOut:
    sidecar = model.sidecar
    frigates_own = model.kind == running.kind == "frigate_default" and running.path is None  # Frigate runs it unasked
    is_running = model.name == running.name or frigates_own
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
        deletable=not is_running and model.kind in ("frigate_plus", "local"),
        problem=model.problem,
        labels=of_model(model, installer),
    )


@router.get("", response_model=ModelsState)
def get_models(request: Request, user: User = Depends(current_user)):
    settings, manifest, codedir = _state(request)
    answer, config_file = _frigate_answer(request)
    safe_mode = probes.frigate_safe_mode(answer)
    frigate_config = None if safe_mode else answer
    installer = installer_default(manifest, codedir)
    detector = detector_type(frigate_config, config_file)
    models = inventory(model_cache_dir(settings, manifest), installer, detector)
    running = running_model(frigate_config, config_file, installer, models)
    labels, source = recognised(frigate_config, running, models, installer)
    if detector is None:
        default = None
    else:
        default = "installer_default" if detector == "edgetpu" and installer is not None else "frigate_default"
    return ModelsState(
        detector=detector,
        frigate_answers=answer is not None,
        frigate_safe_mode=safe_mode,
        default=default,
        running=RunningOut(name=running.name, kind=running.kind, source=running.source),
        models=[_model_out(model, running, detector, installer) for model in models],
        labels=LabelsOut(recognised=labels, source=source, tracked=tracked(frigate_config)),
    )


ERROR_CODES = {
    400: "bad_request", 404: "not_found", 409: "conflict", 413: "too_large", 422: "validation",
    507: "insufficient_storage",
}
NO_SUCH_MODEL = "There is no such model."
DEFAULT = "default"  # the name the default route answers and audits; no model file may have it
DEFAULTS = {"installer_default": "That's the installer's model.", "frigate_default": "That's Frigate's built-in model."}
RUNNING = "That model is running; use another model first."
RUNNING_UNKNOWN = "What Frigate runs can't be told now; try again when Frigate answers."
DETECTOR_UNKNOWN = "The device's detector can't be told now; try again when Frigate answers."
HAS_SIDECAR = "The model already has a sidecar."
INCOMPLETE = "Only a model with its file and its sidecar can be downloaded."
UNREADABLE_PAIR = "The model's files can't be read."

Short = Annotated[str, StringConstraints(min_length=1, max_length=32)]
Label = Annotated[str, StringConstraints(min_length=1, max_length=64)]
Side = Annotated[int, Field(ge=1, le=8192)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class SidecarForm(BaseModel):
    """What Frigate needs to know about a model file: Frigate checks the values when the model is used."""

    model_type: Short
    width: Side
    height: Side
    input_tensor: Short
    input_pixel_format: Short
    input_dtype: Short | None = None
    labels: Annotated[list[Label], Field(min_length=1, max_length=1000)]  # in label-map index order
    name: Title | None = None  # the model's name in the list; the file name when left out


def _refusal(error: UploadError) -> ApiError:
    return ApiError(error.status, ERROR_CODES[error.status], error.message)


def _open_cache(cache: Path) -> int:
    try:
        return open_cache(cache)
    except OSError:
        raise ApiError(500, "internal", "Frigate's model_cache can't be opened.") from None


def _regular(dir_fd: int, name: str) -> bool:
    found = stat_in(dir_fd, name)
    return found is not None and stat.S_ISREG(found.st_mode)


def _listed(request: Request, name: str, frigate_answer: tuple[dict | None, ConfigRead] | None = None) -> ModelOut:
    """The model's entry as GET /models lists it, read again after a write."""
    settings, manifest, codedir = _state(request)
    frigate_config, config_file = frigate_answer or _frigate(request)
    installer = installer_default(manifest, codedir)
    detector = detector_type(frigate_config, config_file)
    models = inventory(model_cache_dir(settings, manifest), installer, detector)
    model = next((model for model in models if model.name == name), None)
    if model is None:
        raise ApiError(500, "internal", "The model was written but isn't listed.")
    running = running_model(frigate_config, config_file, installer, models)
    return _model_out(model, running, detector, installer)


def _reserved(installer, detector: str | None) -> dict[str, str]:
    """The names an upload or an archive may not write: the defaults' files, and DEFAULT, which names no model
    because POST /models/default/use is the default's route."""
    return default_files(installer, detector) | {DEFAULT: "reserved"}


def _content_length(request: Request) -> int | None:
    value = request.headers.get("content-length")
    return int(value) if value is not None and value.isascii() and value.isdigit() else None


def _finish(dir_fd: int, temp: str, filename: str, kind: str, size: int, reserved: dict[str, str]) -> tuple[str, str]:
    """Check what was received and place it; returns the name placed and the model's name. An archive's model may
    not have a name in `reserved`, the defaults' files."""
    if kind == "archive":
        archive = upload.archive_kind(filename)
        upload.check_archive(dir_fd, temp, archive)
        model = archives.place_archive(dir_fd, temp, archive, reserved)
        return model, model
    if kind == "sidecar":
        try:
            parse_sidecar(upload.read_small(dir_fd, temp, SIDECAR_MAX + 1))
        except SidecarError as error:
            raise UploadError(422, str(error)) from None
    elif size == 0:
        raise UploadError(422, upload.EMPTY)
    upload.place(dir_fd, temp, filename)
    return filename, filename.removesuffix(SIDECAR) if kind == "sidecar" else filename


RAW_BODY = {  # the body is read as a stream, so the document is told what it is
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}


@router.put("/upload/{filename:path}", status_code=201, response_model=ModelOut, openapi_extra=RAW_BODY)
async def upload_file(filename: str, request: Request, admin: User = Depends(require_admin)):
    """Stream the body into model_cache as a model file, a sidecar (<model>.json), or an archive. `:path` lets a name
    with a slash reach the name check, which refuses it."""
    settings, manifest, codedir = _state(request)
    kind = upload.kind_of_upload(filename)
    model = filename.removesuffix(SIDECAR) if kind == "sidecar" else filename
    if not valid_name(model) or model == DEFAULT:
        raise _refusal(UploadError(422, upload.BAD_NAME))
    frigate_answer = await run_in_threadpool(_frigate, request)
    defaults = _reserved(installer_default(manifest, codedir), detector_type(*frigate_answer))
    limit = SIDECAR_MAX if kind == "sidecar" else MODEL_FILE_MAX
    declared = _content_length(request)
    cache = model_cache_dir(settings, manifest)
    dir_fd = _open_cache(cache)
    temp = upload.temp_name(filename)
    received = False
    try:
        if kind != "archive" and stat_in(dir_fd, filename) is not None:
            raise upload.exists(model)
        if model in defaults:
            raise UploadError(422, upload.BAD_NAME)  # a default's file is the installer's or Frigate's to write
        if declared is not None and declared > limit:
            raise upload.too_large(limit)
        if not upload.free_space_ok(cache, limit if declared is None else declared):
            raise UploadError(507, upload.NO_SPACE)
        try:
            size = await upload.receive(request.stream(), dir_fd, temp, limit, declared)
        except ClientDisconnect:
            raise UploadError(400, upload.SHORT_BODY) from None
        received = True
        placed, model = await run_in_threadpool(_finish, dir_fd, temp, filename, kind, size, defaults)
    except UploadError as error:
        raise _refusal(error) from None
    finally:
        if received:
            upload.unlink_quietly(dir_fd, temp)
        os.close(dir_fd)
    Audit(request.app.state.state).record(admin.id, "models.upload", detail=placed)
    return await run_in_threadpool(_listed, request, model, frigate_answer)


def _form_sidecar(name: str, form: SidecarForm, detector: str) -> bytes:
    """A sidecar in the Frigate+ record's shape, with the fields Frigate reads, named as the form says or for the file,
    and without an id or a training date, so it's never taken for a Frigate+ model."""
    record = {
        "name": form.name or name,
        "type": form.model_type,
        "supportedDetectors": [detector],
        "width": form.width,
        "height": form.height,
        "inputShape": form.input_tensor,
        "pixelFormat": form.input_pixel_format,
    }
    if form.input_dtype is not None:
        record["inputDataType"] = form.input_dtype
    record["labelMap"] = {str(index): label for index, label in enumerate(form.labels)}
    return (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode()


@router.post("/{name}/sidecar", status_code=201, response_model=ModelOut)
def write_sidecar(name: str, form: SidecarForm, request: Request, admin: User = Depends(require_admin)):
    """Write <name>.json for a model file that has none, for the device's detector."""
    if not valid_name(name) or name == DEFAULT:
        raise _refusal(UploadError(422, upload.BAD_NAME))
    settings, manifest, codedir = _state(request)
    frigate_answer = _frigate(request)
    detector = detector_type(*frigate_answer)
    defaults = default_files(installer_default(manifest, codedir), detector)
    cache = model_cache_dir(settings, manifest)
    dir_fd = _open_cache(cache)
    try:
        if not _regular(dir_fd, name):
            raise ApiError(404, "not_found", NO_SUCH_MODEL)
        if name in defaults:
            raise ApiError(409, "conflict", DEFAULTS[defaults[name]])
        if stat_in(dir_fd, name + SIDECAR) is not None:
            raise ApiError(409, "conflict", HAS_SIDECAR)
        if detector is None:
            raise ApiError(409, "conflict", DETECTOR_UNKNOWN)
        data = _form_sidecar(name, form, detector)
        if not upload.free_space_ok(cache, len(data)):
            raise _refusal(UploadError(507, upload.NO_SPACE))
        temp = upload.temp_name(name + SIDECAR)
        upload.write_new(dir_fd, temp, data)
        try:
            upload.place(dir_fd, temp, name + SIDECAR)
        except UploadError:
            raise ApiError(409, "conflict", HAS_SIDECAR) from None
        finally:
            upload.unlink_quietly(dir_fd, temp)
    finally:
        os.close(dir_fd)
    Audit(request.app.state.state).record(admin.id, "models.sidecar", detail=name)
    return _listed(request, name, frigate_answer)


def _sidecar_size(dir_fd: int, name: str) -> int | None:
    """The size of the model's sidecar when it parses; None when it doesn't, or isn't there."""
    try:
        data = upload.read_small(dir_fd, name + SIDECAR, SIDECAR_MAX + 1)
        parse_sidecar(data)
    except (OSError, SidecarError):
        return None
    return len(data) if len(data) <= SIDECAR_MAX else None


ZIP_BODY = {200: {"description": "The package", "content": {"application/zip": {"schema": {"type": "string",
                                                                                       "format": "binary"}}}}}


@router.get("/{name}/package", response_class=FileResponse, responses=ZIP_BODY)
def download_package(name: str, request: Request, admin: User = Depends(require_admin)):
    """The model's file, its sidecar, and SHA256SUMS in a zip, as an attachment named <name>.zip: only for a model
    with both halves, which a default never has."""
    if not valid_name(name):
        raise _refusal(UploadError(422, upload.BAD_NAME))
    settings, manifest, codedir = _state(request)
    defaults = default_files(installer_default(manifest, codedir), detector_type(*_frigate(request)))
    dir_fd = _open_cache(model_cache_dir(settings, manifest))
    try:
        model = stat_in(dir_fd, name)
        if model is None:
            raise ApiError(404, "not_found", NO_SUCH_MODEL)
        sidecar = _sidecar_size(dir_fd, name)
        if name in defaults or not stat.S_ISREG(model.st_mode) or sidecar is None:
            raise ApiError(404, "not_found", INCOMPLETE)
        if not upload.free_space_ok(settings.state_dir, model.st_size + sidecar):
            raise _refusal(UploadError(507, upload.NO_SPACE))
        path, out = package.create(settings.state_dir, name)
        try:
            with out:
                package.write_package(dir_fd, name, out)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
    except OSError:
        raise ApiError(500, "internal", UNREADABLE_PAIR) from None
    finally:
        os.close(dir_fd)
    Audit(request.app.state.state).record(admin.id, "models.download", detail=name)
    return FileResponse(
        path, media_type="application/zip", filename=f"{name}.zip",
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@router.delete("/{name}", status_code=204)
def delete_model(name: str, request: Request, admin: User = Depends(require_admin)):
    """Remove the model's file and its sidecar, whichever are there, unless Frigate runs it or it's a default.
    What runs is Frigate's answer, or config.yml's when Frigate doesn't answer; when neither can say, nothing is
    removed."""
    if not valid_name(name):
        raise _refusal(UploadError(422, upload.BAD_NAME))
    settings, manifest, codedir = _state(request)
    installer = installer_default(manifest, codedir)
    dir_fd = _open_cache(model_cache_dir(settings, manifest))
    try:
        halves = [file for file in (name, name + SIDECAR) if _regular(dir_fd, file)]
        if not halves:
            raise ApiError(404, "not_found", NO_SUCH_MODEL)
        frigate_answer = _frigate(request)
        running = running_model(*frigate_answer, installer, [])
        if running.source is None:
            raise ApiError(409, "conflict", RUNNING_UNKNOWN)
        if running.name == name:
            raise ApiError(409, "conflict", RUNNING)
        defaults = default_files(installer, detector_type(*frigate_answer))
        if name in defaults:
            raise ApiError(409, "conflict", DEFAULTS[defaults[name]])
        for file in halves:
            try:
                os.unlink(file, dir_fd=dir_fd)
            except FileNotFoundError:
                pass
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    forget(halves)
    Audit(request.app.state.state).record(admin.id, "models.delete", detail=name)
    return Response(status_code=204)


FRIGATE_UNIT = "frigate.service"
RESTARTING = "Frigate is restarting; try again in a minute."
DEFAULT_UNKNOWN = "Frigate's detector type can't be determined, so its default model can't be chosen."
INSTALLER_MISSING = "The installer's model file isn't on the device."


class UseQueued(BaseModel):
    name: str  # the model's name, or "default"
    applied: Literal["frigate", "file"]  # who wrote config.yml: Frigate's config API, or tm-control while it was down
    restarts: list[str]  # the units restarted once this answer has been sent


def _use_refusal(error: UseError) -> ApiError:
    return ApiError(error.status, error.code, error.message)


def _not_restarting(settings: Settings) -> None:
    """Refuse while frigate.service is starting or stopping: a save then would race the restart. Fake mode has no
    systemd to ask, and when systemd can't be asked the use goes ahead; its restart is queued all the same."""
    if settings.fake:
        return
    try:
        state = systemd.show_unit(FRIGATE_UNIT, ["ActiveState"]).get("ActiveState")
    except Exception:
        return
    if state in ("activating", "deactivating"):
        raise ApiError(409, "restarting", RESTARTING)


def _use(request: Request, background: BackgroundTasks, admin: User, section: dict | None, fake_name: str,
         name: str) -> UseQueued:
    """Write section as Frigate's `model:` (None removes it), audit `name`, and queue Frigate's restart. Fake mode
    makes the fake Frigate run fake_name instead."""
    settings, _, codedir = _state(request)
    if settings.fake:
        fake.use_model(settings, fake_name)
        applied = "frigate"
    else:
        try:
            applied = picker.apply(section, codedir)
        except UseError as error:
            raise _use_refusal(error) from None
    Audit(request.app.state.state).record(admin.id, "models.use", detail=name)
    if not settings.fake:
        background.add_task(restart_or_log, FRIGATE_UNIT)
    return UseQueued(name=name, applied=applied, restarts=[FRIGATE_UNIT])


def _installer_file_there(cache: Path, name: str) -> bool:
    try:
        dir_fd = open_cache(cache)
    except OSError:
        return False
    try:
        return _regular(dir_fd, name)
    finally:
        os.close(dir_fd)


def _use_default(request: Request, background: BackgroundTasks, admin: User) -> UseQueued:
    settings, manifest, codedir = _state(request)
    _not_restarting(settings)
    detector = detector_type(*_frigate(request))
    if detector is None:
        raise ApiError(409, "detector_unknown", DEFAULT_UNKNOWN)
    installer = installer_default(manifest, codedir)
    section = picker.default_section(detector, installer)
    if section is not None and not _installer_file_there(model_cache_dir(settings, manifest), installer.file):
        raise ApiError(409, "installer_missing", INSTALLER_MISSING)  # Frigate would restart into a missing model
    return _use(request, background, admin, section, installer.file if section is not None else "", DEFAULT)


@router.post("/default/use", status_code=202, response_model=UseQueued)
def use_default(request: Request, background: BackgroundTasks, admin: User = Depends(require_admin)):
    """Put back what the installer gives this device: its Coral model for an edgetpu detector, and otherwise no
    `model:` section, so Frigate runs its own default. Declared before /{name}/use, so `default` names no model."""
    return _use_default(request, background, admin)


@router.post("/{name}/use", status_code=202, response_model=UseQueued)
def use_model(name: str, request: Request, background: BackgroundTasks, admin: User = Depends(require_admin)):
    """Make Frigate run a model in model_cache that has its file and sidecar and is built for the device's detector.
    A default's file (the installer's, or Frigate's own) is the default, as POST /models/default/use puts it back. The
    running model may be used again: Frigate just restarts."""
    if not valid_name(name):
        raise _refusal(UploadError(422, upload.BAD_NAME))
    settings, manifest, codedir = _state(request)
    installer = installer_default(manifest, codedir)
    detector = detector_type(*_frigate(request))
    if name in default_files(installer, detector):
        return _use_default(request, background, admin)
    _not_restarting(settings)
    models = inventory(model_cache_dir(settings, manifest), installer, detector)
    model = next((model for model in models if model.name == name), None)
    if model is None:
        raise ApiError(404, "not_found", NO_SUCH_MODEL)
    try:
        picker.check_usable(model, detector)
    except UseError as error:
        raise _use_refusal(error) from None
    return _use(request, background, admin, picker.model_section(model), name, name)
