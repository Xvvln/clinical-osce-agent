from __future__ import annotations

import re
from typing import Any, Mapping

from app.models.case import Case, DifferentialDiagnosis, NegativeFinding, ReasoningPoint
from app.services.clinical_reasoning_trace_service import (
    action_order_summary_from_report,
    evidence_chain_breakpoints_from_report,
    sequence_flags_from_report,
)

DEEP_REPORT_ANALYSIS_VERSION = "deep_report_analysis_v1"
DEEP_REPORT_ANALYSIS_PROMPT_VERSION = "deep_report_prompt_v1"

DEEP_REPORT_ANALYSIS_PROMPT_CONTRACT = """你是 OSCE 深度训练分析 Agent。

你不是评分器，也不是诊断裁判。classification、target_diagnosis、score、rubric_trace 均由后端结构化规则确定。
你只能把后端提供的证据包解释成学生能理解的教师讲评，不得新增病例事实、不得修改标准诊断、不得改分。

证据边界：
1. collected_evidence：本轮学生已经采集，可以评价学生是否使用了它。
2. missing_evidence：本轮学生没有采集，只能表述为下一轮需要补采的证据类型，不能泄露具体结果。
3. target_diagnosis_evidence：只用于解释为什么目标诊断更合理；若证据未采集，不能写成本轮已经看到。
4. distractor_clues：只能解释为什么容易误导，不能把患者猜测当成确诊依据。

输出必须围绕：学生为什么会这样想、哪些证据支持、哪些证据反对、还缺什么、目标诊断为什么更合理、下一轮怎么练。
"""

_PUNCTUATION_PATTERN = re.compile(r"[\s,，。；;：:、.!！?？()（）【】\\[\\]{}<>《》\"'“”‘’]")

_CLINICAL_DIMENSIONS: tuple[dict[str, Any], ...] = (
    {"dimension_id": "history_taking", "label": "病史采集", "max_score": 18, "fallback_action": "下一轮先补齐病史主线，再推进查体和检查。"},
    {"dimension_id": "physical_exam", "label": "查体", "max_score": 10, "fallback_action": "下一轮围绕当前诊断假设选择关键查体。"},
    {"dimension_id": "auxiliary_test", "label": "辅助检查", "max_score": 10, "fallback_action": "下一轮只申请能验证或排除假设的必要检查。"},
    {"dimension_id": "main_diagnosis", "label": "主诊断", "max_score": 10, "fallback_action": "下一轮提交前确认诊断名称和关键支持证据一致。"},
    {"dimension_id": "differential_diagnosis", "label": "鉴别诊断", "max_score": 10, "fallback_action": "下一轮至少列出一个相近诊断及排除依据。"},
    {"dimension_id": "reasoning", "label": "推理链", "max_score": 12, "fallback_action": "下一轮用支持证据、反证依据和仍需验证点组织诊断推理。"},
)

_CLINICAL_DIMENSION_BY_ID = {dimension["dimension_id"]: dimension for dimension in _CLINICAL_DIMENSIONS}

_HUMANISTIC_DIMENSIONS: tuple[dict[str, Any], ...] = (
    {"dimension_id": "narrative_medicine", "label": "叙事医学", "max_score": 8},
    {"dimension_id": "communication_skill", "label": "沟通技巧", "max_score": 10},
    {"dimension_id": "medical_ethics", "label": "医学伦理", "max_score": 7},
    {"dimension_id": "relationship_building", "label": "关系建立", "max_score": 5},
)

_HUMANISTIC_DIMENSION_IDS = {str(dimension["dimension_id"]) for dimension in _HUMANISTIC_DIMENSIONS}


def build_deep_report_analysis(*, report: Mapping[str, Any], case: Case) -> dict[str, Any]:
    return {
        "version": DEEP_REPORT_ANALYSIS_VERSION,
        "status": "generated",
        "overall_evaluation": build_overall_evaluation(report=report),
        "diagnostic_contrast_analysis": build_diagnostic_contrast_analysis(report=report, case=case),
        "clinical_task_analysis": build_clinical_task_analysis(report=report),
        "evidence_utilization_analysis": build_evidence_utilization_analysis(report=report, case=case),
        "process_strategy_analysis": build_process_strategy_analysis(report=report),
        "humanistic_communication_analysis": build_humanistic_communication_analysis(report=report),
        "next_training_plan": build_next_training_plan(report=report),
    }


def build_legacy_deep_report_analysis() -> dict[str, Any]:
    return {
        "version": DEEP_REPORT_ANALYSIS_VERSION,
        "status": "legacy_report",
        "overall_evaluation": _empty_overall_evaluation(),
        "diagnostic_contrast_analysis": _empty_diagnostic_contrast_analysis(),
        "clinical_task_analysis": _empty_clinical_task_analysis(),
        "evidence_utilization_analysis": _empty_evidence_utilization_analysis(),
        "process_strategy_analysis": _empty_process_strategy_analysis(),
        "humanistic_communication_analysis": _empty_humanistic_communication_analysis(),
        "next_training_plan": _empty_next_training_plan(),
    }


