"""tm-control migrate moves the ThingsBoard and Plate Recognizer secrets out of Node-RED's config.yml, and a
hand-entered plate-recognizer.env or frigate.env, into the device's secret files. The values here are placeholders."""

import os
import stat
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from tm_control.cli import main
from tm_control.core import migrate
from tm_control.core.secrets import ENTERED_SECRETS, PLATE_RECOGNIZER_LICENSE_KEY, PLATE_RECOGNIZER_TOKEN
from tm_control.core.secrets import FRIGATE_PLUS_API_KEY, THINGSBOARD_ACCESS_TOKEN, VALUE_RULES

from placeholders import PLACEHOLDER_KEY

FIXTURES = Path(__file__).resolve().parent / "fixtures"
# Node-RED's config.yml as the template before this change rendered it with the role's defaults, byte for byte:
# "access_token: ", "lat: ", and "lon: " end in a space.
OLD_TEMPLATE = FIXTURES / "node_red_config_old_template.yml"

TOKEN, PR_TOKEN, PR_KEY = "tb-placeholder-345", "pr-placeholder-346", "pr-placeholder-347"
PR_URL = "        url: http://plate-recognizer:8080"
ADDONS = f"addons:\n    plate_recognizer:\n        token: {PR_TOKEN}\n{PR_URL}\n"
OLD_TOKEN_LINE = "    access_token: \n"


def output(capsys):
    captured = capsys.readouterr()
    return captured.out + captured.err


def write_config(path, access_token=TOKEN, addons=ADDONS):
    """The old template's config.yml with the access token filled in and, unless addons is empty, an addons block
    between thingsboard and deployment, where it shows whether the blank lines around it survive."""
    text = OLD_TEMPLATE.read_text()
    text = text.replace(OLD_TOKEN_LINE, f"    access_token: {access_token}\n", 1)
    if addons:
        text = text.replace("\ndeployment:", f"\n{addons}\ndeployment:", 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o640)
    return path


def lines(text):
    """A file's lines without trailing whitespace, which ruamel drops after a key with no value (lat: )."""
    return [line.rstrip() for line in text.splitlines()]


def removed(original, new, *taken_out):
    """Whether new is original with exactly these lines taken out, every other line the same apart from trailing
    whitespace, and ending in a newline as the original does."""
    kept = lines(original)
    for line in taken_out:
        kept.remove(line.rstrip())
    return kept == lines(new) and new.endswith("\n") == original.endswith("\n")


def data(text):
    return YAML(typ="safe", pure=True).load(text)


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
    expected = data(original)
    del expected["thingsboard"]["access_token"], expected["addons"]["plate_recognizer"]["token"]
    assert data(new) == expected
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
    original = OLD_TEMPLATE.read_text() + f"\naddons:\n    plate_recognizer:\n        token: {PR_TOKEN}\n"
    config.write_text(original)
    assert migrate.run_node_red(config, secrets_dir) == 0
    new = config.read_text()
    assert lines(new) == lines(OLD_TEMPLATE.read_text().replace(OLD_TOKEN_LINE, ""))
    assert new.endswith("readings\n")


