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
    "history_taking": "问诊阶段",
    "physical_exam": "查体中",
    "auxiliary_test": "检查申请中",
    "auxiliary_testing": "检查申请阶段",
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

SKILL_TYPE_LABELS: dict[str, str] = {
    "conversation_repair": "对话纠偏训练",
    "workflow_sequencing": "训练流程顺序纠偏",
    "history_bundle": "病史采集训练",
    "exam_bundle": "查体选择训练",
    "test_strategy": "辅助检查策略训练",
    "reasoning_bridge": "证据链推理训练",
    "differential_broadening": "鉴别诊断拓展训练",
    "safety_boundary": "安全边界训练",
}

SKILL_STAGE_LABELS: dict[str, str] = {
    "case_intro": "训练开始",
    "history": "问诊阶段",
    "history_taking": "问诊阶段",
    "physical_exam": "查体阶段",
    "auxiliary_test": "辅助检查阶段",
    "auxiliary_testing": "辅助检查阶段",
    "diagnosis": "诊断整理阶段",
    "diagnosis_submission": "诊断提交前",
    "feedback": "复盘阶段",
    "feedback_review": "复盘阶段",
}

FOCUS_SCOPE_LABELS: dict[str, str] = {
    "case_baseline": "病例基础教学重点",
    "session_runtime": "当前会话教学重点",
}

FOCUS_SEVERITY_LABELS: dict[str, str] = {
    "high": "高优先级",
    "medium": "中等优先级",
    "low": "低优先级",
}

FOCUS_VISIBILITY_LABELS: dict[str, str] = {
    "student_safe": "学生可见",
    "admin_only": "仅管理员可见",
}

