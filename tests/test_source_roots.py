"""Source-root regressions: import identities, cycle gates, and cached indexes."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from strucin.cli.hooks import main_complexity, main_cycles
from strucin.cli.main import main
from strucin.core import explainer, semantic
from strucin.core.analyzer import analyze_repository
from strucin.core.config import load_config
from strucin.core.import_resolver import _resolve_internal_targets_for_import
from strucin.core.indexer import FileMetadata, scan_repository
from strucin.core.models import ImportInfo
from strucin.core.source_roots import resolve_source_roots
from strucin.exceptions import AnalysisError, ConfigError


def write(root: Path, path: str, content: str = "") -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def cycle_repo(root: Path, layout: str) -> list[str]:
    prefixes = {
        "flat": ("", ""),
        "src": ("src/", "src/"),
        "namespace": ("src/", "src/"),
        "multiple": ("lib_one/", "lib_two/"),
    }
    left, right = prefixes[layout]
    if layout in {"flat", "src"}:
        write(root, f"{left}pkg/__init__.py")
    write(
        root,
        f"{left}pkg/a.py",
        "from pkg import b\n\ndef work():\n    if True:\n        return 1\n",
    )
    write(root, f"{right}pkg/b.py", "import pkg.a\n")
    if layout == "multiple":
        return ["lib_one", "lib_two"]
    return []


@pytest.mark.parametrize("layout", ["flat", "src", "namespace", "multiple"])
@pytest.mark.parametrize("executor", ["thread", "process"])
def test_layouts_preserve_imports_metrics_and_cycles(
    tmp_path: Path, layout: str, executor: str
) -> None:
    roots = cycle_repo(tmp_path, layout)
    result = analyze_repository(
        tmp_path, source_roots=roots or None, executor=executor, max_workers=2
    )
    assert {(edge.source, edge.target) for edge in result.dependency_graph_edges} == {
        ("pkg.a", "pkg.b"),
        ("pkg.b", "pkg.a"),
    }
    assert len(result.cycles) == 1 and set(result.cycles[0]) == {"pkg.a", "pkg.b"}
    for file in result.files:
        if file.module_path in {"pkg.a", "pkg.b"}:
            assert file.fan_in == file.fan_out == 1
    prefix = {"flat": "", "src": "src/", "namespace": "src/", "multiple": "lib_one/"}[layout]
    assert (
        next(file.path for file in result.files if file.module_path == "pkg.a")
        == f"{prefix}pkg/a.py"
    )


@pytest.mark.parametrize("layout", ["flat", "src", "namespace", "multiple"])
@pytest.mark.parametrize("override", ["config", "cli"])
def test_cli_and_hooks_detect_same_cycle(tmp_path: Path, layout: str, override: str) -> None:
    roots = cycle_repo(tmp_path, layout)
    flags: list[str] = []
    if roots:
        if override == "config":
            write(tmp_path, ".strucin.toml", f"[scan]\nsource_roots = {json.dumps(roots)}\n")
        else:
            # A CLI override must take precedence over configuration.
            write(tmp_path, ".strucin.toml", '[scan]\nsource_roots = ["."]\n')
            flags = [part for root in roots for part in ("--source-root", root)]
    assert main(["analyze", str(tmp_path), *flags]) == 0
    payload = json.loads((tmp_path / "analysis.json").read_text(encoding="utf-8"))
    assert len(payload["cycles"]) == 1 and set(payload["cycles"][0]) == {"pkg.a", "pkg.b"}
    assert main_cycles([str(tmp_path), *flags]) == 1
    assert main_complexity([str(tmp_path), "--threshold", "1", *flags]) == 1


@pytest.mark.parametrize(
    ("filename", "content", "location"),
    [
        ("pyproject.toml", '[tool.setuptools.package-dir]\n"" = "python"\n', "python/pkg"),
        ("pyproject.toml", '[tool.setuptools.packages.find]\nwhere = ["python"]\n', "python/pkg"),
        (
            "pyproject.toml",
            '[tool.setuptools.package-dir]\npkg = "implementation"\n',
            "implementation",
        ),
        (
            "pyproject.toml",
            '[tool.poetry]\npackages = [{include = "pkg", from = "python"}]\n',
            "python/pkg",
        ),
        ("setup.cfg", "[options]\npackage_dir =\n    = python\n", "python/pkg"),
        ("setup.cfg", "[options]\npackage_dir =\n    pkg = implementation\n", "implementation"),
        (
            "setup.cfg",
            "[options]\npackages = find:\n[options.packages.find]\nwhere = python\n",
            "python/pkg",
        ),
    ],
)
def test_static_packaging_metadata(
    tmp_path: Path, filename: str, content: str, location: str
) -> None:
    write(tmp_path, filename, content)
    write(tmp_path, f"{location}/__init__.py", "from . import a\n")
    write(tmp_path, f"{location}/a.py", "from . import b\n")
    write(tmp_path, f"{location}/b.py", "from pkg import a\n")
    result = analyze_repository(tmp_path, use_cache=False)
    assert {file.module_path for file in result.files} == {"pkg", "pkg.a", "pkg.b"}
    assert {(edge.source, edge.target) for edge in result.dependency_graph_edges} == {
        ("pkg", "pkg.a"),
        ("pkg.a", "pkg.b"),
        ("pkg.b", "pkg.a"),
    }
    assert set(result.cycles[0]) == {"pkg.a", "pkg.b"}


@pytest.mark.parametrize("filename", ["pyproject.toml", "setup.cfg"])
def test_explicit_roots_bypass_malformed_packaging_metadata(tmp_path: Path, filename: str) -> None:
    write(tmp_path, filename, "malformed = [")
    write(tmp_path, "custom/pkg/a.py")
    with pytest.raises(ConfigError, match="set scan.source_roots explicitly"):
        scan_repository(tmp_path)
    assert scan_repository(tmp_path, source_roots=["custom"]).files[0].module_path == "pkg.a"


def test_explicit_root_disables_src_heuristic(tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py")
    assert scan_repository(tmp_path).files[0].module_path == "pkg.a"
    assert scan_repository(tmp_path, source_roots=["."]).files[0].module_path == "src.pkg.a"


def test_src_package_is_not_stripped(tmp_path: Path) -> None:
    write(tmp_path, "src/__init__.py")
    write(tmp_path, "src/a.py", "from src import b\n")
    write(tmp_path, "src/b.py", "from . import a\n")
    result = analyze_repository(tmp_path, use_cache=False)
    assert set(result.cycles[0]) == {"src.a", "src.b"}


def test_files_outside_source_root_keep_repo_relative_identity(tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py")
    write(tmp_path, "tests/test_app.py", "import pkg.a\n")
    result = analyze_repository(tmp_path, use_cache=False)
    assert {file.module_path for file in result.files} == {"pkg.a", "tests.test_app"}
    assert len(result.dependency_graph_edges) == 1
    assert result.dependency_graph_edges[0].target == "pkg.a"


def test_named_nested_package_mapping_takes_precedence(tmp_path: Path) -> None:
    write(
        tmp_path,
        "pyproject.toml",
        '[tool.setuptools.package-dir]\n"" = "python"\n"pkg.sub" = "python/other"\n',
    )
    write(tmp_path, "python/pkg/a.py", "import pkg.sub.b\n")
    write(tmp_path, "python/other/b.py", "from .. import a\n")
    result = analyze_repository(tmp_path, use_cache=False)
    assert set(result.cycles[0]) == {"pkg.a", "pkg.sub.b"}


def test_multiple_namespace_roots_discovered_from_metadata(tmp_path: Path) -> None:
    roots = cycle_repo(tmp_path, "multiple")
    write(
        tmp_path,
        "pyproject.toml",
        f"[tool.setuptools.packages.find]\nwhere = {json.dumps(roots)}\n",
    )
    assert len(analyze_repository(tmp_path, use_cache=False).cycles) == 1


@pytest.mark.parametrize("roots", [["left", "right"], ["right", "left"]])
def test_duplicate_import_names_fail_instead_of_overwriting(
    tmp_path: Path, roots: list[str]
) -> None:
    write(tmp_path, "left/pkg/a.py", "import pkg.b\n")
    write(tmp_path, "right/pkg/a.py")
    with pytest.raises(
        AnalysisError, match="Ambiguous module 'pkg.a'.*left/pkg/a.py.*right/pkg/a.py"
    ):
        analyze_repository(tmp_path, source_roots=roots)
    assert not (tmp_path / ".strucin_cache/analysis_cache.json").exists()


@pytest.mark.parametrize("value", ['"src"', "[]", "[1]", '[""]'])
def test_invalid_source_root_config_is_rejected(tmp_path: Path, value: str) -> None:
    write(tmp_path, ".strucin.toml", f"[scan]\nsource_roots = {value}\n")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


@pytest.mark.parametrize("directory", ["../outside", "/absolute/source", "missing", "file.py"])
def test_invalid_source_directories_are_rejected(tmp_path: Path, directory: str) -> None:
    write(tmp_path, "file.py")
    with pytest.raises(ConfigError):
        scan_repository(tmp_path, source_roots=[directory])


def test_external_source_root_symlink_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "src").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ConfigError, match="escapes"):
        scan_repository(root)


@pytest.mark.parametrize("level", [2, 3])
@pytest.mark.parametrize("module", [None, "other"])
def test_invalid_relative_imports_do_not_become_absolute(level: int, module: str | None) -> None:
    metadata = FileMetadata(path="src/pkg/a.py", module_path="pkg.a", loc=1, size_bytes=1)
    info = ImportInfo(kind="from", module=module, level=level, names=["b"])
    assert _resolve_internal_targets_for_import(metadata, info, {"b", "other", "other.b"}) == set()


def test_analysis_cache_revalidates_module_identity(tmp_path: Path) -> None:
    cycle_repo(tmp_path, "src")
    first = analyze_repository(tmp_path, source_roots=["."])
    assert first.cycles == []
    second = analyze_repository(tmp_path)
    assert set(second.cycles[0]) == {"pkg.a", "pkg.b"}
    payload = json.loads(
        (tmp_path / ".strucin_cache/analysis_cache.json").read_text(encoding="utf-8")
    )
    assert "src.pkg.a" not in json.dumps(payload)


@pytest.mark.parametrize("legacy", [False, True])
def test_search_rebuilds_index_when_source_mapping_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy: bool
) -> None:
    cycle_repo(tmp_path, "src")
    monkeypatch.setattr(semantic, "_load_sentence_transformer", lambda model: None)
    original = semantic.build_semantic_index(tmp_path, source_roots=["."])
    index_path = tmp_path / "semantic_index.json"
    semantic.write_semantic_index(original, index_path)
    if legacy:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        del payload["source_roots_key"]
        index_path.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["search", "work", "--path", str(tmp_path)]) == 0
    rebuilt = semantic.load_semantic_index(index_path)
    assert {chunk.module_path for chunk in rebuilt.chunks if chunk.module_path} <= {
        "pkg.a",
        "pkg.b",
    }
    assert rebuilt.source_roots_key != original.source_roots_key
    # Once compatible, reuse the same index without rebuilding it.
    assert main(["search", "work", "--path", str(tmp_path)]) == 0
    assert semantic.load_semantic_index(index_path).generated_at == rebuilt.generated_at


@pytest.mark.parametrize("command", ["scan", "report", "explain", "web", "search"])
def test_source_root_option_reaches_every_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    cycle_repo(tmp_path, "multiple")
    monkeypatch.setattr(explainer, "_detect_llm", lambda config: None)
    monkeypatch.setattr(semantic, "_load_sentence_transformer", lambda model: None)
    flags = ["--source-root", "lib_one", "--source-root", "lib_two"]
    if command in {"scan", "report"}:
        argv = [command, str(tmp_path), *flags]
    elif command == "search":
        argv = [command, "work", "--path", str(tmp_path), *flags]
    else:
        argv = [command, "--path", str(tmp_path), *flags]
    assert main(argv) == 0
    paths = {
        "scan": "repo_index.json",
        "report": "docs/REPORT.md",
        "explain": "docs/EXPLAIN.md",
        "web": ".strucin_web/data.json",
        "search": "semantic_index.json",
    }
    output = (tmp_path / paths[command]).read_text(encoding="utf-8")
    assert "pkg.a" in output and "lib_one.pkg.a" not in output


def test_roots_do_not_execute_setup_script(tmp_path: Path) -> None:
    write(tmp_path, "setup.py", "raise RuntimeError('must not execute')\n")
    write(tmp_path, "src/pkg/a.py")
    roots = resolve_source_roots(tmp_path)
    assert roots[0].path == tmp_path / "src"


def test_safe_analysis_does_not_export_source_root_names(tmp_path: Path) -> None:
    cycle_repo(tmp_path, "multiple")
    result = analyze_repository(tmp_path, source_roots=["lib_one", "lib_two"], use_cache=False)
    from strucin.core.privacy import anonymize_analysis

    safe = json.dumps(asdict(anonymize_analysis(result)))
    assert "lib_one" not in safe and "pkg.a" not in safe
    assert len(result.cycles) == 1


def test_internal_source_root_symlink_uses_real_scanned_directory(tmp_path: Path) -> None:
    write(tmp_path, "implementation/pkg/a.py", "from pkg import b\n")
    write(tmp_path, "implementation/pkg/b.py", "import pkg.a\n")
    (tmp_path / "src").symlink_to(tmp_path / "implementation", target_is_directory=True)
    result = analyze_repository(tmp_path, use_cache=False)
    assert set(result.cycles[0]) == {"pkg.a", "pkg.b"}
    assert all(file.path.startswith("implementation/") for file in result.files)


def test_setup_cfg_directory_with_spaces(tmp_path: Path) -> None:
    write(tmp_path, "python sources/pkg/a.py")
    write(tmp_path, "setup.cfg", "[options.packages.find]\nwhere = python sources\n")
    assert scan_repository(tmp_path).files[0].module_path == "pkg.a"


def test_init_suffix_is_not_a_package_initializer() -> None:
    metadata = FileMetadata(
        path="src/pkg/not__init__.py", module_path="pkg.not__init__", loc=1, size_bytes=1
    )
    info = ImportInfo(kind="from", module=None, level=1, names=["b"])
    assert _resolve_internal_targets_for_import(metadata, info, {"pkg.b", "pkg.not__init__.b"}) == {
        "pkg.b"
    }
