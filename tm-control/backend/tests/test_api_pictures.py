"""The pictures an administrator keeps: POST /api/v1/cameras/{name}/reference/{ticket}/keep stores a held take for the
place in use, and /api/v1/pictures lists, shows, packages, and deletes what is stored.

claimed_client runs in fake mode: the fake Frigate's frames are the two drawn fixtures, and the claim made the first
place from the seeded config.yml (45.0, -122.0). No picture, id, place, camera, or point reaches a log line, an error,
or an audit row beyond what item 18 lists.
"""

import errno
import json
import logging
import sqlite3
from urllib.parse import quote

import httpx

import pytest

from tests.test_api_cameras import ADMIN, JSON_HEADERS, NEUTRAL, ORIGIN, VIEWER, add, token  # noqa: F401
from tests.test_api_cameras_reference import (
    CLEAN, EXPIRED, ZONED, base, data, deploy_new_place, error, files,
    in_use, package as manual_package, take, taken, tracking, CAR, WALKER,
)
from tm_control.core.auth import Users
from tm_control.modules.location.places import Places
from tm_control.modules.pictures import store as store_module
from tm_control.modules.pictures.store import ID, Pictures

PREFIX = "/api/v1/pictures"
BAD_IDS = ["..", "../x", "a" * 15, "a" * 17, "A" * 16, "%2e%2e", ""]
MADE_UP = "0123456789abcdef"


@pytest.fixture
def admin(claimed_client, login):
    """The admin, with the claim's place already the one in use (the first read of the places settles that)."""
    login(claimed_client, *ADMIN)
    in_use(claimed_client)
    return claimed_client


def keep_url(found, name="picam_h265") -> str:
    return f"{base(found, name)}/keep"


def kept(client, name="picam_h265") -> dict:
    """A take, then keep it; the picture the keep answered."""
    found = taken(client, name)
    r = client.post(keep_url(found, name), headers=JSON_HEADERS)
    assert r.status_code == 201, r.text
    return r.json()


def listed(client, survey_id=None) -> dict:
    r = client.get(PREFIX, params={} if survey_id is None else {"survey_id": survey_id})
    assert r.status_code == 200, r.text
    return r.json()


def download(client, picture_id, location=False, looked=True, **extra):
    return client.post(f"{PREFIX}/{picture_id}/package", json={"location": location, "looked": looked} | extra,
                       headers=JSON_HEADERS)


def picture_audit(client):
    with sqlite3.connect(client.app.state.state.path) as con:
        return con.execute("SELECT action, detail FROM audit WHERE action LIKE 'picture.%' ORDER BY id").fetchall()


# Roles


@pytest.mark.parametrize("method, path, body", [
    ("get", PREFIX, None),
    ("get", f"{PREFIX}/{MADE_UP}/clean.jpg", None),
    ("delete", f"{PREFIX}/{MADE_UP}", None),
    ("post", f"{PREFIX}/{MADE_UP}/package", {"location": False, "looked": True}),
    ("post", "/api/v1/cameras/picam_h265/reference/made-up-ticket/keep", None),
])
def test_every_route_needs_an_admin(claimed_client, login, method, path, body):
    def call():
        kwargs = {"headers": JSON_HEADERS} if method != "get" else {}
        if body is not None:
            kwargs["json"] = body
        return getattr(claimed_client, method)(path, **kwargs)

    assert call().status_code == 401
    Users(claimed_client.app.state.state).create(*VIEWER, "viewer")
    login(claimed_client, *VIEWER)
    assert call().status_code == 403
    assert claimed_client.app.state.pictures.total() == (0, 0)


# Keep


def test_keep_stores_the_take_for_the_place_in_use(admin):
    place = in_use(admin)
    found = taken(admin)
    r = admin.post(keep_url(found), headers=JSON_HEADERS)
    assert r.status_code == 201, r.text
    picture = r.json()
    assert ID.fullmatch(picture["id"])
    assert (picture["survey_id"], picture["camera"], picture["reason"]) == (place["id"], "picam_h265", "manual")
    assert (picture["mark"], picture["after_restart"], picture["taken_at"]) == ("clear", False, found["taken_at"])
    assert picture["bytes"] == len(CLEAN) + len(ZONED)
    pictures = admin.app.state.pictures
    assert pictures.frame(picture["id"], "clean.jpg") == CLEAN and pictures.frame(picture["id"], "zones.jpg") == ZONED
    stored = pictures.get(picture["id"])
    users = Users(admin.app.state.state)
    assert stored.kept_by == users.by_username(ADMIN[0]).id
    assert stored.boot_id == admin.app.state.clock.boot_id()
    assert stored.facts["deployment_id"] == data(admin, found, location=False)["deployment_id"]


