from pathlib import Path

import jinja2
import pytest
import yaml

from tm_control.core import migrate

REPO = Path(__file__).resolve().parents[3]

DEFAULT_INPUT = "        - path: rtsp://host.containers.internal:8554/picam_h265_detect"
MIGRATED_INPUT = (
    "        - path: rtsp://{FRIGATE_GO2RTC_RTSP_USER}:{FRIGATE_GO2RTC_RTSP_PASSWORD}"
    "@host.containers.internal:8554/picam_h265_detect"
)
PROXY = {
    "header_map": {"user": "x-forwarded-user", "role": "x-forwarded-groups"},
    "auth_secret": "{FRIGATE_PROXY_AUTH_SECRET}",
    "default_role": "viewer",
    "logout_url": "/logout",
}
# What the migration adds to the synthetic configs, between mqtt: and detectors:, as config.yml.j2 has it.
INSERTED = (
    "# The reverse proxy logs users in and passes who they are; Frigate's own login is off (tm-control).\n"
    "auth:\n"
    "  enabled: false\n"
    "proxy:\n"
    "  header_map:\n"
    "    user: x-forwarded-user\n"
    "    role: x-forwarded-groups\n"
    '  auth_secret: "{FRIGATE_PROXY_AUTH_SECRET}"\n'
    "  default_role: viewer\n"
    "  logout_url: /logout\n"
    "tls:\n"
    "  enabled: false\n"
    "\n"
)


def output(capsys):
    captured = capsys.readouterr()
    return captured.out + captured.err


def prepend(path, text):
    path.write_text(text + path.read_text())


def test_adds_auth_proxy_and_tls_sections(frigate_config, capsys):
    assert migrate.run(frigate_config) == 0

    doc = yaml.safe_load(frigate_config.read_text())
    assert doc["auth"] == {"enabled": False}
    assert doc["proxy"] == PROXY
    assert doc["tls"] == {"enabled": False}
    printed = output(capsys)
    assert "updated 1 camera input(s), added proxy auth settings (backup: " in printed
    assert "WARNING" not in printed


def test_adds_the_sections_after_mqtt_like_a_new_install(frigate_config):
    original = frigate_config.read_text()
    assert migrate.run(frigate_config) == 0
    new = frigate_config.read_text()

    assert '  password: "{FRIGATE_MQTT_PASSWORD}"\n\n' + INSERTED + "detectors:\n" in new
    assert new.replace(INSERTED, "", 1) == original.replace(DEFAULT_INPUT, MIGRATED_INPUT)


def test_second_run_changes_nothing(frigate_config, capsys):
    migrate.run(frigate_config)
    after_first = frigate_config.read_text()
    capsys.readouterr()

    assert migrate.run(frigate_config) == 0
    assert frigate_config.read_text() == after_first
    assert "up to date" in output(capsys)
    assert len(list(frigate_config.parent.glob("config.yml.*.bak"))) == 1


def test_adds_only_the_missing_sections(frigate_config, capsys):
    prepend(frigate_config, "auth:\n  enabled: false\n")

    assert migrate.run(frigate_config) == 0
    text = frigate_config.read_text()
    assert text.startswith("auth:\n  enabled: false\n")
    assert text.count("auth:\n") == 1
    doc = yaml.safe_load(text)
    assert doc["proxy"] == PROXY and doc["tls"] == {"enabled": False}
    printed = output(capsys)
    assert "added proxy auth settings" in printed
    assert "WARNING" not in printed


def test_existing_sections_are_left_alone_and_warned_about(frigate_config, capsys):
    prepend(frigate_config, "auth:\n  enabled: true\n")

    assert migrate.run(frigate_config) == 0
    text = frigate_config.read_text()
    assert text.startswith("auth:\n  enabled: true\n")
    assert yaml.safe_load(text)["auth"] == {"enabled": True}
    assert "auth.enabled is true" in capsys.readouterr().err


def test_proxy_section_without_a_secret_warns_and_keeps_frigates_login_on(frigate_config, capsys):
    prepend(frigate_config, "proxy:\n  header_map:\n    user: x-forwarded-user\n    role: x-forwarded-groups\n")

    assert migrate.run(frigate_config) == 0
    doc = yaml.safe_load(frigate_config.read_text())
    assert "auth_secret" not in doc["proxy"]
    assert "auth" not in doc
    assert doc["tls"] == {"enabled": False}
    err = capsys.readouterr().err
    assert "WARNING proxy.auth_secret is missing, so Frigate may trust headers the reverse proxy doesn't set" in err
    assert "WARNING auth was not added, so Frigate's own login stays on until proxy is fixed" in err


@pytest.mark.parametrize(
    "proxy",
    [
        # nginx blanks Remote-Groups, so every user would get default_role, here admin.
        "proxy:\n  header_map:\n    user: remote-user\n    role: remote-groups\n"
        "  auth_secret: \"{FRIGATE_PROXY_AUTH_SECRET}\"\n  default_role: admin\n",
        # nginx passes a client's X-Authentik-Groups through, so a viewer could send admin.
        "proxy:\n  header_map:\n    user: x-forwarded-user\n    role: x-authentik-groups\n"
        "  auth_secret: \"{FRIGATE_PROXY_AUTH_SECRET}\"\n",
    ],
    ids=["remote-headers-default-admin", "client-supplied-role-header"],
)
def test_unsafe_proxy_section_keeps_frigates_login_on(frigate_config, capsys, proxy):
    prepend(frigate_config, proxy)

    assert migrate.run(frigate_config) == 0
    text = frigate_config.read_text()
    assert text.startswith(proxy)
    assert "auth" not in yaml.safe_load(text)
    err = capsys.readouterr().err
    assert "WARNING proxy.header_map." in err
    assert "WARNING auth was not added" in err

    capsys.readouterr()
    assert migrate.run(frigate_config) == 0
    assert "auth" not in yaml.safe_load(frigate_config.read_text())
    assert "up to date" in capsys.readouterr().out


