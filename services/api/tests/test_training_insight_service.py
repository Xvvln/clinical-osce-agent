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
        "frequent_turn_patterns": [],
    }


def test_training_insight_service_summarizes_repeated_agent_turn_patterns_from_training_events(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    store = TrainingEventStore(database_path)
    for session_id in ["session_one", "session_two"]:
        store.append_event(
            session_id=session_id,
            case_id="appendicitis_001",
            student_id="student_demo",
            event_type="history_message",
            payload={
                "message": "你好，你是谁？",
                "reply": "我是这次因右下腹痛来就诊的患者。请继续围绕腹痛问诊。",
                "agent_turn": {
                    "turn_id": "turn:1",
                    "student_message": "你好，你是谁？",
                    "reply": "我是这次因右下腹痛来就诊的患者。请继续围绕腹痛问诊。",
                    "reply_role": "patient",
                    "current_intent": "unknown_history_intent",
                    "turn_policy": "patient_context_redirect",
                    "turn_analysis": {
                        "current_intent": "unknown_history_intent",
                        "confidence": 0.61,
                        "is_off_topic": True,
                        "rationale": "学生在病例问诊开端进行寒暄，未围绕腹痛症状采集病史。",
                    },
                    "agent_path": ["input_router_node", "patient_response_node"],
                    "revealed_fact_id": None,
                    "source_references": [],
                    "safety_flags": [],
                },
            },
        )
        store.append_event(
            session_id=session_id,
            case_id="appendicitis_001",
            student_id="student_demo",
            event_type="report_generated",
            payload={
                "report_id": f"{session_id}_report",
                "total_score": 60,
                "missed_items": ["ht_location"],
                "knowledge_recommendations": [
                    {
                        "reference": "rubric:appendicitis_001_rubric.item.ht_location",
                        "title": "明确疼痛部位和迁移",
                        "reason": "学生未稳定覆盖腹痛部位与转移。",
                    }
                ],
                "source_reference_items": [],
            },
        )

    insights = TrainingInsightService(store).summarize_sessions(["session_one", "session_two"])

    assert insights["frequent_turn_patterns"] == [
        {
            "pattern_id": "turn_pattern_off_topic_redirect",
            "pattern_type": "off_topic_redirect",
            "title": "偏题或寒暄后需要回到问诊目标",
            "count": 2,
            "trigger_item_ids": [
                "turn_intent:unknown_history_intent",
                "turn_policy:patient_context_redirect",
            ],
            "case_ids": ["appendicitis_001"],
            "session_ids": ["session_one", "session_two"],
            "source_report_ids": ["session_one_report", "session_two_report"],
            "source_report_count": 2,
        }
    ]
