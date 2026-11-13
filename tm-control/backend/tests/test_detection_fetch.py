"""The record of a Frigate+ model's download and the background wait that follows Frigate's save."""

import pytest
from placeholders import PLACEHOLDER_KEY

from tm_control.adapters import frigate, httpjson
from tm_control.modules.detection import fetch, picker
from tm_control.modules.detection.fetch import POLL, WAIT, Fetches, wait

MODEL_A = "a" * 32
MODEL_B = "b" * 32
TEXT = f"detectors:\n  coral:\n    type: edgetpu\nmodel:\n  path: plus://{MODEL_A}\n"
OLD = "model:\n  path: /config/model_cache/old.tflite\n"  # what Frigate has until the save writes TEXT
TOO_LONG = (
    "Frigate didn't finish downloading the model in 10 minutes. Check the device's internet connection, then try "
    "again."
)
STOPPED = "Frigate stopped before the download finished. Try again once Frigate is running."
FRIGATE_HEADER_LINES = (
    "Your configuration is invalid.\nSee the official documentation at docs.frigate.video.\n"
)


def downloading() -> Fetches:
    fetches = Fetches()
    assert fetches.start(MODEL_A)
    return fetches


def answers(monkeypatch, save, raw=None):
    """frigate.save_config answers save (a tuple, or an exception it raises); config_raw answers raw."""
    sent = []

    def save_config(text, timeout=frigate.SAVE_TIMEOUT):
        sent.append((text, timeout))
        if isinstance(save, Exception):
            raise save
        return save

    monkeypatch.setattr(frigate, "save_config", save_config)
    monkeypatch.setattr(frigate, "config_raw", lambda: raw)
    return sent


def raws(monkeypatch, *values):
    """frigate.config_raw answers each value in turn (an exception is raised), then the last one again."""
    values = list(values)

    def config_raw():
        value = values.pop(0) if len(values) > 1 else values[0]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(frigate, "config_raw", config_raw)


class Sleeps(list):
    """A sleep that only records how long it was asked to sleep."""

    def __call__(self, seconds):
        self.append(seconds)


def clock(*times):
    values = iter(times)
    return lambda: next(values)


def never_saved():
    raise AssertionError("on_saved was called")


def test_start_refuses_a_second_download_and_finish_releases_it():
    fetches = Fetches()
    assert fetches.current() is None and not fetches.downloading()
    assert fetches.start(MODEL_A)
    assert not fetches.start(MODEL_B)
    assert fetches.current() == fetch.Fetch(MODEL_A, "downloading", None)
    assert fetches.downloading()
    fetches.finish("saved")
    assert fetches.current() == fetch.Fetch(MODEL_A, "saved", None)
    assert not fetches.downloading()
    assert fetches.start(MODEL_B)
    assert fetches.current() == fetch.Fetch(MODEL_B, "downloading", None)


def test_clear_drops_a_finished_record_but_not_a_running_one():
    fetches = downloading()
    fetches.clear()
    assert fetches.current() == fetch.Fetch(MODEL_A, "downloading", None)
    fetches.finish("failed", "Frigate answered 503 to the save.")
    assert fetches.current() == fetch.Fetch(MODEL_A, "failed", "Frigate answered 503 to the save.")
    fetches.clear()
    assert fetches.current() is None
    fetches.clear()
    assert fetches.current() is None


def test_begin_use_refuses_while_a_download_runs_or_another_use_is_in_flight():
    assert downloading().begin_use() == "downloading"
    fetches = Fetches()
    assert fetches.begin_use() is None
    assert fetches.begin_use() == "changing"
    fetches.end_use()
    assert fetches.begin_use() is None


def test_start_refuses_while_a_use_is_in_flight_unless_its_caller_holds_it():
    fetches = Fetches()
    assert fetches.begin_use() is None
    assert not fetches.start(MODEL_A)
    assert fetches.current() is None
    assert fetches.start(MODEL_A, holding_use=True)
    fetches.end_use()
    assert fetches.begin_use() == "downloading"


def test_a_finished_download_lets_a_use_begin():
    fetches = downloading()
    fetches.finish("saved")
    assert fetches.begin_use() is None


def test_a_200_calls_on_saved_then_records_saved(monkeypatch):
    sent = answers(monkeypatch, (200, "Config successfully saved."))
    fetches = downloading()
    seen = []
    wait(fetches, TEXT, lambda: seen.append(fetches.current().state))
    assert seen == ["downloading"]
    assert sent == [(TEXT, WAIT)]
    assert fetches.current() == fetch.Fetch(MODEL_A, "saved", None)


