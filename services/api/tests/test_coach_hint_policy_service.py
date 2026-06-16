from app.services.coach_hint_policy_service import HintIntent, resolve_coach_hint_policy


def _goal(gap_type: str, *, trigger_stage: str, action: str) -> dict[str, object]:
    return {
        "gap_type": gap_type,
        "label": gap_type,
        "trigger_stage": trigger_stage,
        "next_training_action": action,
        "status": "persistent",
        "priority": 10,
    }


def test_policy_keeps_empty_session_onboarding_before_untriggered_humanistic_goal() -> None:
    decision = resolve_coach_hint_policy(
        state={
            "stage": "case_intro",
            "messages": [],
            "asked_questions": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
        },
        default_hint="你还没有开始问诊。第一步先用开放式问题建立病史主线。",
        training_goals=[
            _goal(
                "relationship_empathy_missing",
                trigger_stage="history_taking",
                action="下一轮患者表达担忧后，先回应情绪再继续医学问诊。",
            )
        ],
    )

    assert decision.intent == HintIntent.CASE_ONBOARDING
    assert decision.hint == "你还没有开始问诊。第一步先用开放式问题建立病史主线。"
    assert decision.training_goal_hint == ""
    assert decision.trigger_state == "none"
    assert decision.suppressed_goal_types == ["relationship_empathy_missing"]


def test_policy_selects_empathy_goal_only_after_patient_emotion_signal() -> None:
    decision = resolve_coach_hint_policy(
        state={
            "stage": "history_taking",
            "messages": [
                {"role": "student", "content": "以前有什么病吗？"},
                {"role": "patient", "content": "我有点害怕是不是要开刀。"},
            ],
            "asked_questions": ["以前有什么病吗？"],
            "revealed_facts": ["appendicitis_001.hf_06"],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
        },
        default_hint="先继续补齐腹痛相关病史。",
        training_goals=[
            _goal(
                "relationship_empathy_missing",
                trigger_stage="history_taking",
                action="下一轮患者表达担忧后，先回应情绪再继续医学问诊。",
            )
        ],
    )

    assert decision.intent == HintIntent.RELATIONSHIP_REPAIR
    assert decision.trigger_state == "triggered"
    assert decision.training_goal_hint == "本轮患者表达担忧后，先回应情绪再继续医学问诊。"


def test_policy_prepares_relationship_goal_before_patient_emotion_signal() -> None:
    decision = resolve_coach_hint_policy(
        state={
            "stage": "history_taking",
            "messages": [
                {"role": "student", "content": "以前有什么病吗？"},
                {"role": "patient", "content": "以前身体还可以。"},
            ],
            "asked_questions": ["以前有什么病吗？"],
            "revealed_facts": ["appendicitis_001.hf_06"],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
        },
        default_hint="先继续补齐腹痛相关病史。",
        training_goals=[
            _goal(
                "relationship_empathy_missing",
                trigger_stage="history_taking",
                action="下一轮患者表达担忧后，先回应情绪再继续医学问诊。",
            )
        ],
    )

    assert decision.intent == HintIntent.OPPORTUNITY_PREPARATION
    assert decision.selected_goal_type == "relationship_empathy_missing"
    assert decision.trigger_state == "preparation"
    assert "主动询问患者最担心什么" in decision.training_goal_hint


def test_policy_does_not_prepare_relationship_goal_after_only_social_opening() -> None:
    decision = resolve_coach_hint_policy(
        state={
            "stage": "case_intro",
            "messages": [
                {"role": "student", "content": "您好。"},
                {"role": "patient", "content": "您好医生。"},
            ],
            "asked_questions": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
        },
        default_hint="先用开放式问题建立病史主线。",
        training_goals=[
            _goal(
                "relationship_empathy_missing",
                trigger_stage="history_taking",
                action="下一轮患者表达担忧后，先回应情绪再继续医学问诊。",
            )
        ],
    )

    assert decision.intent == HintIntent.HISTORY_PROGRESSION
    assert decision.trigger_state == "none"
    assert decision.training_goal_hint == ""
    assert decision.suppressed_goal_types == ["relationship_empathy_missing"]


