"""tm-control migrate moves the ThingsBoard and Plate Recognizer secrets out of Node-RED's config.yml and a
hand-entered plate-recognizer.env into the device's secret files. The values here are placeholders."""

import os
import stat
from pathlib import Path

import pytest

from tm_control.core import migrate
from tm_control.core.secrets import ENTERED_SECRETS, PLATE_RECOGNIZER_LICENSE_KEY, PLATE_RECOGNIZER_TOKEN
from tm_control.core.secrets import THINGSBOARD_ACCESS_TOKEN

FIXTURES = Path(__file__).resolve().parent / "fixtures"

TOKEN, PR_TOKEN, PR_KEY = "tb-placeholder-345", "pr-placeholder-346", "pr-placeholder-347"
PR_URL = "        url: http://plate-recognizer:8080"
ADDONS = f"addons:\n    plate_recognizer:\n        token: {PR_TOKEN}\n{PR_URL}\n"
EMPTY_TOKEN_LINE = "    access_token:"


def output(capsys):
    captured = capsys.readouterr()
    return captured.out + captured.err


def write_config(path, access_token=TOKEN, addons=ADDONS):
    """The fixture config.yml with the access token filled in and, unless addons is empty, an addons block
    between thingsboard and deployment, where it shows whether the blank lines around it survive."""
    text = (FIXTURES / "node_red_config_ok.yml").read_text()
    text = text.replace(EMPTY_TOKEN_LINE, f"{EMPTY_TOKEN_LINE} {access_token}".rstrip(), 1)
    if addons:
        text = text.replace("\ndeployment:", f"\n{addons}\ndeployment:", 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o640)
    return path


def removed(original, new, *lines):
    """Whether new is original with exactly these lines taken out, everything else byte for byte."""
    kept = original.splitlines(keepends=True)
    for line in lines:
        kept.remove(line + "\n")
    return "".join(kept) == new


@pytest.fixture
def config_yml(tmp_path):
    return write_config(tmp_path / "node-red-tm" / "config" / "config.yml")


@pytest.fixture
def secrets_dir(tmp_path):
    """The entered secrets as tmsetup creates them: empty files, 0640, in a 0750 directory."""
    path = tmp_path / "secrets"
    path.mkdir()
    for name in ENTERED_SECRETS:
        (path / name).write_text("")
        (path / name).chmod(0o640)
    path.chmod(0o750)
    return path


@pytest.fixture
def env_file(tmp_path):
    """Write plate-recognizer.env as the template has it, with the values the test gives."""
    path = tmp_path / "plate-recognizer" / "plate-recognizer.env"
    path.parent.mkdir()

    def write(token="YYYYY", license_key="XXXXX"):
        path.write_text(
            "# Plate Recognizer settings, loaded by plate-recognizer.service.\n"
            "# Blank means not set.\n"
            f"TOKEN={token}\nLICENSE_KEY={license_key}\nWORKERS=2\n"
        )
        return path

    return write


def secret(secrets_dir, name):
    return (secrets_dir / name).read_text()


def backups(config):
    return list(config.parent.glob("config.yml.*.bak"))


def test_moves_both_tokens_into_the_empty_files_and_deletes_the_keys(config_yml, secrets_dir, capsys):
    original = config_yml.read_text()
    assert migrate.run_node_red(config_yml, secrets_dir) == 0

    assert secret(secrets_dir, THINGSBOARD_ACCESS_TOKEN) == TOKEN + "\n"
    assert secret(secrets_dir, PLATE_RECOGNIZER_TOKEN) == PR_TOKEN + "\n"
    assert secret(secrets_dir, PLATE_RECOGNIZER_LICENSE_KEY) == ""
    new = config_yml.read_text()
    assert removed(original, new, f"    access_token: {TOKEN}", f"        token: {PR_TOKEN}")
    assert PR_URL in new.splitlines()
    assert stat.S_IMODE(config_yml.stat().st_mode) == 0o640
    (backup,) = backups(config_yml)
    assert backup.read_text() == original
    printed = output(capsys)
    assert f"{config_yml}: moved thingsboard.access_token to the secrets file, " in printed
    assert f"moved addons.plate_recognizer.token to the secrets file (backup: {backup})\n" in printed
    assert TOKEN not in printed and PR_TOKEN not in printed


def test_an_addons_block_left_empty_is_removed(tmp_path, secrets_dir, capsys):
    config = write_config(tmp_path / "config.yml", addons=f"addons:\n    plate_recognizer:\n        token: {PR_TOKEN}\n")
    original = config.read_text()
    assert migrate.run_node_red(config, secrets_dir) == 0

    new = config.read_text()
    assert removed(original, new, f"    access_token: {TOKEN}", "addons:", "    plate_recognizer:",
                   f"        token: {PR_TOKEN}", "")  # and the blank line after the block
    assert "addons" not in new
    assert secret(secrets_dir, PLATE_RECOGNIZER_TOKEN) == PR_TOKEN + "\n"