def build_overall_evaluation(*, report: Mapping[str, Any]) -> dict[str, Any]:
    total_score = _number(report.get("total_score"))
    max_score = _number(report.get("max_score"), fallback=100)
    score_groups = _mapping(report.get("score_groups"))
    clinical_group = _mapping(score_groups.get("clinical_osce"))
    humanistic_group = _mapping(score_groups.get("humanistic_communication"))
    clinical_score = _number(clinical_group.get("score"))
    clinical_max = _number(clinical_group.get("max_score"), fallback=70)
    humanistic_score = _number(humanistic_group.get("score"))
    humanistic_max = _number(humanistic_group.get("max_score"), fallback=30)
    score_parts = [
        f"本轮总分 {_format_score(total_score)}/{_format_score(max_score)}",
    ]
    if clinical_max > 0:
        score_parts.append(f"临床 OSCE {_format_score(clinical_score)}/{_format_score(clinical_max)}")
    if humanistic_max > 0:
        score_parts.append(f"人文沟通 {_format_score(humanistic_score)}/{_format_score(humanistic_max)}")
    score_interpretation = "，".join(score_parts) + "。"
    ratio = total_score / max_score if max_score > 0 else 0
    judgement = _completion_judgement(ratio)
    return {
        **_empty_overall_evaluation(),
        "summary": _overall_summary(judgement),
        "score_interpretation": score_interpretation,
        "completion_judgement": judgement,
        "primary_strengths": _primary_strengths(report),
        "primary_weaknesses": _primary_weaknesses(report),
    }


def build_clinical_task_analysis(*, report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(dimension["dimension_id"]): _clinical_task_item(report=report, dimension=dimension)
        for dimension in _CLINICAL_DIMENSIONS
    }


def build_evidence_utilization_analysis(*, report: Mapping[str, Any], case: Case) -> dict[str, Any]:
    covered_nodes = _evidence_nodes(report, "covered_evidence_nodes")
    missing_nodes = _evidence_nodes(report, "missing_evidence_nodes")
    breakpoints = evidence_chain_breakpoints_from_report(report)
    if not breakpoints:
        breakpoints = _evidence_chain_breakpoints_from_case(case=case, missing_nodes=missing_nodes)
    return {
        **_empty_evidence_utilization_analysis(),
        "collected_key_evidence": covered_nodes[:8],
        "missing_key_evidence": missing_nodes[:8],
        "evidence_chain_breakpoints": breakpoints[:8],
        "unused_or_misused_evidence": _unused_or_misused_evidence(report=report, case=case),
    }


def build_process_strategy_analysis(*, report: Mapping[str, Any]) -> dict[str, Any]:
    action_order_summary = action_order_summary_from_report(report)
    trace = _mapping(report.get("clinical_reasoning_trace"))
    flags = sequence_flags_from_report(report)
    if not flags:
        flags = _sequence_flags_from_trace_root(trace)
    return {
        **_empty_process_strategy_analysis(),
        "action_order_summary": _action_order_summary_text(action_order_summary, flags),
        "sequence_flags": flags[:6],
        "premature_or_delayed_actions": [_sequence_flag_action(flag) for flag in flags[:4]],
    }


def build_humanistic_communication_analysis(*, report: Mapping[str, Any]) -> dict[str, Any]:
    missed_opportunities = _missed_opportunities(report)
    repair_actions = _relationship_repair_actions(report, missed_opportunities)
    return {
        **_empty_humanistic_communication_analysis(),
        "dimension_scores": [
            _humanistic_dimension_score(report, dimension)
            for dimension in _HUMANISTIC_DIMENSIONS
            if _report_has_dimension(report, str(dimension["dimension_id"]))
        ],
        "matched_evidence": _humanistic_matched_evidence(report),
        "missed_opportunities": missed_opportunities,
        "relationship_repair_actions": repair_actions,
    }


def build_next_training_plan(*, report: Mapping[str, Any]) -> dict[str, Any]:
    linked_gaps = _linked_training_gaps(report)
    top_goals = sorted(
        (_training_goal_from_gap(gap) for gap in linked_gaps),
        key=lambda item: item["priority"],
        reverse=True,
    )[:5]
    stage_actions = [_stage_triggered_action_from_goal(goal) for goal in top_goals]
    return {
        **_empty_next_training_plan(),
        "top_goals": top_goals,
        "stage_triggered_actions": stage_actions,
        "success_signals": [_success_signal_from_goal(goal) for goal in top_goals],
        "linked_training_gaps": linked_gaps,
    }


def _empty_overall_evaluation() -> dict[str, Any]:
    return {
        "summary": "",
        "score_interpretation": "",
        "completion_judgement": "not_ready",
        "primary_strengths": [],
        "primary_weaknesses": [],
    }


