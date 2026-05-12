import json

from app.graph.osce_graph import reflection_node, training_strategy_node


def test_agent_strategy_node_updates_next_best_action() -> None:
    result = training_strategy_node(
        {
            "case_id": "appendicitis_001",
            "stage": "case_intro",
            "revealed_facts": [],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "evolution_candidates": [],
            "agent_decision_trace": [],
        }
    )

    pedagogy_state = result["pedagogy_state"]
    assert pedagogy_state["training_phase"] == "case_intro"
    assert pedagogy_state["active_learning_goal"] == "补齐核心病史"
    assert pedagogy_state["next_best_action"] == "先追问起病、部位变化、性质、程度和伴随症状。"
    assert pedagogy_state["coaching_mode"] == "socratic"
    assert pedagogy_state["safety_mode"] == "teaching_only"
    assert result["agent_decision_trace"][0]["node"] == "training_strategy_node"
    assert result["agent_decision_trace"][0]["decision"] == "补齐核心病史"


def test_agent_strategy_node_builds_teaching_plan_checkpoint_and_lifecycle_trace() -> None:
    result = training_strategy_node(
        {
            "case_id": "appendicitis_001",
            "session_id": "session-demo",
            "stage": "history_taking",
            "revealed_facts": ["appendicitis_001.hf_01"],
            "requested_exams": [],
            "requested_tests": [],
            "student_hypotheses": [],
            "final_submission": None,
            "missed_items": ["ht_migration", "ax_ua"],
            "evolution_candidates": ["腹痛问诊束：提交诊断前，请补齐腹痛关键病史。"],
            "agent_decision_trace": [],
        }
    )

    pedagogy_state = result["pedagogy_state"]
    teaching_plan = pedagogy_state["teaching_plan"]
    assert teaching_plan["plan_id"] == "teaching_plan:session-demo:history_taking"
    assert teaching_plan["case_id"] == "appendicitis_001"
    assert teaching_plan["stage"] == "history_taking"
    assert teaching_plan["selected_strategy"] == "hint_ladder_level_1"
    assert teaching_plan["observed_gap_ids"] == ["ht_migration", "ax_ua"]
    assert teaching_plan["source_references"] == [
        "rubric:appendicitis_001_rubric.item.ht_migration",
        "rubric:appendicitis_001_rubric.item.ax_ua",
    ]
    assert "reveal_main_diagnosis" in teaching_plan["blocked_actions"]
    assert "reveal_hidden_fact_without_question" in teaching_plan["blocked_actions"]

    checkpoint = pedagogy_state["stage_checkpoint"]
    assert checkpoint["checkpoint_id"] == "stage_checkpoint:session-demo:history_taking"
    assert checkpoint["stage"] == "history_taking"
    assert checkpoint["status"] == "needs_physical_exam"
    assert "history:appendicitis_001.hf_01" in checkpoint["covered_signal_ids"]
    assert "physical_exam:*" in checkpoint["pending_signal_ids"]

    hint_ladder = pedagogy_state["hint_ladder"]
    assert [hint["level"] for hint in hint_ladder] == [1, 2, 3]
    assert all(hint["disclosure_policy"] == "category_only_no_answer" for hint in hint_ladder)

    trace = result["agent_decision_trace"][0]
    assert trace["observe"]["stage"] == "history_taking"
    assert trace["observe"]["observed_gap_ids"] == ["ht_migration", "ax_ua"]
    assert trace["decide"]["selected_strategy"] == "hint_ladder_level_1"
    assert trace["act"]["next_best_action"] == pedagogy_state["next_best_action"]
    assert trace["reflect"]["safety_mode"] == "teaching_only"

    agent_text = json.dumps(result, ensure_ascii=False)
    assert "急性阑尾炎" not in agent_text
    assert "阑尾炎" not in agent_text


