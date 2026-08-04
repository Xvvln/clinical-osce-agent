import hashlib
import json

import pytest

from app.services import retrieval_index as retrieval_index_module
from app.services import vertex_embedding_retriever as vertex_embedding_retriever_module
from app.services.chroma_retriever import (
    DEFAULT_CHROMA_SEARCH_EF,
    ChromaRetrievalIndex,
    ChromaRetrievalResult,
    ChromaRetrievalSettings,
    ChromaSourceDocument,
    build_chroma_manifest_status,
    build_chroma_retrieval_settings_from_environment,
)
from app.services.rag_knowledge_store import RagKnowledgeStore
from app.services.retrieval_index import (
    RetrievalDocument,
    search_retrieval_documents,
    search_retrieval_documents_batch,
    search_retrieval_documents_with_embeddings,
)
from app.services.model_call_policy import (
    ModelProviderOverloadedError,
    ModelProviderTimeoutError,
)
from app.services.runtime_model_config_store import runtime_model_config_store


@pytest.fixture(autouse=True)
def clear_retrieval_document_cache():
    retrieval_index_module._retrieval_documents.cache_clear()
    yield
    retrieval_index_module._retrieval_documents.cache_clear()


def _unique_chroma_collection(tmp_path) -> str:  # type: ignore[no-untyped-def]
    digest = hashlib.sha1(str(tmp_path).encode("utf-8")).hexdigest()[:12]
    return f"test_retrieval_{digest}"


class FakeEmbeddingClient:
    def embed_texts(self, texts: list[str], *, task_type: str) -> list[list[float]]:
        if task_type == "RETRIEVAL_QUERY":
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]
        if task_type == "RETRIEVAL_DOCUMENT":
            vectors: list[list[float]] = []
            for index, text in enumerate(texts):
                if "白细胞升高" in text:
                    vectors.append([1.0, 0.0, 0.0, 0.0])
                else:
                    vectors.append(
                        [0.0, 1.0, float((index % 7) + 1) / 10.0, float((index % 11) + 1) / 10.0]
                    )
            return vectors
        raise AssertionError(f"unexpected task_type: {task_type}")


class ThreeDimensionalFakeEmbeddingClient:
    def embed_texts(self, texts: list[str], *, task_type: str) -> list[list[float]]:
        if task_type == "RETRIEVAL_QUERY":
            return [[1.0, 0.0, 0.0] for _ in texts]
        if task_type == "RETRIEVAL_DOCUMENT":
            return [
                [1.0, 0.0, 0.0] if "白细胞升高" in text else [0.0, 1.0, 0.0]
                for text in texts
            ]
        raise AssertionError(f"unexpected task_type: {task_type}")


class CountingFakeEmbeddingClient(FakeEmbeddingClient):
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def embed_texts(self, texts: list[str], *, task_type: str) -> list[list[float]]:
        self.calls.append((task_type, len(texts)))
        return super().embed_texts(texts, task_type=task_type)


class ResourceExhaustedEmbeddingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def embed_texts(self, texts: list[str], *, task_type: str) -> list[list[float]]:
        self.calls.append((task_type, len(texts)))
        raise RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded for gemini-embedding")


class ExactPhraseFakeEmbeddingClient:
    def __init__(self, phrase: str) -> None:
        self.phrase = phrase

    def embed_texts(self, texts: list[str], *, task_type: str) -> list[list[float]]:
        if task_type == "RETRIEVAL_QUERY":
            return [
                [1.0, 0.0, 0.0, 0.0] if self.phrase in text else [0.0, 1.0, 0.0, 0.0]
                for text in texts
            ]
        if task_type == "RETRIEVAL_DOCUMENT":
            return [
                [1.0, 0.0, 0.0, 0.0] if self.phrase in text else [0.0, 1.0, 0.0, 0.0]
                for text in texts
            ]
        raise AssertionError(f"unexpected task_type: {task_type}")


class FakeGenAIEmbeddingClient:
    created_kwargs: list[dict[str, object]] = []
    embed_content_calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.created_kwargs.append(kwargs)
        self.models = self

    def embed_content(self, **kwargs: object):
        self.embed_content_calls.append(kwargs)
        contents = kwargs.get("contents", [])
        content_count = len(contents) if isinstance(contents, list) else 1
        return type(
            "FakeEmbeddingResponse",
            (),
            {
                "embeddings": [
                    type("FakeEmbedding", (), {"values": [float(index), 0.2, 0.3]})()
                    for index in range(content_count)
                ]
            },
        )()


def test_search_retrieval_documents_uses_lexical_fallback_without_embedding_client(
    monkeypatch,
) -> None:
    monkeypatch.setattr(retrieval_index_module, "build_vertex_embedding_client_from_environment", lambda: None)
    monkeypatch.setattr(retrieval_index_module, "build_local_embedding_client_from_environment", lambda: None)

    results = search_retrieval_documents("右下腹痛", limit=3)

    assert results
    assert results[0].reference == "case:appendicitis_001"
    assert results[0].retrieval_methods == ("lexical",)
    assert results[0].lexical_score is not None


def test_lexical_fallback_applies_allowed_references_before_ranking(monkeypatch) -> None:
    allowed_reference = "rubric:appendicitis_001_rubric.item.pe_rebound"
    monkeypatch.setattr(retrieval_index_module, "build_vertex_embedding_client_from_environment", lambda: None)
    monkeypatch.setattr(retrieval_index_module, "build_local_embedding_client_from_environment", lambda: None)
    monkeypatch.setattr(retrieval_index_module, "_build_dashscope_reranker", lambda: None)

    results = search_retrieval_documents(
        "反跳痛和腹膜刺激征怎么查",
        limit=3,
        allowed_references={allowed_reference},
    )

    assert [result.reference for result in results] == [allowed_reference]
    assert results[0].retrieval_methods == ("lexical",)