def test_policy_does_not_repeat_relationship_preparation_after_emotion_was_answered() -> None:
    decision = resolve_coach_hint_policy(
        state={
            "stage": "history_taking",
            "messages": [
                {"role": "student", "content": "您现在最担心什么？"},
                {"role": "patient", "content": "我有点害怕是不是要开刀。"},
                {"role": "student", "content": "我理解你的担心，我们先把情况问清楚再判断。"},
            ],
            "asked_questions": ["您现在最担心什么？"],
            "revealed_facts": ["appendicitis_001.hf_08"],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
        },
        default_hint="先继续补齐腹痛相关病史。",
        training_goals=[
            _goal(
                "relationship_empathy_missing",
                trigger_stage="history_taking",
                action="下一轮患者表达担忧后，先回应情绪再继续医学问诊。",
            )
        ],
    )

    assert decision.intent == HintIntent.HISTORY_PROGRESSION
    assert decision.trigger_state == "none"
    assert decision.training_goal_hint == ""
    assert decision.suppressed_goal_types == ["relationship_empathy_missing"]


def test_policy_selects_ethics_goal_in_procedure_stage() -> None:
    decision = resolve_coach_hint_policy(
        state={
            "stage": "physical_exam",
            "messages": [{"role": "student", "content": "我想查一下腹部。"}],
            "asked_questions": ["什么时候开始疼的？"],
            "revealed_facts": ["appendicitis_001.hf_01"],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
        },
        default_hint="已有病史线索，下一步选择关键查体来验证。",
        training_goals=[
            _goal(
                "ethics_consent_missing",
                trigger_stage="physical_exam",
                action="下一轮查体或检查前先说明目的、可能不适并征得同意。",
            )
        ],
    )

    assert decision.intent == HintIntent.ETHICS_CONSENT_BEFORE_ACTION
    assert decision.trigger_state == "triggered"
    assert decision.training_goal_hint == "本轮查体或检查前先说明目的、可能不适并征得同意。"


def test_policy_prepares_ethics_goal_before_procedure_stage_after_history_evidence() -> None:
    decision = resolve_coach_hint_policy(
        state={
            "stage": "history_taking",
            "messages": [{"role": "student", "content": "疼痛从哪里开始的？"}],
            "asked_questions": ["疼痛从哪里开始的？", "有没有恶心发热？"],
            "revealed_facts": ["appendicitis_001.hf_01", "appendicitis_001.hf_03"],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
        },
        default_hint="已有病史线索，下一步选择关键查体来验证。",
        training_goals=[
            _goal(
                "ethics_consent_missing",
                trigger_stage="physical_exam",
                action="下一轮查体或检查前先说明目的、可能不适并征得同意。",
            )
        ],
    )

    assert decision.intent == HintIntent.OPPORTUNITY_PREPARATION
    assert decision.selected_goal_type == "ethics_consent_missing"
    assert decision.trigger_state == "preparation"
    assert decision.training_goal_hint == "本轮准备进入查体或检查前，先说明目的、可能不适并征得同意。"


def test_policy_allows_opening_communication_goal_at_empty_onboarding() -> None:
    decision = resolve_coach_hint_policy(
        state={
            "stage": "case_intro",
            "messages": [],
            "asked_questions": [],
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
        },
        default_hint="你还没有开始问诊。第一步先用开放式问题建立病史主线。",
        training_goals=[
            _goal(
                "communication_open_question_missing",
                trigger_stage="history_taking",
                action="下一轮开场先用开放式问题让患者完整描述主诉。",
            )
        ],
    )

    assert decision.intent == HintIntent.CASE_ONBOARDING
    assert decision.trigger_state == "triggered"
    assert decision.training_goal_hint == "本轮开场先用开放式问题让患者完整描述主诉。"
