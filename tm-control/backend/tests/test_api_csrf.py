import pytest
from fastapi.testclient import TestClient

from tm_control.app import create_app

LOGIN = "/api/v1/auth/login"
BODY = {"username": "admin", "password": "correct horse 1"}


def assert_forbidden(r):
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


def test_post_without_origin_is_forbidden(claimed_client):
    assert_forbidden(claimed_client.post(LOGIN, json=BODY))


@pytest.mark.parametrize(
    "origin",
    ["http://evil.example", "http://tm-test.local.evil.example", "http://tm-test.local:8080", "null", "tm-test.local"],
)
def test_post_from_another_origin_is_forbidden(claimed_client, origin):
    assert_forbidden(claimed_client.post(LOGIN, json=BODY, headers={"Origin": origin}))


def test_post_with_a_form_body_is_forbidden(claimed_client):
    assert_forbidden(claimed_client.post(LOGIN, data={"a": "b"}, headers={"Origin": "http://tm-test.local"}))


@pytest.mark.parametrize("content_type", ["text/plain", "application/jsonx", "multipart/form-data; boundary=x", ""])
def test_post_with_another_content_type_is_forbidden(claimed_client, content_type):
    headers = {"Origin": "http://tm-test.local", "Content-Type": content_type}
    assert_forbidden(claimed_client.post(LOGIN, content=b'{"username": "admin"}', headers=headers))


@pytest.mark.parametrize("origin", ["http://tm-test.local", "https://TM-TEST.local"])
def test_matching_origin_and_json_pass(claimed_client, origin):
    r = claimed_client.post(LOGIN, json=BODY, headers={"Origin": origin})
    assert r.status_code == 200


def test_json_with_a_charset_passes(claimed_client):
    headers = {"Origin": "http://tm-test.local", "Content-Type": "application/json; charset=utf-8"}
    r = claimed_client.post(LOGIN, content=b'{"username": "admin", "password": "correct horse 1"}', headers=headers)
    assert r.status_code == 200


def test_the_port_is_part_of_the_host(settings):
    client = TestClient(create_app(settings), base_url="http://tm-test.local:8080")
    r = client.post("/api/v1/auth/logout", json={}, headers={"Origin": "http://tm-test.local:8080"})
    assert r.status_code == 204
    assert_forbidden(client.post("/api/v1/auth/logout", json={}, headers={"Origin": "http://tm-test.local"}))


def test_referer_is_accepted_when_origin_is_missing(claimed_client):
    r = claimed_client.post(LOGIN, json=BODY, headers={"Referer": "http://tm-test.local/login?next=/frigate/"})
    assert r.status_code == 200
    assert_forbidden(claimed_client.post(LOGIN, json=BODY, headers={"Referer": "http://evil.example/login"}))


def test_a_wrong_origin_is_not_rescued_by_the_referer(claimed_client):
    headers = {"Origin": "http://evil.example", "Referer": "http://tm-test.local/login"}
    assert_forbidden(claimed_client.post(LOGIN, json=BODY, headers=headers))


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_other_unsafe_methods_are_checked(claimed_client, method):
    assert_forbidden(claimed_client.request(method.upper(), "/api/v1/auth/session"))


def test_get_is_never_checked(claimed_client):
    assert claimed_client.get("/api/v1/auth/session").status_code == 200
    assert claimed_client.get("/api/v1/auth/session", headers={"Origin": "http://evil.example"}).status_code == 200


def test_unknown_api_paths_are_checked_before_routing(claimed_client):
    assert_forbidden(claimed_client.post("/api/v1/nope", json={}))


def test_paths_outside_the_api_are_not_checked(claimed_client):
    assert claimed_client.post("/logout").status_code == 405