EFFECT_STATUS_LABELS: dict[str, str] = {
    "insufficient_samples": "样本不足",
    "improving": "观察到改善",
    "neutral": "效果待观察",
    "declining": "需要复核",
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

TRAINING_SKILL_ACTION_LABELS: dict[str, str] = {
    "hint_ladder": "分层提示",
    "reflection_prompt": "复盘引导",
}

LEGACY_ITEM_PREFIX_LABELS: dict[str, str] = {
    "dxd": "鉴别诊断",
    "ht": "病史采集",
    "pe": "查体",
    "rs": "推理表达",
    "at": "辅助检查",
}

LEGACY_ITEM_TOKEN_LABELS: dict[str, str] = {
    "allergy": "过敏史",
    "character": "疼痛性质",
    "crohn": "克罗恩病",
    "ectopic": "异位妊娠",
    "exclude": "排除依据",
    "ice": "患者想法、担忧与期望",
    "medical": "病史",
    "past": "既往",
    "severity": "程度",
    "urolith": "输尿管结石",
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


def reference_label(reference: str) -> str:
    normalized_reference = str(reference or "").strip()
    if not normalized_reference:
        return "未记录来源引用"
    rubric_reference = _parse_rubric_item_reference(normalized_reference)
    if rubric_reference is not None:
        case_id, item_id = rubric_reference
        label = _rubric_item_label_for_case(case_id, item_id)
        if label:
            return f"评分项：{label}"
        legacy_label = _legacy_item_label(item_id)
        if legacy_label:
            return f"评分项：{legacy_label}"
        return f"评分项：{case_title(case_id)} / {item_id}（当前 Rubric 未收录）"
    if normalized_reference.startswith("case:"):
        return f"病例：{case_title(normalized_reference.removeprefix('case:'))}"
    if normalized_reference.startswith("source:"):
        return f"来源：{source_title(normalized_reference.removeprefix('source:'))}"
    if normalized_reference.startswith("knowledge:"):
        knowledge_payload = normalized_reference.removeprefix("knowledge:")
        knowledge_case_id = knowledge_payload.split(".", maxsplit=1)[0]
        if knowledge_case_id:
            return f"知识条目：{case_title(knowledge_case_id)}"
        return "知识条目"
    if normalized_reference.startswith("rag_knowledge:"):
        return "教师知识库条目"
    return normalized_reference


def reference_labels(references: Iterable[str]) -> list[str]:
    return [reference_label(reference) for reference in references if str(reference).strip()]


def stage_label(stage: str) -> str:
    return STAGE_LABELS.get(str(stage or ""), str(stage or "") or "未知阶段")


def pattern_type_label(pattern_type: str) -> str:
    return PATTERN_TYPE_LABELS.get(str(pattern_type or ""), str(pattern_type or "") or "未分类模式")


def skill_type_label(skill_type: str) -> str:
    return SKILL_TYPE_LABELS.get(str(skill_type or ""), str(skill_type or "") or "未分类 Skill")


def effect_status_label(effect_status: str) -> str:
    return EFFECT_STATUS_LABELS.get(str(effect_status or ""), str(effect_status or "") or "未知效果状态")


def stage_scope_labels(stage_scope: Iterable[str]) -> list[str]:
    return [SKILL_STAGE_LABELS.get(str(stage or ""), str(stage or "") or "未知阶段") for stage in stage_scope]


def focus_scope_label(scope: str) -> str:
    return FOCUS_SCOPE_LABELS.get(str(scope or ""), str(scope or "") or "未记录范围")


def focus_severity_label(severity: str) -> str:
    return FOCUS_SEVERITY_LABELS.get(str(severity or ""), str(severity or "") or "未记录优先级")


def focus_visibility_label(visibility_level: str) -> str:
    return FOCUS_VISIBILITY_LABELS.get(str(visibility_level or ""), str(visibility_level or "") or "未记录可见性")


def training_skill_action_label(action_type: str) -> str:
    return TRAINING_SKILL_ACTION_LABELS.get(str(action_type or ""), str(action_type or "") or "未记录动作")


def trigger_item_label(trigger_item_id: str, case_ids: Iterable[str] = ()) -> str:
    normalized_trigger = str(trigger_item_id or "").strip()
    if not normalized_trigger:
        return "未记录触发项"
    if normalized_trigger in TRIGGER_ITEM_LABELS:
        return TRIGGER_ITEM_LABELS[normalized_trigger]
    case_id_list = list(case_ids)
    label = rubric_item_label(normalized_trigger, case_id_list)
    if case_id_list and label == normalized_trigger:
        return f"未收录评分项：{normalized_trigger}"
    return label


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
        if labels:
            return " / ".join(labels)
        legacy_label = _legacy_item_label(normalized_item_id)
        return legacy_label if legacy_label else normalized_item_id
    if labels:
        return " / ".join(labels)
    for rubric_path in sorted(RUBRICS_DIR.glob("*.yaml")):
        rubric_case_id = rubric_path.stem.removesuffix("_rubric")
        label = _rubric_item_label_for_case(rubric_case_id, normalized_item_id)
        if label and label not in labels:
            labels.append(label)
    if labels:
        return " / ".join(labels)
    legacy_label = _legacy_item_label(normalized_item_id)
    return legacy_label if legacy_label else normalized_item_id


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
    return {
        **item,
        "reference_label": reference_label(str(item.get("reference", ""))),
        "case_titles": case_titles(case_ids),
    }


def enrich_training_insight_learning_recommendation(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "reference_label": reference_label(str(item.get("reference", ""))),
    }


def enrich_training_insight_turn_pattern(pattern: dict[str, Any]) -> dict[str, Any]:
    case_ids = [str(case_id) for case_id in pattern.get("case_ids", [])]
    trigger_ids = [str(item_id) for item_id in pattern.get("trigger_item_ids", [])]
    return {
        **pattern,
        "pattern_type_label": pattern_type_label(str(pattern.get("pattern_type", ""))),
        "trigger_item_labels": trigger_item_labels(trigger_ids, case_ids),
        "case_titles": case_titles(case_ids),
    }


def enrich_training_skill_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    case_ids = _candidate_case_ids(candidate)
    trigger_ids = _candidate_trigger_item_ids(candidate)
    stage_scope = [str(stage) for stage in candidate.get("stage_scope", []) if str(stage)]
    source_turn_patterns = candidate.get("source_turn_patterns", [])
    return {
        **candidate,
        "case_ids": case_ids,
        "case_titles": case_titles(case_ids),
        "trigger_item_ids": trigger_ids,
        "trigger_item_labels": trigger_item_labels(trigger_ids, case_ids),
        "skill_type_label": skill_type_label(str(candidate.get("skill_type", ""))),
        "stage_scope_labels": stage_scope_labels(stage_scope),
        "effect_status_label": effect_status_label(str(candidate.get("effect_status", ""))),
        "related_recommendation_labels": reference_labels(candidate.get("related_recommendations", [])),
        "teaching_action_plan": [
            _enrich_training_skill_teaching_action(action, case_ids)
            for action in candidate.get("teaching_action_plan", [])
            if isinstance(action, dict)
        ],
        "source_turn_patterns": [
            enrich_training_insight_turn_pattern(pattern)
            for pattern in source_turn_patterns
            if isinstance(pattern, dict)
        ],
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


def enrich_teaching_focus_pattern(pattern: dict[str, Any]) -> dict[str, Any]:
    case_ids = [str(case_id) for case_id in pattern.get("case_ids", []) if str(case_id)]
    trigger_item_ids = [str(item_id) for item_id in pattern.get("trigger_item_ids", []) if str(item_id)]
    source_reference_ids = [str(reference) for reference in pattern.get("source_reference_ids", []) if str(reference)]
    return {
        **pattern,
        "case_titles": case_titles(case_ids),
        "scope_label": focus_scope_label(str(pattern.get("scope", ""))),
        "severity_label": focus_severity_label(str(pattern.get("severity", ""))),
        "visibility_level_label": focus_visibility_label(str(pattern.get("visibility_level", ""))),
        "trigger_item_labels": rubric_item_labels(trigger_item_ids, case_ids),
        "source_reference_labels": reference_labels(source_reference_ids),
    }


def _enrich_training_skill_teaching_action(action: dict[str, Any], case_ids: Iterable[str]) -> dict[str, Any]:
    trigger_item_ids = [str(item_id) for item_id in action.get("trigger_item_ids", []) if str(item_id)]
    stage_scope = [str(stage) for stage in action.get("stage_scope", []) if str(stage)]
    return {
        **action,
        "action_type_label": training_skill_action_label(str(action.get("action_type", ""))),
        "stage_scope_labels": stage_scope_labels(stage_scope),
        "trigger_item_labels": trigger_item_labels(trigger_item_ids, case_ids),
    }


def _candidate_case_ids(candidate: dict[str, Any]) -> list[str]:
    case_ids = [str(case_id) for case_id in candidate.get("case_ids", []) if str(case_id)]
    if case_ids:
        return case_ids
    reference_case_ids = _case_ids_from_references(candidate.get("related_recommendations", []))
    if reference_case_ids:
        return reference_case_ids
    applies_when = candidate.get("applies_when")
    if isinstance(applies_when, dict):
        return [str(case_id) for case_id in applies_when.get("case_ids", []) if str(case_id)]
    return []


def _candidate_trigger_item_ids(candidate: dict[str, Any]) -> list[str]:
    trigger_ids = [str(item_id) for item_id in candidate.get("trigger_item_ids", []) if str(item_id)]
    if trigger_ids:
        return trigger_ids
    trigger_item_id = str(candidate.get("trigger_item_id", "")).strip()
    if trigger_item_id:
        return [trigger_item_id]
    applies_when = candidate.get("applies_when")
    if isinstance(applies_when, dict):
        return [str(item_id) for item_id in applies_when.get("trigger_item_ids", []) if str(item_id)]
    return []


def _case_ids_from_references(references: Iterable[str]) -> list[str]:
    case_ids: list[str] = []
    for reference in references:
        rubric_reference = _parse_rubric_item_reference(str(reference))
        if rubric_reference is None:
            continue
        case_id, _item_id = rubric_reference
        if case_id not in case_ids:
            case_ids.append(case_id)
    return case_ids


def _parse_rubric_item_reference(reference: str) -> tuple[str, str] | None:
    normalized_reference = str(reference or "").strip()
    if not normalized_reference.startswith("rubric:"):
        return None
    payload = normalized_reference.removeprefix("rubric:")
    if "_rubric.item." not in payload:
        return None
    case_id, item_id = payload.split("_rubric.item.", 1)
    if not case_id or not item_id:
        return None
    return case_id, item_id


def _legacy_item_label(item_id: str) -> str:
    normalized_item_id = str(item_id or "").strip()
    if not normalized_item_id:
        return ""
    tokens = [token for token in normalized_item_id.split("_") if token]
    if not tokens:
        return ""
    prefix_label = LEGACY_ITEM_PREFIX_LABELS.get(tokens[0])
    translated_tokens = [LEGACY_ITEM_TOKEN_LABELS.get(token, "") for token in tokens[1:]]
    translated_tokens = [token for token in translated_tokens if token]
    if prefix_label and translated_tokens:
        return f"{prefix_label}：{'、'.join(translated_tokens)}（历史字段）"
    if translated_tokens:
        return f"{'、'.join(translated_tokens)}（历史字段）"
    return ""


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