def test_addons_at_the_end_of_the_file_go_with_their_blank_line(tmp_path, secrets_dir):
    config = tmp_path / "config.yml"
    original = (FIXTURES / "node_red_config_ok.yml").read_text() + f"\naddons:\n    plate_recognizer:\n        token: {PR_TOKEN}\n"
    config.write_text(original)
    assert migrate.run_node_red(config, secrets_dir) == 0
    assert config.read_text() == (FIXTURES / "node_red_config_ok.yml").read_text().replace(
        f"{EMPTY_TOKEN_LINE}\n", "")


@pytest.mark.parametrize(("before", "after"), [
    (  # the only key, so thingsboard stays as an empty mapping
        f"thingsboard:\n    access_token: {TOKEN}  # mine\n\n# the deployment\ndeployment:\n    lat: 1\n",
        "thingsboard: {}\n\n# the deployment\ndeployment:\n    lat: 1\n",
    ),
    (  # the first key, with a comment before the next
        f"addons:\n    plate_recognizer:\n        token: {PR_TOKEN}\n        # the url\n        url: http://x\n"
        "\n    # other\n    other: [1, 2]\n\ndeployment:\n    lat: 1\n",
        "addons:\n    plate_recognizer:\n        # the url\n        url: http://x\n"
        "\n    # other\n    other: [1, 2]\n\ndeployment:\n    lat: 1\n",
    ),
    (  # after a block list and after a flow list, where ruamel keeps the lines on the next key
        f"thingsboard:\n    hosts:\n        - a\n    access_token: {TOKEN}\n\n    # nested\n"
        f"addons:\n    list: [1]\n    plate_recognizer:\n        token: {PR_TOKEN}\n\n# the deployment\ndeployment:\n"
        "    lat: 1\n",
        "thingsboard:\n    hosts:\n        - a\n\n    # nested\naddons:\n    list: [1]\n\n# the deployment\n"
        "deployment:\n    lat: 1\n",
    ),
])
def test_comments_and_blank_lines_around_a_deleted_key_stay(tmp_path, secrets_dir, before, after):
    config = tmp_path / "config.yml"
    config.write_text(before)
    assert migrate.run_node_red(config, secrets_dir) == 0
    assert config.read_text() == after


def test_running_twice_is_up_to_date(config_yml, secrets_dir, capsys):
    migrate.run_node_red(config_yml, secrets_dir)
    after_first = config_yml.read_text()
    capsys.readouterr()

    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert output(capsys) == f"tm-control migrate: {config_yml}: up to date\n"
    assert config_yml.read_text() == after_first
    assert len(backups(config_yml)) == 1


def test_a_set_file_wins_over_a_different_key(tmp_path, secrets_dir, capsys):
    config = write_config(tmp_path / "config.yml", access_token="tb-placeholder-222", addons="")
    (secrets_dir / THINGSBOARD_ACCESS_TOKEN).write_text("tb-placeholder-111\n")

    assert migrate.run_node_red(config, secrets_dir) == 0
    captured = capsys.readouterr()
    assert secret(secrets_dir, THINGSBOARD_ACCESS_TOKEN) == "tb-placeholder-111\n"
    assert "access_token" not in config.read_text()
    assert "removed thingsboard.access_token from config.yml" in captured.out
    (warning,) = [line for line in captured.err.splitlines() if "WARNING" in line]
    assert "thingsboard.access_token" in warning and "secrets file" in warning and "kept" in warning
    printed = captured.out + captured.err
    assert "tb-placeholder-111" not in printed and "tb-placeholder-222" not in printed
    (backup,) = backups(config)
    assert "tb-placeholder-222" in backup.read_text()  # the one copy of the other value


def test_the_same_value_in_both_removes_the_key_quietly(tmp_path, secrets_dir, capsys):
    config = write_config(tmp_path / "config.yml", addons="")
    (secrets_dir / THINGSBOARD_ACCESS_TOKEN).write_text(TOKEN + "\n")

    assert migrate.run_node_red(config, secrets_dir) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith(
        f"tm-control migrate: {config}: removed thingsboard.access_token from config.yml, "
        "which the secrets file already holds (backup: ")
    assert captured.err == ""
    assert "access_token" not in config.read_text()
    assert secret(secrets_dir, THINGSBOARD_ACCESS_TOKEN) == TOKEN + "\n"


