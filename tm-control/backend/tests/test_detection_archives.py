"""archives.py and package.py: a model and its sidecar in a zip or tar.gz, unpacked into model_cache, and the zip a
model is packaged in for download.

Hostile archives are built here with zipfile and tarfile directly. Every refusal also checks that the directory is
as it was, with no temporary name left.
"""

import gzip
import hashlib
import io
import os
import stat
import struct
import tarfile
import time
import zipfile
from pathlib import Path

import pytest

from tm_control.modules.detection import archives, package, upload
from tm_control.modules.detection.inventory import MODEL_FILE_MAX, SIDECAR_MAX, open_cache
from tm_control.modules.detection.upload import UploadError

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SIDECAR = (FIXTURES / "model_sidecar.json").read_bytes()
MODEL = bytes(range(256)) * 16
PAIR = {"m.tflite": MODEL, "m.tflite.json": SIDECAR}

NO_PAIR = "The archive has no model file and sidecar pair."
TOO_MANY = "The archive holds more than a model, its sidecar, and SHA256SUMS."
NOT_PLAIN = "An archive member has a path, or isn't a plain file."
TOO_LARGE = "An archive member is larger than its cap."
MISMATCH = "SHA256SUMS doesn't match the files."
UNREADABLE = "The archive can't be read."


@pytest.fixture
def cache(tmp_path):
    path = tmp_path / "model_cache"
    path.mkdir()
    fd = open_cache(path)
    yield path, fd
    os.close(fd)


def names(path: Path) -> list[str]:
    return sorted(entry.name for entry in path.iterdir())


def sums(files: dict[str, bytes], star=False) -> bytes:
    marker = "*" if star else " "
    return "".join(f"{hashlib.sha256(data).hexdigest()} {marker}{name}\n" for name, data in files.items()).encode()


def make_zip(files: dict[str, bytes], infos=()) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
        for info, data in infos:
            zf.writestr(info, data)
    return out.getvalue()


def make_tgz(files: dict[str, bytes], infos=()) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for info, data in infos:
            if data is None:
                header_only(tar, info)
            else:
                tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def header_only(tar, info):
    """A member's header with nothing behind it, so a header can claim a size no data backs."""
    header = info.tobuf(tar.format, tar.encoding, tar.errors)
    tar.fileobj.write(header)
    tar.offset += len(header)


MAKERS = {"zip": make_zip, "gzip": make_tgz}


def stage(cache, data: bytes) -> str:
    """The archive under a temporary name in the cache, as the upload route leaves it."""
    path, fd = cache
    temp = upload.temp_name("m.zip")
    (path / temp).write_bytes(data)
    return temp


def extract(cache, data: bytes, kind):
    path, fd = cache
    with io.BytesIO(data) as file:
        return archives.extract(file, kind, fd)


def refused(cache, data: bytes, kind) -> str:
    path, fd = cache
    before = names(path)
    temp = stage(cache, data)
    with pytest.raises(UploadError) as raised:
        archives.place_archive(fd, temp, kind)
    assert names(path) == before  # nothing placed, the archive and every member's temporary name removed
    return raised.value.message


@pytest.mark.parametrize("kind", ["zip", "gzip"])
def test_a_zip_or_tgz_with_a_pair_is_placed_as_a_pair(cache, kind):
    path, fd = cache
    temp = stage(cache, MAKERS[kind](PAIR))
    assert archives.place_archive(fd, temp, kind) == "m.tflite"
    assert names(path) == ["m.tflite", "m.tflite.json"]
    assert (path / "m.tflite").read_bytes() == MODEL and (path / "m.tflite.json").read_bytes() == SIDECAR
    assert stat.S_IMODE((path / "m.tflite").stat().st_mode) == 0o644
    assert extract(cache, MAKERS[kind]({"n.tflite": b"\x01", "n.tflite.json": SIDECAR}), kind) == (
        "n.tflite", "n.tflite.json", False)


@pytest.mark.parametrize("kind", ["zip", "gzip"])
def test_sums_are_checked_in_either_sha256sum_form(cache, kind):
    assert extract(cache, MAKERS[kind](PAIR | {"SHA256SUMS": sums(PAIR)}), kind) == ("m.tflite", "m.tflite.json", True)
    other = {"o.tflite": MODEL, "o.tflite.json": SIDECAR}
    assert extract(cache, MAKERS[kind](other | {"SHA256SUMS": sums(other, star=True)}), kind)[2] is True


