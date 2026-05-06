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
