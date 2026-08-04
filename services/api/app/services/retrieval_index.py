from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml

from app.services.chroma_retriever import ChromaSourceDocument, build_chroma_retrieval_index_from_environment
from app.services.dashscope_reranker import DashScopeReranker, build_dashscope_reranker_from_environment
from app.services.local_embedding_retriever import (
    build_local_embedding_client_from_environment,
    get_local_embedding_model_name_from_environment,
)
from app.services.model_call_policy import (
    ModelProviderOverloadedError,
    ModelProviderPolicyError,
    ModelProviderTimeoutError,
)
from app.services.rag_knowledge_store import normalize_rag_stage_scope, rag_knowledge_store
from app.services.rag_hybrid_retrieval_service import (
    RankedReference,
    expand_retrieval_query,
    fuse_ranked_references,
    rank_lexical_documents,
)
from app.services.source_freshness_service import enrich_source_freshness
from app.services.vertex_embedding_retriever import (
    DEFAULT_VERTEX_EMBEDDING_MODEL,
    build_vertex_embedding_client_from_environment,
)

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"
RUBRICS_DIR = ROOT_DIR / "data" / "rubrics"
SOURCE_REGISTRY_PATH = ROOT_DIR / "data" / "attribution" / "source_registry" / "sources.json"
LOGGER = logging.getLogger(__name__)
INDEXABLE_RAG_KNOWLEDGE_VISIBILITIES = {"pre_submit_safe", "post_submit_review"}
_MODEL_ASSISTED_RETRIEVAL_ENABLED: ContextVar[bool] = ContextVar(
    "model_assisted_retrieval_enabled",
    default=True,
)


@contextmanager
def lexical_retrieval_only() -> Iterator[None]:
    """Keep deterministic system checks independent from optional model providers."""
    token = _MODEL_ASSISTED_RETRIEVAL_ENABLED.set(False)
    try:
        yield
    finally:
        _MODEL_ASSISTED_RETRIEVAL_ENABLED.reset(token)


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
    case_id: str = ""
    visibility: str = ""
    allowed_agents: tuple[str, ...] = ()
    stage_scope: tuple[str, ...] = ()
    retrieval_methods: tuple[str, ...] = ()
    vector_score: float | None = None
    lexical_score: float | None = None


def search_retrieval_documents(
    query: str,
    limit: int = 5,
    *,
    allowed_references: Collection[str] | None = None,
) -> list[RetrievalDocument]:
    results_by_query = search_retrieval_documents_batch(
        [query],
        limit=limit,
        allowed_references=allowed_references,
    )
    return results_by_query[0] if results_by_query else []


