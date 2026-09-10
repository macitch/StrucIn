"""Regression checks at privacy boundaries, including provider and cache output."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from strucin.cli.hooks import check_complexity, check_cycles
from strucin.cli.main import main
from strucin.core import explainer, semantic
from strucin.core.analyzer import analyze_repository, write_analysis
from strucin.core.config import LLMConfig
from strucin.core.explainer import explain_repository, write_explain_metadata, write_explanation
from strucin.core.indexer import scan_repository, write_repo_index
from strucin.core.privacy import anonymize_analysis, anonymize_hits
from strucin.exceptions import ConfigError

PRIVATE_MARKERS = (
    "covertpkg",
    "ledger_private",
    "worker_private",
    "VaultPrivate",
    "settle_private",
    "vendor_private",
    "ImportedPrivate",
    "module-private-prose",
    "class-private-prose",
    "function-private-prose",
    "swordfish-private",
    "covert_workspace",
)


@pytest.fixture
def private_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "covert_workspace"
    package = root / "covertpkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "ledger_private.py").write_text(
        '"""module-private-prose password="swordfish-private" """\n'
        "from covertpkg import worker_private\n"
        "from vendor_private import ImportedPrivate\n"
        "class VaultPrivate:\n"
        '    """class-private-prose"""\n'
        "    def settle_private(self):\n"
        '        """function-private-prose"""\n'
        "        if True:\n"
        "            return 1\n",
        encoding="utf-8",
    )
    (package / "worker_private.py").write_text(
        "import covertpkg.ledger_private\n", encoding="utf-8"
    )
    monkeypatch.setattr(explainer, "_detect_llm", lambda config: None)
    monkeypatch.setattr(semantic, "_load_sentence_transformer", lambda model: None)
    return root


def assert_private(text: str) -> None:
    for marker in PRIVATE_MARKERS:
        assert marker.lower() not in text.lower(), marker


def arguments(command: str, root: Path) -> list[str]:
    if command in {"scan", "analyze", "report"}:
        return [command, str(root)]
    if command == "search":
        return [command, "settle_private", "--path", str(root)]
    return [command, "--path", str(root)]


@pytest.mark.parametrize("command", ["scan", "analyze", "report", "explain", "search", "web"])
@pytest.mark.parametrize("via_config", [True, False])
def test_safe_commands_hide_identifiers_and_avoid_raw_caches(
    private_repo: Path, capsys: pytest.CaptureFixture[str], command: str, via_config: bool
) -> None:
    (private_repo / ".strucin.toml").write_text(
        f"[security]\nsafe_mode = {str(via_config).lower()}\n"
        "[observability]\nstructured_logging = true\ntiming_enabled = false\n",
        encoding="utf-8",
    )
    argv = arguments(command, private_repo) + ([] if via_config else ["--safe-mode"])
    assert main(argv) == 0
    captured = capsys.readouterr()
    assert_private(captured.out + captured.err)
    assert not (private_repo / ".strucin_cache/analysis_cache.json").exists()
    assert not (private_repo / ".strucin_cache/explain_cache.json").exists()
    assert not (private_repo / "semantic_index.json").exists()
    for path in private_repo.rglob("*"):
        if path.is_file() and path.suffix != ".py" and path.name != ".strucin.toml":
            assert_private(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("command", ["scan", "analyze", "search"])
def test_safe_json_status(
    private_repo: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    assert main([*arguments(command, private_repo), "--safe-mode", "--json"]) == 0
    captured = capsys.readouterr()
    assert_private(captured.out + captured.err)


@pytest.mark.parametrize("command", ["scan", "analyze", "report", "explain", "search", "web"])
def test_no_safe_mode_overrides_config(private_repo: Path, command: str) -> None:
    (private_repo / ".strucin.toml").write_text("[security]\nsafe_mode = true\n", encoding="utf-8")
    assert main([*arguments(command, private_repo), "--no-safe-mode"]) == 0
    outputs = {
        "scan": "repo_index.json",
        "analyze": "analysis.json",
        "report": "docs/REPORT.md",
        "explain": "docs/EXPLAIN.md",
        "search": "semantic_index.json",
        "web": ".strucin_web/data.json",
    }
    assert "covertpkg" in (private_repo / outputs[command]).read_text(encoding="utf-8")


def test_analysis_exports_preserve_structure_without_mutating_input(private_repo: Path) -> None:
    raw = analyze_repository(private_repo, max_workers=1, use_cache=False)
    safe = anonymize_analysis(raw)
    assert raw.cycles
    assert_private(json.dumps(asdict(safe)))
    assert "covertpkg" in json.dumps(asdict(raw))
    names = {
        left.module_path: right.module_path
        for left, right in zip(raw.files, safe.files, strict=True)
    }
    assert safe.cycles == [[names[name] for name in cycle] for cycle in raw.cycles]
    assert [(edge.source, edge.target) for edge in safe.dependency_graph_edges] == [
        (names[edge.source], names[edge.target]) for edge in raw.dependency_graph_edges
    ]
    for left, right in zip(raw.files, safe.files, strict=True):
        assert (left.loc, left.fan_in, left.fan_out, left.cyclomatic_complexity) == (
            right.loc,
            right.fan_in,
            right.fan_out,
            right.cyclomatic_complexity,
        )
        assert right.docstring is None
        assert all(item.docstring is None for item in [*right.functions, *right.classes])
    write_analysis(raw, private_repo / "analysis.json", private_repo / "graph.json", safe_mode=True)
    write_repo_index(
        scan_repository(private_repo), private_repo / "repo_index.json", safe_mode=True
    )
    for filename in ["analysis.json", "graph.json", "repo_index.json"]:
        assert_private((private_repo / filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_safe_llm_context_response_metadata_and_cache(
    private_repo: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(explainer, "_detect_llm", lambda config: (provider, "covert_workspace"))

    def provider_response(context: str, selected_provider: str, model: str) -> str:
        calls.append(context)
        assert selected_provider == provider
        return (
            f"Review {private_repo} covertpkg.ledger_private VaultPrivate settle_private "
            "class-private-prose password='swordfish-private'. module_0001 has a cycle."
        )

    monkeypatch.setattr(explainer, "_call_llm", provider_response)
    normal_cache = private_repo / ".strucin_cache/explain_cache.json"
    normal_cache.parent.mkdir()
    normal_cache.write_text("raw cache covertpkg", encoding="utf-8")
    analysis_cache = normal_cache.with_name("analysis_cache.json")
    analysis_cache.write_text("invalid raw cache covertpkg", encoding="utf-8")
    output = explain_repository(private_repo, safe_mode=True, llm_config=LLMConfig())
    assert len(calls) == 1
    assert_private(calls[0])
    context = json.loads(calls[0])
    assert context["cycles"] and context["file_count"] == 3
    assert all(file["docstring"] is None for file in context["files"])
    assert_private(json.dumps(asdict(output)))
    assert "module_0001 has a cycle" in output.content
    write_explanation(output, private_repo / "explain.md")
    write_explain_metadata(output, private_repo / "explain.json")
    safe_cache = normal_cache.with_name("explain_safe_cache.json")
    assert_private(safe_cache.read_text(encoding="utf-8"))
    assert normal_cache.read_text(encoding="utf-8") == "raw cache covertpkg"
    assert analysis_cache.read_text(encoding="utf-8") == "invalid raw cache covertpkg"
    # A cache hit must reapply output filtering, and drop unrelated entries.
    payload = json.loads(safe_cache.read_text(encoding="utf-8"))
    payload["entries"][output.cache_key]["content"] = (
        "covertpkg VaultPrivate token='swordfish-private'"
    )
    payload["entries"]["covertpkg"] = {"content": "covertpkg", "generated_at": "covertpkg"}
    safe_cache.write_text(json.dumps(payload), encoding="utf-8")
    cached = explain_repository(private_repo, safe_mode=True, llm_config=LLMConfig())
    assert len(calls) == 1
    assert cached.generated_at == output.generated_at
    assert_private(json.dumps(asdict(cached)))
    assert_private(safe_cache.read_text(encoding="utf-8"))
    refreshed = explain_repository(
        private_repo, safe_mode=True, refresh=True, llm_config=LLMConfig()
    )
    assert len(calls) == 2
    assert_private(refreshed.content)


@pytest.mark.parametrize("cache_text", ["{broken", '{"cache_version":"1","entries":{}}'])
def test_invalid_safe_cache_regenerates(private_repo: Path, cache_text: str) -> None:
    cache = private_repo / ".strucin_cache/explain_safe_cache.json"
    cache.parent.mkdir()
    cache.write_text(cache_text, encoding="utf-8")
    output = explain_repository(private_repo, safe_mode=True)
    assert "Safe mode is **enabled**" in output.content
    assert_private(cache.read_text(encoding="utf-8"))


def test_safe_search_ignores_existing_index_and_omits_source(
    private_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cache = private_repo / "semantic_index.json"
    cache.write_text("invalid private index covertpkg", encoding="utf-8")
    assert main([*arguments("search", private_repo), "--safe-mode"]) == 0
    assert_private(capsys.readouterr().out)
    assert cache.read_text(encoding="utf-8") == "invalid private index covertpkg"
    index = semantic.build_semantic_index(private_repo)
    raw = semantic.search_semantic_index(index, "settle_private")
    safe = anonymize_hits(raw, index)
    assert raw and any(hit.chunk.text for hit in raw)
    assert [hit.score for hit in safe] == [hit.score for hit in raw]
    assert all(not hit.preview and not hit.chunk.text for hit in safe)
    assert_private(json.dumps([asdict(hit) for hit in safe]))


def test_safe_hooks_hide_names_and_skip_cache(
    private_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (private_repo / ".strucin.toml").write_text("[security]\nsafe_mode = true\n", encoding="utf-8")
    assert check_cycles(private_repo) == 1
    assert check_complexity(private_repo, threshold=1) == 1
    captured = capsys.readouterr()
    assert_private(captured.out + captured.err)
    assert not (private_repo / ".strucin_cache").exists()


@pytest.mark.parametrize("json_output", [True, False])
def test_safe_diff_compares_raw_snapshots_then_hides_names(
    private_repo: Path, capsys: pytest.CaptureFixture[str], json_output: bool
) -> None:
    before = private_repo / "before.json"
    after = private_repo / "after.json"
    graph = private_repo / "graph.json"
    write_analysis(analyze_repository(private_repo, use_cache=False), before, graph)
    (private_repo / "covertpkg/worker_private.py").unlink()
    (private_repo / "covertpkg/new_private.py").write_text("x = 1\n", encoding="utf-8")
    write_analysis(analyze_repository(private_repo, use_cache=False), after, graph)
    argv = ["diff", str(before), str(after), "--safe-mode"] + (["--json"] if json_output else [])
    assert main(argv) == 0
    output = capsys.readouterr().out
    assert_private(output)
    assert "new_private" not in output
    if json_output:
        payload = json.loads(output)
        assert payload["summary"]["modules_added"] == 1
        assert payload["summary"]["modules_removed"] == 1


def test_safe_explanation_cache_still_enforces_path_boundary(
    private_repo: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("untouched", encoding="utf-8")
    cache = private_repo / ".strucin_cache/explain_safe_cache.json"
    cache.parent.mkdir()
    cache.symlink_to(outside)
    with pytest.raises(ConfigError, match="escapes"):
        explain_repository(private_repo, safe_mode=True)
    assert outside.read_text(encoding="utf-8") == "untouched"


def test_normal_cache_hit_does_not_rewrite_cache(
    private_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = explain_repository(private_repo)

    def unexpected_write(*args: object, **kwargs: object) -> None:
        pytest.fail("Normal cache hits must not require writing the cache")

    monkeypatch.setattr(explainer, "_write_cache", unexpected_write)
    assert explain_repository(private_repo) == original


@pytest.mark.parametrize("timestamp", ["covert_workspace", None])
def test_safe_cache_invalid_metadata_falls_back_without_leaking(
    private_repo: Path, monkeypatch: pytest.MonkeyPatch, timestamp: str | None
) -> None:
    monkeypatch.setattr(explainer, "_detect_llm", lambda config: ("openai", "model"))
    monkeypatch.setattr(explainer, "_call_llm", lambda *args: None)
    output = explain_repository(private_repo, safe_mode=True, llm_config=LLMConfig())
    cache = private_repo / ".strucin_cache/explain_safe_cache.json"
    payload = json.loads(cache.read_text(encoding="utf-8"))
    payload["entries"][output.cache_key] = {
        "generated_at": timestamp,
        "content": "covertpkg module-private-prose",
    }
    cache.write_text(json.dumps(payload), encoding="utf-8")
    result = explain_repository(private_repo, safe_mode=True, llm_config=LLMConfig())
    assert "Safe mode is **enabled**" in result.content
    assert_private(json.dumps(asdict(result)))
    assert_private(cache.read_text(encoding="utf-8"))
