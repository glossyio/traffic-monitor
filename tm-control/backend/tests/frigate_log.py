"""Synthetic Frigate 0.18 journal lines shared by test modules: the block Frigate prints for a config that doesn't
validate before it starts in safe mode, and a traceback's ending."""

MODEL_ID = "abc123"


def validation_block(*messages: str) -> list[str]:
    """What Frigate prints for each validation error (Line #, Key, Value, Message), between its banners."""
    lines = [
        "*************************************************************",
        "*** Your config file is not valid!                        ***",
        "*** Please check the docs at                              ***",
        "*** https://docs.frigate.video/configuration/             ***",
        "*************************************************************",
        "*** Config Validation Errors                              ***",
        "*************************************************************",
    ]
    for number, message in enumerate(messages, start=3):
        lines += [f"Line #  : {number}", "Key     : model -> path", f"Value   : plus://{MODEL_ID}", f"Message : {message}"]
    return lines + [
        "*************************************************************",
        "*** End Config Validation Errors                          ***",
        "*************************************************************",
        "Starting Frigate in safe mode.",
    ]


DETECTOR_MESSAGE = "Value error, Model does not support detector type of edgetpu"
SAFE_MODE_LINES = validation_block(DETECTOR_MESSAGE)

# The end of a run that stopped while downloading a Frigate+ model, as journalctl -o short-iso prints it.
TRACEBACK_TAIL = [
    "2026-11-04T10:00:00+0000 tm-test frigate[812]: Traceback (most recent call last):",
    '2026-11-04T10:00:00+0000 tm-test frigate[812]:   File "/opt/frigate/frigate/plus.py", line 90, in _get',
    "2026-11-04T10:00:00+0000 tm-test frigate[812]:     raise Exception(r.text)",
    '2026-11-04T10:00:00+0000 tm-test frigate[812]: Exception: {"message":"Unauthorized"}',
    "2026-11-04T10:00:01+0000 tm-test systemd[1]: frigate.service: Main process exited, code=exited, status=1/FAILURE",
    "2026-11-04T10:00:01+0000 tm-test systemd[1]: frigate.service: Failed with result 'exit-code'.",
]

# Frigate's exceptions for a Frigate+ key its server refused and for a plus:// model with no key set (bench A3)
REFUSED_KEY_LINE = 'Exception: Unable to refresh API token: {"message":"User not found"}'
NO_KEY_LINE = "Exception: Plus API key not set. See https://docs.frigate.video/integrations/plus#set-your-api-key"


def crash_loop_tail(last_line: str) -> list[str]:
    """The end of a run as journalctl -o short-iso printed it on the bench: Frigate's s6 supervisor stamps each line
    it forwards after journalctl's own prefix; systemd's lines have no such stamp."""
    frigate = [
        "Traceback (most recent call last):",
        '  File "/opt/frigate/frigate/plus.py", line 63, in _refresh_token_if_needed',
        "    raise Exception(",
        last_line,
        "Service Frigate exited with code 1 (by signal 0)",
    ]
    stamp = "2026-11-04T18:07:36+0000 tm-test frigate[2201]: 2026-11-04 18:07:36.850573607  "
    return [stamp + text for text in frigate] + [
        "2026-11-04T18:07:37+0000 tm-test systemd[1]: frigate.service: Main process exited, code=exited, status=1/FAILURE",
        "2026-11-04T18:07:37+0000 tm-test systemd[1]: frigate.service: Failed with result 'exit-code'.",
        "2026-11-04T18:07:47+0000 tm-test systemd[1]: frigate.service: Scheduled restart job, restart counter is at 3.",
    ]


CRASH_LOOP_TAIL = crash_loop_tail(REFUSED_KEY_LINE)