def search_retrieval_documents_batch(
    queries: Sequence[str],
    limit: int = 5,
    *,
    allowed_references: Collection[str] | None = None,
) -> list[list[RetrievalDocument]]:
    normalized_queries = [str(query).strip() for query in queries]
    results_by_query: list[list[RetrievalDocument]] = [[] for _ in normalized_queries]
    active_queries = [
        (index, query)
        for index, query in enumerate(normalized_queries)
        if query
    ]
    reference_filter = (
        frozenset(str(reference).strip() for reference in allowed_references if str(reference).strip())
        if allowed_references is not None
        else None
    )
    if limit <= 0 or not active_queries or reference_filter == frozenset():
        return results_by_query

    model_assisted_retrieval_enabled = _MODEL_ASSISTED_RETRIEVAL_ENABLED.get()
    reranker = _build_dashscope_reranker() if model_assisted_retrieval_enabled else None
    retrieval_limit = _hybrid_candidate_limit(limit, reranker)
    eligible_documents = _eligible_retrieval_documents(reference_filter)
    eligible_references = frozenset(document.reference for document in eligible_documents)
    lexical_results_by_query = {
        original_index: _search_lexical_retrieval_documents(
            query,
            documents=eligible_documents,
            limit=retrieval_limit,
        )
        for original_index, query in active_queries
    }
    if not model_assisted_retrieval_enabled:
        for original_index, _ in active_queries:
            results_by_query[original_index] = lexical_results_by_query[original_index][:limit]
        return results_by_query
    embedding_clients = _build_embedding_clients_from_environment()
    if not embedding_clients:
        LOGGER.info("RAG vector retrieval skipped because no embedding client is configured; using lexical retrieval")
        for original_index, query in active_queries:
            results_by_query[original_index] = _apply_dashscope_rerank(
                query,
                lexical_results_by_query[original_index],
                limit=limit,
                reranker=reranker,
            )
        return results_by_query

    source_documents = get_chroma_source_documents()
    chroma_candidate_limit = (
        len(source_documents)
        if reference_filter is not None
        else retrieval_limit
    )

    for embedding_client, embedding_model in embedding_clients:
        try:
            chroma_index = build_chroma_retrieval_index_from_environment(
                embedding_client=embedding_client,
                documents=source_documents,
                root_dir=ROOT_DIR,
                embedding_model=embedding_model,
            )
            if chroma_index is not None:
                chroma_results_by_query = chroma_index.search_batch(
                    [expand_retrieval_query(query) for _, query in active_queries],
                    limit=chroma_candidate_limit,
                )
                for (original_index, _), chroma_results in zip(active_queries, chroma_results_by_query):
                    vector_results = [
                        RetrievalDocument(
                            reference=result.reference,
                            source_type=result.source_type,
                            title=result.title,
                            snippet=result.snippet,
                            score=result.score,
                            retrieval_methods=("vector",),
                            vector_score=result.score,
                        )
                        for result in chroma_results
                        if result.reference in eligible_references
                    ]
                    results_by_query[original_index] = _fuse_retrieval_documents(
                        normalized_queries[original_index],
                        documents=eligible_documents,
                        vector_results=vector_results[:retrieval_limit],
                        lexical_results=lexical_results_by_query[original_index],
                        limit=limit,
                        reranker=reranker,
                    )
                return results_by_query
        except ModelProviderPolicyError:
            raise
        except Exception as exc:
            if _is_embedding_quota_error(exc):
                LOGGER.warning(
                    "ChromaDB retrieval failed for embedding model %s because embedding quota is exhausted; trying next embedding client: %s",
                    embedding_model,
                    exc,
                )
                continue
            LOGGER.warning(
                "ChromaDB retrieval failed for embedding model %s; falling back to in-memory vector search: %s",
                embedding_model,
                exc,
            )

        try:
            fallback_kwargs: dict[str, object] = {}
            if reference_filter is not None:
                fallback_kwargs["allowed_references"] = reference_filter
            embedding_results_by_query = search_retrieval_documents_with_embeddings_batch(
                [query for _, query in active_queries],
                embedding_client=embedding_client,
                limit=limit,
                reranker=reranker,
                **fallback_kwargs,
            )
            for (original_index, _), embedding_results in zip(active_queries, embedding_results_by_query):
                results_by_query[original_index] = embedding_results
            return results_by_query
        except ModelProviderPolicyError:
            raise
        except Exception as exc:
            LOGGER.warning("RAG vector retrieval failed for embedding model %s: %s", embedding_model, exc)
            continue
    LOGGER.warning("RAG vector retrieval failed for every configured embedding client; using lexical retrieval")
    for original_index, query in active_queries:
        results_by_query[original_index] = _apply_dashscope_rerank(
            query,
            lexical_results_by_query[original_index],
            limit=limit,
            reranker=reranker,
        )
    return results_by_query


def _build_embedding_client_from_environment() -> tuple[EmbeddingClient | None, str]:
    embedding_clients = _build_embedding_clients_from_environment()
    return embedding_clients[0] if embedding_clients else (None, "")


def _build_embedding_clients_from_environment() -> list[tuple[EmbeddingClient, str]]:
    embedding_clients: list[tuple[EmbeddingClient, str]] = []
    try:
        vertex_embedding_client = build_vertex_embedding_client_from_environment()
    except Exception as exc:
        LOGGER.warning("Vertex embedding client initialization failed; continuing without it: %s", exc)
        vertex_embedding_client = None
    if vertex_embedding_client is not None:
        embedding_clients.append(
            (vertex_embedding_client, _env("OSCE_VERTEX_EMBEDDING_MODEL", DEFAULT_VERTEX_EMBEDDING_MODEL))
        )
    try:
        local_embedding_client = build_local_embedding_client_from_environment()
    except Exception as exc:
        LOGGER.warning("Local embedding client initialization failed; continuing without it: %s", exc)
        local_embedding_client = None
    if local_embedding_client is not None:
        embedding_clients.append((local_embedding_client, get_local_embedding_model_name_from_environment()))
    return embedding_clients


