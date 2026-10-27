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


CREDENTIALED = "rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}@host.containers.internal:8554/"


def add_go2rtc_streams(path, streams):
    """Add a go2rtc: section with the given streams: entries (YAML text, indented 4) before the cameras: key."""
    path.write_text(path.read_text().replace("cameras:\n", f"go2rtc:\n  streams:\n{streams}cameras:\n", 1))


def test_input_that_isnt_a_valid_url_is_left_alone_and_not_printed(frigate_config, capsys):
    bad_path = "rtsp://admin:pa[ss@192.0.2.10:554/s"
    add_camera(frigate_config, "bracket", bad_path)

    assert migrate.run(frigate_config) == 0
    assert f"- path: {bad_path}\n" in frigate_config.read_text()
    printed = output(capsys)
    assert "WARNING camera 'bracket' has an input path that isn't a valid URL" in printed
    assert "updated 1 camera input(s)" in printed
    assert "pa[ss" not in printed and "admin" not in printed and "192.0.2.10" not in printed


def test_a_url_with_only_a_password_counts_as_credentialed(frigate_config, capsys):
    add_camera(frigate_config, "password_only", "rtsp://:pw@192.0.2.50:8554/cam")

    assert migrate.run(frigate_config) == 0
    assert "rtsp://:pw@192.0.2.50:8554/cam" in frigate_config.read_text()
    printed = output(capsys)
    assert "WARNING" not in printed
    assert ":pw@" not in printed


def test_warning_leaves_out_the_query_and_fragment(frigate_config, capsys):
    add_camera(frigate_config, "by_token", "rtsp://192.0.2.50:8554/cam?token=abc#frag")

    assert migrate.run(frigate_config) == 0
    assert "rtsp://192.0.2.50:8554/cam?token=abc#frag" in frigate_config.read_text()
    printed = output(capsys)
    assert "WARNING camera 'by_token' reads rtsp://192.0.2.50:8554/cam without credentials" in printed
    assert "token=abc" not in printed and "frag" not in printed


def test_warning_keeps_the_brackets_on_an_ipv6_host(frigate_config, capsys):
    add_camera(frigate_config, "by_ipv6", "'rtsp://[2001:db8::5]:8554/cam?token=abc'")

    assert migrate.run(frigate_config) == 0
    printed = output(capsys)
    assert "WARNING camera 'by_ipv6' reads rtsp://[2001:db8::5]:8554/cam without credentials" in printed
    assert "token=abc" not in printed


def test_rewrites_go2rtc_stream_sources_in_list_and_string_form(frigate_config, capsys):
    add_go2rtc_streams(
        frigate_config,
        "    picam:\n"
        "      - rtsp://host.containers.internal:8554/picam_h265_detect\n"
        "    other: rtsp://host.containers.internal:8554/picam_h265_detect_hr\n",
    )
    original = frigate_config.read_text()

    assert migrate.run(frigate_config) == 0
    old_lines, new_lines = original.splitlines(), frigate_config.read_text().splitlines()
    assert [(a, b) for a, b in zip(old_lines, new_lines) if a != b] == [
        ("      - rtsp://host.containers.internal:8554/picam_h265_detect", f"      - {CREDENTIALED}picam_h265_detect"),
        ("    other: rtsp://host.containers.internal:8554/picam_h265_detect_hr", f"    other: {CREDENTIALED}picam_h265_detect_hr"),
        (DEFAULT_INPUT, MIGRATED_INPUT),
    ]
    assert "updated 3 camera input(s) and stream source(s)" in output(capsys)

    after_first = frigate_config.read_text()
    assert migrate.run(frigate_config) == 0
    assert frigate_config.read_text() == after_first
    assert "up to date" in output(capsys)


def test_dry_run_counts_go2rtc_stream_sources(frigate_config, capsys):
    add_go2rtc_streams(frigate_config, "    other: rtsp://host.containers.internal:8554/picam_h265_detect_hr\n")
    original = frigate_config.read_text()

    assert migrate.run(frigate_config, dry_run=True) == 0
    assert frigate_config.read_text() == original
    assert "would update 2 camera input(s) and stream source(s)" in output(capsys)