def test_a_package_from_write_package_round_trips_with_sums_checked(cache, tmp_path):
    path, fd = cache
    (path / "m.tflite").write_bytes(MODEL)
    (path / "m.tflite.json").write_bytes(SIDECAR)
    os.utime(path / "m.tflite", (1_700_000_000, 1_700_000_000))
    out = io.BytesIO()
    package.write_package(fd, "m.tflite", out)
    with zipfile.ZipFile(io.BytesIO(out.getvalue())) as zf:
        assert zf.namelist() == ["m.tflite", "m.tflite.json", "SHA256SUMS"]
        assert all(info.compress_type == zipfile.ZIP_STORED for info in zf.infolist())
        assert zf.read("SHA256SUMS") == sums(PAIR)
        assert zf.getinfo("m.tflite").date_time == time.localtime(1_700_000_000)[:6]
    second = tmp_path / "second"
    second.mkdir()
    second_fd = open_cache(second)
    try:
        with io.BytesIO(out.getvalue()) as file:
            assert archives.extract(file, "zip", second_fd) == ("m.tflite", "m.tflite.json", True)
    finally:
        os.close(second_fd)
    assert (second / "m.tflite").read_bytes() == MODEL and (second / "m.tflite.json").read_bytes() == SIDECAR
    assert names(second) == ["m.tflite", "m.tflite.json"]


def test_write_package_reads_only_regular_files(cache):
    path, fd = cache
    (path / "m.tflite.json").write_bytes(SIDECAR)
    (path / "target").write_bytes(MODEL)
    (path / "m.tflite").symlink_to(path / "target")
    with pytest.raises(OSError):
        package.write_package(fd, "m.tflite", io.BytesIO())


@pytest.mark.parametrize("kind", ["zip", "gzip"])
def test_a_wrong_sum_is_refused_and_nothing_is_placed(cache, kind):
    wrong = sums({"m.tflite": b"other", "m.tflite.json": SIDECAR})
    for listing in (wrong, sums({"m.tflite": MODEL}), sums(PAIR) + sums({"x": b"x"}), b"not a sums file\n",
                    sums(PAIR).replace(b"  ", b" "), b"\xff" * 10):
        assert refused(cache, MAKERS[kind](PAIR | {"SHA256SUMS": listing}), kind) == MISMATCH


def tar_info(name, kind=tarfile.REGTYPE, size=0, **fields):
    info = tarfile.TarInfo(name)
    info.type = kind
    info.size = size
    for field, value in fields.items():
        setattr(info, field, value)
    return info


def zip_info(name, mode):
    info = zipfile.ZipInfo(name)
    info.external_attr = mode << 16
    return info


def test_archive_members_with_paths_links_or_devices_are_refused(cache):
    for kind in ("zip", "gzip"):
        for name in ("../m.tflite", "sub/m.tflite", "/m.tflite", "..\\m.tflite", "sub\\m.tflite.json"):
            files = {"m.tflite": MODEL, "m.tflite.json": SIDECAR} | {name: MODEL}
            files.pop(name.replace("\\", "/").rsplit("/", 1)[-1], None)
            assert refused(cache, MAKERS[kind](files), kind) == NOT_PLAIN, (kind, name)
    hostile = [
        tar_info("m.tflite", tarfile.SYMTYPE, linkname="/etc/passwd"),
        tar_info("m.tflite", tarfile.LNKTYPE, linkname="m.tflite.json"),
        tar_info("m.tflite", tarfile.CHRTYPE, devmajor=1, devminor=3),
        tar_info("m.tflite", tarfile.BLKTYPE, devmajor=8, devminor=0),
        tar_info("m.tflite", tarfile.FIFOTYPE),
    ]
    for info in hostile:
        data = make_tgz({"m.tflite.json": SIDECAR}, [(info, None)])
        assert refused(cache, data, "gzip") == NOT_PLAIN, info.type
    for mode in (stat.S_IFLNK | 0o777, stat.S_IFCHR | 0o644, stat.S_IFIFO | 0o644, stat.S_IFSOCK | 0o644):
        data = make_zip({"m.tflite.json": SIDECAR}, [(zip_info("m.tflite", mode), b"/etc/passwd")])
        assert refused(cache, data, "zip") == NOT_PLAIN, oct(mode)
    plain = make_zip({"m.tflite.json": SIDECAR}, [(zip_info("m.tflite", stat.S_IFREG | 0o600), MODEL)])
    assert extract(cache, plain, "zip")[0] == "m.tflite"


