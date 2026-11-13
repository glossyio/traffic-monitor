"""The detection module's reading of Frigate: the detector, the model that runs, and the label lists."""

import json
from pathlib import Path

import pytest
from placeholders import PLACEHOLDER_KEY

from tm_control.adapters import httpjson
from tm_control.adapters.yamlfile import ConfigRead, _round_trip_yaml
from tm_control.modules.detection import picker
from tm_control.modules.detection.inventory import InstallerDefault, Model, ModelFile, parse_sidecar
from tm_control.modules.detection.labels import of_model, recognised, tracked
from tm_control.modules.detection.picker import (
    FRIGATE_HEADER,
    Running,
    UseError,
    apply,
    check_usable,
    default_section,
    detector_type,
    model_section,
    refusal_lines,
    replace_model_section,
    running_model,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "model_sidecar.json"
PLUS_ID = "0123456789abcdef0123456789abcdef"
INSTALLER_FILE = "installer_int8_edgetpu.tflite"
CACHE = "/config/model_cache"
NO_FILE = ConfigRead(None, "missing")
INSTALLER = InstallerDefault(section={"path": f"{CACHE}/{INSTALLER_FILE}"}, file=INSTALLER_FILE, labels_file=None)


def answer(detectors, **top):
    return {"detectors": detectors, **top}


def file_of(data):
    return ConfigRead(data, None)


def plus_model(name=PLUS_ID):
    sidecar = parse_sidecar(FIXTURE.read_bytes())
    return Model(name, "frigate_plus", sidecar, (ModelFile(name, 1, "a" * 64),), True, None)


def local_model(name="mine.tflite", complete=True, **changes):
    record = json.loads(FIXTURE.read_text())
    record.pop("id")
    record.pop("verifiedCounts")
    sidecar = parse_sidecar(json.dumps(record | changes).encode())
    return Model(name, "local", sidecar, (ModelFile(name, 1, "c" * 64),), complete, None)


def default_model():
    return Model(INSTALLER_FILE, "installer_default", None, (ModelFile(INSTALLER_FILE, 1, "b" * 64),), True, None)


def test_detector_type_prefers_frigates_answer_then_the_file_then_cpu():
    frigate = answer({"coral": {"type": "edgetpu"}, "second": {"type": "cpu"}})
    assert detector_type(frigate, file_of({"detectors": {"x": {"type": "hailo8l"}}})) == "edgetpu"
    assert detector_type(None, file_of({"detectors": {"x": {"type": "hailo8l"}}})) == "hailo8l"
    assert detector_type(None, file_of({"mqtt": {"enabled": False}})) == "cpu"
    assert detector_type(None, file_of({"detectors": {}})) == "cpu"
    assert detector_type(None, NO_FILE) is None
    assert detector_type(None, ConfigRead(None, "invalid", 3, 1)) is None
    assert detector_type(answer({}), NO_FILE) is None  # an answer without a detector says nothing


def test_running_model_from_frigate_names_the_pair_and_its_kind():
    models = [default_model(), plus_model()]
    frigate = answer({"coral": {"type": "edgetpu", "model": {"path": f"{CACHE}/{PLUS_ID}"}}})
    assert running_model(frigate, NO_FILE, INSTALLER, models) == Running(
        PLUS_ID, "frigate_plus", f"{CACHE}/{PLUS_ID}", "frigate")
    frigate = answer({"coral": {"model": {"path": f"{CACHE}/{INSTALLER_FILE}"}}})
    running = running_model(frigate, NO_FILE, INSTALLER, models)
    assert (running.name, running.kind, running.source) == (INSTALLER_FILE, "installer_default", "frigate")
    # the installer's file is its default even when the file isn't in the cache
    assert running_model(frigate, NO_FILE, INSTALLER, []).kind == "installer_default"
    frigate = answer({"cpu": {"model": {"path": "/cpu_model.tflite"}}})
    assert running_model(frigate, NO_FILE, INSTALLER, models) == Running(
        None, "frigate_default", "/cpu_model.tflite", "frigate")
    frigate = answer({"cpu": {"model": {"path": f"{CACHE}/gone.tflite"}}})
    assert running_model(frigate, NO_FILE, INSTALLER, models) == Running(
        "gone.tflite", "local", f"{CACHE}/gone.tflite", "frigate")
    frigate = answer({"cpu": {"model": {}}}, model={"path": f"{CACHE}/{PLUS_ID}"})  # the top-level path is the fallback
    assert running_model(frigate, NO_FILE, INSTALLER, models).name == PLUS_ID
    for nothing in (answer({"cpu": {}}), answer({"cpu": {"model": {"path": ""}}}), answer({})):
        assert running_model(nothing, NO_FILE, INSTALLER, models) == Running(None, "frigate_default", None, "frigate")
    nested = answer({"cpu": {"model": {"path": f"{CACHE}/sub/{PLUS_ID}"}}})
    assert running_model(nested, NO_FILE, INSTALLER, models).name is None


def test_running_model_from_the_file_reads_plus_paths():
    models = [plus_model()]
    file = file_of({"model": {"path": f"plus://{PLUS_ID}"}, "detectors": {"c": {"type": "edgetpu"}}})
    assert running_model(None, file, INSTALLER, models) == Running(
        PLUS_ID, "frigate_plus", f"{CACHE}/{PLUS_ID}", "config_file")
    assert running_model(None, file_of({"detectors": {}}), INSTALLER, models) == Running(
        None, "frigate_default", None, "config_file")
    assert running_model(None, file_of({"model": {"path": "plus://../x"}}), INSTALLER, models).name is None
    assert running_model(None, NO_FILE, INSTALLER, models) == Running(None, None, None, None)


def test_recognised_prefers_frigates_merged_labelmap(tmp_path):
    models = [plus_model(), default_model()]
    labelmap = {str(index): f"label{index}" for index in range(91)}
    items = list(labelmap.items())
    frigate = answer({"coral": {"model": {"path": f"{CACHE}/{PLUS_ID}", "labelmap": dict(reversed(items))}}})
    running = running_model(frigate, NO_FILE, INSTALLER, models)
    labels, source = recognised(frigate, running, models, INSTALLER)
    assert source == "frigate" and labels == [f"label{index}" for index in range(91)]
    # without a labelmap in Frigate's answer, the running model's sidecar
    frigate = answer({"coral": {"model": {"path": f"{CACHE}/{PLUS_ID}"}}})
    running = running_model(frigate, NO_FILE, INSTALLER, models)
    assert recognised(frigate, running, models, INSTALLER) == (["person", "bicycle", "car"], "sidecar")
    assert recognised(None, running, models, INSTALLER) == (["person", "bicycle", "car"], "sidecar")
    # the installer's default has its labels file
    labels_file = tmp_path / "labels.txt"
    labels_file.write_text("person\n\nbicycle\n  \ncar\n")
    installer = InstallerDefault(INSTALLER.section, INSTALLER_FILE, labels_file)
    running = running_model(None, file_of({"model": {"path": f"{CACHE}/{INSTALLER_FILE}"}}), installer, models)
    assert recognised(None, running, models, installer) == (["person", "bicycle", "car"], "labels_file")
    assert recognised(None, running, models, INSTALLER) == (None, None)  # no labels file
    missing = InstallerDefault(INSTALLER.section, INSTALLER_FILE, tmp_path / "none.txt")
    assert recognised(None, running, models, missing) == (None, None)
    default = Running(None, "frigate_default", None, "frigate")
    assert recognised(None, default, models, installer) == (None, None)
    assert recognised(None, Running(None, None, None, None), models, installer) == (None, None)


@pytest.mark.parametrize("labelmap", [{}, {"a": "x"}, {"0": 1}, ["x"], "x"])
def test_recognised_ignores_a_labelmap_it_cannot_read(labelmap):
    models = [plus_model()]
    frigate = answer({"c": {"model": {"path": f"{CACHE}/{PLUS_ID}", "labelmap": labelmap}}})
    running = running_model(frigate, NO_FILE, INSTALLER, models)
    assert recognised(frigate, running, models, INSTALLER) == (["person", "bicycle", "car"], "sidecar")


def test_recognised_leaves_out_frigates_unknown_padding():
    models = [plus_model()]
    labelmap = {str(index): "unknown" for index in range(91)} | {"0": "person", "1": "bicycle", "16": "bear"}
    frigate = answer({"coral": {"model": {"path": f"{CACHE}/{PLUS_ID}", "labelmap": labelmap}}})
    running = running_model(frigate, NO_FILE, INSTALLER, models)
    assert recognised(frigate, running, models, INSTALLER) == (["person", "bicycle", "bear"], "frigate")


def test_a_labelmap_of_nothing_but_unknown_says_nothing():
    models = [plus_model()]
    labelmap = {str(index): "unknown" for index in range(91)}
    frigate = answer({"coral": {"model": {"path": f"{CACHE}/{PLUS_ID}", "labelmap": labelmap}}})
    running = running_model(frigate, NO_FILE, INSTALLER, models)
    assert recognised(frigate, running, models, INSTALLER) == (["person", "bicycle", "car"], "sidecar")


def test_a_models_own_list_leaves_out_unknown_too(tmp_path):
    record = json.loads(FIXTURE.read_bytes())
    record["labelMap"] = {"0": "person", "1": "unknown", "2": "car", "3": "unknown"}
    padded = Model("padded", "local", parse_sidecar(json.dumps(record).encode()), (), True, None)
    assert of_model(padded, INSTALLER) == ["person", "car"]
    labels_file = tmp_path / "labels.txt"
    labels_file.write_text("person\nunknown\ncar\n")
    installer = InstallerDefault(INSTALLER.section, INSTALLER_FILE, labels_file)
    assert of_model(default_model(), installer) == ["person", "car"]
    running = Running(INSTALLER_FILE, "installer_default", f"{CACHE}/{INSTALLER_FILE}", "config_file")
    assert recognised(None, running, [default_model()], installer) == (["person", "car"], "labels_file")


def test_tracked_is_the_ordered_union_of_global_and_camera_lists():
    frigate = {
        "objects": {"track": ["person", "car"]},
        "cameras": {
            "a": {"objects": {"track": ["car", "dog", "person"]}},
            "b": {"objects": {}},
            "c": {"objects": {"track": ["bus", "dog"]}},
            "d": {},
        },
    }
    assert tracked(frigate) == ["person", "car", "dog", "bus"]
    assert tracked({"cameras": {"a": {"objects": {"track": ["cat"]}}}}) == ["cat"]
    assert tracked({"objects": {"track": "person"}, "cameras": []}) == []
    assert tracked(None) == []


# The write half: the model section, its place in config.yml, and how it reaches Frigate.

CONFIG = """# see https://docs.frigate.video/configuration/reference
mqtt:
  enabled: true
  user: "{FRIGATE_MQTT_USER}"  # quoted, as tmsetup writes it

detectors:
  # the Coral the installer found
  coral:
    type: edgetpu
    device: usb

model:
  model_type: yolo-generic
  path: /config/model_cache/old.tflite

ffmpeg:
  hwaccel_args: -hwaccel drm  # keep

cameras:
  picam_h265:
    ffmpeg:
      inputs:
        - path: rtsp://host.containers.internal:8554/picam_h265_detect
          roles:
            - detect
"""
INSTALLER_SECTION = {  # sorted, as a device's manifest JSON has it
    "height": 512,
    "labelmap_path": "/config/labels-coco17.txt",
    "model_type": "yolo-generic",
    "path": f"{CACHE}/{INSTALLER_FILE}",
    "width": 512,
}


def load(text):
    return _round_trip_yaml(2).load(text)


def dump(doc):
    import io

    out = io.StringIO()
    _round_trip_yaml(2).dump(doc, out)
    return out.getvalue()


def outside_model(text, collapse=True):
    """The text's lines that aren't the model section's (its `model:` line and the indented lines under it), with
    runs of blank lines made one when `collapse`: a section removed from between two blank lines leaves one."""
    lines, inside = [], False
    for line in text.splitlines():
        if line.startswith("model:"):
            inside = True
            continue
        if inside and line.startswith(" "):
            continue
        inside = False
        if collapse and not line and lines and not lines[-1]:
            continue
        lines.append(line)
    return lines


def test_model_section_for_a_plus_pair_is_only_the_path():
    assert model_section(plus_model()) == {"path": f"plus://{PLUS_ID}"}


def test_model_section_for_a_local_pair_translates_the_sidecar():
    section = model_section(local_model())
    assert section == {
        "path": f"{CACHE}/mine.tflite",
        "width": 320,
        "height": 320,
        "input_tensor": "nhwc",
        "input_pixel_format": "rgb",
        "model_type": "yolo-generic",
        "labelmap": {0: "person", 1: "bicycle", 2: "car"},
    }
    assert all(type(key) is int for key in section["labelmap"])
    assert model_section(local_model(inputDataType="float"))["input_dtype"] == "float"
    allowed = {"path", "labelmap_path", "width", "height", "labelmap", "attributes_map", "input_tensor",
               "input_pixel_format", "input_dtype", "model_type"}  # Frigate's ModelConfig forbids any other key
    assert set(model_section(local_model(inputDataType="int"))) <= allowed


def test_default_section_is_the_installers_for_edgetpu_and_nothing_otherwise():
    installer = InstallerDefault(section=INSTALLER_SECTION | {"extra": 1}, file=INSTALLER_FILE, labels_file=None)
    section = default_section("edgetpu", installer)
    assert section == INSTALLER_SECTION | {"extra": 1}
    assert list(section) == ["model_type", "width", "height", "path", "labelmap_path", "extra"]  # the template's order
    for detector in ("cpu", "hailo8l", "onnx"):
        assert default_section(detector, installer) is None
    assert default_section("edgetpu", None) is None


def test_replace_model_section_keeps_comments_and_the_rest():
    doc = load(CONFIG)
    replace_model_section(doc, {"path": f"plus://{PLUS_ID}"})
    text = dump(doc)
    assert outside_model(text) == outside_model(CONFIG)
    assert f"\nmodel:\n  path: plus://{PLUS_ID}\n\nffmpeg:\n" in text  # the blank line after the section stays
    assert '"{FRIGATE_MQTT_USER}"  # quoted' in text and "# the Coral the installer found" in text
    assert load(text)["model"] == {"path": f"plus://{PLUS_ID}"}

    # deleted: Frigate's own default
    doc = load(CONFIG)
    replace_model_section(doc, None)
    text = dump(doc)
    assert "model" not in load(text) and outside_model(text) == outside_model(CONFIG)
    assert "    device: usb\n\nffmpeg:\n" in text
    doc = load(text)
    replace_model_section(doc, None)  # nothing to delete
    assert dump(doc) == text

    # inserted after detectors, with int label keys
    doc = load(text)
    replace_model_section(doc, model_section(local_model()))
    inserted = dump(doc)
    assert list(load(inserted)) == ["mqtt", "detectors", "model", "ffmpeg", "cameras"]
    assert outside_model(inserted) == outside_model(CONFIG)
    assert "\nmodel:\n  path: /config/model_cache/mine.tflite\n" in inserted
    assert "  labelmap:\n    0: person\n    1: bicycle\n    2: car\n\nffmpeg:\n" in inserted
    assert load(inserted)["model"]["labelmap"] == {0: "person", 1: "bicycle", 2: "car"}

    # no detectors key either: at the end
    doc = load("mqtt:\n  enabled: false\n")
    replace_model_section(doc, {"path": f"plus://{PLUS_ID}"})
    assert dump(doc) == f"mqtt:\n  enabled: false\nmodel:\n  path: plus://{PLUS_ID}\n"


DETECTORS = "detectors:\n  c:\n    type: edgetpu\n"
AFTER = "\n# ffmpeg settings\nffmpeg:\n  a: 1\n"  # a comment and a blank line that belong to the key after model


def edit(text, section):
    doc = load(text)
    replace_model_section(doc, section)
    return dump(doc)


def test_a_deleted_model_section_leaves_the_comment_after_it():
    text = f"{DETECTORS}model:\n  path: /x\n{AFTER}"
    deleted = edit(text, None)
    assert deleted == f"{DETECTORS}{AFTER}"
    assert outside_model(deleted, collapse=False) == outside_model(text, collapse=False)
    # an end-of-line comment on the key before stays where it was, at its column
    text = f"detectors:\n  c:\n    type: edgetpu  # the Coral\nmodel:\n  path: /x\n{AFTER}"
    assert edit(text, None) == f"detectors:\n  c:\n    type: edgetpu  # the Coral\n{AFTER}"
    # a key with a scalar value before model, and a model section that ends in a list
    text = f"version: 0.16-0\nmodel:\n  attributes_map:\n    car:\n      - license_plate\n{AFTER}"
    assert edit(text, None) == f"version: 0.16-0\n{AFTER}"


def test_a_replaced_model_section_that_ended_in_a_list_keeps_the_comment_after_it():
    text = (f"{DETECTORS}model:\n  path: /x\n  attributes_map:\n    car:\n      - license_plate\n"
            "\n# ffmpeg settings, keep\nffmpeg:\n  a: 1\n")
    replaced = edit(text, {"path": f"plus://{PLUS_ID}"})
    assert replaced == f"{DETECTORS}model:\n  path: plus://{PLUS_ID}\n\n# ffmpeg settings, keep\nffmpeg:\n  a: 1\n"
    assert outside_model(replaced, collapse=False) == outside_model(text, collapse=False)
    # and the other way: a list in the new section takes the comment
    replaced_back = edit(replaced, {"path": "/x", "attributes_map": {"car": ["license_plate"]}})
    assert replaced_back == text


def test_an_inserted_model_section_goes_before_the_comment_of_the_key_after_it():
    text = f"{DETECTORS}{AFTER}"
    inserted = edit(text, {"path": f"plus://{PLUS_ID}"})
    assert inserted == f"{DETECTORS}\nmodel:\n  path: plus://{PLUS_ID}\n{AFTER}"
    assert outside_model(inserted) == outside_model(text)  # only a blank line before model is new
    assert edit(inserted, None) == text


DETECTOR_MODEL = "detectors:\n  coral:\n    type: edgetpu\n    model:\n      path: /config/model_cache/old.tflite\n"
DETECTOR_MODEL_REFUSAL = (
    "Frigate's config sets a model inside detectors.coral; remove it in Frigate's config editor first.")


def test_a_model_inside_a_detector_is_refused_before_any_write(tmp_path, monkeypatch):
    codedir, config = codedir_with(tmp_path, DETECTOR_MODEL)
    for raw in (DETECTOR_MODEL, None):  # through Frigate, then from the file
        api = FakeFrigateApi(raw)
        monkeypatch.setattr(httpjson, "get", api.get)
        monkeypatch.setattr(httpjson, "post", api.post)
        for section in ({"path": f"plus://{PLUS_ID}"}, None):
            with pytest.raises(UseError) as refused:
                apply(section, codedir)
            assert (refused.value.status, refused.value.code, refused.value.message) == (
                409, "detector_model", DETECTOR_MODEL_REFUSAL)
        assert api.posts == []
    assert config.read_text() == DETECTOR_MODEL and backups(config) == []
    # a detector's model without a path (Frigate's resolved fields only) is no obstacle
    codedir_with(tmp_path / "other", "detectors:\n  coral:\n    type: edgetpu\n    model: {}\n")
    assert apply(None, tmp_path / "other") == "file"


FRIGATE_MESSAGE = (
    f"{FRIGATE_HEADER}\nSee the official documentation at docs.frigate.video.\n\n"
    "Line 18: model -> path - Value error, the model file is missing\n"
    f"  Line 19: model -> width - Input should be a valid integer {PLACEHOLDER_KEY}  \n"
)


def test_refusal_lines_drop_the_header_and_redact():
    lines = refusal_lines(FRIGATE_MESSAGE)
    assert lines == ("Line 18: model -> path - Value error, the model file is missing; "
                     "Line 19: model -> width - Input should be a valid integer <key>")
    assert PLACEHOLDER_KEY not in lines and "docs.frigate.video" not in lines
    long = f"{FRIGATE_HEADER}\nSee the official documentation at docs.frigate.video.\n" + "\n".join(
        f"Line {n}: cameras -> x{n} - {PLACEHOLDER_KEY}" for n in range(40))
    cut = refusal_lines(long)
    assert len(cut) <= 500 and PLACEHOLDER_KEY[:20] not in cut
    # Frigate's other refusals hold a traceback: its last line says what went wrong
    traceback = f"Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: bad {PLACEHOLDER_KEY}\n"
    assert refusal_lines(traceback) == "ValueError: bad <key>"


def test_refusal_lines_show_frigates_html_entities_as_text():
    # Frigate escapes its 400 messages for HTML; the page shows text
    traceback = ("Traceback (most recent call last):\n"
                 "Exception: Unable to refresh API token: {&#34;message&#34;:&#34;User not found&#34;}\n")
    assert refusal_lines(traceback) == 'Exception: Unable to refresh API token: {"message":"User not found"}'
    validation = f"{FRIGATE_HEADER}\nSee the docs.\n\nLine 4: model -> path - Value error, &lt;none&gt; &amp; &#x27;x&#x27;\n"
    assert refusal_lines(validation) == "Line 4: model -> path - Value error, <none> & 'x'"


def test_refusal_lines_redact_a_key_written_as_entities():
    hidden = PLACEHOLDER_KEY.replace(":", "&#58;", 1)
    assert hidden != PLACEHOLDER_KEY
    lines = refusal_lines(f"Traceback (most recent call last):\nException: bad key {hidden}\n")
    assert lines == "Exception: bad key <key>"
    assert PLACEHOLDER_KEY[:20] not in lines and "&#58;" not in lines


class FakeFrigateApi:
    """httpjson.get and httpjson.post as Frigate's /config/raw and /config/save answer them."""

    def __init__(self, raw, save=(200, {"success": True, "message": "Config successfully saved."})):
        self.raw = raw
        self.save = save
        self.posts = []

    def get(self, url, headers=None, timeout=None):
        if url == "http://127.0.0.1:5000/api/config/raw" and self.raw is not None:
            return 200, json.dumps(self.raw).encode()
        return None, None

    def post(self, url, body, content_type, headers=None, timeout=None):
        self.posts.append((url, body, content_type, timeout))
        status, answer = self.save
        return status, None if answer is None else json.dumps(answer).encode()


def codedir_with(tmp_path, text):
    config = tmp_path / "frigate" / "config" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(text)
    return tmp_path, config


def backups(config):
    return sorted(path.name for path in config.parent.glob("config.yml.*.bak"))


def test_apply_saves_through_frigate_when_it_answers(tmp_path, monkeypatch):
    codedir, config = codedir_with(tmp_path, "on disk: unchanged\n")
    api = FakeFrigateApi(CONFIG)
    monkeypatch.setattr(httpjson, "get", api.get)
    monkeypatch.setattr(httpjson, "post", api.post)
    assert apply({"path": f"plus://{PLUS_ID}"}, codedir) == "frigate"
    ((url, body, content_type, timeout),) = api.posts
    assert url == "http://127.0.0.1:5000/api/config/save?save_option=saveonly"
    assert content_type == "text/plain" and timeout == 30
    saved = body.decode()
    assert load(saved)["model"] == {"path": f"plus://{PLUS_ID}"}
    assert outside_model(saved) == outside_model(CONFIG)
    assert config.read_text() == "on disk: unchanged\n" and backups(config) == []


def test_apply_edits_the_file_when_frigate_is_silent(tmp_path, monkeypatch):
    codedir, config = codedir_with(tmp_path, CONFIG)
    api = FakeFrigateApi(None)
    monkeypatch.setattr(httpjson, "get", api.get)
    monkeypatch.setattr(httpjson, "post", api.post)
    assert apply(None, codedir) == "file"
    assert api.posts == []
    assert "model" not in load(config.read_text())
    assert outside_model(config.read_text()) == outside_model(CONFIG)
    (backup,) = backups(config)
    assert (config.parent / backup).read_text() == CONFIG
    with pytest.raises(UseError) as refused:
        apply({"path": "x"}, tmp_path / "nowhere")
    assert (refused.value.status, refused.value.code) == (500, "config_write")
    assert refused.value.message == "Frigate's config.yml couldn't be written: FileNotFoundError"


def test_frigates_refusal_is_shown_and_nothing_is_restarted(tmp_path, monkeypatch):
    codedir, config = codedir_with(tmp_path, CONFIG)
    api = FakeFrigateApi(CONFIG, save=(400, {"success": False, "message": FRIGATE_MESSAGE}))
    monkeypatch.setattr(httpjson, "get", api.get)
    monkeypatch.setattr(httpjson, "post", api.post)
    with pytest.raises(UseError) as refused:
        apply({"path": f"plus://{PLUS_ID}"}, codedir)
    assert (refused.value.status, refused.value.code) == (422, "frigate_refused")
    assert refused.value.message == "Frigate refused the config: " + refusal_lines(FRIGATE_MESSAGE)
    assert PLACEHOLDER_KEY not in refused.value.message
    assert config.read_text() == CONFIG and backups(config) == []
    api.save = (400, None)  # no message to show
    with pytest.raises(UseError) as bare:
        apply({"path": f"plus://{PLUS_ID}"}, codedir)
    assert (bare.value.status, bare.value.message) == (422, "Frigate refused the config.")
    api.save = (500, None)
    with pytest.raises(UseError) as failed:
        apply({"path": f"plus://{PLUS_ID}"}, codedir)
    assert (failed.value.status, failed.value.code, failed.value.message) == (
        502, "frigate_error", "Frigate answered 500 to the save.")
    api.save = (None, None)
    with pytest.raises(UseError) as silent:
        apply({"path": f"plus://{PLUS_ID}"}, codedir)
    assert (silent.value.status, silent.value.code, silent.value.message) == (
        502, "frigate_error", "Frigate didn't answer the save; its config may or may not have changed. Try again.")
    assert config.read_text() == CONFIG and backups(config) == []


def test_check_usable_refuses_the_wrong_detector_an_unknown_one_and_an_incomplete_pair():
    check_usable(plus_model(), "edgetpu")
    with pytest.raises(UseError) as unknown:
        check_usable(plus_model(), None)
    assert (unknown.value.status, unknown.value.code) == (409, "detector_unknown")
    assert unknown.value.message == (
        "Frigate's detector type can't be determined, so a model can't be checked against it.")
    with pytest.raises(UseError) as wrong:
        check_usable(local_model(supportedDetectors=["hailo8l", "rknn"]), "edgetpu")
    assert (wrong.value.status, wrong.value.code) == (422, "wrong_detector")
    assert wrong.value.message == "This model is built for hailo8l, rknn; this device detects with edgetpu."
    bare = Model("bare.tflite", "local", None, (ModelFile("bare.tflite", 1, "d" * 64),), False, None)
    with pytest.raises(UseError) as incomplete:
        check_usable(bare, "edgetpu")
    assert (incomplete.value.status, incomplete.value.code, incomplete.value.message) == (
        422, "incomplete", "This model is missing its sidecar.")
    with pytest.raises(UseError) as no_file:
        check_usable(local_model(complete=False), "edgetpu")
    assert (no_file.value.status, no_file.value.code) == (422, "incomplete")
    assert no_file.value.message == "This model's file is missing or can't be read."


class SilentSaveApi(FakeFrigateApi):
    """A Frigate that writes the file but doesn't answer the save in time: /config/raw then shows the saved text."""

    def __init__(self, raw, writes: bool):
        super().__init__(raw)
        self.writes = writes

    def post(self, url, body, content_type, headers=None, timeout=None):
        self.posts.append((url, body, content_type, timeout))
        if self.writes:
            self.raw = body.decode()
        return None, None


def test_a_save_frigate_wrote_but_did_not_answer_counts_as_saved(tmp_path, monkeypatch):
    codedir, config = codedir_with(tmp_path, "on disk: unchanged\n")
    api = SilentSaveApi(CONFIG, writes=True)
    monkeypatch.setattr(httpjson, "get", api.get)
    monkeypatch.setattr(httpjson, "post", api.post)
    assert apply({"path": f"plus://{PLUS_ID}"}, codedir) == "frigate"
    assert len(api.posts) == 1 and config.read_text() == "on disk: unchanged\n"


def test_a_save_frigate_neither_wrote_nor_answered_is_a_502_that_says_so(tmp_path, monkeypatch):
    codedir, config = codedir_with(tmp_path, "on disk: unchanged\n")
    api = SilentSaveApi(CONFIG, writes=False)
    monkeypatch.setattr(httpjson, "get", api.get)
    monkeypatch.setattr(httpjson, "post", api.post)
    with pytest.raises(UseError) as refused:
        apply({"path": f"plus://{PLUS_ID}"}, codedir)
    assert (refused.value.status, refused.value.code) == (502, "frigate_error")
    assert refused.value.message == "Frigate didn't answer the save; its config may or may not have changed. Try again."
    assert config.read_text() == "on disk: unchanged\n" and backups(config) == []
