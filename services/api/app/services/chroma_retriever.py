from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


DEFAULT_CHROMA_COLLECTION = "clinical_osce_retrieval"
DEFAULT_CHROMA_PERSIST_DIRECTORY = "./data/processed/chroma"


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
            metadata={"hnsw:space": "cosine"},
        )

    def search(self, query: str, *, limit: int = 5) -> list[ChromaRetrievalResult]:
        normalized_query = query.strip()
        if not normalized_query or limit <= 0 or not self._documents:
            return []

        self.ensure_indexed()
        query_vectors = self._embedding_client.embed_texts([normalized_query], task_type="RETRIEVAL_QUERY")
        if len(query_vectors) != 1:
            raise ValueError("embedding client must return one query vector")

        raw_results = self._collection.query(
            query_embeddings=query_vectors,
            n_results=min(limit, len(self._documents)),
            include=["metadatas", "distances"],
        )
        metadatas = raw_results.get("metadatas", [[]])[0]
        distances = raw_results.get("distances", [[]])[0]

        results: list[ChromaRetrievalResult] = []
        for metadata, distance in zip(metadatas, distances):
            if not metadata:
                continue
            score = _distance_to_score(float(distance))
            if score <= 0:
                continue
            results.append(
                ChromaRetrievalResult(
                    reference=str(metadata.get("reference", "")),
                    source_type=str(metadata.get("source_type", "")),
                    title=str(metadata.get("title", "")),
                    snippet=str(metadata.get("snippet", "")),
                    score=score,
                )
            )
        return results

    def ensure_indexed(self) -> None:
        if not self._documents:
            return

        document_vectors = self._embedding_client.embed_texts(
            [_document_embedding_text(document) for document in self._documents],
            task_type="RETRIEVAL_DOCUMENT",
        )
        if len(document_vectors) != len(self._documents):
            raise ValueError("embedding client must return one vector for each ChromaDB document")

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


def build_chroma_retrieval_index_from_environment(
    *,
    embedding_client: EmbeddingClient,
    documents: Sequence[ChromaSourceDocument],
    root_dir: Path,
) -> ChromaRetrievalIndex | None:
    if not _truthy_env("OSCE_CHROMA_ENABLED"):
        return None

    persist_directory = _resolve_persist_directory(
        _env("CHROMA_PERSIST_DIRECTORY", DEFAULT_CHROMA_PERSIST_DIRECTORY),
        root_dir=root_dir,
    )
    collection_name = _env("OSCE_CHROMA_COLLECTION", DEFAULT_CHROMA_COLLECTION)
    return ChromaRetrievalIndex(
        settings=ChromaRetrievalSettings(
            persist_directory=persist_directory,
            collection_name=collection_name,
        ),
        embedding_client=embedding_client,
        documents=documents,
    )


def _document_embedding_text(document: ChromaSourceDocument) -> str:
    return f"{document.source_type}\n{document.reference}\n{document.title}\n{document.snippet}"


def _document_id(document: ChromaSourceDocument) -> str:
    digest = hashlib.sha256(document.reference.encode("utf-8")).hexdigest()
    return f"source-{digest}"


def _distance_to_score(distance: float) -> float:
    return max(0.0, 1.0 - distance)


def _resolve_persist_directory(raw_path: str, *, root_dir: Path) -> Path:
    persist_directory = Path(raw_path)
    if persist_directory.is_absolute():
        return persist_directory
    return root_dir / persist_directory


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _truthy_env(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


__all__ = [
    "ChromaRetrievalIndex",
    "ChromaRetrievalResult",
    "ChromaRetrievalSettings",
    "ChromaSourceDocument",
    "build_chroma_retrieval_index_from_environment",
]
