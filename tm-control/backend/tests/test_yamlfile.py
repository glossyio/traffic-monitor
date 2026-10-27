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
