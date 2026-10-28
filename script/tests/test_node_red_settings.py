"""The Node-RED editor trusts only the reverse proxy's token: settings.js checks what tm-control mints."""

import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys

import pytest
from tmsetup_render import REPO

sys.path.insert(0, str(REPO / "tm-control" / "backend"))

from tm_control.core.auth import NodeRedToken  # noqa: E402  (needs tm-control/backend on sys.path)

SETTINGS = REPO / "container/node-red-tm/data/settings.js"
KEY = "placeholder-token-key"
NOW = 1_800_000_000
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def mint(username, role, now=NOW, key=KEY):
    return NodeRedToken(key).mint(username, role, now=now)


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def signed(body_bytes, key=KEY):
    """A token whose signature is right, built without tm-control, so a bad body reaches the claims checks."""
    body = b64(body_bytes)
    return f"{body}.{b64(hmac.new(key.encode(), body.encode(), hashlib.sha256).digest())}"


def run_node(script, env=None):
    result = subprocess.run(
        ["node", "-e", f"const s = require({json.dumps(str(SETTINGS))});\n{script}"],
        capture_output=True, text=True, timeout=30, env=env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def verify(token, key, now=NOW):
    """Run settings.js's verifier on any JSON value, so non-string tokens can be passed too."""
    return run_node(
        f"const u = s.verifyProxyToken({json.dumps(token)}, {json.dumps(key)}, {now});\n"
        "console.log(u === null ? 'null' : JSON.stringify(u));"
    )


def test_settings_have_no_built_in_user_and_read_the_proxy_header():
    text = SETTINGS.read_text()
    assert "users: []" in text
    assert 'tokenHeader: "x-tm-nr-token"' in text
    assert "$2a$08$" not in text
    assert "userMenu: false" in text
    assert "credentialSecret: process.env.NODE_RED_CREDENTIAL_SECRET" in text


@needs_node
@pytest.mark.parametrize("key, token, expected", [
    (KEY, mint("admin", "admin"), "admin"),
    ("", mint("admin", "admin"), None),
    ("other-key", mint("admin", "admin"), None),
    (KEY, mint("v", "viewer"), None),
    (KEY, mint("admin", "admin", now=NOW - 600), None),
    (KEY, "garbage", None),
], ids=["admin", "no-key", "wrong-key", "viewer", "expired", "garbage"])
def test_javascript_verifier_agrees_with_the_python_minter(key, token, expected):
    out = verify(token, key)
    if expected is None:
        assert out == "null"
    else:
        assert json.loads(out) == {"username": expected, "permissions": "*"}


@needs_node
def test_a_token_is_refused_from_the_second_it_expires():
    """tm-control's verifier refuses at now >= exp; the editor must not accept a token tm-control would refuse."""
    assert verify(mint("admin", "admin", now=NOW - 300), KEY) == "null"
    assert json.loads(verify(mint("admin", "admin", now=NOW - 299), KEY))["username"] == "admin"


@needs_node
@pytest.mark.parametrize("token", [
    None,
    12345,
    {"u": "admin"},
    "",
    ".",
    "a.b.c",
    mint("admin", "admin") + ".x",
    "." + mint("admin", "admin").split(".")[1],
    mint("admin", "admin").split(".")[0] + ".",
    mint("admin", "admin").split(".")[0],
    mint("admin", "admin").replace(".", ".!", 1),
    mint("admin", "admin") + "=",
    signed(b"not json"),
    signed(b"[1, 2]"),
    signed(b"null"),
    signed(b'"admin"'),
    signed(json.dumps({"r": "admin", "exp": NOW + 300}).encode()),
    signed(json.dumps({"u": "admin", "exp": NOW + 300}).encode()),
    signed(json.dumps({"u": "admin", "r": "admin"}).encode()),
    signed(json.dumps({"u": 1, "r": "admin", "exp": NOW + 300}).encode()),
    signed(json.dumps({"u": "admin", "r": ["admin"], "exp": NOW + 300}).encode()),
    signed(json.dumps({"u": "admin", "r": "admin", "exp": str(NOW + 300)}).encode()),
    signed(json.dumps({"u": "admin", "r": "admin", "exp": None}).encode()),
    signed(b'{"u":"admin","r":"admin","exp":1e999}'),
    signed(json.dumps({"u": "admin", "r": "Admin", "exp": NOW + 300}).encode()),
], ids=[
    "null", "number", "object", "empty", "only-dot", "three-parts", "extra-part", "no-body", "no-signature",
    "no-dot", "signature-not-base64url", "padded-signature", "body-not-json", "body-array", "body-null",
    "body-string", "no-u", "no-r", "no-exp", "u-not-string", "r-not-string", "exp-string", "exp-null",
    "exp-infinite", "r-case",
])
def test_javascript_verifier_refuses_malformed_tokens(token):
    assert verify(token, KEY) == "null"


@needs_node
def test_an_independently_signed_admin_token_is_accepted():
    """The signature covers the body's base64url text, exactly as tm-control signs it."""
    token = signed(json.dumps({"u": "admin", "r": "admin", "exp": NOW + 300}, separators=(",", ":")).encode())
    assert token == mint("admin", "admin")
    assert json.loads(verify(token, KEY))["username"] == "admin"


@needs_node
def test_editor_login_reads_the_key_from_the_environment_and_fails_closed_without_it():
    """A node-red-tm.env from before the proxy login has no TM_NR_TOKEN_KEY: every token is refused (Review Focus 4)."""
    script = (
        f"s.adminAuth.tokens({json.dumps(mint('admin', 'admin', now=None))})"
        ".then((u) => console.log(u === null ? 'null' : u.username + ' ' + u.permissions));"
    )
    env = {key: value for key, value in os.environ.items() if key != "TM_NR_TOKEN_KEY"}
    assert run_node(script, env=env) == "null"
    assert run_node(script, env={**env, "TM_NR_TOKEN_KEY": ""}) == "null"
    assert run_node(script, env={**env, "TM_NR_TOKEN_KEY": "other-key"}) == "null"
    assert run_node(script, env={**env, "TM_NR_TOKEN_KEY": KEY}) == "admin *"
