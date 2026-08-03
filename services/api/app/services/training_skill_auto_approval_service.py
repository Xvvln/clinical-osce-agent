from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from app.services.agent_rag_context_service import retrieve_agent_context
from app.services.admin_display_resolver import trigger_item_labels as resolve_trigger_item_labels
from app.services.rag_knowledge_store import rag_knowledge_store
from app.services.skill_role_policy_service import build_approval_skill_role_policy
from app.services.training_skill_policy import build_skill_memory_fields, build_teaching_action_plan
from app.services.training_skill_regression_gate import FORBIDDEN_CANDIDATE_PATTERNS, FORBIDDEN_CANDIDATE_TERMS

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "training_skill_auto_approval.sqlite3"
AUTO_APPROVAL_AGENT_ID = "skill_auto_approval_agent"

PROTECTED_CANDIDATE_FIELDS = [
    "candidate_id",
    "trigger_item_id",
    "trigger_item_ids",
    "case_ids",
    "skill_type",
    "stage_scope",
    "applies_when",
    "source_report_count",
    "support_count",
    "related_recommendations",
    "prohibited_content_policy",
    "success_metrics",
]

SAFE_TERM_REPLACEMENTS = {
    "剂量": "证据链训练要点",
    "处方": "训练复盘策略",
    "阿莫西林": "训练证据链",
    "头孢": "训练证据链",
    "抗生素": "训练证据链",
    "治疗方案": "训练复盘策略",
    "用药剂量": "证据链训练要点",
    "用药建议": "学习复盘建议",
    "手术方案": "训练步骤安排",
    "处置建议": "下一步训练建议",
}

SAFE_PATTERN_REPLACEMENTS = {
    "dose_expression": "证据链训练要点",
    "dose_frequency": "训练复盘频次",
}

MEMORY_FIELD_KEYS = [
    "memory_layer",
    "skill_memory_version",
    "problem_pattern",
    "router_index",
    "intervention",
    "effect_tracking",
]

SAFETY_SUFFIX = "仅提示训练步骤和证据链复盘，不透露病例答案或隐藏事实，不提供真实诊疗信息。"
SKILL_APPROVAL_RAG_VISIBILITIES = {"pre_submit_safe", "post_submit_review"}
PROTECTED_DIAGNOSIS_PLACEHOLDER = "当前主要诊断假设"


class TrainingSkillAutoApprovalSettingsStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def get_settings(self) -> dict[str, Any]:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT auto_apply_enabled, approval_agent_id, updated_by, updated_at
                FROM training_skill_auto_approval_settings
                WHERE id = 1
                """
            ).fetchone()
        if row is None:
            return {
                "auto_apply_enabled": False,
                "approval_agent_id": AUTO_APPROVAL_AGENT_ID,
                "updated_by": "",
                "updated_at": None,
            }
        return {
            "auto_apply_enabled": bool(row[0]),
            "approval_agent_id": row[1],
            "updated_by": row[2],
            "updated_at": row[3],
        }

    def update_settings(self, *, auto_apply_enabled: bool, updated_by: str) -> dict[str, Any]:
        self._initialize()
        updated_at = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO training_skill_auto_approval_settings (
                    id,
                    auto_apply_enabled,
                    approval_agent_id,
                    updated_by,
                    updated_at
                )
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    auto_apply_enabled = excluded.auto_apply_enabled,
                    approval_agent_id = excluded.approval_agent_id,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (
                    1 if auto_apply_enabled else 0,
                    AUTO_APPROVAL_AGENT_ID,
                    updated_by,
                    updated_at,
                ),
            )
        return self.get_settings()

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_skill_auto_approval_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    auto_apply_enabled INTEGER NOT NULL,
                    approval_agent_id TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    updated_at TEXT
                )
                """
            )


