from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


DEFAULT_CHROMA_COLLECTION = "clinical_osce_retrieval"
DEFAULT_CHROMA_PERSIST_DIRECTORY = "./data/processed/chroma"
DEFAULT_CHROMA_SEARCH_EF = 500
CHROMA_MANIFEST_FILENAME = "retrieval_index_manifest.json"
CHROMA_MANIFEST_SCHEMA_VERSION = "1.1"


class EmbeddingClient(Protocol):
    def embed_texts(self, texts: Sequence[str], *, task_type: str) -> list[list[float]]:
        ...


@dataclass(frozen=True)
class ChromaSourceDocument:
    reference: str
    source_type: str
    title: str
    snippet: str


@dataclass(frozen=True)
class ChromaRetrievalResult:
    reference: str
    source_type: str
    title: str
    snippet: str
    score: float


@dataclass(frozen=True)
class ChromaRetrievalSettings:
    persist_directory: Path
    collection_name: str = DEFAULT_CHROMA_COLLECTION
    embedding_model: str = "unknown"
    search_ef: int = DEFAULT_CHROMA_SEARCH_EF

    def __post_init__(self) -> None:
        if self.search_ef <= 0:
            raise ValueError("Chroma search_ef must be a positive integer")


class ChromaRetrievalIndex:
    def __init__(
        self,
        *,
        settings: ChromaRetrievalSettings,
        embedding_client: EmbeddingClient,
        documents: Sequence[ChromaSourceDocument],
    ) -> None:
        try:
            import chromadb
        except ImportError as exc:  # pragma: no cover - exercised only when dependency is absent
            raise RuntimeError("chromadb is required when OSCE_CHROMA_ENABLED=true") from exc

        settings.persist_directory.mkdir(parents=True, exist_ok=True)
        self._settings = settings
        self._embedding_client = embedding_client
        self._documents = tuple(documents)
        self._client = chromadb.PersistentClient(path=str(settings.persist_directory))
        self._collection = self._client.get_or_create_collection(
            name=settings.collection_name,
            metadata=_collection_metadata(settings),
        )

    def search(self, query: str, *, limit: int = 5) -> list[ChromaRetrievalResult]:
        results_by_query = self.search_batch([query], limit=limit)
        return results_by_query[0] if results_by_query else []

    def search_batch(self, queries: Sequence[str], *, limit: int = 5) -> list[list[ChromaRetrievalResult]]:
        normalized_queries = [str(query).strip() for query in queries]
        results_by_query: list[list[ChromaRetrievalResult]] = [[] for _ in normalized_queries]
        active_queries = [
            (index, query)
            for index, query in enumerate(normalized_queries)
            if query
        ]
        if limit <= 0 or not self._documents or not active_queries:
            return results_by_query

        self.ensure_indexed()
        query_texts = [query for _, query in active_queries]
        query_vectors = self._embedding_client.embed_texts(query_texts, task_type="RETRIEVAL_QUERY")
        if len(query_vectors) != len(query_texts):
            raise ValueError("embedding client must return one vector for each query")

        try:
            raw_results = self._query_collection(query_vectors, limit=limit)
        except Exception as exc:
            if not _is_embedding_dimension_mismatch_error(exc):
                raise
            self._reset_collection()
            self.ensure_indexed()
            raw_results = self._query_collection(query_vectors, limit=limit)

        empty_result_indexes: list[int] = []
        for result_index, (original_index, _) in enumerate(active_queries):
            query_results = _parse_query_results(raw_results, result_index=result_index)
            results_by_query[original_index] = query_results[:limit]
            if not query_results:
                empty_result_indexes.append(result_index)

        if empty_result_indexes:
            exact_query_vectors = [query_vectors[index] for index in empty_result_indexes]
            exact_raw_results = self._query_collection(
                exact_query_vectors,
                limit=len(self._documents),
            )
            for retry_index, result_index in enumerate(empty_result_indexes):
                original_index = active_queries[result_index][0]
                results_by_query[original_index] = _parse_query_results(
                    exact_raw_results,
                    result_index=retry_index,
                )[:limit]
        return results_by_query

    def ensure_indexed(self) -> None:
        if not self._documents:
            return
        manifest_status = build_chroma_manifest_status(settings=self._settings, documents=self._documents)
        if manifest_status.get("rebuild_required") is True:
            self._reset_collection()
        elif self._collection_has_expected_count():
            return

        document_vectors = self._embedding_client.embed_texts(
            [_document_embedding_text(document) for document in self._documents],
            task_type="RETRIEVAL_DOCUMENT",
        )
        if len(document_vectors) != len(self._documents):
            raise ValueError("embedding client must return one vector for each ChromaDB document")

        try:
            self._upsert_documents(document_vectors)
        except Exception as exc:
            if not _is_embedding_dimension_mismatch_error(exc):
                raise
            self._reset_collection()
            self._upsert_documents(document_vectors)
        write_chroma_manifest(settings=self._settings, documents=self._documents)

    def _upsert_documents(self, document_vectors: list[list[float]]) -> None:
        self._collection.upsert(
            ids=[_document_id(document) for document in self._documents],
            embeddings=document_vectors,
            documents=[_document_embedding_text(document) for document in self._documents],
            metadatas=[
                {
                    "reference": document.reference,
                    "source_type": document.source_type,
                    "title": document.title,
                    "snippet": document.snippet,
                }
                for document in self._documents
            ],
        )

    def _query_collection(self, query_vectors: list[list[float]], *, limit: int) -> dict[str, Any]:
        return self._collection.query(
            query_embeddings=query_vectors,
            n_results=min(limit, len(self._documents)),
            include=["metadatas", "distances"],
        )

    def _reset_collection(self) -> None:
        try:
            self._client.delete_collection(name=self._settings.collection_name)
        except Exception:
            pass
        self._collection = self._client.get_or_create_collection(
            name=self._settings.collection_name,
            metadata=_collection_metadata(self._settings),
        )

    def _collection_has_expected_count(self) -> bool:
        try:
            return int(self._collection.count()) >= len(self._documents)
        except Exception:
            return False


