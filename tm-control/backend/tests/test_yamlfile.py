import os
import stat
from datetime import datetime, timezone

import pytest

from tm_control.adapters import yamlfile
from tm_control.adapters.yamlfile import ConcurrentEditError, RoundTripFile

NOW = datetime(2026, 10, 2, 15, 30, 0, tzinfo=timezone.utc)


def test_round_trip_without_edits_is_byte_identical(frigate_config):
    document = RoundTripFile(frigate_config)
    assert document.render() == frigate_config.read_text()


def test_round_trip_keeps_a_final_newline(frigate_config):
    frigate_config.write_text(frigate_config.read_text() + "\n")
    assert RoundTripFile(frigate_config).render() == frigate_config.read_text()


def test_save_without_edits_writes_nothing(frigate_config):
    before = frigate_config.stat().st_mtime_ns
    assert RoundTripFile(frigate_config).save(now=NOW) is None
    assert frigate_config.stat().st_mtime_ns == before
    assert sorted(p.name for p in frigate_config.parent.iterdir()) == ["config.yml"]


def test_save_changes_only_the_edited_line_and_keeps_comments_and_quotes(frigate_config):
    original = frigate_config.read_text()
    document = RoundTripFile(frigate_config)
    document.data["cameras"]["picam_h265"]["detect"]["fps"] = 5
    document.save(now=NOW)

    old_lines, new_lines = original.splitlines(), frigate_config.read_text().splitlines()
    changed = [(a, b) for a, b in zip(old_lines, new_lines) if a != b]
    assert len(old_lines) == len(new_lines)
    assert changed == [("      fps: 10", "      fps: 5")]
    assert '  password: "{FRIGATE_MQTT_PASSWORD}"' in new_lines
    comments = [line for line in old_lines if line.lstrip().startswith("#")]
    assert len(comments) >= 2
    assert comments == [line for line in new_lines if line.lstrip().startswith("#")]


def test_save_backs_up_the_previous_file(frigate_config):
    original = frigate_config.read_text()
    document = RoundTripFile(frigate_config)
    document.data["mqtt"]["port"] = 1884
    backup = document.save(now=NOW)

    assert backup == frigate_config.with_name("config.yml.20261002T153000Z.bak")
    assert backup.read_text() == original


def test_save_keeps_the_file_mode(frigate_config):
    document = RoundTripFile(frigate_config)
    document.data["mqtt"]["port"] = 1884
    document.save(now=NOW)
    assert stat.S_IMODE(frigate_config.stat().st_mode) == 0o640


def test_save_refuses_when_the_file_changed_after_loading(frigate_config):
    document = RoundTripFile(frigate_config)
    frigate_config.write_text(frigate_config.read_text() + "# edited by hand\n")
    document.data["mqtt"]["port"] = 1884
    with pytest.raises(ConcurrentEditError):
        document.save(now=NOW)
    assert frigate_config.read_text().endswith("# edited by hand\n")


def test_failed_write_leaves_the_file_and_no_temp_files(frigate_config, monkeypatch):
    original = frigate_config.read_text()

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(yamlfile.os, "replace", fail)
    with pytest.raises(OSError):
        yamlfile.write_atomic(frigate_config, "new: content\n")
    assert frigate_config.read_text() == original
    assert sorted(p.name for p in frigate_config.parent.iterdir()) == ["config.yml"]


# migrate runs as root in tmsetup, in directories that the code owner and Node-RED's container can write to.


def test_back_up_refuses_a_link_planted_at_the_backup_name(frigate_config, tmp_path):
    target = tmp_path / "elsewhere"
    target.write_text("not yours\n")
    yamlfile.backup_path(frigate_config, NOW).symlink_to(target)
    with pytest.raises(FileExistsError):
        yamlfile.back_up(frigate_config, NOW)
    assert target.read_text() == "not yours\n"


def test_save_refuses_a_link_planted_at_the_backup_name(frigate_config, tmp_path):
    original = frigate_config.read_text()
    target = tmp_path / "elsewhere"
    target.write_text("not yours\n")
    yamlfile.backup_path(frigate_config, NOW).symlink_to(target)
    document = RoundTripFile(frigate_config)
    document.data["mqtt"]["port"] = 1884
    with pytest.raises(OSError):
        document.save(now=NOW)
    assert target.read_text() == "not yours\n"
    assert frigate_config.read_text() == original


def test_a_linked_file_is_neither_loaded_nor_backed_up(frigate_config, tmp_path):
    link = tmp_path / "linked.yml"
    link.symlink_to(frigate_config)
    with pytest.raises(OSError):
        RoundTripFile(link)
    with pytest.raises(OSError):
        yamlfile.back_up(link, NOW)
    assert not yamlfile.backup_path(link, NOW).exists()


def test_back_up_keeps_the_mode_and_as_root_sets_the_owner_through_the_open_file(frigate_config, monkeypatch):
    owners = []
    monkeypatch.setattr(yamlfile.os, "geteuid", lambda: 0)
    monkeypatch.setattr(yamlfile.os, "fchown", lambda fd, uid, gid: owners.append((uid, gid)))
    monkeypatch.setattr(yamlfile.os, "chown", lambda *args: pytest.fail("chown by path follows a swapped name"))
    backup = yamlfile.back_up(frigate_config, NOW)
    assert backup.read_text() == frigate_config.read_text()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o640
    assert owners == [(frigate_config.stat().st_uid, frigate_config.stat().st_gid)]


def test_write_atomic_sets_mode_and_owner_through_the_open_file(frigate_config, monkeypatch):
    owners = []
    monkeypatch.setattr(yamlfile.os, "geteuid", lambda: 0)
    monkeypatch.setattr(yamlfile.os, "fchown", lambda fd, uid, gid: owners.append((uid, gid)))
    monkeypatch.setattr(yamlfile.os, "chown", lambda *args: pytest.fail("chown by path follows a swapped name"))
    monkeypatch.setattr(yamlfile.os, "chmod", lambda *args: pytest.fail("chmod by path follows a swapped name"))
    yamlfile.write_atomic(frigate_config, "new: content\n")
    assert frigate_config.read_text() == "new: content\n"
    assert stat.S_IMODE(frigate_config.stat().st_mode) == 0o640
    assert owners == [(frigate_config.stat().st_uid, frigate_config.stat().st_gid)]


def test_write_atomic_refuses_a_path_that_became_a_link(tmp_path):
    """Its mode would come from the link (0777), and as root its owner from whoever made it."""
    target = tmp_path / "elsewhere"
    target.write_text("not yours\n")
    link = tmp_path / "swapped.yml"
    link.symlink_to(target)
    with pytest.raises(OSError, match="not a regular file"):
        yamlfile.write_atomic(link, "new: content\n")
    assert link.is_symlink() and target.read_text() == "not yours\n"
    assert not list(tmp_path.glob(".swapped.yml.*.tmp"))


def test_a_fifo_is_neither_read_nor_backed_up(tmp_path, prompt):
    fifo = tmp_path / "config.yml"
    os.mkfifo(fifo)
    with pytest.raises(OSError, match="not a regular file"):
        yamlfile.read_text(fifo)
    with pytest.raises(OSError, match="not a regular file"):
        yamlfile.back_up(fifo, NOW)
    assert not yamlfile.backup_path(fifo, NOW).exists()
