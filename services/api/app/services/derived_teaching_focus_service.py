from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.models.case import Case
from app.services.focus_sanitizer import assert_student_safe_focus_payload
from app.services.osce_session_service import OsceSession, load_case_node

ROOT_DIR = Path(__file__).resolve().parents[4]
RUBRICS_DIR = ROOT_DIR / "data" / "rubrics"

FOCUS_DIMENSION_ORDER = [
    "history_taking",
    "physical_exam",
    "auxiliary_test",
    "differential_diagnosis",
    "reasoning",
]

FOCUS_DIMENSION_LABELS = {
    "history_taking": "病史采集",
    "physical_exam": "查体选择",
    "auxiliary_test": "辅助检查",
    "differential_diagnosis": "鉴别诊断",
    "reasoning": "推理链表达",
}

FOCUS_TRAINING_SUGGESTIONS = {
    "history_taking": "优先用开放式问题补齐起病、部位或放射、性质、程度、伴随症状和相关背景。",
    "physical_exam": "选择与当前主诉匹配的基础生命体征和重点系统查体，用查体结果验证已收集线索。",
    "auxiliary_test": "申请能验证当前假设并排除高风险鉴别的基础检查，避免只凭单一线索结束训练。",
    "differential_diagnosis": "在提交前保留至少两个鉴别方向，并说明支持或排除依据。",
    "reasoning": "把已问到的病史、查体和检查证据串成支持证据与排除依据。",
}


def build_case_baseline_focus(case_id: str) -> dict[str, Any]:
    case = load_case_node(case_id)
    rubric = _load_rubric(case_id)
    patterns = [
        _build_focus_pattern(
            case=case,
            dimension_id=dimension_id,
            item_ids=_rubric_item_ids_for_dimension(rubric, dimension_id),
            scope="case_baseline",
            source_report_count=0,
            why_now="病例开始前根据病例结构与 rubric 生成，不依赖单个演示脚本。",
        )
        for dimension_id in FOCUS_DIMENSION_ORDER
        if _rubric_item_ids_for_dimension(rubric, dimension_id)
    ]
    payload = {"case_id": case.case_id, "scope": "case_baseline", "patterns": patterns}
    assert_student_safe_focus_payload(payload, case)
    return payload


def build_session_teaching_focus(session: OsceSession) -> dict[str, Any]:
    case = load_case_node(session.case_id)
    rubric = _load_rubric(session.case_id)
    next_dimension = _next_runtime_dimension(session)
    item_ids = _rubric_item_ids_for_dimension(rubric, next_dimension)
    if not item_ids:
        item_ids = [item_id for dimension_id in FOCUS_DIMENSION_ORDER for item_id in _rubric_item_ids_for_dimension(rubric, dimension_id)]
    patterns = [
        _build_focus_pattern(
            case=case,
            dimension_id=next_dimension,
            item_ids=item_ids,
            scope="session_runtime",
            source_report_count=0,
            why_now=_runtime_reason(session, next_dimension),
        )
    ]
    payload = {
        "case_id": case.case_id,
        "session_id": session.session_id,
        "scope": "session_runtime",
        "patterns": patterns,
    }
    assert_student_safe_focus_payload(payload, case)
    return payload


def build_admin_teaching_focus_patterns(case_ids: list[str] | None = None) -> list[dict[str, Any]]:
    effective_case_ids = case_ids or sorted(path.stem for path in (ROOT_DIR / "data" / "cases").glob("*.json"))
    patterns: list[dict[str, Any]] = []
    for case_id in effective_case_ids:
        patterns.extend(build_case_baseline_focus(case_id)["patterns"])
    return patterns


def get_admin_teaching_focus_pattern(focus_id: str) -> dict[str, Any] | None:
    for pattern in build_admin_teaching_focus_patterns():
        if pattern["focus_id"] == focus_id:
            return pattern
    return None


def _load_rubric(case_id: str) -> dict[str, Any]:
    return yaml.safe_load((RUBRICS_DIR / f"{case_id}_rubric.yaml").read_text(encoding="utf-8"))


def _rubric_item_ids_for_dimension(rubric: dict[str, Any], dimension_id: str) -> list[str]:
    for dimension in rubric.get("dimensions", []):
        if dimension.get("dimension_id") == dimension_id:
            return [str(item["item_id"]) for item in dimension.get("items", [])]
    return []


def _build_focus_pattern(
    *,
    case: Case,
    dimension_id: str,
    item_ids: list[str],
    scope: str,
    source_report_count: int,
    why_now: str,
) -> dict[str, Any]:
    title = f"{case.course_module}病例{FOCUS_DIMENSION_LABELS[dimension_id]}训练重点"
    pattern = f"{dimension_id}_bundle"
    return {
        "focus_id": f"{scope}:{case.case_id}:{dimension_id}",
        "scope": scope,
        "pattern": pattern,
        "title": title,
        "description": f"围绕{case.course_module}主诉，覆盖{FOCUS_DIMENSION_LABELS[dimension_id]}相关 rubric 项，避免过早跳到答案。",
        "training_suggestion": FOCUS_TRAINING_SUGGESTIONS[dimension_id],
        "trigger_item_ids": item_ids,
        "case_ids": [case.case_id],
        "support_count": len(item_ids),
        "source_report_count": source_report_count,
        "source_reference_ids": [f"rubric:{case.rubric_ref.rubric_id}.item.{item_id}" for item_id in item_ids],
        "severity": _severity_for_item_count(len(item_ids)),
        "visibility_level": "student_safe",
        "why_now": why_now,
    }


def _severity_for_item_count(item_count: int) -> str:
    if item_count >= 3:
        return "high"
    if item_count == 2:
        return "medium"
    return "low"


def _next_runtime_dimension(session: OsceSession) -> str:
    if not session.revealed_facts:
        return "history_taking"
    if not session.requested_exams:
        return "physical_exam"
    if not session.requested_tests:
        return "auxiliary_test"
    if session.final_submission is None:
        return "reasoning"
    return "differential_diagnosis"


def _runtime_reason(session: OsceSession, dimension_id: str) -> str:
    if dimension_id == "history_taking":
        return "当前会话尚未披露关键病史，优先补齐问诊线索。"
    if dimension_id == "physical_exam":
        return "当前会话已有部分病史，但尚未记录查体。"
    if dimension_id == "auxiliary_test":
        return "当前会话已有病史或查体线索，但尚未记录辅助检查。"
    if dimension_id == "reasoning":
        return "当前会话已有多类证据，下一步应组织支持与排除依据。"
    return "当前会话已提交诊断，适合复盘鉴别诊断与推理边界。"