def test_search_retrieval_documents_returns_case_for_clinical_query(monkeypatch) -> None:
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "false")
    monkeypatch.setattr(
        retrieval_index_module,
        "build_vertex_embedding_client_from_environment",
        lambda: ExactPhraseFakeEmbeddingClient("右下腹痛"),
    )

    results = search_retrieval_documents("右下腹痛", limit=3)

    assert results
    assert results[0].reference == "case:appendicitis_001"
    assert results[0].source_type == "case"
    assert results[0].title == "右下腹痛教学病例"
    assert "转移性右下腹痛" in results[0].snippet
    assert results[0].score > 0


def test_search_retrieval_documents_uses_local_embedding_when_vertex_is_not_configured(monkeypatch) -> None:
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "false")
    monkeypatch.setattr(
        retrieval_index_module,
        "build_vertex_embedding_client_from_environment",
        lambda: None,
    )
    monkeypatch.setattr(
        retrieval_index_module,
        "build_local_embedding_client_from_environment",
        lambda: ExactPhraseFakeEmbeddingClient("右下腹痛"),
    )

    results = search_retrieval_documents("右下腹痛", limit=3)

    assert results
    assert results[0].reference == "case:appendicitis_001"
    assert results[0].source_type == "case"


def test_search_retrieval_documents_falls_back_to_local_embedding_when_vertex_fails(monkeypatch) -> None:
    class FailingVertexEmbeddingClient:
        def embed_texts(self, texts: list[str], *, task_type: str) -> list[list[float]]:
            raise RuntimeError("vertex embedding quota exceeded")

    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "false")
    monkeypatch.setattr(
        retrieval_index_module,
        "build_vertex_embedding_client_from_environment",
        lambda: FailingVertexEmbeddingClient(),
    )
    monkeypatch.setattr(
        retrieval_index_module,
        "build_local_embedding_client_from_environment",
        lambda: ExactPhraseFakeEmbeddingClient("右下腹痛"),
    )

    results = search_retrieval_documents("右下腹痛", limit=3)

    assert results
    assert results[0].reference == "case:appendicitis_001"
    assert results[0].source_type == "case"


def test_search_retrieval_documents_does_not_hide_provider_timeout(
    monkeypatch,
) -> None:
    class TimedOutVertexEmbeddingClient:
        def embed_texts(
            self,
            texts: list[str],
            *,
            task_type: str,
        ) -> list[list[float]]:
            raise ModelProviderTimeoutError("deadline exceeded")

    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "false")
    monkeypatch.setattr(
        retrieval_index_module,
        "build_vertex_embedding_client_from_environment",
        lambda: TimedOutVertexEmbeddingClient(),
    )
    monkeypatch.setattr(
        retrieval_index_module,
        "build_local_embedding_client_from_environment",
        lambda: ExactPhraseFakeEmbeddingClient("右下腹痛"),
    )

    with pytest.raises(ModelProviderTimeoutError):
        search_retrieval_documents("右下腹痛", limit=3)


@pytest.mark.parametrize(
    "provider_error",
    [
        ModelProviderOverloadedError("provider busy"),
        ModelProviderTimeoutError("provider exceeded its optional budget"),
    ],
    ids=["overload", "timeout"],
)
def test_dashscope_rerank_falls_back_to_vector_order_on_transient_provider_error(
    provider_error: Exception,
) -> None:
    class UnavailableReranker:
        def rerank(
            self,
            query: str,
            documents: list[str],
            *,
            top_k: int,
        ) -> list[object]:
            raise provider_error

        def top_limit(self, result_limit: int, document_count: int) -> int:
            return min(result_limit, document_count)

    documents = [
        RetrievalDocument(
            reference=f"case:{index}",
            source_type="case",
            title=f"病例 {index}",
            snippet="摘要",
            score=float(index),
        )
        for index in range(2)
    ]

    results = retrieval_index_module._apply_dashscope_rerank(
        "右下腹痛",
        documents,
        limit=2,
        reranker=UnavailableReranker(),  # type: ignore[arg-type]
    )

    assert [result.reference for result in results] == ["case:0", "case:1"]


def test_search_retrieval_documents_skips_same_vertex_in_memory_fallback_after_quota_error(
    tmp_path,
    monkeypatch,
) -> None:
    vertex_client = ResourceExhaustedEmbeddingClient()
    local_client = CountingFakeEmbeddingClient()
    monkeypatch.delenv("OSCE_CHROMA_ENABLED", raising=False)
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", str(tmp_path / "chroma"))
    monkeypatch.setenv("OSCE_CHROMA_COLLECTION", _unique_chroma_collection(tmp_path))
    monkeypatch.setattr(
        retrieval_index_module,
        "build_vertex_embedding_client_from_environment",
        lambda: vertex_client,
    )
    monkeypatch.setattr(
        retrieval_index_module,
        "build_local_embedding_client_from_environment",
        lambda: local_client,
    )

    search_retrieval_documents("右下腹痛", limit=3)

    assert len(vertex_client.calls) == 1
    assert local_client.calls


def test_search_retrieval_documents_skips_unavailable_local_embedding_client(monkeypatch) -> None:
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "false")
    monkeypatch.setattr(
        retrieval_index_module,
        "build_vertex_embedding_client_from_environment",
        lambda: None,
    )
    monkeypatch.setattr(
        retrieval_index_module,
        "build_local_embedding_client_from_environment",
        lambda: (_ for _ in ()).throw(RuntimeError("fastembed is required when OSCE_LOCAL_EMBEDDING_ENABLED=true")),
    )

    results = search_retrieval_documents("右下腹痛", limit=3)

    assert results
    assert results[0].reference == "case:appendicitis_001"
    assert results[0].retrieval_methods == ("lexical",)


