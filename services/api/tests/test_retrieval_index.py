from app.services import retrieval_index as retrieval_index_module
from app.services.chroma_retriever import ChromaRetrievalIndex, ChromaRetrievalSettings, ChromaSourceDocument
from app.services.retrieval_index import search_retrieval_documents, search_retrieval_documents_with_embeddings


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


def test_search_retrieval_documents_returns_case_for_clinical_query() -> None:
    results = search_retrieval_documents("右下腹痛", limit=3)

    assert results
    assert results[0].reference == "case:appendicitis_001"
    assert results[0].source_type == "case"
    assert results[0].title == "右下腹痛教学病例"
    assert "转移性右下腹痛" in results[0].snippet
    assert results[0].score > 0


def test_search_retrieval_documents_returns_rubric_item_for_exam_query() -> None:
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


def test_search_retrieval_documents_returns_knowledge_item_for_reasoning_query() -> None:
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


def test_search_retrieval_documents_with_embeddings_can_recall_semantic_source_without_keyword_overlap() -> None:
    results = search_retrieval_documents_with_embeddings(
        "炎症实验室证据",
        embedding_client=FakeEmbeddingClient(),
        limit=3,
    )

    assert results
    assert results[0].reference == "knowledge:appendicitis_001.rp_03"
    assert results[0].source_type == "knowledge"
    assert results[0].score > 0.99


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


def test_search_retrieval_documents_uses_chroma_when_enabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "true")
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", str(tmp_path / "chroma"))
    monkeypatch.setenv("OSCE_CHROMA_COLLECTION", "test_retrieval_documents")
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
        "search_retrieval_documents_with_embeddings",
        fail_in_memory_embedding_search,
    )

    results = search_retrieval_documents("炎症实验室证据", limit=3)

    assert results
    assert results[0].reference == "knowledge:appendicitis_001.rp_03"
    assert results[0].source_type == "knowledge"
    assert results[0].score > 0.99
