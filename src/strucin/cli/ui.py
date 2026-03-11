from __future__ import annotations

import sys
from typing import Any

_rich_available = False
try:
    from rich.console import Console
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
    from rich.table import Table

    _rich_available = True
except ImportError:
    pass

_console: Any = None
_err_console: Any = None


def _get_console() -> Any:
    global _console  # noqa: PLW0603
    if _rich_available and _console is None:
        _console = Console()
    return _console


def _get_err_console() -> Any:
    global _err_console  # noqa: PLW0603
    if _rich_available and _err_console is None:
        _err_console = Console(stderr=True)
    return _err_console


def print_error(message: str) -> None:
    err = _get_err_console()
    if err is not None:
        err.print(f"[bold red]Error:[/bold red] {message}")
    else:
        print(f"Error: {message}", file=sys.stderr)


def print_success(message: str) -> None:
    con = _get_console()
    if con is not None:
        con.print(f"[bold green]✓[/bold green] {message}")
    else:
        print(message)


def print_info(message: str) -> None:
    con = _get_console()
    if con is not None:
        con.print(f"[dim]{message}[/dim]")
    else:
        print(message)


def print_warning(message: str) -> None:
    err = _get_err_console()
    if err is not None:
        err.print(f"[bold yellow]Warning:[/bold yellow] {message}")
    else:
        print(f"Warning: {message}", file=sys.stderr)


def print_progress(step: int, total: int, message: str) -> None:
    if _rich_available:
        con = _get_console()
        con.print(f"[bold cyan][{step}/{total}][/bold cyan] {message}")
    else:
        safe_total = max(total, 1)
        ratio = min(max(step / safe_total, 0.0), 1.0)
        width = 20
        filled = int(width * ratio)
        bar = "#" * filled + "-" * (width - filled)
        print(f"[{bar}] {step}/{safe_total} {message}")


def create_progress() -> Any:
    if _rich_available:
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        )
    return None


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    if _rich_available:
        table = Table(show_edge=False, pad_edge=False)
        for header in headers:
            table.add_column(header, style="bold")
        for row in rows:
            table.add_row(*row)
        con = _get_console()
        with con.capture() as capture:
            con.print(table)
        return str(capture.get()).rstrip()

    all_rows = [headers, *rows]
    widths = [max(len(row[index]) for row in all_rows) for index in range(len(headers))]

    def format_row(row: list[str]) -> str:
        return " | ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))

    separator = "-+-".join("-" * width for width in widths)
    rendered = [format_row(headers), separator]
    rendered.extend(format_row(row) for row in rows)
    return "\n".join(rendered)
