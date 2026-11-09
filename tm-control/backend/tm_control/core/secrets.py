"""Device secrets: one file per secret in /etc/traffic-monitor/secrets/, generated once by tmsetup (tasks/secrets.yml).

Errors name the secret, never its value or path.
"""

from pathlib import Path

SESSION_KEY = "tm_control_session_key"
FRIGATE_PROXY_SECRET = "frigate_proxy_secret"
NODE_RED_TOKEN_KEY = "node_red_token_key"
NAMES = (SESSION_KEY, FRIGATE_PROXY_SECRET, NODE_RED_TOKEN_KEY)


class MissingSecret(RuntimeError):
    """A secret file is missing, unreadable, or empty."""

    def __init__(self, name):
        super().__init__(f"secret {name} is missing, unreadable, or empty")
        self.name = name


class Secrets:
    def __init__(self, dir: Path):
        self.dir = Path(dir)
        self._cache = {}

    def read(self, name: str) -> str:
        if not name or "/" in name or name.startswith("."):
            raise ValueError("a secret name is a plain file name")
        if name not in self._cache:
            try:
                value = (self.dir / name).read_text(encoding="utf-8").strip()
            except (OSError, UnicodeDecodeError):
                raise MissingSecret(name) from None
            if not value:
                raise MissingSecret(name)
            self._cache[name] = value
        return self._cache[name]

    @property
    def session_key(self) -> str:
        return self.read(SESSION_KEY)

    @property
    def frigate_proxy_secret(self) -> str:
        return self.read(FRIGATE_PROXY_SECRET)

    @property
    def node_red_token_key(self) -> str:
        return self.read(NODE_RED_TOKEN_KEY)


class FakeSecrets(Secrets):
    """Fixed, public values for fake mode and tests. Never used on a device."""

    def __init__(self):
        super().__init__(Path("/nonexistent"))

    def read(self, name: str) -> str:
        return f"fake-{name}-not-secret"