@pytest.mark.parametrize("answers, mark", [
    (([CAR], [CAR]), "clear"),
    (([CAR, WALKER], [CAR]), "person"),
    ((None, None), "unchecked"),
])
def test_the_mark_is_the_takes_people(admin, monkeypatch, answers, mark):
    tracking(admin, monkeypatch, *answers)
    assert kept(admin)["mark"] == mark


def keep_refused(client, found, expected, name="picam_h265"):
    r = client.post(keep_url(found, name), headers=JSON_HEADERS)
    assert (r.status_code, r.json()["error"]["code"]) == expected, r.text
    return r


def test_an_unknown_ticket_and_a_ticket_under_another_cameras_name_are_expired(admin, token):
    assert add(admin).status_code == 200
    found = taken(admin)
    r = keep_refused(admin, found, (404, "reference_expired"), name=NEUTRAL)
    assert r.json()["error"]["message"] == EXPIRED
    r = admin.post("/api/v1/cameras/picam_h265/reference/made-up-ticket/keep", headers=JSON_HEADERS)
    assert error(r) == (404, "reference_expired", EXPIRED)
    assert admin.app.state.pictures.total() == (0, 0) and picture_audit(admin) == []


def test_a_take_with_no_place_in_use_is_refused(admin, monkeypatch):
    monkeypatch.setattr(Places, "in_use", lambda self: None)
    found = taken(admin)
    assert found["survey_id"] is None
    keep_refused(admin, found, (409, "no_place"))


def test_a_take_whose_place_was_replaced_by_a_deploy_is_refused(admin):
    found = taken(admin)
    deploy_new_place(admin, 45.52252, -122.6912)
    keep_refused(admin, found, (409, "no_place"))
    assert admin.app.state.pictures.total() == (0, 0)


def test_a_second_keep_is_refused(admin):
    found = taken(admin)
    assert admin.post(keep_url(found), headers=JSON_HEADERS).status_code == 201
    keep_refused(admin, found, (409, "already_kept"))
    assert admin.app.state.pictures.total()[0] == 1


def test_no_room_is_refused_and_only_room_decides(admin, monkeypatch):
    room = {"free": False}
    monkeypatch.setattr(Pictures, "has_room", lambda self: room["free"])
    found = taken(admin)
    keep_refused(admin, found, (409, "no_space"))
    assert admin.app.state.pictures.total() == (0, 0)
    room["free"] = True
    monkeypatch.setattr("tm_control.modules.pictures.store.PICTURES_MAX", 0)  # the count limits nothing here
    assert admin.post(keep_url(found), headers=JSON_HEADERS).status_code == 201


def test_a_refusal_says_nothing_of_the_picture(admin, monkeypatch):
    messages = []
    room = {"free": False}
    monkeypatch.setattr(Pictures, "has_room", lambda self: room["free"])
    found = taken(admin)
    messages.append(keep_refused(admin, found, (404, "reference_expired"), name="oak_ave_tele").json()["error"])
    messages.append(keep_refused(admin, found, (409, "no_space")).json()["error"])
    room["free"] = True
    assert admin.post(keep_url(found), headers=JSON_HEADERS).status_code == 201
    messages.append(keep_refused(admin, found, (409, "already_kept")).json()["error"])
    place = in_use(admin)["id"]
    for message in messages:
        text = json.dumps(message)
        assert place not in text and "picam_h265" not in text and "oak_ave_tele" not in text


def test_the_ticket_still_saves_the_zip_after_a_keep(admin):
    found = taken(admin)
    assert admin.post(keep_url(found), headers=JSON_HEADERS).status_code == 201
    r = manual_package(admin, found, location=False)
    assert r.status_code == 200 and f"{found['stem']}.json" in files(r)
    assert admin.get(f"{base(found)}/clean.jpg").status_code == 200