def build_chroma_retrieval_index_from_environment(
    *,
    embedding_client: EmbeddingClient,
    documents: Sequence[ChromaSourceDocument],
    root_dir: Path,
    embedding_model: str = "",
) -> ChromaRetrievalIndex | None:
    if not _chroma_enabled_from_environment():
        return None

    settings = build_chroma_retrieval_settings_from_environment(
        root_dir=root_dir,
        embedding_model=embedding_model,
    )
    return ChromaRetrievalIndex(
        settings=settings,
        embedding_client=embedding_client,
        documents=documents,
    )


def build_chroma_retrieval_settings_from_environment(
    *,
    root_dir: Path,
    embedding_model: str = "",
) -> ChromaRetrievalSettings:
    return ChromaRetrievalSettings(
        persist_directory=_resolve_persist_directory(
            _env("CHROMA_PERSIST_DIRECTORY", DEFAULT_CHROMA_PERSIST_DIRECTORY),
            root_dir=root_dir,
        ),
        collection_name=_env("OSCE_CHROMA_COLLECTION", DEFAULT_CHROMA_COLLECTION),
        embedding_model=embedding_model or _env("OSCE_VERTEX_EMBEDDING_MODEL", "gemini-embedding-001"),
        search_ef=_positive_int_env("OSCE_CHROMA_SEARCH_EF", DEFAULT_CHROMA_SEARCH_EF),
    )


