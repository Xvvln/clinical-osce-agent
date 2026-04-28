from app.services.knowledge_recommender import recommend_knowledge_items


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
