from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from app.models.case import Case, HiddenFact, ReasoningPoint
from app.services.admin_display_resolver import rubric_item_label, rubric_item_labels

TRACE_VERSION = "clinical_reasoning_trace_v1"

HISTORY_SLOT_LABELS: dict[str, str] = {
    "onset": "追问起病时间",
    "duration": "追问持续时间",
    "location": "追问疼痛部位",
    "character": "追问疼痛性质",
    "radiation": "追问放射或转移",
    "severity": "追问疼痛程度",
    "aggravating": "追问加重因素",
    "relieving": "追问缓解因素",
    "progression": "追问症状演变",
    "associated_symptom": "追问伴随症状",
    "frequency": "追问发作频率",
    "timing": "追问发作时段",
    "context": "追问诱发背景",
    "negation": "追问阴性症状",
}

PATTERN_DEFINITIONS: dict[str, dict[str, str]] = {
    "weak_problem_representation": {
        "label": "问题表征薄弱",
        "category": "problem_representation",
        "why": "临床推理需要先把主诉转化为结构化问题表征；如果起病与进展、核心症状特征、伴随信息和相关阴性信息不清，后续诊断假设会缺少支点。",
        "remediation": "下一轮先用开放式问题确认主诉和病程，再根据当前病例的关键训练点补齐症状特征、伴随信息和相关阴性信息。",
    },
    "premature_testing_before_exam": {
        "label": "检查申请早于关键查体",
        "category": "hypothesis_testing",
        "why": "辅助检查应服务于病史和查体形成的诊断假设；跳过关键查体会让检查选择变成列表式申请。",
        "remediation": "下一轮在申请辅助检查前，先说明当前假设，并选择能验证或反驳该假设的关键查体。",
    },
    "delayed_hypothesis_generation": {
        "label": "诊断假设生成偏晚",
        "category": "hypothesis_testing",
        "why": "OSCE 训练关注边采集证据边形成假设；只在最后提交诊断，容易忽略哪些证据正在支持或反驳假设。",
        "remediation": "下一轮在完成核心病史后先提出 1-2 个初步假设，再决定查体和检查要验证什么。",
    },
    "thin_differential_reasoning": {
        "label": "鉴别诊断过窄",
        "category": "differential_reasoning",
        "why": "临床诊断不只是命中主诊断，还要解释为什么暂不支持其他相近可能。",
        "remediation": "下一轮提交前至少整理一个支持依据、一个排除依据和一个仍需验证的问题。",
    },
    "weak_evidence_synthesis": {
        "label": "证据整合不足",
        "category": "evidence_synthesis",
        "why": "零散证据需要被组织成支持、反证和不确定性，否则推理表达会显得跳跃。",
        "remediation": "下一轮用“病史证据、查体证据、检查证据、鉴别排除”四段式整理诊断推理。",
    },
    "premature_closure_risk": {
        "label": "过早闭合风险",
        "category": "metacognition",
        "why": "在问题表征和鉴别排除不足时过早提交结论，容易把单个线索当成完整诊断链。",
        "remediation": "下一轮提交前先自问：还有哪些关键事实没确认？有哪些相近诊断需要排除？现有证据是否足够支持结论？",
    },
}


