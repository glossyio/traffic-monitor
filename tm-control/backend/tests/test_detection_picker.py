"""The detection module's reading of Frigate: the detector, the model that runs, and the label lists."""

from pathlib import Path

import pytest

from tm_control.adapters.yamlfile import ConfigRead
from tm_control.modules.detection.inventory import InstallerDefault, Model, ModelFile, parse_sidecar
from tm_control.modules.detection.labels import recognised, tracked
from tm_control.modules.detection.picker import Running, detector_type, running_model

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