def build_diagnostic_contrast_analysis(*, report: Mapping[str, Any], case: Case) -> dict[str, Any]:
    final_submission = _mapping(report.get("final_submission"))
    submitted_diagnosis = str(final_submission.get("diagnosis") or "").strip()
    student_reasoning = str(final_submission.get("reasoning") or "").strip()
    matched_target_terms = _matched_target_terms(submitted_diagnosis, case)
    matched_differential = _matched_differential(submitted_diagnosis, case.diagnosis.differential_diagnoses)
    covered_nodes = _merge_evidence_nodes(
        _evidence_nodes(report, "covered_evidence_nodes"),
        _collected_case_fact_nodes(case, report.get("collected_source_ids")),
    )
    missing_nodes = _evidence_nodes(report, "missing_evidence_nodes")

    classification = _classification(
        submitted_diagnosis=submitted_diagnosis,
        matched_target_terms=matched_target_terms,
        matched_differential=matched_differential,
    )
    evidence_supporting_target = _supporting_target_evidence(
        covered_nodes=covered_nodes,
        reasoning_points=case.diagnosis.reasoning_points,
    )
    evidence_against_submitted = _evidence_against_submitted(
        covered_nodes=covered_nodes,
        matched_differential=matched_differential,
        negative_findings=case.negative_findings,
    )
    missed_discriminating_evidence = _missed_discriminating_evidence(
        missing_nodes=missing_nodes,
        negative_findings=case.negative_findings,
    )
    why_student_may_choose_it = _why_student_may_choose_diagnosis(
        submitted_diagnosis=submitted_diagnosis,
        student_reasoning=student_reasoning,
        matched_differential=matched_differential,
        case=case,
    )
    reasoning_error_patterns = _reasoning_error_patterns(report)

    return {
        **_empty_diagnostic_contrast_analysis(),
        "submitted_diagnosis": submitted_diagnosis,
        "target_diagnosis": case.diagnosis.main_diagnosis,
        "classification": classification,
        "matched_target_terms": matched_target_terms,
        "matched_differential_name": matched_differential.disease_name if matched_differential else "",
        "why_student_may_choose_it": why_student_may_choose_it,
        "evidence_supporting_submitted": [],
        "evidence_against_submitted": evidence_against_submitted,
        "evidence_supporting_target": evidence_supporting_target,
        "missed_discriminating_evidence": missed_discriminating_evidence,
        "reasoning_error_patterns": reasoning_error_patterns,
        "teacher_explanation": _teacher_explanation(
            classification=classification,
            submitted_diagnosis=submitted_diagnosis,
            target_diagnosis=case.diagnosis.main_diagnosis,
            matched_differential=matched_differential,
            evidence_against_submitted=evidence_against_submitted,
            evidence_supporting_target=evidence_supporting_target,
            missed_discriminating_evidence=missed_discriminating_evidence,
        ),
        "next_training_action": _next_training_action(classification),
    }


def _empty_diagnostic_contrast_analysis() -> dict[str, Any]:
    return {
        "submitted_diagnosis": "",
        "target_diagnosis": "",
        "classification": "unsupported",
        "matched_target_terms": [],
        "matched_differential_name": "",
        "why_student_may_choose_it": [],
        "evidence_supporting_submitted": [],
        "evidence_against_submitted": [],
        "evidence_supporting_target": [],
        "missed_discriminating_evidence": [],
        "reasoning_error_patterns": [],
        "teacher_explanation": "",
        "next_training_action": "",
    }


def _empty_clinical_task_analysis() -> dict[str, Any]:
    return {
        str(dimension["dimension_id"]): {
            "task_id": str(dimension["dimension_id"]),
            "label": str(dimension["label"]),
            "score": 0,
            "max_score": int(dimension["max_score"]),
            "completion_level": "missing",
            "completed_items": [],
            "missed_items": [],
            "next_action": str(dimension["fallback_action"]),
        }
        for dimension in _CLINICAL_DIMENSIONS
    }


def _empty_evidence_utilization_analysis() -> dict[str, Any]:
    return {
        "collected_key_evidence": [],
        "missing_key_evidence": [],
        "evidence_chain_breakpoints": [],
        "unused_or_misused_evidence": [],
    }


def _empty_process_strategy_analysis() -> dict[str, Any]:
    return {
        "action_order_summary": "本轮暂缺足够事件顺序信息。",
        "sequence_flags": [],
        "premature_or_delayed_actions": [],
    }


def _empty_humanistic_communication_analysis() -> dict[str, Any]:
    return {
        "dimension_scores": [
            {
                "dimension_id": str(dimension["dimension_id"]),
                "label": str(dimension["label"]),
                "score": 0,
                "max_score": int(dimension["max_score"]),
                "completion_level": "missing",
            }
            for dimension in _HUMANISTIC_DIMENSIONS
        ],
        "matched_evidence": [],
        "missed_opportunities": [],
        "relationship_repair_actions": [],
    }