def build_clinical_reasoning_trace(
    *,
    session: Any,
    case: Case,
    report: Mapping[str, Any],
) -> dict[str, Any]:
    revealed_facts = set(_string_list(_get(session, "revealed_facts", [])))
    requested_exams = set(_string_list(_get(session, "requested_exams", [])))
    requested_tests = set(_string_list(_get(session, "requested_tests", [])))
    collected_evidence: set[str] = set()
    collected_evidence.update(revealed_facts)
    collected_evidence.update(requested_exams)
    collected_evidence.update(requested_tests)

    final_submission = _mapping_or_none(_get(session, "final_submission", None))
    student_hypotheses = _string_list(_get(session, "student_hypotheses", []))

    problem_representation = _build_problem_representation(case, revealed_facts)
    action_timeline = _build_action_timeline(session, case)
    action_order_summary = _build_action_order_summary(action_timeline, problem_representation)
    illness_script_alignment = _build_illness_script_alignment(case, collected_evidence)
    evidence_chain_breakpoints = _build_evidence_chain_breakpoints(case, illness_script_alignment)
    hypothesis_testing = _build_hypothesis_testing(
        requested_exams=requested_exams,
        requested_tests=requested_tests,
        final_submission=final_submission,
        student_hypotheses=student_hypotheses,
        action_order_summary=action_order_summary,
    )
    differential_reasoning = _build_differential_reasoning(
        case=case,
        report=report,
        final_submission=final_submission,
        student_hypotheses=student_hypotheses,
    )
    evidence_synthesis = _build_evidence_synthesis(
        report=report,
        illness_script_alignment=illness_script_alignment,
        final_submission=final_submission,
    )
    cognitive_patterns = _build_cognitive_patterns(
        problem_representation=problem_representation,
        hypothesis_testing=hypothesis_testing,
        differential_reasoning=differential_reasoning,
        evidence_synthesis=evidence_synthesis,
        evidence_chain_breakpoints=evidence_chain_breakpoints,
        final_submission=final_submission,
        report=report,
    )
    return {
        "trace_version": TRACE_VERSION,
        "case_id": case.case_id,
        "problem_representation": problem_representation,
        "action_timeline": action_timeline,
        "action_order_summary": action_order_summary,
        "illness_script_alignment": illness_script_alignment,
        "evidence_chain_breakpoints": evidence_chain_breakpoints,
        "hypothesis_testing": hypothesis_testing,
        "differential_reasoning": differential_reasoning,
        "evidence_synthesis": evidence_synthesis,
        "cognitive_patterns": cognitive_patterns,
        "teacher_focus_questions": _teacher_focus_questions(cognitive_patterns),
        "student_visible_summary": _student_visible_summary(cognitive_patterns),
    }


def _build_problem_representation(case: Case, revealed_facts: set[str]) -> dict[str, Any]:
    facts = [
        fact
        for fact in case.history.hidden_facts
        if fact.topic in {"现病史", "系统回顾"} and fact.slot is not None
    ]
    semantic_qualifiers = [_semantic_qualifier(case, fact, revealed_facts) for fact in facts]
    covered = [item for item in semantic_qualifiers if item["status"] == "covered"]
    missing = [item for item in semantic_qualifiers if item["status"] != "covered"]
    total_count = len(semantic_qualifiers)
    coverage_ratio = len(covered) / total_count if total_count else 1.0
    return {
        "status": _coverage_status(coverage_ratio, weak_threshold=0.45, strong_threshold=0.8),
        "coverage_ratio": round(coverage_ratio, 4),
        "covered_count": len(covered),
        "total_count": total_count,
        "semantic_qualifiers": semantic_qualifiers,
        "covered_semantic_qualifiers": covered,
        "missing_semantic_qualifiers": missing,
    }


def _semantic_qualifier(case: Case, fact: HiddenFact, revealed_facts: set[str]) -> dict[str, Any]:
    labels = rubric_item_labels(fact.linked_rubric_items[:1], [case.case_id]) if fact.linked_rubric_items else []
    slot = str(fact.slot or "")
    return {
        "qualifier_id": f"history_slot:{slot or fact.fact_id}",
        "label": labels[0] if labels else HISTORY_SLOT_LABELS.get(slot, f"追问{fact.topic}"),
        "slot": slot,
        "fact_id": fact.fact_id,
        "linked_rubric_items": list(fact.linked_rubric_items),
        "status": "covered" if fact.fact_id in revealed_facts else "missing",
    }


def _build_illness_script_alignment(case: Case, collected_evidence: set[str]) -> dict[str, Any]:
    script_elements = [_script_element(point, collected_evidence) for point in case.diagnosis.reasoning_points]
    covered = [item for item in script_elements if item["status"] == "covered"]
    missing = [item for item in script_elements if item["status"] != "covered"]
    total_evidence = sum(len(item["required_evidence"]) for item in script_elements)
    covered_evidence = sum(len(item["covered_evidence"]) for item in script_elements)
    coverage_ratio = covered_evidence / total_evidence if total_evidence else 1.0
    return {
        "status": _coverage_status(coverage_ratio, weak_threshold=0.4, strong_threshold=0.75),
        "coverage_ratio": round(coverage_ratio, 4),
        "covered_script_elements": covered,
        "missing_script_elements": missing,
        "script_elements": script_elements,
    }


def _script_element(point: ReasoningPoint, collected_evidence: set[str]) -> dict[str, Any]:
    required_evidence = list(point.required_evidence)
    covered_evidence = [evidence for evidence in required_evidence if evidence in collected_evidence]
    if not required_evidence or len(covered_evidence) == len(required_evidence):
        status = "covered"
    elif covered_evidence:
        status = "partial"
    else:
        status = "missing"
    return {
        "point_id": point.point_id,
        "statement": point.statement,
        "kind": point.kind,
        "status": status,
        "required_evidence": required_evidence,
        "covered_evidence": covered_evidence,
        "missing_evidence": [evidence for evidence in required_evidence if evidence not in collected_evidence],
    }


