from pathlib import Path

from tm_control.core import migrate

REPO = Path(__file__).resolve().parents[3]

DEFAULT_INPUT = "        - path: rtsp://host.containers.internal:8554/picam_h265_detect"
MIGRATED_INPUT = (
    "        - path: rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}"
    "@host.containers.internal:8554/picam_h265_detect"
)


def output(capsys):
    captured = capsys.readouterr()
    return captured.out + captured.err


def add_camera(path, name, input_path):
    """Add a camera with one ffmpeg input to a Frigate config, at the top of the cameras: key."""
    text = path.read_text().replace(
        "cameras:\n",
        f"cameras:\n  {name}:\n    ffmpeg:\n      inputs:\n        - path: {input_path}\n          roles:\n            - detect\n",
        1,
    )
    path.write_text(text)


def test_rewrites_the_default_camera_input_and_nothing_else(frigate_config, capsys):
    original = frigate_config.read_text()
    assert migrate.run(frigate_config) == 0

    old_lines, new_lines = original.splitlines(), frigate_config.read_text().splitlines()
    assert [(a, b) for a, b in zip(old_lines, new_lines) if a != b] == [(DEFAULT_INPUT, MIGRATED_INPUT)]
    assert "updated 1 camera input(s)" in output(capsys)
    assert len(list(frigate_config.parent.glob("config.yml.*.bak"))) == 1


def test_running_twice_changes_nothing_the_second_time(frigate_config, capsys):
    migrate.run(frigate_config)
    after_first = frigate_config.read_text()
    capsys.readouterr()

    assert migrate.run(frigate_config) == 0
    assert frigate_config.read_text() == after_first
    assert "up to date" in output(capsys)
    assert len(list(frigate_config.parent.glob("config.yml.*.bak"))) == 1


def test_leaves_other_cameras_alone(frigate_config, capsys):
    add_camera(frigate_config, "street_ipcam", "rtsp://{FRIGATE_RTSP_USER}:{FRIGATE_RTSP_PASSWORD}@192.168.1.20:554/live")
    add_camera(frigate_config, "restream", "rtsp://127.0.0.1:8554/picam_h265_detect")

    assert migrate.run(frigate_config) == 0
    text = frigate_config.read_text()
    assert "rtsp://{FRIGATE_RTSP_USER}:{FRIGATE_RTSP_PASSWORD}@192.168.1.20:554/live" in text
    assert "rtsp://127.0.0.1:8554/picam_h265_detect" in text
    assert "WARNING" not in output(capsys)


def test_warns_about_port_8554_inputs_it_cannot_rewrite(frigate_config, capsys):
    add_camera(frigate_config, "by_ip", "rtsp://192.168.1.50:8554/picam_h265_detect")

    assert migrate.run(frigate_config) == 0
    assert "rtsp://192.168.1.50:8554/picam_h265_detect" in frigate_config.read_text()
    assert "WARNING camera 'by_ip'" in output(capsys)


def test_keeps_quotes_on_a_quoted_input(frigate_config):
    frigate_config.write_text(frigate_config.read_text().replace(
        "path: rtsp://host.containers.internal:8554/picam_h265_detect",
        "path: 'rtsp://host.containers.internal:8554/picam_h265_detect'",
    ))
    migrate.run(frigate_config)
    assert (
        "path: 'rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}"
        "@host.containers.internal:8554/picam_h265_detect'"
    ) in frigate_config.read_text()


def test_dry_run_reports_without_writing(frigate_config, capsys):
    original = frigate_config.read_text()
    assert migrate.run(frigate_config, dry_run=True) == 0
    assert frigate_config.read_text() == original
    assert "would update 1 camera input(s)" in output(capsys)
    assert list(frigate_config.parent.glob("config.yml.*.bak")) == []


def test_config_without_cameras_is_up_to_date(tmp_path, capsys):
    path = tmp_path / "config.yml"
    path.write_text("mqtt:\n  enabled: false\n")
    assert migrate.run(path) == 0
    assert "up to date" in output(capsys)


def test_missing_file_is_an_error(tmp_path, capsys):
    assert migrate.run(tmp_path / "missing.yml") == 1
    assert "ERROR reading" in output(capsys)


def test_invalid_yaml_is_an_error_and_is_left_alone(tmp_path, capsys):
    path = tmp_path / "config.yml"
    path.write_text("cameras: [unclosed\n")
    assert migrate.run(path) == 1
    assert "ERROR reading" in output(capsys)
    assert path.read_text() == "cameras: [unclosed\n"


def test_migrated_inputs_match_what_new_installs_get():
    template = (REPO / "container" / "frigate" / "config" / "config.yml.j2").read_text()
    assert migrate.HOST_GO2RTC_RTSP_WITH_CREDENTIALS + "picam_h265_detect" in template