def test_proxy_section_like_ours_still_gets_auth_turned_off(frigate_config, capsys):
    prepend(
        frigate_config,
        "proxy:\n  header_map:\n    user: X-Forwarded-User\n    role: x-forwarded-groups\n"
        "  auth_secret: \"{FRIGATE_PROXY_AUTH_SECRET}\"\n",
    )

    assert migrate.run(frigate_config) == 0
    assert yaml.safe_load(frigate_config.read_text())["auth"] == {"enabled": False}
    assert "WARNING" not in output(capsys)


@pytest.mark.parametrize(
    ("section", "warning"),
    [
        ("auth:\n  reset_admin_password: true\n", "auth.enabled is missing"),
        ("tls:\n  enabled: true\n", "tls.enabled is true"),
        ("tls: {}\n", "tls.enabled is missing"),
        ("proxy:\n  header_map:\n    user: remote-user\n    role: x-forwarded-groups\n  auth_secret: \"{FRIGATE_PROXY_AUTH_SECRET}\"\n",
         "proxy.header_map.user is not x-forwarded-user"),
        ("proxy:\n  auth_secret: \"{FRIGATE_PROXY_AUTH_SECRET}\"\n", "proxy.header_map.role is not x-forwarded-groups"),
        ("proxy:\n  header_map:\n    user: x-forwarded-user\n    role: x-forwarded-groups\n"
         "  auth_secret: \"{FRIGATE_PROXY_AUTH_SECRET}\"\n  default_role: admin\n", "proxy.default_role is not viewer"),
    ],
)
def test_existing_values_that_break_the_proxy_login_warn(frigate_config, capsys, section, warning):
    prepend(frigate_config, section)

    assert migrate.run(frigate_config) == 0
    assert frigate_config.read_text().startswith(section)
    assert f"WARNING {warning}" in capsys.readouterr().err


def test_a_secret_other_than_the_placeholder_warns_without_printing_it(frigate_config, capsys):
    prepend(
        frigate_config,
        "proxy:\n  header_map:\n    user: x-forwarded-user\n    role: x-forwarded-groups\n"
        "  auth_secret: s3cret-value\n  default_role: viewer\n",
    )

    assert migrate.run(frigate_config) == 0
    assert "auth_secret: s3cret-value\n" in frigate_config.read_text()
    printed = output(capsys)
    assert "WARNING proxy.auth_secret is not {FRIGATE_PROXY_AUTH_SECRET}" in printed
    assert "s3cret" not in printed


def test_complete_sections_do_not_warn(frigate_config, capsys):
    migrate.run(frigate_config)
    capsys.readouterr()
    assert migrate.run(frigate_config) == 0
    assert "WARNING" not in output(capsys)


def test_only_proxy_settings_to_add(tmp_path, capsys):
    path = tmp_path / "config.yml"
    path.write_text("mqtt:\n  enabled: false\n\ncameras: {}\n")

    assert migrate.run(path, dry_run=True) == 0
    assert path.read_text() == "mqtt:\n  enabled: false\n\ncameras: {}\n"
    assert f"tm-control migrate: {path}: would add proxy auth settings\n" == output(capsys)

    assert migrate.run(path) == 0
    assert f"tm-control migrate: {path}: added proxy auth settings (backup: " in output(capsys)
    assert list(yaml.safe_load(path.read_text())) == ["mqtt", "auth", "proxy", "tls", "cameras"]


def test_config_without_mqtt_gets_the_sections_at_the_top(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("cameras: {}\n")
    assert migrate.run(path) == 0
    assert list(yaml.safe_load(path.read_text())) == ["auth", "proxy", "tls", "cameras"]


def new_install_config():
    template = (REPO / "container" / "frigate" / "config" / "config.yml.j2").read_text()
    rendered = jinja2.Environment(trim_blocks=True, undefined=jinja2.StrictUndefined).from_string(template).render(
        tmsetup_detectors={}
    )
    return yaml.safe_load(rendered)


def test_migrated_sections_match_what_new_installs_get():
    config = new_install_config()
    assert {key: config[key] for key in migrate.PROXY_AUTH_SECTIONS} == migrate.PROXY_AUTH_SECTIONS
    assert migrate.PROXY_AUTH_SECTIONS == {"auth": {"enabled": False}, "proxy": PROXY, "tls": {"enabled": False}}


def test_new_install_config_needs_no_migration(tmp_path, capsys):
    template = (REPO / "container" / "frigate" / "config" / "config.yml.j2").read_text()
    path = tmp_path / "config.yml"
    path.write_text(jinja2.Environment(trim_blocks=True).from_string(template).render(tmsetup_detectors={}))

    assert migrate.run(path) == 0
    assert output(capsys) == f"tm-control migrate: {path}: up to date\n"


def test_dry_run_lists_both_steps(frigate_config, capsys):
    original = frigate_config.read_text()
    assert migrate.run(frigate_config, dry_run=True) == 0
    assert frigate_config.read_text() == original
    assert f"tm-control migrate: {frigate_config}: would update 1 camera input(s), add proxy auth settings\n" in (
        output(capsys)
    )
    assert list(frigate_config.parent.glob("config.yml.*.bak")) == []
