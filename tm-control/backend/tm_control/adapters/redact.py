"""Strip secrets from text that leaves the device, such as the diagnostics download."""

import re

REDACTED = "<redacted>"

# A key that names a secret, then an optional closing quote and `=` or `:`, then the value up to the next whitespace.
# The key may end a longer name (TM_MQTT_BROKER_PASSWORD, NODE_RED_CREDENTIAL_SECRET, TM_NR_TOKEN_KEY) but not run
# on into another word (secrets_dir, tokens). Spaces and tabs only around the separator, so a key at a line's end
# doesn't take the next line's first word.
_KEY_VALUE = re.compile(
    r"(?i)(?:password|passwd|secret|token|setup[ _-]?code)(?:[_-]?key)?(?![A-Za-z0-9_])"
    r"[\"']?[ \t]*[=:][ \t]*(?P<value>\S+)"
)


def _spans(text: str, values: list[str]) -> list[tuple[int, int]]:
    """Where text holds a secret: every occurrence of each value, and the value after each secret-looking key."""
    spans = [match.span("value") for match in _KEY_VALUE.finditer(text)]
    for value in sorted({value for value in values if value}):
        start = text.find(value)
        while start >= 0:
            spans.append((start, start + len(value)))
            start = text.find(value, start + 1)
    return spans


def redact(text: str, values: list[str]) -> str:
    """text with each secret replaced by REDACTED: every occurrence of each of `values`, and the value after every
    secret-looking key (password=, token:, the setup code, ...), whose key and separator stay.

    Both kinds of span are found in the original text, then overlapping and touching spans are merged and each merged
    span becomes one REDACTED. So a value that is also a key's word (frigate.env's default password is "password")
    can't hide the secret after that key, and a value with spaces in it is redacted whole even after a key.
    """
    out, end = [], 0
    for start, stop in sorted(_spans(text, values)):
        if out and start <= end:  # overlaps or touches the span before it
            end = max(end, stop)
            continue
        if out:
            out.append(REDACTED)
        out.append(text[end:start])
        end = stop
    if not out:
        return text
    out.append(REDACTED)
    out.append(text[end:])
    return "".join(out)
