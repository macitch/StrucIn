from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from dataclasses import replace as dc_replace
from datetime import UTC, datetime
from functools import partial
from math import sqrt
from pathlib import Path
from typing import Any

from strucin.core.artifacts import build_artifact_metadata
from strucin.core.indexer import EXCLUDED_DIRS, FileMetadata, scan_repository

TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_logger = logging.getLogger(__name__)
_ST_MODEL_CACHE: dict[str, Any] = {}
_ST_MODEL_LOCK = threading.Lock()


@dataclass(frozen=True)
class SemanticChunk:
    id: str
    path: str
    module_path: str | None
    symbol: str | None
    kind: str
    start_line: int
    end_line: int
    text: str


@dataclass(frozen=True)
class SemanticIndex:
    repo_root: str
    generated_at: str
    model: str
    dimensions: int
    chunk_count: int
    chunks: list[SemanticChunk]
    vectors: list[list[float]]


@dataclass(frozen=True)
class SemanticHit:
    chunk: SemanticChunk
    score: float
    preview: str


def _text_preview(text: str, max_chars: int = 140) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 3]}..."


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


def _hash_token(token: str, dimensions: int) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, byteorder="big", signed=False)
    return value % dimensions


def embed_text(text: str, dimensions: int = 256) -> list[float]:
    """Return an L2-normalised bag-of-tokens vector for *text*.

    Each token is hashed via BLAKE2b (8-byte digest) into one of *dimensions*
    buckets and its count is incremented.  The resulting count vector is then
    divided by its Euclidean (L2) norm so that the dot product of any two
    returned vectors equals their cosine similarity — enabling efficient nearest-
    neighbour search without a separate normalisation step at query time.

    BLAKE2b is chosen because it is fast, available in the standard library, and
    distributes tokens uniformly across buckets with low collision probability.

    **Known limitations vs neural embeddings:**
    - Captures *vocabulary overlap*, not semantic meaning (synonyms score 0).
    - Sensitive to token surface form; "run" and "running" are unrelated buckets.
    - High-dimensional spaces are sparse; recall degrades on very short queries.
    - No positional or contextual information is encoded.

    Use the ``sentence-transformers`` back-end (``strucin[embeddings]``) for
    higher-quality semantic search when the extra dependency is acceptable.
    """
    vector = [0.0] * dimensions
    for token in _tokenize(text):
        vector[_hash_token(token, dimensions)] += 1.0

    norm = sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _slice_source(source: str, start_line: int, end_line: int) -> str:
    lines = source.splitlines()
    if start_line < 1 or end_line < start_line:
        return ""
    return "\n".join(lines[start_line - 1 : end_line])


def _python_chunks_for_file(file_metadata: FileMetadata, source: str) -> list[SemanticChunk]:
    chunks: list[SemanticChunk] = []
    relative_path = file_metadata.path
    module_path = file_metadata.module_path
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return chunks

    module_docstring = ast.get_docstring(tree)
    if module_docstring:
        chunks.append(
            SemanticChunk(
                id="",
                path=relative_path,
                module_path=module_path,
                symbol=module_path,
                kind="module_docstring",
                start_line=1,
                end_line=min(20, len(source.splitlines())),
                text=module_docstring,
            )
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            start = node.lineno
            end = node.end_lineno or node.lineno
            chunks.append(
                SemanticChunk(
                    id="",
                    path=relative_path,
                    module_path=module_path,
                    symbol=node.name,
                    kind="class",
                    start_line=start,
                    end_line=end,
                    text=_slice_source(source, start, end),
                )
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = node.end_lineno or node.lineno
            chunks.append(
                SemanticChunk(
                    id="",
                    path=relative_path,
                    module_path=module_path,
                    symbol=node.name,
                    kind="function",
                    start_line=start,
                    end_line=end,
                    text=_slice_source(source, start, end),
                )
            )

    if not chunks:
        line_count = max(1, len(source.splitlines()))
        chunks.append(
            SemanticChunk(
                id="",
                path=relative_path,
                module_path=module_path,
                symbol=module_path,
                kind="module_source",
                start_line=1,
                end_line=line_count,
                text=source,
            )
        )
    return chunks


def _doc_chunks(repo_root: Path, excluded_dirs: set[str]) -> list[SemanticChunk]:
    chunks: list[SemanticChunk] = []
    for current_root, dir_names, file_names in os.walk(repo_root, topdown=True):
        dir_names[:] = [dir_name for dir_name in dir_names if dir_name not in excluded_dirs]
        root_path = Path(current_root)
        for file_name in file_names:
            lower = file_name.lower()
            if not (lower.endswith(".md") or lower.endswith(".rst") or lower.endswith(".txt")):
                continue
            file_path = root_path / file_name
            relative_path = file_path.relative_to(repo_root).as_posix()
            text = file_path.read_text(encoding="utf-8", errors="ignore").strip()
            if not text:
                continue
            chunks.append(
                SemanticChunk(
                    id="",
                    path=relative_path,
                    module_path=None,
                    symbol=file_name,
                    kind="document",
                    start_line=1,
                    end_line=max(1, len(text.splitlines())),
                    text=text,
                )
            )
    return sorted(chunks, key=lambda item: item.path)


def _assign_chunk_ids(chunks: list[SemanticChunk]) -> list[SemanticChunk]:
    return [dc_replace(chunk, id=f"chunk-{index:05d}") for index, chunk in enumerate(chunks, 1)]


def _chunks_for_metadata(root: Path, file_metadata: FileMetadata) -> list[SemanticChunk]:
    source = (root / file_metadata.path).read_text(encoding="utf-8", errors="ignore")
    return _python_chunks_for_file(file_metadata, source)


def _load_sentence_transformer(model_name: str) -> Any | None:
    with _ST_MODEL_LOCK:
        if model_name in _ST_MODEL_CACHE:
            return _ST_MODEL_CACHE[model_name]
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_name)
        with _ST_MODEL_LOCK:
            _ST_MODEL_CACHE[model_name] = model
        return model
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            "failed to load embedding model %r (%s): %s; falling back to hashing.",
            model_name,
            type(exc).__name__,
            exc,
        )
        return None