def test_bad_names_are_refused_as_upload_names_are(cache):
    for kind in ("zip", "gzip"):
        for name in ("-m.tflite", "m tflite", "é.tflite", "x" * 129):
            data = MAKERS[kind]({name: MODEL, name + ".json": SIDECAR})
            assert refused(cache, data, kind) == "That name isn't allowed.", (kind, name)


@pytest.mark.parametrize("kind", ["zip", "gzip"])
def test_dot_files_macosx_and_directories_are_ignored(cache, kind):
    extra = {".DS_Store": b"x", "._m.tflite": b"x", "__MACOSX/._m.tflite": b"x", "__MACOSX/sub/x": b"x"}
    if kind == "zip":
        data = make_zip(PAIR | extra, [(zipfile.ZipInfo("sub/"), b"")])
    else:
        directories = [(tar_info("sub", tarfile.DIRTYPE), None), (tar_info(".", tarfile.DIRTYPE), None)]
        data = make_tgz(PAIR | extra, directories)
    assert extract(cache, data, kind) == ("m.tflite", "m.tflite.json", False)
    assert names(cache[0]) == ["m.tflite", "m.tflite.json"]


@pytest.mark.parametrize("kind", ["zip", "gzip"])
def test_more_than_three_members_or_no_pair_is_refused(cache, kind):
    make = MAKERS[kind]
    assert refused(cache, make(PAIR | {"SHA256SUMS": sums(PAIR), "extra": b"x"}), kind) == TOO_MANY
    assert refused(cache, make(PAIR | {"n.tflite": b"x"}), kind) == TOO_MANY
    assert refused(cache, make({"m.tflite": MODEL}), kind) == NO_PAIR
    assert refused(cache, make({"m.tflite.json": SIDECAR}), kind) == NO_PAIR
    assert refused(cache, make({"m.tflite": MODEL, "n.tflite.json": SIDECAR}), kind) == NO_PAIR
    assert refused(cache, make({"m.tflite": MODEL, "SHA256SUMS": b""}), kind) == NO_PAIR
    assert refused(cache, make({}), kind) == NO_PAIR
    dots = {f".{index}": b"" for index in range(30)}
    assert extract(cache, make(PAIR | dots), kind)[0] == "m.tflite"  # 32 entries, every one examined
    os.unlink("m.tflite", dir_fd=cache[1])
    os.unlink("m.tflite.json", dir_fd=cache[1])
    dots[".30"] = b""
    assert refused(cache, make(PAIR | dots), kind) == TOO_MANY  # 33 entries, ignored ones counted


def test_a_zip_whose_central_directory_claims_many_entries_is_refused_before_it_is_parsed(cache, monkeypatch):
    data = make_zip(PAIR)
    end = data.rindex(b"PK\x05\x06")
    lied = data[:end + 8] + struct.pack("<HH", 40000, 40000) + data[end + 12:]
    monkeypatch.setattr(zipfile.ZipFile, "_RealGetContents", lambda self: pytest.fail("parsed"))
    assert refused(cache, lied, "zip") == TOO_MANY


def test_a_member_whose_name_is_taken_is_refused_before_extraction(cache, monkeypatch):
    path, fd = cache
    monkeypatch.setattr(archives, "copy_member", lambda *args, **kwargs: pytest.fail("extracted"))
    for taken in ("m.tflite", "m.tflite.json"):
        (path / taken).write_bytes(b"theirs")
        message = refused(cache, make_zip(PAIR), "zip")
        assert message == "A model named m.tflite is already on the device; delete it first."
        assert (path / taken).read_bytes() == b"theirs"
        (path / taken).unlink()
    temp = stage(cache, make_zip(PAIR))
    with pytest.raises(UploadError) as raised:
        archives.place_archive(fd, temp, "zip", reserved="m.tflite")  # the installer's file is the installer's
    assert raised.value.message == "That name isn't allowed." and names(path) == []


def test_a_name_that_appears_while_extracting_is_never_replaced_and_the_first_half_is_taken_back(cache, monkeypatch):
    path, fd = cache
    real_place = upload.place

    def place(dir_fd, temp, final):
        if final == "m.tflite.json":
            (path / final).write_bytes(b"theirs")  # as a request racing this one would
        real_place(dir_fd, temp, final)

    monkeypatch.setattr(upload, "place", place)
    assert refused_after(cache, make_zip(PAIR)) == "A model named m.tflite is already on the device; delete it first."
    assert names(path) == ["m.tflite.json"] and (path / "m.tflite.json").read_bytes() == b"theirs"


