from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.services.training_skill_context_safety import candidate_context_safety_violations
from app.services.training_skill_policy import (
    build_prohibited_content_policy,
    build_success_metrics,
    build_teaching_action_plan,
)

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "training_skills.sqlite3"

STAGE_SCOPE_LABELS = {
    "case_intro": "训练开始",
    "history_taking": "问诊阶段",
    "physical_exam": "查体阶段",
    "auxiliary_testing": "辅助检查阶段",
    "auxiliary_test": "辅助检查阶段",
    "diagnosis_submission": "诊断提交前",
    "diagnosis": "诊断整理阶段",
    "feedback": "复盘阶段",
    "feedback_review": "复盘阶段",
}

EFFECT_STATUS_LABELS = {
    "insufficient_samples": "样本不足",
    "improving": "观察到改善",
    "neutral": "效果待观察",
    "declining": "需要复核",
}


class TrainingSkillStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def enable_candidate(self, candidate: dict[str, Any]) -> bool:
        if candidate.get("review", {}).get("status") != "approved":
            return False
        if candidate_context_safety_violations(candidate):
            return False
        self._initialize()
        skill = _skill_from_candidate(candidate)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO training_skills (skill_id, skill_json)
                VALUES (?, ?)
                ON CONFLICT(skill_id) DO UPDATE SET skill_json = excluded.skill_json
                """,
                (skill["skill_id"], json.dumps(skill, ensure_ascii=False)),
            )
        return True

    def get_skill(self, skill_id: str) -> dict[str, Any] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT skill_json FROM training_skills WHERE skill_id = ?",
                (skill_id,),
            ).fetchone()
        if row is None:
            return None
        skill = json.loads(row[0])
        hydrated_skill = _hydrate_skill_student_metadata(skill)
        if hydrated_skill != skill:
            with sqlite3.connect(self.database_path) as connection:
                connection.execute(
                    "UPDATE training_skills SET skill_json = ? WHERE skill_id = ?",
                    (json.dumps(hydrated_skill, ensure_ascii=False), skill_id),
                )
        return hydrated_skill

    def list_enabled_skills(self) -> list[dict[str, Any]]:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute("SELECT skill_id, skill_json FROM training_skills ORDER BY id").fetchall()
            skills: list[dict[str, Any]] = []
            for skill_id, skill_json in rows:
                skill = json.loads(skill_json)
                hydrated_skill = _hydrate_skill_student_metadata(skill)
                if hydrated_skill != skill:
                    connection.execute(
                        "UPDATE training_skills SET skill_json = ? WHERE skill_id = ?",
                        (json.dumps(hydrated_skill, ensure_ascii=False), skill_id),
                    )
                skills.append(hydrated_skill)
        return skills

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_skills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT NOT NULL UNIQUE,
                    skill_json TEXT NOT NULL
                )
                """
            )