def test_search_retrieval_documents_returns_rubric_item_for_exam_query(monkeypatch) -> None:
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "false")
    monkeypatch.setattr(
        retrieval_index_module,
        "build_vertex_embedding_client_from_environment",
        lambda: ExactPhraseFakeEmbeddingClient("反跳痛"),
    )

    results = search_retrieval_documents("反跳痛", limit=5)

    rubric_result = next(
        result
        for result in results
        if result.reference == "rubric:appendicitis_001_rubric.item.pe_rebound"
    )
    assert rubric_result.source_type == "rubric"
    assert rubric_result.title == "检查反跳痛"
    assert "evidence_expected: abd.palpation.rebound" in rubric_result.snippet
    assert rubric_result.score > 0


def test_search_retrieval_documents_returns_knowledge_item_for_reasoning_query(monkeypatch) -> None:
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "false")
    monkeypatch.setattr(
        retrieval_index_module,
        "build_vertex_embedding_client_from_environment",
        lambda: FakeEmbeddingClient(),
    )

    results = search_retrieval_documents("白细胞升高", limit=8)

    knowledge_result = next(
        result
        for result in results
        if result.reference == "knowledge:appendicitis_001.rp_03"
    )
    assert knowledge_result.source_type == "knowledge"
    assert knowledge_result.title == "急性阑尾炎诊断依据"
    assert "白细胞升高" in knowledge_result.snippet
    assert knowledge_result.score > 0