def _build_action_timeline(session: Any, case: Case) -> list[dict[str, Any]]:
    explicit_timeline = _timeline_list(_get(session, "action_timeline", []))
    if explicit_timeline:
        return _normalize_action_timeline(explicit_timeline, case)

    action_timeline: list[dict[str, Any]] = []
    for turn_index, turn in enumerate(_mapping_list(_get(session, "agent_turn_memory", [])), start=1):
        revealed_fact_ids = _string_list(turn.get("revealed_fact_ids"))
        if not revealed_fact_ids:
            fact_id = str(turn.get("revealed_fact_id") or "").strip()
            revealed_fact_ids = [fact_id] if fact_id else []
        for fact_id in revealed_fact_ids:
            action_timeline.append(
                {
                    "turn_index": turn_index,
                    "action_type": "history_fact_revealed",
                    "source_id": fact_id,
                    "label": _evidence_label(case, fact_id),
                }
            )

    known_sources = {str(item.get("source_id")) for item in action_timeline if item.get("source_id")}
    next_index = len(action_timeline) + 1
    for exam_code in _string_list(_get(session, "requested_exams", [])):
        if exam_code in known_sources:
            continue
        action_timeline.append(
            {
                "turn_index": next_index,
                "action_type": "physical_exam_requested",
                "source_id": exam_code,
                "label": _evidence_label(case, exam_code),
            }
        )
        next_index += 1
    for test_code in _string_list(_get(session, "requested_tests", [])):
        if test_code in known_sources:
            continue
        action_timeline.append(
            {
                "turn_index": next_index,
                "action_type": "auxiliary_test_requested",
                "source_id": test_code,
                "label": _evidence_label(case, test_code),
            }
        )
        next_index += 1
    if _mapping_or_none(_get(session, "final_submission", None)):
        action_timeline.append(
            {
                "turn_index": next_index,
                "action_type": "diagnosis_submitted",
                "source_id": "final_submission",
                "label": "提交诊断",
            }
        )
    return _normalize_action_timeline(action_timeline, case)


def _normalize_action_timeline(items: list[Mapping[str, Any]], case: Case) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for fallback_index, item in enumerate(items, start=1):
        action_type = str(item.get("action_type") or "").strip()
        source_id = str(item.get("source_id") or "").strip()
        if not action_type:
            continue
        raw_turn_index = item.get("turn_index", fallback_index)
        turn_index = int(raw_turn_index) if isinstance(raw_turn_index, int | str) and str(raw_turn_index).isdigit() else fallback_index
        label = str(item.get("label") or "").strip() or _evidence_label(case, source_id)
        normalized.append(
            {
                "turn_index": turn_index,
                "action_type": action_type,
                "source_id": source_id,
                "label": label,
            }
        )
    return sorted(normalized, key=lambda item: int(item["turn_index"]))


def _build_action_order_summary(
    action_timeline: list[dict[str, Any]],
    problem_representation: Mapping[str, Any],
) -> dict[str, Any]:
    first_history_index = _first_action_index(action_timeline, {"history_fact_revealed"})
    first_exam_index = _first_action_index(action_timeline, {"physical_exam_requested"})
    first_test_index = _first_action_index(action_timeline, {"auxiliary_test_requested"})
    first_submission_index = _first_action_index(action_timeline, {"diagnosis_submitted"})
    history_before_test_count = 0
    if first_test_index is not None:
        history_before_test_count = sum(
            1
            for item in action_timeline
            if item.get("action_type") == "history_fact_revealed" and int(item.get("turn_index", 0)) < first_test_index
        )
    return {
        "first_history_fact_turn_index": first_history_index,
        "first_physical_exam_turn_index": first_exam_index,
        "first_auxiliary_test_turn_index": first_test_index,
        "diagnosis_submission_turn_index": first_submission_index,
        "history_fact_count_before_first_test": history_before_test_count,
        "problem_representation_coverage_ratio": float(problem_representation.get("coverage_ratio") or 0.0),
    }


def _first_action_index(action_timeline: list[dict[str, Any]], action_types: set[str]) -> int | None:
    indexes = [
        int(item["turn_index"])
        for item in action_timeline
        if str(item.get("action_type")) in action_types and str(item.get("turn_index", "")).isdigit()
    ]
    return min(indexes) if indexes else None


