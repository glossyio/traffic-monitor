# Reference Picture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the Cameras page an admin takes one zip for one camera: Frigate's current frame, the same view with the zone outlines, a data file with everything Frigate holds for each zone, and an SVG with the zones named, for a tool that places recorded paths on a street.

**Architecture:** The control app asks Frigate's API for two frames (`latest.jpg`, plain and with `zones=1`) and reads the zones from the same `/api/config` answer. It holds both pictures in memory under a ticket for ten minutes, shows them to the admin, and builds the zip from the same bytes. The data file and the SVG are written when the zip is asked for. Nothing is written to the device's disk, no flow or schema changes, and no package is added.

**Tech Stack:** Python 3.13 standard library (`zipfile`, `base64`, `xml.sax.saxutils`), FastAPI and pydantic (tm-control backend), Vue 3 + Vuetify 3 + TypeScript (tm-control UI), pytest, Vitest, MkDocs.

**Spec:** "What it must do" below.

**Repo:** `glossyio/traffic-monitor`, branch `feature/reference-picture/338` off `dev` (`80c1d6d` when this was written), in its own worktree. All paths below are relative to the repo root.

## What it must do

1. An admin-only action on a camera's row of the Cameras page gives one zip with four files that share one stem, `tm-reference_<survey id>_<camera key>_<UTC time>`:

   | File | Comes from | Holds |
   |---|---|---|
   | `<stem>_clean.jpg` | Frigate, `GET /api/<camera>/latest.jpg` | The detect stream's current frame, nothing drawn on it |
   | `<stem>_zones.jpg` | Frigate, the same request with `zones=1` | A frame with the outline of each zone that is on, in the zone's colour |
   | `<stem>.json` | Frigate's `/api/config` and the control app's records | The data file (format below) |
   | `<stem>_zones.svg` | The control app, from the clean frame and the data file | The clean frame with the zones outlined and named, and a legend below it |

2. The pictures come through Frigate's API, asked for at JPEG quality 95 and at the frame's own size, so paths and boxes saved as fractions of the detect frame line up with them.
3. A live frame only. The action refuses, with one message, when the camera is off in Frigate, when Frigate marks the frame as an older one, and when Frigate has no frame at all.
4. The pictures shown are the pictures saved. Both are fetched once, kept in memory for 600 seconds, shown on the page, and zipped from the same bytes. Nothing is written to disk.
5. A people check: Frigate is asked, before and after the pictures, whether it is tracking a person on the camera. A person gives an amber warning above the preview and blocks nothing. With Frigate's detection off the page says the check couldn't run.
6. A note tells the admin what the picture gives away, before any picture is taken.
7. The data file holds the survey id, the camera's key, the camera's open deployment id, each picture's time in UTC, the Traffic Monitor and Frigate versions, the detect width and height, and every zone: its key, colour as `#rrggbb`, whether it is on, its corners as fractions in stored order with a letter each, its side lengths as entered and listed by side, and its inertia, loitering time, speed threshold, objects, and filters.
8. The place's exact point is in the data file unless the admin clears a box, "Include this place's exact location", which is ticked when the page opens and greyed when there is no point to include.
9. The data file and the SVG never hold Frigate's name for the camera, a zone's `friendly_name`, or a place's description.
10. The picture is on the exact-location side: never in tmdb, the database download, or an upload. The audit log gets the camera's key and whether the location was included, never the point.
11. Fake mode serves a stand-in picture, so the whole page works on a laptop.

Not in this change: where the camera points (its bearing or heading, pitch, height, distance, and field of view). The device records only a compass bearing today; the data file gains all of it together, as one `pose` object, once the control app records the camera's mounting. Adding keys doesn't change `format_version`. a labelled JPEG, which would need an image library; any change to tmdb or the flows.

## Global Constraints

- No new package in any requirements or `package.json` file, no root job, no change to `tm-control.service` or its sandbox, no nginx change.
- Pictures exist only in the app's memory and in answers to an admin's requests. No picture, ticket, coordinate, or Frigate camera name goes to a log line, an audit row, or an error message.
- Every new route takes `require_admin`. Frigate is reached only through `tm_control/adapters/frigate.py`, on 127.0.0.1.
- This change never turns on Frigate's detection, snapshots, or recording, and never writes Frigate's config.
- Zone keys and camera keys are typed by operators. In the SVG they are escaped; in file names every character outside `A-Z a-z 0-9 _ -` becomes `_`.
- UI: conventional Vuetify components, no custom CSS beyond spacing classes, wording in `reference.ts`, rules in the backend. The UI task's implementer loads `frontend-design:frontend-design`, `superpowers:test-driven-development`, and `superpowers:verification-before-completion`; these constraints win over the design skill's push for distinctiveness.
- Tests never use a real camera picture. Off the device they use the made-up JPEG bytes from `tests/jpegs.py` and the two drawn fixtures. On a bench unit, automated checks read status, headers, type, and size only; nobody but the maintainer opens a picture.
- Docs ride with the code and follow "Writing docs" in `docs/development/contributing.md`. `mkdocs build --strict` must pass.
- Commit messages end with the trailer block in the repo's `CLAUDE.md`. No device names or addresses in commits or PR text.
- Nothing is pushed. The maintainer reads the commits and the PR text first.
- Open work that edits the same files: PR 326 (`CLAUDE.md`, `docs/development/tm-control.md`, `tm-control/ui/README.md`, `fake.py`, `test_openapi_document.py`, and the generated `openapi.json` and `schema.d.ts`) and the event-fields branch (`CLAUDE.md`, `docs/development/tm-control.md`; it also adds `docs/data-and-payloads/object-paths.md`). If one merges into `dev` first, merge `dev` in, keep both sides, and regenerate the two API files instead of resolving them by hand. Once `object-paths.md` is on `dev`, link it and the new docs section to each other.

## Review Focus

Inputs the requirements imply and a person will meet; each has a test in the task named.

1. The camera stopped sending. Frigate then answers `latest.jpg` with HTTP 200 and its own "no frames" picture, with no header that says so. The action must refuse it, not zip it. Tasks 1 and 5.
2. A zone key or camera key with markup, quotes, a slash, or letters outside ASCII: the SVG stays well-formed with the key as text, and the file names stay plain. Tasks 3 and 4.
3. Frigate's zones in an odd shape: no `coordinates`, a list instead of a string, pixel values, three corners, thirty corners, no `color`, a zone that is off, a value that isn't a mapping. Each zone is still listed, and none crashes the take. Task 2.
4. The pictures are gone while the dialog is open (ten minutes passed, the app restarted, or the admin took another): the page says so and offers to take them again; it never shows a broken picture with a working Save button. Tasks 5 and 6.
5. No place in use, a place with no coordinates, or Node-RED not answering: the take still works, with an empty survey id, location, or deployment id. Task 5.

## Files

| File | Change |
|---|---|
| `tm-control/backend/tm_control/adapters/httpjson.py` | `get_with_headers` |
| `tm-control/backend/tm_control/adapters/frigate.py` | `Frame`, `latest_frame`, `people_tracked` |
| `tm-control/backend/tm_control/modules/cameras/zones.py` | New: `ZoneFacts` and `zone_facts`, what Frigate holds for each zone |
| `tm-control/backend/tm_control/modules/cameras/reference.py` | New: `Reference`, `References` (the tickets), `jpeg_size`, `stem`, `data_file`, `package` |
| `tm-control/backend/tm_control/modules/cameras/svg.py` | New: `reference_svg` |
| `tm-control/backend/tm_control/modules/cameras/router.py` | Four routes under `/cameras/{name}/reference` |
| `tm-control/backend/tm_control/app.py` | `app.state.references` |
| `tm-control/backend/tm_control/fake.py` | The fake Frigate's frames, stats, people, and version |
| `tm-control/backend/tests/fixtures/reference_clean.jpg`, `reference_zones.jpg` | New: two drawn stand-in pictures, 1536 by 864 |
| `tm-control/ui/src/api/openapi.json`, `schema.d.ts` | Regenerated, never edited by hand |
| `tm-control/ui/src/modules/cameras/reference.ts`, `ReferencePicture.vue`, `CamerasPage.vue` | The dialog and its button |
| `script/devpi/tests/test_web.py` | The viewer refusals and one take on a `pii_free` unit |
| Tests | `tm-control/backend/tests/jpegs.py`, `test_frigate_frames.py`, `test_cameras_zones.py`, `test_cameras_reference.py`, `test_api_cameras_reference.py` (all new), `conftest.py`, `test_openapi_document.py`; `tm-control/ui/tests/camera-reference.spec.ts`, `reference-picture.spec.ts` (new), `fake-api.ts` |
| Docs | `docs/use/cameras.md`, `docs/use/wifi-hotspot.md`, `docs/development/tm-control.md`, `tm-control/ui/README.md`, `CLAUDE.md`, `docs/assets/images/cameras-reference.png` (new) |