def test_search_retrieval_documents_includes_admin_managed_safe_knowledge(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "false")
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    store.upsert_item(
        {
            "knowledge_id": "case:appendicitis_001:teaching:history_migration",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "teaching_note",
            "visibility": "pre_submit_safe",
            "allowed_agents": ["coach"],
            "source_id": "fareez_osce_2022",
            "title": "右下腹痛问诊中的疼痛迁移",
            "text": "疼痛迁移训练应追问是否从上腹或脐周转移到右下腹。",
            "tags": ["abdominal_pain", "history_taking"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )
    store.upsert_item(
        {
            "knowledge_id": "case:appendicitis_001:admin:hidden_answer_note",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "internal_note",
            "visibility": "secret_scoring_only",
            "allowed_agents": ["scoring"],
            "source_id": "",
            "title": "隐藏答案内部说明",
            "text": "隐藏答案内部说明不应进入通用检索索引。",
            "tags": ["internal"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )
    monkeypatch.setattr(retrieval_index_module, "rag_knowledge_store", store)
    monkeypatch.setattr(
        retrieval_index_module,
        "build_vertex_embedding_client_from_environment",
        lambda: ExactPhraseFakeEmbeddingClient("疼痛迁移训练"),
    )
    retrieval_index_module._retrieval_documents.cache_clear()

    results = search_retrieval_documents("疼痛迁移训练", limit=5)
    hidden_results = search_retrieval_documents("隐藏答案内部说明", limit=5)

    managed_result = next(
        result
        for result in results
        if result.reference == "rag_knowledge:case:appendicitis_001:teaching:history_migration"
    )
    assert managed_result.source_type == "rag_knowledge"
    assert managed_result.title == "右下腹痛问诊中的疼痛迁移"
    assert "visibility: pre_submit_safe" in managed_result.snippet
    assert "source_id: fareez_osce_2022" in managed_result.snippet
    assert "疼痛迁移训练" in managed_result.snippet
    assert all(result.source_type != "rag_knowledge" for result in hidden_results)


def test_retrieval_index_excludes_unapproved_managed_knowledge(tmp_path, monkeypatch) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    for review_status in ["pending_review", "rejected"]:
        store.upsert_item(
            {
                "knowledge_id": f"global:review:{review_status}",
                "scope": "global",
                "case_id": "",
                "content_kind": "teaching_note",
                "visibility": "pre_submit_safe",
                "allowed_agents": ["coach"],
                "source_id": "",
                "title": review_status,
                "text": f"不应进入索引 {review_status}",
                "tags": ["review"],
                "review_status": review_status,
            },
            updated_by="admin@example.test",
        )
    monkeypatch.setattr(retrieval_index_module, "rag_knowledge_store", store)
    retrieval_index_module._retrieval_documents.cache_clear()

    references = {document.reference for document in retrieval_index_module._retrieval_documents()}

    assert "rag_knowledge:global:review:pending_review" not in references
    assert "rag_knowledge:global:review:rejected" not in references


def test_chroma_source_documents_include_admin_managed_knowledge_in_manifest(tmp_path, monkeypatch) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    store.upsert_item(
        {
            "knowledge_id": "case:appendicitis_001:teaching:history_migration",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "teaching_note",
            "visibility": "post_submit_review",
            "allowed_agents": ["reflection", "skill_approval"],
            "stage_scope": ["feedback"],
            "source_id": "fareez_osce_2022",
            "title": "右下腹痛问诊中的疼痛迁移",
            "text": "训练后复盘可强调疼痛演变采集不足的问题。",
            "tags": ["reflection"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )
    monkeypatch.setattr(retrieval_index_module, "rag_knowledge_store", store)
    retrieval_index_module._retrieval_documents.cache_clear()

    documents = retrieval_index_module.get_chroma_source_documents()
    settings = ChromaRetrievalSettings(
        persist_directory=tmp_path / "chroma",
        collection_name="test_retrieval_documents",
        embedding_model="fake-embedding-model",
    )
    manifest = build_chroma_manifest_status(settings=settings, documents=documents)

    managed_document = next(
        document
        for document in documents
        if document.reference == "rag_knowledge:case:appendicitis_001:teaching:history_migration"
    )
    assert managed_document.source_type == "rag_knowledge"
    assert "post_submit_review" in managed_document.snippet
    assert "stage_scope: feedback" in managed_document.snippet
    assert managed_document.case_id == "appendicitis_001"
    assert managed_document.visibility == "post_submit_review"
    assert managed_document.allowed_agents == "reflection|skill_approval"
    assert managed_document.stage_scope == "feedback"
    assert manifest["source_count"] == len(documents)
    assert "appendicitis_001" in manifest["case_ids"]
    assert manifest["content_hash"].startswith("sha256:")


def test_search_retrieval_documents_with_embeddings_can_recall_semantic_source_without_keyword_overlap() -> None:
    results = search_retrieval_documents_with_embeddings(
        "炎症实验室证据",
        embedding_client=FakeEmbeddingClient(),
        limit=3,
    )

    assert results
    assert results[0].reference == "knowledge:appendicitis_001.rp_03"
    assert results[0].source_type == "knowledge"
    assert results[0].score > 0.9
    assert results[0].retrieval_methods == ("vector", "lexical")


def test_chroma_retrieval_index_persists_vectors_between_clients(tmp_path) -> None:
    documents = [
        ChromaSourceDocument(
            reference="knowledge:appendicitis_001.rp_03",
            source_type="knowledge",
            title="急性阑尾炎诊断依据",
            snippet="白细胞升高提示炎症反应。",
        ),
        ChromaSourceDocument(
            reference="case:appendicitis_001",
            source_type="case",
            title="右下腹痛教学病例",
            snippet="转移性右下腹痛。",
        ),
    ]
    settings = ChromaRetrievalSettings(
        persist_directory=tmp_path / "chroma",
        collection_name="test_retrieval_documents",
    )

    first_index = ChromaRetrievalIndex(
        settings=settings,
        embedding_client=FakeEmbeddingClient(),
        documents=documents,
    )
    first_results = first_index.search("炎症实验室证据", limit=2)
    second_index = ChromaRetrievalIndex(
        settings=settings,
        embedding_client=FakeEmbeddingClient(),
        documents=documents,
    )
    second_results = second_index.search("炎症实验室证据", limit=2)

    assert first_results[0].reference == "knowledge:appendicitis_001.rp_03"
    assert second_results[0].reference == "knowledge:appendicitis_001.rp_03"
    assert second_results[0].source_type == "knowledge"
    assert second_results[0].score > 0.99
    assert any(settings.persist_directory.iterdir())


def test_chroma_retrieval_index_skips_document_embedding_when_manifest_is_current(tmp_path) -> None:
    documents = [
        ChromaSourceDocument(
            reference="knowledge:appendicitis_001.rp_03",
            source_type="knowledge",
            title="急性阑尾炎诊断依据",
            snippet="白细胞升高提示炎症反应。",
        ),
        ChromaSourceDocument(
            reference="case:appendicitis_001",
            source_type="case",
            title="右下腹痛教学病例",
            snippet="转移性右下腹痛。",
        ),
    ]
    settings = ChromaRetrievalSettings(
        persist_directory=tmp_path / "chroma",
        collection_name="test_retrieval_documents",
    )
    first_index = ChromaRetrievalIndex(
        settings=settings,
        embedding_client=FakeEmbeddingClient(),
        documents=documents,
    )
    first_index.search("炎症实验室证据", limit=2)
    counting_client = CountingFakeEmbeddingClient()
    second_index = ChromaRetrievalIndex(
        settings=settings,
        embedding_client=counting_client,
        documents=documents,
    )

    results = second_index.search("炎症实验室证据", limit=2)

    assert results[0].reference == "knowledge:appendicitis_001.rp_03"
    assert ("RETRIEVAL_QUERY", 1) in counting_client.calls
    assert not any(task_type == "RETRIEVAL_DOCUMENT" for task_type, _ in counting_client.calls)


def test_chroma_retrieval_index_batches_query_embeddings_when_manifest_is_current(tmp_path) -> None:
    documents = [
        ChromaSourceDocument(
            reference="knowledge:appendicitis_001.rp_03",
            source_type="knowledge",
            title="急性阑尾炎诊断依据",
            snippet="白细胞升高提示炎症反应。",
        ),
        ChromaSourceDocument(
            reference="case:appendicitis_001",
            source_type="case",
            title="右下腹痛教学病例",
            snippet="转移性右下腹痛。",
        ),
    ]
    settings = ChromaRetrievalSettings(
        persist_directory=tmp_path / "chroma",
        collection_name="test_retrieval_documents",
    )
    first_index = ChromaRetrievalIndex(
        settings=settings,
        embedding_client=FakeEmbeddingClient(),
        documents=documents,
    )
    first_index.search("炎症实验室证据", limit=2)
    counting_client = CountingFakeEmbeddingClient()
    second_index = ChromaRetrievalIndex(
        settings=settings,
        embedding_client=counting_client,
        documents=documents,
    )

    results_by_query = second_index.search_batch(["炎症实验室证据", "右下腹痛病例"], limit=2)

    assert len(results_by_query) == 2
    assert results_by_query[0][0].reference == "knowledge:appendicitis_001.rp_03"
    assert ("RETRIEVAL_QUERY", 2) in counting_client.calls
    assert not any(task_type == "RETRIEVAL_DOCUMENT" for task_type, _ in counting_client.calls)


def test_chroma_retrieval_index_reuses_query_embedding_for_filtered_empty_exact_retry(
    monkeypatch,
) -> None:
    documents = [
        ChromaSourceDocument(
            reference=f"knowledge:appendicitis_001.rp_{index}",
            source_type="knowledge",
            title=f"知识条目 {index}",
            snippet=f"教学片段 {index}",
        )
        for index in range(3)
    ]
    embedding_client = CountingFakeEmbeddingClient()
    index = object.__new__(ChromaRetrievalIndex)
    index._documents = tuple(documents)
    index._embedding_client = embedding_client
    query_calls: list[tuple[list[list[float]], int]] = []

    def fake_query_collection(query_vectors: list[list[float]], *, limit: int) -> dict[str, object]:
        query_calls.append((query_vectors, limit))
        if limit == 1:
            return {
                "metadatas": [
                    [
                        {
                            "reference": documents[0].reference,
                            "source_type": documents[0].source_type,
                            "title": documents[0].title,
                            "snippet": documents[0].snippet,
                        }
                    ],
                    [
                        {
                            "reference": documents[1].reference,
                            "source_type": documents[1].source_type,
                            "title": documents[1].title,
                            "snippet": documents[1].snippet,
                        }
                    ],
                ],
                "distances": [[0.1], [1.1]],
            }
        return {
            "metadatas": [
                [
                    {
                        "reference": documents[2].reference,
                        "source_type": documents[2].source_type,
                        "title": documents[2].title,
                        "snippet": documents[2].snippet,
                    }
                ]
            ],
            "distances": [[0.2]],
        }

    monkeypatch.setattr(index, "ensure_indexed", lambda: None)
    monkeypatch.setattr(index, "_query_collection", fake_query_collection)

    results_by_query = index.search_batch(["首个问题", "需要精确重查的问题"], limit=1)

    assert embedding_client.calls == [("RETRIEVAL_QUERY", 2)]
    assert [limit for _, limit in query_calls] == [1, len(documents)]
    assert query_calls[1][0][0] is query_calls[0][0][1]
    assert results_by_query[0][0].reference == documents[0].reference
    assert results_by_query[1][0].reference == documents[2].reference


def test_chroma_retrieval_index_recovers_when_embedding_dimension_changes(tmp_path) -> None:
    documents = [
        ChromaSourceDocument(
            reference="knowledge:appendicitis_001.rp_03",
            source_type="knowledge",
            title="急性阑尾炎诊断依据",
            snippet="白细胞升高提示炎症反应。",
        ),
        ChromaSourceDocument(
            reference="case:appendicitis_001",
            source_type="case",
            title="右下腹痛教学病例",
            snippet="转移性右下腹痛。",
        ),
    ]
    settings = ChromaRetrievalSettings(
        persist_directory=tmp_path / "chroma",
        collection_name="test_retrieval_documents",
    )
    first_index = ChromaRetrievalIndex(
        settings=settings,
        embedding_client=FakeEmbeddingClient(),
        documents=documents,
    )
    first_index.search("炎症实验室证据", limit=2)
    second_index = ChromaRetrievalIndex(
        settings=settings,
        embedding_client=ThreeDimensionalFakeEmbeddingClient(),
        documents=documents,
    )

    results = second_index.search("炎症实验室证据", limit=2)

    assert results
    assert results[0].reference == "knowledge:appendicitis_001.rp_03"
    assert results[0].score > 0.9


def test_chroma_retrieval_index_removes_stale_documents_when_source_set_changes(tmp_path) -> None:
    stale_document = ChromaSourceDocument(
        reference="rag_knowledge:case:appendicitis_001:removed",
        source_type="rag_knowledge",
        title="已停用知识",
        snippet="白细胞升高提示炎症反应。",
    )
    active_document = ChromaSourceDocument(
        reference="case:appendicitis_001",
        source_type="case",
        title="右下腹痛教学病例",
        snippet="转移性右下腹痛。",
    )
    settings = ChromaRetrievalSettings(
        persist_directory=tmp_path / "chroma",
        collection_name="test_retrieval_documents",
    )
    first_index = ChromaRetrievalIndex(
        settings=settings,
        embedding_client=FakeEmbeddingClient(),
        documents=[stale_document, active_document],
    )
    first_results = first_index.search("炎症实验室证据", limit=2)
    second_index = ChromaRetrievalIndex(
        settings=settings,
        embedding_client=FakeEmbeddingClient(),
        documents=[active_document],
    )

    second_results = second_index.search("炎症实验室证据", limit=1)

    assert first_results[0].reference == stale_document.reference
    assert all(result.reference != stale_document.reference for result in second_results)


def test_chroma_manifest_tracks_built_index_and_rebuild_need(tmp_path) -> None:
    documents = [
        ChromaSourceDocument(
            reference="knowledge:appendicitis_001.rp_03",
            source_type="knowledge",
            title="急性阑尾炎诊断依据",
            snippet="白细胞升高提示炎症反应。",
        ),
        ChromaSourceDocument(
            reference="rubric:appendicitis_001_rubric.item.ax_cbc",
            source_type="rubric",
            title="申请血常规",
            snippet="evidence_expected: lab.cbc",
        ),
    ]
    settings = ChromaRetrievalSettings(
        persist_directory=tmp_path / "chroma",
        collection_name="test_retrieval_documents",
        embedding_model="fake-embedding-model",
    )

    missing_status = build_chroma_manifest_status(settings=settings, documents=documents)

    assert missing_status["status"] == "missing"
    assert missing_status["rebuild_required"] is True
    assert missing_status["source_count"] == 2
    assert missing_status["case_ids"] == ["appendicitis_001"]

    index = ChromaRetrievalIndex(
        settings=settings,
        embedding_client=FakeEmbeddingClient(),
        documents=documents,
    )
    index.ensure_indexed()
    built_status = build_chroma_manifest_status(settings=settings, documents=documents)

    assert built_status["status"] == "built"
    assert built_status["rebuild_required"] is False
    assert built_status["collection"] == "test_retrieval_documents"
    assert built_status["embedding_model"] == "fake-embedding-model"
    assert built_status["index_config"] == {
        "hnsw:search_ef": DEFAULT_CHROMA_SEARCH_EF,
        "hnsw:space": "cosine",
    }
    assert built_status["stored_index_config"] == built_status["index_config"]
    assert built_status["source_count"] == 2
    assert built_status["stored_source_count"] == 2
    assert built_status["content_hash"].startswith("sha256:")
    assert built_status["stored_content_hash"] == built_status["content_hash"]
    assert built_status["manifest_path"].endswith("retrieval_index_manifest.json")

    expanded_documents = [
        *documents,
        ChromaSourceDocument(
            reference="case:acs_001",
            source_type="case",
            title="胸痛教学病例",
            snippet="胸痛危险信号。",
        ),
    ]
    stale_status = build_chroma_manifest_status(settings=settings, documents=expanded_documents)

    assert stale_status["status"] == "stale"
    assert stale_status["rebuild_required"] is True
    assert stale_status["source_count"] == 3
    assert stale_status["stored_source_count"] == 2
    assert stale_status["case_ids"] == ["acs_001", "appendicitis_001"]


def test_chroma_manifest_marks_legacy_and_changed_index_config_stale(tmp_path) -> None:
    documents = [
        ChromaSourceDocument(
            reference="case:appendicitis_001",
            source_type="case",
            title="右下腹痛教学病例",
            snippet="转移性右下腹痛。",
        )
    ]
    settings = ChromaRetrievalSettings(
        persist_directory=tmp_path / "chroma",
        collection_name="test_retrieval_documents",
        embedding_model="fake-embedding-model",
    )
    index = ChromaRetrievalIndex(
        settings=settings,
        embedding_client=FakeEmbeddingClient(),
        documents=documents,
    )
    index.ensure_indexed()

    changed_settings = ChromaRetrievalSettings(
        persist_directory=settings.persist_directory,
        collection_name=settings.collection_name,
        embedding_model=settings.embedding_model,
        search_ef=733,
    )
    changed_status = build_chroma_manifest_status(settings=changed_settings, documents=documents)

    assert changed_status["status"] == "stale"
    assert changed_status["rebuild_required"] is True
    assert changed_status["stored_index_config"]["hnsw:search_ef"] == DEFAULT_CHROMA_SEARCH_EF
    assert changed_status["index_config"]["hnsw:search_ef"] == 733

    rebuilding_client = CountingFakeEmbeddingClient()
    rebuilt_index = ChromaRetrievalIndex(
        settings=changed_settings,
        embedding_client=rebuilding_client,
        documents=documents,
    )
    rebuilt_index.ensure_indexed()

    assert ("RETRIEVAL_DOCUMENT", len(documents)) in rebuilding_client.calls
    assert rebuilt_index._collection.metadata["hnsw:search_ef"] == 733
    assert build_chroma_manifest_status(
        settings=changed_settings,
        documents=documents,
    )["status"] == "built"

    manifest_path = settings.persist_directory / "retrieval_index_manifest.json"
    legacy_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy_manifest["schema_version"] = "1.0"
    legacy_manifest.pop("index_config")
    manifest_path.write_text(
        json.dumps(legacy_manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    legacy_status = build_chroma_manifest_status(settings=settings, documents=documents)

    assert legacy_status["status"] == "stale"
    assert legacy_status["rebuild_required"] is True
    assert legacy_status["stored_schema_version"] == "1.0"
    assert legacy_status["stored_index_config"] == {}


def test_chroma_index_uses_same_search_metadata_after_reset(tmp_path) -> None:
    settings = ChromaRetrievalSettings(
        persist_directory=tmp_path / "chroma",
        collection_name="test_retrieval_documents",
        embedding_model="fake-embedding-model",
    )
    index = ChromaRetrievalIndex(
        settings=settings,
        embedding_client=FakeEmbeddingClient(),
        documents=[],
    )

    assert index._collection.metadata == {
        "hnsw:space": "cosine",
        "hnsw:search_ef": DEFAULT_CHROMA_SEARCH_EF,
    }
    assert index._collection.configuration["hnsw"]["ef_search"] == DEFAULT_CHROMA_SEARCH_EF

    index._reset_collection()

    assert index._collection.metadata == {
        "hnsw:space": "cosine",
        "hnsw:search_ef": DEFAULT_CHROMA_SEARCH_EF,
    }
    assert index._collection.configuration["hnsw"]["ef_search"] == DEFAULT_CHROMA_SEARCH_EF


def test_chroma_settings_read_positive_search_ef_and_fall_back_for_invalid_environment_values(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", "runtime/chroma")
    monkeypatch.setenv("OSCE_CHROMA_COLLECTION", "test_environment_settings")
    monkeypatch.setenv("OSCE_CHROMA_SEARCH_EF", "733")

    settings = build_chroma_retrieval_settings_from_environment(
        root_dir=tmp_path,
        embedding_model="fake-embedding-model",
    )

    assert settings.persist_directory == tmp_path / "runtime/chroma"
    assert settings.collection_name == "test_environment_settings"
    assert settings.embedding_model == "fake-embedding-model"
    assert settings.search_ef == 733

    for invalid_value in ["0", "-1", "not-an-integer"]:
        monkeypatch.setenv("OSCE_CHROMA_SEARCH_EF", invalid_value)
        invalid_settings = build_chroma_retrieval_settings_from_environment(
            root_dir=tmp_path,
            embedding_model="fake-embedding-model",
        )
        assert invalid_settings.search_ef == DEFAULT_CHROMA_SEARCH_EF


def test_chroma_manifest_status_marks_malformed_manifest_invalid(tmp_path) -> None:
    documents = [
        ChromaSourceDocument(
            reference="case:appendicitis_001",
            source_type="case",
            title="右下腹痛教学病例",
            snippet="转移性右下腹痛。",
        )
    ]
    settings = ChromaRetrievalSettings(
        persist_directory=tmp_path / "chroma",
        collection_name="test_retrieval_documents",
        embedding_model="fake-embedding-model",
    )
    settings.persist_directory.mkdir()
    (settings.persist_directory / "retrieval_index_manifest.json").write_text(
        '{"source_count":"not-a-number"}',
        encoding="utf-8",
    )

    status = build_chroma_manifest_status(settings=settings, documents=documents)

    assert status["status"] == "invalid"
    assert status["rebuild_required"] is True


def test_search_retrieval_documents_uses_chroma_when_enabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "true")
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", str(tmp_path / "chroma"))
    monkeypatch.setenv("OSCE_CHROMA_COLLECTION", _unique_chroma_collection(tmp_path))
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_PROJECT", "demo-project")
    monkeypatch.setattr(
        retrieval_index_module,
        "build_vertex_embedding_client_from_environment",
        lambda: FakeEmbeddingClient(),
    )

    def fail_in_memory_embedding_search(*args, **kwargs):
        raise AssertionError("in-memory embedding fallback should not run when ChromaDB is enabled")

    monkeypatch.setattr(
        retrieval_index_module,
        "search_retrieval_documents_with_embeddings_batch",
        fail_in_memory_embedding_search,
    )

    results = search_retrieval_documents("炎症实验室证据", limit=3)

    assert results
    assert results[0].reference == "knowledge:appendicitis_001.rp_03"
    assert results[0].source_type == "knowledge"
    assert results[0].score > 0.9
    assert results[0].retrieval_methods == ("vector", "lexical")


def test_search_retrieval_documents_uses_batch_fallback_once_when_chroma_fails(
    monkeypatch,
) -> None:
    embedding_client = FakeEmbeddingClient()
    fallback_calls: list[dict[str, object]] = []

    class FailingChromaIndex:
        def search_batch(self, queries: list[str], *, limit: int) -> list[list[object]]:
            raise RuntimeError(f"chroma unavailable for {queries!r} at limit {limit}")

    monkeypatch.setattr(
        retrieval_index_module,
        "build_vertex_embedding_client_from_environment",
        lambda: embedding_client,
    )
    monkeypatch.setattr(
        retrieval_index_module,
        "build_local_embedding_client_from_environment",
        lambda: None,
    )
    monkeypatch.setattr(
        retrieval_index_module,
        "build_chroma_retrieval_index_from_environment",
        lambda **_: FailingChromaIndex(),
    )

    def batch_fallback(
        queries: list[str],
        *,
        embedding_client: object,
        limit: int,
        reranker: object,
    ) -> list[list[retrieval_index_module.RetrievalDocument]]:
        fallback_calls.append(
            {
                "queries": queries,
                "embedding_client": embedding_client,
                "limit": limit,
                "reranker": reranker,
            }
        )
        return [
            [
                retrieval_index_module.RetrievalDocument(
                    reference="case:appendicitis_001",
                    source_type="case",
                    title="右下腹痛教学病例",
                    snippet="转移性右下腹痛。",
                    score=1.0,
                )
            ]
        ]

    monkeypatch.setattr(
        retrieval_index_module,
        "search_retrieval_documents_with_embeddings_batch",
        batch_fallback,
    )

    results = search_retrieval_documents("右下腹痛", limit=3)

    assert [result.reference for result in results] == ["case:appendicitis_001"]
    assert len(fallback_calls) == 1
    assert fallback_calls[0]["queries"] == ["右下腹痛"]
    assert fallback_calls[0]["embedding_client"] is embedding_client
    assert fallback_calls[0]["limit"] == 3


def test_search_retrieval_documents_filters_allowed_references_before_rerank(
    monkeypatch,
) -> None:
    embedding_client = FakeEmbeddingClient()
    captured_limits: list[int] = []
    allowed_reference = "rag_knowledge:case:appendicitis_001:coach:abdominal_pain_history_sequence"

    class GlobalChromaIndex:
        def search_batch(
            self,
            queries: list[str],
            *,
            limit: int,
        ) -> list[list[ChromaRetrievalResult]]:
            captured_limits.append(limit)
            global_hits = [
                ChromaRetrievalResult(
                    reference=f"rubric:appendicitis_001_rubric.item.noise_{index}",
                    source_type="rubric",
                    title=f"noise {index}",
                    snippet="global corpus noise",
                    score=1.0 - index * 0.01,
                )
                for index in range(30)
            ]
            global_hits.append(
                ChromaRetrievalResult(
                    reference=allowed_reference,
                    source_type="rag_knowledge",
                    title="腹痛问诊教学知识",
                    snippet="先追问起病和疼痛迁移。",
                    score=0.4,
                )
            )
            return [global_hits[:limit] for _ in queries]

    monkeypatch.setattr(
        retrieval_index_module,
        "build_vertex_embedding_client_from_environment",
        lambda: embedding_client,
    )
    monkeypatch.setattr(
        retrieval_index_module,
        "build_local_embedding_client_from_environment",
        lambda: None,
    )
    monkeypatch.setattr(
        retrieval_index_module,
        "build_chroma_retrieval_index_from_environment",
        lambda **_: GlobalChromaIndex(),
    )
    monkeypatch.setattr(retrieval_index_module, "_build_dashscope_reranker", lambda: None)

    results = search_retrieval_documents(
        "腹痛问诊",
        limit=3,
        allowed_references={allowed_reference},
    )

    assert captured_limits == [len(retrieval_index_module.get_chroma_source_documents())]
    assert [result.reference for result in results] == [allowed_reference]


def test_search_retrieval_documents_drops_stale_chroma_references(monkeypatch) -> None:
    class StaleChromaIndex:
        def search_batch(
            self,
            queries: list[str],
            *,
            limit: int,
        ) -> list[list[ChromaRetrievalResult]]:
            return [
                [
                    ChromaRetrievalResult(
                        reference="rag_knowledge:deleted:stale_chunk",
                        source_type="rag_knowledge",
                        title="已删除的旧片段",
                        snippet="这条旧索引内容不应继续被召回。",
                        score=0.99,
                    )
                ]
                for _ in queries
            ]

    monkeypatch.setattr(
        retrieval_index_module,
        "build_vertex_embedding_client_from_environment",
        lambda: ExactPhraseFakeEmbeddingClient("右下腹痛"),
    )
    monkeypatch.setattr(
        retrieval_index_module,
        "build_local_embedding_client_from_environment",
        lambda: None,
    )
    monkeypatch.setattr(
        retrieval_index_module,
        "build_chroma_retrieval_index_from_environment",
        lambda **_: StaleChromaIndex(),
    )
    monkeypatch.setattr(retrieval_index_module, "_build_dashscope_reranker", lambda: None)

    results = search_retrieval_documents("右下腹痛", limit=3)

    assert results
    assert all(result.reference != "rag_knowledge:deleted:stale_chunk" for result in results)
    assert results[0].reference == "case:appendicitis_001"


def test_vertex_embedding_client_uses_runtime_vertex_adc_without_embedding_env(monkeypatch) -> None:
    monkeypatch.delenv("OSCE_VERTEX_EMBEDDING_ENABLED", raising=False)
    monkeypatch.delenv("OSCE_VERTEX_EMBEDDING_PROJECT", raising=False)
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "vertex_gemini_adc",
            "api_key": "",
            "model": "gemini-2.5-flash",
            "base_url": "runtime-demo-project",
            "proxy_url": "direct",
            "location": "global",
        }
    )
    FakeGenAIEmbeddingClient.created_kwargs = []
    monkeypatch.setattr(vertex_embedding_retriever_module.genai, "Client", FakeGenAIEmbeddingClient)

    try:
        embedding_client = vertex_embedding_retriever_module.build_vertex_embedding_client_from_environment()
        vectors = embedding_client.embed_texts(["右下腹疼痛迁移"], task_type="RETRIEVAL_QUERY")
    finally:
        runtime_model_config_store.clear()

    assert embedding_client is not None
    client_kwargs = FakeGenAIEmbeddingClient.created_kwargs[0]
    assert {key: value for key, value in client_kwargs.items() if key != "http_options"} == {
        "vertexai": True,
        "project": "runtime-demo-project",
        "location": "global",
    }
    assert client_kwargs["http_options"].client_args == {
        "follow_redirects": False,
        "trust_env": False,
    }
    assert client_kwargs["http_options"].async_client_args["trust_env"] is False
    assert vectors == [[0.0, 0.2, 0.3]]


def test_vertex_embedding_client_batches_multiple_texts(monkeypatch) -> None:
    FakeGenAIEmbeddingClient.created_kwargs = []
    FakeGenAIEmbeddingClient.embed_content_calls = []
    monkeypatch.setattr(vertex_embedding_retriever_module.genai, "Client", FakeGenAIEmbeddingClient)
    client = vertex_embedding_retriever_module.VertexTextEmbeddingClient(
        vertex_embedding_retriever_module.VertexEmbeddingSettings(project="demo-project")
    )

    vectors = client.embed_texts(["第一段", "第二段", "第三段"], task_type="RETRIEVAL_DOCUMENT")

    assert len(FakeGenAIEmbeddingClient.embed_content_calls) == 1
    assert FakeGenAIEmbeddingClient.embed_content_calls[0]["contents"] == ["第一段", "第二段", "第三段"]
    assert vectors == [[0.0, 0.2, 0.3], [1.0, 0.2, 0.3], [2.0, 0.2, 0.3]]


def test_search_retrieval_documents_uses_chroma_by_default_when_embedding_client_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OSCE_CHROMA_ENABLED", raising=False)
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", str(tmp_path / "chroma"))
    monkeypatch.setenv("OSCE_CHROMA_COLLECTION", _unique_chroma_collection(tmp_path))
    monkeypatch.setattr(
        retrieval_index_module,
        "build_vertex_embedding_client_from_environment",
        lambda: FakeEmbeddingClient(),
    )

    def fail_in_memory_embedding_search(*args, **kwargs):
        raise AssertionError("in-memory embedding fallback should not run when ChromaDB can be used")

    monkeypatch.setattr(
        retrieval_index_module,
        "search_retrieval_documents_with_embeddings_batch",
        fail_in_memory_embedding_search,
    )

    results = search_retrieval_documents("炎症实验室证据", limit=3)

    assert results
    assert results[0].reference == "knowledge:appendicitis_001.rp_03"
    assert (tmp_path / "chroma").exists()


def test_search_retrieval_documents_batch_uses_chroma_once_for_multiple_queries(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OSCE_CHROMA_ENABLED", raising=False)
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", str(tmp_path / "chroma"))
    monkeypatch.setenv("OSCE_CHROMA_COLLECTION", _unique_chroma_collection(tmp_path))
    counting_client = CountingFakeEmbeddingClient()
    monkeypatch.setattr(
        retrieval_index_module,
        "build_vertex_embedding_client_from_environment",
        lambda: counting_client,
    )

    results_by_query = search_retrieval_documents_batch(["炎症实验室证据", "右下腹痛病例"], limit=3)

    assert len(results_by_query) == 2
    assert results_by_query[0]
    assert results_by_query[0][0].reference == "knowledge:appendicitis_001.rp_03"
    assert ("RETRIEVAL_QUERY", 2) in counting_client.calls


def test_lexical_retrieval_only_skips_optional_model_providers(monkeypatch) -> None:
    def fail_model_provider_build() -> None:
        raise AssertionError("optional model provider must not be initialized")

    monkeypatch.setattr(
        retrieval_index_module,
        "_build_dashscope_reranker",
        fail_model_provider_build,
    )
    monkeypatch.setattr(
        retrieval_index_module,
        "_build_embedding_clients_from_environment",
        fail_model_provider_build,
    )

    with retrieval_index_module.lexical_retrieval_only():
        results = search_retrieval_documents("炎症实验室证据", limit=3)

    assert results
    assert all(result.retrieval_methods == ("lexical",) for result in results)