def _build_evidence_chain_breakpoints(
    case: Case,
    illness_script_alignment: Mapping[str, Any],
) -> list[dict[str, Any]]:
    breakpoints: list[dict[str, Any]] = []
    for element in illness_script_alignment.get("script_elements", []):
        if not isinstance(element, Mapping) or element.get("status") == "covered":
            continue
        missing_evidence = _string_list(element.get("missing_evidence"))
        covered_evidence = _string_list(element.get("covered_evidence"))
        if not missing_evidence:
            continue
        kind = _normalized_reasoning_kind(str(element.get("kind") or ""))
        missing_labels = [_evidence_label(case, evidence_id) for evidence_id in missing_evidence]
        covered_labels = [_evidence_label(case, evidence_id) for evidence_id in covered_evidence]
        breakpoints.append(
            {
                "breakpoint_id": str(element.get("point_id") or ""),
                "statement": str(element.get("statement") or ""),
                "kind": kind,
                "status": str(element.get("status") or "missing"),
                "covered_evidence": covered_evidence,
                "covered_evidence_labels": covered_labels,
                "missing_evidence": missing_evidence,
                "missing_evidence_labels": missing_labels,
                "teacher_action": _teacher_action_for_breakpoint(kind, missing_labels),
            }
        )
    return breakpoints


def _build_hypothesis_testing(
    *,
    requested_exams: set[str],
    requested_tests: set[str],
    final_submission: Mapping[str, Any] | None,
    student_hypotheses: list[str],
    action_order_summary: Mapping[str, Any],
) -> dict[str, Any]:
    sequence_flags: list[dict[str, Any]] = []
    first_test_index = _int_or_none(action_order_summary.get("first_auxiliary_test_turn_index"))
    first_exam_index = _int_or_none(action_order_summary.get("first_physical_exam_turn_index"))
    if requested_tests and not requested_exams:
        sequence_flags.append(
            {
                "flag_id": "premature_testing_before_exam",
                "label": PATTERN_DEFINITIONS["premature_testing_before_exam"]["label"],
                "severity": "medium",
                "evidence": "本轮已经申请辅助检查，但尚未记录关键查体。",
            }
        )
    elif first_test_index is not None and first_exam_index is not None and first_test_index < first_exam_index:
        sequence_flags.append(
            {
                "flag_id": "premature_testing_before_exam",
                "label": PATTERN_DEFINITIONS["premature_testing_before_exam"]["label"],
                "severity": "medium",
                "evidence": "本轮先申请辅助检查，随后才记录关键查体，验证顺序偏检查驱动。",
            }
        )
    prior_hypotheses = _prior_hypotheses(student_hypotheses, final_submission)
    if final_submission and not prior_hypotheses:
        sequence_flags.append(
            {
                "flag_id": "delayed_hypothesis_generation",
                "label": PATTERN_DEFINITIONS["delayed_hypothesis_generation"]["label"],
                "severity": "medium",
                "evidence": "训练记录中未看到提交诊断前形成过明确诊断假设。",
            }
        )
    if requested_tests and not prior_hypotheses:
        evidence_seeking_style = "checklist_or_test_driven"
    elif prior_hypotheses:
        evidence_seeking_style = "hypothesis_directed"
    else:
        evidence_seeking_style = "exploratory"
    return {
        "status": "needs_attention" if sequence_flags else "organized",
        "evidence_seeking_style": evidence_seeking_style,
        "sequence_flags": sequence_flags,
        "prior_hypotheses": prior_hypotheses,
    }


def _prior_hypotheses(student_hypotheses: list[str], final_submission: Mapping[str, Any] | None) -> list[str]:
    final_diagnosis = str((final_submission or {}).get("diagnosis") or "").strip()
    prior: list[str] = []
    for hypothesis in student_hypotheses:
        normalized = hypothesis.strip()
        if not normalized:
            continue
        if final_diagnosis and normalized == final_diagnosis:
            continue
        prior.append(normalized)
    return prior


