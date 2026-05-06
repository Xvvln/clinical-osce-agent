from app.services.retrieval_index import search_retrieval_documents, search_retrieval_documents_with_embeddings


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
    class FakeEmbeddingClient:
        def embed_texts(self, texts: list[str], *, task_type: str) -> list[list[float]]:
            if task_type == "RETRIEVAL_QUERY":
                return [[1.0, 0.0] for _ in texts]
            if task_type == "RETRIEVAL_DOCUMENT":
                return [
                    [1.0, 0.0] if "白细胞升高" in text else [0.0, 1.0]
                    for text in texts
                ]
            raise AssertionError(f"unexpected task_type: {task_type}")

    results = search_retrieval_documents_with_embeddings(
        "炎症实验室证据",
        embedding_client=FakeEmbeddingClient(),
        limit=3,
    )

    assert results
    assert results[0].reference == "knowledge:appendicitis_001.rp_03"
    assert results[0].source_type == "knowledge"
    assert results[0].score > 0.99
