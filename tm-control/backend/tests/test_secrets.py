from pathlib import Path

import pytest
from ruamel.yaml import YAML

from conftest import PLACEHOLDER_KEY
from tm_control.core.secrets import (
    ENTERED_SECRETS,
    FRIGATE_PLUS_API_KEY,
    GENERATED_SECRETS,
    NAMES,
    PLATE_RECOGNIZER_LICENSE_KEY,
    PLATE_RECOGNIZER_TOKEN,
    SESSION_KEY,
    THINGSBOARD_ACCESS_TOKEN,
    VALUE_PATTERNS,
    VALUE_RULES,
    FakeSecrets,
    MissingSecret,
    Secrets,
    is_valid_value,
)

REPO = Path(__file__).resolve().parents[3]


def test_generated_and_entered_names_match_the_role():
    role_vars = YAML(typ="safe", pure=True).load(REPO / "script/ansible/roles/tmsetup/vars/main.yml")
    assert list(GENERATED_SECRETS) == role_vars["tmsetup_secret_names"]
    assert list(ENTERED_SECRETS) == role_vars["tmsetup_entered_secret_names"]
    assert set(NAMES) <= set(GENERATED_SECRETS)


def test_the_entered_names():
    assert ENTERED_SECRETS == (
        THINGSBOARD_ACCESS_TOKEN, FRIGATE_PLUS_API_KEY, PLATE_RECOGNIZER_TOKEN, PLATE_RECOGNIZER_LICENSE_KEY,
    )
    assert ENTERED_SECRETS == (
        "thingsboard_access_token", "frigate_plus_api_key", "plate_recognizer_token", "plate_recognizer_license_key",
    )


def test_is_set_and_ends_with_follow_the_file(tmp_path):
    secrets = Secrets(tmp_path)
    name = THINGSBOARD_ACCESS_TOKEN
    assert not secrets.is_set(name) and secrets.ends_with(name) is None  # no file
    (tmp_path / name).write_text("")
    assert not secrets.is_set(name) and secrets.ends_with(name) is None
    with pytest.raises(MissingSecret):
        secrets.read(name)
    (tmp_path / name).write_text("  \n")
    assert not secrets.is_set(name)
    (tmp_path / name).write_text("tb-placeholder-9876\n")
    assert secrets.is_set(name) and secrets.ends_with(name) == "9876"
    assert secrets.read(name) == "tb-placeholder-9876"  # not cached while it was empty
    (tmp_path / name).write_text("ab")
    assert secrets.is_set(name) and secrets.ends_with(name) is None  # never a short secret whole
    assert secrets.ends_with(name, 1) is None


def test_ends_with_shows_at_most_a_third_of_the_value(tmp_path):
    secrets = Secrets(tmp_path)
    name = THINGSBOARD_ACCESS_TOKEN
    (tmp_path / name).write_text("tb-placeh-1\n")  # 11 characters
    assert secrets.is_set(name) and secrets.ends_with(name) is None
    (tmp_path / name).write_text("tb-placeh-12\n")  # 12
    assert secrets.ends_with(name) == "h-12"
    assert secrets.ends_with(name, 0) is None and secrets.ends_with(name, -1) is None
    assert secrets.ends_with(name, 5) is None and secrets.ends_with(name, 3) == "-12"
    fake = FakeSecrets()
    fake.entered[name] = "tb-placeh-1"
    assert fake.is_set(name) and fake.ends_with(name) is None
    fake.entered[name] = "tb-placeh-12"
    assert fake.ends_with(name) == "h-12" and fake.ends_with(name, 0) is None


def test_is_set_raises_only_for_a_bad_name(tmp_path):
    secrets = Secrets(tmp_path)
    for bad in ("", "a/b", ".hidden"):
        with pytest.raises(ValueError):
            secrets.is_set(bad)
        with pytest.raises(ValueError):
            secrets.ends_with(bad)


def test_an_unreadable_entered_secret_is_not_set(tmp_path):
    (tmp_path / PLATE_RECOGNIZER_TOKEN).write_bytes(b"\xff\xfe")
    secrets = Secrets(tmp_path)
    assert not secrets.is_set(PLATE_RECOGNIZER_TOKEN)
    assert secrets.ends_with(PLATE_RECOGNIZER_TOKEN) is None
    (tmp_path / PLATE_RECOGNIZER_LICENSE_KEY).mkdir()  # a directory where a file should be
    assert not secrets.is_set(PLATE_RECOGNIZER_LICENSE_KEY)