def _build_differential_reasoning(
    *,
    case: Case,
    report: Mapping[str, Any],
    final_submission: Mapping[str, Any] | None,
    student_hypotheses: list[str],
) -> dict[str, Any]:
    submitted_text = " ".join(
        [
            str((final_submission or {}).get("diagnosis") or ""),
            str((final_submission or {}).get("reasoning") or ""),
            *student_hypotheses,
        ]
    ).lower()
    expected = []
    mentioned_count = 0
    for differential in case.diagnosis.differential_diagnoses:
        disease_name = differential.disease_name
        mentioned = bool(disease_name and disease_name.lower() in submitted_text)
        if mentioned:
            mentioned_count += 1
        expected.append(
            {
                "disease_name": disease_name,
                "expected_action": differential.expected_action,
                "key_distinction": differential.key_distinction,
                "status": "mentioned" if mentioned else "not_mentioned",
            }
        )
    differential_score = _dimension_score(report, "differential_diagnosis")
    status = "broad" if mentioned_count else "thin"
    if differential_score > 0 and mentioned_count:
        status = "developing"
    return {
        "status": status,
        "mentioned_count": mentioned_count,
        "expected_count": len(expected),
        "expected_differentials": expected,
        "dimension_score": differential_score,
    }


def _build_evidence_synthesis(
    *,
    report: Mapping[str, Any],
    illness_script_alignment: Mapping[str, Any],
    final_submission: Mapping[str, Any] | None,
) -> dict[str, Any]:
    reasoning_score = _dimension_score(report, "reasoning")
    coverage_ratio = float(illness_script_alignment.get("coverage_ratio") or 0.0)
    status = "strong" if coverage_ratio >= 0.75 and reasoning_score > 0 else "developing"
    if final_submission and (coverage_ratio < 0.45 or reasoning_score <= 0):
        status = "weak"
    return {
        "status": status,
        "reasoning_dimension_score": reasoning_score,
        "script_coverage_ratio": round(coverage_ratio, 4),
    }


def _build_cognitive_patterns(
    *,
    problem_representation: Mapping[str, Any],
    hypothesis_testing: Mapping[str, Any],
    differential_reasoning: Mapping[str, Any],
    evidence_synthesis: Mapping[str, Any],
    evidence_chain_breakpoints: list[dict[str, Any]],
    final_submission: Mapping[str, Any] | None,
    report: Mapping[str, Any],
) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []
    if problem_representation.get("status") in {"weak", "developing"}:
        missing = problem_representation.get("missing_semantic_qualifiers", [])
        source_signals = _source_signals_from_qualifiers(missing)
        labels = _dedupe(_labels_from_items(missing))[:4]
        remediation = PATTERN_DEFINITIONS["weak_problem_representation"]["remediation"]
        if labels:
            remediation = (
                "下一轮先用开放式问题确认主诉和病程，再依次完成："
                f"{_compact(labels, fallback='本病例的关键病史训练点')}；用一句话概括后再进入查体和检查。"
            )
        patterns.append(
            _pattern(
                "weak_problem_representation",
                severity="high" if final_submission and problem_representation.get("status") == "weak" else "medium",
                evidence=f"问题表征缺少{_compact(labels, fallback='关键病史语义要素')}。",
                source_signal_ids=source_signals,
                remediation=remediation,
                focus_labels=labels,
            )
        )
    flag_ids = {str(flag.get("flag_id")) for flag in hypothesis_testing.get("sequence_flags", []) if isinstance(flag, dict)}
    if "premature_testing_before_exam" in flag_ids:
        patterns.append(
            _pattern(
                "premature_testing_before_exam",
                severity="medium",
                evidence="辅助检查已经启动，但查体证据尚未形成完整中间环节。",
                source_signal_ids=["event:auxiliary_test_requested", "sequence:before_physical_exam"],
            )
        )
    if "delayed_hypothesis_generation" in flag_ids:
        patterns.append(
            _pattern(
                "delayed_hypothesis_generation",
                severity="medium",
                evidence="未看到提交诊断前的阶段性假设，诊断更像最终填写而非边验证边推进。",
                source_signal_ids=["event:diagnosis_submitted"],
            )
        )
    missed_item_set = {str(item) for item in report.get("missed_items", []) if str(item)}
    if final_submission and differential_reasoning.get("status") == "thin":
        patterns.append(
            _pattern(
                "thin_differential_reasoning",
                severity="high" if _dimension_score(report, "differential_diagnosis") <= 0 else "medium",
                evidence="提交内容未充分呈现相近诊断的支持或排除依据。",
                source_signal_ids=sorted(item for item in missed_item_set if item.startswith(("dxd_", "diff_", "rs_"))),
            )
        )
    if final_submission and evidence_synthesis.get("status") in {"weak", "developing"}:
        breakpoint_sources = [
            evidence_id
            for breakpoint in evidence_chain_breakpoints
            for evidence_id in _string_list(breakpoint.get("missing_evidence"))
        ]
        patterns.append(
            _pattern(
                "weak_evidence_synthesis",
                severity="high" if evidence_synthesis.get("status") == "weak" else "medium",
                evidence="已收集线索尚未充分整理为支持、排除和仍需验证的证据链。",
                source_signal_ids=[
                    *sorted(item for item in missed_item_set if item.startswith(("rs_", "dxd_", "dx_"))),
                    *breakpoint_sources,
                ],
            )
        )
    pattern_ids = {pattern["pattern_id"] for pattern in patterns}
    if final_submission and {"weak_problem_representation", "thin_differential_reasoning"} <= pattern_ids:
        patterns.append(
            _pattern(
                "premature_closure_risk",
                severity="medium",
                evidence="问题表征和鉴别排除均不充分时已经提交结论，存在过早闭合训练风险。",
                source_signal_ids=["event:diagnosis_submitted"],
            )
        )
    return patterns