# The list and the frames


def test_the_list_is_newest_first_and_can_be_one_places(admin):
    first = in_use(admin)["id"]
    older = kept(admin)
    newer = kept(admin)
    second = deploy_new_place(admin, 45.52252, -122.6912)
    latest = kept(admin)
    everything = listed(admin)
    assert [one["id"] for one in everything["pictures"]] == [latest["id"], newer["id"], older["id"]]
    assert set(everything["pictures"][0]) == {
        "id", "survey_id", "camera", "taken_at", "reason", "mark", "after_restart", "bytes"}
    here = listed(admin, first)
    assert [one["id"] for one in here["pictures"]] == [newer["id"], older["id"]]
    assert [one["id"] for one in listed(admin, second)["pictures"]] == [latest["id"]]
    assert listed(admin, "00000000-si")["pictures"] == []
    for body in (everything, here):  # the totals are the whole device's
        assert body["stored"] == 3 and body["stored_bytes"] == 3 * (len(CLEAN) + len(ZONED))


def test_an_empty_device_lists_nothing(admin):
    assert listed(admin) == {"pictures": [], "stored": 0, "stored_bytes": 0}


def test_a_frame_is_the_stored_bytes_with_no_store(admin):
    picture = kept(admin)
    for name, content in (("clean.jpg", CLEAN), ("zones.jpg", ZONED)):
        r = admin.get(f"{PREFIX}/{picture['id']}/{name}")
        assert r.status_code == 200 and r.content == content
        assert r.headers["content-type"] == "image/jpeg" and r.headers["cache-control"] == "no-store"
    assert admin.get(f"{PREFIX}/{picture['id']}/other.jpg").status_code == 404
    assert admin.get(f"{PREFIX}/{picture['id']}/clean.JPG").status_code == 404


@pytest.mark.parametrize("bad", BAD_IDS)
def test_a_frame_under_a_made_up_id_is_a_404(admin, bad):
    kept(admin)
    assert admin.get(f"{PREFIX}/{quote(bad, safe='')}/clean.jpg").status_code == 404
    assert admin.get(f"{PREFIX}/{MADE_UP}/clean.jpg").status_code == 404


# What goes over the wire, as written: the client neither re-encodes nor normalizes these (checked below). The second
# item is the id the route sees after the server decodes the path, or None when the path no longer has the route's two
# segments, so the router answers 404 itself.
RAW_PATHS = [
    ("%2e%2e", ("..",)),
    ("%2E%2E", ("..",)),
    ("%252e%252e", ("..", "%2e%2e")),
    ("..%5Cx", ("..\\x",)),
    ("%00", ("\x00",)),
    ("..%2Fx", None),
    ("%2e%2e%2f%2e%2e", None),
    ("%2e%2e%2fpictures", None),
    ("", None),
]


@pytest.mark.parametrize("segment, seen", RAW_PATHS)
def test_a_raw_made_up_id_is_a_404_and_touches_no_disk(admin, monkeypatch, segment, seen):
    kept(admin)
    path = f"{PREFIX}/{segment}/clean.jpg"
    assert admin.build_request("GET", path).url.raw_path.decode() == path  # as written, on the wire
    asked = []
    real = Pictures.frame

    def frame(self, picture_id, name):
        asked.append(picture_id)
        return real(self, picture_id, name)

    def no_disk(*args, **kwargs):
        raise AssertionError("no file is touched for an id that isn't one")

    monkeypatch.setattr(Pictures, "frame", frame)
    for name in ("_read", "_is_file", "_remove"):
        monkeypatch.setattr(store_module, name, no_disk)
    monkeypatch.setattr(Pictures, "_dir", no_disk)
    r = admin.get(path)
    assert r.status_code == 404, r.text
    assert asked == [] if seen is None else len(asked) == 1 and asked[0] in seen  # the ids it may decode to
    for other in ("delete", "package"):  # the same segment on the other two routes
        wire = f"{PREFIX}/{segment}" + ("/package" if other == "package" else "")
        sent = admin.request("POST" if other == "package" else "DELETE", wire, headers=JSON_HEADERS,
                             json={"location": False, "looked": True} if other == "package" else None)
        assert sent.status_code in (204, 404, 405), (other, sent.text)  # no such route for some of them