def _embed_texts(
    texts: list[str],
    model_name: str,
    fallback_dimensions: int,
) -> tuple[list[list[float]], int, str]:
    """Returns (vectors, actual_dims, actual_model_used)."""
    if model_name != "hashing-v1":
        st_model = _load_sentence_transformer(model_name)
        if st_model is not None:
            raw = st_model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            vectors = [row.tolist() for row in raw]
            dims = len(vectors[0]) if vectors else fallback_dimensions
            return vectors, dims, model_name

    # Hashing fallback
    vectors = [embed_text(text, fallback_dimensions) for text in texts]
    return vectors, fallback_dimensions, "hashing-v1"


def build_semantic_index(
    repo_path: Path,
    dimensions: int = 256,
    embedding_model: str = "all-MiniLM-L6-v2",
    excluded_dirs: set[str] | None = None,
    max_workers: int | None = None,
) -> SemanticIndex:
    active_excluded_dirs = excluded_dirs if excluded_dirs is not None else EXCLUDED_DIRS
    index = scan_repository(
        repo_path,
        excluded_dirs=active_excluded_dirs,
        max_workers=max_workers,
    )
    root = Path(index.repo_root)

    if max_workers == 1:
        chunk_groups = [_chunks_for_metadata(root, file_metadata) for file_metadata in index.files]
    else:
        chunk_builder = partial(_chunks_for_metadata, root)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            chunk_groups = list(executor.map(chunk_builder, index.files))

    all_chunks = [chunk for group in chunk_groups for chunk in group]

    all_chunks.extend(_doc_chunks(root, active_excluded_dirs))
    all_chunks = [chunk for chunk in all_chunks if chunk.text.strip()]
    all_chunks = _assign_chunk_ids(all_chunks)

    texts = [chunk.text for chunk in all_chunks]
    vectors, actual_dims, actual_model = _embed_texts(texts, embedding_model, dimensions)
    return SemanticIndex(
        repo_root=index.repo_root,
        generated_at=datetime.now(UTC).isoformat(),
        model=actual_model,
        dimensions=actual_dims,
        chunk_count=len(all_chunks),
        chunks=all_chunks,
        vectors=vectors,
    )


def write_semantic_index(index: SemanticIndex, output_path: Path) -> None:
    payload = {
        "artifact_metadata": build_artifact_metadata(
            "semantic_index",
            generated_at=index.generated_at,
        ),
        "repo_root": index.repo_root,
        "generated_at": index.generated_at,
        "model": index.model,
        "dimensions": index.dimensions,
        "chunk_count": index.chunk_count,
        "chunks": [asdict(chunk) for chunk in index.chunks],
        "vectors": index.vectors,
    }
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)
        file.write("\n")


def load_semantic_index(input_path: Path) -> SemanticIndex:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    chunks = [SemanticChunk(**chunk) for chunk in payload["chunks"]]
    return SemanticIndex(
        repo_root=payload["repo_root"],
        generated_at=payload["generated_at"],
        model=payload["model"],
        dimensions=payload["dimensions"],
        chunk_count=payload["chunk_count"],
        chunks=chunks,
        vectors=payload["vectors"],
    )


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def search_semantic_index(index: SemanticIndex, query: str, top_k: int = 5) -> list[SemanticHit]:
    if top_k <= 0:
        return []

    query_vectors, _, _ = _embed_texts([query], index.model, index.dimensions)
    query_vector = query_vectors[0]
    if len(query_vector) != index.dimensions:
        raise ValueError(
            f"Query vector has {len(query_vector)} dimensions; index expects {index.dimensions}."
        )
    scored: list[tuple[int, float]] = []
    for idx, vector in enumerate(index.vectors):
        score = _dot(query_vector, vector)
        if score <= 0:
            continue
        scored.append((idx, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    hits: list[SemanticHit] = []
    for idx, score in scored[:top_k]:
        chunk = index.chunks[idx]
        hits.append(SemanticHit(chunk=chunk, score=score, preview=_text_preview(chunk.text)))
    return hits