def _pattern(
    pattern_id: str,
    *,
    severity: str,
    evidence: str,
    source_signal_ids: list[str],
    remediation: str | None = None,
    focus_labels: list[str] | None = None,
) -> dict[str, Any]:
    definition = PATTERN_DEFINITIONS[pattern_id]
    pattern = {
        "pattern_id": pattern_id,
        "label": definition["label"],
        "category": definition["category"],
        "severity": severity,
        "evidence": evidence,
        "why_it_matters": definition["why"],
        "remediation": remediation or definition["remediation"],
        "source_signal_ids": _dedupe(source_signal_ids),
        "trigger_item_ids": [item for item in _dedupe(source_signal_ids) if _is_training_item_id(item)],
    }
    if focus_labels:
        pattern["focus_labels"] = _dedupe(focus_labels)[:4]
    return pattern


def _teacher_focus_questions(patterns: list[dict[str, Any]]) -> list[str]:
    questions: list[str] = []
    for pattern in patterns[:4]:
        pattern_id = str(pattern.get("pattern_id") or "")
        if pattern_id == "weak_problem_representation":
            focus = _compact(
                _string_list(pattern.get("focus_labels")),
                fallback="起病与进展、核心症状、伴随信息和相关阴性信息",
            )
            questions.append(f"你现在能围绕以下关键点用一句话概括患者吗：{focus}？")
        elif pattern_id == "premature_testing_before_exam":
            questions.append("在申请检查前，哪一个查体结果会最直接改变你的判断？")
        elif pattern_id == "thin_differential_reasoning":
            questions.append("除了当前主诊断，你还需要排除哪一个相近可能？依据是什么？")
        elif pattern_id == "weak_evidence_synthesis":
            questions.append("你能把现有证据分成支持、排除和仍需验证三类吗？")
        else:
            questions.append(f"针对“{pattern.get('label', '本轮问题')}”，下一轮你准备先验证哪一条证据？")
    return questions


def _student_visible_summary(patterns: list[dict[str, Any]]) -> str:
    if not patterns:
        return "本轮训练未形成明显临床思维模式风险，后续可继续练习证据表达和迁移训练。"
    labels = [str(pattern.get("label")) for pattern in patterns[:3] if pattern.get("label")]
    return f"本轮主要思维问题集中在：{'、'.join(labels)}。"


