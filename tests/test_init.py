from __future__ import annotations

from pathlib import Path

from strucin.cli.main import main


def test_init_creates_config_file(tmp_path: Path) -> None:
    result = main(["init", "--path", str(tmp_path)])
    assert result == 0
    config_path = tmp_path / ".strucin.toml"
    assert config_path.exists()
    content = config_path.read_text(encoding="utf-8")
    assert "[scan]" in content
    assert "[performance]" in content
    assert "[output]" in content


def test_init_refuses_overwrite(tmp_path: Path) -> None:
    config_path = tmp_path / ".strucin.toml"
    config_path.write_text("existing", encoding="utf-8")
    result = main(["init", "--path", str(tmp_path)])
    assert result == 1
    assert config_path.read_text(encoding="utf-8") == "existing"


def test_init_force_overwrites(tmp_path: Path) -> None:
    config_path = tmp_path / ".strucin.toml"
    config_path.write_text("old", encoding="utf-8")
    result = main(["init", "--path", str(tmp_path), "--force"])
    assert result == 0
    content = config_path.read_text(encoding="utf-8")
    assert "[scan]" in content
