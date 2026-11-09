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


def test_back_up_twice_in_the_same_second_makes_two_backups(frigate_config):
    original = frigate_config.read_bytes()
    first = yamlfile.back_up(frigate_config, NOW)
    second = yamlfile.back_up(frigate_config, NOW)
    third = yamlfile.back_up(frigate_config, NOW)
    assert first == frigate_config.with_name("config.yml.20261002T153000Z.bak")
    assert second == frigate_config.with_name("config.yml.20261002T153000Z.1.bak")
    assert third == frigate_config.with_name("config.yml.20261002T153000Z.2.bak")
    assert all(backup.read_bytes() == original for backup in (first, second, third))


def backup_names(config):
    return sorted(path.name for path in config.parent.glob("config.yml.*"))


def test_back_up_keeps_only_the_newest_ten_of_its_own(frigate_config):
    for hour in range(13):
        yamlfile.back_up(frigate_config, datetime(2026, 10, 2, hour, 30, 0, tzinfo=timezone.utc))
    assert backup_names(frigate_config) == [f"config.yml.20261002T{hour:02}3000Z.bak" for hour in range(3, 13)]


def test_back_up_orders_same_second_copies_by_their_number(frigate_config):
    for number in range(1, 12):
        frigate_config.with_name(f"config.yml.20261002T153000Z.{number}.bak").write_text("older")
    yamlfile.back_up(frigate_config, datetime(2026, 10, 2, 16, 30, 0, tzinfo=timezone.utc))
    # By number: .11 is newer than .9, though it sorts before it as text.
    assert backup_names(frigate_config) == sorted(
        [*(f"config.yml.20261002T153000Z.{number}.bak" for number in range(3, 12)), "config.yml.20261002T163000Z.bak"]
    )


@pytest.mark.parametrize(
    "name",
    [
        "config.yml.1791000000.2026-10-02@15:30:00~",  # tmsetup's Ansible backups
        "config.yml.bak",  # one made by hand
        "config.yml.old.bak",
        "config.yml.20261002T1530Z.bak",
        "config.yml.20261002T153000Z.x.bak",
        "other.yml.20200101T000000Z.bak",  # another file's
    ],
)
def test_back_up_leaves_every_other_name_alone(frigate_config, name):
    other = frigate_config.with_name(name)
    other.write_text("kept")
    for hour in range(12):
        yamlfile.back_up(frigate_config, datetime(2026, 10, 2, hour, 30, 0, tzinfo=timezone.utc))
    assert other.read_text() == "kept"
    assert len(list(frigate_config.parent.glob("config.yml.20261002T??????Z.bak"))) == 10


def test_a_copy_to_keep_gets_a_name_pruning_leaves_alone(frigate_config):
    kept = yamlfile.back_up(frigate_config, NOW, keep=True)
    same_second = yamlfile.back_up(frigate_config, NOW, keep=True)
    assert kept == frigate_config.with_name("config.yml.20261002T153000Z.migrate.bak")
    assert same_second == frigate_config.with_name("config.yml.20261002T153000Z.migrate.1.bak")
    for hour in range(12):
        yamlfile.back_up(frigate_config, datetime(2026, 10, 2, hour, 30, 0, tzinfo=timezone.utc))
    assert kept.exists() and same_second.exists()
    assert len(list(frigate_config.parent.glob("config.yml.20261002T??????Z.bak"))) == 10


def test_making_a_copy_to_keep_prunes_nothing(frigate_config):
    for hour in range(12):
        yamlfile.back_up(frigate_config, datetime(2026, 10, 2, hour, 30, 0, tzinfo=timezone.utc))
    before = backup_names(frigate_config)
    kept = yamlfile.back_up(frigate_config, NOW, keep=True)
    assert backup_names(frigate_config) == sorted([*before, kept.name])


def test_save_can_keep_its_copy(frigate_config):
    document = RoundTripFile(frigate_config)
    document.data["mqtt"]["port"] = 1884
    assert document.save(now=NOW, keep=True) == frigate_config.with_name("config.yml.20261002T153000Z.migrate.bak")