def search_retrieval_documents_with_embeddings(
    query: str,
    *,
    embedding_client: EmbeddingClient,
    limit: int = 5,
    allowed_references: Collection[str] | None = None,
) -> list[RetrievalDocument]:
    results_by_query = search_retrieval_documents_with_embeddings_batch(
        [query],
        embedding_client=embedding_client,
        limit=limit,
        allowed_references=allowed_references,
    )
    return results_by_query[0] if results_by_query else []


def search_retrieval_documents_with_embeddings_batch(
    queries: Sequence[str],
    *,
    embedding_client: EmbeddingClient,
    limit: int = 5,
    reranker: DashScopeReranker | None = None,
    allowed_references: Collection[str] | None = None,
) -> list[list[RetrievalDocument]]:
    normalized_queries = [str(query).strip() for query in queries]
    results_by_query: list[list[RetrievalDocument]] = [[] for _ in normalized_queries]
    active_queries = [
        (index, query)
        for index, query in enumerate(normalized_queries)
        if query
    ]
    if limit <= 0 or not active_queries:
        return results_by_query

    reranker = reranker if reranker is not None else _build_dashscope_reranker()
    retrieval_limit = _hybrid_candidate_limit(limit, reranker)
    reference_filter = (
        frozenset(str(reference).strip() for reference in allowed_references if str(reference).strip())
        if allowed_references is not None
        else None
    )
    documents = [
        document
        for document in _retrieval_documents()
        if reference_filter is None or document.reference in reference_filter
    ]
    if not documents:
        return results_by_query
    query_vectors = embedding_client.embed_texts(
        [expand_retrieval_query(query) for _, query in active_queries],
        task_type="RETRIEVAL_QUERY",
    )
    if len(query_vectors) != len(active_queries):
        raise ValueError("embedding client must return one vector for each query")

    document_vectors = embedding_client.embed_texts(
        [_document_embedding_text(document) for document in documents],
        task_type="RETRIEVAL_DOCUMENT",
    )
    if len(document_vectors) != len(documents):
        raise ValueError("embedding client must return one vector for each retrieval document")

    for (original_index, _), query_vector in zip(active_queries, query_vectors):
        scored_documents: list[RetrievalDocument] = []
        for document, document_vector in zip(documents, document_vectors):
            vector_score = _cosine_similarity(query_vector, document_vector)
            scored_documents.append(
                replace(
                    document,
                    score=vector_score,
                    retrieval_methods=("vector",),
                    vector_score=vector_score,
                )
            )
        vector_results = [
            document
            for document in sorted(scored_documents, key=lambda item: (-item.score, item.source_type, item.reference))
            if document.score > 0
        ][:retrieval_limit]
        lexical_results = _search_lexical_retrieval_documents(
            normalized_queries[original_index],
            documents=documents,
            limit=retrieval_limit,
        )
        results_by_query[original_index] = _fuse_retrieval_documents(
            normalized_queries[original_index],
            documents=documents,
            vector_results=vector_results,
            lexical_results=lexical_results,
            limit=limit,
            reranker=reranker,
        )
    return results_by_query


def get_chroma_source_documents() -> tuple[ChromaSourceDocument, ...]:
    return tuple(
        ChromaSourceDocument(
            reference=document.reference,
            source_type=document.source_type,
            title=document.title,
            snippet=document.snippet,
            case_id=document.case_id,
            visibility=document.visibility,
            allowed_agents="|".join(document.allowed_agents),
            stage_scope="|".join(document.stage_scope),
        )
        for document in _retrieval_documents()
    )


@lru_cache(maxsize=1)
def _retrieval_documents() -> tuple[RetrievalDocument, ...]:
    documents: list[RetrievalDocument] = []
    documents.extend(_case_documents())
    documents.extend(_source_documents())
    documents.extend(_managed_rag_knowledge_documents())
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