## Commands

```bash
. .venv/bin/activate                                   # the dev venv from CLAUDE.md, in the same shell call
python -m pytest tm-control/backend/tests -q           # backend
python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests -q   # everything off-device
PYTHONPATH=tm-control/backend python -m tm_control dump-openapi > tm-control/ui/src/api/openapi.json
podman run --rm -v "$PWD/tm-control/ui:/ui:Z" -w /ui docker.io/library/node:22.23.4-alpine sh -c 'npm ci && npm run api:generate && npm run build && npm test'
~/.venvs/tm-docs/bin/mkdocs build --strict
```

## Names used across tasks

| Name | Where | What |
|---|---|---|
| `frigate.Frame` | `adapters/frigate.py` | `NamedTuple(data: bytes, offline: bool)` |
| `ZoneFacts`, `Corner`, `Side` | `modules/cameras/zones.py` | pydantic models, below |
| `Reference` | `modules/cameras/reference.py` | frozen dataclass, below |
| `app.state.references` | `app.py` | the one `References` store |
| `NO_PLACE = "no-place"` | `reference.py` | the stem's survey part when no place is in use |
| `FALLBACK_COLOR = "#888888"` | `zones.py` | drawn for a zone Frigate gave no colour |

```python
class Corner(BaseModel):
    letter: str   # A, B, C ... in stored order
    x: float      # fractions of the detect frame, from its top-left corner
    y: float

class Side(BaseModel):
    start: str    # a corner's letter
    end: str      # the next corner's letter; the last side ends at A
    length: float

class ZoneFacts(BaseModel):
    key: str
    color: str | None            # "#rrggbb"; None when Frigate gave none
    enabled: bool
    drawn: bool                  # on, with at least three corners: outlined in the zones picture and the SVG
    corners: list[Corner]
    distances: list[float]       # as entered in Frigate, in Frigate's order; [] when none
    sides: list[Side]            # the same lengths by side; [] unless there is one length per corner
    inertia: int | None
    loitering_time: int | None
    speed_threshold: float | None
    objects: list[str]
    filters: dict

@dataclass(frozen=True)
class Reference:
    ticket: str
    user_id: int
    camera: str                          # the sensors.cameras key, never Frigate's name
    survey_id: str | None
    point: tuple[float, float] | None    # the place's exact lat, lon
    deployment_id: str | None
    clean: bytes
    zones_picture: bytes
    clean_at: float                      # Unix seconds, when each answer arrived
    zones_at: float
    width: int                           # the detect frame's
    height: int
    unit: Literal["m", "ft"]             # Frigate's unit system: metric or imperial
    zones: list[ZoneFacts]
    people: Literal["none", "seen", "not_checked"]
    tm_version: str
    frigate_version: str | None
    expires: float                       # on time.monotonic()'s clock
```

---

### Task 1: Frigate's frames and its people answer

**Files:**
- Modify: `tm-control/backend/tm_control/adapters/httpjson.py`, `adapters/frigate.py`
- Modify: `tm-control/backend/tests/conftest.py` (`device_client` silences the new function too)
- Create: `tm-control/backend/tests/jpegs.py`
- Test: `tm-control/backend/tests/test_frigate_frames.py`

**Interfaces:**
- Produces:
  - `httpjson.get_with_headers(url, headers=None, timeout=None) -> tuple[int | None, bytes | None, dict[str, str]]`: as `get`, plus the answer's headers with lower-case names; `{}` when nothing answered.
  - `frigate.Frame`, `frigate.latest_frame(camera: str, zones: bool = False) -> Frame | None`, `frigate.people_tracked(camera: str) -> int | None`.
  - `tests/jpegs.py`: `jpeg(width: int, height: int) -> bytes`, made-up bytes that start like a JPEG and carry a size.

What Frigate 0.18.2 does, read from its source (`frigate/api/media.py`, `latest_frame`):

- `GET /api/<camera>/latest.jpg` takes `quality` (default 70), `height`, `zones`, and others, as integers. With no `height` the answer is the detect frame at its own size.
- A frame older than the camera's `ffmpeg.retry_interval` (10 seconds) is stale. Frigate then answers 200 with its most recent preview frame and the header `X-Frigate-Offline: true`, or, with no preview, 200 with its own error picture and **no such header**.
- An unknown camera is a 404 with a JSON body.
- `GET /api/events` takes `in_progress=1`, `cameras`, `labels` (comma-separated), and `limit`, and answers a JSON list.

- [ ] **Step 1: Write `tests/jpegs.py`**

```python
"""Made-up JPEG bytes for tests: the start-of-image marker, a JFIF header, a frame header that carries a size, and the
end marker. No picture is in them."""


def jpeg(width: int, height: int) -> bytes:
    jfif = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    frame = b"\xff\xc0\x00\x0b\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x01\x01\x11\x00"
    return b"\xff\xd8" + jfif + frame + b"\xff\xd9"
```

- [ ] **Step 2: Write the failing tests** in `test_frigate_frames.py`. Its `answering` fixture patches `httpjson.get_with_headers` with a function that records each call as `(url, headers, timeout)`, answers what the test gave it, and returns the list of calls.

```python
JPEG = jpeg(1536, 864)
IMAGE = {"content-type": "image/jpeg", "cache-control": "no-store"}


def test_latest_frame_asks_for_the_frame_at_quality_95_past_the_cache(answering):
    calls = answering((200, JPEG, IMAGE))
    assert frigate.latest_frame("oak ave/tele") == frigate.Frame(JPEG, False)
    url, headers, timeout = calls[0]
    assert url == "http://127.0.0.1:5000/api/oak%20ave%2Ftele/latest.jpg?quality=95"
    assert headers == {"X-Cache-Bypass": "1"} and timeout == frigate.FRAME_TIMEOUT == 10


def test_latest_frame_with_zones_adds_zones_1(answering):
    calls = answering((200, JPEG, IMAGE))
    frigate.latest_frame("picam_h265", zones=True)
    assert calls[0][0].endswith("/picam_h265/latest.jpg?quality=95&zones=1")


def test_an_older_frame_is_marked_offline(answering):
    answering((200, JPEG, IMAGE | {"x-frigate-offline": "true"}))
    assert frigate.latest_frame("picam_h265") == frigate.Frame(JPEG, True)


@pytest.mark.parametrize("answer", [
    (None, None, {}),                                        # Frigate didn't answer
    (404, b'{"success": false}', {"content-type": "application/json"}),
    (200, b'{"success": false}', {"content-type": "application/json"}),
    (200, b"GIF89a", IMAGE),                                 # says JPEG, isn't one
    (200, None, IMAGE),                                      # longer than the adapter reads
])
def test_anything_but_a_jpeg_is_no_frame(answering, answer):
    answering(answer)
    assert frigate.latest_frame("picam_h265") is None


def test_people_tracked_counts_frigates_list(answering):
    calls = answering((200, b'[{"id": "a"}, {"id": "b"}]', {}))
    assert frigate.people_tracked("oak ave") == 2
    assert calls[0][0] == "http://127.0.0.1:5000/api/events?in_progress=1&cameras=oak+ave&labels=person&limit=5"
    assert calls[0][1] == {"X-Cache-Bypass": "1"}


@pytest.mark.parametrize("answer", [(None, None, {}), (500, b"[]", {}), (200, b'{"a": 1}', {}), (200, b"no", {})])
def test_people_tracked_is_none_without_a_list(answering, answer):
    answering(answer)
    assert frigate.people_tracked("picam_h265") is None
```

Add one test of `get_with_headers` itself against a `http.server` on 127.0.0.1 in a thread: the status, the body, a header read under its lower-case name, `(None, None, {})` for a closed port, and `ValueError` for a host other than 127.0.0.1.

- [ ] **Step 3: Run them and see them fail**

Run: `python -m pytest tm-control/backend/tests/test_frigate_frames.py -q`
Expected: `AttributeError`, `httpjson` has no `get_with_headers`.