def refused_after(cache, data):
    path, fd = cache
    temp = stage(cache, data)
    with pytest.raises(UploadError) as raised:
        archives.place_archive(fd, temp, "zip")
    assert not [name for name in names(path) if name.startswith(".upload-")]
    return raised.value.message


def patch_central_size(data: bytes, name: bytes, size: int) -> bytes:
    """The zip with the central directory's uncompressed size of `name` changed: a header that lies."""
    start = data.index(b"PK\x01\x02")
    while True:
        name_length = struct.unpack("<H", data[start + 28:start + 30])[0]
        if data[start + 46:start + 46 + name_length] == name:
            return data[:start + 24] + struct.pack("<I", size) + data[start + 28:]
        start = data.index(b"PK\x01\x02", start + 4)


def test_a_member_over_its_cap_is_refused_without_reading_it_all(cache, monkeypatch):
    monkeypatch.setattr(archives, "copy_member", lambda *args, **kwargs: pytest.fail("extracted"))
    big = 101 * 1024 * 1024
    data = make_tgz({"m.tflite.json": SIDECAR}, [(tar_info("m.tflite", size=big), None)])
    assert refused(cache, data, "gzip") == TOO_LARGE  # the header alone: there are no 101 MB behind it
    data = make_tgz({"m.tflite": MODEL}, [(tar_info("m.tflite.json", size=SIDECAR_MAX + 1), None)])
    assert refused(cache, data, "gzip") == TOO_LARGE
    data = make_tgz(PAIR, [(tar_info("SHA256SUMS", size=archives.SUMS_MAX + 1), None)])
    assert refused(cache, data, "gzip") == TOO_LARGE
    assert refused(cache, patch_central_size(make_zip(PAIR), b"m.tflite", big), "zip") == TOO_LARGE
    assert refused(cache, patch_central_size(make_zip(PAIR), b"m.tflite.json", SIDECAR_MAX + 1), "zip") == TOO_LARGE


def test_a_copy_stops_one_byte_past_its_cap_whatever_the_header_says(cache):
    path, fd = cache
    read = []

    class Endless(io.RawIOBase):
        def readable(self):
            return True

        def readinto(self, buffer):
            read.append(len(buffer))
            buffer[:] = b"\x00" * len(buffer)
            return len(buffer)

    member = archives.Member("m.tflite", 10, lambda: io.BufferedReader(Endless(), buffer_size=16))
    created = []
    with pytest.raises(archives.ArchiveError) as raised:
        archives.copy_member(member, fd, 1000, created)
    assert raised.value.message == TOO_LARGE and raised.value.status == 413
    assert sum(read) <= 1001 + 16
    for temp in created:
        upload.unlink_quietly(fd, temp)
    assert names(path) == []


def test_a_zip_whose_data_is_longer_than_its_header_says_is_refused(cache):
    data = patch_central_size(make_zip(PAIR), b"m.tflite", 10)
    assert refused(cache, data, "zip") == UNREADABLE  # zipfile stops at the stated size; the CRC then fails


@pytest.mark.parametrize("method", [zipfile.ZIP_LZMA, zipfile.ZIP_BZIP2])
def test_a_zip_member_compressed_other_than_stored_or_deflated_is_refused_before_it_is_read(cache, monkeypatch, method):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("m.tflite.json", SIDECAR)
        zf.writestr("m.tflite", bytes(1024 * 1024), compress_type=method)
    data = patch_central_size(out.getvalue(), b"m.tflite", 1000)  # the header understates what it inflates to
    monkeypatch.setattr(archives, "copy_member", lambda *args, **kwargs: pytest.fail("read"))
    assert refused(cache, data, "zip") == UNREADABLE


def test_an_empty_model_or_a_bad_sidecar_is_refused(cache):
    assert refused(cache, make_zip({"m.tflite": b"", "m.tflite.json": SIDECAR}), "zip") == "The file is empty."
    assert refused(cache, make_zip({"m.tflite": MODEL, "m.tflite.json": b"[]"}), "zip") == (
        "The sidecar isn't a JSON object.")


def test_free_space_for_the_members_is_checked_before_extraction(cache, monkeypatch):
    needed = []

    def free_space_ok(target, size):
        needed.append(size)
        return False

    monkeypatch.setattr(upload, "free_space_ok", free_space_ok)
    assert refused(cache, make_zip(PAIR), "zip") == "The device would have less than 512 MB free."
    assert needed == [len(MODEL) + len(SIDECAR)]