def _managed_rag_knowledge_documents() -> list[RetrievalDocument]:
    documents: list[RetrievalDocument] = []
    for item in rag_knowledge_store.list_items():
        if item.get("enabled") is False:
            continue
        if item.get("review_status", "approved") != "approved":
            continue
        visibility = str(item.get("visibility", "")).strip()
        if visibility not in INDEXABLE_RAG_KNOWLEDGE_VISIBILITIES:
            continue
        knowledge_id = str(item.get("knowledge_id", "")).strip()
        title = str(item.get("title", "")).strip()
        text = str(item.get("text", "")).strip()
        if not knowledge_id or not title or not text:
            continue
        snippet_parts = [
            f"scope: {str(item.get('scope', '')).strip()}",
            f"case_id: {str(item.get('case_id', '')).strip()}",
            f"content_kind: {str(item.get('content_kind', '')).strip()}",
            f"visibility: {visibility}",
            f"allowed_agents: {', '.join(str(agent) for agent in item.get('allowed_agents', []) if str(agent))}",
            f"stage_scope: {', '.join(normalize_rag_stage_scope(item.get('stage_scope')))}",
            f"source_id: {str(item.get('source_id', '')).strip()}",
            f"tags: {', '.join(str(tag) for tag in item.get('tags', []) if str(tag))}",
            text,
        ]
        documents.append(
            RetrievalDocument(
                reference=f"rag_knowledge:{knowledge_id}",
                source_type="rag_knowledge",
                title=title,
                snippet="；".join(part for part in snippet_parts if part),
                score=0,
                case_id=str(item.get("case_id", "")).strip(),
                visibility=visibility,
                allowed_agents=tuple(
                    str(agent).strip()
                    for agent in item.get("allowed_agents", [])
                    if str(agent).strip()
                ),
                stage_scope=tuple(normalize_rag_stage_scope(item.get("stage_scope"))),
            )
        )
    return documents