def _empty_next_training_plan() -> dict[str, Any]:
    return {
        "top_goals": [],
        "stage_triggered_actions": [],
        "success_signals": [],
        "linked_training_gaps": [],
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any, *, fallback: float = 0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float(fallback)


def _format_score(value: float | int) -> str:
    normalized = float(value)
    return str(int(normalized)) if normalized.is_integer() else f"{normalized:.1f}"


def _completion_judgement(ratio: float) -> str:
    if ratio >= 0.85:
        return "strong"
    if ratio >= 0.65:
        return "mostly_complete"
    if ratio >= 0.4:
        return "needs_targeted_repair"
    return "needs_rebuild"


def _overall_summary(judgement: str) -> str:
    if judgement == "strong":
        return "本轮整体完成度较高，下一步重点是把证据链表达得更精炼。"
    if judgement == "mostly_complete":
        return "本轮已经完成主要训练任务，但仍有少数关键证据或推理表达需要补齐。"
    if judgement == "needs_targeted_repair":
        return "本轮已经收集到部分关键线索，但诊断验证、鉴别排除或表达结构仍需要定向修补。"
    return "本轮关键训练链路尚未闭合，下一轮应先补齐核心证据，再提交诊断与推理。"


def _primary_strengths(report: Mapping[str, Any]) -> list[str]:
    strengths: list[str] = []
    for task in sorted(
        (_clinical_task_item(report=report, dimension=dimension) for dimension in _CLINICAL_DIMENSIONS),
        key=lambda item: (item["score"] / item["max_score"]) if item["max_score"] else 0,
        reverse=True,
    ):
        ratio = (task["score"] / task["max_score"]) if task["max_score"] else 0
        if task["score"] <= 0 or ratio < 0.5:
            continue
        strengths.append(f"{task['label']}完成度相对较高（{_format_score(float(task['score']))}/{task['max_score']}）。")
        if len(strengths) >= 3:
            break
    return strengths or ["本轮尚未形成稳定优势项，先完成一次完整训练链路。"]


def _primary_weaknesses(report: Mapping[str, Any]) -> list[str]:
    weaknesses: list[str] = []
    training_gaps = report.get("training_gaps")
    if isinstance(training_gaps, list):
        for gap in training_gaps:
            if not isinstance(gap, Mapping):
                continue
            label = str(gap.get("label") or gap.get("gap_type") or "").strip()
            if label and label not in weaknesses:
                weaknesses.append(label)
            if len(weaknesses) >= 3:
                return weaknesses
    for task in build_clinical_task_analysis(report=report).values():
        if task["completion_level"] in {"missing", "weak"}:
            label = str(task["label"])
            if label not in weaknesses:
                weaknesses.append(label)
            if len(weaknesses) >= 3:
                break
    return weaknesses or ["暂无明确薄弱项。"]


def _normalize_text(value: str) -> str:
    return _PUNCTUATION_PATTERN.sub("", value).lower()


def _matched_target_terms(submitted_diagnosis: str, case: Case) -> list[str]:
    submitted = _normalize_text(submitted_diagnosis)
    if not submitted:
        return []
    terms = [case.diagnosis.main_diagnosis, *case.diagnosis.main_diagnosis_synonyms]
    exact_matches = [str(term) for term in terms if _normalize_text(str(term)) == submitted]
    if exact_matches:
        return exact_matches
    matches: list[str] = []
    for term in terms:
        normalized_term = _normalize_text(str(term))
        if normalized_term and (normalized_term in submitted or submitted in normalized_term):
            matches.append(str(term))
    return matches


def _matched_differential(
    submitted_diagnosis: str,
    differentials: list[DifferentialDiagnosis],
) -> DifferentialDiagnosis | None:
    submitted = _normalize_text(submitted_diagnosis)
    if not submitted:
        return None
    for differential in differentials:
        disease_name = _normalize_text(differential.disease_name)
        if disease_name and (disease_name in submitted or submitted in disease_name):
            return differential
    return None


def _classification(
    *,
    submitted_diagnosis: str,
    matched_target_terms: list[str],
    matched_differential: DifferentialDiagnosis | None,
) -> str:
    if matched_target_terms:
        return "correct"
    if matched_differential is not None:
        return "plausible_differential"
    normalized = _normalize_text(submitted_diagnosis)
    if "腹痛" in normalized or "急腹症" in normalized:
        return "partially_correct"
    return "unsupported"


def _evidence_nodes(report: Mapping[str, Any], key: str) -> list[dict[str, str]]:
    evidence_graph_summary = _mapping(report.get("evidence_graph_summary"))
    nodes = evidence_graph_summary.get(key)
    if not isinstance(nodes, list):
        return []
    result: list[dict[str, str]] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        source_id = str(node.get("source_id") or "").strip()
        label = str(node.get("label") or source_id).strip()
        if source_id:
            item = {"source_id": source_id, "label": label}
            node_id = str(node.get("node_id") or "").strip()
            if node_id:
                item["node_id"] = node_id
            result.append(item)
    return result


def _clinical_task_item(*, report: Mapping[str, Any], dimension: Mapping[str, Any]) -> dict[str, Any]:
    dimension_id = str(dimension["dimension_id"])
    score = _dimension_score(report, dimension_id)
    max_score = _dimension_max_score(report, dimension_id, fallback=int(dimension["max_score"]))
    traces = _dimension_trace_items(report, dimension_id)
    missed_items = [_trace_summary(trace, report) for trace in traces if _trace_score(trace) < _trace_max_score(trace)]
    completed_items = [_trace_summary(trace, report) for trace in traces if _trace_score(trace) > 0]
    return {
        "task_id": dimension_id,
        "label": str(dimension["label"]),
        "score": int(score) if score.is_integer() else score,
        "max_score": max_score,
        "completion_level": _task_completion_level(score, max_score),
        "completed_items": completed_items[:5],
        "missed_items": missed_items[:5],
        "next_action": _task_next_action(missed_items, str(dimension["fallback_action"])),
    }


def _dimension_score(report: Mapping[str, Any], dimension_id: str) -> float:
    dimension_scores = _mapping(report.get("dimension_scores"))
    value = dimension_scores.get(dimension_id)
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _dimension_max_score(report: Mapping[str, Any], dimension_id: str, *, fallback: int) -> int:
    rubric_scores = _mapping(report.get("rubric_scores"))
    rubric_total = sum(
        max(0, int(_number(item.get("max_score"))))
        for item in rubric_scores.values()
        if isinstance(item, Mapping) and str(item.get("dimension_id") or "") == dimension_id
    )
    if rubric_total > 0:
        return rubric_total
    return fallback


def _report_has_dimension(report: Mapping[str, Any], dimension_id: str) -> bool:
    if dimension_id in _mapping(report.get("dimension_scores")):
        return True
    if dimension_id in _mapping(report.get("dimension_traces")):
        return True
    return any(
        isinstance(item, Mapping) and str(item.get("dimension_id") or "") == dimension_id
        for item in _mapping(report.get("rubric_scores")).values()
    )


def _dimension_trace_items(report: Mapping[str, Any], dimension_id: str) -> list[Mapping[str, Any]]:
    dimension_traces = _mapping(report.get("dimension_traces"))
    traces = dimension_traces.get(dimension_id)
    if not isinstance(traces, list):
        return []
    return [trace for trace in traces if isinstance(trace, Mapping)]


def _trace_score(trace: Mapping[str, Any]) -> float:
    return _number(trace.get("score"))


def _trace_max_score(trace: Mapping[str, Any]) -> float:
    return max(_number(trace.get("max_score")), 0)


def _trace_summary(trace: Mapping[str, Any], report: Mapping[str, Any]) -> dict[str, Any]:
    item_id = _trace_item_id(trace)
    rubric_score = _mapping(_mapping(report.get("rubric_scores")).get(item_id))
    label = str(
        trace.get("label")
        or trace.get("description")
        or rubric_score.get("description")
        or item_id
        or "未命名评分项"
    ).strip()
    return {
        "item_id": item_id,
        "label": label,
        "score": _trace_score(trace),
        "max_score": _trace_max_score(trace),
        "gap_type": str(trace.get("gap_type") or "").strip(),
        "next_training_action": str(trace.get("next_training_action") or "").strip(),
    }


def _task_completion_level(score: float, max_score: int) -> str:
    ratio = score / max_score if max_score > 0 else 0
    if score <= 0:
        return "missing"
    if ratio < 0.5:
        return "weak"
    if ratio < 0.8:
        return "partial"
    return "solid"


def _task_next_action(missed_items: list[dict[str, Any]], fallback: str) -> str:
    for item in missed_items:
        action = str(item.get("next_training_action") or "").strip()
        if action:
            return action
    if missed_items:
        labels = "、".join(str(item["label"]) for item in missed_items[:3] if item.get("label"))
        if labels:
            return f"下一轮优先补齐：{labels}。"
    return fallback


def _evidence_chain_breakpoints_from_case(*, case: Case, missing_nodes: list[dict[str, str]]) -> list[dict[str, Any]]:
    missing_by_source = {node["source_id"]: node for node in missing_nodes}
    breakpoints: list[dict[str, Any]] = []
    for point in case.diagnosis.reasoning_points:
        missing_evidence = [missing_by_source[source_id] for source_id in point.required_evidence if source_id in missing_by_source]
        if not missing_evidence:
            continue
        kind = _normalized_reasoning_kind(point.kind)
        breakpoints.append(
            {
                "breakpoint_id": point.point_id,
                "statement": point.statement,
                "kind": kind,
                "status": "broken",
                "missing_evidence": [item["source_id"] for item in missing_evidence],
                "missing_evidence_labels": [item["label"] for item in missing_evidence],
                "teacher_action": _teacher_action_for_breakpoint(kind, [item["label"] for item in missing_evidence]),
            }
        )
    return breakpoints


def _normalized_reasoning_kind(kind: str) -> str:
    if kind == "支持":
        return "support"
    if kind == "排除":
        return "exclude"
    return "reasoning"


def _teacher_action_for_breakpoint(kind: str, missing_labels: list[str]) -> str:
    focus = "、".join(missing_labels[:3]) if missing_labels else "关键证据"
    if kind == "exclude":
        return f"先补齐{focus}，再说明这些证据如何排除相近诊断。"
    return f"先补齐{focus}，再说明这些证据如何支持或修正当前诊断假设。"


def _unused_or_misused_evidence(*, report: Mapping[str, Any], case: Case) -> list[dict[str, str]]:
    final_submission = _mapping(report.get("final_submission"))
    combined = f"{final_submission.get('diagnosis', '')} {final_submission.get('reasoning', '')}"
    result: list[dict[str, str]] = []
    for clue in case.distractor_clues:
        if clue.patient_expression and clue.patient_expression in combined:
            result.append(
                {
                    "source_id": clue.clue_id,
                    "label": clue.patient_expression,
                    "issue": "患者想法不能直接作为诊断依据。",
                    "next_training_action": "下一轮把患者叙事和医学证据分开记录。",
                }
            )
    return result


def _sequence_flags_from_trace_root(trace: Mapping[str, Any]) -> list[dict[str, Any]]:
    flags = trace.get("sequence_flags")
    if not isinstance(flags, list):
        return []
    result: list[dict[str, Any]] = []
    for flag in flags:
        if not isinstance(flag, Mapping):
            continue
        flag_id = str(flag.get("flag_id") or "").strip()
        label = str(flag.get("label") or flag_id).strip()
        if not label:
            continue
        result.append(
            {
                "flag_id": flag_id or label,
                "label": label,
                "severity": str(flag.get("severity") or "medium"),
                "evidence": str(flag.get("evidence") or ""),
            }
        )
    return result


def _action_order_summary_text(action_order_summary: Mapping[str, Any], flags: list[dict[str, Any]]) -> str:
    if flags:
        return "本轮过程顺序存在需要复盘的节点，应在下一轮按病史、假设、查体、检查、诊断表达逐步推进。"
    if action_order_summary:
        return "本轮训练过程顺序未发现明显结构性问题。"
    return "本轮暂缺足够事件顺序信息。"


def _sequence_flag_action(flag: Mapping[str, Any]) -> str:
    flag_id = str(flag.get("flag_id") or "")
    label = str(flag.get("label") or "")
    if "hypothesis" in flag_id or "假设" in label:
        return "下一轮先形成诊断假设，再选择查体和检查去验证支持证据与反证。"
    if "testing" in flag_id or "检查" in label:
        return "下一轮申请辅助检查前，先完成关键查体并说明检查要验证什么。"
    return f"下一轮围绕“{label or flag_id}”调整训练顺序。"


def _humanistic_dimension_score(report: Mapping[str, Any], dimension: Mapping[str, Any]) -> dict[str, Any]:
    dimension_id = str(dimension["dimension_id"])
    score = _dimension_score(report, dimension_id)
    max_score = _dimension_max_score(report, dimension_id, fallback=int(dimension["max_score"]))
    return {
        "dimension_id": dimension_id,
        "label": str(dimension["label"]),
        "score": int(score) if score.is_integer() else score,
        "max_score": max_score,
        "completion_level": _task_completion_level(score, max_score),
    }


def _humanistic_matched_evidence(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for dimension in _HUMANISTIC_DIMENSIONS:
        dimension_id = str(dimension["dimension_id"])
        for trace in _dimension_trace_items(report, dimension_id):
            evidence = _string_list(trace.get("matched_evidence"))
            if not evidence or _trace_score(trace) <= 0:
                continue
            result.append(
                {
                    "dimension_id": dimension_id,
                    "dimension_label": str(dimension["label"]),
                    "rubric_item_id": _trace_item_id(trace),
                    "label": str(trace.get("label") or _trace_item_id(trace) or "人文沟通证据"),
                    "score": _trace_score(trace),
                    "max_score": _trace_max_score(trace),
                    "stage": str(trace.get("stage") or ""),
                    "matched_evidence": evidence,
                    "match_method": str(trace.get("match_method") or trace.get("match_kind") or ""),
                    "timing_status": str(trace.get("timing_status") or ""),
                }
            )
    return result[:8]


def _missed_opportunities(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    opportunities = report.get("missed_opportunities")
    if not isinstance(opportunities, list):
        return []
    result: list[dict[str, Any]] = []
    for opportunity in opportunities:
        if not isinstance(opportunity, Mapping):
            continue
        opportunity_id = str(opportunity.get("opportunity_id") or "").strip()
        gap_type = str(opportunity.get("gap_type") or "").strip()
        if not opportunity_id and not gap_type:
            continue
        result.append(
            {
                "opportunity_id": opportunity_id or gap_type,
                "gap_type": gap_type,
                "stage": str(opportunity.get("stage") or ""),
                "trigger_evidence": str(opportunity.get("trigger_evidence") or ""),
                "expected_response": str(opportunity.get("expected_response") or ""),
                "next_training_action": str(opportunity.get("next_training_action") or ""),
            }
        )
    return result[:8]


def _relationship_repair_actions(
    report: Mapping[str, Any],
    missed_opportunities: list[dict[str, Any]],
) -> list[str]:
    actions: list[str] = []
    for opportunity in missed_opportunities:
        action = str(opportunity.get("next_training_action") or "").strip()
        if action and action not in actions:
            actions.append(action)
    for gap in _linked_training_gaps(report):
        if str(gap.get("skill_type") or "") != "relationship_repair" and "relationship" not in str(gap.get("gap_type") or ""):
            continue
        action = str(gap.get("next_training_action") or "").strip()
        if action and action not in actions:
            actions.append(action)
    return actions[:4]


def _linked_training_gaps(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    gaps = report.get("training_gaps")
    if not isinstance(gaps, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for gap in gaps:
        if not isinstance(gap, Mapping):
            continue
        dimension_id = str(gap.get("dimension_id") or "").strip()
        gap_type = str(gap.get("gap_type") or "").strip()
        gap_source = str(gap.get("gap_source") or "").strip()
        if dimension_id not in _HUMANISTIC_DIMENSION_IDS and gap_source != "missed_opportunity" and not _is_humanistic_gap_type(gap_type):
            continue
        dedupe_key = f"{gap_type}:{gap.get('rubric_item_id') or ''}:{gap_source}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        result.append(
            {
                "dimension_id": dimension_id,
                "rubric_item_id": str(gap.get("rubric_item_id") or ""),
                "gap_type": gap_type,
                "label": str(gap.get("label") or gap_type),
                "missing_score": _number(gap.get("missing_score")),
                "severity": str(gap.get("severity") or "medium"),
                "stage": str(gap.get("stage") or ""),
                "trigger_stage": str(gap.get("trigger_stage") or gap.get("stage") or ""),
                "next_training_action": str(gap.get("next_training_action") or ""),
                "skill_type": str(gap.get("skill_type") or ""),
                "gap_source": gap_source,
            }
        )
    return result[:10]


def _is_humanistic_gap_type(gap_type: str) -> bool:
    return any(token in gap_type for token in ["narrative", "communication", "ethics", "relationship", "empathy", "consent"])


def _training_goal_from_gap(gap: Mapping[str, Any]) -> dict[str, Any]:
    gap_type = str(gap.get("gap_type") or "")
    trigger = _trigger_for_gap(gap)
    action = str(gap.get("next_training_action") or _default_gap_action(gap_type))
    success_signal = _success_signal_text(gap_type)
    return {
        "gap_type": gap_type,
        "label": str(gap.get("label") or gap_type),
        "dimension_id": str(gap.get("dimension_id") or ""),
        "stage": str(gap.get("trigger_stage") or gap.get("stage") or _stage_for_gap_type(gap_type)),
        "priority": _gap_priority(gap),
        "severity": str(gap.get("severity") or "medium"),
        "trigger": trigger,
        "next_training_action": action,
        "success_signal": success_signal,
        "skill_type": str(gap.get("skill_type") or _skill_type_for_gap(gap_type)),
        "gap_source": str(gap.get("gap_source") or ""),
    }


def _gap_priority(gap: Mapping[str, Any]) -> float:
    severity_bonus = {"high": 4, "medium": 2, "low": 0}.get(str(gap.get("severity") or "medium"), 1)
    source_bonus = 3 if str(gap.get("gap_source") or "") == "missed_opportunity" else 0
    ethics_bonus = 2 if "ethics" in str(gap.get("gap_type") or "") or "consent" in str(gap.get("gap_type") or "") else 0
    return _number(gap.get("missing_score")) + severity_bonus + source_bonus + ethics_bonus


def _stage_triggered_action_from_goal(goal: Mapping[str, Any]) -> dict[str, Any]:
    gap_type = str(goal.get("gap_type") or "")
    return {
        "stage": str(goal.get("stage") or _stage_for_gap_type(gap_type)),
        "trigger": str(goal.get("trigger") or _trigger_for_gap(goal)),
        "action": str(goal.get("next_training_action") or _default_gap_action(gap_type)),
        "gap_type": gap_type,
        "success_signal": str(goal.get("success_signal") or _success_signal_text(gap_type)),
    }


def _success_signal_from_goal(goal: Mapping[str, Any]) -> str:
    label = str(goal.get("label") or goal.get("gap_type") or "训练目标")
    signal = str(goal.get("success_signal") or _success_signal_text(str(goal.get("gap_type") or "")))
    return f"完成标志：{label}；{signal}"


def _trigger_for_gap(gap: Mapping[str, Any]) -> str:
    gap_type = str(gap.get("gap_type") or "")
    if "empathy" in gap_type or "relationship" in gap_type:
        return "患者表达焦虑或担忧"
    if "consent" in gap_type or "ethics" in gap_type:
        return "准备查体或辅助检查前"
    if "summary" in gap_type or "communication" in gap_type:
        return "阶段转换或提交诊断前"
    if "narrative" in gap_type or "perspective" in gap_type:
        return "问诊早期了解患者视角时"
    return str(gap.get("trigger_stage") or gap.get("stage") or "下一轮对应阶段")


def _stage_for_gap_type(gap_type: str) -> str:
    if "consent" in gap_type or "ethics" in gap_type:
        return "physical_exam"
    if "summary" in gap_type:
        return "stage_transition"
    return "history_taking"


def _default_gap_action(gap_type: str) -> str:
    if "empathy" in gap_type or "relationship" in gap_type:
        return "下一轮患者表达焦虑或担忧后，先回应情绪，再继续医学问诊。"
    if "consent" in gap_type or "ethics" in gap_type:
        return "下一轮查体或检查前先说明目的、可能不适并征得同意。"
    if "summary" in gap_type or "communication" in gap_type:
        return "下一轮阶段转换前先总结已理解内容，并请患者确认。"
    if "narrative" in gap_type or "perspective" in gap_type:
        return "下一轮问诊早期主动询问患者担忧、期待和生活影响。"
    return "下一轮围绕该训练缺口做一次可观察、可记录的动作。"


def _success_signal_text(gap_type: str) -> str:
    if "empathy" in gap_type or "relationship" in gap_type:
        return "患者表达担忧后，学生下一句能先承认情绪并说明会一起处理。"
    if "consent" in gap_type or "ethics" in gap_type:
        return "查体或检查动作发生前，学生已说明目的、可能不适并获得同意。"
    if "summary" in gap_type or "communication" in gap_type:
        return "阶段转换前，学生能总结关键信息并确认理解是否准确。"
    if "narrative" in gap_type or "perspective" in gap_type:
        return "学生能主动询问患者担忧、期待或生活影响，并在后续推理中使用。"
    return "学生完成对应可观察动作，并在报告 trace 中记录为 recovered。"


def _skill_type_for_gap(gap_type: str) -> str:
    if "empathy" in gap_type or "relationship" in gap_type:
        return "relationship_repair"
    if "consent" in gap_type or "ethics" in gap_type:
        return "ethics_consent"
    if "summary" in gap_type or "communication" in gap_type:
        return "communication_structure"
    if "narrative" in gap_type or "perspective" in gap_type:
        return "narrative_perspective"
    return "clinical_reasoning"


def _trace_item_id(trace: Mapping[str, Any]) -> str:
    return str(trace.get("item_id") or trace.get("rubric_item_id") or "").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (str(raw).strip() for raw in value) if item]


def _collected_case_fact_nodes(case: Case, collected_source_ids: Any) -> list[dict[str, str]]:
    if not isinstance(collected_source_ids, list):
        return []
    collected = {str(source_id) for source_id in collected_source_ids if str(source_id).strip()}
    result: list[dict[str, str]] = []
    for fact in case.history.hidden_facts:
        if fact.fact_id in collected:
            result.append({"source_id": fact.fact_id, "label": fact.canonical_answer})
    return result


def _merge_evidence_nodes(*groups: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for group in groups:
        for node in group:
            source_id = node["source_id"]
            if source_id in seen:
                continue
            seen.add(source_id)
            result.append(node)
    return result


def _supporting_target_evidence(
    *,
    covered_nodes: list[dict[str, str]],
    reasoning_points: list[ReasoningPoint],
) -> list[dict[str, str]]:
    support_source_ids = {
        source_id
        for point in reasoning_points
        if point.kind == "支持"
        for source_id in point.required_evidence
    }
    return _nodes_with_sources(covered_nodes, support_source_ids)


def _evidence_against_submitted(
    *,
    covered_nodes: list[dict[str, str]],
    matched_differential: DifferentialDiagnosis | None,
    negative_findings: list[NegativeFinding],
) -> list[dict[str, str]]:
    if matched_differential is None:
        return []
    exclusion_source_ids = _negative_source_ids_for_diagnosis(
        negative_findings=negative_findings,
        diagnosis_name=matched_differential.disease_name,
    )
    return _nodes_with_sources(covered_nodes, exclusion_source_ids)


def _missed_discriminating_evidence(
    *,
    missing_nodes: list[dict[str, str]],
    negative_findings: list[NegativeFinding],
) -> list[dict[str, str]]:
    exclusion_source_ids = {finding.source for finding in negative_findings}
    return _nodes_with_sources(missing_nodes, exclusion_source_ids)


def _negative_source_ids_for_diagnosis(
    *,
    negative_findings: list[NegativeFinding],
    diagnosis_name: str,
) -> set[str]:
    normalized_diagnosis = _normalize_text(diagnosis_name)
    return {
        finding.source
        for finding in negative_findings
        if any(_normalize_text(name) == normalized_diagnosis for name in finding.supports_exclusion_of)
    }


def _nodes_with_sources(nodes: list[dict[str, str]], source_ids: set[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for node in nodes:
        if node["source_id"] in source_ids and node not in result:
            result.append(node)
    return result


def _why_student_may_choose_diagnosis(
    *,
    submitted_diagnosis: str,
    student_reasoning: str,
    matched_differential: DifferentialDiagnosis | None,
    case: Case,
) -> list[str]:
    reasons: list[str] = []
    combined = f"{submitted_diagnosis} {student_reasoning}"
    for keyword in ["恶心", "呕吐", "腹泻", "吃坏", "胃肠"]:
        if keyword in combined:
            reasons.append(f"学生理由中提到“{keyword}”，这可能把思路带向消化道相关鉴别诊断。")
            break
    if matched_differential is not None:
        reasons.append(f"{matched_differential.disease_name}本身属于本病例需要排除的鉴别诊断。")
    for clue in case.distractor_clues:
        if any(token and token in combined for token in ["吃坏", "胃肠", clue.patient_expression]):
            reasons.append(f"患者表达“{clue.patient_expression}”容易形成干扰，但它不能直接作为确诊依据。")
            break
    if not reasons:
        reasons.append("学生提交的诊断需要回到已采集证据中重新验证支持依据和反对依据。")
    return reasons


def _reasoning_error_patterns(report: Mapping[str, Any]) -> list[str]:
    trace = _mapping(report.get("clinical_reasoning_trace"))
    patterns = trace.get("cognitive_patterns")
    result: list[str] = []
    if isinstance(patterns, list):
        for pattern in patterns:
            if not isinstance(pattern, Mapping):
                continue
            label = str(pattern.get("label") or pattern.get("pattern_id") or "").strip()
            if label and label not in result:
                result.append(label)
    for gap in report.get("training_gaps", []) if isinstance(report.get("training_gaps"), list) else []:
        if not isinstance(gap, Mapping):
            continue
        label = str(gap.get("label") or gap.get("gap_type") or "").strip()
        if label and label not in result:
            result.append(label)
    return result[:5]


def _teacher_explanation(
    *,
    classification: str,
    submitted_diagnosis: str,
    target_diagnosis: str,
    matched_differential: DifferentialDiagnosis | None,
    evidence_against_submitted: list[dict[str, str]],
    evidence_supporting_target: list[dict[str, str]],
    missed_discriminating_evidence: list[dict[str, str]],
) -> str:
    if classification == "correct":
        return f"本轮提交的“{submitted_diagnosis}”已经命中目标诊断“{target_diagnosis}”，下一步重点是把支持依据和排除依据表达完整。"
    if matched_differential is not None:
        against = _label_list(evidence_against_submitted, "当前已采集证据")
        support = _label_list(evidence_supporting_target, f"支持{target_diagnosis}的证据")
        missing = _label_list(missed_discriminating_evidence, "仍需补采的鉴别证据")
        return (
            f"“{submitted_diagnosis}”可以作为鉴别诊断讨论，但本轮不能直接作为最终结论。"
            f"{against}会削弱这个判断；{support}更能支持“{target_diagnosis}”。"
            f"{missing}应用来进一步完成排除路径。"
        )
    return (
        f"本轮提交的“{submitted_diagnosis}”缺少足够结构化证据支撑。"
        f"需要回到已采集线索，比较它与“{target_diagnosis}”之间的支持证据、反对证据和仍需补采的鉴别证据。"
    )


def _next_training_action(classification: str) -> str:
    if classification == "correct":
        return "下一轮继续练习先列支持依据，再列反证 / 排除依据，最后用一句话完成诊断表达。"
    return "下一轮提交诊断前，先列支持依据，再列反证 / 排除依据，最后判断哪个诊断更符合证据链。"


def _label_list(nodes: list[dict[str, str]], fallback: str) -> str:
    labels = [node["label"] for node in nodes[:3] if node.get("label")]
    return "、".join(labels) if labels else fallback
