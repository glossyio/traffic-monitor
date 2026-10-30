import pytest

from tm_control.adapters.redact import REDACTED, redact


def test_redact_replaces_each_value_and_prefers_the_longest():
    assert redact("x=abcdef y=abc", ["abc", "abcdef"]) == "x=<redacted> y=<redacted>"


def test_redact_ignores_empty_values():
    assert redact("nothing to hide", ["", "absent"]) == "nothing to hide"


@pytest.mark.parametrize(
    "line, expected",
    [
        ("password=hunter2", "password=<redacted>"),
        ("Password: hunter2", "Password: <redacted>"),
        ("TM_MQTT_BROKER_PASSWORD=hunter2", "TM_MQTT_BROKER_PASSWORD=<redacted>"),
        ("access_token: tb-token-1", "access_token: <redacted>"),
        ("passwd = hunter2 and more", "passwd = <redacted> and more"),
        ("NODE_RED_CREDENTIAL_SECRET=s3cr3t-value", "NODE_RED_CREDENTIAL_SECRET=<redacted>"),
        ("TM_INTERNAL_TOKEN=abc123", "TM_INTERNAL_TOKEN=<redacted>"),
        ("Setup code: ABCD-EFGH", "Setup code: <redacted>"),
        ("setup_code=ABCD-EFGH", "setup_code=<redacted>"),
        ("setup-code: ABCD-EFGH", "setup-code: <redacted>"),
        ('{"password": "hunter2", "user": "tm"}', '{"password": <redacted> "user": "tm"}'),
        ("GET /feeds/api?token=abc123&src=x", "GET /feeds/api?token=<redacted>"),
        ("dbPassword: hunter2", "dbPassword: <redacted>"),
        ("TM_NR_TOKEN_KEY=abcdef", "TM_NR_TOKEN_KEY=<redacted>"),
    ],
)
def test_redact_masks_password_and_token_lines(line, expected):
    assert redact(line, []) == expected
    assert REDACTED in redact(line, [])


@pytest.mark.parametrize(
    "line",
    [
        "2026-10-28T09:12:30-0700 tm-fake frigate[812]: Starting Frigate (0.18.1)",
        "secrets_dir=/etc/traffic-monitor/secrets",
        "tokens: 3 issued",
        "the password was changed",
    ],
)
def test_redact_leaves_ordinary_text(line):
    assert redact(line, ["unrelated-secret-value"]) == line


@pytest.mark.parametrize("line", ["password=hunter2", '{"password": "hunter2"}', "mqtt_password: hunter2"])
def test_a_value_that_is_also_a_key_does_not_hide_the_secret_after_it(line):
    """frigate.env's defaults include FRIGATE_RTSP_PASSWORD=password, so "password" is one of the values."""
    out = redact(line, ["password", "mqtt_pass"])
    assert "hunter2" not in out
    assert REDACTED in out


@pytest.mark.parametrize(
    "text, values, expected",
    [
        ("db password=my pass phrase end", ["my pass phrase"], "db password=<redacted> end"),
        ("token: abc def", ["abc def"], "token: <redacted>"),
        ("a s3cr3t-one and s3cr3t-one again", ["s3cr3t-one"], "a <redacted> and <redacted> again"),
        ("x aaaa-secretbbbb-secret y", ["aaaa-secret", "bbbb-secret"], "x <redacted> y"),
        ("password=hunter2", ["password"], "<redacted>=<redacted>"),
    ],
)
def test_a_value_and_a_key_match_are_redacted_as_one_span(text, values, expected):
    """Spans from both passes are found in the original text and merged, so neither pass can split the other's."""
    assert redact(text, values) == expected


def test_redact_does_not_reach_the_next_line():
    assert redact("password:\nnext line stays", []) == "password:\nnext line stays"