def build_chroma_manifest_status(
    *,
    settings: ChromaRetrievalSettings,
    documents: Sequence[ChromaSourceDocument],
) -> dict[str, Any]:
    expected = _build_chroma_manifest_payload(settings=settings, documents=documents, built_at="")
    manifest_path = _manifest_path(settings)
    base_status: dict[str, Any] = {
        "schema_version": CHROMA_MANIFEST_SCHEMA_VERSION,
        "manifest_path": str(manifest_path),
        "collection": expected["collection"],
        "embedding_model": expected["embedding_model"],
        "index_config": expected["index_config"],
        "source_count": expected["source_count"],
        "case_ids": expected["case_ids"],
        "content_hash": expected["content_hash"],
        "built_at": "",
        "stored_schema_version": "",
        "stored_collection": "",
        "stored_embedding_model": "",
        "stored_index_config": {},
        "stored_source_count": 0,
        "stored_case_ids": [],
        "stored_content_hash": "",
    }
    if not manifest_path.exists():
        return {**base_status, "status": "missing", "rebuild_required": True}

    try:
        stored = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {**base_status, "status": "invalid", "rebuild_required": True}

    try:
        stored_schema_version = str(stored.get("schema_version", ""))
        stored_collection = str(stored.get("collection", ""))
        stored_embedding_model = str(stored.get("embedding_model", ""))
        raw_stored_index_config = stored.get("index_config", {})
        if not isinstance(raw_stored_index_config, dict):
            raise TypeError("index_config must be an object")
        stored_index_config = dict(raw_stored_index_config)
        stored_content_hash = str(stored.get("content_hash", ""))
        stored_source_count = int(stored.get("source_count", 0) or 0)
        stored_case_ids = [str(case_id) for case_id in stored.get("case_ids", []) if str(case_id)]
    except (TypeError, ValueError):
        return {**base_status, "status": "invalid", "rebuild_required": True}
    rebuild_required = (
        stored_schema_version != CHROMA_MANIFEST_SCHEMA_VERSION
        or stored_collection != expected["collection"]
        or stored_embedding_model != expected["embedding_model"]
        or stored_index_config != expected["index_config"]
        or stored_source_count != expected["source_count"]
        or stored_content_hash != expected["content_hash"]
    )
    return {
        **base_status,
        "status": "stale" if rebuild_required else "built",
        "rebuild_required": rebuild_required,
        "built_at": str(stored.get("built_at", "")),
        "stored_schema_version": stored_schema_version,
        "stored_collection": stored_collection,
        "stored_embedding_model": stored_embedding_model,
        "stored_index_config": stored_index_config,
        "stored_source_count": stored_source_count,
        "stored_case_ids": stored_case_ids,
        "stored_content_hash": stored_content_hash,
    }


def write_chroma_manifest(
    *,
    settings: ChromaRetrievalSettings,
    documents: Sequence[ChromaSourceDocument],
) -> dict[str, Any]:
    settings.persist_directory.mkdir(parents=True, exist_ok=True)
    manifest = _build_chroma_manifest_payload(
        settings=settings,
        documents=documents,
        built_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
    )
    _manifest_path(settings).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def resolve_chroma_persist_directory(raw_path: str, *, root_dir: Path) -> Path:
    return _resolve_persist_directory(raw_path, root_dir=root_dir)


def _document_embedding_text(document: ChromaSourceDocument) -> str:
    return f"{document.source_type}\n{document.reference}\n{document.title}\n{document.snippet}"


def _document_id(document: ChromaSourceDocument) -> str:
    digest = hashlib.sha256(document.reference.encode("utf-8")).hexdigest()
    return f"source-{digest}"


def _distance_to_score(distance: float) -> float:
    return max(0.0, 1.0 - distance)


def _parse_query_results(
    raw_results: dict[str, Any],
    *,
    result_index: int,
) -> list[ChromaRetrievalResult]:
    metadatas_by_query = raw_results.get("metadatas", [])
    distances_by_query = raw_results.get("distances", [])
    metadatas = metadatas_by_query[result_index] if result_index < len(metadatas_by_query) else []
    distances = distances_by_query[result_index] if result_index < len(distances_by_query) else []
    query_results: list[ChromaRetrievalResult] = []
    for metadata, distance in zip(metadatas, distances):
        if not metadata:
            continue
        score = _distance_to_score(float(distance))
        if score <= 0:
            continue
        query_results.append(
            ChromaRetrievalResult(
                reference=str(metadata.get("reference", "")),
                source_type=str(metadata.get("source_type", "")),
                title=str(metadata.get("title", "")),
                snippet=str(metadata.get("snippet", "")),
                score=score,
            )
        )
    return query_results


