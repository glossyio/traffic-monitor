import pytest

from tm_control.adapters.redact import REDACTED, redact, redact_words


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


def test_camera_names_are_replaced_as_whole_words():
    assert redact_words("front_door: frontage at front. a.b axb", ["front", "a.b"]) == (
        "front_door: frontage at <redacted>. <redacted> axb"
    )


def test_redact_words_prefers_the_longest_and_ignores_empty_words():
    assert redact_words("oak_ave and oak_ave_wide", ["oak_ave", "", "oak_ave_wide"]) == "<redacted> and <redacted>"
    assert redact_words("nothing to hide", ["", "absent"]) == "nothing to hide"
    assert redact_words("a-b is not a b", ["a-b"]) == "<redacted> is not a b"


def test_redact_words_reads_a_percent_escape_as_an_edge():
    line = '"GET /login?next=/frigate/settings%3Fpage%3DmasksAndZones%26camera%3Doak_ave_wide HTTP/1.1" 200 612'
    assert redact_words(line, ["oak_ave_wide"]) == line.replace("oak_ave_wide", "<redacted>")
    assert redact_words("next=%2ffrigate%2freview%3fcameras%3doak_ave_wide%26zones%3dx", ["oak_ave_wide"]) == (
        "next=%2ffrigate%2freview%3fcameras%3d<redacted>%26zones%3dx"
    )
    # Not an escape: a letter and a digit before the name, without the percent sign
    assert redact_words("A3Doak_ave_wide %3Doak_ave_wide_2", ["oak_ave_wide"]) == "A3Doak_ave_wide %3Doak_ave_wide_2"


def test_redact_words_reads_an_escape_encoded_again_as_an_edge():
    # A login redirect encodes an escape the address already had once more: %2C becomes %252C
    line = "next=/frigate/explore%3Fcameras%3Doak_ave_wide%252Celm_st_north HTTP/1.1"
    assert redact_words(line, ["oak_ave_wide", "elm_st_north"]) == (
        "next=/frigate/explore%3Fcameras%3D<redacted>%252C<redacted> HTTP/1.1"
    )
    assert redact_words("camera%253doak_ave_wide", ["oak_ave_wide"]) == "camera%253d<redacted>"
    # Not one: without the percent sign, and a longer name after it
    assert redact_words("A252Coak_ave_wide %252Coak_ave_wide_2", ["oak_ave_wide"]) == (
        "A252Coak_ave_wide %252Coak_ave_wide_2"
    )


def test_a_download_links_token_in_nginxs_log_is_hidden():
    line = (
        '10.42.0.23 - - [10/Nov/2026:08:11:15 +0000] '
        '"GET /storefiles?files=/db/tmdb.sqlite&tm_token=PLACEHOLDER HTTP/1.1" 200 394000'
    )
    out = redact(line, [])
    assert "PLACEHOLDER" not in out and "files=/db/tmdb.sqlite&tm_token=" in out and ' HTTP/1.1" 200' in out


def test_a_database_copys_ticket_in_nginxs_log_is_hidden():
    ticket = "0123456789abcdef" * 2
    line = (
        '10.42.0.23 - - [15/Nov/2026:08:11:15 +0000] '
        f'"GET /storefiles?files=tmdb-exact-{ticket}&tm_token=PLACEHOLDER HTTP/1.1" 200 394000'
    )
    out = redact(line, [])
    assert ticket not in out and "PLACEHOLDER" not in out
    assert f"files=tmdb-exact-{REDACTED}&tm_token={REDACTED} HTTP/1.1" in out and ' HTTP/1.1" 200' in out
    # with the session's cookie the same file can be asked for without a token
    assert redact(f'"GET /storefiles?files=tmdb-exact-{ticket} HTTP/1.1" 404', []) == (
        f'"GET /storefiles?files=tmdb-exact-{REDACTED} HTTP/1.1" 404'
    )


def test_the_database_copys_own_file_names_are_not_taken_for_a_ticket():
    line = "tm_20261115_tmdb-exact-locations.tar.gz holds tmdb-exact-locations.sqlite"
    assert redact(line, []) == line


PICTURE_ID = "0123456789abcdef"


def test_a_stored_pictures_id_in_nginxs_log_is_hidden():
    line = (
        '10.42.0.23 - - [27/Nov/2026:08:11:15 +0000] '
        f'"GET /api/v1/pictures/{PICTURE_ID}/clean.jpg HTTP/1.1" 200 98765'
    )
    out = redact(line, [])
    assert PICTURE_ID not in out
    assert f'"GET /api/v1/pictures/{REDACTED}/clean.jpg HTTP/1.1" 200 98765' in out
    for request in (
        f"DELETE /api/v1/pictures/{PICTURE_ID} HTTP/1.1",
        f"POST /api/v1/pictures/{PICTURE_ID}/package HTTP/1.1",
    ):
        assert redact(f'"{request}" 204 0', []) == f'"{request.replace(PICTURE_ID, REDACTED)}" 204 0'


def test_a_stored_pictures_id_is_hidden_in_any_letter_case_and_when_encoded():
    upper = PICTURE_ID.upper()
    for path in (
        f"/api/v1/pictures/{upper}/zones.jpg",  # nginx logs the path as it was asked for
        f"/login?next=%2Fapi%2Fv1%2Fpictures%2F{PICTURE_ID}%2Fclean.jpg",  # a login redirect's next=
        f"/login?next=%2fapi%2fv1%2fpictures%2f{PICTURE_ID}%2fclean.jpg",
        f"/login?next=%252Fapi%252Fv1%252Fpictures%252F{PICTURE_ID}",  # encoded once more
    ):
        out = redact(f'"GET {path} HTTP/1.1" 200 612', [])
        assert PICTURE_ID not in out.lower() and out.count(REDACTED) == 1, path


def test_other_pictures_paths_are_left_alone():
    for line in (
        "GET /api/v1/pictures HTTP/1.1",
        "GET /api/v1/pictures?survey_id=3f9a1c2e-si HTTP/1.1",
        f"GET /api/v1/pictures/{PICTURE_ID}0/clean.jpg HTTP/1.1",  # not an id: 17 characters
        "GET /api/v1/pictures/0123456789abcde/clean.jpg HTTP/1.1",  # 15
        f"GET /frigate/api/preview/{PICTURE_ID}/start HTTP/1.1",
        f"GET /api/v1/cameras/picam_h265/reference/{PICTURE_ID} HTTP/1.1",
    ):
        assert redact(line, []) == line