@pytest.mark.parametrize(("written", "text"), [
    ("1234567890123456789", "1234567890123456789"),  # an int that a float would round
    ("00123456789", "00123456789"),  # the leading zeros an int drops
    ("1e5", "1e5"),
    ("0x1F", "0x1F"),
    ("'00042'", "00042"),
])
def test_moves_a_numeric_token_as_text(tmp_path, secrets_dir, written, text):
    config = write_config(tmp_path / "config.yml", access_token=written, addons="")
    assert migrate.run_node_red(config, secrets_dir) == 0
    assert secret(secrets_dir, THINGSBOARD_ACCESS_TOKEN) == text + "\n"
    assert "access_token" not in config.read_text()


@pytest.mark.parametrize("value", ["true", "[tb-placeholder-1, b]", "{a: tb-placeholder-2}", "2026-01-01",
                                   "'tb-placeholder-3 tb-placeholder-4'", '"tb-placeholder-5\\ntb-placeholder-6"'])
def test_a_value_that_is_not_one_token_is_left_as_it_is(tmp_path, secrets_dir, value, capsys):
    config = write_config(tmp_path / "config.yml", access_token=value, addons="")
    original = config.read_text()
    assert migrate.run_node_red(config, secrets_dir) == 0
    captured = capsys.readouterr()
    assert captured.out == f"tm-control migrate: {config}: up to date\n"
    assert f"WARNING {config}: thingsboard.access_token " in captured.err
    assert "left as it is" in captured.err
    assert "placeholder" not in captured.err
    assert config.read_text() == original
    assert secret(secrets_dir, THINGSBOARD_ACCESS_TOKEN) == ""


@pytest.mark.parametrize("block", ["", "thingsboard: 7\n", "thingsboard:\n  enabled: false\n", "addons: 3\n",
                                   "addons:\n  plate_recognizer: x\n", "- a list\n", "just text\n"])
def test_a_config_without_the_mappings_is_up_to_date(tmp_path, secrets_dir, block, capsys):
    config = tmp_path / "config.yml"
    config.write_text(block)
    assert migrate.run_node_red(config, secrets_dir) == 0
    assert output(capsys) == f"tm-control migrate: {config}: up to date\n"
    assert config.read_text() == block
    assert not backups(config)


@pytest.mark.parametrize("value", ["", " ''", ' ""', " ~", " null"])
def test_an_empty_key_is_removed(tmp_path, value, capsys):
    """Every unit installed with the old template has access_token: with no value. The secrets directory isn't
    needed for that, so this runs without one."""
    config = write_config(tmp_path / "config.yml", access_token="", addons="")
    config.write_text(config.read_text().replace(f"{EMPTY_TOKEN_LINE}\n", f"{EMPTY_TOKEN_LINE}{value}\n"))
    original = config.read_text()

    assert migrate.run_node_red(config, tmp_path / "missing-secrets") == 0
    new = config.read_text()
    assert removed(original, new, f"{EMPTY_TOKEN_LINE}{value}")
    (backup,) = backups(config)
    assert output(capsys) == (
        f"tm-control migrate: {config}: removed the empty thingsboard.access_token (backup: {backup})\n")


def test_an_empty_plate_recognizer_token_is_removed_with_its_empty_mappings(tmp_path, capsys):
    config = write_config(tmp_path / "config.yml", access_token="", addons="addons:\n    plate_recognizer:\n        token: ''\n")
    assert migrate.run_node_red(config, tmp_path / "missing-secrets") == 0
    assert config.read_text() == (FIXTURES / "node_red_config_ok.yml").read_text().replace(f"{EMPTY_TOKEN_LINE}\n", "")
    printed = output(capsys)
    assert "removed the empty thingsboard.access_token, removed the empty addons.plate_recognizer.token (backup: " in printed


def test_dry_run_reports_an_empty_key_without_removing_it(tmp_path, capsys):
    config = write_config(tmp_path / "config.yml", access_token="", addons="")
    original = config.read_text()
    assert migrate.run_node_red(config, tmp_path / "missing-secrets", dry_run=True) == 0
    assert output(capsys) == f"tm-control migrate: {config}: would remove the empty thingsboard.access_token\n"
    assert config.read_text() == original
    assert not backups(config)


def test_a_missing_secret_file_is_created_with_the_directorys_group(config_yml, secrets_dir):
    (secrets_dir / THINGSBOARD_ACCESS_TOKEN).unlink()
    assert migrate.run_node_red(config_yml, secrets_dir) == 0

    path = secrets_dir / THINGSBOARD_ACCESS_TOKEN
    assert path.read_text() == TOKEN + "\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert path.stat().st_gid == secrets_dir.stat().st_gid
    if os.geteuid() == 0:
        assert path.stat().st_uid == 0