def _skill_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    trigger_item_id = _non_empty_string(candidate.get("trigger_item_id"))
    applies_when = candidate.get("applies_when")
    if not isinstance(applies_when, dict):
        applies_when = {}
    trigger_item_ids = _normalized_string_list(candidate.get("trigger_item_ids"))
    if not trigger_item_ids:
        trigger_item_ids = _normalized_string_list(applies_when.get("trigger_item_ids"))
    if not trigger_item_ids and _is_concrete_trigger_item_id(trigger_item_id):
        trigger_item_ids = [trigger_item_id]
    case_ids = _normalized_string_list(candidate.get("case_ids"))
    stage_scope = _normalized_string_list(candidate.get("stage_scope"))
    if not stage_scope:
        stage_scope = _normalized_string_list(applies_when.get("stage_scope"))
    if not stage_scope:
        stage_scope = ["case_intro"]
    if not applies_when:
        applies_when = {
            "case_ids": case_ids,
            "stage_scope": stage_scope,
            "trigger_item_ids": trigger_item_ids,
            "current_missing_evidence": [],
            "min_support_count": candidate.get("support_count", 0),
        }
    else:
        applies_when = {
            **applies_when,
            "case_ids": _normalized_string_list(applies_when.get("case_ids")) or case_ids,
            "stage_scope": _normalized_string_list(applies_when.get("stage_scope")) or stage_scope,
            "trigger_item_ids": _normalized_string_list(applies_when.get("trigger_item_ids")) or trigger_item_ids,
            "current_missing_evidence": _normalized_string_list(applies_when.get("current_missing_evidence")),
            "min_support_count": _safe_int(applies_when.get("min_support_count") or candidate.get("support_count")),
        }
    teaching_action_plan = candidate.get("teaching_action_plan")
    if not isinstance(teaching_action_plan, list) or not teaching_action_plan:
        teaching_action_plan = build_teaching_action_plan(
            stage_scope=stage_scope,
            trigger_item_ids=trigger_item_ids,
            suggested_strategy=str(candidate["suggested_strategy"]),
        )
    prohibited_content_policy = candidate.get("prohibited_content_policy")
    if not isinstance(prohibited_content_policy, dict):
        prohibited_content_policy = build_prohibited_content_policy()
    success_metrics = candidate.get("success_metrics")
    if not isinstance(success_metrics, list) or not success_metrics:
        success_metrics = build_success_metrics()
    skill = {
        "skill_id": f"skill_{candidate['trigger_item_id']}",
        "source_candidate_id": candidate["candidate_id"],
        "trigger_item_id": trigger_item_id,
        "trigger_item_ids": trigger_item_ids,
        "case_ids": case_ids,
        "skill_type": str(candidate.get("skill_type", "reasoning_bridge")),
        "stage_scope": stage_scope,
        "effect_status": str(candidate.get("effect_status", "insufficient_samples")),
        "applies_when": applies_when,
        "title": candidate["title"],
        "description": candidate["description"],
        "suggested_strategy": candidate["suggested_strategy"],
        "teaching_action_plan": teaching_action_plan,
        "prohibited_content_policy": prohibited_content_policy,
        "success_metrics": success_metrics,
        "status": "enabled",
        "source_report_count": candidate["source_report_count"],
        "support_count": candidate["support_count"],
        "related_recommendations": list(candidate.get("related_recommendations", [])),
    }
    reasoning_pattern_ids = _normalized_string_list(candidate.get("reasoning_pattern_ids"))
    reasoning_pattern_labels = _normalized_string_list(candidate.get("reasoning_pattern_labels"))
    source_trace_version = _non_empty_string(candidate.get("source_trace_version"))
    if reasoning_pattern_ids:
        skill["reasoning_pattern_ids"] = reasoning_pattern_ids
        skill["applies_when"] = {
            **skill["applies_when"],
            "reasoning_pattern_ids": _normalized_string_list(
                skill["applies_when"].get("reasoning_pattern_ids")
            )
            or reasoning_pattern_ids,
        }
    if reasoning_pattern_labels:
        skill["reasoning_pattern_labels"] = reasoning_pattern_labels
    if source_trace_version:
        skill["source_trace_version"] = source_trace_version
    scope = str(candidate.get("scope", "global"))
    if scope != "global":
        skill["scope"] = scope
        skill["owner_student_id"] = str(candidate.get("owner_student_id", ""))
        skill["source_session_id"] = str(candidate.get("source_session_id", ""))
        skill["source_session_ids"] = list(candidate.get("source_session_ids", []))
        skill["source_report_ids"] = list(candidate.get("source_report_ids", []))
    if scope != "global" or candidate.get("rag_evidence_items"):
        skill["rag_evidence_items"] = list(candidate.get("rag_evidence_items", []))
    if scope != "global" or candidate.get("approval_dialogue"):
        skill["approval_dialogue"] = list(candidate.get("approval_dialogue", []))
    if scope != "global" or (candidate.get("web_check_status") and candidate.get("web_check_status") != "not_configured"):
        skill["web_check_status"] = str(candidate.get("web_check_status", "not_configured"))
    if scope != "global" or candidate.get("external_evidence_checks"):
        skill["external_evidence_checks"] = list(candidate.get("external_evidence_checks", []))
    return _hydrate_skill_student_metadata(skill)


def _hydrate_skill_student_metadata(skill: dict[str, Any]) -> dict[str, Any]:
    hydrated_skill = _normalize_skill_core_metadata(dict(skill))
    support_count = _safe_int(hydrated_skill.get("support_count"))
    source_report_count = _safe_int(hydrated_skill.get("source_report_count"))
    effect_status = str(hydrated_skill.get("effect_status", "insufficient_samples"))
    description = _non_empty_string(hydrated_skill.get("description"))
    suggested_strategy = _non_empty_string(hydrated_skill.get("suggested_strategy"))

    hydrated_skill["student_visible_summary"] = _non_empty_string(
        hydrated_skill.get("student_visible_summary")
    ) or description
    hydrated_skill["learning_action"] = _non_empty_string(hydrated_skill.get("learning_action")) or suggested_strategy
    hydrated_skill["activation_summary"] = _non_empty_string(
        hydrated_skill.get("activation_summary")
    ) or _build_activation_summary(hydrated_skill)
    hydrated_skill["source_summary"] = _non_empty_string(
        hydrated_skill.get("source_summary")
    ) or _build_source_summary(source_report_count, support_count)
    hydrated_skill["effect_status_label"] = _non_empty_string(
        hydrated_skill.get("effect_status_label")
    ) or EFFECT_STATUS_LABELS.get(effect_status, effect_status)
    hydrated_skill["scope_label"] = _non_empty_string(hydrated_skill.get("scope_label")) or _scope_label(
        hydrated_skill
    )
    if not isinstance(hydrated_skill.get("teaching_action_plan"), list) or not hydrated_skill["teaching_action_plan"]:
        hydrated_skill["teaching_action_plan"] = build_teaching_action_plan(
            stage_scope=_normalized_string_list(hydrated_skill.get("stage_scope")),
            trigger_item_ids=_normalized_string_list(hydrated_skill.get("trigger_item_ids")),
            suggested_strategy=suggested_strategy,
        )
    if not isinstance(hydrated_skill.get("prohibited_content_policy"), dict):
        hydrated_skill["prohibited_content_policy"] = build_prohibited_content_policy()
    if not isinstance(hydrated_skill.get("success_metrics"), list) or not hydrated_skill["success_metrics"]:
        hydrated_skill["success_metrics"] = build_success_metrics()
    hydrated_skill["related_recommendations"] = _normalized_string_list(hydrated_skill.get("related_recommendations"))
    return hydrated_skill


