from app.services.knowledge_recommender import recommend_knowledge_items


def test_recommend_knowledge_items_resolves_known_evidence_without_retrieval(monkeypatch) -> None:
    def fail_search_retrieval_documents(*args, **kwargs):
        raise AssertionError("known evidence ids should be resolved deterministically, not retrieved")

    monkeypatch.setattr(
        "app.services.knowledge_recommender.search_retrieval_documents",
        fail_search_retrieval_documents,
    )

    report = {
        "case_id": "appendicitis_001",
        "rubric_scores": {
            "reasoning_core": {
                "description": "推理链覆盖关键证据并能自圆其说",
                "dimension_id": "reasoning",
                "score": 0,
                "max_score": 15,
                "missing_evidence": ["appendicitis_001.rp_03"],
            }
        },
        "missed_items": ["reasoning_core"],
    }

    recommendations = recommend_knowledge_items(report)

    assert {
        "reference": "knowledge:appendicitis_001.rp_03",
        "title": "急性阑尾炎诊断依据",
        "reason": "关联本轮缺失证据：白细胞升高伴 CRP 升高支持炎症性腹痛。",
    } in recommendations


def test_recommend_knowledge_items_uses_retrieval_for_similar_case_recommendations(monkeypatch) -> None:
    class RetrievedCase:
        reference = "case:pneumonia_001"
        source_type = "case"
        title = "发热咳嗽伴胸痛教学病例"
        snippet = "发热、咳嗽、胸痛；用于对照急症问诊结构"
        score = 0.92

    def fake_search_retrieval_documents(query: str, limit: int = 5):
        assert "右下腹痛" in query
        assert "腹痛" in query
        assert limit == 8
        return [RetrievedCase()]

    monkeypatch.setattr(
        "app.services.knowledge_recommender.search_retrieval_documents",
        fake_search_retrieval_documents,
    )

    report = {
        "case_id": "appendicitis_001",
        "rubric_scores": {},
        "missed_items": [],
    }

    recommendations = recommend_knowledge_items(report)

    assert {
        "reference": "case:pneumonia_001",
        "title": "发热咳嗽伴胸痛教学病例",
        "reason": "与当前病例在主诉、标签或训练目标上相近，可用于下一轮对照训练。",
    } in recommendations


def test_recommend_knowledge_items_uses_missed_rubric_items() -> None:
    report = {
        "case_id": "appendicitis_001",
        "rubric_scores": {
            "ht_location": {
                "description": "追问疼痛部位与转移",
                "dimension_id": "history_taking",
                "score": 0,
                "max_score": 10,
            }
        },
        "missed_items": ["ht_location"],
    }

    recommendations = recommend_knowledge_items(report)

    assert recommendations[0] == {
        "reference": "rubric:appendicitis_001_rubric.item.ht_location",
        "title": "追问疼痛部位与转移",
        "reason": "本轮评分未找到足够证据，建议复习该问诊要点。",
    }


def test_recommend_knowledge_items_adds_retrieved_knowledge_for_reasoning_gap() -> None:
    report = {
        "case_id": "appendicitis_001",
        "rubric_scores": {
            "reasoning_core": {
                "description": "推理链覆盖关键证据并能自圆其说",
                "dimension_id": "reasoning",
                "score": 0,
                "max_score": 15,
                "missing_evidence": ["appendicitis_001.rp_03"],
            }
        },
        "missed_items": ["reasoning_core"],
    }

    recommendations = recommend_knowledge_items(report)

    assert {
        "reference": "knowledge:appendicitis_001.rp_03",
        "title": "急性阑尾炎诊断依据",
        "reason": "关联本轮缺失证据：白细胞升高伴 CRP 升高支持炎症性腹痛。",
    } in recommendations


def test_recommend_knowledge_items_adds_similar_cases_without_current_case() -> None:
    report = {
        "case_id": "appendicitis_001",
        "rubric_scores": {},
        "missed_items": [],
    }

    recommendations = recommend_knowledge_items(report)
    similar_case_recommendations = [
        recommendation
        for recommendation in recommendations
        if recommendation["reference"].startswith("case:")
    ]

    assert similar_case_recommendations
    assert all(recommendation["reference"] != "case:appendicitis_001" for recommendation in similar_case_recommendations)
    assert similar_case_recommendations[0]["reason"] == "病例库暂无同模块病例，推荐用于下一轮对照训练。"
