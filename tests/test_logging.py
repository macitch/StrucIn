from __future__ import annotations

import json

import pytest

from strucin.utils.logging import CommandTiming, emit_structured_log


def test_emit_structured_log_writes_json_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    emit_structured_log(enabled=True, event="test_event", key="value")
    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err.strip())
    assert payload["event"] == "test_event"
    assert payload["key"] == "value"
    assert "ts" in payload


def test_emit_structured_log_disabled_produces_no_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit_structured_log(enabled=False, event="ignored")
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


def test_emit_structured_log_output_is_sorted(capsys: pytest.CaptureFixture[str]) -> None:
    emit_structured_log(enabled=True, event="e", z_last="z", a_first="a")
    captured = capsys.readouterr()
    payload = json.loads(captured.err.strip())
    keys = list(payload.keys())
    assert keys == sorted(keys)


def test_command_timing_fields() -> None:
    timing = CommandTiming(stage="analyze", duration_ms=123.4)
    assert timing.stage == "analyze"
    assert timing.duration_ms == 123.4