- [ ] **Step 4: Write the three functions.** `get_with_headers` shares `_send`'s error handling, and `get` and `post` keep their two-value answers. `latest_frame` returns `None` unless the status is 200, the content type starts with `image/jpeg`, and the body starts with `b"\xff\xd8\xff"`; `offline` is whether `x-frigate-offline` is `true`. Both Frigate calls send `FRESH`. In `conftest.py`, `device_client` patches `httpjson.get_with_headers` to answer `(None, None, {})`, beside its `get` and `post`.

- [ ] **Step 5: Run the backend tests and see them pass**

Run: `python -m pytest tm-control/backend/tests -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tm-control/backend
git commit   # subject: Read a camera's current frame and the people being tracked from Frigate's API
```

---

### Task 2: What Frigate holds for each zone

**Files:**
- Create: `tm-control/backend/tm_control/modules/cameras/zones.py`
- Test: `tm-control/backend/tests/test_cameras_zones.py`

**Interfaces:**
- Produces: `Corner`, `Side`, `ZoneFacts` (above), `FALLBACK_COLOR`, and
  - `corner_letter(index: int) -> str`: `A` to `Z`, then `AA`, `AB`, and so on, as spreadsheet columns go.
  - `detect_size(camera: Mapping) -> tuple[int, int] | None`: `detect.width` and `detect.height` when both are positive integers.
  - `distance_unit(config: Mapping) -> Literal["m", "ft"]`: `"ft"` when `ui.unit_system` is `"imperial"`, else `"m"`.
  - `zone_facts(camera: Mapping) -> list[ZoneFacts]`: one per zone, in Frigate's order.

The rules, which the tests pin:

- **Whitelist.** A zone's facts are built from `coordinates`, `color`, `enabled`, `distances`, `inertia`, `loitering_time`, `speed_threshold`, `objects`, and `filters` only. `friendly_name` and any key Frigate adds later are never copied.
- **Colour.** `/api/config` gives `color` as three integers in blue, green, red order, which is how Frigate's drawing code uses them. `[176, 53, 112]` is `#7035b0`. Anything else is `None`.
- **Corners.** `coordinates` is a string `"x,y,x,y,..."` or a list of `"x,y"` strings. Values are fractions of the detect frame. When any value is above 1 they are pixels, and each is divided by the detect width or height; with no detect size such a zone has no corners. An odd count, fewer than three points, or a value that isn't a finite number gives no corners.
- **Enabled** is `enabled is not False`, as `state.py` reads it. **Drawn** is enabled with at least three corners.
- **Distances** are Frigate's strings (`"12.0"`) as floats. **Sides** pair them with the corners in stored order (A to B, B to C, ..., the last back to A) only when there is exactly one length per corner.
- A zone whose value isn't a mapping is listed with its key, on, with no colour and no corners.

- [ ] **Step 1: Write the failing tests**

```python
RADAR = {
    "coordinates": "0.169,0.489,0.451,0.358,0.821,0.528,0.472,0.796", "color": [92, 160, 64],
    "distances": ["12.0", "7.3", "12.0", "7.3"], "inertia": 3, "loitering_time": 0, "speed_threshold": None,
    "objects": ["car"], "filters": {"car": {"min_area": 500}}, "friendly_name": "Oak Ave by the school",
}
CAMERA = {"detect": {"width": 1536, "height": 864}, "zones": {"zone_radar": RADAR}}


def test_a_zone_with_side_lengths():
    [zone] = zone_facts(CAMERA)
    assert (zone.key, zone.color, zone.enabled, zone.drawn) == ("zone_radar", "#40a05c", True, True)
    assert [(c.letter, c.x, c.y) for c in zone.corners] == [
        ("A", 0.169, 0.489), ("B", 0.451, 0.358), ("C", 0.821, 0.528), ("D", 0.472, 0.796)]
    assert zone.distances == [12.0, 7.3, 12.0, 7.3]
    assert [(s.start, s.end, s.length) for s in zone.sides] == [
        ("A", "B", 12.0), ("B", "C", 7.3), ("C", "D", 12.0), ("D", "A", 7.3)]
    assert (zone.inertia, zone.loitering_time, zone.speed_threshold) == (3, 0, None)
    assert zone.objects == ["car"] and zone.filters == {"car": {"min_area": 500}}


def test_frigates_name_for_a_zone_is_never_copied():
    assert "Oak Ave" not in zone_facts(CAMERA)[0].model_dump_json()


@pytest.mark.parametrize("coordinates, corners", [
    (["0.1,0.2", "0.3,0.4", "0.5,0.6"], [(0.1, 0.2), (0.3, 0.4), (0.5, 0.6)]),   # a list
    ("768,432,1536,432,1536,864", [(0.5, 0.5), (1.0, 0.5), (1.0, 1.0)]),         # pixels
    ("0.1,0.2,0.3,0.4", []),                                                     # two points
    ("0.1,0.2,0.3,0.4,0.5", []),                                                 # an odd count
    ("0.1,0.2,0.3,nan,0.5,0.6", []), ("a,b,c,d,e,f", []), (None, []), (7, []),
])
def test_corners(coordinates, corners):
    [zone] = zone_facts({"detect": {"width": 1536, "height": 864}, "zones": {"z": {"coordinates": coordinates}}})
    assert [(c.x, c.y) for c in zone.corners] == corners and zone.drawn is bool(corners)


def test_pixels_without_a_detect_size_give_no_corners():
    assert zone_facts({"zones": {"z": {"coordinates": "768,432,1536,432,1536,864"}}})[0].corners == []


def test_a_zone_that_is_off_is_listed_and_not_drawn():
    [zone] = zone_facts({"zones": {"z": RADAR | {"enabled": False}}})
    assert (zone.enabled, zone.drawn, len(zone.corners)) == (False, False, 4)


@pytest.mark.parametrize("value", [{}, None, "text", [1, 2]])
def test_a_zone_in_an_odd_shape_is_still_listed(value):
    [zone] = zone_facts({"zones": {"zone_lane_bus": value}})
    assert (zone.key, zone.color, zone.enabled, zone.corners, zone.sides, zone.filters) == (
        "zone_lane_bus", None, True, [], [], {})


@pytest.mark.parametrize("color", [None, [1, 2], [1, 2, 256], ["a", "b", "c"], "red", [1.5, 2, 3]])
def test_an_odd_colour_is_none(color):
    assert zone_facts({"zones": {"z": {"color": color}}})[0].color is None


def test_lengths_are_listed_by_side_only_with_one_per_corner():
    triangle = RADAR | {"coordinates": "0.1,0.1,0.9,0.1,0.5,0.9"}
    [zone] = zone_facts({"zones": {"z": triangle}})
    assert zone.distances == [12.0, 7.3, 12.0, 7.3] and zone.sides == []


def test_thirty_corners_are_lettered_past_z():
    points = ",".join(f"0.{i:02d},0.5" for i in range(30))
    letters = [c.letter for c in zone_facts({"zones": {"z": {"coordinates": points}}})[0].corners]
    assert letters[25:28] == ["Z", "AA", "AB"] and len(set(letters)) == 30


@pytest.mark.parametrize("camera", [{}, {"zones": None}, {"zones": ["a"]}, {"zones": "text"}])
def test_no_zones(camera):
    assert zone_facts(camera) == []


def test_detect_size_and_distance_unit():
    assert detect_size(CAMERA) == (1536, 864)
    assert detect_size({"detect": {"width": 0, "height": 864}}) is None and detect_size({}) is None
    assert distance_unit({"ui": {"unit_system": "imperial"}}) == "ft"
    assert distance_unit({"ui": {"unit_system": "metric"}}) == "m" and distance_unit({}) == "m"
```

- [ ] **Step 2: Run them and see them fail**

Run: `python -m pytest tm-control/backend/tests/test_cameras_zones.py -q`
Expected: an import error, `No module named 'tm_control.modules.cameras.zones'`.

- [ ] **Step 3: Write `zones.py`** from the rules above. It imports `probes.mapping` and nothing else from `tm_control`.

- [ ] **Step 4: Run them and see them pass**, then commit.

```bash
git add tm-control/backend
git commit   # subject: List what Frigate holds for each of a camera's zones
```

---

### Task 3: The pictures in memory, and the data file

**Files:**
- Create: `tm-control/backend/tm_control/modules/cameras/reference.py`
- Modify: `tm-control/backend/tm_control/app.py` (`app.state.references = References()`, beside `download_grants`)
- Test: `tm-control/backend/tests/test_cameras_reference.py`