def test_no_answer_with_the_config_saved_counts_as_saved(monkeypatch):
    answers(monkeypatch, (None, None), raw=TEXT)
    fetches = downloading()
    seen = []
    sleeps = Sleeps()
    wait(fetches, TEXT, lambda: seen.append(fetches.current().state), clock=clock(0, 600), sleep=sleeps)
    assert seen == ["downloading"]
    assert sleeps == []
    assert fetches.current() == fetch.Fetch(MODEL_A, "saved", None)


def test_a_validation_refusal_is_recorded_with_frigates_lines(monkeypatch):
    refusal = FRIGATE_HEADER_LINES + (
        "Line 3: model -> path - Value error, Model does not support detector type of edgetpu\n"
    )
    answers(monkeypatch, (400, refusal))
    fetches = downloading()
    wait(fetches, TEXT, never_saved)
    assert fetches.current() == fetch.Fetch(
        MODEL_A, "refused",
        "Frigate refused the model: Line 3: model -> path - Value error, Model does not support detector type of "
        "edgetpu",
    )


def test_a_refusal_without_lines_says_so(monkeypatch):
    answers(monkeypatch, (400, None))
    fetches = downloading()
    wait(fetches, TEXT, never_saved)
    assert fetches.current() == fetch.Fetch(MODEL_A, "refused", "Frigate refused the model.")


def test_a_traceback_refusal_keeps_its_last_line_and_no_key(monkeypatch):
    refusal = "\n" + FRIGATE_HEADER_LINES + "\n" + (
        "Traceback (most recent call last):\n"
        '  File "/opt/frigate/frigate/plus.py", line 1, in _get_valid_token\n'
        "    raise Exception(\n"
        f"Exception: Unable to refresh API token: {PLACEHOLDER_KEY}\n"
    )
    answers(monkeypatch, (400, refusal))
    fetches = downloading()
    wait(fetches, TEXT, never_saved)
    record = fetches.current()
    assert record.state == "refused"
    assert record.message.startswith("Frigate refused the model: Exception: Unable to refresh API token")
    assert "Traceback" not in record.message
    assert PLACEHOLDER_KEY not in record.message
    assert PLACEHOLDER_KEY[:20] not in record.message


def test_no_answer_after_the_wait_says_ten_minutes(monkeypatch):
    answers(monkeypatch, (None, None), raw=OLD)
    fetches = downloading()
    sleeps = Sleeps()
    wait(fetches, TEXT, never_saved, clock=clock(0, 600), sleep=sleeps)
    assert sleeps == []
    assert fetches.current() == fetch.Fetch(MODEL_A, "failed", TOO_LONG)


def test_no_answer_just_inside_the_wait_still_says_ten_minutes(monkeypatch):
    answers(monkeypatch, (None, None), raw=OLD)
    fetches = downloading()
    wait(fetches, TEXT, never_saved, clock=clock(100, 100 + WAIT - 5), sleep=Sleeps())
    assert fetches.current() == fetch.Fetch(MODEL_A, "failed", TOO_LONG)


def test_no_answer_sooner_says_frigate_stopped(monkeypatch):
    answers(monkeypatch, (None, None), raw=None)
    fetches = downloading()
    sleeps = Sleeps()
    wait(fetches, TEXT, never_saved, clock=clock(0, 12), sleep=sleeps)
    assert sleeps == []
    assert fetches.current() == fetch.Fetch(MODEL_A, "failed", STOPPED)


def test_no_answer_with_the_old_config_polls_until_the_wait_ends(monkeypatch):
    answers(monkeypatch, (None, None))
    raws(monkeypatch, OLD)
    fetches = downloading()
    sleeps = Sleeps()
    wait(fetches, TEXT, never_saved, clock=clock(0, 12, 300, WAIT - 6, WAIT - 5), sleep=sleeps)
    assert sleeps == [POLL, POLL, POLL]
    assert fetches.current() == fetch.Fetch(MODEL_A, "failed", TOO_LONG)


def test_a_504_is_followed_until_frigate_has_saved_the_config(monkeypatch):
    # Frigate's nginx gives up on the save after 6 minutes; Frigate itself keeps downloading, then writes the file
    answers(monkeypatch, (504, None))
    raws(monkeypatch, OLD, OLD, TEXT)
    fetches = downloading()
    seen = []
    sleeps = Sleeps()
    wait(fetches, TEXT, lambda: seen.append(fetches.current().state), clock=clock(0, 360, 365), sleep=sleeps)
    assert sleeps == [POLL, POLL]
    assert seen == ["downloading"]
    assert fetches.current() == fetch.Fetch(MODEL_A, "saved", None)


