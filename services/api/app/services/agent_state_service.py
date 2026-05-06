from __future__ import annotations

from typing import Any


def build_pedagogy_state(state: dict[str, Any]) -> dict[str, Any]:
    stage = str(state.get("stage") or "case_intro")
    missed_items = _string_list(state.get("missed_items", []))
    skill_context_ids = _skill_context_ids(state.get("evolution_candidates", []))
    active_goal, next_best_action, evidence_gap, differential_gap = _phase_plan(state)
    return {
        "training_phase": stage,
        "active_learning_goal": active_goal,
        "missing_rubric_items": missed_items,
        "evidence_gap": evidence_gap,
        "differential_gap": differential_gap,
        "next_best_action": next_best_action,
        "skill_context_ids": skill_context_ids,
        "coaching_mode": _coaching_mode(state),
        "safety_mode": "teaching_only",
        "reflection_summary_id": _reflection_summary_id(state),
    }


def append_decision_trace(
    existing_trace: list[dict[str, Any]] | None,
    node: str,
    pedagogy_state: dict[str, Any],
) -> list[dict[str, Any]]:
    trace = list(existing_trace or [])
    trace.append(
        {
            "trace_id": f"decision:{len(trace) + 1}",
            "node": node,
            "stage": pedagogy_state["training_phase"],
            "decision": pedagogy_state["active_learning_goal"],
            "next_best_action": pedagogy_state["next_best_action"],
            "skill_context_ids": list(pedagogy_state.get("skill_context_ids", [])),
            "coaching_mode": pedagogy_state["coaching_mode"],
            "safety_mode": pedagogy_state["safety_mode"],
        }
    )
    return trace


def build_reflection_summary(state: dict[str, Any]) -> dict[str, Any]:
    missed_items = _string_list(state.get("missed_items", []))
    reflection_summary_id = f"reflection:{state.get('case_id', 'unknown')}:{len(missed_items)}"
    if missed_items:
        summary = f"本轮有 {len(missed_items)} 个待复盘训练点，优先回看证据收集顺序和推理表达。"
        next_focus = "下一轮先围绕漏项最多的维度补齐问诊、查体或辅助检查证据。"
    else:
        summary = "本轮证据链基本完整，下一轮可继续练习结构化表达和鉴别思路。"
        next_focus = "保持先收集证据、再组织假设、最后提交结论的训练节奏。"
    return {
        "reflection_summary_id": reflection_summary_id,
        "missed_item_count": len(missed_items),
        "missed_item_ids": missed_items,
        "summary": summary,
        "next_focus": next_focus,
        "safety_note": "反思摘要仅用于 OSCE 教学训练，不改变病例标准答案、rubric 或评分规则。",
    }


def _phase_plan(state: dict[str, Any]) -> tuple[str, str, str, str]:
    if state.get("final_submission") is not None:
        return (
            "复盘推理边界",
            "查看报告并复盘漏项、鉴别诊断和下一轮训练重点。",
            "已提交结论，重点转入证据链复盘。",
            "对照已收集证据说明支持和不支持的依据。",
        )
    if not _string_list(state.get("revealed_facts", [])):
        return (
            "补齐核心病史",
            "先追问起病、部位变化、性质、程度和伴随症状。",
            "尚未形成足够病史证据。",
            "暂不进入诊断判断，先扩大关键病史信息。",
        )
    if not _string_list(state.get("requested_exams", [])):
        return (
            "选择关键查体",
            "根据已收集病史选择生命体征和重点查体。",
            "已有部分病史，但缺少体征证据。",
            "用查体结果检验当前线索是否一致。",
        )
    if not _string_list(state.get("requested_tests", [])):
        return (
            "选择辅助检查",
            "申请能验证当前假设并排除高风险鉴别的基础检查。",
            "已有病史和查体，仍缺少检查证据。",
            "用检查结果补强或修正当前假设。",
        )
    if not _string_list(state.get("student_hypotheses", [])):
        return (
            "组织诊断推理",
            "把病史、查体和检查证据串成支持与排除依据。",
            "已收集多类证据，下一步需要结构化表达。",
            "比较支持证据与待排除线索，再形成假设。",
        )
    return (
        "提交前查漏补缺",
        "继续补齐未覆盖的关键证据，再提交最终诊断与推理依据。",
        "已形成假设，仍需确认关键证据是否完整。",
        "提交前明确哪些证据支持、哪些证据仍需排除。",
    )


def _coaching_mode(state: dict[str, Any]) -> str:
    if state.get("final_submission") is not None or state.get("stage") == "feedback":
        return "reflective"
    if _string_list(state.get("evolution_candidates", [])):
        return "skill_guided"
    return "socratic"


def _skill_context_ids(evolution_candidates: Any) -> list[str]:
    skills = _string_list(evolution_candidates)
    return [f"enabled_skill:{index + 1}" for index, _skill in enumerate(skills)]


def _reflection_summary_id(state: dict[str, Any]) -> str | None:
    reflection_summary = state.get("reflection_summary")
    if isinstance(reflection_summary, dict):
        summary_id = reflection_summary.get("reflection_summary_id")
        if isinstance(summary_id, str) and summary_id:
            return summary_id
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]