def _normalize_skill_core_metadata(skill: dict[str, Any]) -> dict[str, Any]:
    trigger_item_id = _non_empty_string(skill.get("trigger_item_id"))
    applies_when = skill.get("applies_when")
    if not isinstance(applies_when, dict):
        applies_when = {}

    trigger_item_ids = _normalized_string_list(skill.get("trigger_item_ids"))
    if not trigger_item_ids:
        trigger_item_ids = _normalized_string_list(applies_when.get("trigger_item_ids"))
    if not trigger_item_ids and _is_concrete_trigger_item_id(trigger_item_id):
        trigger_item_ids = [trigger_item_id]

    case_ids = _normalized_string_list(skill.get("case_ids"))
    if not case_ids:
        case_ids = _normalized_string_list(applies_when.get("case_ids"))

    stage_scope = _normalized_string_list(skill.get("stage_scope"))
    if not stage_scope:
        stage_scope = _normalized_string_list(applies_when.get("stage_scope"))
    if not stage_scope:
        stage_scope = ["case_intro"]

    skill["trigger_item_id"] = trigger_item_id
    skill["trigger_item_ids"] = trigger_item_ids
    skill["case_ids"] = case_ids
    skill["stage_scope"] = stage_scope
    normalized_applies_when = {
        **applies_when,
        "case_ids": _normalized_string_list(applies_when.get("case_ids")) or case_ids,
        "stage_scope": _normalized_string_list(applies_when.get("stage_scope")) or stage_scope,
        "trigger_item_ids": _normalized_string_list(applies_when.get("trigger_item_ids")) or trigger_item_ids,
        "current_missing_evidence": _normalized_string_list(applies_when.get("current_missing_evidence")),
        "min_support_count": _safe_int(applies_when.get("min_support_count") or skill.get("support_count")),
    }
    reasoning_pattern_ids = _normalized_string_list(skill.get("reasoning_pattern_ids"))
    if reasoning_pattern_ids:
        normalized_applies_when["reasoning_pattern_ids"] = _normalized_string_list(
            applies_when.get("reasoning_pattern_ids")
        ) or reasoning_pattern_ids
        skill["reasoning_pattern_ids"] = reasoning_pattern_ids
    elif "reasoning_pattern_ids" in skill:
        skill.pop("reasoning_pattern_ids", None)
    reasoning_pattern_labels = _normalized_string_list(skill.get("reasoning_pattern_labels"))
    if reasoning_pattern_labels:
        skill["reasoning_pattern_labels"] = reasoning_pattern_labels
    elif "reasoning_pattern_labels" in skill:
        skill.pop("reasoning_pattern_labels", None)
    if not _non_empty_string(skill.get("source_trace_version")):
        skill.pop("source_trace_version", None)
    skill["applies_when"] = normalized_applies_when
    return skill


def _build_activation_summary(skill: dict[str, Any]) -> str:
    case_ids = _normalized_string_list(skill.get("case_ids"))
    case_summary = "适用于所有当前开放病例"
    if case_ids:
        case_summary = f"适用于{'、'.join(_case_title(case_id) for case_id in case_ids)}"

    stage_scope = _normalized_string_list(skill.get("stage_scope"))
    stage_summary = "匹配训练阶段时"
    if stage_scope:
        stage_summary = f"{'、'.join(STAGE_SCOPE_LABELS.get(stage, stage) for stage in stage_scope)}时"

    trigger_item_ids = _normalized_string_list(skill.get("trigger_item_ids"))
    if trigger_item_ids:
        return f"{case_summary}；{stage_summary}，当当前缺口命中 {len(trigger_item_ids)} 个关联训练点时触发。"
    return f"{case_summary}；{stage_summary}，当训练状态匹配该 Skill 条件时触发。"


def _build_source_summary(source_report_count: int, support_count: int) -> str:
    if source_report_count > 0:
        return f"来自 {source_report_count} 份报告，累计支持 {support_count} 次。"
    return f"来自训练事件聚合，累计支持 {support_count} 次。"


def _scope_label(skill: dict[str, Any]) -> str:
    return "个人 Skill" if str(skill.get("scope", "global")) == "personal" else "全局 Skill"


def _case_title(case_id: str) -> str:
    case_path = CASES_DIR / f"{case_id}.json"
    if not case_path.exists():
        return case_id
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    title = payload.get("case_title")
    return str(title) if title else case_id


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _non_empty_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalized_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (_non_empty_string(raw_item) for raw_item in value) if item]


def _is_concrete_trigger_item_id(value: str) -> bool:
    if not value:
        return False
    return not value.startswith(("training_pattern_", "turn_pattern_", "personal_skill_candidate_"))


training_skill_store = TrainingSkillStore()