def _is_embedding_dimension_mismatch_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "dimension" in message and (
        "expecting embedding" in message
        or "embedding dimension" in message
        or "dimensionality" in message
    )


def _resolve_persist_directory(raw_path: str, *, root_dir: Path) -> Path:
    persist_directory = Path(raw_path)
    if persist_directory.is_absolute():
        return persist_directory
    return root_dir / persist_directory


def _manifest_path(settings: ChromaRetrievalSettings) -> Path:
    return settings.persist_directory / CHROMA_MANIFEST_FILENAME


def _build_chroma_manifest_payload(
    *,
    settings: ChromaRetrievalSettings,
    documents: Sequence[ChromaSourceDocument],
    built_at: str,
) -> dict[str, Any]:
    documents_tuple = tuple(documents)
    return {
        "schema_version": CHROMA_MANIFEST_SCHEMA_VERSION,
        "collection": settings.collection_name,
        "embedding_model": settings.embedding_model,
        "index_config": _collection_metadata(settings),
        "source_count": len(documents_tuple),
        "case_ids": _manifest_case_ids(documents_tuple),
        "content_hash": _manifest_content_hash(settings=settings, documents=documents_tuple),
        "built_at": built_at,
    }


def _manifest_content_hash(
    *,
    settings: ChromaRetrievalSettings,
    documents: Sequence[ChromaSourceDocument],
) -> str:
    payload = {
        "schema_version": CHROMA_MANIFEST_SCHEMA_VERSION,
        "collection": settings.collection_name,
        "embedding_model": settings.embedding_model,
        "index_config": _collection_metadata(settings),
        "documents": [
            {
                "reference": document.reference,
                "source_type": document.source_type,
                "title": document.title,
                "snippet": document.snippet,
            }
            for document in sorted(documents, key=lambda item: (item.source_type, item.reference, item.title, item.snippet))
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"


def _manifest_case_ids(documents: Sequence[ChromaSourceDocument]) -> list[str]:
    case_ids = {_case_id_from_reference(document.reference) for document in documents}
    return sorted(case_id for case_id in case_ids if case_id)


def _case_id_from_reference(reference: str) -> str:
    if reference.startswith("case:"):
        return reference.removeprefix("case:").split(".", maxsplit=1)[0]
    if reference.startswith("rag_knowledge:"):
        knowledge_id_parts = reference.removeprefix("rag_knowledge:").split(":")
        if len(knowledge_id_parts) >= 3 and knowledge_id_parts[0] == "case":
            return knowledge_id_parts[1]
        return ""
    if reference.startswith("knowledge:"):
        return reference.removeprefix("knowledge:").split(".", maxsplit=1)[0]
    if reference.startswith("rubric:"):
        rubric_id = reference.removeprefix("rubric:").split(".", maxsplit=1)[0]
        return rubric_id.removesuffix("_rubric")
    return ""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _positive_int_env(name: str, default: int) -> int:
    raw_value = _env(name)
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default


def _collection_metadata(settings: ChromaRetrievalSettings) -> dict[str, str | int]:
    return {
        "hnsw:space": "cosine",
        "hnsw:search_ef": settings.search_ef,
    }


def _chroma_enabled_from_environment() -> bool:
    raw_value = _env("OSCE_CHROMA_ENABLED")
    if not raw_value:
        return True
    return raw_value.lower() in {"1", "true", "yes", "on"}


def _truthy_env(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


__all__ = [
    "DEFAULT_CHROMA_SEARCH_EF",
    "ChromaRetrievalIndex",
    "ChromaRetrievalResult",
    "ChromaRetrievalSettings",
    "ChromaSourceDocument",
    "build_chroma_manifest_status",
    "build_chroma_retrieval_index_from_environment",
    "build_chroma_retrieval_settings_from_environment",
    "resolve_chroma_persist_directory",
    "write_chroma_manifest",
]