def test_a_missing_secret_file_is_created_root_owned_as_root(config_yml, secrets_dir, monkeypatch):
    (secrets_dir / THINGSBOARD_ACCESS_TOKEN).unlink()
    owners = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "fchown", lambda fd, uid, gid: owners.append((uid, gid)))
    monkeypatch.setattr(os, "chown", lambda *args: None)

    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    assert owners == [(0, secrets_dir.stat().st_gid)]


def test_dry_run_changes_nothing(config_yml, secrets_dir, capsys):
    original = config_yml.read_text()
    (secrets_dir / PLATE_RECOGNIZER_TOKEN).unlink()

    assert migrate.run_node_red(config_yml, secrets_dir, dry_run=True) == 0
    assert output(capsys) == (
        f"tm-control migrate: {config_yml}: would move thingsboard.access_token to the secrets file, "
        "move addons.plate_recognizer.token to the secrets file\n")
    assert config_yml.read_text() == original
    assert secret(secrets_dir, THINGSBOARD_ACCESS_TOKEN) == ""
    assert not (secrets_dir / PLATE_RECOGNIZER_TOKEN).exists()
    assert not backups(config_yml)


def test_an_unreadable_secrets_dir_is_an_error(config_yml, tmp_path, capsys):
    original = config_yml.read_text()
    assert migrate.run_node_red(config_yml, tmp_path / "missing-secrets") == 1
    printed = output(capsys)
    assert "tm-control migrate: ERROR" in printed
    assert TOKEN not in printed
    assert config_yml.read_text() == original
    assert not backups(config_yml)


def test_a_secret_file_that_cannot_be_read_is_an_error(config_yml, secrets_dir, capsys):
    (secrets_dir / THINGSBOARD_ACCESS_TOKEN).unlink()
    (secrets_dir / THINGSBOARD_ACCESS_TOKEN).mkdir()
    original = config_yml.read_text()
    assert migrate.run_node_red(config_yml, secrets_dir) == 1
    assert "ERROR" in output(capsys)
    assert config_yml.read_text() == original
    assert secret(secrets_dir, PLATE_RECOGNIZER_TOKEN) == ""


def test_a_missing_config_is_an_error(tmp_path, secrets_dir, capsys):
    assert migrate.run_node_red(tmp_path / "missing.yml", secrets_dir) == 1
    assert f"tm-control migrate: ERROR reading {tmp_path / 'missing.yml'}" in output(capsys)


def test_a_yaml_error_is_reported_without_the_text(tmp_path, secrets_dir, capsys):
    config = tmp_path / "config.yml"
    text = f"thingsboard:\n    access_token: {TOKEN} extra: y\n"
    config.write_text(text)

    assert migrate.run_node_red(config, secrets_dir) == 1
    printed = output(capsys)
    assert f"tm-control migrate: ERROR reading {config}: invalid YAML (" in printed
    assert ") at line 2, column " in printed
    assert TOKEN not in printed and "extra" not in printed
    assert config.read_text() == text
    assert secret(secrets_dir, THINGSBOARD_ACCESS_TOKEN) == ""


def test_plate_recognizer_env_values_move_once_and_placeholders_do_not(env_file, secrets_dir, capsys):
    path = env_file(token=PR_TOKEN, license_key="XXXXX")
    original = path.read_text()

    assert migrate.run_plate_recognizer_env(path, secrets_dir) == 0
    captured = capsys.readouterr()
    assert captured.out == f"tm-control migrate: {path}: moved TOKEN to the secrets files\n"
    assert captured.err == ""
    assert secret(secrets_dir, PLATE_RECOGNIZER_TOKEN) == PR_TOKEN + "\n"
    assert secret(secrets_dir, PLATE_RECOGNIZER_LICENSE_KEY) == ""
    assert path.read_text() == original  # tmsetup writes the lines from the secrets on the same run

    assert migrate.run_plate_recognizer_env(path, secrets_dir) == 0
    assert output(capsys) == f"tm-control migrate: {path}: up to date\n"

    for token, license_key in [("YYYYY", ""), ("", "XXXXX"), ("YYYYY", "XXXXX"), ("", "")]:
        (secrets_dir / PLATE_RECOGNIZER_TOKEN).write_text("")
        path = env_file(token=token, license_key=license_key)
        assert migrate.run_plate_recognizer_env(path, secrets_dir) == 0
        assert output(capsys) == f"tm-control migrate: {path}: up to date\n"
        assert secret(secrets_dir, PLATE_RECOGNIZER_TOKEN) == ""
        assert secret(secrets_dir, PLATE_RECOGNIZER_LICENSE_KEY) == ""