def test_a_504_then_frigate_down_says_stopped_without_waiting_out_the_clock(monkeypatch):
    answers(monkeypatch, (504, None))
    raws(monkeypatch, OLD, None)
    fetches = downloading()
    sleeps = Sleeps()
    wait(fetches, TEXT, never_saved, clock=clock(0, 360), sleep=sleeps)
    assert sleeps == [POLL]
    assert fetches.current() == fetch.Fetch(MODEL_A, "failed", STOPPED)


@pytest.mark.parametrize("status", [None, 502, 504])
def test_no_answer_a_502_and_a_504_are_all_followed(monkeypatch, status):
    answers(monkeypatch, (status, None))
    raws(monkeypatch, OLD, TEXT)
    fetches = downloading()
    saved = []
    wait(fetches, TEXT, lambda: saved.append(True), clock=clock(0, 10), sleep=Sleeps())
    assert saved == [True]
    assert fetches.current() == fetch.Fetch(MODEL_A, "saved", None)


def test_an_error_mid_poll_never_leaves_it_downloading(monkeypatch):
    answers(monkeypatch, (504, None))
    raws(monkeypatch, OLD, OLD, OSError(PLACEHOLDER_KEY))
    fetches = downloading()
    wait(fetches, TEXT, never_saved, clock=clock(0, 10, 20), sleep=Sleeps())
    assert fetches.current() == fetch.Fetch(MODEL_A, "failed", "The download couldn't be followed: OSError")


def test_another_status_is_failed_with_the_status(monkeypatch):
    answers(monkeypatch, (503, None))
    fetches = downloading()
    wait(fetches, TEXT, never_saved)
    assert fetches.current() == fetch.Fetch(MODEL_A, "failed", "Frigate answered 503 to the save.")


def test_an_error_in_the_wait_never_leaves_it_downloading(monkeypatch):
    answers(monkeypatch, RuntimeError(f"boom {PLACEHOLDER_KEY}"))
    fetches = downloading()
    wait(fetches, TEXT, never_saved)
    assert fetches.current() == fetch.Fetch(MODEL_A, "failed", "The download couldn't be followed: RuntimeError")


def test_an_error_reading_the_config_back_is_failed(monkeypatch):
    answers(monkeypatch, (None, None))

    def config_raw():
        raise ValueError(PLACEHOLDER_KEY)

    monkeypatch.setattr(frigate, "config_raw", config_raw)
    fetches = downloading()
    wait(fetches, TEXT, never_saved, clock=clock(0, 12), sleep=Sleeps())
    assert fetches.current() == fetch.Fetch(MODEL_A, "failed", "The download couldn't be followed: ValueError")


def test_an_error_in_on_saved_is_failed_too(monkeypatch):
    answers(monkeypatch, (200, "Config successfully saved."))
    fetches = downloading()

    def on_saved():
        raise OSError(PLACEHOLDER_KEY)

    wait(fetches, TEXT, on_saved)
    assert fetches.current() == fetch.Fetch(MODEL_A, "failed", "The download couldn't be followed: OSError")


def test_spawn_runs_the_target_on_a_daemon_thread():
    import threading

    done = threading.Event()
    seen = []

    def target():
        seen.append(threading.current_thread().daemon)
        done.set()

    fetch.spawn(target)
    assert done.wait(5)
    assert seen == [True]


def test_save_config_passes_its_timeout(monkeypatch):
    calls = []

    def post(url, body, content_type, headers=None, timeout=None, method="POST"):
        calls.append((url, body, content_type, timeout))
        return 200, b'{"success": true, "message": "Config successfully saved."}'

    monkeypatch.setattr(httpjson, "post", post)
    assert frigate.save_config("model: {}\n", timeout=WAIT) == (200, "Config successfully saved.")
    assert calls[-1][3] == 600
    frigate.save_config("model: {}\n")
    assert calls[-1][3] == frigate.SAVE_TIMEOUT


def test_the_picker_edits_a_config_through_its_public_function():
    text = "detectors:\n  coral:\n    type: edgetpu\n"
    assert picker.edited(text, {"path": f"plus://{MODEL_A}"}).endswith(f"model:\n  path: plus://{MODEL_A}\n")
    with pytest.raises(picker.UseError):
        picker.edited("- a list\n", {"path": f"plus://{MODEL_A}"})
