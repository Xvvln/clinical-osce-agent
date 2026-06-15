from app.services.training_event_store import TrainingEventStore
from app.services.training_insight_service import TrainingInsightService


EMPTY_HUMANISTIC_COMMUNICATION_INSIGHT = {
    "report_count": 0,
    "average_score": 0,
    "max_score": 30,
    "dimension_averages": [],
    "frequent_gaps": [],
    "frequent_missed_opportunities": [],
    "anchor_candidate_count": 0,
    "anchor_candidates_by_status": [],
    "trend": {
        "previous_average_score": 0,
        "recent_average_score": 0,
        "delta": 0,
    },
}


class BatchOnlyTrainingEventStore:
    def __init__(self, events_by_session: dict[str, list[dict[str, object]]]) -> None:
        self.events_by_session = events_by_session
        self.batch_calls: list[list[str]] = []

    def list_events_for_sessions(self, session_ids: list[str]) -> dict[str, list[dict[str, object]]]:
        self.batch_calls.append(session_ids)
        return {session_id: self.events_by_session.get(session_id, []) for session_id in session_ids}

    def list_session_events(self, session_id: str) -> list[dict[str, object]]:
        raise AssertionError(f"insight summary should batch-load events, got {session_id}")


def test_training_insight_service_batch_loads_events_for_large_admin_summaries() -> None:
    store = BatchOnlyTrainingEventStore(
        {
            "session_one": [
                {
                    "session_id": "session_one",
                    "case_id": "appendicitis_001",
                    "student_id": "student_demo",
                    "event_type": "report_generated",
                    "payload": {
                        "report_id": "session_one_report",
                        "total_score": 55,
                        "missed_items": ["ht_location"],
                        "knowledge_recommendations": [],
                        "source_reference_items": [],
                    },
                    "created_at": "2026-05-01T00:00:00+00:00",
                }
            ],
            "session_two": [],
        }
    )

    insights = TrainingInsightService(store).summarize_sessions(["session_one", "session_two"])

    assert store.batch_calls == [["session_one", "session_two"]]
    assert insights["session_count"] == 2
    assert insights["report_count"] == 1


