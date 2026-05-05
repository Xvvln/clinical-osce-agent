from app.services.training_event_store import TrainingEventStore
from app.services.training_insight_service import TrainingInsightService


def test_training_insight_service_summarizes_frequent_missed_items_from_report_events(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    store = TrainingEventStore(database_path)
    store.append_event(
        session_id="session_one",
        case_id="appendicitis_001",
        student_id="student_demo",
        event_type="report_generated",
        payload={
            "report_id": "session_one_report",
            "total_score": 55,
            "missed_items": ["ht_location", "reasoning_core"],
            "knowledge_recommendations": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                    "title": "推理链覆盖关键证据并能自圆其说",
                    "reason": "本轮评分未找到足够证据，建议复习该临床推理要点。",
                },
                {
                    "reference": "knowledge:appendicitis_001.rp_03",
                    "title": "急性阑尾炎诊断依据",
                    "reason": "关联本轮缺失证据：白细胞升高支持急性炎症过程。",
                },
                {
                    "reference": "case:acs_001",
                    "title": "胸痛伴出汗教学病例",
                    "reason": "病例库暂无同模块病例，推荐用于下一轮对照训练。",
                },
            ],
            "source_reference_items": [
                {
                    "reference": "source:fareez_osce_2022",
                    "source_type": "source",
                    "title": "Fareez OSCE 数据集",
                    "metadata": {"license": "CC BY 4.0"},
                },
                {
                    "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                    "source_type": "rubric",
                    "title": "推理链覆盖关键证据并能自圆其说",
                    "metadata": {},
                },
            ],
        },
    )
    store.append_event(
        session_id="session_two",
        case_id="pneumonia_001",
        student_id="student_demo",
        event_type="history_message",
        payload={"message": "什么时候开始发热的？"},
    )
    store.append_event(
        session_id="session_two",
        case_id="pneumonia_001",
        student_id="student_demo",
        event_type="report_generated",
        payload={
            "report_id": "session_two_report",
            "total_score": 68,
            "missed_items": ["reasoning_core"],
            "knowledge_recommendations": [
                {
                    "reference": "rubric:pneumonia_001_rubric.item.reasoning_core",
                    "title": "推理链覆盖关键证据并能自圆其说",
                    "reason": "本轮评分未找到足够证据，建议复习该临床推理要点。",
                }
            ],
            "source_reference_items": [
                {
                    "reference": "source:fareez_osce_2022",
                    "source_type": "source",
                    "title": "Fareez OSCE 数据集",
                    "metadata": {"license": "CC BY 4.0"},
                }
            ],
        },
    )

    insights = TrainingInsightService(store).summarize_sessions(["session_one", "session_two"])

    assert insights == {
        "session_count": 2,
        "report_count": 2,
        "frequent_missed_items": [
            {
                "item_id": "reasoning_core",
                "count": 2,
                "case_ids": ["appendicitis_001", "pneumonia_001"],
            },
            {
                "item_id": "ht_location",
                "count": 1,
                "case_ids": ["appendicitis_001"],
            },
        ],
        "frequent_learning_recommendations": [
            {
                "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                "title": "推理链覆盖关键证据并能自圆其说",
                "count": 1,
            },
            {
                "reference": "rubric:pneumonia_001_rubric.item.reasoning_core",
                "title": "推理链覆盖关键证据并能自圆其说",
                "count": 1,
            },
            {
                "reference": "knowledge:appendicitis_001.rp_03",
                "title": "急性阑尾炎诊断依据",
                "count": 1,
            },
        ],
        "frequent_source_references": [
            {
                "reference": "source:fareez_osce_2022",
                "source_type": "source",
                "title": "Fareez OSCE 数据集",
                "count": 2,
                "case_ids": ["appendicitis_001", "pneumonia_001"],
                "metadata": {"license": "CC BY 4.0"},
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                "source_type": "rubric",
                "title": "推理链覆盖关键证据并能自圆其说",
                "count": 1,
                "case_ids": ["appendicitis_001"],
                "metadata": {},
            },
        ],
    }
