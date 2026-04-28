from app.services.retrieval_index import search_retrieval_documents


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