def _source_signals_from_qualifiers(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    source_signals: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        linked = item.get("linked_rubric_items")
        if isinstance(linked, list):
            source_signals.extend(str(link).strip() for link in linked if str(link).strip())
        fact_id = str(item.get("fact_id") or "").strip()
        if fact_id:
            source_signals.append(fact_id)
    return _dedupe(source_signals)


def _labels_from_items(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    return [str(item.get("label")).strip() for item in items if isinstance(item, Mapping) and str(item.get("label", "")).strip()]


def _dimension_score(report: Mapping[str, Any], dimension_id: str) -> float:
    dimension_scores = report.get("dimension_scores")
    if isinstance(dimension_scores, Mapping):
        value = dimension_scores.get(dimension_id)
        if isinstance(value, (int, float)):
            return float(value)
    rubric_scores = report.get("rubric_scores")
    if isinstance(rubric_scores, Mapping):
        return float(
            sum(
                float(item.get("score", 0))
                for item in rubric_scores.values()
                if isinstance(item, Mapping) and str(item.get("dimension_id")) == dimension_id
            )
        )
    return 0.0


def _coverage_status(coverage_ratio: float, *, weak_threshold: float, strong_threshold: float) -> str:
    if coverage_ratio >= strong_threshold:
        return "strong"
    if coverage_ratio >= weak_threshold:
        return "developing"
    return "weak"


def _compact(items: list[str], *, fallback: str, limit: int = 4) -> str:
    clean_items = _dedupe([item for item in items if item])
    if not clean_items:
        return fallback
    suffix = f"等 {len(clean_items)} 项" if len(clean_items) > limit else ""
    return "、".join(clean_items[:limit]) + suffix


def _get(container: Any, key: str, default: Any = None) -> Any:
    if isinstance(container, Mapping):
        return container.get(key, default)
    return getattr(container, key, default)


def _mapping_or_none(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (str(raw).strip() for raw in value) if item]


def _timeline_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _evidence_label(case: Case, evidence_id: str) -> str:
    if not evidence_id:
        return ""
    for fact in case.history.hidden_facts:
        if fact.fact_id == evidence_id:
            labels = rubric_item_labels(fact.linked_rubric_items[:1], [case.case_id]) if fact.linked_rubric_items else []
            return labels[0] if labels else HISTORY_SLOT_LABELS.get(str(fact.slot or ""), fact.topic)
    for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]:
        if exam.exam_code == evidence_id:
            return exam.exam_name_cn
    for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]:
        if test.test_code == evidence_id:
            return test.test_name_cn
    for point in case.diagnosis.reasoning_points:
        if point.point_id == evidence_id:
            return point.statement
    return evidence_id


def _normalized_reasoning_kind(kind: str) -> str:
    if kind == "支持":
        return "support"
    if kind == "排除":
        return "exclude"
    if kind == "鉴别":
        return "differentiate"
    return "risk"


def _teacher_action_for_breakpoint(kind: str, missing_labels: list[str]) -> str:
    focus = _compact(missing_labels, fallback="关键证据")
    if kind == "support":
        return f"先补齐{focus}，再说明这些证据如何支持当前诊断假设。"
    if kind == "exclude":
        return f"先补齐{focus}，再说明这些证据如何排除相近诊断。"
    if kind == "differentiate":
        return f"围绕{focus}比较相近诊断，避免只给出单一结论。"
    return f"围绕{focus}确认风险线索，并说明下一步验证方向。"


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        normalized = str(item).strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _is_training_item_id(value: str) -> bool:
    if not value or ":" in value or "." in value:
        return False
    return bool(rubric_item_label(value, ()))