def test_plate_recognizer_env_moves_both_values(env_file, secrets_dir, capsys):
    path = env_file(token=PR_TOKEN, license_key=PR_KEY)
    assert migrate.run_plate_recognizer_env(path, secrets_dir) == 0
    assert output(capsys) == f"tm-control migrate: {path}: moved TOKEN, LICENSE_KEY to the secrets files\n"
    assert secret(secrets_dir, PLATE_RECOGNIZER_TOKEN) == PR_TOKEN + "\n"
    assert secret(secrets_dir, PLATE_RECOGNIZER_LICENSE_KEY) == PR_KEY + "\n"


def test_plate_recognizer_env_dry_run_writes_nothing(env_file, secrets_dir, capsys):
    path = env_file(token=PR_TOKEN, license_key=PR_KEY)
    assert migrate.run_plate_recognizer_env(path, secrets_dir, dry_run=True) == 0
    assert output(capsys) == f"tm-control migrate: {path}: would move TOKEN, LICENSE_KEY to the secrets files\n"
    assert secret(secrets_dir, PLATE_RECOGNIZER_TOKEN) == ""
    assert secret(secrets_dir, PLATE_RECOGNIZER_LICENSE_KEY) == ""


def test_plate_recognizer_env_does_not_overwrite_a_set_file(env_file, secrets_dir, capsys):
    (secrets_dir / PLATE_RECOGNIZER_TOKEN).write_text("pr-placeholder-111\n")
    path = env_file(token="pr-placeholder-222", license_key="XXXXX")
    original = path.read_text()

    assert migrate.run_plate_recognizer_env(path, secrets_dir) == 0
    captured = capsys.readouterr()
    assert captured.out == f"tm-control migrate: {path}: up to date\n"
    (warning,) = captured.err.splitlines()
    assert warning.startswith(f"tm-control migrate: WARNING {path}: TOKEN ")
    assert "kept" in warning
    assert "pr-placeholder-111" not in warning and "pr-placeholder-222" not in warning
    assert secret(secrets_dir, PLATE_RECOGNIZER_TOKEN) == "pr-placeholder-111\n"
    # tmsetup rewrites the TOKEN line from the secrets file next, so the other value is kept in a backup
    (backup,) = path.parent.glob("plate-recognizer.env.*.bak")
    assert backup.read_text() == original
    assert f"(backup: {backup})" in warning

    # While the add-on is turned off, nothing rewrites the line, so the next run warns again but backs up only once
    backup = backup.rename(path.with_name("plate-recognizer.env.20261101T000000Z.bak"))
    assert migrate.run_plate_recognizer_env(path, secrets_dir) == 0
    assert f"(backup: {backup})" in capsys.readouterr().err
    assert list(path.parent.glob("plate-recognizer.env.*.bak")) == [backup]


def test_plate_recognizer_env_missing_or_unreadable(tmp_path, secrets_dir, capsys):
    missing = tmp_path / "plate-recognizer" / "plate-recognizer.env"
    assert migrate.run_plate_recognizer_env(missing, secrets_dir) == 0  # the add-on isn't installed
    assert output(capsys) == f"tm-control migrate: {missing}: up to date\n"

    missing.mkdir(parents=True)
    assert migrate.run_plate_recognizer_env(missing, secrets_dir) == 1
    assert f"tm-control migrate: ERROR reading {missing}" in output(capsys)


def test_plate_recognizer_env_with_an_unreadable_secrets_dir_is_an_error(env_file, tmp_path, capsys):
    path = env_file(token=PR_TOKEN)
    assert migrate.run_plate_recognizer_env(path, tmp_path / "missing-secrets") == 1
    printed = output(capsys)
    assert "tm-control migrate: ERROR" in printed and PR_TOKEN not in printed


def test_backups_keep_the_owner_as_root(config_yml, secrets_dir, monkeypatch):
    """migrate runs as root in tmsetup, and config.yml belongs to the code owner, so the backup must too."""
    chowned = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "chown", lambda path, uid, gid: chowned.append((Path(path), uid, gid)))
    monkeypatch.setattr(os, "fchown", lambda *args: None)
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    (backup,) = backups(config_yml)
    assert (backup, config_yml.stat().st_uid, config_yml.stat().st_gid) in chowned


def test_the_fixture_has_the_old_templates_empty_slot():
    assert f"{EMPTY_TOKEN_LINE}\n" in (FIXTURES / "node_red_config_ok.yml").read_text()
