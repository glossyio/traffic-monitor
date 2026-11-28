"""The pictures an admin kept (/api/v1/pictures): the list, each picture's two frames, a delete, and the zip of one
picture. Keeping a take is the Cameras router's route (POST /cameras/{name}/reference/{ticket}/keep), which answers
with the PictureOut made here.

Nothing here logs. A picture's id, place, camera, and point stay in the answers to the admin who asked and in the audit
rows item 18 lists: the place's id and the camera's key, never a picture's id or a coordinate.
"""

from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel

from tm_control.core.auth import Audit, User
from tm_control.core.errors import ApiError
from tm_control.modules import Module
from tm_control.modules.auth.deps import require_admin
from tm_control.modules.cameras import reference
from tm_control.modules.cameras.reference import Mark
from tm_control.modules.location.places import Places
from tm_control.modules.pictures.errors import storage_error

if TYPE_CHECKING:  # store.py imports the cameras package, which imports this module
    from tm_control.modules.pictures.store import Stored

router = APIRouter(prefix="/pictures", tags=["pictures"])

PICTURE_BODY = {200: {"description": "The picture", "content": {"image/jpeg": {"schema": {"type": "string",
                                                                                         "format": "binary"}}}}}
ZIP_BODY = {200: {"description": "The zip", "content": {"application/zip": {"schema": {"type": "string",
                                                                                      "format": "binary"}}}}}
NO_STORE = {"Cache-Control": "no-store"}
FRAMES = ("clean.jpg", "zones.jpg")


class PictureOut(BaseModel):
    id: str
    survey_id: str
    camera: str  # the sensors.cameras key
    taken_at: str  # the clean frame's time, as in the data file
    reason: Literal["deployed", "opted_in", "mounting", "setup", "daylight", "manual"]
    mark: Mark
    after_restart: bool  # the first picture of a camera after the unit restarted
    bytes: int  # both frames together


class PicturesState(BaseModel):
    pictures: list[PictureOut]  # newest first; one place's when asked
    stored: int  # the whole device's count and bytes, whatever the list is of
    stored_bytes: int


class PackageIn(BaseModel):
    location: bool  # put the place's exact location in the data file
    looked: Literal[True]  # the admin looked at both views first


def picture_out(stored: "Stored") -> PictureOut:
    return PictureOut(
        id=stored.id,
        survey_id=stored.survey_id,
        camera=stored.camera,
        taken_at=reference.iso(stored.clean_at),
        reason=stored.reason,
        mark=stored.mark,
        after_restart=stored.after_restart,
        bytes=stored.clean_bytes + stored.zones_bytes,
    )


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "There is no such picture.")


@router.get("", response_model=PicturesState)
def list_pictures(
    request: Request, survey_id: str | None = Query(None), admin: User = Depends(require_admin)
) -> PicturesState:
    """The kept pictures, newest first: the whole device's, or one place's with `survey_id`."""
    pictures = request.app.state.pictures
    stored, stored_bytes = pictures.total()
    return PicturesState(
        pictures=[picture_out(one) for one in pictures.all(survey_id)], stored=stored, stored_bytes=stored_bytes
    )


@router.get("/{picture_id}/{picture}", response_class=Response, responses=PICTURE_BODY)
def picture_frame(picture_id: str, picture: str, request: Request, admin: User = Depends(require_admin)) -> Response:
    """One of a picture's two frames, as Frigate sent it."""
    try:
        found = request.app.state.pictures.frame(picture_id, picture) if picture in FRAMES else None
    except OSError as error:
        raise storage_error(error) from None
    if found is None:
        raise _not_found()
    return Response(found, media_type="image/jpeg", headers=NO_STORE)


@router.delete("/{picture_id}", status_code=204)
def delete_picture(picture_id: str, request: Request, admin: User = Depends(require_admin)) -> Response:
    """Delete a picture: its files, then its row. 204 whether or not there was one."""
    try:
        gone = request.app.state.pictures.delete(picture_id)
    except OSError as error:
        raise storage_error(error) from None
    if gone is not None:
        detail = f"{gone.survey_id} {gone.camera} {gone.reason}"
        Audit(request.app.state.state).record(admin.id, "picture.delete", detail)
    return Response(status_code=204)


@router.post("/{picture_id}/package", response_class=Response, responses=ZIP_BODY)
def picture_package(
    picture_id: str, body: PackageIn, request: Request, admin: User = Depends(require_admin)
) -> Response:
    """The zip of one picture, as the Cameras page's is: the two frames, the data file (with the place's point as it is
    now, when `location` is true and the place has one), and the drawing."""
    app_state = request.app.state
    stored = app_state.pictures.get(picture_id)
    if stored is None:
        raise _not_found()
    place = Places(app_state.state).get(stored.survey_id)
    point = None
    if body.location and place is not None and place.lat is not None and place.lon is not None:
        point = (place.lat, place.lon)
    try:
        shot = app_state.pictures.shot(stored, point)
    except OSError as error:
        raise storage_error(error) from None
    if shot is None:
        raise _not_found()
    content = reference.package(shot, with_location=body.location)
    action = "picture.download_with_location" if point else "picture.download"
    Audit(app_state.state).record(admin.id, action, f"{stored.survey_id} {stored.camera}")
    return Response(
        content, media_type="application/zip",
        headers=NO_STORE | {"Content-Disposition": f'attachment; filename="{reference.stem(shot)}.zip"'},
    )


module = Module("pictures", router)
