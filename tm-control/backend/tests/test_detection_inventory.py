"""The detection module's inventory of Frigate's model_cache: names, sidecars, hashes, and which files make a model."""

import copy
import dataclasses
import hashlib
import json
import os
import threading
from pathlib import Path

import pytest

from tm_control.core.manifest import FrigateInfo, load_manifest
from tm_control.modules.detection import inventory as inv
from tm_control.modules.detection.inventory import (
    SIDECAR_MAX, InstallerDefault, SidecarError, host_path, installer_default, inventory, kind_of, parse_sidecar,
    sha256_in, valid_name,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "model_sidecar.json"
SIDECAR = FIXTURE.read_bytes()
PLUS_ID = "0123456789abcdef0123456789abcdef"
INSTALLER_FILE = "installer_int8_edgetpu.tflite"


@pytest.fixture
def manifest():
    return load_manifest(Path(__file__).resolve().parent / "fixtures" / "manifest.json")


@pytest.fixture
def cache(tmp_path):
    path = tmp_path / "model_cache"
    path.mkdir()
    return path


def pair(cache, name, sidecar=SIDECAR, size=4096):
    (cache / name).write_bytes(bytes(size))
    (cache / f"{name}.json").write_bytes(sidecar)


def installer(cache):
    return InstallerDefault(section={"path": f"/config/model_cache/{INSTALLER_FILE}"}, file=INSTALLER_FILE,
                            labels_file=None)


def with_(**changes):
    document = json.loads(SIDECAR)
    for key, value in changes.items():
        if value is ...:
            document.pop(key)
        else:
            document[key] = value
    return json.dumps(document).encode()


def by_name(models):
    return {model.name: model for model in models}


def test_valid_names():
    for name in ("a", "x.tflite", PLUS_ID, "A-b_c.1", "a" * 128):
        assert valid_name(name), name
    for name in (".hidden", "a.json", "..", ".", "a/b", "a" * 129, "", "-a", "a b", "a\n", "é.tflite", "a.json.json"):
        assert not valid_name(name), repr(name)


def test_parse_sidecar_keeps_the_eight_fields_and_drops_the_rest():
    sidecar = parse_sidecar(SIDECAR)
    assert sidecar == inv.Sidecar(
        id=PLUS_ID, name="Test site yolov9", trained_at="2026-10-01T12:00:00Z", type="yolo-generic",
        detectors=("edgetpu",), width=320, height=320, input_shape="nhwc", pixel_format="rgb", input_dtype=None,
        labels=("person", "bicycle", "car"),
    )
    assert not hasattr(sidecar, "verifiedCounts") and not hasattr(sidecar, "verified_counts")
    assert "verifiedCounts" not in {field.name for field in dataclasses.fields(sidecar)}
    assert "front_door_cam" not in repr(sidecar)


def test_parse_sidecar_orders_labels_by_index_and_reads_the_data_type():
    sidecar = parse_sidecar(with_(labelMap={"10": "k", "2": "c", "0": "a"}, inputDataType="int", id=3, name=None))
    assert sidecar.labels == ("a", "c", "k")
    assert sidecar.input_dtype == "int"
    assert sidecar.id is None and sidecar.name is None  # not strings: the optional descriptive fields drop out


@pytest.mark.parametrize("data, message", [
    *[(with_(**{field: ...}), f"The sidecar lacks {field}.") for field in
      ("type", "supportedDetectors", "width", "height", "inputShape", "pixelFormat", "labelMap")],
    *[(with_(**{field: value}), f"The sidecar's {field} has the wrong type.") for field, value in (
        ("type", 3), ("supportedDetectors", "edgetpu"), ("supportedDetectors", [1]), ("width", "320"),
        ("width", 3.5), ("width", True), ("height", None), ("inputShape", ["nhwc"]), ("pixelFormat", 1),
        ("labelMap", ["person"]), ("labelMap", {"0": 1}), ("inputDataType", 5))],
    (with_(supportedDetectors=[]), "The sidecar's supportedDetectors is empty."),
    (with_(labelMap={"a": "x"}), "The sidecar's labelMap keys must be decimal strings."),
    (with_(labelMap={"-1": "x"}), "The sidecar's labelMap keys must be decimal strings."),
    (with_(labelMap={"1": "x", "01": "y"}), "The sidecar's labelMap keys must be decimal strings."),
    (b"[]", "The sidecar isn't a JSON object."),
    (b"{", "The sidecar isn't a JSON object."),
    (b"\xff\xfe", "The sidecar isn't a JSON object."),
    (b"[" * 100000, "The sidecar isn't a JSON object."),
])
def test_parse_sidecar_refuses_each_missing_or_mistyped_field(data, message):
    with pytest.raises(SidecarError) as raised:
        parse_sidecar(data)
    assert str(raised.value) == message


def test_a_frigate_plus_pair_is_told_from_a_local_model_by_the_id():
    sidecar = parse_sidecar(SIDECAR)
    assert kind_of(PLUS_ID, sidecar) == "frigate_plus"
    assert kind_of("mine.tflite", sidecar) == "local"
    assert kind_of(PLUS_ID, parse_sidecar(with_(id="x"))) == "local"
    assert kind_of(PLUS_ID, None) == "local"


def test_inventory_lists_pairs_halves_and_the_installers_default(cache):
    pair(cache, PLUS_ID)
    pair(cache, "mine.tflite")
    (cache / "bare.tflite").write_bytes(bytes(10))
    (cache / "lonely.tflite.json").write_bytes(SIDECAR)
    (cache / INSTALLER_FILE).write_bytes(bytes(1024))
    models = inventory(cache, installer(cache))
    assert [model.name for model in models] == [INSTALLER_FILE, PLUS_ID, "bare.tflite", "lonely.tflite", "mine.tflite"]
    found = by_name(models)
    default = found[INSTALLER_FILE]
    assert (default.kind, default.sidecar, default.complete, default.problem) == ("installer_default", None, True, None)
    assert [(file.name, file.size) for file in default.files] == [(INSTALLER_FILE, 1024)]
    assert (found[PLUS_ID].kind, found[PLUS_ID].complete) == ("frigate_plus", True)
    assert found[PLUS_ID].sidecar.id == PLUS_ID
    assert [(file.name, file.size) for file in found[PLUS_ID].files] == [
        (PLUS_ID, 4096), (f"{PLUS_ID}.json", len(SIDECAR))]
    assert (found["mine.tflite"].kind, found["mine.tflite"].complete) == ("local", True)
    bare = found["bare.tflite"]
    assert (bare.complete, bare.sidecar, bare.problem) == (False, None, None)
    assert found["bare.tflite"].files[0].size == 10
    lonely = found["lonely.tflite"]
    assert not lonely.complete and [file.name for file in lonely.files] == ["lonely.tflite.json"]
    # every regular file listed carries its hash
    assert default.files[0].sha256 == hashlib.sha256(bytes(1024)).hexdigest()
    assert found[PLUS_ID].files[0].sha256 == hashlib.sha256(bytes(4096)).hexdigest()
    assert found[PLUS_ID].files[1].sha256 == hashlib.sha256(SIDECAR).hexdigest()
    assert lonely.files[0].sha256 == hashlib.sha256(SIDECAR).hexdigest()


def test_the_installers_file_is_not_listed_twice(cache):
    pair(cache, INSTALLER_FILE)
    assert [model.name for model in inventory(cache, installer(cache))] == [INSTALLER_FILE]
    assert inventory(cache, installer(cache))[0].kind == "installer_default"
    assert [model.kind for model in inventory(cache, None)] == ["local"]


def test_subdirectories_symlinks_and_bad_names_are_skipped(cache):
    pair(cache, "good.tflite")
    (cache / "hailo").mkdir()
    (cache / "link.tflite").symlink_to(cache / "good.tflite")
    (cache / "link.tflite.json").symlink_to(cache / "good.tflite.json")
    (cache / ".DS_Store").write_bytes(b"x")
    (cache / ("n" * 200)).write_bytes(b"x")
    (cache / ".json").write_bytes(SIDECAR)
    (cache / "a.json.json").write_bytes(SIDECAR)
    assert [model.name for model in inventory(cache, None)] == ["good.tflite"]


def test_one_bad_file_does_not_blank_the_inventory(cache, monkeypatch):
    pair(cache, "good.tflite")
    pair(cache, "bad.tflite", sidecar=b"{")
    (cache / "dangling.tflite").symlink_to(cache / "nowhere")
    (cache / "dangling.tflite.json").symlink_to(cache / "nowhere.json")
    (cache / ("w" * 255)).write_bytes(b"x")  # as long as a name can be, and not a valid one
    os.mkfifo(cache / "fifo.tflite")
    os.mkfifo(cache / "fifo2.tflite.json")
    pair(cache, "huge.tflite", sidecar=b" " * (SIDECAR_MAX + 1))
    pair(cache, "locked.tflite")  # a full pair, but the model file can't be opened
    unreadable = cache / "locked.tflite"
    unreadable.chmod(0)
    real_listdir = os.listdir
    monkeypatch.setattr(os, "listdir", lambda fd: [*real_listdir(fd), "c" * 300, "c" * 300 + ".json"])
    try:
        models = by_name(inventory(cache, None))
    finally:
        unreadable.chmod(0o600)
    assert models["good.tflite"].complete and models["good.tflite"].problem is None
    assert not models["bad.tflite"].complete and models["bad.tflite"].sidecar is None
    assert models["bad.tflite"].problem == "The sidecar isn't a JSON object."
    assert not models["huge.tflite"].complete and "too large" in models["huge.tflite"].problem
    assert [file.sha256 for file in models["huge.tflite"].files][1] is None  # an oversized sidecar isn't hashed
    for name in ("dangling.tflite", "fifo.tflite", "fifo2.tflite", "w" * 255, "c" * 300):
        assert name not in models, name
    assert set(models) <= {"good.tflite", "bad.tflite", "huge.tflite", "locked.tflite"}
    if os.geteuid() != 0:
        assert models["locked.tflite"].problem == "The file can't be read."
        assert models["locked.tflite"].files[0].sha256 is None
        assert not models["locked.tflite"].complete
        assert models["locked.tflite"].sidecar is not None  # its sidecar still parsed
    assert models["good.tflite"].files[0].sha256 == hashlib.sha256(bytes(4096)).hexdigest()


def test_an_unreadable_sidecar_makes_the_entry_incomplete(cache):
    if os.geteuid() == 0:
        pytest.skip("root reads a mode 000 file")
    pair(cache, "locked.tflite")
    (cache / "locked.tflite.json").chmod(0)
    model = by_name(inventory(cache, None))["locked.tflite"]
    assert not model.complete and model.problem == "The sidecar can't be read."


def test_a_missing_or_linked_cache_directory_lists_nothing(tmp_path):
    (tmp_path / "file").write_bytes(b"x")
    (tmp_path / "link").symlink_to(tmp_path)
    for path in (tmp_path / "nope", tmp_path / "file", tmp_path / "link"):
        assert inventory(path, None) == []
        assert inventory(path, installer(tmp_path)) == []


def test_the_installers_default_is_listed_only_when_its_file_is_a_regular_file(cache):
    assert inventory(cache, installer(cache)) == []  # no file
    (cache / "elsewhere").write_bytes(b"x")
    (cache / INSTALLER_FILE).symlink_to(cache / "elsewhere")
    assert [model.name for model in inventory(cache, installer(cache))] == ["elsewhere"]  # a link isn't the file
    (cache / INSTALLER_FILE).unlink()
    (cache / INSTALLER_FILE).mkdir()
    assert [model.name for model in inventory(cache, installer(cache))] == ["elsewhere"]


def test_an_unreadable_installer_file_is_listed_incomplete(cache):
    if os.geteuid() == 0:
        pytest.skip("root reads a mode 000 file")
    (cache / INSTALLER_FILE).write_bytes(bytes(8))
    (cache / INSTALLER_FILE).chmod(0)
    model = inventory(cache, installer(cache))[0]
    assert (model.kind, model.complete, model.problem) == ("installer_default", False, "The file can't be read.")
    assert model.files[0].sha256 is None


def test_an_oversized_sidecar_is_never_read_past_the_cap(cache, monkeypatch):
    (cache / "huge.tflite.json").write_bytes(b" " * (4 * SIDECAR_MAX))
    asked, got = [], []
    real = os.read

    def counting(fd, count):
        asked.append(count)
        block = real(fd, count)
        got.append(len(block))
        return block

    monkeypatch.setattr(inv.os, "read", counting)
    model = by_name(inventory(cache, None))["huge.tflite"]
    assert model.problem == "The sidecar is too large." and not model.complete
    assert model.files[0].sha256 is None
    assert max(asked) <= SIDECAR_MAX + 1 and sum(got) == SIDECAR_MAX + 1


def test_the_sidecar_is_read_once_and_hashed_from_the_bytes_that_were_parsed(cache, monkeypatch):
    inv.HASHES.clear()
    pair(cache, "a.tflite")
    reads = []
    real = inv.open_in
    monkeypatch.setattr(inv, "open_in", lambda *args, **kwargs: reads.append(args[1]) or real(*args, **kwargs))
    model = by_name(inventory(cache, None))["a.tflite"]
    assert reads.count("a.tflite.json") == 1
    assert model.files[1].sha256 == hashlib.sha256(SIDECAR).hexdigest()
    assert model.files[1].size == len(SIDECAR)


def test_hashes_are_cached_by_name_size_and_mtime(cache, monkeypatch):
    inv.HASHES.clear()
    pair(cache, "a.tflite", size=3_000_000)
    expected = hashlib.sha256(bytes(3_000_000)).hexdigest()
    opened = []
    real = inv.open_in
    monkeypatch.setattr(inv, "open_in", lambda *args, **kwargs: opened.append(args[1]) or real(*args, **kwargs))

    def listed():
        opened.clear()
        return by_name(inventory(cache, None))["a.tflite"].files[0]

    assert listed().sha256 == expected
    assert opened.count("a.tflite") == 1
    assert listed().sha256 == expected  # same name, size, and mtime: not read again
    assert opened.count("a.tflite") == 0
    first = os.stat(cache / "a.tflite")
    os.utime(cache / "a.tflite", ns=(1, first.st_mtime_ns + 1_000_000_000))
    assert listed().sha256 == expected  # touched: read again
    assert opened.count("a.tflite") == 1
    assert len([key for key in inv.HASHES if key[0] == "a.tflite"]) == 1  # the stale key is dropped
    (cache / "a.tflite").write_bytes(b"changed")
    assert listed().sha256 == hashlib.sha256(b"changed").hexdigest()  # a new size: read again
    assert opened.count("a.tflite") == 1


def test_the_hash_is_of_the_file_that_was_read(cache):
    inv.HASHES.clear()
    pair(cache, "a.tflite", size=10)
    fd = inv.open_cache(cache)
    try:
        stale = inv.stat_in(fd, "a.tflite")
        (cache / "a.tflite").write_bytes(b"x" * 20)
        os.utime(cache / "a.tflite", ns=(1, stale.st_mtime_ns + 5))
        sha256_in(fd, "a.tflite", stale)
        assert ("a.tflite", 10, stale.st_mtime_ns) not in inv.HASHES  # keyed by what the open file is
        assert any(key[:2] == ("a.tflite", 20) for key in inv.HASHES)
    finally:
        os.close(fd)


def test_the_helpers_open_relative_to_the_directory_and_never_follow_links(cache, prompt):
    (cache / "real").write_bytes(b"x")
    (cache / "link").symlink_to(cache / "real")
    os.mkfifo(cache / "fifo")
    fd = inv.open_cache(cache)
    try:
        assert inv.stat_in(fd, "missing") is None
        assert inv.stat_in(fd, "link").st_mode & 0o170000 == 0o120000  # the link itself
        with pytest.raises(OSError):
            inv.open_in(fd, "link", os.O_RDONLY)
        os.close(inv.open_in(fd, "fifo", os.O_RDONLY))  # doesn't block without a writer
        os.close(inv.open_in(fd, "real", os.O_RDONLY))
    finally:
        os.close(fd)
    with pytest.raises(OSError):
        inv.open_cache(cache / "link")
    (cache.parent / "elsewhere").symlink_to(cache)
    with pytest.raises(OSError):
        inv.open_cache(cache.parent / "elsewhere")


def test_host_path_stays_under_frigates_config():
    codedir = Path("/opt/traffic-monitor")
    assert host_path(codedir, "/config/labels-coco17.txt") == codedir / "frigate/config/labels-coco17.txt"
    assert host_path(codedir, "/config/model_cache/x.txt") == codedir / "frigate/config/model_cache/x.txt"
    assert host_path("/opt/traffic-monitor", "/config/a") == codedir / "frigate/config/a"
    for bad in ("/config//etc/passwd", "/config/a//b", "/config/./x", "/config/a/", "/config/../x",
                "/config/a/../../x", "/etc/x", "/configs/x", "config/x", "/config/", "/config", "",
                "/config/a\0b", None, 3):
        assert host_path(codedir, bad) is None, bad
    assert host_path(codedir, "/config/a..b") is not None


def test_installer_default_comes_from_the_manifests_coral_section(manifest):
    chosen = installer_default(manifest, "/opt/traffic-monitor")
    assert chosen.file == "yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite"
    assert chosen.section == manifest.frigate.coral_model
    assert chosen.labels_file == Path("/opt/traffic-monitor/frigate/config/labels-coco17.txt")
    without = copy.deepcopy(manifest)
    without.frigate = FrigateInfo()
    assert installer_default(without, "/opt/traffic-monitor") is None
    odd = copy.deepcopy(manifest)
    odd.frigate = FrigateInfo(coral_model={"path": "/config/model_cache/m.tflite", "labelmap_path": "/etc/passwd"})
    assert installer_default(odd, "/opt/traffic-monitor").labels_file is None
    odd.frigate = FrigateInfo(coral_model={"path": "/config/model_cache/m.tflite"})
    assert installer_default(odd, "/opt/traffic-monitor").labels_file is None


def test_model_cache_dir_is_under_frigates_config_or_beside_the_fake_state(settings, manifest):
    assert settings.fake
    assert inv.model_cache_dir(settings, manifest) == settings.state_dir.parent / "model_cache"
    real = dataclasses.replace(settings, fake=False)
    assert inv.model_cache_dir(real, manifest) == Path("/opt/traffic-monitor/frigate/config/model_cache")


def test_hashing_from_two_threads_is_safe(cache):
    inv.HASHES.clear()
    pair(cache, "a.tflite", size=100_000)
    fd = inv.open_cache(cache)
    errors = []

    def work():
        try:
            for _ in range(20):
                sha256_in(fd, "a.tflite", inv.stat_in(fd, "a.tflite"))
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    os.close(fd)
    assert errors == []


def test_forget_drops_the_hashes_of_removed_names():
    from tm_control.modules.detection import inventory as module

    module.HASHES[("gone.tflite", 1, 1)] = "a"
    module.HASHES[("kept.tflite", 1, 1)] = "b"
    module.forget(["gone.tflite", "never.tflite"])
    assert ("gone.tflite", 1, 1) not in module.HASHES and module.HASHES[("kept.tflite", 1, 1)] == "b"
    del module.HASHES[("kept.tflite", 1, 1)]