**Interfaces:**
- Consumes: `ZoneFacts` (Task 2).
- Produces: `Reference` (above), `NO_PLACE`, and
  - `class References`: `TTL = 600.0`, `LIMIT = 2`;
    `keep(self, now: float, **fields) -> Reference` (`fields` are `Reference`'s other than `ticket` and `expires`);
    `get(self, ticket: str, user_id: int, now: float) -> Reference | None`;
    `drop(self, ticket: str, user_id: int) -> None`; `__len__`.
  - `jpeg_size(data: bytes) -> tuple[int, int] | None`: the width and height in a JPEG's frame header.
  - `stem(reference: Reference) -> str`
  - `data_file(reference: Reference, with_location: bool) -> dict`

The rules:

- **Tickets.** `secrets.token_urlsafe(16)`. A ticket answers only for the user who took it and before `expires`. Keeping one drops that user's earlier ones and every expired one, then the oldest while `LIMIT` are held. The store is locked like `DownloadGrants`.
- **`jpeg_size`** walks the segments after `FF D8`: a marker is `FF` then a byte; markers `D0` to `D9` and `01` have no length; the others carry a two-byte big-endian length that counts itself. The first of `C0` to `CF` other than `C4`, `C8`, and `CC` holds one byte of precision, then the height and the width as two bytes each. Truncated or malformed bytes give `None`.
- **`stem`** is `tm-reference_<survey id or no-place>_<camera>_<clean_at as YYYYMMDDTHHMMSSZ>`, with every character of the camera's key outside `A-Z a-z 0-9 _ -` replaced by `_`.
- **`data_file`** returns exactly this, with times as `2026-11-18T18:30:05Z`:

```json
{
  "format": "traffic-monitor-reference",
  "format_version": 1,
  "survey_id": "3f9a1c2e-si",
  "camera": "camera_1_3fa9c2",
  "deployment_id": "1795026000000-1a2b3c4d-d",
  "location": {"lat": 45.0, "lon": -122.0},
  "pictures": {
    "clean": {"file": "<stem>_clean.jpg", "taken_at": "2026-11-18T18:30:05Z"},
    "zones": {"file": "<stem>_zones.jpg", "taken_at": "2026-11-18T18:30:06Z"},
    "drawing": {"file": "<stem>_zones.svg"}
  },
  "traffic_monitor_version": "0.8.0",
  "frigate_version": "0.18.2-abc1234",
  "detect": {"width": 1536, "height": 864},
  "distance_unit": "m",
  "zones": [ ...each ZoneFacts as model_dump() gives it... ]
}
```

  `location` is `null` when `with_location` is false or the reference has no point; `survey_id`, `deployment_id`, and `frigate_version` are `null` when unknown.

- [ ] **Step 1: Write the failing tests.** A `reference(**changes)` helper in the test file builds a `Reference` from made-up values (`camera="camera_1_3fa9c2"`, `survey_id="3f9a1c2e-si"`, `point=(45.5231, -122.6765)`, `clean=jpeg(1536, 864)`, `clean_at=1795026605.0`, which is 2026-11-18 18:30:05 UTC, and one zone, `zone_facts(CAMERA)[0]` from Task 2's `CAMERA`). `FIELDS` is that reference's fields without `ticket` and `expires`.

```python
def test_a_ticket_answers_its_user_until_it_expires():
    store = References()
    kept = store.keep(100.0, **FIELDS)
    assert store.get(kept.ticket, kept.user_id, 100.0 + 599.9) is kept
    assert store.get(kept.ticket, kept.user_id, 100.0 + 600.0) is None
    assert store.get(kept.ticket, kept.user_id + 1, 100.0) is None
    assert store.get("no-such-ticket", kept.user_id, 100.0) is None


def test_a_new_take_drops_the_users_earlier_one_and_the_store_holds_two():
    store = References()
    first = store.keep(0.0, **FIELDS)
    second = store.keep(1.0, **FIELDS)
    assert store.get(first.ticket, first.user_id, 2.0) is None and len(store) == 1
    for user_id in (2, 3):
        store.keep(3.0, **FIELDS | {"user_id": user_id})
    assert len(store) == 2 and store.get(second.ticket, second.user_id, 4.0) is None


def test_drop_forgets_only_the_owners_ticket():
    store = References()
    kept = store.keep(0.0, **FIELDS)
    store.drop(kept.ticket, kept.user_id + 1)
    assert len(store) == 1
    store.drop(kept.ticket, kept.user_id)
    assert len(store) == 0


@pytest.mark.parametrize("data, size", [
    (jpeg(1536, 864), (1536, 864)), (jpeg(1, 65535), (1, 65535)),
    (b"", None), (b"\xff\xd8", None), (b"GIF89a" + bytes(20), None), (jpeg(1536, 864)[:24], None),
    (b"\xff\xd8\xff\xe0\x00\x02" * 3, None),
])
def test_jpeg_size(data, size):
    assert jpeg_size(data) == size


def test_jpeg_size_reads_the_two_drawn_fixtures():
    for name in ("reference_clean.jpg", "reference_zones.jpg"):
        assert jpeg_size((FIXTURES / name).read_bytes()) == (1536, 864)


def test_the_stem_names_the_place_the_camera_and_the_time():
    assert stem(reference()) == "tm-reference_3f9a1c2e-si_camera_1_3fa9c2_20261118T183005Z"
    assert stem(reference(survey_id=None)) == "tm-reference_no-place_camera_1_3fa9c2_20261118T183005Z"
    assert stem(reference(camera="../oak ave<1>é")) == "tm-reference_3f9a1c2e-si____oak_ave_1___20261118T183005Z"


def test_the_data_file():
    found = data_file(reference(), with_location=True)
    assert list(found) == ["format", "format_version", "survey_id", "camera", "deployment_id", "location", "pictures",
                           "traffic_monitor_version", "frigate_version", "detect", "distance_unit", "zones"]
    assert (found["format"], found["format_version"]) == ("traffic-monitor-reference", 1)
    assert found["location"] == {"lat": 45.5231, "lon": -122.6765}
    assert found["pictures"]["clean"] == {
        "file": "tm-reference_3f9a1c2e-si_camera_1_3fa9c2_20261118T183005Z_clean.jpg",
        "taken_at": "2026-11-18T18:30:05Z"}
    assert found["detect"] == {"width": 1536, "height": 864} and found["distance_unit"] == "m"
    assert found["zones"][0]["sides"][0] == {"start": "A", "end": "B", "length": 12.0}
    json.dumps(found)  # nothing in it that JSON can't hold


def test_the_location_is_left_out_on_request_and_when_there_is_none():
    assert data_file(reference(), with_location=False)["location"] is None
    assert data_file(reference(point=None), with_location=True)["location"] is None
    assert "45.5231" not in json.dumps(data_file(reference(), with_location=False))
```

`test_jpeg_size_reads_the_two_drawn_fixtures` fails until Task 5 adds the fixtures; mark it `xfail(strict=True)` here and remove the mark there.

- [ ] **Step 2: Run them and see them fail** (`No module named 'tm_control.modules.cameras.reference'`).
- [ ] **Step 3: Write `reference.py`** and the line in `app.py`.
- [ ] **Step 4: Run the backend tests and see them pass**, then commit.

```bash
git add tm-control/backend
git commit   # subject: Hold a camera's reference pictures in memory under a ticket, and write their data file
```

---

### Task 4: The SVG and the zip

**Files:**
- Create: `tm-control/backend/tm_control/modules/cameras/svg.py`
- Modify: `tm-control/backend/tm_control/modules/cameras/reference.py` (`package`)
- Test: `tm-control/backend/tests/test_cameras_reference.py`

**Interfaces:**
- Consumes: `Reference`, `stem`, `data_file` (Task 3); `ZoneFacts`, `FALLBACK_COLOR` (Task 2).
- Produces:
  - `svg.reference_svg(clean: bytes, width: int, height: int, zones: list[ZoneFacts], unit: str, caption: str) -> str`
  - `reference.caption(reference: Reference) -> str`: `Traffic Monitor reference picture  ·  place <survey id or "none">  ·  camera <key>  ·  2026-11-18 18:30:05 UTC`
  - `reference.package(reference: Reference, with_location: bool) -> bytes`: the zip.

**The SVG's layout.** It is written as text, with every operator-typed string passed through `xml.sax.saxutils.escape`. All sizes below are for a frame 1536 wide and are multiplied by `s = width / 1536`; every number is written rounded to a whole pixel. `RADAR_FACTS` in the tests is `zone_facts(CAMERA)[0]` from Task 2.

| Part | Rule |
|---|---|
| Root | `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 W H+STRIP" width="W" height="H+STRIP" font-family="DejaVu Sans, Arial, Helvetica, sans-serif">`, with `STRIP = (62 + 40 * len(zones) + 44) * s` |
| Style | `.halo { paint-order: stroke; stroke: #fff; stroke-width: 6px; stroke-linejoin: round; }` (the width scaled) |
| Title | `<title>` with the caption |
| Frame | `<image href="data:image/jpeg;base64,..." width="W" height="H" preserveAspectRatio="none"/>` at the top |
| Each drawn zone | `<polygon>` through its corners in pixels, `fill` its colour at `fill-opacity="0.10"`, `stroke` its colour, `stroke-width` 4, `stroke-linejoin="round"` |
| Corner letters | Only on zones that have `sides`; when no zone has them, on every drawn zone with four corners. A dot (`<circle r="6">`, the zone's colour, white 2 stroke) on the corner, and the letter 34 toward the zone's centre, `class="halo"`, size 24, bold |
| Zone names | The key at the centre of its corners, `class="halo"`, size 26, bold, the zone's colour. While it is within 34 down and 240 across of a name already placed, it moves down by 34 |
| Strip | A white `<rect>` under the frame; the caption at `x=40, y=H+34`, size 22 |
| Legend | One row per zone, drawn or not, 40 apart from `y=H+80`: a 34 by 26 swatch, the key in bold, then `  ·  A–B 12 m, B–C 7.3 m, ...` for a zone with sides (lengths as `%g`, the unit after each), or `  ·  off in Frigate, not drawn` or `  ·  no outline` for a zone that isn't drawn |
| Footer | `Lettered corners are in the order Frigate stores them; every zone's corners are in the data file.`, size 18, `#555`, 14 above the bottom |

A zone with no colour uses `FALLBACK_COLOR`.

**The zip.** Four entries in this order, each with mode 0644 and the clean picture's time in UTC as its date: `<stem>_clean.jpg` and `<stem>_zones.jpg` stored, `<stem>.json` (`json.dumps(..., indent=2, ensure_ascii=False)` plus a newline) and `<stem>_zones.svg` deflated. It is built in an `io.BytesIO`.

- [ ] **Step 1: Write the failing tests**

```python
NS = {"svg": "http://www.w3.org/2000/svg"}


def drawing(zones, width=1536, height=864):
    return ElementTree.fromstring(reference_svg(jpeg(width, height), width, height, zones, "m", "a caption"))


def test_the_svg_carries_the_clean_frame_and_one_outline_per_drawn_zone():
    off = RADAR_FACTS.model_copy(update={"key": "zone_off", "enabled": False, "drawn": False})
    root = drawing([RADAR_FACTS, off])
    assert root.get("viewBox") == f"0 0 1536 {864 + 62 + 40 * 2 + 44}"
    image = root.find("svg:image", NS)
    assert base64.b64decode(image.get("href").removeprefix("data:image/jpeg;base64,")) == jpeg(1536, 864)
    assert (image.get("width"), image.get("height")) == ("1536", "864")
    [polygon] = root.findall("svg:polygon", NS)
    assert polygon.get("points").split()[0] == "260,422" and polygon.get("stroke") == "#40a05c"
    text = " ".join(node.text or "" for node in root.iter("{http://www.w3.org/2000/svg}text"))
    assert "A–B 12 m, B–C 7.3 m, C–D 12 m, D–A 7.3 m" in " ".join(root.itertext())
    assert "off in Frigate, not drawn" in " ".join(root.itertext()) and "zone_radar" in text


def test_a_key_with_markup_stays_text():
    key = '<script>alert(1)</script>&"\'é'
    root = drawing([RADAR_FACTS.model_copy(update={"key": key})])
    assert root.find(".//svg:script", NS) is None
    assert sum(node.text == key for node in root.iter()) >= 1


def test_only_zones_with_side_lengths_get_corner_letters():
    plain = RADAR_FACTS.model_copy(update={"key": "zone_capture", "distances": [], "sides": []})
    assert len(drawing([RADAR_FACTS, plain]).findall("svg:circle", NS)) == 4
    assert len(drawing([plain, plain]).findall("svg:circle", NS)) == 8   # none has lengths: every four-cornered zone


def test_names_on_top_of_each_other_step_apart():
    twin = RADAR_FACTS.model_copy(update={"key": "zone_twin"})
    names = [n for n in drawing([RADAR_FACTS, twin]).iter("{http://www.w3.org/2000/svg}text")
             if n.text in ("zone_radar", "zone_twin") and n.get("class") == "halo"]
    assert abs(float(names[0].get("y")) - float(names[1].get("y"))) >= 34


def test_sizes_follow_the_frames_width():
    root = drawing([RADAR_FACTS], width=768, height=432)
    assert root.get("viewBox") == f"0 0 768 {432 + (62 + 40 + 44) // 2}"
    assert root.find("svg:polygon", NS).get("stroke-width") == "2"


def test_a_zone_with_no_colour_or_no_corners_doesnt_break_the_drawing():
    bare = ZoneFacts(key="zone_lane_bus", color=None, enabled=True, drawn=False, corners=[], distances=[], sides=[],
                     inertia=None, loitering_time=None, speed_threshold=None, objects=[], filters={})
    root = drawing([bare, RADAR_FACTS.model_copy(update={"color": None})])
    assert root.find("svg:polygon", NS).get("stroke") == "#888888" and "no outline" in " ".join(root.itertext())


def test_the_zip_holds_the_four_files_from_the_same_bytes():
    kept = reference()
    archive = zipfile.ZipFile(io.BytesIO(package(kept, with_location=True)))
    name = "tm-reference_3f9a1c2e-si_camera_1_3fa9c2_20261118T183005Z"
    assert archive.namelist() == [f"{name}_clean.jpg", f"{name}_zones.jpg", f"{name}.json", f"{name}_zones.svg"]
    assert archive.read(f"{name}_clean.jpg") == kept.clean and archive.read(f"{name}_zones.jpg") == kept.zones_picture
    assert json.loads(archive.read(f"{name}.json")) == data_file(kept, with_location=True)
    assert archive.getinfo(f"{name}.json").date_time == (2026, 11, 18, 18, 30, 5)
    ElementTree.fromstring(archive.read(f"{name}_zones.svg"))


def test_the_zip_without_the_location_holds_it_nowhere():
    data = package(reference(), with_location=False)
    archive = zipfile.ZipFile(io.BytesIO(data))
    assert all(b"45.5231" not in archive.read(name) for name in archive.namelist())
```

- [ ] **Step 2: Run them and see them fail** (`No module named 'tm_control.modules.cameras.svg'`).
- [ ] **Step 3: Write `svg.py`, `caption`, and `package`.** `svg.py` imports only `zones.py` from `tm_control`.
- [ ] **Step 4: Run the backend tests and see them pass**, then commit.

```bash
git add tm-control/backend
git commit   # subject: Draw the reference picture's labelled SVG and pack the zip
```

---

### Task 5: The routes, and fake mode's stand-in

**Files:**
- Modify: `tm-control/backend/tm_control/modules/cameras/router.py`, `tm-control/backend/tm_control/fake.py`
- Create: `tm-control/backend/tests/fixtures/reference_clean.jpg`, `reference_zones.jpg`
- Modify: `tm-control/ui/src/api/openapi.json`, `schema.d.ts` (regenerated), `tm-control/backend/tests/test_openapi_document.py`
- Test: `tm-control/backend/tests/test_api_cameras_reference.py`

**Interfaces:**
- Consumes: everything Tasks 1 to 4 produce.
- Produces, under `/api/v1`, all `require_admin`:

| Route | Answers |
|---|---|
| `POST /cameras/{name}/reference` | 200 `ReferenceOut`. Takes the pictures and keeps them. |
| `GET /cameras/{name}/reference/{ticket}/{picture}` | 200 `image/jpeg`, `Cache-Control: no-store`. `picture` is `clean.jpg` or `zones.jpg`. |
| `GET /cameras/{name}/reference/{ticket}/package?location=true\|false` | 200 `application/zip`, `Cache-Control: no-store`, `Content-Disposition: attachment; filename="<stem>.zip"`. `location` is required. |
| `DELETE /cameras/{name}/reference/{ticket}` | 204, whether or not the ticket was held. |

```python
class ReferenceOut(BaseModel):
    ticket: str
    expires_in: int          # seconds: 600
    stem: str                # the zip's name without ".zip"
    camera: str
    survey_id: str | None
    taken_at: str            # the clean picture's, as in the data file
    width: int
    height: int
    unit: Literal["m", "ft"]
    zones: list[ZoneFacts]
    people: Literal["none", "seen", "not_checked"]
    has_location: bool       # the place in use has a point, so the box can be ticked
```

- In `fake.py`: `FAKE_FRIGATE_VERSION = "0.18.2-fake"`, `frigate_stats(settings) -> dict` (the fixture's stats, with the first camera's numbers for every camera the fake Frigate has), `frigate_frame(settings, camera: str, zones: bool) -> frigate.Frame | None` (the fixture pictures, never offline; `None` for a camera the fake Frigate lacks), `frigate_people(settings, camera: str) -> int | None` (0).

**The take, in order.** Each read of Frigate is `fake.<...>` in fake mode and `frigate.<...>` on a device, as `set_detection` does it. The take holds no lock: it writes nothing.

1. `config.yml` has no entry `name`: 404 `not_found` (`_not_found()`).
2. Frigate's whole config, read once (`frigate.config()`): none, or safe mode: 409 `frigate_unavailable` (`_unavailable()`).
3. The entry's row from `compare()`: its Frigate camera is absent, or the entry duplicates another: 409 `cameras_changed`. The camera is off in Frigate: 409 `camera_off`, with `set_detection`'s message.
4. No detect size in the config: 409 `no_picture`.
5. Frigate's stats: the camera's `camera_fps` isn't a number above 0, or the stats didn't come: 409 `no_picture`.
6. When the row's `detect` is `True`: `people_tracked`, before.
7. The clean frame, then the zones frame. Either is `None`, is marked offline, or has a `jpeg_size` other than the detect size: 409 `no_picture`. Each picture's time is `time.time()` when its answer arrived.
8. When step 6 ran: `people_tracked`, after. `people` is `"seen"` when either count is above 0, `"not_checked"` when step 6 didn't run or either answer was `None`, else `"none"`.
9. The place in use (`Places(...).in_use()`), its point when it has both coordinates, and the camera's open deployment: the row of `nodered.deployments(place.id)` with `sensorType == "cameras"`, `sensorName == name`, and no `entryEndDateTime`. No place, or a `NodeRedError`: no deployment id. The versions are `manifest.tm_version` and `frigate.version()` (`FAKE_FRIGATE_VERSION` in fake mode), and the unit is `distance_unit` of step 2's config.
10. Keep it (`app.state.references.keep(time.monotonic(), ...)`), record the audit row, answer.

`no_picture`'s message: `Frigate has no live picture from this camera right now. Check the camera on the Status page, then try again.`

Steps 5 and 7 together are how Frigate's error picture is refused: it comes with a 200 and no header, so the take checks that the camera is delivering frames and that the picture is the size of the detect frame.

**The other routes.** A ticket that `references.get` doesn't return, or whose `camera` isn't `name`: 404 `reference_expired`, `These pictures are no longer held on the device. Take them again.`

**Audit.** The take records `camera.reference`; the package records `camera.reference_saved` or `camera.reference_saved_with_location` (the second only when the location was asked for and there was a point). The detail is the camera's key each time. Showing a picture and dropping a ticket record nothing.

- [ ] **Step 1: Make the two fixtures.** They are drawings, not photographs: 1536 by 864, a grey road between two verges under a pale sky, with the words `Stand-in picture (fake mode)`. `reference_zones.jpg` is the same drawing with the outline of each of the four zones in `fixtures/frigate_api_config.json`, 2 pixels wide, in the zone's colour (its `color` read as blue, green, red). Draw them with a throwaway Pillow script run with the system `python3`, which has Pillow; save at quality 80. Don't commit the script, and don't add Pillow to any requirements file. Remove the `xfail` mark from Task 3's fixture test.

- [ ] **Step 2: Write the failing tests** in `test_api_cameras_reference.py`, with `test_api_cameras.py`'s `admin` fixture and `frigate_says` helper (import them or repeat them as that file's neighbours do). `take(client, name="picam_h265")` posts with `JSON_HEADERS`.

```python
def test_a_take_answers_the_legend_and_holds_the_pictures(admin):
    r = take(admin)
    assert r.status_code == 200, r.text
    found = r.json()
    assert (found["camera"], found["survey_id"], found["width"], found["height"]) == ("picam_h265", None, 1536, 864)
    assert found["expires_in"] == 600 and found["unit"] == "m" and found["people"] == "none"
    assert found["stem"].startswith("tm-reference_no-place_picam_h265_")
    assert [zone["key"] for zone in found["zones"]][:4] == ["zone_capture", "zone_far", "zone_near", "zone_radar"]
    assert found["zones"][0]["color"] == "#7035b0" and found["zones"][4]["drawn"] is False   # zone_lane_bus: {}
    base = f"/api/v1/cameras/picam_h265/reference/{found['ticket']}"
    for picture, fixture in (("clean.jpg", "reference_clean.jpg"), ("zones.jpg", "reference_zones.jpg")):
        shown = admin.get(f"{base}/{picture}")
        assert shown.status_code == 200 and shown.content == (FIXTURES / fixture).read_bytes()
        assert shown.headers["content-type"] == "image/jpeg" and shown.headers["cache-control"] == "no-store"


def test_the_package_is_the_zip_of_what_was_shown(admin):
    found = take(admin).json()
    r = admin.get(f"/api/v1/cameras/picam_h265/reference/{found['ticket']}/package", params={"location": "false"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == f'attachment; filename="{found["stem"]}.zip"'
    archive = zipfile.ZipFile(io.BytesIO(r.content))
    assert archive.read(f"{found['stem']}_clean.jpg") == (FIXTURES / "reference_clean.jpg").read_bytes()
    assert json.loads(archive.read(f"{found['stem']}.json"))["location"] is None


def test_the_package_needs_the_location_choice(admin):
    found = take(admin).json()
    assert admin.get(f"/api/v1/cameras/picam_h265/reference/{found['ticket']}/package").status_code == 422
```

And these, each a few lines in the same style:

- **The place.** After a place is deployed through the API (as `test_api_surveys.py` does), a take answers its `survey_id` and `has_location: true`; the package with `location=true` holds the place's point and a `deployment_id` that is one of the fake Node-RED's open rows for `("cameras", "picam_h265")`. With `nodered.deployments` raising `NodeRedError("unreachable")` the take still answers, and the data file's `deployment_id` is `null`. For a place with no coordinates `has_location` is false and `location=true` still gives `null`.
- **Refusals, each with nothing kept** (`len(admin.app.state.references) == 0`) **and no audit row:** an unknown entry (404 `not_found`); Frigate silent and in safe mode (409 `frigate_unavailable`); the entry's camera gone from Frigate (409 `cameras_changed`); the camera off in Frigate (409 `camera_off`); `camera_fps` 0, the camera missing from the stats, and no stats (409 `no_picture`); the clean frame `None`; the zones frame `Frame(data, True)`; a frame of `jpeg(640, 360)`, which is Frigate's error picture as the take sees it (409 `no_picture` each).
- **People.** With `fake.frigate_people` answering 0 then 1: `"seen"`. Answering `None`: `"not_checked"`. With the camera's detection off in the fake Frigate (`fake.set_frigate_detect`): `"not_checked"`, and `frigate_people` is never called.
- **Frigate is asked by its own name.** After `POST /cameras` adds `oak_ave_tele` under a neutral name, a take of that name calls `fake.frigate_frame` with `"oak_ave_tele"`, and neither the take's answer nor any file in the package contains `oak_ave_tele`.
- **Nothing private in the files.** The package of `picam_h265` contains neither `Bus lane (north)` (the fake zone's `friendly_name`) nor the place's description, in any of its files.
- **Tickets.** A ticket under another camera's name, an unknown ticket, and a ticket after `DELETE` are 404 `reference_expired` on both `GET`s; with `References.TTL` patched to 0 before the take, the same. `DELETE` answers 204 twice running. A second take makes the first ticket 404.
- **Audit and logs.** After a take and two packages (one with the location at a place that has a point, one without), the audit rows are `("camera.reference", key)`, `("camera.reference_saved_with_location", key)`, `("camera.reference_saved", key)`. With `caplog` at DEBUG, no record holds the ticket, a coordinate, or `oak_ave_tele`.
- **Roles.** A viewer gets 403 and a signed-out caller 401 on all four routes; the `POST` and the `DELETE` without the JSON content type are refused by the cross-site check as the other writes are.

In `test_openapi_document.py`, add `test_reference_paths_are_declared_with_their_answers`: the `POST` declares a 200 with a `$ref`; the picture route declares 200 with `image/jpeg`, and the package route 200 with `application/zip`, each `{"type": "string", "format": "binary"}`; the `DELETE` declares 204.

- [ ] **Step 3: Run them and see them fail** (404 on the `POST`).
- [ ] **Step 4: Write the fake functions and the four routes**, under a `# Reference picture` heading at the end of `router.py`, and extend the module's docstring. Declare the two binary answers with `responses=` as `modules/detection/router.py`'s `_binary` does. Answer the pictures and the zip with `fastapi.Response`; nothing touches the disk.
- [ ] **Step 5: Regenerate the API files** (the `dump-openapi` line under "Commands", then the UI command, which runs `api:generate`).
- [ ] **Step 6: Run everything off-device and see it pass**

Run: `python -m pytest container/node-red-tm/schema/tests script/tests tm-control/backend/tests -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add tm-control
git commit   # subject: Take a camera's reference picture through the control app's API
```

---

### Task 6: The Cameras page

Load `frontend-design:frontend-design`, `superpowers:test-driven-development`, and `superpowers:verification-before-completion` first.

**Files:**
- Create: `tm-control/ui/src/modules/cameras/reference.ts`, `ReferencePicture.vue`
- Modify: `tm-control/ui/src/modules/cameras/CamerasPage.vue`, `tm-control/ui/tests/fake-api.ts` (`referenceOut(changes)`), `tm-control/ui/README.md` (design notes)
- Test: `tm-control/ui/tests/camera-reference.spec.ts`, `reference-picture.spec.ts`, `cameras-page.spec.ts`

**Interfaces:**
- Consumes: `ReferenceOut` and `ZoneFacts` from the regenerated schema; `saveBlob` from `components/download.ts`.
- Produces, in `reference.ts`:
  - `canTake(row: CameraRow): boolean`: an entry (`name !== null`) whose camera is on in Frigate and that duplicates no other.
  - `pictureUrl(name: string, ticket: string, picture: 'clean.jpg' | 'zones.jpg'): string`: `/api/v1/cameras/<name, URI-encoded>/reference/<ticket>/<picture>`.
  - `legendRows(reference: ReferenceOut): { key: string; color: string; detail: string }[]`
  - `peopleLine(people: ReferenceOut['people']): { type: 'warning' | undefined; text: string }`
  - `ReferencePicture.vue`: a dialog with `v-model:open` and the prop `name: string` (the camera's key).

**The flow.** The row's button opens the dialog. It shows the intro and the note, and **Take the pictures**. A take (`POST`) shows both pictures as `<img>` elements whose `src` is `pictureUrl(...)`, the people line, the legend, the location box, and **Save the zip**, **Take again**, and **Close**. Save fetches the package as a blob (`parseAs: 'blob'`, `query: { location }`) and hands it to `saveBlob(blob, `${stem}.zip`)`. Closing the dialog, or taking again, sends `DELETE` for the ticket it held and ignores the answer. The dialog starts over each time it opens. A 404 from Save, or a picture that fails to load (`@error`), puts the dialog back to its first step with the expired message. Any other refusal shows the API's message in an error alert and stays where it is.

The copy, exactly (the maintainer edits the note's wording at the stop below):

| Where | Text |
|---|---|
| Row button | `Reference picture` (text variant, primary, with the row's other actions; shown when `canTake(row)` and Frigate answers) |
| Dialog title | `Reference picture of ${name}` |
| Intro | `A still picture of what this camera sees, and the same view with its zones marked, for a tool that places recorded paths on a street. You get one zip with both pictures, a data file with the zones, and a labelled drawing.` |
| Note (a tonal warning alert) | `This picture shows your street. Anyone who has it can tell where the unit is, and it shows whoever was in view. Take it when nobody is in the picture, look at both pictures before you save them, and share them only with people you would give the unit's exact location. The data file also holds that location unless you clear the box below.` |
| Held line | `The device holds these pictures in memory for 10 minutes and never saves them.` |
| Picture captions | `The camera's view` and `The same view with Frigate's zone outlines`; under both, `The two were taken a moment apart.` |
| `peopleLine('seen')` | warning: `Frigate was tracking a person on this camera when the pictures were taken. Wait until nobody is in view, then take them again.` |
| `peopleLine('none')` | `Frigate wasn't tracking a person when the pictures were taken. It can miss people, so look at both pictures yourself.` |
| `peopleLine('not_checked')` | `The check for people in view couldn't run, because Frigate's detection is off for this camera or Frigate didn't answer. Look at both pictures yourself.` |
| Legend heading | `Zones` |
| `legendRows` detail | `A–B 12 m, B–C 7.3 m, C–D 12 m, D–A 7.3 m` for a zone with sides (the unit from `reference.unit`); `off in Frigate, not drawn` for a zone that is off; `no outline` for a zone that is on and not drawn; otherwise empty. `color` is the zone's, or `#888888`. |
| Location box | `Include this place's exact location`; ticked on every take; disabled and cleared when `has_location` is false, with the hint `No place with coordinates is in use, so the data file holds no location.` |
| Expired | `These pictures are no longer held on the device. Take them again.` |

- [ ] **Step 1: Write the failing tests.**

  `camera-reference.spec.ts`: `canTake` for an in-step entry (true), a new Frigate camera, an entry whose camera is off, gone, or unknown, and a duplicate (false each); `pictureUrl('oak ave', 'tk', 'clean.jpg')` is `/api/v1/cameras/oak%20ave/reference/tk/clean.jpg`; `legendRows` for the four cases in the table, with `ft` when the unit is `ft`; `peopleLine` for its three values.

  `reference-picture.spec.ts`, mounted through the Cameras page as `cameras-page.spec.ts` mounts it, with `referenceOut()` answering the `POST`:
  - The row button opens the dialog with the intro and the note, and no picture yet. A row that can't take one has no such button, and no row has it while Frigate is down.
  - **Take the pictures** sends `POST /api/v1/cameras/camera_1_3fa9c2/reference` and shows two `img` elements with the two `pictureUrl` addresses and the captions as their `alt` text, the people line, and one legend row per zone.
  - `people: 'seen'` shows a warning alert; `'not_checked'` shows the sentence without one.
  - With `has_location: true` the box is ticked, and **Save the zip** sends `GET .../package` with `location=true` and saves a blob named `<stem>.zip` (spy on `URL.createObjectURL` as `detection-page.spec.ts` does). Cleared, it sends `location=false`. With `has_location: false` the box is disabled and the hint shows.
  - A 404 `reference_expired` from Save returns the dialog to its first step with the expired message and no pictures. So does an `error` event on a picture.
  - A 409 `no_picture` from the take shows the API's message and leaves **Take the pictures**.
  - **Take again** sends `DELETE` for the old ticket, then `POST`. **Close** sends `DELETE` and closes; opening it again shows the first step.

- [ ] **Step 2: Run them and see them fail** (`npm test` in the Node image).
- [ ] **Step 3: Write `reference.ts`, `ReferencePicture.vue`, and the button in `CamerasPage.vue`.** Follow `CorrectDialog.vue` for the dialog (`v-dialog` with `max-width` and an `aria-label`, a `v-card` with `color="surface"`), with a wider `max-width` so the two pictures sit side by side on a desktop and stack on a phone (`v-row` and `v-col cols="12" md="6"`). Each picture is a plain `<img>` with `class="w-100"`, the legend a list of rows with a small coloured square (`:style="{ backgroundColor: row.color }"`, which is data, not styling). The page keeps one dialog and the name it is open for; `hasBody(row)` counts the new button.
- [ ] **Step 4: Build, test, and look at it.** Run the full UI command from "Commands". Then run fake mode (`CLAUDE.md`, "Fake mode") and open the dialog at phone and desktop width, before and after a take, and with a place deployed so the box is live. Add a "Reference picture" paragraph to the Cameras design notes in `tm-control/ui/README.md`: the two steps, why the note comes before the pictures, and why the pictures are plain `<img>` elements (the session cookie authorizes them, and nothing is kept in the page once the dialog closes).
- [ ] **Step 5: Commit, then stop for the maintainer**

```bash
git add tm-control/ui
git commit   # subject: Add the reference picture dialog to the Cameras page
```

Stop here. Show the maintainer the dialog in fake mode (screenshots at both widths, both steps), open the zip's SVG and data file from a fake-mode take for the maintainer, and ask for their wording of the note before the docs quote it.

---

### Task 7: Docs

**Files:** the six under "Docs" in the table above.

- [ ] **Step 1: `docs/use/cameras.md`.** A new section before "Zone names are saved with your data", titled "Take a reference picture":
  - What it is for and what the zip holds, as a table of the four files.
  - The steps: **Reference picture** on the camera's row, read the note, **Take the pictures**, look at both, choose whether to include the location, **Save the zip**.
  - Privacy, in the page's own voice: the picture shows the street and whoever was in view; the data file holds the place's exact location unless the box is cleared; the device keeps the pictures in memory for ten minutes and never saves them; they are in no database, export, or upload.
  - The people check and its limits: it needs Frigate's detection on, it asks about people only, and the preview is the real check.
  - When it refuses: the camera is off in Frigate, or isn't sending.
  - The data file's fields, as a table, with the zone fields, the corner letters, and the note that side lengths are listed in the order Frigate stores the corners. Say that Frigate's name for the camera and a zone's display name are never in it.
  - That the zones picture is Frigate's own drawing (outlines only, zones that are on) and the SVG is the control app's, drawn on the clean picture.
  - Saving the zip from a phone on the unit's hotspot: it doesn't save from Android's sign-in window, like **Download diagnostics**; link to that list in `wifi-hotspot.md`.
  - Add the row button to the list of what a row shows.
- [ ] **Step 2: The screenshot.** `docs/assets/images/cameras-reference.png`: the dialog after a take, on a phone, in fake mode (the stand-in drawing), with alt text that says what it shows. Reference it from the new section at `width="300"`.
- [ ] **Step 3: `docs/use/wifi-hotspot.md`**: in the list of what saves from Android's sign-in window, add the reference picture's zip beside **Download diagnostics** (it doesn't; the preview does show). The bench confirms it before the sentence is written.
- [ ] **Step 4: `docs/development/tm-control.md`**, "The Cameras module": the four routes in its table, and a paragraph on the tickets (in memory, 600 seconds, one per admin), the two checks that refuse Frigate's error picture, and the three new files (`zones.py`, `reference.py`, `svg.py`).
- [ ] **Step 5: `CLAUDE.md`**: in the `tm-control/` bullet, the Cameras page's reference picture; in the runtime topology's tm-control paragraph, one sentence on the routes, the in-memory tickets, and the rule that no picture is written to disk or logged.
- [ ] **Step 6: Build the docs**

Run: `~/.venvs/tm-docs/bin/mkdocs build --strict`
Expected: it builds with no warning.

- [ ] **Step 7: Commit**

```bash
git add docs CLAUDE.md tm-control/ui/README.md
git commit   # subject: Document the Cameras page's reference picture
```

---

### Task 8: Device tests, bench, the plan copy, and the text for review

**Files:**
- Modify: `script/devpi/tests/test_web.py`

- [ ] **Step 1: Device tests.**
  - `VIEWER_ACTIONS` gains the four routes for `picam_h265` with a made-up ticket (403 each). Put the `POST` in `GUARDED_ACTIONS`: let through, it would hold a street picture in the app's memory.
  - `test_a_reference_picture_is_a_zip_of_four_files`, only on a host marked `pii_free` (`require_pii_free`), because the test process receives the pictures' bytes. For the first row of `GET /cameras` that is an entry with its camera on: take; both pictures answer 200, `image/jpeg`, `no-store`, and bytes that start `FF D8 FF`; the package with `location=false` is a zip of four names with the answer's stem, whose data file has `"location": null`, the row's key as `camera`, and no Frigate camera name when the two differ; then `DELETE`, and the picture is a 404. Failure messages name statuses, lengths, and keys, never bytes. A unit with no such row skips.
- [ ] **Step 2: Run everything off-device once more** (the three commands under "Commands": pytest, the UI, the docs). All pass.
- [ ] **Step 3: Bench run, logged with `tmdev check`** on a bench unit marked `pii_free`, at the branch head (`script/devpi/README.md`), run from a worktree of that commit. Deploy with the `tm-control` and `revproxy` tags. The AI reads statuses, headers, types, and sizes only, and never opens or saves a picture. Items:
  1. The device tests pass (`tmdev.py test <host>`), the new one included.
  2. As installed (detection off): a take answers 200 with `people: not_checked`, the detect size, and the camera's zones. Record `ui.unit_system` from Frigate's `/api/config` and the two pictures' lengths.
  3. `manual`, the maintainer: open the dialog in a browser, look at both pictures, save the zip, and open the SVG. The outlines sit on the zones as Frigate's editor shows them, the names are readable, and the data file's corners match Frigate's. From an Android phone in the hotspot's sign-in window: the preview shows, and whether the zip saves.
  4. The camera stops sending: stop `go2rtc_server.service`, wait 30 seconds, and ask Frigate for `latest.jpg` directly. Record its status, whether `X-Frigate-Offline` is set, and the picture's size from its header bytes. A take answers 409 `no_picture`. Start the service again and wait for a take to succeed.
  5. The camera off in Frigate (its `enabled` switch, not detection): a take answers 409 `camera_off`. Turn it back on and confirm in `/api/config`.
  6. The pictures are gone 10 minutes after a take (404 `reference_expired`), and the journal of `tm-control.service` for the run holds no ticket and no coordinate.
  7. The audit log has `camera.reference` rows with the camera's key only.
  8. The people check. **This turns Frigate's detection on, once, so ask the maintainer first and say it is one time.** With their consent: turn detection on for the bench camera, take once (`people` is `none`, or `seen` if he stands in view), turn detection off, confirm `detect.enabled` is false in `/api/config` sent with `X-Cache-Bypass: 1`, and record that in the check. Without it, record the item as not run.
- [ ] **Step 4: The public plan copy.** Copy this plan to `design/plans/2026-11-18-reference-picture.md`, and commit it last.
- [ ] **Step 5: Write the text, and stop.** Write, for the maintainer to read before anything is pushed: the PR title and body from `.github/PULL_REQUEST_TEMPLATE.md`, against `dev`, with "Closes #338", with the bench check's id, what item 4 found about Frigate's error picture, and the template's "Docs" and "AI assistance" sections filled in.

---

## As built (added 2026-11-18, after the bench)

The bench run (check `20261118T232006Z`, a Raspberry Pi 5 with a Coral PCIe, deployed with the `tm-control` and `revproxy` tags) changed the build in these ways. The tasks above are kept as they were written.

- **The people check is gone.** Bench items 8 and 8b found that Frigate's `/api/events` can't answer the question. Frigate 0.18.2 saves an event only once the object has a clip or a snapshot, and makes a snapshot only once the object has moved. So with recording and snapshots off (as installed), or with a person standing still, the check said nobody was there while someone stood in view. The list that does hold every tracked object is `camera_activity` on Frigate's WebSocket, which would need a new package. The maintainer chose to drop the check: `people_tracked`, `frigate_people`, `people` in `ReferenceOut`, and `peopleLine` aren't in the code, and the dialog's note now says the device doesn't check the pictures for people and the admin is responsible for making sure nobody is in either picture before saving them. The docs say the same.
- **The ticket is kept out of the control app's access log.** uvicorn's access log printed each picture's path, ticket included. `HideTickets` in `modules/cameras/reference.py`, a filter `tm-control serve` puts on `uvicorn.access`, writes `-` in its place. nginx's access log still holds the ticket; it expires in ten minutes.
- **Zone corners are fractions as Frigate gives them.** Frigate's `/api/config` answers with fractions of the frame even when its `config.yml` holds pixels, and a corner past the frame's edge is below 0 or above 1. `_corners` keeps them as they are and no longer divides by the detect size; the first build dropped a zone with a corner above 1 from the SVG and misread the rest.
- **The SVG's labels are lighter.** Zone names are regular weight (corner letters stay bold), and the white halo behind them is 3 px at a width of 1536.
- **Frigate's frame when the camera stops sending.** With go2rtc stopped, `latest.jpg` answered 200 with `X-Frigate-Offline: true` and an older 320×180 frame. A take refuses it with 409 `no_picture`; the header, the stats, and the size would each have caught it. Frigate's no-frames error picture wasn't seen, because Frigate still had an older frame.
- **Android's sign-in window** shows the preview but doesn't save the zip ("Could not download"), as expected. The docs say so.
