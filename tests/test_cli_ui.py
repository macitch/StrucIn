from __future__ import annotations

import pytest

from strucin.cli.ui import format_table, print_error, print_progress

# ---------------------------------------------------------------------------
# format_table
# ---------------------------------------------------------------------------


def test_format_table_basic() -> None:
    result = format_table(["Name", "LOC"], [["pkg.a", "120"], ["pkg.b", "80"]])
    assert "Name" in result
    assert "LOC" in result
    assert "pkg.a" in result
    assert "pkg.b" in result
    assert "120" in result


def test_format_table_single_column() -> None:
    result = format_table(["Module"], [["pkg.a"], ["pkg.b"]])
    assert "pkg.a" in result
    assert "pkg.b" in result


def test_format_table_empty_rows() -> None:
    result = format_table(["Header"], [])
    assert "Header" in result


def test_format_table_contains_all_data() -> None:
    result = format_table(["Col"], [["val"]])
    assert "Col" in result
    assert "val" in result


# ---------------------------------------------------------------------------
# print_progress
# ---------------------------------------------------------------------------


def test_print_progress_full(capsys: pytest.CaptureFixture[str]) -> None:
    print_progress(10, 10, "done")
    out = capsys.readouterr().out
    assert "10" in out
    assert "done" in out


def test_print_progress_zero_step(capsys: pytest.CaptureFixture[str]) -> None:
    print_progress(0, 10, "start")
    out = capsys.readouterr().out
    assert "0" in out
    assert "10" in out


def test_print_progress_step_exceeds_total(capsys: pytest.CaptureFixture[str]) -> None:
    """step > total must not crash; ratio is clamped to 1.0."""
    print_progress(20, 10, "overflow")
    out = capsys.readouterr().out
    assert "overflow" in out


def test_print_progress_zero_total(capsys: pytest.CaptureFixture[str]) -> None:
    """total=0 must not raise ZeroDivisionError."""
    print_progress(0, 0, "empty")
    capsys.readouterr()  # just ensure no exception


# ---------------------------------------------------------------------------
# print_error
# ---------------------------------------------------------------------------


def test_print_error_writes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    print_error("something went wrong")
    captured = capsys.readouterr()
    assert "something went wrong" in captured.err
    assert captured.out == ""