def test_training_insight_service_summarizes_humanistic_communication_stats(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    store = TrainingEventStore(database_path)
    store.append_event(
        session_id="session_one",
        case_id="appendicitis_001",
        student_id="student_demo",
        event_type="report_generated",
        payload={
            "report_id": "session_one_report",
            "score_groups": {"humanistic_communication": {"score": 8, "max_score": 30}},
            "dimension_scores": {
                "narrative_medicine": 2,
                "communication_skill": 3,
                "medical_ethics": 1,
                "relationship_building": 2,
            },
            "training_gaps": [
                {
                    "dimension_id": "medical_ethics",
                    "gap_type": "ethics_consent_missing",
                    "label": "查体或检查前说明目的并征得同意",
                    "missing_score": 3,
                    "skill_type": "ethics_consent",
                }
            ],
            "missed_opportunities": [
                {
                    "gap_type": "relationship_empathy_missing",
                    "expected_response": "患者表达担忧后，应先回应情绪。",
                }
            ],
            "humanistic_anchor_candidates": [
                {"status": "candidate"},
                {"status": "reviewed"},
            ],
        },
    )
    store.append_event(
        session_id="session_two",
        case_id="appendicitis_001",
        student_id="student_demo",
        event_type="report_generated",
        payload={
            "report_id": "session_two_report",
            "score_groups": {"humanistic_communication": {"score": 14, "max_score": 30}},
            "dimension_scores": {
                "narrative_medicine": 5,
                "communication_skill": 4,
                "medical_ethics": 2,
                "relationship_building": 3,
            },
            "training_gaps": [
                {
                    "dimension_id": "medical_ethics",
                    "gap_type": "ethics_consent_missing",
                    "label": "查体或检查前说明目的并征得同意",
                    "missing_score": 2,
                    "skill_type": "ethics_consent",
                },
                {
                    "dimension_id": "relationship_building",
                    "gap_type": "relationship_empathy_missing",
                    "label": "患者表达担忧后缺少共情回应",
                    "missing_score": 2,
                    "skill_type": "relationship_repair",
                },
            ],
            "missed_opportunities": [],
            "humanistic_anchor_candidates": [
                {"status": "reviewed"},
            ],
        },
    )

    insights = TrainingInsightService(store).summarize_sessions(["session_one", "session_two"])

    assert insights["humanistic_communication"] == {
        "report_count": 2,
        "average_score": 11,
        "max_score": 30,
        "dimension_averages": [
            {"dimension_id": "narrative_medicine", "dimension_label": "叙事医学", "average_score": 3.5},
            {"dimension_id": "communication_skill", "dimension_label": "沟通技巧", "average_score": 3.5},
            {"dimension_id": "relationship_building", "dimension_label": "关系建立", "average_score": 2.5},
            {"dimension_id": "medical_ethics", "dimension_label": "医学伦理", "average_score": 1.5},
        ],
        "frequent_gaps": [
            {
                "gap_type": "ethics_consent_missing",
                "label": "查体或检查前说明目的并征得同意",
                "count": 2,
                "missing_score_total": 5,
                "skill_type": "ethics_consent",
            },
            {
                "gap_type": "relationship_empathy_missing",
                "label": "患者表达担忧后缺少共情回应",
                "count": 1,
                "missing_score_total": 2,
                "skill_type": "relationship_repair",
            },
        ],
        "frequent_missed_opportunities": [
            {
                "gap_type": "relationship_empathy_missing",
                "expected_response": "患者表达担忧后，应先回应情绪。",
                "count": 1,
            }
        ],
        "anchor_candidate_count": 3,
        "anchor_candidates_by_status": [
            {"status": "reviewed", "count": 2},
            {"status": "candidate", "count": 1},
        ],
        "trend": {
            "previous_average_score": 8,
            "recent_average_score": 14,
            "delta": 6,
        },
    }


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
                "item_label": "推理链覆盖感染症状、体征和影像证据",
                "count": 2,
                "case_ids": ["appendicitis_001", "pneumonia_001"],
                "case_titles": ["右下腹痛教学病例", "发热咳嗽伴胸痛教学病例"],
            },
            {
                "item_id": "ht_location",
                "item_label": "ht_location",
                "count": 1,
                "case_ids": ["appendicitis_001"],
                "case_titles": ["右下腹痛教学病例"],
            },
        ],
        "frequent_learning_recommendations": [
            {
                "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                "reference_label": "评分项：右下腹痛教学病例 / reasoning_core（当前 Rubric 未收录）",
                "title": "推理链覆盖关键证据并能自圆其说",
                "count": 1,
            },
            {
                "reference": "rubric:pneumonia_001_rubric.item.reasoning_core",
                "reference_label": "评分项：推理链覆盖感染症状、体征和影像证据",
                "title": "推理链覆盖关键证据并能自圆其说",
                "count": 1,
            },
            {
                "reference": "knowledge:appendicitis_001.rp_03",
                "reference_label": "知识条目：右下腹痛教学病例",
                "title": "急性阑尾炎诊断依据",
                "count": 1,
            },
        ],
        "frequent_source_references": [
            {
                "reference": "source:fareez_osce_2022",
                "source_type": "source",
                "title": "Fareez OSCE 数据集",
                "reference_label": "来源：A dataset of simulated patient-physician medical interviews with a focus on respiratory cases",
                "count": 2,
                "case_ids": ["appendicitis_001", "pneumonia_001"],
                "case_titles": ["右下腹痛教学病例", "发热咳嗽伴胸痛教学病例"],
                "metadata": {"license": "CC BY 4.0"},
            },
            {
                "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                "source_type": "rubric",
                "title": "推理链覆盖关键证据并能自圆其说",
                "reference_label": "评分项：右下腹痛教学病例 / reasoning_core（当前 Rubric 未收录）",
                "count": 1,
                "case_ids": ["appendicitis_001"],
                "case_titles": ["右下腹痛教学病例"],
                "metadata": {},
            },
        ],
        "frequent_turn_patterns": [],
        "humanistic_communication": EMPTY_HUMANISTIC_COMMUNICATION_INSIGHT,
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
            "pattern_type_label": "偏题/寒暄回到问诊目标",
            "title": "偏题或寒暄后需要回到问诊目标",
            "count": 2,
            "trigger_item_ids": [
                "turn_intent:unknown_history_intent",
                "turn_policy:patient_context_redirect",
            ],
            "trigger_item_labels": [
                "未命中明确病史意图",
                "引导回患者上下文",
            ],
            "case_ids": ["appendicitis_001"],
            "case_titles": ["右下腹痛教学病例"],
            "session_ids": ["session_one", "session_two"],
            "source_report_ids": ["session_one_report", "session_two_report"],
            "source_report_count": 2,
        }
    ]