def _source_documents() -> list[RetrievalDocument]:
    if not SOURCE_REGISTRY_PATH.exists():
        return []
    payload = json.loads(SOURCE_REGISTRY_PATH.read_text(encoding="utf-8"))
    documents: list[RetrievalDocument] = []
    for raw_item in payload if isinstance(payload, list) else []:
        if not isinstance(raw_item, dict):
            continue
        item = enrich_source_freshness(raw_item)
        source_id = str(item.get("source_id", ""))
        if not source_id:
            continue
        snippet_parts = [
            item.get("source_name", ""),
            " ".join(str(alias) for alias in item.get("search_aliases", []) if str(alias)),
            item.get("source_url", ""),
            item.get("license", ""),
            item.get("data_type", ""),
            " ".join(str(usage) for usage in item.get("allowed_usage", [])),
            item.get("transformation", ""),
            item.get("risk_note", ""),
            item.get("review_basis", ""),
            f"source_version: {item.get('source_version', '')}",
            f"freshness_status: {item.get('freshness_status', '')}",
            f"last_reviewed_at: {item.get('last_reviewed_at', '')}",
            f"review_due_at: {item.get('review_due_at', '')}",
            f"superseded_by: {item.get('superseded_by', '')}",
        ]
        documents.append(
            RetrievalDocument(
                reference=f"source:{source_id}",
                source_type="source",
                title=str(item.get("source_name", source_id)),
                snippet="；".join(str(part) for part in snippet_parts if part),
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


def _document_embedding_text(document: RetrievalDocument) -> str:
    return f"{document.source_type}\n{document.reference}\n{document.title}\n{document.snippet}"


def _eligible_retrieval_documents(
    reference_filter: frozenset[str] | None,
) -> list[RetrievalDocument]:
    return [
        document
        for document in _retrieval_documents()
        if reference_filter is None or document.reference in reference_filter
    ]


def _search_lexical_retrieval_documents(
    query: str,
    *,
    documents: Sequence[RetrievalDocument],
    limit: int,
) -> list[RetrievalDocument]:
    documents_by_reference = {document.reference: document for document in documents}
    return [
        replace(
            documents_by_reference[result.reference],
            score=result.score,
            retrieval_methods=("lexical",),
            lexical_score=result.score,
        )
        for result in rank_lexical_documents(query, documents, limit=limit)
        if result.reference in documents_by_reference
    ]


def _fuse_retrieval_documents(
    query: str,
    *,
    documents: Sequence[RetrievalDocument],
    vector_results: Sequence[RetrievalDocument],
    lexical_results: Sequence[RetrievalDocument],
    limit: int,
    reranker: DashScopeReranker | None,
) -> list[RetrievalDocument]:
    documents_by_reference = {document.reference: document for document in documents}
    vector_by_reference = {document.reference: document for document in vector_results}
    lexical_by_reference = {document.reference: document for document in lexical_results}
    candidate_limit = _hybrid_candidate_limit(limit, reranker)
    fused_references = fuse_ranked_references(
        vector_results=[
            RankedReference(reference=document.reference, score=document.score)
            for document in vector_results
        ],
        lexical_results=[
            RankedReference(reference=document.reference, score=document.score)
            for document in lexical_results
        ],
        limit=candidate_limit,
    )
    fused_documents: list[RetrievalDocument] = []
    for fused_reference in fused_references:
        base_document = (
            documents_by_reference.get(fused_reference.reference)
            or vector_by_reference.get(fused_reference.reference)
            or lexical_by_reference.get(fused_reference.reference)
        )
        if base_document is None:
            continue
        fused_documents.append(
            replace(
                base_document,
                score=fused_reference.score,
                retrieval_methods=fused_reference.retrieval_methods,
                vector_score=fused_reference.vector_score,
                lexical_score=fused_reference.lexical_score,
            )
        )
    return _apply_dashscope_rerank(
        query,
        fused_documents,
        limit=limit,
        reranker=reranker,
    )


def _build_dashscope_reranker() -> DashScopeReranker | None:
    try:
        return build_dashscope_reranker_from_environment()
    except Exception as exc:
        LOGGER.warning("DashScope reranker initialization failed; continuing without rerank: %s", exc)
        return None


def _rerank_candidate_limit(result_limit: int, reranker: DashScopeReranker | None) -> int:
    if reranker is None:
        return result_limit
    return reranker.candidate_limit(result_limit)


def _hybrid_candidate_limit(result_limit: int, reranker: DashScopeReranker | None) -> int:
    fusion_limit = min(50, max(result_limit, result_limit * 4))
    return max(fusion_limit, _rerank_candidate_limit(result_limit, reranker))


def _apply_dashscope_rerank(
    query: str,
    documents: Sequence[RetrievalDocument],
    *,
    limit: int,
    reranker: DashScopeReranker | None = None,
) -> list[RetrievalDocument]:
    vector_results = list(documents)
    if limit <= 0 or not vector_results:
        return []

    reranker = reranker if reranker is not None else _build_dashscope_reranker()
    if reranker is None or len(vector_results) <= 1:
        return vector_results[:limit]

    try:
        rerank_results = reranker.rerank(
            query,
            [_document_embedding_text(document) for document in vector_results],
            top_k=reranker.top_limit(limit, len(vector_results)),
        )
    except (ModelProviderTimeoutError, ModelProviderOverloadedError) as exc:
        LOGGER.warning(
            "DashScope rerank was unavailable within its optional budget; using vector order: %s",
            exc,
        )
        return vector_results[:limit]
    except ModelProviderPolicyError:
        raise
    except Exception as exc:
        LOGGER.warning("DashScope rerank failed; using vector order: %s", exc)
        return vector_results[:limit]

    reranked_documents: list[RetrievalDocument] = []
    used_indexes: set[int] = set()
    for result in rerank_results:
        if result.index < 0 or result.index >= len(vector_results) or result.index in used_indexes:
            continue
        used_indexes.add(result.index)
        reranked_documents.append(replace(vector_results[result.index], score=result.relevance_score))

    if len(reranked_documents) < limit:
        reranked_documents.extend(
            document
            for index, document in enumerate(vector_results)
            if index not in used_indexes
        )
    return reranked_documents[:limit]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding vectors must have the same dimensionality")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    dot_product = sum(left_value * right_value for left_value, right_value in zip(left, right))
    return dot_product / (left_norm * right_norm)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _is_embedding_quota_error(error: BaseException) -> bool:
    message = str(error)
    return "RESOURCE_EXHAUSTED" in message or "quota exceeded" in message.lower()