def test_read_caches_generated_names_only(tmp_path):
    secrets = Secrets(tmp_path)
    (tmp_path / SESSION_KEY).write_text("session-placeholder-1\n")
    assert secrets.read(SESSION_KEY) == "session-placeholder-1"
    (tmp_path / SESSION_KEY).write_text("session-placeholder-2\n")
    assert secrets.read(SESSION_KEY) == "session-placeholder-1"
    (tmp_path / THINGSBOARD_ACCESS_TOKEN).write_text("tb-placeholder-1111\n")
    assert secrets.read(THINGSBOARD_ACCESS_TOKEN) == "tb-placeholder-1111"
    (tmp_path / THINGSBOARD_ACCESS_TOKEN).write_text("tb-placeholder-2222\n")
    assert secrets.read(THINGSBOARD_ACCESS_TOKEN) == "tb-placeholder-2222"


def test_fake_secrets_entered_values():
    fake = FakeSecrets()
    assert fake.read(SESSION_KEY) == f"fake-{SESSION_KEY}-not-secret"
    for name in ENTERED_SECRETS:
        assert not fake.is_set(name) and fake.ends_with(name) is None
        with pytest.raises(MissingSecret):
            fake.read(name)
    fake.entered[THINGSBOARD_ACCESS_TOKEN] = "tb-placeholder-0001"
    assert fake.is_set(THINGSBOARD_ACCESS_TOKEN) and fake.ends_with(THINGSBOARD_ACCESS_TOKEN) == "0001"
    assert fake.read(THINGSBOARD_ACCESS_TOKEN) == "tb-placeholder-0001"
    assert not fake.is_set(PLATE_RECOGNIZER_TOKEN)
    assert FakeSecrets().entered == dict.fromkeys(ENTERED_SECRETS, "")  # each instance has its own
    assert fake.is_set(SESSION_KEY) and fake.ends_with(SESSION_KEY) == "cret"


def test_the_frigate_plus_key_takes_frigates_own_format():
    assert is_valid_value(FRIGATE_PLUS_API_KEY, PLACEHOLDER_KEY)
    for bad in (PLACEHOLDER_KEY.upper(), PLACEHOLDER_KEY.replace(":", ""), PLACEHOLDER_KEY[:-1],
                PLACEHOLDER_KEY + "0", PLACEHOLDER_KEY.replace("-", "_", 1), " " + PLACEHOLDER_KEY):
        assert not is_valid_value(FRIGATE_PLUS_API_KEY, bad), bad


def test_every_entered_secret_has_a_value_pattern_and_its_rule_in_words():
    assert set(VALUE_PATTERNS) == set(VALUE_RULES) == set(ENTERED_SECRETS)


@pytest.mark.parametrize(("name", "value", "valid"), [
    (THINGSBOARD_ACCESS_TOKEN, "tb-placeholder-601.A_z~", True),
    (THINGSBOARD_ACCESS_TOKEN, "x" * 256, True),
    (THINGSBOARD_ACCESS_TOKEN, "x" * 257, False),
    (THINGSBOARD_ACCESS_TOKEN, "", False),
    (THINGSBOARD_ACCESS_TOKEN, "tb/placeholder", False),
    (THINGSBOARD_ACCESS_TOKEN, "tb?placeholder", False),
    (THINGSBOARD_ACCESS_TOKEN, "tb#placeholder", False),
    (THINGSBOARD_ACCESS_TOKEN, "tb-placeholder\n", False),
    (PLATE_RECOGNIZER_TOKEN, "pr/placeholder?#'\"", True),
    (PLATE_RECOGNIZER_TOKEN, "pr placeholder", False),
    (PLATE_RECOGNIZER_TOKEN, "pr-placeholdé", False),
    (PLATE_RECOGNIZER_LICENSE_KEY, "pr-placeholder-602", True),
    (PLATE_RECOGNIZER_LICENSE_KEY, "pr-placeholder-602\n", False),
])
def test_entered_secret_values_meet_their_pattern(name, value, valid):
    assert is_valid_value(name, value) is valid