def test_agent_strategy_node_tracks_auxiliary_test_before_physical_exam_as_reasoning_gap() -> None:
    result = training_strategy_node(
        {
            "case_id": "appendicitis_001",
            "session_id": "session-skip-exam",
            "stage": "auxiliary_test",
            "revealed_facts": ["appendicitis_001.hf_01"],
            "requested_exams": [],
            "requested_tests": ["lab.cbc"],
            "student_hypotheses": [],
            "final_submission": None,
            "missed_items": [],
            "evolution_candidates": [],
            "training_progress": {
                "history": {
                    "covered": 1,
                    "pending_fact_ids": ["hf_02", "hf_03"],
                },
                "physical_exam": {
                    "requested": 0,
                    "pending_codes": ["vitals.temperature", "abd.palpation.rebound"],
                    "must_pending_codes": ["vitals.temperature", "abd.palpation.rebound"],
                },
                "auxiliary_test": {
                    "requested": 1,
                    "pending_codes": ["lab.crp"],
                    "must_pending_codes": ["lab.crp"],
                },
                "reasoning": {
                    "pending_evidence": ["abd.palpation.rebound"],
                    "ready_for_hypothesis": False,
                },
            },
            "agent_decision_trace": [],
        }
    )

    clinical_state = result["pedagogy_state"]["clinical_reasoning_state"]
    assert clinical_state["last_action_stage"] == "auxiliary_test"
    assert clinical_state["pedagogical_phase"] == "needs_physical_exam"
    assert "auxiliary_test_before_physical_exam" in clinical_state["sequence_flags"]
    assert clinical_state["readiness"] == {
        "history": "partial",
        "physical_exam": "missing",
        "auxiliary_test": "started",
        "reasoning": "missing",
    }
    assert clinical_state["safe_pending_points"]["physical_exam"]["must_pending_codes"] == [
        "vitals.temperature",
        "abd.palpation.rebound",
    ]
    assert clinical_state["next_best_action"]["action_type"] == "request_physical_exam"
    assert "体征证据" in clinical_state["next_best_action"]["why"]
    assert "辅助检查" in clinical_state["next_best_action"]["why"]
    assert "查体" in clinical_state["socratic_question"]
    assert result["agent_decision_trace"][0]["observe"]["sequence_flags"] == [
        "auxiliary_test_before_physical_exam",
        "auxiliary_test_without_hypothesis",
    ]
    assert result["agent_decision_trace"][0]["act"]["next_best_action"] == clinical_state["next_best_action"]["message"]


def test_reflection_node_does_not_leak_diagnosis() -> None:
    result = reflection_node(
        {
            "case_id": "appendicitis_001",
            "stage": "feedback",
            "missed_items": ["ht_migration", "pe_rebound"],
            "final_submission": {
                "diagnosis": "急性阑尾炎",
                "reasoning": "考虑急性阑尾炎。",
            },
            "agent_decision_trace": [],
        }
    )

    reflection_text = json.dumps(
        {
            "summary": result["reflection_summary"]["summary"],
            "next_focus": result["reflection_summary"]["next_focus"],
            "safety_note": result["reflection_summary"]["safety_note"],
        },
        ensure_ascii=False,
    )
    assert result["reflection_summary"]["reflection_summary_id"] == "reflection:appendicitis_001:2"
    assert "急性阑尾炎" not in reflection_text
    assert "阑尾炎" not in reflection_text
    assert result["agent_decision_trace"][0]["node"] == "reflection_node"
    assert result["reflection_summary"]["reflection_prompts"] == [
        {
            "prompt_id": "reflection_prompt:appendicitis_001:missed_items",
            "question": "本轮哪些证据收集步骤最容易被你跳过？请按问诊、查体、辅助检查和推理表达分组复盘。",
            "related_item_ids": ["ht_migration", "pe_rebound"],
        },
        {
            "prompt_id": "reflection_prompt:appendicitis_001:evidence_chain",
            "question": "下次训练前，你会先补齐哪些证据类别，再组织诊断假设？",
            "related_item_ids": ["ht_migration", "pe_rebound"],
        },
    ]
