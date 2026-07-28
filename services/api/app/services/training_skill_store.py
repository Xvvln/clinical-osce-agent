from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.admin_display_resolver import trigger_item_labels as resolve_trigger_item_labels
from app.services.training_skill_context_safety import candidate_context_safety_violations
from app.services.training_skill_policy import (
    build_prohibited_content_policy,
    build_skill_memory_fields,
    build_success_metrics,
    build_teaching_action_plan,
)

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "training_skills.sqlite3"
DATABASE_SCHEMA_VERSION = 2

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


class TrainingSkillDeletedError(RuntimeError):
    def __init__(self, skill_id: str) -> None:
        super().__init__(skill_id)
        self.skill_id = skill_id


class TrainingSkillOwnershipError(RuntimeError):
    def __init__(self, skill_id: str) -> None:
        super().__init__(skill_id)
        self.skill_id = skill_id


class TrainingSkillSourceDeletedError(RuntimeError):
    def __init__(self, source_session_id: str) -> None:
        super().__init__(source_session_id)
        self.source_session_id = source_session_id


@dataclass(frozen=True)
class GlobalSkillSourceCleanup:
    affected_skill_ids: tuple[str, ...]


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
            connection.execute("BEGIN IMMEDIATE")
            skill_id = str(skill["skill_id"])
            if self._is_skill_deleted(connection, skill_id):
                raise TrainingSkillDeletedError(skill_id)
            deleted_source_session_id = self._deleted_source_reference(
                connection,
                candidate,
            )
            if deleted_source_session_id is not None:
                raise TrainingSkillSourceDeletedError(deleted_source_session_id)
            connection.execute(
                """
                INSERT INTO training_skills (skill_id, skill_json)
                VALUES (?, ?)
                ON CONFLICT(skill_id) DO UPDATE SET skill_json = excluded.skill_json
                """,
                (skill_id, json.dumps(skill, ensure_ascii=False)),
            )
        return True

    def get_skill(self, skill_id: str) -> dict[str, Any] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT skill_json FROM training_skills WHERE skill_id = ?",
                (skill_id,),
            ).fetchone()
            if row is None:
                return None
            skill = json.loads(row[0])
            hydrated_skill = _hydrate_skill_student_metadata(skill)
            if hydrated_skill != skill:
                connection.execute(
                    "UPDATE training_skills SET skill_json = ? WHERE skill_id = ?",
                    (json.dumps(hydrated_skill, ensure_ascii=False), skill_id),
                )
        return hydrated_skill

    def list_enabled_skills(self) -> list[dict[str, Any]]:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
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
                if str(hydrated_skill.get("status", "enabled")) == "enabled":
                    skills.append(hydrated_skill)
        return skills

    def delete_personal_skill(
        self,
        *,
        skill_id: str,
        owner_student_id: str,
        source_session_id: str,
        source_candidate_id: str,
    ) -> bool:
        """Delete one deterministic personal skill and persist a write fence."""

        _validate_personal_skill_delete_identity(
            skill_id=skill_id,
            owner_student_id=owner_student_id,
            source_session_id=source_session_id,
            source_candidate_id=source_candidate_id,
        )
        self._initialize()
        deleted_at = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            tombstone = connection.execute(
                """
                SELECT scope, owner_student_id, source_session_id, source_candidate_id
                FROM training_skill_tombstones
                WHERE skill_id = ?
                """,
                (skill_id,),
            ).fetchone()
            if tombstone is not None:
                if tuple(str(value) for value in tombstone) != (
                    "personal",
                    owner_student_id,
                    source_session_id,
                    source_candidate_id,
                ):
                    raise TrainingSkillOwnershipError(skill_id)
                return False

            row = connection.execute(
                """
                SELECT skill_json
                FROM training_skills
                WHERE skill_id = ?
                """,
                (skill_id,),
            ).fetchone()
            if row is not None:
                skill = _decode_skill(row[0], skill_id=skill_id)
                if (
                    str(skill.get("skill_id", "")) != skill_id
                    or str(skill.get("scope", "")) != "personal"
                    or str(skill.get("owner_student_id", "")) != owner_student_id
                    or str(skill.get("source_session_id", "")) != source_session_id
                    or str(skill.get("source_candidate_id", "")) != source_candidate_id
                ):
                    raise TrainingSkillOwnershipError(skill_id)

            connection.execute(
                """
                INSERT INTO training_skill_tombstones (
                    skill_id,
                    scope,
                    owner_student_id,
                    source_session_id,
                    source_candidate_id,
                    deleted_at
                )
                VALUES (?, 'personal', ?, ?, ?, ?)
                """,
                (
                    skill_id,
                    owner_student_id,
                    source_session_id,
                    source_candidate_id,
                    deleted_at,
                ),
            )
            cursor = connection.execute(
                """
                DELETE FROM training_skills
                WHERE skill_id = ?
                """,
                (skill_id,),
            )
        return cursor.rowcount == 1

    def remove_global_source_contributions(
        self,
        *,
        source_session_id: str,
        owner_student_id: str,
        source_report_id: str,
        affected_candidate_ids: list[str],
    ) -> GlobalSkillSourceCleanup:
        normalized_candidate_ids = sorted(
            {
                str(candidate_id)
                for candidate_id in affected_candidate_ids
                if str(candidate_id)
            }
        )
        if (
            not source_session_id
            or not owner_student_id
            or source_report_id != f"{source_session_id}_report"
        ):
            raise TrainingSkillOwnershipError(source_session_id)

        self._initialize()
        deleted_at = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT
                    owner_student_id,
                    source_report_id,
                    affected_candidate_ids_json,
                    affected_skill_ids_json
                FROM training_skill_source_tombstones
                WHERE source_session_id = ?
                """,
                (source_session_id,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing[0]) != owner_student_id
                    or str(existing[1]) != source_report_id
                    or _decode_string_list(existing[2]) != normalized_candidate_ids
                ):
                    raise TrainingSkillOwnershipError(source_session_id)
                return GlobalSkillSourceCleanup(
                    affected_skill_ids=tuple(_decode_string_list(existing[3]))
                )

            rows = connection.execute(
                """
                SELECT skill_id, skill_json
                FROM training_skills
                ORDER BY id
                """
            ).fetchall()
            affected_skill_ids: list[str] = []
            stale_payloads: list[tuple[str, str]] = []
            for raw_skill_id, raw_skill_json in rows:
                skill_id = str(raw_skill_id)
                skill = _decode_skill(str(raw_skill_json), skill_id=skill_id)
                if str(skill.get("scope", "global")) != "global":
                    continue
                if (
                    str(skill.get("source_candidate_id", ""))
                    not in normalized_candidate_ids
                    and not _payload_references_source(
                        skill,
                        source_session_id=source_session_id,
                        source_report_id=source_report_id,
                    )
                ):
                    continue
                affected_skill_ids.append(skill_id)
                stale_payloads.append(
                    (
                        skill_id,
                        json.dumps(
                            _stale_global_skill_without_source(
                                skill,
                                source_session_id=source_session_id,
                                source_report_id=source_report_id,
                            ),
                            ensure_ascii=False,
                        ),
                    )
                )

            affected_skill_ids.sort()
            connection.execute(
                """
                INSERT INTO training_skill_source_tombstones (
                    source_session_id,
                    owner_student_id,
                    source_report_id,
                    affected_candidate_ids_json,
                    affected_skill_ids_json,
                    deleted_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source_session_id,
                    owner_student_id,
                    source_report_id,
                    json.dumps(normalized_candidate_ids),
                    json.dumps(affected_skill_ids),
                    deleted_at,
                ),
            )
            connection.executemany(
                """
                UPDATE training_skills
                SET skill_json = ?
                WHERE skill_id = ?
                """,
                [(payload, skill_id) for skill_id, payload in stale_payloads],
            )
        return GlobalSkillSourceCleanup(
            affected_skill_ids=tuple(affected_skill_ids)
        )

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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_skill_tombstones (
                    skill_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    owner_student_id TEXT NOT NULL,
                    source_session_id TEXT NOT NULL,
                    source_candidate_id TEXT NOT NULL,
                    deleted_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_skill_source_tombstones (
                    source_session_id TEXT PRIMARY KEY,
                    owner_student_id TEXT NOT NULL,
                    source_report_id TEXT NOT NULL,
                    affected_candidate_ids_json TEXT NOT NULL,
                    affected_skill_ids_json TEXT NOT NULL,
                    deleted_at TEXT NOT NULL
                )
                """
            )
            connection.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")

    @staticmethod
    def _is_skill_deleted(
        connection: sqlite3.Connection,
        skill_id: str,
    ) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM training_skill_tombstones
            WHERE skill_id = ?
            """,
            (skill_id,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _deleted_source_reference(
        connection: sqlite3.Connection,
        candidate: dict[str, Any],
    ) -> str | None:
        rows = connection.execute(
            """
            SELECT
                source_session_id,
                source_report_id,
                affected_candidate_ids_json
            FROM training_skill_source_tombstones
            """
        ).fetchall()
        candidate_id = str(candidate.get("candidate_id", ""))
        for raw_session_id, raw_report_id, raw_affected_ids in rows:
            source_session_id = str(raw_session_id)
            if _payload_references_source(
                candidate,
                source_session_id=source_session_id,
                source_report_id=str(raw_report_id),
            ):
                return source_session_id
            if (
                candidate_id in _decode_string_list(raw_affected_ids)
                and not _has_explicit_remaining_source_provenance(candidate)
            ):
                return source_session_id
        return None


def _validate_personal_skill_delete_identity(
    *,
    skill_id: str,
    owner_student_id: str,
    source_session_id: str,
    source_candidate_id: str,
) -> None:
    if (
        not owner_student_id
        or not source_session_id
        or skill_id != f"skill_personal_{source_session_id}"
        or source_candidate_id != f"personal_skill_candidate_{source_session_id}"
    ):
        raise TrainingSkillOwnershipError(skill_id)


def _decode_skill(value: str, *, skill_id: str) -> dict[str, Any]:
    skill = json.loads(value)
    if not isinstance(skill, dict):
        raise TrainingSkillOwnershipError(skill_id)
    return skill


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
    skill_type = _candidate_skill_type(candidate, trigger_item_ids)
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
        "skill_type": skill_type,
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
    for memory_key in (
        "memory_layer",
        "skill_memory_version",
        "problem_pattern",
        "router_index",
        "intervention",
        "effect_tracking",
    ):
        if memory_key in candidate:
            skill[memory_key] = candidate[memory_key]
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
    teacher_analysis_context = candidate.get("teacher_analysis_context")
    if isinstance(teacher_analysis_context, dict) and teacher_analysis_context:
        skill["teacher_analysis_context"] = dict(teacher_analysis_context)
    scope = str(candidate.get("scope", "global"))
    if scope != "global":
        skill["scope"] = scope
        skill["owner_student_id"] = str(candidate.get("owner_student_id", ""))
        skill["source_session_id"] = str(candidate.get("source_session_id", ""))
    if candidate.get("source_session_ids"):
        skill["source_session_ids"] = list(candidate.get("source_session_ids", []))
    if candidate.get("source_report_ids"):
        skill["source_report_ids"] = list(candidate.get("source_report_ids", []))
    if candidate.get("source_turn_patterns"):
        skill["source_turn_patterns"] = list(
            candidate.get("source_turn_patterns", [])
        )
    if candidate.get("source_provenance_schema_version"):
        skill["source_provenance_schema_version"] = str(
            candidate["source_provenance_schema_version"]
        )
    if scope != "global" or candidate.get("rag_evidence_items"):
        skill["rag_evidence_items"] = list(candidate.get("rag_evidence_items", []))
    if scope != "global" or candidate.get("approval_dialogue"):
        skill["approval_dialogue"] = list(candidate.get("approval_dialogue", []))
    if scope != "global" or (candidate.get("web_check_status") and candidate.get("web_check_status") != "not_configured"):
        skill["web_check_status"] = str(candidate.get("web_check_status", "not_configured"))
    if scope != "global" or candidate.get("external_evidence_checks"):
        skill["external_evidence_checks"] = list(candidate.get("external_evidence_checks", []))
    return _hydrate_skill_student_metadata(skill)


def _decode_string_list(value: object) -> list[str]:
    decoded = json.loads(str(value))
    if not isinstance(decoded, list):
        return []
    return sorted(str(item) for item in decoded if str(item))


def _payload_references_source(
    payload: dict[str, Any],
    *,
    source_session_id: str,
    source_report_id: str,
) -> bool:
    if str(payload.get("source_session_id", "")) == source_session_id:
        return True
    if source_session_id in _normalized_string_list(
        payload.get("source_session_ids")
    ):
        return True
    if source_report_id in _normalized_string_list(payload.get("source_report_ids")):
        return True
    for pattern in _mapping_list(payload.get("source_turn_patterns")):
        if source_session_id in _normalized_string_list(pattern.get("session_ids")):
            return True
        if source_report_id in _normalized_string_list(
            pattern.get("source_report_ids")
        ):
            return True
    return False


def _stale_global_skill_without_source(
    skill: dict[str, Any],
    *,
    source_session_id: str,
    source_report_id: str,
) -> dict[str, Any]:
    sanitized = dict(skill)
    for key in (
        "teaching_action_plan",
        "problem_pattern",
        "router_index",
        "intervention",
        "effect_tracking",
        "teacher_analysis_context",
        "rag_evidence_items",
        "approval_dialogue",
        "external_evidence_checks",
        "reasoning_pattern_labels",
        "trigger_item_labels",
        "student_visible_summary",
        "learning_action",
        "activation_summary",
        "effect_status_label",
        "scope_label",
    ):
        sanitized.pop(key, None)
    sanitized["title"] = "来源证据已变化的训练 Skill"
    sanitized["description"] = "原 Skill 内容已失效，需基于剩余证据重新生成。"
    sanitized["suggested_strategy"] = "重新生成并完成评审后，方可再次启用。"
    sanitized["related_recommendations"] = []
    sanitized.pop("source_session_id", None)
    sanitized["source_session_ids"] = [
        value
        for value in _normalized_string_list(skill.get("source_session_ids"))
        if value != source_session_id
    ]
    sanitized["source_report_ids"] = [
        value
        for value in _normalized_string_list(skill.get("source_report_ids"))
        if value != source_report_id
    ]
    sanitized_patterns: list[dict[str, Any]] = []
    for pattern in _mapping_list(skill.get("source_turn_patterns")):
        next_pattern = dict(pattern)
        next_pattern["session_ids"] = [
            value
            for value in _normalized_string_list(pattern.get("session_ids"))
            if value != source_session_id
        ]
        next_pattern["source_report_ids"] = [
            value
            for value in _normalized_string_list(pattern.get("source_report_ids"))
            if value != source_report_id
        ]
        if not next_pattern["session_ids"] and not next_pattern["source_report_ids"]:
            continue
        next_pattern["count"] = 0
        next_pattern["source_report_count"] = len(
            next_pattern["source_report_ids"]
        )
        sanitized_patterns.append(next_pattern)
    sanitized["source_turn_patterns"] = sanitized_patterns
    sanitized["source_report_count"] = len(sanitized["source_report_ids"])
    sanitized["support_count"] = 0
    sanitized["status"] = "stale_requires_review"
    sanitized["effect_status"] = "insufficient_samples"
    sanitized["source_summary"] = "来源证据已变化，需重新生成并评审后启用。"
    applies_when = sanitized.get("applies_when")
    if isinstance(applies_when, dict):
        sanitized["applies_when"] = {
            **applies_when,
            "min_support_count": 0,
        }
    return sanitized


def _mapping_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _has_explicit_remaining_source_provenance(
    candidate: dict[str, Any],
) -> bool:
    if (
        str(candidate.get("source_provenance_schema_version", ""))
        != "training_candidate_sources.v1"
    ):
        return False
    if _normalized_string_list(candidate.get("source_session_ids")):
        return True
    if _normalized_string_list(candidate.get("source_report_ids")):
        return True
    return any(
        _normalized_string_list(pattern.get("session_ids"))
        or _normalized_string_list(pattern.get("source_report_ids"))
        for pattern in _mapping_list(candidate.get("source_turn_patterns"))
    )


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
    hydrated_skill = _ensure_skill_memory_fields(hydrated_skill)
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


def _candidate_skill_type(candidate: dict[str, Any], trigger_item_ids: list[str]) -> str:
    explicit_skill_type = _non_empty_string(candidate.get("skill_type"))
    if explicit_skill_type:
        return explicit_skill_type
    if trigger_item_ids and all(item_id.startswith("ht_") for item_id in trigger_item_ids):
        return "history_bundle"
    if trigger_item_ids and all(item_id.startswith("pe_") for item_id in trigger_item_ids):
        return "exam_bundle"
    if trigger_item_ids and all(item_id.startswith(("lab.", "img.", "aux_", "test_")) for item_id in trigger_item_ids):
        return "test_strategy"
    return "reasoning_bridge"


def _ensure_skill_memory_fields(skill: dict[str, Any]) -> dict[str, Any]:
    trigger_item_ids = _normalized_string_list(skill.get("trigger_item_ids"))
    case_ids = _normalized_string_list(skill.get("case_ids"))
    defaults = build_skill_memory_fields(
        pattern_id=_non_empty_string(skill.get("trigger_item_id"))
        or _non_empty_string(skill.get("source_candidate_id"))
        or _non_empty_string(skill.get("skill_id")),
        skill_type=str(skill.get("skill_type", "reasoning_bridge")),
        trigger_item_ids=trigger_item_ids,
        case_ids=case_ids,
        source_report_count=_safe_int(skill.get("source_report_count")),
        support_count=_safe_int(skill.get("support_count")),
        title=_non_empty_string(skill.get("title")),
        description=_non_empty_string(skill.get("description")),
        suggested_strategy=_non_empty_string(skill.get("suggested_strategy")),
        stage_scope=_normalized_string_list(skill.get("stage_scope")),
        effect_status=str(skill.get("effect_status", "insufficient_samples")),
        reasoning_pattern_ids=_normalized_string_list(skill.get("reasoning_pattern_ids")),
        reasoning_pattern_labels=_normalized_string_list(skill.get("reasoning_pattern_labels")),
        trigger_item_labels=resolve_trigger_item_labels(trigger_item_ids, case_ids),
        application_count=_safe_int(_dict(skill.get("effect_tracking")).get("application_count")),
    )
    for key, default_value in defaults.items():
        existing_value = skill.get(key)
        if _has_meaningful_memory_value(existing_value):
            continue
        skill[key] = default_value
    return skill


def _has_meaningful_memory_value(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _scope_label(skill: dict[str, Any]) -> str:
    return "个人 Skill" if str(skill.get("scope", "global")) == "personal" else "全局 Skill"


def _case_title(case_id: str) -> str:
    case_path = CASES_DIR / f"{case_id}.json"
    if not case_path.exists():
        return case_id
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    title = payload.get("case_title")
    return str(title) if title else case_id


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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