class TrainingSkillApprovalAgent:
    agent_id = AUTO_APPROVAL_AGENT_ID

    def review_candidate(
        self,
        candidate: dict[str, Any],
        *,
        protected_terms: list[str] | None = None,
    ) -> dict[str, Any]:
        original_candidate = deepcopy(candidate)
        reviewed_candidate = deepcopy(candidate)
        changed_fields: list[dict[str, Any]] = []

        for field in ["title", "description", "suggested_strategy"]:
            before = str(reviewed_candidate.get(field, ""))
            after = _sanitize_training_text(before, protected_terms or [])
            if field == "suggested_strategy":
                after = _ensure_safety_suffix(after)
            if after != before:
                reviewed_candidate[field] = after
                changed_fields.append({"field": field, "before": before, "after": after})

        before_action_plan = deepcopy(reviewed_candidate.get("teaching_action_plan", []))
        next_action_plan = build_teaching_action_plan(
            stage_scope=[str(stage) for stage in reviewed_candidate.get("stage_scope", [])],
            trigger_item_ids=[str(item_id) for item_id in reviewed_candidate.get("trigger_item_ids", [])],
            suggested_strategy=str(reviewed_candidate.get("suggested_strategy", "")),
        )
        if _json_payload(before_action_plan) != _json_payload(next_action_plan):
            reviewed_candidate["teaching_action_plan"] = next_action_plan
            changed_fields.append(
                {
                    "field": "teaching_action_plan",
                    "before": before_action_plan,
                    "after": next_action_plan,
                }
            )

        before_memory_fields = {
            field: deepcopy(reviewed_candidate.get(field))
            for field in MEMORY_FIELD_KEYS
        }
        refreshed_memory_fields = _build_refreshed_skill_memory_fields(reviewed_candidate)
        reviewed_candidate.update(refreshed_memory_fields)
        for field in MEMORY_FIELD_KEYS:
            before = before_memory_fields.get(field)
            after = reviewed_candidate.get(field)
            if _json_payload(before) != _json_payload(after):
                changed_fields.append({"field": field, "before": before, "after": after})

        retrieved_knowledge_context = _retrieve_skill_approval_knowledge_context(reviewed_candidate)
        quality_review = _build_quality_review(
            original_candidate=original_candidate,
            reviewed_candidate=reviewed_candidate,
            retrieved_knowledge_context=retrieved_knowledge_context,
        )
        approval_role_policy = build_approval_skill_role_policy(reviewed_candidate)
        reviewed_candidate["approval_agent_review"] = {
            "agent_id": self.agent_id,
            "decision": "prepared_for_auto_apply" if quality_review["passed"] else "blocked",
            "revision_status": "modified" if changed_fields else "unchanged",
            "changed_fields": changed_fields,
            "reviewed_fields": [
                "title",
                "description",
                "suggested_strategy",
                "teaching_action_plan",
                *MEMORY_FIELD_KEYS,
            ],
            "protected_fields": list(PROTECTED_CANDIDATE_FIELDS),
            "quality_review": quality_review,
            "role_policy": approval_role_policy,
            "knowledge_references": [item["reference"] for item in retrieved_knowledge_context],
            "retrieved_knowledge_context": retrieved_knowledge_context,
            "safety_constraints": [
                "teaching_strategy_only",
                "no_standard_answer",
                "no_hidden_facts",
                "no_treatment_or_dose",
                "rag_visibility_filtered",
            ],
        }
        return _sanitize_nested_training_text(reviewed_candidate, protected_terms or [])


def _sanitize_training_text(text: str, protected_terms: list[str] | None = None) -> str:
    sanitized = text
    for forbidden_term in FORBIDDEN_CANDIDATE_TERMS:
        sanitized = sanitized.replace(forbidden_term, SAFE_TERM_REPLACEMENTS[forbidden_term])
    for violation_id, pattern in FORBIDDEN_CANDIDATE_PATTERNS.items():
        sanitized = re.sub(pattern, SAFE_PATTERN_REPLACEMENTS[violation_id], sanitized)
    sanitized = sanitized.replace("本病例标准答案", PROTECTED_DIAGNOSIS_PLACEHOLDER)
    for protected_term in protected_terms or []:
        if protected_term:
            sanitized = sanitized.replace(protected_term, PROTECTED_DIAGNOSIS_PLACEHOLDER)
    return sanitized.strip()


def _sanitize_nested_training_text(value: Any, protected_terms: list[str] | None = None) -> Any:
    if isinstance(value, str):
        return _sanitize_training_text(value, protected_terms)
    if isinstance(value, list):
        return [_sanitize_nested_training_text(item, protected_terms) for item in value]
    if isinstance(value, dict):
        return {
            key: _sanitize_nested_training_text(nested_value, protected_terms)
            for key, nested_value in value.items()
        }
    return value


