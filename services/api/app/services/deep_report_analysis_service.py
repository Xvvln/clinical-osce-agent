from __future__ import annotations

import re
from typing import Any, Mapping

from app.models.case import Case, DifferentialDiagnosis, NegativeFinding, ReasoningPoint

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


def build_deep_report_analysis(*, report: Mapping[str, Any], case: Case) -> dict[str, Any]:
    return {
        "version": DEEP_REPORT_ANALYSIS_VERSION,
        "status": "generated",
        "diagnostic_contrast_analysis": build_diagnostic_contrast_analysis(report=report, case=case),
    }


def build_legacy_deep_report_analysis() -> dict[str, Any]:
    return {
        "version": DEEP_REPORT_ANALYSIS_VERSION,
        "status": "legacy_report",
        "diagnostic_contrast_analysis": _empty_diagnostic_contrast_analysis(),
    }


def build_diagnostic_contrast_analysis(*, report: Mapping[str, Any], case: Case) -> dict[str, Any]:
    final_submission = _mapping(report.get("final_submission"))
    submitted_diagnosis = str(final_submission.get("diagnosis") or "").strip()
    student_reasoning = str(final_submission.get("reasoning") or "").strip()
    matched_target_terms = _matched_target_terms(submitted_diagnosis, case)
    matched_differential = _matched_differential(submitted_diagnosis, case.diagnosis.differential_diagnoses)
    covered_nodes = _evidence_nodes(report, "covered_evidence_nodes")
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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


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
            result.append({"source_id": source_id, "label": label})
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