def test_training_insight_service_summarizes_auxiliary_test_before_physical_exam_pattern(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    store = TrainingEventStore(database_path)
    for session_id in ["session_one", "session_two"]:
        store.append_event(
            session_id=session_id,
            case_id="appendicitis_001",
            student_id="student_demo",
            event_type="history_message",
            payload={
                "message": "什么时候开始疼的？",
                "reply": "24 小时前开始。",
                "agent_turn": {
                    "turn_id": "turn:1",
                    "student_message": "什么时候开始疼的？",
                    "reply": "24 小时前开始。",
                    "reply_role": "patient",
                    "current_intent": "ask_onset",
                    "turn_policy": "history_fact_disclosure",
                    "turn_analysis": {
                        "current_intent": "ask_onset",
                        "confidence": 0.93,
                        "is_off_topic": False,
                        "rationale": "学生开始采集病史。",
                    },
                    "agent_path": ["input_router_node", "patient_response_node"],
                    "revealed_fact_id": "appendicitis_001.hf_01",
                    "source_references": ["case:appendicitis_001.history.appendicitis_001.hf_01"],
                    "safety_flags": [],
                },
            },
        )
        store.append_event(
            session_id=session_id,
            case_id="appendicitis_001",
            student_id="student_demo",
            event_type="auxiliary_test_requested",
            payload={"test_code": "lab.cbc", "result": "白细胞升高"},
        )
        store.append_event(
            session_id=session_id,
            case_id="appendicitis_001",
            student_id="student_demo",
            event_type="report_generated",
            payload={
                "report_id": f"{session_id}_report",
                "total_score": 58,
                "missed_items": ["pe_rebound"],
                "knowledge_recommendations": [],
                "source_reference_items": [],
            },
        )

    insights = TrainingInsightService(store).summarize_sessions(["session_one", "session_two"])

    assert insights["frequent_turn_patterns"] == [
        {
            "pattern_id": "turn_pattern_auxiliary_test_before_physical_exam",
            "pattern_type": "auxiliary_test_before_physical_exam",
            "pattern_type_label": "跳过查体直接申请辅助检查",
            "title": "有病史线索后跳过查体直接申请辅助检查",
            "count": 2,
            "trigger_item_ids": [
                "event:auxiliary_test_requested",
                "sequence:before_physical_exam",
            ],
            "trigger_item_labels": [
                "申请辅助检查",
                "发生在查体前",
            ],
            "case_ids": ["appendicitis_001"],
            "case_titles": ["右下腹痛教学病例"],
            "session_ids": ["session_one", "session_two"],
            "source_report_ids": ["session_one_report", "session_two_report"],
            "source_report_count": 2,
        }
    ]