def _ensure_safety_suffix(text: str) -> str:
    if SAFETY_SUFFIX in text:
        return text
    if not text:
        return SAFETY_SUFFIX
    return f"{text.rstrip('。')}。{SAFETY_SUFFIX}"


def _build_refreshed_skill_memory_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    trigger_item_ids = _normalized_string_list(candidate.get("trigger_item_ids"))
    case_ids = _normalized_string_list(candidate.get("case_ids"))
    problem_pattern = _dict(candidate.get("problem_pattern"))
    effect_tracking = _dict(candidate.get("effect_tracking"))
    return build_skill_memory_fields(
        pattern_id=str(candidate.get("trigger_item_id") or candidate.get("candidate_id") or ""),
        skill_type=str(candidate.get("skill_type") or "reasoning_bridge"),
        trigger_item_ids=trigger_item_ids,
        case_ids=case_ids,
        source_report_count=_safe_int(candidate.get("source_report_count")),
        support_count=_safe_int(candidate.get("support_count")),
        title=str(candidate.get("title") or ""),
        description=str(candidate.get("description") or ""),
        suggested_strategy=str(candidate.get("suggested_strategy") or ""),
        stage_scope=_normalized_string_list(candidate.get("stage_scope")),
        effect_status=str(candidate.get("effect_status") or "insufficient_samples"),
        reasoning_pattern_ids=_normalized_string_list(problem_pattern.get("reasoning_pattern_ids")),
        reasoning_pattern_labels=_normalized_string_list(problem_pattern.get("reasoning_pattern_labels")),
        trigger_item_labels=resolve_trigger_item_labels(trigger_item_ids, case_ids),
        application_count=_safe_int(effect_tracking.get("application_count")),
    )


def _build_quality_review(
    *,
    original_candidate: dict[str, Any],
    reviewed_candidate: dict[str, Any],
    retrieved_knowledge_context: list[dict[str, Any]],
) -> dict[str, Any]:
    protected_field_changes = [
        field
        for field in PROTECTED_CANDIDATE_FIELDS
        if _json_payload(original_candidate.get(field)) != _json_payload(reviewed_candidate.get(field))
    ]
    unsafe_terms = _unsafe_terms_in_teaching_body(reviewed_candidate)
    required_skill_body_sections = [
        "teaching_goal",
        "coach_strategy",
        "focus_points",
        "hint_ladder",
        "teaching_sop",
        "reflection_prompt",
        "avoid",
    ]
    intervention = _dict(reviewed_candidate.get("intervention"))
    teaching_sop = _dict(intervention.get("teaching_sop"))
    approval_role_policy = build_approval_skill_role_policy(reviewed_candidate)
    role_policy_checks = {
        str(check.get("check_id") or ""): check
        for check in approval_role_policy.get("checks", [])
        if isinstance(check, dict)
    }
    checks = [
        _quality_check(
            "protected_fields_preserved",
            "保护字段未被审批 Agent 改写",
            not protected_field_changes,
            "无保护字段变化" if not protected_field_changes else f"被改写字段：{', '.join(protected_field_changes)}",
        ),
        _quality_check(
            "unsafe_terms_removed",
            "教学正文不包含真实治疗、用药或剂量建议",
            not unsafe_terms,
            "未发现危险建议" if not unsafe_terms else f"仍包含：{', '.join(unsafe_terms)}",
        ),
        _quality_check(
            "skill_body_complete",
            "Skill Body 包含 Coach 所需的教学结构",
            all(_has_meaningful_value(intervention.get(section)) for section in required_skill_body_sections),
            "已包含教学目标、焦点训练点、分层提示、SOP、复盘提示和边界"
            if all(_has_meaningful_value(intervention.get(section)) for section in required_skill_body_sections)
            else "Skill Body 缺少必要章节",
        ),
        _quality_check(
            "teaching_sop_complete",
            "教学 SOP 有分步教师动作和安全边界",
            bool(teaching_sop.get("version"))
            and len(teaching_sop.get("teacher_moves") or []) >= 3
            and bool(teaching_sop.get("student_task"))
            and bool(teaching_sop.get("completion_signal"))
            and bool(teaching_sop.get("safety_guardrails")),
            "SOP 已包含不少于 3 步教师动作、学生任务、完成信号和安全边界",
        ),
        _quality_check(
            "rag_visibility_filtered",
            "审批知识只来自允许可见性的知识库片段",
            all(
                str(item.get("visibility") or "") in SKILL_APPROVAL_RAG_VISIBILITIES
                for item in retrieved_knowledge_context
            ),
            "RAG 片段已按 skill_approval 可见性过滤",
        ),
        _quality_check(
            "prohibited_content_policy_complete",
            "审批角色禁区策略完整",
            bool(role_policy_checks.get("prohibited_content_policy_complete", {}).get("passed")),
            str(role_policy_checks.get("prohibited_content_policy_complete", {}).get("detail") or "缺少禁区策略"),
        ),
        _quality_check(
            "success_metrics_declared",
            "审批角色已声明可追踪成效指标",
            bool(role_policy_checks.get("success_metrics_declared", {}).get("passed")),
            str(role_policy_checks.get("success_metrics_declared", {}).get("detail") or "缺少成效指标"),
        ),
    ]
    failed_checks = [check["check_id"] for check in checks if not check["passed"]]
    return {
        "passed": not failed_checks,
        "checks": checks,
        "failed_checks": failed_checks,
        "revision_summary": (
            "审批 Agent 已完成安全净化、Skill Body 刷新和质量检查。"
            if not failed_checks
            else "审批 Agent 发现候选 Skill 仍存在质量或安全问题。"
        ),
    }