def pattern_counts_from_reports(reports: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    pattern_by_id: dict[str, dict[str, Any]] = {}
    for report in reports:
        trace = report.get("clinical_reasoning_trace")
        if not isinstance(trace, Mapping):
            continue
        for pattern in trace.get("cognitive_patterns", []):
            if not isinstance(pattern, Mapping):
                continue
            pattern_id = str(pattern.get("pattern_id") or "").strip()
            if not pattern_id:
                continue
            counter[pattern_id] += 1
            pattern_by_id.setdefault(
                pattern_id,
                {
                    "pattern_id": pattern_id,
                    "label": str(pattern.get("label") or pattern_id),
                    "category": str(pattern.get("category") or "clinical_reasoning"),
                    "severity": str(pattern.get("severity") or "medium"),
                },
            )
    return [
        {
            **pattern_by_id[pattern_id],
            "count": count,
        }
        for pattern_id, count in counter.most_common()
    ]


def sequence_flags_from_report(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    trace = report.get("clinical_reasoning_trace")
    if not isinstance(trace, Mapping):
        return []
    hypothesis_testing = trace.get("hypothesis_testing")
    if not isinstance(hypothesis_testing, Mapping):
        return []
    flags: list[dict[str, Any]] = []
    for flag in _mapping_list(hypothesis_testing.get("sequence_flags")):
        flag_id = str(flag.get("flag_id") or "").strip()
        if not flag_id:
            continue
        flags.append(
            {
                "flag_id": flag_id,
                "label": str(flag.get("label") or flag_id),
                "severity": str(flag.get("severity") or "medium"),
                "evidence": str(flag.get("evidence") or ""),
            }
        )
    return flags


def action_order_summary_from_report(report: Mapping[str, Any]) -> dict[str, Any]:
    trace = report.get("clinical_reasoning_trace")
    if not isinstance(trace, Mapping):
        return {}
    action_order_summary = trace.get("action_order_summary")
    if not isinstance(action_order_summary, Mapping):
        return {}
    return {
        "first_history_turn_index": _int_or_none(action_order_summary.get("first_history_turn_index")),
        "first_physical_exam_turn_index": _int_or_none(action_order_summary.get("first_physical_exam_turn_index")),
        "first_auxiliary_test_turn_index": _int_or_none(action_order_summary.get("first_auxiliary_test_turn_index")),
        "first_diagnosis_hypothesis_turn_index": _int_or_none(
            action_order_summary.get("first_diagnosis_hypothesis_turn_index")
        ),
        "diagnosis_submission_turn_index": _int_or_none(action_order_summary.get("diagnosis_submission_turn_index")),
    }


def evidence_chain_breakpoints_from_report(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    trace = report.get("clinical_reasoning_trace")
    if not isinstance(trace, Mapping):
        return []
    breakpoints: list[dict[str, Any]] = []
    for breakpoint in _mapping_list(trace.get("evidence_chain_breakpoints")):
        statement = str(breakpoint.get("statement") or "").strip()
        breakpoint_id = str(breakpoint.get("breakpoint_id") or statement).strip()
        if not breakpoint_id and not statement:
            continue
        breakpoints.append(
            {
                "breakpoint_id": breakpoint_id or statement,
                "statement": statement or breakpoint_id,
                "kind": str(breakpoint.get("kind") or "support"),
                "status": str(breakpoint.get("status") or "broken"),
                "missing_evidence": _string_list(breakpoint.get("missing_evidence")),
                "missing_evidence_labels": _string_list(breakpoint.get("missing_evidence_labels")),
                "teacher_action": str(breakpoint.get("teacher_action") or ""),
            }
        )
    return breakpoints


def sequence_issue_counts_from_reports(
    reports: list[Mapping[str, Any]],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    flag_by_id: dict[str, dict[str, Any]] = {}
    for report in reports:
        seen_in_report: set[str] = set()
        for flag in sequence_flags_from_report(report):
            flag_id = str(flag.get("flag_id") or "").strip()
            if not flag_id or flag_id in seen_in_report:
                continue
            seen_in_report.add(flag_id)
            counter[flag_id] += 1
            flag_by_id.setdefault(
                flag_id,
                {
                    "flag_id": flag_id,
                    "label": str(flag.get("label") or flag_id),
                    "severity": str(flag.get("severity") or "medium"),
                    "evidence_examples": [],
                },
            )
            evidence = str(flag.get("evidence") or "").strip()
            examples = flag_by_id[flag_id]["evidence_examples"]
            if evidence and evidence not in examples:
                examples.append(evidence)
    return [
        {
            **flag_by_id[flag_id],
            "evidence_examples": flag_by_id[flag_id]["evidence_examples"][:3],
            "count": count,
        }
        for flag_id, count in counter.most_common(limit)
    ]


def evidence_chain_focus_from_reports(
    reports: list[Mapping[str, Any]],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    breakpoint_by_id: dict[str, dict[str, Any]] = {}
    for report in reports:
        seen_in_report: set[str] = set()
        for breakpoint in evidence_chain_breakpoints_from_report(report):
            breakpoint_id = str(breakpoint.get("breakpoint_id") or breakpoint.get("statement") or "").strip()
            if not breakpoint_id or breakpoint_id in seen_in_report:
                continue
            seen_in_report.add(breakpoint_id)
            counter[breakpoint_id] += 1
            item = breakpoint_by_id.setdefault(
                breakpoint_id,
                {
                    "breakpoint_id": breakpoint_id,
                    "statement": str(breakpoint.get("statement") or breakpoint_id),
                    "kind": str(breakpoint.get("kind") or "support"),
                    "status": str(breakpoint.get("status") or "broken"),
                    "missing_evidence": [],
                    "missing_evidence_labels": [],
                    "teacher_action": str(breakpoint.get("teacher_action") or ""),
                },
            )
            item["missing_evidence"] = _dedupe(
                [*item["missing_evidence"], *_string_list(breakpoint.get("missing_evidence"))]
            )
            item["missing_evidence_labels"] = _dedupe(
                [*item["missing_evidence_labels"], *_string_list(breakpoint.get("missing_evidence_labels"))]
            )
            if not item["teacher_action"] and breakpoint.get("teacher_action"):
                item["teacher_action"] = str(breakpoint.get("teacher_action") or "")
    return [
        {
            **breakpoint_by_id[breakpoint_id],
            "missing_evidence": breakpoint_by_id[breakpoint_id]["missing_evidence"][:8],
            "missing_evidence_labels": breakpoint_by_id[breakpoint_id]["missing_evidence_labels"][:8],
            "count": count,
        }
        for breakpoint_id, count in counter.most_common(limit)
    ]
