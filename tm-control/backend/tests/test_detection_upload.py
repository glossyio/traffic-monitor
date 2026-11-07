"""upload.py: what an upload is by its name, writing a body through a temporary name, and the free-space floor.

The stream is an async generator of chunks, as Starlette's request.stream() is; each test runs it with asyncio.run.
"""

import asyncio
import os
from collections import namedtuple

import pytest

from tm_control.modules.detection import upload
from tm_control.modules.detection.inventory import MODEL_FILE_MAX, SIDECAR_MAX, open_cache
from tm_control.modules.system.checks import STORAGE_ERROR


def chunks(*parts: bytes):
    async def stream():
        for part in parts:
            yield part

    return stream()


@pytest.fixture
def cache(tmp_path):
    path = tmp_path / "model_cache"
    path.mkdir()
    fd = open_cache(path)
    yield path, fd
    os.close(fd)


def run_receive(fd, stream, limit=MODEL_FILE_MAX, declared=None, temp=".upload-00000000-m.tflite"):
    return asyncio.run(upload.receive(stream, fd, temp, limit, declared))


def test_kind_of_upload_by_name():
    assert upload.kind_of_upload("m.zip") == "archive"
    assert upload.kind_of_upload("m.tar.gz") == "archive"
    assert upload.kind_of_upload("m.tgz") == "archive"
    assert upload.kind_of_upload("m.tflite.json") == "sidecar"
    assert upload.kind_of_upload("0123456789abcdef0123456789abcdef.json") == "sidecar"
    assert upload.kind_of_upload("m.tflite") == "model"
    assert upload.kind_of_upload("0123456789abcdef0123456789abcdef") == "model"
    assert upload.kind_of_upload("m.gz") == "model"  # only .tar.gz and .tgz are tar archives
    assert upload.MAGIC == {"zip": b"PK\x03\x04", "gzip": b"\x1f\x8b"}


def test_temp_names_are_hidden_unique_and_cut_to_200_characters():
    first, second = upload.temp_name("m.tflite"), upload.temp_name("m.tflite")
    assert first.startswith(".upload-") and first.endswith("-m.tflite")
    assert len(first) == len(".upload-12345678-m.tflite")
    assert first != second
    assert len(upload.temp_name("a" * 300)) == 200  # longer than any valid name, so it never cuts one today


def test_receive_writes_exactly_the_body_and_fsyncs(cache, monkeypatch):
    path, fd = cache
    synced = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda target: (synced.append(target), real_fsync(target))[1])
    size = run_receive(fd, chunks(b"abc", b"", b"defg"), declared=7)
    assert size == 7
    assert (path / ".upload-00000000-m.tflite").read_bytes() == b"abcdefg"
    assert oct((path / ".upload-00000000-m.tflite").stat().st_mode & 0o777) == oct(0o644 & ~current_umask())
    assert len(synced) == 1


def current_umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


def test_receive_refuses_an_existing_temporary_name_and_a_link(cache):
    path, fd = cache
    (path / ".upload-00000000-m.tflite").write_bytes(b"other")
    with pytest.raises(FileExistsError):
        run_receive(fd, chunks(b"abc"))
    assert (path / ".upload-00000000-m.tflite").read_bytes() == b"other"  # an O_EXCL refusal removes nothing
    (path / ".link").symlink_to(path.parent / "elsewhere")
    with pytest.raises(FileExistsError):
        run_receive(fd, chunks(b"abc"), temp=".link")
    assert not (path.parent / "elsewhere").exists()


def test_a_body_over_the_cap_is_cut_off_and_leaves_nothing(cache):
    path, fd = cache
    with pytest.raises(upload.UploadError) as raised:
        run_receive(fd, chunks(b"12345", b"678901"), limit=10)
    assert raised.value.status == 413
    assert os.listdir(path) == []
    with pytest.raises(upload.UploadError) as raised:
        run_receive(fd, chunks(b"x" * (SIDECAR_MAX + 1)), limit=SIDECAR_MAX)
    assert (raised.value.status, raised.value.message) == (413, "The sidecar is larger than 2 MB.")
    with pytest.raises(upload.UploadError) as raised:
        run_receive(fd, chunks(b"x" * 11), limit=10)
    assert raised.value.message == "The file is larger than 100 MB."
    assert os.listdir(path) == []
    assert run_receive(fd, chunks(b"x" * 10), limit=10) == 10  # exactly the cap is accepted


def test_a_body_shorter_than_content_length_leaves_nothing(cache):
    path, fd = cache
    with pytest.raises(upload.UploadError) as raised:
        run_receive(fd, chunks(b"abc"), declared=4)
    assert (raised.value.status, raised.value.message) == (400, "The body ended before Content-Length.")
    assert os.listdir(path) == []


def test_a_stream_that_fails_partway_leaves_nothing(cache):
    path, fd = cache

    async def broken():
        yield b"abc"
        raise ConnectionResetError

    with pytest.raises(ConnectionResetError):
        run_receive(fd, broken())
    assert os.listdir(path) == []


def test_place_gives_the_name_without_replacing(cache):
    path, fd = cache
    (path / ".t").write_bytes(b"new")
    upload.place(fd, ".t", "m.tflite")
    assert sorted(os.listdir(path)) == ["m.tflite"]
    (path / ".t").write_bytes(b"newer")
    with pytest.raises(upload.UploadError) as raised:
        upload.place(fd, ".t", "m.tflite")
    assert raised.value.status == 409
    assert (path / "m.tflite").read_bytes() == b"new"


Statvfs = namedtuple("Statvfs", "f_frsize f_bavail")


def test_free_space_floor(cache, monkeypatch):
    path, _ = cache
    assert upload.FREE_SPACE_MIN == STORAGE_ERROR == 512 * 1024 * 1024
    asked = []

    def statvfs(target):
        asked.append(target)
        return Statvfs(4096, (upload.FREE_SPACE_MIN + 1000) // 4096)

    monkeypatch.setattr(os, "statvfs", statvfs)
    free = (upload.FREE_SPACE_MIN + 1000) // 4096 * 4096
    assert upload.free_space_ok(path, free - upload.FREE_SPACE_MIN) is True
    assert upload.free_space_ok(path, free - upload.FREE_SPACE_MIN + 1) is False
    assert asked == [path, path]
    monkeypatch.setattr(os, "statvfs", lambda target: (_ for _ in ()).throw(OSError("no such file system")))
    assert upload.free_space_ok(path, 1) is False


def test_upload_errors_carry_the_fixed_messages():
    assert upload.BAD_NAME == "That name isn't allowed."
    exists = upload.exists("m.tflite")
    assert (exists.status, exists.message) == (409, "A model named m.tflite is already on the device; delete it first.")
    assert upload.NO_SPACE == "The device would have less than 512 MB free."
