from __future__ import annotations

import json
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml

from app.services.vertex_embedding_retriever import build_vertex_embedding_client_from_environment

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"
RUBRICS_DIR = ROOT_DIR / "data" / "rubrics"
LOGGER = logging.getLogger(__name__)


class EmbeddingClient(Protocol):
    def embed_texts(self, texts: Sequence[str], *, task_type: str) -> list[list[float]]:
        ...


@dataclass(frozen=True)
class RetrievalDocument:
    reference: str
    source_type: str
    title: str
    snippet: str
    score: float


def search_retrieval_documents(query: str, limit: int = 5) -> list[RetrievalDocument]:
    normalized_query = query.strip().lower()
    if not normalized_query or limit <= 0:
        return []

    embedding_client = build_vertex_embedding_client_from_environment()
    if embedding_client is not None:
        try:
            return search_retrieval_documents_with_embeddings(query, embedding_client=embedding_client, limit=limit)
        except Exception as exc:
            LOGGER.warning("Vertex embedding retrieval failed; falling back to deterministic search: %s", exc)

    scored_documents = [
        RetrievalDocument(
            reference=document.reference,
            source_type=document.source_type,
            title=document.title,
            snippet=document.snippet,
            score=_score_document(normalized_query, document),
        )
        for document in _retrieval_documents()
    ]
    return [
        document
        for document in sorted(scored_documents, key=lambda item: (-item.score, item.source_type, item.reference))
        if document.score > 0
    ][:limit]


def search_retrieval_documents_with_embeddings(
    query: str,
    *,
    embedding_client: EmbeddingClient,
    limit: int = 5,
) -> list[RetrievalDocument]:
    normalized_query = query.strip()
    if not normalized_query or limit <= 0:
        return []

    documents = list(_retrieval_documents())
    query_vectors = embedding_client.embed_texts([normalized_query], task_type="RETRIEVAL_QUERY")
    if len(query_vectors) != 1:
        raise ValueError("embedding client must return one query vector")

    document_vectors = embedding_client.embed_texts(
        [_document_embedding_text(document) for document in documents],
        task_type="RETRIEVAL_DOCUMENT",
    )
    if len(document_vectors) != len(documents):
        raise ValueError("embedding client must return one vector for each retrieval document")

    scored_documents = [
        RetrievalDocument(
            reference=document.reference,
            source_type=document.source_type,
            title=document.title,
            snippet=document.snippet,
            score=_cosine_similarity(query_vectors[0], document_vector),
        )
        for document, document_vector in zip(documents, document_vectors)
    ]
    return [
        document
        for document in sorted(scored_documents, key=lambda item: (-item.score, item.source_type, item.reference))
        if document.score > 0
    ][:limit]


@lru_cache(maxsize=1)
def _retrieval_documents() -> tuple[RetrievalDocument, ...]:
    documents: list[RetrievalDocument] = []
    documents.extend(_case_documents())
    documents.extend(_knowledge_documents())
    documents.extend(_rubric_documents())
    return tuple(documents)


def _case_documents() -> list[RetrievalDocument]:
    documents: list[RetrievalDocument] = []
    for case_path in sorted(CASES_DIR.glob("*.json")):
        payload = json.loads(case_path.read_text(encoding="utf-8"))
        case_id = payload["case_id"]
        title = payload["case_title"]
        snippet_parts = [
            payload.get("chief_complaint", ""),
            payload.get("course_module", ""),
            payload.get("diagnosis", {}).get("main_diagnosis", ""),
            " ".join(payload.get("tags", [])),
        ]
        documents.append(
            RetrievalDocument(
                reference=f"case:{case_id}",
                source_type="case",
                title=title,
                snippet="；".join(part for part in snippet_parts if part),
                score=0,
            )
        )
    return documents


def _knowledge_documents() -> list[RetrievalDocument]:
    documents: list[RetrievalDocument] = []
    for case_path in sorted(CASES_DIR.glob("*.json")):
        payload = json.loads(case_path.read_text(encoding="utf-8"))
        case_id = payload["case_id"]
        title = f"{payload['diagnosis']['main_diagnosis']}诊断依据"
        for point in payload.get("diagnosis", {}).get("reasoning_points", []):
            documents.append(
                RetrievalDocument(
                    reference=f"knowledge:{point['point_id']}",
                    source_type="knowledge",
                    title=title,
                    snippet=point["statement"],
                    score=0,
                )
            )
    return documents



def _rubric_documents() -> list[RetrievalDocument]:
    documents: list[RetrievalDocument] = []
    for rubric_path in sorted(RUBRICS_DIR.glob("*.yaml")):
        payload = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
        rubric_id = payload["rubric_id"]
        for dimension in payload.get("dimensions", []):
            dimension_id = dimension.get("dimension_id", "")
            for item in dimension.get("items", []):
                item_id = item["item_id"]
                evidence_expected = item.get("evidence_expected", [])
                snippet = f"dimension: {dimension_id}; evidence_expected: {', '.join(evidence_expected)}"
                documents.append(
                    RetrievalDocument(
                        reference=f"rubric:{rubric_id}.item.{item_id}",
                        source_type="rubric",
                        title=item["description"],
                        snippet=snippet,
                        score=0,
                    )
                )
    return documents


def _score_document(query: str, document: RetrievalDocument) -> int:
    haystack = f"{document.reference} {document.title} {document.snippet}".lower()
    if query in haystack:
        return len(query) * 10

    return sum(1 for token in _query_tokens(query) if token in haystack)


def _document_embedding_text(document: RetrievalDocument) -> str:
    return f"{document.source_type}\n{document.reference}\n{document.title}\n{document.snippet}"


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding vectors must have the same dimensionality")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    dot_product = sum(left_value * right_value for left_value, right_value in zip(left, right))
    return dot_product / (left_norm * right_norm)


def _query_tokens(query: str) -> list[str]:
    return [token for token in query.replace("；", " ").replace(",", " ").split() if token]
