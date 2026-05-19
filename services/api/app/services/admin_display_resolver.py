from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"
RUBRICS_DIR = ROOT_DIR / "data" / "rubrics"
SOURCE_REGISTRY_PATH = ROOT_DIR / "data" / "attribution" / "source_registry" / "sources.json"


STAGE_LABELS: dict[str, str] = {
    "case_intro": "病例导入",
    "history": "问诊中",
    "physical_exam": "查体中",
    "auxiliary_test": "检查申请中",
    "diagnosis": "诊断整理中",
    "diagnosis_submission": "诊断已提交",
    "diagnosis_submitted": "诊断已提交",
    "feedback": "报告已生成",
    "report_ready": "报告已生成",
}

PATTERN_TYPE_LABELS: dict[str, str] = {
    "off_topic_redirect": "偏题/寒暄回到问诊目标",
    "premature_answer_request": "过早索要答案",
    "safety_boundary_request": "触发真实诊疗边界",
    "exam_before_history": "未完成病史先查体",
    "test_before_history": "未完成病史先申请检查",
    "auxiliary_test_before_physical_exam": "跳过查体直接申请辅助检查",
}

TRIGGER_ITEM_LABELS: dict[str, str] = {
    "turn_intent:unknown_history_intent": "未命中明确病史意图",
    "turn_policy:patient_context_redirect": "引导回患者上下文",
    "turn_intent:answer_request_redirect": "索要答案或诊断结论",
    "turn_policy:answer_boundary_redirect": "阻止直接给出答案",
    "turn_intent:safety_boundary": "真实诊疗边界请求",
    "turn_policy:safety_boundary_redirect": "安全边界重定向",
    "event:physical_exam_requested": "请求查体",
    "event:auxiliary_test_requested": "申请辅助检查",
    "sequence:before_history_fact_disclosure": "发生在核心病史披露前",
    "sequence:before_physical_exam": "发生在查体前",
}

BATCH_LABELS: dict[str, str] = {
    "batch_smoke": "冒烟评测批次",
    "batch_regression": "回归评测批次",
    "admin_skill_candidate_generation_smoke": "Skill 候选生成评测",
}


def case_title(case_id: str) -> str:
    normalized_case_id = str(case_id or "").strip()
    if not normalized_case_id:
        return "全局知识库"
    case_payload = _load_case_payload(normalized_case_id)
    title = case_payload.get("case_title") if isinstance(case_payload, dict) else None
    return title if isinstance(title, str) and title.strip() else normalized_case_id


def case_titles(case_ids: Iterable[str]) -> list[str]:
    return [case_title(case_id) for case_id in case_ids]


def source_title(source_id: str) -> str:
    normalized_source_id = str(source_id or "").strip()
    if not normalized_source_id:
        return "未绑定来源"
    source = _source_registry_map().get(normalized_source_id)
    if source is None:
        return normalized_source_id
    title = source.get("source_name")
    return title if isinstance(title, str) and title.strip() else normalized_source_id


def stage_label(stage: str) -> str:
    return STAGE_LABELS.get(str(stage or ""), str(stage or "") or "未知阶段")


def pattern_type_label(pattern_type: str) -> str:
    return PATTERN_TYPE_LABELS.get(str(pattern_type or ""), str(pattern_type or "") or "未分类模式")


def trigger_item_label(trigger_item_id: str, case_ids: Iterable[str] = ()) -> str:
    normalized_trigger = str(trigger_item_id or "").strip()
    if not normalized_trigger:
        return "未记录触发项"
    if normalized_trigger in TRIGGER_ITEM_LABELS:
        return TRIGGER_ITEM_LABELS[normalized_trigger]
    return rubric_item_label(normalized_trigger, case_ids)


def trigger_item_labels(trigger_item_ids: Iterable[str], case_ids: Iterable[str] = ()) -> list[str]:
    case_id_list = list(case_ids)
    return [trigger_item_label(item_id, case_id_list) for item_id in trigger_item_ids]


def rubric_item_label(item_id: str, case_ids: Iterable[str] = ()) -> str:
    normalized_item_id = str(item_id or "").strip()
    if not normalized_item_id:
        return "未记录评分项"
    case_id_list = [str(case_id) for case_id in case_ids if str(case_id)]
    labels: list[str] = []
    for case_id in case_id_list:
        label = _rubric_item_label_for_case(case_id, normalized_item_id)
        if label and label not in labels:
            labels.append(label)
    if case_id_list:
        return " / ".join(labels) if labels else normalized_item_id
    if labels:
        return " / ".join(labels)
    for rubric_path in sorted(RUBRICS_DIR.glob("*.yaml")):
        rubric_case_id = rubric_path.stem.removesuffix("_rubric")
        label = _rubric_item_label_for_case(rubric_case_id, normalized_item_id)
        if label and label not in labels:
            labels.append(label)
    return " / ".join(labels) if labels else normalized_item_id