def test_a_lost_file_is_a_404(admin):
    picture = kept(admin)
    (admin.app.state.pictures.root / picture["id"] / "zones.jpg").unlink()
    for name in ("clean.jpg", "zones.jpg"):
        r = admin.get(f"{PREFIX}/{picture['id']}/{name}")
        assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")
    assert download(admin, picture["id"]).status_code == 404


# Delete


def test_delete_is_a_204_twice_and_the_files_are_gone(admin):
    picture = kept(admin)
    directory = admin.app.state.pictures.root / picture["id"]
    assert directory.is_dir()
    for _ in range(2):
        assert admin.delete(f"{PREFIX}/{picture['id']}", headers=JSON_HEADERS).status_code == 204
    assert not directory.exists() and listed(admin)["pictures"] == []
    assert admin.delete(f"{PREFIX}/{MADE_UP}", headers=JSON_HEADERS).status_code == 204
    for bad in BAD_IDS[2:-1]:  # a made-up id is a 204 like any other with no picture; ".." and "" are no segment
        assert admin.delete(f"{PREFIX}/{quote(bad, safe='')}", headers=JSON_HEADERS).status_code == 204, bad
    assert admin.app.state.pictures.total() == (0, 0)


# The package


def test_a_pictures_zip_is_the_manual_takes_zip(admin):
    found = taken(admin)
    picture = admin.post(keep_url(found), headers=JSON_HEADERS).json()
    manual = manual_package(admin, found, location=False)
    r = download(admin, picture["id"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == f'attachment; filename="{found["stem"]}.zip"'
    assert r.headers["cache-control"] == "no-store"
    archive, expected = files(r), files(manual)
    assert list(archive) == list(expected) == [
        f"{found['stem']}_clean.jpg", f"{found['stem']}_zones.jpg", f"{found['stem']}.json",
        f"{found['stem']}_zones.svg"]
    pictures = admin.app.state.pictures
    assert archive[f"{found['stem']}_clean.jpg"] == pictures.frame(picture["id"], "clean.jpg") == CLEAN
    assert archive[f"{found['stem']}_zones.jpg"] == pictures.frame(picture["id"], "zones.jpg") == ZONED
    assert archive[f"{found['stem']}.json"] == expected[f"{found['stem']}.json"]
    assert archive[f"{found['stem']}_zones.svg"] == expected[f"{found['stem']}_zones.svg"]


def test_no_route_gives_two_pictures(admin):
    document = admin.app.openapi()
    routes = sorted((path, sorted(methods)) for path, methods in document["paths"].items()
                    if path.startswith(PREFIX))
    assert routes == sorted([
        (PREFIX, ["get"]),
        (f"{PREFIX}/{{picture_id}}/{{picture}}", ["get"]),
        (f"{PREFIX}/{{picture_id}}", ["delete"]),
        (f"{PREFIX}/{{picture_id}}/package", ["post"]),
    ])
    schema = document["components"]["schemas"]["PackageIn"]
    assert sorted(schema["properties"]) == ["location", "looked"]
    assert all(property_.get("type") != "array" for property_ in schema["properties"].values())


def test_the_location_is_the_places_now(admin):
    place = deploy_new_place(admin, 45.52252, -122.6912)
    picture = kept(admin)
    stem = admin.app.state.pictures.get(picture["id"])
    assert stem.survey_id == place
    name = f"tm-reference_{place}_picam_h265_"

    def written(location):
        r = download(admin, picture["id"], location=location)
        assert r.status_code == 200, r.text
        archive = files(r)
        return json.loads(next(content for key, content in archive.items() if key.endswith(".json")
                               and key.startswith(name)))

    assert written(True)["location"] == {"lat": 45.52252, "lon": -122.6912}
    r = admin.post(f"/api/v1/surveys/{place}/location", json={"lat": 45.0, "lon": -122.0}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert written(True)["location"] == {"lat": 45.0, "lon": -122.0}
    assert written(False)["location"] is None


def test_a_place_with_no_point_gives_no_location(admin):
    deploy_new_place(admin, None, None)
    picture = kept(admin)
    r = download(admin, picture["id"], location=True)
    assert r.status_code == 200
    archive = files(r)
    assert json.loads(next(content for key, content in archive.items() if key.endswith(".json")))["location"] is None


@pytest.mark.parametrize("case, status", [
    ("unknown", 404), ("made_up", 404), ("not_looked", 422), ("no_look", 422), ("no_location", 422),
])
def test_package_refusals(admin, case, status):
    picture = kept(admin)
    picture_id = {"unknown": MADE_UP, "made_up": quote("../x", safe="")}.get(case, picture["id"])
    body = {"location": False, "looked": True}
    if case == "not_looked":
        body["looked"] = False
    elif case == "no_look":
        del body["looked"]
    elif case == "no_location":
        del body["location"]
    r = admin.post(f"{PREFIX}/{picture_id}/package", json=body, headers=JSON_HEADERS)
    assert r.status_code == status, r.text
    assert picture_audit(admin) == [("picture.keep", f"{picture['survey_id']} picam_h265")]


# Audit and logs


def test_audit_rows_hold_keys_and_reasons(admin):
    place = in_use(admin)["id"]
    picture = kept(admin)
    listed(admin)
    assert admin.get(f"{PREFIX}/{picture['id']}/clean.jpg").status_code == 200
    assert download(admin, picture["id"], location=True).status_code == 200
    assert download(admin, picture["id"], location=False).status_code == 200
    assert admin.delete(f"{PREFIX}/{picture['id']}", headers=JSON_HEADERS).status_code == 204
    assert admin.delete(f"{PREFIX}/{picture['id']}", headers=JSON_HEADERS).status_code == 204  # nothing to delete
    assert picture_audit(admin) == [
        ("picture.keep", f"{place} picam_h265"),
        ("picture.download_with_location", f"{place} picam_h265"),
        ("picture.download", f"{place} picam_h265"),
        ("picture.delete", f"{place} picam_h265 manual"),
    ]
    assert not any(picture["id"] in detail for _, detail in picture_audit(admin))


def test_a_download_with_no_point_is_audited_as_without(admin):
    deploy_new_place(admin, None, None)
    picture = kept(admin)
    assert download(admin, picture["id"], location=True).status_code == 200
    assert [action for action, _ in picture_audit(admin)] == ["picture.keep", "picture.download"]


def test_no_picture_fact_reaches_a_log_line(admin, caplog):
    caplog.set_level(logging.DEBUG)
    place = deploy_new_place(admin, 45.52252, -122.6912)
    caplog.clear()
    picture = kept(admin)
    listed(admin)
    listed(admin, place)
    assert admin.get(f"{PREFIX}/{picture['id']}/clean.jpg").status_code == 200
    assert admin.get(f"{PREFIX}/{MADE_UP}/clean.jpg").status_code == 404
    assert download(admin, picture["id"], location=True).status_code == 200
    assert admin.delete(f"{PREFIX}/{picture['id']}", headers=JSON_HEADERS).status_code == 204
    records = [record for record in caplog.records if record.name != "httpx"]  # httpx: the test's own client
    for record in records:
        message = record.getMessage()
        for fact in (picture["id"], place, "picam_h265", "45.52252", "122.6912"):
            assert fact not in message, record.name
        if not record.name.startswith("uvicorn"):  # only the access log holds a path; a route's template has no id
            assert ("/pictures" not in message and "/keep" not in message) or "{" in message, message


# A failing disk: the store raises OSError, whose text holds a path that ends in the picture's id

FAULTY = f"/var/lib/tm-control/pictures/{MADE_UP}/clean.jpg"


def broken_disk(error_number):
    def raise_it(*args, **kwargs):
        raise OSError(error_number, "placeholder-disk-text", FAULTY)

    return raise_it


def nothing_of_the_path(response, caplog):
    assert FAULTY not in response.text and MADE_UP not in response.text and "pictures/" not in response.text
    for record in caplog.records:
        if record.name == "httpx":  # the test's own client
            continue
        text = record.getMessage() + (record.exc_text or "") + "".join(map(str, record.args or ()))
        assert record.exc_info is None, record.name
        assert FAULTY not in text and MADE_UP not in text and "placeholder-disk-text" not in text, record.name


STORAGE = (
    "The device couldn't read or write its stored pictures. Try again, and check the device's storage if it keeps "
    "happening."
)
NO_SPACE = "There isn't enough free space on the device to keep these pictures."


@pytest.mark.parametrize("number, expected", [
    (errno.ENOSPC, (409, "no_space", NO_SPACE)),
    (errno.EIO, (500, "storage", STORAGE)),
])
def test_a_disk_error_on_keep_is_a_fixed_answer_and_the_take_can_be_kept_again(
    admin, monkeypatch, caplog, number, expected
):
    caplog.set_level(logging.DEBUG)
    found = taken(admin)
    real = Pictures.add
    monkeypatch.setattr(Pictures, "add", broken_disk(number))
    r = admin.post(keep_url(found), headers=JSON_HEADERS)
    assert error(r) == expected
    nothing_of_the_path(r, caplog)
    assert picture_audit(admin) == []
    monkeypatch.setattr(Pictures, "add", real)  # nothing was marked kept
    assert admin.post(keep_url(found), headers=JSON_HEADERS).status_code == 201


def test_an_unreadable_boot_id_is_not_answered_as_the_pictures_storage(admin, monkeypatch):
    from tm_control.modules.pictures.clock import BOOT_ID, Clock

    def unreadable(self):
        raise OSError(errno.EIO, "placeholder-disk-text", str(BOOT_ID))

    found = taken(admin)
    real = Clock.boot_id
    monkeypatch.setattr(Clock, "boot_id", unreadable)
    with pytest.raises(OSError):  # an unexpected error, not the "storage" answer the store's try would give it
        admin.post(keep_url(found), headers=JSON_HEADERS)
    assert admin.app.state.pictures.total() == (0, 0) and picture_audit(admin) == []
    monkeypatch.setattr(Clock, "boot_id", real)  # nothing was marked kept
    assert admin.post(keep_url(found), headers=JSON_HEADERS).status_code == 201


@pytest.mark.parametrize("number", [errno.ENOSPC, errno.EIO])
def test_a_disk_error_on_delete_is_a_fixed_answer(admin, monkeypatch, caplog, number):
    caplog.set_level(logging.DEBUG)
    picture = kept(admin)
    monkeypatch.setattr(Pictures, "delete", broken_disk(number))
    r = admin.delete(f"{PREFIX}/{picture['id']}", headers=JSON_HEADERS)
    assert error(r) == (500, "storage", STORAGE)
    nothing_of_the_path(r, caplog)
    assert [action for action, _ in picture_audit(admin)] == ["picture.keep"]


@pytest.mark.parametrize("number", [errno.ENOSPC, errno.EIO])
def test_a_disk_error_on_a_frame_or_a_download_is_a_fixed_answer(admin, monkeypatch, caplog, number):
    caplog.set_level(logging.DEBUG)
    picture = kept(admin)
    monkeypatch.setattr(Pictures, "frame", broken_disk(number))
    monkeypatch.setattr(Pictures, "shot", broken_disk(number))
    for r in (admin.get(f"{PREFIX}/{picture['id']}/clean.jpg"), download(admin, picture["id"])):
        assert error(r) == (500, "storage", STORAGE)
        nothing_of_the_path(r, caplog)
    assert [action for action, _ in picture_audit(admin)] == ["picture.keep"]


@pytest.mark.parametrize("number", [errno.ENOSPC, errno.EIO])
def test_a_disk_error_deleting_a_place_leaves_the_place(admin, monkeypatch, caplog, number):
    caplog.set_level(logging.DEBUG)
    old = in_use(admin)["id"]
    kept(admin)
    deploy_new_place(admin, 45.52252, -122.6912)
    monkeypatch.setattr(Pictures, "delete_place", broken_disk(number))
    r = admin.delete(f"/api/v1/surveys/{old}", headers=JSON_HEADERS)
    assert error(r) == (500, "storage", STORAGE)
    nothing_of_the_path(r, caplog)
    assert Places(admin.app.state.state).get(old) is not None