@pytest.mark.parametrize("kind", ["zip", "gzip"])
def test_a_corrupt_archive_is_refused(cache, kind):
    good = MAKERS[kind](PAIR)
    for data in (good[:len(good) // 2], good[:4] + b"\x00" * 100, b"PK\x03\x04", b"\x1f\x8b\x08\x00garbage"):
        assert refused(cache, data, kind) == UNREADABLE, data[:8]
    plain_tar = io.BytesIO()
    with tarfile.open(fileobj=plain_tar, mode="w") as tar:  # a tar that isn't gzipped
        info = tarfile.TarInfo("m.tflite")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    assert refused(cache, plain_tar.getvalue(), "gzip") == UNREADABLE


def test_an_encrypted_zip_member_is_refused(cache):
    data = bytearray(make_zip(PAIR))
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = 0
        while (start := data.find(signature, start)) >= 0:
            data[start + offset] |= 0x1  # the encrypted flag
            start += 4
    assert refused(cache, bytes(data), "zip") == UNREADABLE


def test_place_archive_opens_the_staged_name_without_following_a_link(cache, tmp_path):
    path, fd = cache
    outside = tmp_path / "outside.zip"
    outside.write_bytes(make_zip(PAIR))
    temp = upload.temp_name("m.zip")
    (path / temp).symlink_to(outside)
    with pytest.raises(UploadError) as raised:
        archives.place_archive(fd, temp, "zip")
    assert raised.value.message == UNREADABLE
    assert names(path) == [] and outside.exists()


def test_new_package_files_are_private_and_never_reuse_a_name(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    first, out = package.create(state, "m.tflite")
    out.close()
    second, out = package.create(state, "m.tflite")
    out.close()
    assert first != second and first.parent == state / "packages"
    assert first.name.startswith("m.tflite-") and first.name.endswith(".zip")
    assert stat.S_IMODE((state / "packages").stat().st_mode) == 0o700
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    old = os.stat(first).st_mtime - 2 * 3600
    os.utime(first, (old, old))
    third, out = package.create(state, "m.tflite")  # a package left from a download that never finished is swept
    out.close()
    assert sorted(path.name for path in (state / "packages").iterdir()) == sorted([second.name, third.name])


def test_open_in_is_how_members_are_written(cache, monkeypatch):
    """Every member's temporary name is created O_EXCL through open_in, relative to the cache's descriptor."""
    path, fd = cache
    flags = []
    real = archives.open_in

    def spy(dir_fd, name, mode, *rest):
        flags.append((dir_fd, name, mode))
        return real(dir_fd, name, mode, *rest)

    monkeypatch.setattr(archives, "open_in", spy)
    temp = stage(cache, make_zip(PAIR))
    archives.place_archive(fd, temp, "zip")
    assert flags[0] == (fd, temp, os.O_RDONLY)
    written = [entry for entry in flags[1:] if entry[2] & os.O_CREAT]
    assert len(written) == 2 and all(entry[0] == fd and entry[2] & os.O_EXCL for entry in written)
    assert all(entry[1].startswith(".upload-") for entry in written)


def test_the_caps_are_the_plans(cache):
    assert archives.MEMBERS_MAX == 3 and archives.ENTRIES_MAX == 32 and archives.SUMS_NAME == "SHA256SUMS"
    assert MODEL_FILE_MAX == 100 * 1024 * 1024


def test_a_tar_is_never_decompressed_past_its_total_cap(cache, monkeypatch):
    """A member that is skipped, or a header that claims a huge extension, still can't make the reader decompress
    without end: the whole tar stream stops at TAR_MAX."""
    monkeypatch.setattr(archives, "TAR_MAX", 64 * 1024)
    data = make_tgz(PAIR | {".big": bytes(128 * 1024)})
    assert refused(cache, data, "gzip") == TOO_LARGE
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        info = tarfile.TarInfo("m.tflite")
        info.size = len(MODEL)
        info.pax_headers = {"comment": "x" * (128 * 1024)}
        tar.addfile(info, io.BytesIO(MODEL))
    returned = []
    real_read = gzip.GzipFile.read

    def read(self, size=-1):
        returned.append(real_read(self, size))
        return returned[-1]

    monkeypatch.setattr(gzip.GzipFile, "read", read)
    assert refused(cache, out.getvalue(), "gzip") == TOO_LARGE
    assert sum(len(block) for block in returned) <= 64 * 1024  # the extension header was never read into memory
    assert extract(cache, make_tgz(PAIR), "gzip")[0] == "m.tflite"  # under the cap is fine
