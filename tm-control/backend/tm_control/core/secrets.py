"""Device secrets: one file per secret in /etc/traffic-monitor/secrets/. Generated secrets are made once by tmsetup
(tasks/secrets.yml); entered secrets are typed in by an operator (a root job writes the file) and an empty file means
not set.

Errors name the secret, never its value or path.
"""

import re
from pathlib import Path

SESSION_KEY = "tm_control_session_key"
FRIGATE_PROXY_SECRET = "frigate_proxy_secret"
NODE_RED_TOKEN_KEY = "node_red_token_key"
NODE_RED_INTERNAL_TOKEN = "node_red_internal_token"  # X-TM-Internal-Token for Node-RED's /tm-internal/ endpoints
# The ones tm-control needs to start
NAMES = (SESSION_KEY, FRIGATE_PROXY_SECRET, NODE_RED_TOKEN_KEY, NODE_RED_INTERNAL_TOKEN)
PLATE_RECOGNIZER_TOKEN = "plate_recognizer_token"
PLATE_RECOGNIZER_LICENSE_KEY = "plate_recognizer_license_key"
THINGSBOARD_ACCESS_TOKEN = "thingsboard_access_token"
# Every secret tmsetup generates (tmsetup_secret_names), whether tm-control uses it or not: diagnostics strips them all.
GENERATED_SECRETS = (
    "go2rtc_rtsp_password", SESSION_KEY, FRIGATE_PROXY_SECRET, NODE_RED_TOKEN_KEY, NODE_RED_INTERNAL_TOKEN,
)
# The ones an operator enters (tmsetup_entered_secret_names); a file may be empty, which means not set.
ENTERED_SECRETS = (THINGSBOARD_ACCESS_TOKEN, PLATE_RECOGNIZER_TOKEN, PLATE_RECOGNIZER_LICENSE_KEY)
DEVICE_SECRETS = GENERATED_SECRETS + ENTERED_SECRETS

# What each entered secret's value may be, and the rule in words for a message. The ThingsBoard token goes into the
# upload URL's path, so it takes only URL-unreserved characters; the Plate Recognizer values go into a header and an
# env line, so they take printable ASCII with no spaces.
_URL_SAFE = r"[A-Za-z0-9._~-]{1,256}"
_PRINTABLE = r"[\x21-\x7e]{1,256}"
VALUE_PATTERNS = {
    THINGSBOARD_ACCESS_TOKEN: _URL_SAFE,
    PLATE_RECOGNIZER_TOKEN: _PRINTABLE,
    PLATE_RECOGNIZER_LICENSE_KEY: _PRINTABLE,
}
VALUE_RULES = {
    THINGSBOARD_ACCESS_TOKEN: "1 to 256 letters, digits, and . _ ~ -",
    PLATE_RECOGNIZER_TOKEN: "1 to 256 printable ASCII characters with no spaces",
    PLATE_RECOGNIZER_LICENSE_KEY: "1 to 256 printable ASCII characters with no spaces",
}


def is_valid_value(name: str, value: str) -> bool:
    """Whether value meets the entered secret's pattern, as a whole."""
    return re.fullmatch(VALUE_PATTERNS[name], value) is not None


class MissingSecret(RuntimeError):
    """A secret file is missing, unreadable, or empty."""

    def __init__(self, name):
        super().__init__(f"secret {name} is missing, unreadable, or empty")
        self.name = name


class Secrets:
    def __init__(self, dir: Path):
        self.dir = Path(dir)
        self._cache = {}

    @staticmethod
    def _check_name(name: str) -> None:
        if not name or "/" in name or name.startswith("."):
            raise ValueError("a secret name is a plain file name")

    def _value(self, name: str) -> str:
        """The file's content, stripped; empty when it is missing, unreadable, or blank."""
        try:
            return (self.dir / name).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return ""

    def read(self, name: str) -> str:
        """A secret's value. Generated secrets are read once; an entered one is read every time, because a job can
        change it while tm-control runs."""
        self._check_name(name)
        if name in self._cache:
            return self._cache[name]
        value = self._value(name)
        if not value:
            raise MissingSecret(name)
        if name in GENERATED_SECRETS:
            self._cache[name] = value
        return value

    def is_set(self, name: str) -> bool:
        """Whether the secret's file holds a value. Never raises for a readable name, whatever state the file is in."""
        self._check_name(name)
        return bool(self._value(name))

    def ends_with(self, name: str, count: int = 4) -> str | None:
        """The last `count` characters of the value. None when it isn't set, and when the ending would be more than a
        third of it (fewer than 3 * count characters, or count below 1), so a short secret is never shown whole."""
        self._check_name(name)
        value = self._value(name)
        if count < 1 or len(value) < 3 * count:
            return None
        return value[-count:]

    @property
    def session_key(self) -> str:
        return self.read(SESSION_KEY)

    @property
    def frigate_proxy_secret(self) -> str:
        return self.read(FRIGATE_PROXY_SECRET)

    @property
    def node_red_token_key(self) -> str:
        return self.read(NODE_RED_TOKEN_KEY)

    @property
    def node_red_internal_token(self) -> str:
        return self.read(NODE_RED_INTERNAL_TOKEN)


class FakeSecrets(Secrets):
    """Fixed, public values for fake mode and tests. Never used on a device.

    The generated secrets always have a value. The entered ones are empty until a test or the fake job sets
    `entered[name]`.
    """

    def __init__(self):
        super().__init__(Path("/nonexistent"))
        self.entered = dict.fromkeys(ENTERED_SECRETS, "")

    def _value(self, name: str) -> str:
        if name in self.entered:
            return self.entered[name].strip()
        return f"fake-{name}-not-secret"

    def read(self, name: str) -> str:
        value = self._value(name)
        if not value:
            raise MissingSecret(name)
        return value