def _quality_check(check_id: str, title: str, passed: bool, detail: str) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "title": title,
        "passed": passed,
        "detail": detail,
    }


def _unsafe_terms_in_teaching_body(candidate: dict[str, Any]) -> list[str]:
    intervention = _dict(candidate.get("intervention"))
    teaching_sop = _dict(intervention.get("teaching_sop"))
    text = " ".join(
        [
            str(candidate.get("title") or ""),
            str(candidate.get("description") or ""),
            str(candidate.get("suggested_strategy") or ""),
            str(intervention.get("coach_strategy") or ""),
            " ".join(str(item) for item in intervention.get("hint_ladder") or []),
            str(teaching_sop.get("student_task") or ""),
            str(teaching_sop.get("completion_signal") or ""),
            " ".join(
                str(move.get("move") or "")
                for move in teaching_sop.get("teacher_moves") or []
                if isinstance(move, dict)
            ),
        ]
    )
    violations: list[str] = []
    for term in FORBIDDEN_CANDIDATE_TERMS:
        if term in text and term not in violations:
            violations.append(term)
    violations.extend(
        violation_id
        for violation_id, pattern in FORBIDDEN_CANDIDATE_PATTERNS.items()
        if pattern.search(text)
    )
    return violations


def _has_meaningful_value(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _retrieve_skill_approval_knowledge_context(candidate: dict[str, Any], *, limit: int = 3) -> list[dict[str, Any]]:
    return retrieve_agent_context(
        agent_role="skill_approval",
        case_ids=[str(case_id) for case_id in candidate.get("case_ids", []) if str(case_id)],
        query_terms=[
            str(candidate.get("title", "")),
            str(candidate.get("description", "")),
            str(candidate.get("suggested_strategy", "")),
            *[str(item_id) for item_id in candidate.get("trigger_item_ids", []) if str(item_id)],
            *[str(case_id) for case_id in candidate.get("case_ids", []) if str(case_id)],
        ],
        allowed_visibilities=SKILL_APPROVAL_RAG_VISIBILITIES,
        stage_scope=[
            *[str(stage) for stage in candidate.get("stage_scope", []) if str(stage)],
            "feedback",
        ],
        limit=limit,
        store=rag_knowledge_store,
    )


def _json_payload(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


training_skill_auto_approval_settings_store = TrainingSkillAutoApprovalSettingsStore()
training_skill_approval_agent = TrainingSkillApprovalAgent()


__all__ = [
    "AUTO_APPROVAL_AGENT_ID",
    "TrainingSkillApprovalAgent",
    "TrainingSkillAutoApprovalSettingsStore",
    "training_skill_approval_agent",
    "training_skill_auto_approval_settings_store",
]