@pytest.mark.parametrize(("before", "after"), [
    (  # the only key, so thingsboard stays as an empty mapping
        f"thingsboard:\n    access_token: {TOKEN}  # mine\n\n# the deployment\ndeployment:\n    lat: 1\n    database_precision: '1'\n",
        "thingsboard: {}\n\n# the deployment\ndeployment:\n    lat: 1\n    database_precision: '1'\n",
    ),
    (  # the first key, with a comment before the next
        f"addons:\n    plate_recognizer:\n        token: {PR_TOKEN}\n        # the url\n        url: http://x\n"
        "\n    # other\n    other: [1, 2]\n\ndeployment:\n    lat: 1\n    database_precision: '1'\n",
        "addons:\n    plate_recognizer:\n        # the url\n        url: http://x\n"
        "\n    # other\n    other: [1, 2]\n\ndeployment:\n    lat: 1\n    database_precision: '1'\n",
    ),
    (  # after a block list and after a flow list, where ruamel keeps the lines on the next key
        f"thingsboard:\n    hosts:\n        - a\n    access_token: {TOKEN}\n\n    # nested\n"
        f"addons:\n    list: [1]\n    plate_recognizer:\n        token: {PR_TOKEN}\n\n# the deployment\ndeployment:\n"
        "    lat: 1\n    database_precision: '1'\n",
        "thingsboard:\n    hosts:\n        - a\n\n    # nested\naddons:\n    list: [1]\n\n# the deployment\n"
        "deployment:\n    lat: 1\n    database_precision: '1'\n",
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
    assert captured.err.endswith(" Enter it on the control app's Device page and delete the key.\n")
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


@pytest.mark.parametrize("value", [" ", "", " ''", ' ""', " ~", " null"])
def test_an_empty_key_is_removed(tmp_path, value, capsys):
    """Every unit installed with the old template has "access_token: " with no value (the first case, the
    fixture's own line). The secrets directory isn't needed for that, so this runs without one."""
    config = write_config(tmp_path / "config.yml", access_token="", addons="")
    config.write_text(config.read_text().replace(OLD_TOKEN_LINE, f"    access_token:{value}\n"))
    original = config.read_text()

    assert migrate.run_node_red(config, tmp_path / "missing-secrets") == 0
    new = config.read_text()
    assert removed(original, new, f"    access_token:{value}")
    (backup,) = backups(config)
    assert output(capsys) == (
        f"tm-control migrate: {config}: removed the empty thingsboard.access_token (backup: {backup})\n")


def test_an_empty_plate_recognizer_token_is_removed_with_its_empty_mappings(tmp_path, capsys):
    config = write_config(tmp_path / "config.yml", access_token="", addons="addons:\n    plate_recognizer:\n        token: ''\n")
    assert migrate.run_node_red(config, tmp_path / "missing-secrets") == 0
    assert lines(config.read_text()) == lines(OLD_TEMPLATE.read_text().replace(OLD_TOKEN_LINE, ""))
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
    assert owners[0] == (0, secrets_dir.stat().st_gid)  # then write_atomic keeps that owner


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
    monkeypatch.setattr(os, "fchown", lambda fd, uid, gid: chowned.append((os.readlink(f"/proc/self/fd/{fd}"), uid, gid)))
    assert migrate.run_node_red(config_yml, secrets_dir) == 0
    (backup,) = backups(config_yml)
    assert (str(backup), config_yml.stat().st_uid, config_yml.stat().st_gid) in chowned


def test_the_fixture_has_the_old_templates_empty_slot():
    text = OLD_TEMPLATE.read_text()
    assert OLD_TOKEN_LINE in text.splitlines(keepends=True)
    assert "    lat: \n" in text and "    lon: \n" in text
    assert data(text)["thingsboard"]["access_token"] is None


CONFIG_REMEDY = " Enter it on the control app's Device page and delete the key.\n"
TB_RULE = "1 to 256 letters, digits, and . _ ~ -"
PR_RULE = "1 to 256 printable ASCII characters with no spaces"


@pytest.mark.parametrize("value", ["tb/placeholder-501", "tb-placeholder?502", "'tb-placeholder#503'",
                                   "'tb-placeholdé-504'", "tb-placeholder-505" + "x" * 239, "'tb-placeholder 506'"])
def test_a_thingsboard_token_the_upload_url_cannot_carry_is_left_with_a_warning(tmp_path, secrets_dir, value, capsys):
    """The token goes into the upload URL's path, so it takes only URL-unreserved characters (Review Focus 2)."""
    config = write_config(tmp_path / "config.yml", access_token=value, addons="")
    original = config.read_text()
    assert migrate.run_node_red(config, secrets_dir) == 0
    captured = capsys.readouterr()
    assert captured.out == f"tm-control migrate: {config}: up to date\n"
    (warning,) = captured.err.splitlines(keepends=True)
    assert warning.startswith(f"tm-control migrate: WARNING {config}: thingsboard.access_token ")
    assert TB_RULE in warning and "left as it is" in warning and warning.endswith(CONFIG_REMEDY)
    assert "placeholder" not in warning
    assert config.read_text() == original
    assert secret(secrets_dir, THINGSBOARD_ACCESS_TOKEN) == ""


def test_the_longest_thingsboard_token_moves(tmp_path, secrets_dir):
    value = "tb-placeholder-507" + "x" * 238
    config = write_config(tmp_path / "config.yml", access_token=value, addons="")
    assert migrate.run_node_red(config, secrets_dir) == 0
    assert secret(secrets_dir, THINGSBOARD_ACCESS_TOKEN) == value + "\n"


def test_a_plate_recognizer_token_takes_any_printable_ascii(tmp_path, secrets_dir, capsys):
    config = write_config(tmp_path / "config.yml", access_token="",
                          addons="addons:\n    plate_recognizer:\n        token: pr/placeholder?508\n")
    assert migrate.run_node_red(config, secrets_dir) == 0
    assert secret(secrets_dir, PLATE_RECOGNIZER_TOKEN) == "pr/placeholder?508\n"
    assert "WARNING" not in capsys.readouterr().err


@pytest.mark.parametrize("value", ["'pr-placeholder 509'", "'pr-placeholdé-510'"])
def test_a_plate_recognizer_token_with_a_space_or_non_ascii_is_left_with_a_warning(tmp_path, secrets_dir, value,
                                                                                    capsys):
    config = write_config(tmp_path / "config.yml", access_token="",
                          addons=f"addons:\n    plate_recognizer:\n        token: {value}\n")
    assert migrate.run_node_red(config, secrets_dir) == 0
    captured = capsys.readouterr()
    assert value in config.read_text()
    (warning,) = captured.err.splitlines(keepends=True)
    assert "addons.plate_recognizer.token " in warning and PR_RULE in warning and warning.endswith(CONFIG_REMEDY)
    assert "placeholder" not in captured.out + captured.err
    assert secret(secrets_dir, PLATE_RECOGNIZER_TOKEN) == ""


@pytest.mark.parametrize(("token", "license_key", "refused"), [
    ("pr-placeholder-511 pr-placeholder-512", "XXXXX", ["TOKEN"]),
    ("YYYYY", "pr-placeholdé-513", ["LICENSE_KEY"]),
    ("pr-placeholder 514", "pr-placeholder 515", ["TOKEN", "LICENSE_KEY"]),
])
def test_an_env_value_the_env_line_cannot_carry_is_backed_up_with_a_warning(env_file, secrets_dir, token,
                                                                             license_key, refused, capsys):
    """tmsetup rewrites the line from the (empty) secrets file next, so the env file's value would be lost."""
    path = env_file(token=token, license_key=license_key)
    original = path.read_text()
    assert migrate.run_plate_recognizer_env(path, secrets_dir) == 0
    captured = capsys.readouterr()
    assert captured.out == f"tm-control migrate: {path}: up to date\n"
    (backup,) = path.parent.glob("plate-recognizer.env.*.bak")
    assert backup.read_text() == original
    warnings = captured.err.splitlines()
    assert [line.split(": ")[2].split()[0] for line in warnings] == refused
    for warning in warnings:
        assert PR_RULE in warning
        assert warning.endswith(f"Enter it on the control app's Device page; the env file was backed up to {backup}.")
    assert "placeholder" not in captured.out + captured.err
    assert secret(secrets_dir, PLATE_RECOGNIZER_TOKEN) == ""
    assert secret(secrets_dir, PLATE_RECOGNIZER_LICENSE_KEY) == ""
    assert path.read_text() == original


def test_an_env_value_that_cannot_move_is_not_backed_up_in_a_dry_run(env_file, secrets_dir, capsys):
    path = env_file(token="pr-placeholder 516")
    assert migrate.run_plate_recognizer_env(path, secrets_dir, dry_run=True) == 0
    assert "WARNING" in capsys.readouterr().err
    assert not list(path.parent.glob("plate-recognizer.env.*.bak"))


def test_a_linked_config_is_refused(tmp_path, secrets_dir, capsys):
    """As root, following a link would read, back up, and replace a file the link's maker chose."""
    target = write_config(tmp_path / "target.yml")
    original = target.read_text()
    link = tmp_path / "config.yml"
    link.symlink_to(target)
    assert migrate.run_node_red(link, secrets_dir) == 1
    printed = output(capsys)
    assert f"tm-control migrate: ERROR reading {link}" in printed and TOKEN not in printed
    assert target.read_text() == original and link.is_symlink()
    assert secret(secrets_dir, THINGSBOARD_ACCESS_TOKEN) == ""


def test_a_linked_env_file_is_refused(env_file, tmp_path, secrets_dir, capsys):
    target = env_file(token=PR_TOKEN)
    link = tmp_path / "plate-recognizer.env"
    link.symlink_to(target)
    assert migrate.run_plate_recognizer_env(link, secrets_dir) == 1
    printed = output(capsys)
    assert f"tm-control migrate: ERROR reading {link}" in printed and PR_TOKEN not in printed
    assert secret(secrets_dir, PLATE_RECOGNIZER_TOKEN) == ""


def test_a_link_planted_at_the_backup_name_is_not_followed(config_yml, secrets_dir, tmp_path, monkeypatch, capsys):
    """Node-RED's container can write its config directory, and the backup's name is easy to guess."""
    target = tmp_path / "elsewhere"
    target.write_text("not yours\n")
    planted = config_yml.with_name("config.yml.20261103T120000Z.bak")
    planted.symlink_to(target)
    monkeypatch.setattr("tm_control.adapters.yamlfile.backup_path", lambda path, now=None: planted)
    original = config_yml.read_text()

    assert migrate.run_node_red(config_yml, secrets_dir) == 1
    printed = output(capsys)
    assert f"tm-control migrate: ERROR writing {config_yml}" in printed
    assert TOKEN not in printed and PR_TOKEN not in printed
    assert target.read_text() == "not yours\n"
    assert config_yml.read_text() == original


def test_a_link_planted_at_the_env_backup_name_is_not_followed(env_file, secrets_dir, tmp_path, monkeypatch, capsys):
    target = tmp_path / "elsewhere"
    target.write_text("not yours\n")
    path = env_file(token="pr-placeholder 517")
    planted = path.with_name("plate-recognizer.env.20261103T120000Z.bak")
    planted.symlink_to(target)
    monkeypatch.setattr("tm_control.adapters.yamlfile.backup_path", lambda path, now=None: planted)
    assert migrate.run_plate_recognizer_env(path, secrets_dir) == 1
    assert "ERROR" in output(capsys)
    assert target.read_text() == "not yours\n"


def test_a_config_that_is_not_utf8_is_an_error(tmp_path, secrets_dir, capsys):
    config = tmp_path / "config.yml"
    config.write_bytes(b"\xff\xfethingsboard:\n")
    assert migrate.run_node_red(config, secrets_dir) == 1
    assert output(capsys) == f"tm-control migrate: ERROR reading {config}: not UTF-8 (UnicodeDecodeError)\n"


def test_an_env_file_that_is_not_utf8_is_an_error(env_file, secrets_dir, capsys):
    path = env_file()
    path.write_bytes(b"TOKEN=\xff\n")
    assert migrate.run_plate_recognizer_env(path, secrets_dir) == 1
    assert output(capsys) == f"tm-control migrate: ERROR reading {path}: not UTF-8 (UnicodeDecodeError)\n"


def test_a_fifo_at_config_yml_is_an_error_and_returns_promptly(tmp_path, secrets_dir, prompt, capsys):
    """Node-RED's container can write its config directory, so a FIFO there must not hang root's migrate."""
    config = tmp_path / "config.yml"
    os.mkfifo(config)
    assert migrate.run_node_red(config, secrets_dir) == 1
    assert output(capsys) == f"tm-control migrate: ERROR reading {config}: not a regular file\n"


def test_a_fifo_at_the_env_file_is_an_error_and_returns_promptly(tmp_path, secrets_dir, prompt, capsys):
    path = tmp_path / "plate-recognizer.env"
    os.mkfifo(path)
    assert migrate.run_plate_recognizer_env(path, secrets_dir) == 1
    assert output(capsys) == f"tm-control migrate: ERROR reading {path}: not a regular file\n"


def test_a_fifo_among_the_env_backups_is_skipped(env_file, secrets_dir, prompt, capsys):
    path = env_file(token="pr-placeholder 518")
    os.mkfifo(path.with_name("plate-recognizer.env.20261103T120000Z.bak"))
    assert migrate.run_plate_recognizer_env(path, secrets_dir) == 0
    made = [p for p in path.parent.glob("plate-recognizer.env.*.bak") if p.is_file()]
    assert len(made) == 1 and made[0].read_text() == path.read_text()


class PlantedError(Exception):
    """An unexpected failure whose message holds a value."""


@pytest.mark.parametrize("option, helper", [("--node-red-config", "_find"), ("--plate-recognizer-env", "_env_values")])
def test_an_unexpected_error_prints_only_its_kind(config_yml, env_file, secrets_dir, monkeypatch, capsys, option,
                                                  helper):
    """No traceback, and so no message that could quote a value, reaches the install log."""

    def fail(*args, **kwargs):
        raise PlantedError("tb-placeholder-902")

    monkeypatch.setattr(migrate, helper, fail)
    path = config_yml if option == "--node-red-config" else env_file(token=PR_TOKEN)
    assert main(["migrate", option, str(path), "--secrets-dir", str(secrets_dir)]) == 1
    printed = output(capsys)
    assert printed == f"tm-control migrate: ERROR {path}: PlantedError\n"
    assert "tb-placeholder-902" not in printed


def frigate_env(tmp_path, key=PLACEHOLDER_KEY):
    """frigate.env as frigate.env.j2 renders it, with placeholders, and PLUS_API_KEY set to key."""
    path = tmp_path / "frigate" / "frigate.env"
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        "# Frigate environment variables\n"
        "FRIGATE_RTSP_PASSWORD=rtsp-placeholder-701\n"
        "# Credentials Frigate uses to read the camera from go2rtc on the host (set by tmsetup.sh)\n"
        "FRIGATE_GO2RTC_RTSP_USER=frigate\n"
        "FRIGATE_GO2RTC_RTSP_PASSWORD=go2rtc-placeholder-702\n"
        "# Frigate trusts the reverse proxy's user and role headers only with this secret (set by tmsetup.sh)\n"
        "FRIGATE_PROXY_AUTH_SECRET=proxy-placeholder-703\n"
        f"PLUS_API_KEY={key}\n"
        "FRIGATE_MQTT_USER=frigate\n"
        "FRIGATE_MQTT_PASSWORD=mqtt-placeholder-704\n"
        "FRIGATE_HOME_DIR=/opt/traffic-monitor/frigate\n"
        "FRIGATE_VERSION=0.18.1\n"
        "# Keep in step with the /frigate location in revproxy's frigate.conf.j2 and the path in tm-control's APPS\n"
        "FRIGATE_BASE_PATH=/frigate\n"
    )
    return path


def frigate_backups(path):
    return list(path.parent.glob("frigate.env.*.bak"))


def holds_a_key(printed):
    """Whether printed text holds the placeholder key's id, its secret part, or its first group, in either case."""
    lowered = printed.lower()
    return any(part in lowered for part in PLACEHOLDER_KEY.split(":") + [PLACEHOLDER_KEY[:8]])


@pytest.mark.parametrize("quote", ["", '"'], ids=["bare", "between v0.5.0's quotes"])
def test_a_frigate_plus_key_typed_into_frigate_env_moves(tmp_path, secrets_dir, quote, capsys):
    """v0.5.0 rendered PLUS_API_KEY="", so a key typed between its quotes moves as the bare key."""
    path = frigate_env(tmp_path, key=f"{quote}{PLACEHOLDER_KEY}{quote}")
    original = path.read_text()

    assert migrate.run_frigate_env(path, secrets_dir) == 0
    captured = capsys.readouterr()
    assert captured.out == f"tm-control migrate: {path}: moved PLUS_API_KEY to the secrets files\n"
    assert captured.err == ""
    assert not holds_a_key(captured.out)
    assert secret(secrets_dir, FRIGATE_PLUS_API_KEY) == PLACEHOLDER_KEY + "\n"
    assert stat.S_IMODE((secrets_dir / FRIGATE_PLUS_API_KEY).stat().st_mode) == 0o640
    assert path.read_text() == original  # tmsetup writes the line from the secret file on the same run
    assert not frigate_backups(path)

    # The same value in both, as before tmsetup rewrites the line, is up to date and quiet
    assert migrate.run_frigate_env(path, secrets_dir) == 0
    assert output(capsys) == f"tm-control migrate: {path}: up to date\n"


@pytest.mark.parametrize("key", ["", '""'], ids=["v0.6.0 and later", "v0.5.0"])
def test_an_empty_plus_api_key_line_is_up_to_date(tmp_path, secrets_dir, key, capsys):
    """frigate.env.j2 wrote PLUS_API_KEY="" in v0.5.0 and PLUS_API_KEY= since; neither is a key."""
    path = frigate_env(tmp_path, key=key)
    assert migrate.run_frigate_env(path, secrets_dir) == 0
    captured = capsys.readouterr()
    assert captured.out == f"tm-control migrate: {path}: up to date\n"
    assert captured.err == ""
    assert secret(secrets_dir, FRIGATE_PLUS_API_KEY) == ""
    assert not frigate_backups(path)


def test_a_missing_frigate_env_is_up_to_date(tmp_path, secrets_dir, capsys):
    path = tmp_path / "frigate" / "frigate.env"  # a first install: the template renders it later
    assert migrate.run_frigate_env(path, secrets_dir) == 0
    assert output(capsys) == f"tm-control migrate: {path}: up to date\n"
    assert secret(secrets_dir, FRIGATE_PLUS_API_KEY) == ""


@pytest.mark.parametrize("key", [
    PLACEHOLDER_KEY.upper(),
    PLACEHOLDER_KEY.replace(":", ": "),
    PLACEHOLDER_KEY.replace(":", ""),
    f'"{PLACEHOLDER_KEY.upper()}"',
    f'"{PLACEHOLDER_KEY}',
    f"'{PLACEHOLDER_KEY}'",
], ids=["uppercase", "a space", "no colon", "uppercase between quotes", "one quote", "single quotes"])
def test_a_frigate_plus_key_that_frigate_would_reject_is_left_with_a_warning(tmp_path, secrets_dir, key, capsys):
    """tmsetup writes the (empty) secret file over the PLUS_API_KEY line next, so the typed key's only copy is the
    backup."""
    path = frigate_env(tmp_path, key=key)
    original = path.read_text()

    assert migrate.run_frigate_env(path, secrets_dir) == 0
    captured = capsys.readouterr()
    assert captured.out == f"tm-control migrate: {path}: up to date\n"
    assert secret(secrets_dir, FRIGATE_PLUS_API_KEY) == ""
    (backup,) = frigate_backups(path)
    assert backup.read_text() == original
    assert path.read_text() == original
    (warning,) = captured.err.splitlines()
    assert warning.startswith(f"tm-control migrate: WARNING {path}: PLUS_API_KEY isn't ")
    assert VALUE_RULES[FRIGATE_PLUS_API_KEY] in warning
    assert warning.endswith(f"Enter it on the control app's Device page; the env file was backed up to {backup}.")
    assert key not in captured.out + captured.err
    assert not holds_a_key(captured.out + captured.err)


def test_a_quoted_frigate_plus_key_the_secret_file_holds_is_up_to_date(tmp_path, secrets_dir, capsys):
    (secrets_dir / FRIGATE_PLUS_API_KEY).write_text(PLACEHOLDER_KEY + "\n")
    path = frigate_env(tmp_path, key=f'"{PLACEHOLDER_KEY}"')
    assert migrate.run_frigate_env(path, secrets_dir) == 0
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == (f"tm-control migrate: {path}: up to date\n", "")
    assert not frigate_backups(path)


def test_a_frigate_plus_key_that_differs_from_the_secret_file_is_kept_out_with_a_warning(tmp_path, secrets_dir,
                                                                                         capsys):
    (secrets_dir / FRIGATE_PLUS_API_KEY).write_text(PLACEHOLDER_KEY + "\n")
    other = PLACEHOLDER_KEY[:-1] + "8"
    path = frigate_env(tmp_path, key=other)
    original = path.read_text()

    assert migrate.run_frigate_env(path, secrets_dir) == 0
    captured = capsys.readouterr()
    assert captured.out == f"tm-control migrate: {path}: up to date\n"
    assert secret(secrets_dir, FRIGATE_PLUS_API_KEY) == PLACEHOLDER_KEY + "\n"
    (backup,) = frigate_backups(path)
    assert backup.read_text() == original
    (warning,) = captured.err.splitlines()
    assert warning.startswith(f"tm-control migrate: WARNING {path}: PLUS_API_KEY differs from the secrets file "
                              f"{FRIGATE_PLUS_API_KEY}, which is kept")
    assert f"(backup: {backup})" in warning
    assert not holds_a_key(captured.out + captured.err)


def test_frigate_env_dry_run_writes_nothing(tmp_path, secrets_dir, capsys):
    path = frigate_env(tmp_path)
    original = path.read_text()
    assert migrate.run_frigate_env(path, secrets_dir, dry_run=True) == 0
    assert output(capsys) == f"tm-control migrate: {path}: would move PLUS_API_KEY to the secrets files\n"
    assert secret(secrets_dir, FRIGATE_PLUS_API_KEY) == ""
    assert path.read_text() == original
    assert not frigate_backups(path)

    # A key Frigate would reject warns, but isn't backed up in a dry run either
    path = frigate_env(tmp_path, key=PLACEHOLDER_KEY.upper())
    assert migrate.run_frigate_env(path, secrets_dir, dry_run=True) == 0
    captured = capsys.readouterr()
    assert captured.out == f"tm-control migrate: {path}: up to date\n"
    assert "a run without --dry-run backs up the env file" in captured.err
    assert not holds_a_key(captured.err)
    assert not frigate_backups(path)