def test_back_up_prunes_only_regular_files(frigate_config, tmp_path):
    target = tmp_path / "elsewhere"
    target.write_text("target")
    link = frigate_config.with_name("config.yml.20200101T000000Z.bak")
    link.symlink_to(target)
    directory = frigate_config.with_name("config.yml.20200101T000001Z.bak")
    directory.mkdir()
    for hour in range(12):
        yamlfile.back_up(frigate_config, datetime(2026, 10, 2, hour, 30, 0, tzinfo=timezone.utc))
    assert link.is_symlink() and target.read_text() == "target" and directory.is_dir()


def test_a_prune_that_fails_doesnt_fail_the_backup(frigate_config, monkeypatch):
    for hour in range(10):
        yamlfile.back_up(frigate_config, datetime(2026, 10, 2, hour, 30, 0, tzinfo=timezone.utc))
    real = os.unlink

    def refuse(path, *args, **kwargs):
        if str(path).endswith(".bak"):
            raise PermissionError("read-only")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", refuse)
    backup = yamlfile.back_up(frigate_config, datetime(2026, 10, 2, 11, 30, 0, tzinfo=timezone.utc))
    assert backup.exists()


def test_a_copy_made_with_the_clock_behind_is_kept(frigate_config):
    """A Pi with no real-time clock can start before its clock is set, so a new copy can carry the oldest stamp."""
    for hour in range(10):
        yamlfile.back_up(frigate_config, datetime(2026, 10, 2, hour, 30, 0, tzinfo=timezone.utc))
    behind = yamlfile.back_up(frigate_config, datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc))
    assert behind.exists()
    assert len(backup_names(frigate_config)) == 10
    assert not frigate_config.with_name("config.yml.20261002T003000Z.bak").exists()


def test_back_up_gives_up_after_the_bounded_number_of_names(frigate_config, monkeypatch):
    monkeypatch.setattr(yamlfile, "MAX_BACKUPS_PER_SECOND", 3)
    for _ in range(3):
        yamlfile.back_up(frigate_config, NOW)
    with pytest.raises(FileExistsError):
        yamlfile.back_up(frigate_config, NOW)
    assert len(list(frigate_config.parent.glob("config.yml.*.bak"))) == 3


def test_back_up_refuses_a_link_at_a_later_name_too(frigate_config, tmp_path):
    target = tmp_path / "elsewhere"
    target.write_text("not yours\n")
    yamlfile.back_up(frigate_config, NOW)
    frigate_config.with_name("config.yml.20261002T153000Z.1.bak").symlink_to(target)
    with pytest.raises(FileExistsError):
        yamlfile.back_up(frigate_config, NOW)
    assert target.read_text() == "not yours\n"


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


def test_read_config_reports_missing_unreadable_and_invalid_with_the_line(tmp_path):
    path = tmp_path / "config" / "config.yml"
    assert yamlfile.read_config(path) == yamlfile.ConfigRead(None, "missing")
    path.parent.mkdir()
    path.write_text("- a list\n- not a mapping\n")
    assert yamlfile.read_config(path) == yamlfile.ConfigRead(None, "invalid")
    path.write_text("a: 1\nb: [unclosed\n")
    read = yamlfile.read_config(path)
    assert read.data is None and read.problem == "invalid" and read.line is not None and read.column is not None
    path.write_bytes(b"\xff\xfe\x00bad")
    assert yamlfile.read_config(path) == yamlfile.ConfigRead(None, "unreadable")
    path.write_text("model:\n  path: plus://abc\n")
    assert yamlfile.read_config(path) == yamlfile.ConfigRead({"model": {"path": "plus://abc"}}, None)
    path.chmod(0o000)
    try:
        read = yamlfile.read_config(path)
        assert read == yamlfile.ConfigRead(None, "unreadable") or read.problem is None  # unless the tests run as root
    finally:
        path.chmod(0o600)