def rubric_item_labels(item_ids: Iterable[str], case_ids: Iterable[str] = ()) -> list[str]:
    case_id_list = list(case_ids)
    return [rubric_item_label(item_id, case_id_list) for item_id in item_ids]


def batch_label(batch_id: str) -> str:
    normalized_batch_id = str(batch_id or "").strip()
    if normalized_batch_id in BATCH_LABELS:
        return BATCH_LABELS[normalized_batch_id]
    if normalized_batch_id.startswith("admin_manual_"):
        suffix = normalized_batch_id.removeprefix("admin_manual_")
        if suffix.isdigit():
            timestamp = datetime.fromtimestamp(int(suffix) / 1000)
            return f"手动系统评测 · {timestamp:%Y-%m-%d %H:%M}"
        return "手动系统评测"
    if "regression" in normalized_batch_id:
        return "回归评测批次"
    if "smoke" in normalized_batch_id:
        return "冒烟评测批次"
    return "系统评测批次" if normalized_batch_id else "未命名评测批次"


def enrich_training_insight_missed_item(item: dict[str, Any]) -> dict[str, Any]:
    case_ids = [str(case_id) for case_id in item.get("case_ids", [])]
    return {
        **item,
        "item_label": rubric_item_label(str(item.get("item_id", "")), case_ids),
        "case_titles": case_titles(case_ids),
    }


def enrich_training_insight_source_reference(item: dict[str, Any]) -> dict[str, Any]:
    case_ids = [str(case_id) for case_id in item.get("case_ids", [])]
    return {**item, "case_titles": case_titles(case_ids)}


def enrich_training_insight_turn_pattern(pattern: dict[str, Any]) -> dict[str, Any]:
    case_ids = [str(case_id) for case_id in pattern.get("case_ids", [])]
    trigger_ids = [str(item_id) for item_id in pattern.get("trigger_item_ids", [])]
    return {
        **pattern,
        "pattern_type_label": pattern_type_label(str(pattern.get("pattern_type", ""))),
        "trigger_item_labels": trigger_item_labels(trigger_ids, case_ids),
        "case_titles": case_titles(case_ids),
    }


def enrich_session_summary(session: dict[str, Any]) -> dict[str, Any]:
    return {
        **session,
        "case_title": case_title(str(session.get("case_id", ""))),
        "stage_label": stage_label(str(session.get("stage", ""))),
    }


def enrich_report(report: dict[str, Any]) -> dict[str, Any]:
    case_id = str(report.get("case_id", ""))
    missed_items = [str(item_id) for item_id in report.get("missed_items", [])]
    return {
        **report,
        "case_title": case_title(case_id),
        "missed_item_labels": rubric_item_labels(missed_items, [case_id]),
    }


def enrich_rag_knowledge_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "case_title": case_title(str(item.get("case_id", ""))),
        "source_title": source_title(str(item.get("source_id", ""))),
    }


def enrich_rag_document(document: dict[str, Any]) -> dict[str, Any]:
    return {
        **document,
        "case_title": case_title(str(document.get("case_id", ""))),
        "source_title": source_title(str(document.get("source_id", ""))),
    }


@lru_cache(maxsize=128)
def _load_case_payload(case_id: str) -> dict[str, Any]:
    case_path = CASES_DIR / f"{case_id}.json"
    if not case_path.exists():
        return {}
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=128)
def _load_rubric_payload(case_id: str) -> dict[str, Any]:
    rubric_path = RUBRICS_DIR / f"{case_id}_rubric.yaml"
    if not rubric_path.exists():
        return {}
    payload = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=128)
def _rubric_item_label_for_case(case_id: str, item_id: str) -> str:
    rubric = _load_rubric_payload(case_id)
    for dimension in rubric.get("dimensions", []):
        if not isinstance(dimension, dict):
            continue
        for item in dimension.get("items", []):
            if not isinstance(item, dict) or item.get("item_id") != item_id:
                continue
            description = item.get("description")
            return description if isinstance(description, str) and description.strip() else item_id
    return ""


@lru_cache(maxsize=1)
def _source_registry_map() -> dict[str, dict[str, Any]]:
    if not SOURCE_REGISTRY_PATH.exists():
        return {}
    payload = json.loads(SOURCE_REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return {}
    sources: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        source_id = item.get("source_id")
        if isinstance(source_id, str) and source_id.strip():
            sources[source_id] = item
    return sources