def test_keeps_quotes_on_quoted_go2rtc_stream_sources(frigate_config):
    add_go2rtc_streams(
        frigate_config,
        "    picam:\n"
        "      - 'rtsp://host.containers.internal:8554/picam_h265_detect'\n"
        "    other: \"rtsp://host.containers.internal:8554/picam_h265_detect_hr\"\n",
    )

    assert migrate.run(frigate_config) == 0
    text = frigate_config.read_text()
    assert f"      - '{CREDENTIALED}picam_h265_detect'\n" in text
    assert f"    other: \"{CREDENTIALED}picam_h265_detect_hr\"\n" in text


def test_warns_about_go2rtc_streams_it_cannot_rewrite(frigate_config, capsys):
    add_go2rtc_streams(
        frigate_config,
        "    lan:\n"
        "      - rtsp://192.0.2.50:8554/x?token=abc\n"
        "    broken: rtsp://admin:pa[ss@192.0.2.10:8554/s\n",
    )

    assert migrate.run(frigate_config) == 0
    text = frigate_config.read_text()
    assert "rtsp://192.0.2.50:8554/x?token=abc" in text
    assert "rtsp://admin:pa[ss@192.0.2.10:8554/s" in text
    printed = output(capsys)
    assert "WARNING go2rtc stream 'lan' reads rtsp://192.0.2.50:8554/x without credentials" in printed
    assert "WARNING go2rtc stream 'broken' has a source that isn't a valid URL" in printed
    assert "token=abc" not in printed and "pa[ss" not in printed


def test_leaves_go2rtc_entries_that_arent_strings_alone(frigate_config, capsys):
    add_go2rtc_streams(
        frigate_config,
        "    mapped:\n"
        "      url: rtsp://host.containers.internal:8554/a\n"
        "    mixed:\n"
        "      - url: rtsp://host.containers.internal:8554/b\n"
        "      - 8554\n"
        "    empty:\n",
    )
    original = frigate_config.read_text()

    assert migrate.run(frigate_config) == 0
    old_lines, new_lines = original.splitlines(), frigate_config.read_text().splitlines()
    assert [(a, b) for a, b in zip(old_lines, new_lines) if a != b] == [(DEFAULT_INPUT, MIGRATED_INPUT)]
    printed = output(capsys)
    assert "updated 1 camera input(s) to use" in printed
    assert "WARNING" not in printed


def test_go2rtc_section_that_isnt_a_mapping_is_ignored(tmp_path, capsys):
    path = tmp_path / "config.yml"
    path.write_text("go2rtc:\n  streams:\n    - rtsp://host.containers.internal:8554/a\ncameras:\n")
    assert migrate.run(path) == 0
    assert "up to date" in output(capsys)


def test_warns_about_a_wrapped_source_that_reads_this_devices_go2rtc(frigate_config, capsys):
    wrapped = "ffmpeg:rtsp://host.containers.internal:8554/picam_h265_detect#video=copy"
    add_go2rtc_streams(frigate_config, f"    picam:\n      - {wrapped}\n")
    original = frigate_config.read_text()

    assert migrate.run(frigate_config) == 0
    old_lines, new_lines = original.splitlines(), frigate_config.read_text().splitlines()
    assert [(a, b) for a, b in zip(old_lines, new_lines) if a != b] == [(DEFAULT_INPUT, MIGRATED_INPUT)]
    printed = output(capsys)
    assert printed.count("WARNING") == 1
    assert (
        "WARNING go2rtc stream 'picam' reads this device's go2rtc stream 'picam_h265_detect' "
        "inside another source type without the login"
    ) in printed
    assert "#video=copy" not in printed and "ffmpeg:rtsp" not in printed


def test_warns_about_a_wrapped_camera_input_too(frigate_config, capsys):
    add_camera(frigate_config, "wrapped", "'ffmpeg:rtsp://host.containers.internal:8554/picam?x=1 -an'")

    assert migrate.run(frigate_config) == 0
    printed = output(capsys)
    assert "WARNING camera 'wrapped' reads this device's go2rtc stream 'picam' inside another source type" in printed
    assert "x=1" not in printed and "-an" not in printed


def test_a_wrapped_source_with_the_login_placeholders_does_not_warn(frigate_config, capsys):
    add_go2rtc_streams(frigate_config, f"    picam:\n      - ffmpeg:{CREDENTIALED}picam_h265_detect#video=copy\n")

    assert migrate.run(frigate_config) == 0
    assert "WARNING" not in output(capsys)
