from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.training_skill_context_safety import candidate_with_context_safety_review

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "runtime" / "training_skill_candidates.sqlite3"
DATABASE_SCHEMA_VERSION = 2


class TrainingSkillCandidateDeletedError(RuntimeError):
    def __init__(self, candidate_id: str) -> None:
        super().__init__(candidate_id)
        self.candidate_id = candidate_id


class TrainingSkillCandidateOwnershipError(RuntimeError):
    def __init__(self, candidate_id: str) -> None:
        super().__init__(candidate_id)
        self.candidate_id = candidate_id


class TrainingSkillCandidateSourceDeletedError(RuntimeError):
    def __init__(self, source_session_id: str) -> None:
        super().__init__(source_session_id)
        self.source_session_id = source_session_id


@dataclass(frozen=True)
class GlobalCandidateSourceCleanup:
    affected_candidate_ids: tuple[str, ...]
    deleted_candidate_ids: tuple[str, ...]
    stale_candidate_ids: tuple[str, ...]


class TrainingSkillCandidateStore:
    def __init__(self, database_path: Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = database_path

    def save_candidate(self, candidate: dict[str, Any], review: dict[str, Any]) -> None:
        self._initialize()
        payload = {**candidate, "review": review}
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            candidate_id = str(candidate["candidate_id"])
            if self._is_candidate_deleted(connection, candidate_id):
                raise TrainingSkillCandidateDeletedError(candidate_id)
            deleted_source_session_id = self._deleted_source_reference(
                connection,
                payload,
            )
            if deleted_source_session_id is not None:
                raise TrainingSkillCandidateSourceDeletedError(
                    deleted_source_session_id
                )
            connection.execute(
                """
                INSERT INTO training_skill_candidates (candidate_id, candidate_json)
                VALUES (?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET candidate_json = excluded.candidate_json
                """,
                (candidate_id, json.dumps(payload, ensure_ascii=False)),
            )

    def save_candidate_unless_reviewed(self, candidate: dict[str, Any], review: dict[str, Any]) -> bool:
        existing_candidate = self.get_candidate(str(candidate["candidate_id"]))
        if existing_candidate is not None and existing_candidate["review"]["status"] in {"approved", "rejected"}:
            return False
        self.save_candidate(candidate, review)
        return True

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT candidate_json FROM training_skill_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def list_candidate_summaries(self) -> list[dict[str, Any]]:
        self._initialize()
        with sqlite3.connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT candidate_json FROM training_skill_candidates ORDER BY id",
            ).fetchall()
        return [_candidate_summary(candidate_with_context_safety_review(json.loads(row[0]))) for row in rows]

    def approve_candidate(self, candidate_id: str, reviewer_id: str) -> bool:
        return self._set_review_status(candidate_id, reviewer_id, "approved")

    def reject_candidate(self, candidate_id: str, reviewer_id: str) -> bool:
        return self._set_review_status(candidate_id, reviewer_id, "rejected")

    def delete_personal_candidate(
        self,
        *,
        candidate_id: str,
        owner_student_id: str,
        source_session_id: str,
    ) -> bool:
        """Delete one deterministic personal candidate and persist a write fence."""

        _validate_personal_candidate_delete_identity(
            candidate_id=candidate_id,
            owner_student_id=owner_student_id,
            source_session_id=source_session_id,
        )
        self._initialize()
        deleted_at = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            tombstone = connection.execute(
                """
                SELECT scope, owner_student_id, source_session_id
                FROM training_skill_candidate_tombstones
                WHERE candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()
            if tombstone is not None:
                if tuple(str(value) for value in tombstone) != (
                    "personal",
                    owner_student_id,
                    source_session_id,
                ):
                    raise TrainingSkillCandidateOwnershipError(candidate_id)
                return False

            row = connection.execute(
                """
                SELECT candidate_json
                FROM training_skill_candidates
                WHERE candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()
            if row is not None:
                candidate = _decode_candidate(row[0], candidate_id=candidate_id)
                if (
                    str(candidate.get("candidate_id", "")) != candidate_id
                    or str(candidate.get("scope", "")) != "personal"
                    or str(candidate.get("owner_student_id", "")) != owner_student_id
                    or str(candidate.get("source_session_id", "")) != source_session_id
                ):
                    raise TrainingSkillCandidateOwnershipError(candidate_id)

            connection.execute(
                """
                INSERT INTO training_skill_candidate_tombstones (
                    candidate_id,
                    scope,
                    owner_student_id,
                    source_session_id,
                    deleted_at
                )
                VALUES (?, 'personal', ?, ?, ?)
                """,
                (candidate_id, owner_student_id, source_session_id, deleted_at),
            )
            cursor = connection.execute(
                """
                DELETE FROM training_skill_candidates
                WHERE candidate_id = ?
                """,
                (candidate_id,),
            )
        return cursor.rowcount == 1

    def remove_global_source_contributions(
        self,
        *,
        source_session_id: str,
        owner_student_id: str,
        source_report_id: str,
    ) -> GlobalCandidateSourceCleanup:
        if (
            not source_session_id
            or not owner_student_id
            or source_report_id != f"{source_session_id}_report"
        ):
            raise TrainingSkillCandidateOwnershipError(source_session_id)

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
                    deleted_candidate_ids_json,
                    stale_candidate_ids_json
                FROM training_skill_candidate_source_tombstones
                WHERE source_session_id = ?
                """,
                (source_session_id,),
            ).fetchone()
            if existing is not None:
                if str(existing[0]) != owner_student_id or str(existing[1]) != source_report_id:
                    raise TrainingSkillCandidateOwnershipError(source_session_id)
                return _global_candidate_source_cleanup_from_row(existing[2:])

            rows = connection.execute(
                """
                SELECT candidate_id, candidate_json
                FROM training_skill_candidates
                ORDER BY id
                """
            ).fetchall()
            deleted_candidate_ids: list[str] = []
            stale_candidate_ids: list[str] = []
            stale_payloads: list[tuple[str, str]] = []
            for raw_candidate_id, raw_candidate_json in rows:
                candidate_id = str(raw_candidate_id)
                candidate = _decode_candidate(
                    str(raw_candidate_json),
                    candidate_id=candidate_id,
                )
                if str(candidate.get("scope", "global")) != "global":
                    continue
                if not _payload_references_source(
                    candidate,
                    source_session_id=source_session_id,
                    source_report_id=source_report_id,
                ):
                    continue
                review = candidate.get("review", {})
                review_status = (
                    str(review.get("status", ""))
                    if isinstance(review, dict)
                    else ""
                )
                previous_review_status = (
                    str(review.get("previous_status", ""))
                    if isinstance(review, dict)
                    else ""
                )
                if (
                    review_status
                    not in {
                        "approved",
                        "rejected",
                        "stale_requires_review",
                    }
                    and previous_review_status not in {"approved", "rejected"}
                ):
                    deleted_candidate_ids.append(candidate_id)
                    continue
                stale_candidate_ids.append(candidate_id)
                stale_payloads.append(
                    (
                        candidate_id,
                        json.dumps(
                            _stale_global_candidate_without_source(
                                candidate,
                                source_session_id=source_session_id,
                                source_report_id=source_report_id,
                            ),
                            ensure_ascii=False,
                        ),
                    )
                )

            affected_candidate_ids = sorted(
                [*deleted_candidate_ids, *stale_candidate_ids]
            )
            connection.execute(
                """
                INSERT INTO training_skill_candidate_source_tombstones (
                    source_session_id,
                    owner_student_id,
                    source_report_id,
                    affected_candidate_ids_json,
                    deleted_candidate_ids_json,
                    stale_candidate_ids_json,
                    deleted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_session_id,
                    owner_student_id,
                    source_report_id,
                    json.dumps(affected_candidate_ids),
                    json.dumps(sorted(deleted_candidate_ids)),
                    json.dumps(sorted(stale_candidate_ids)),
                    deleted_at,
                ),
            )
            if deleted_candidate_ids:
                placeholders = ",".join("?" for _ in deleted_candidate_ids)
                connection.execute(
                    f"""
                    DELETE FROM training_skill_candidates
                    WHERE candidate_id IN ({placeholders})
                    """,
                    deleted_candidate_ids,
                )
            connection.executemany(
                """
                UPDATE training_skill_candidates
                SET candidate_json = ?
                WHERE candidate_id = ?
                """,
                [(payload, candidate_id) for candidate_id, payload in stale_payloads],
            )
        return GlobalCandidateSourceCleanup(
            affected_candidate_ids=tuple(affected_candidate_ids),
            deleted_candidate_ids=tuple(sorted(deleted_candidate_ids)),
            stale_candidate_ids=tuple(sorted(stale_candidate_ids)),
        )

    def _set_review_status(self, candidate_id: str, reviewer_id: str, status: str) -> bool:
        candidate = self.get_candidate(candidate_id)
        if candidate is None or candidate["review"]["status"] != "ready_for_review":
            return False
        normalized_candidate = candidate_with_context_safety_review(candidate)
        if normalized_candidate["review"]["status"] != "ready_for_review":
            candidate = normalized_candidate
            with sqlite3.connect(self.database_path) as connection:
                connection.execute(
                    "UPDATE training_skill_candidates SET candidate_json = ? WHERE candidate_id = ?",
                    (json.dumps(candidate, ensure_ascii=False), candidate_id),
                )
            return False
        candidate["review"] = {**candidate["review"], "status": status, "reviewer_id": reviewer_id}
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE training_skill_candidates SET candidate_json = ? WHERE candidate_id = ?",
                (json.dumps(candidate, ensure_ascii=False), candidate_id),
            )
        return True

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_skill_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id TEXT NOT NULL UNIQUE,
                    candidate_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_skill_candidate_tombstones (
                    candidate_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    owner_student_id TEXT NOT NULL,
                    source_session_id TEXT NOT NULL,
                    deleted_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_skill_candidate_source_tombstones (
                    source_session_id TEXT PRIMARY KEY,
                    owner_student_id TEXT NOT NULL,
                    source_report_id TEXT NOT NULL,
                    affected_candidate_ids_json TEXT NOT NULL,
                    deleted_candidate_ids_json TEXT NOT NULL,
                    stale_candidate_ids_json TEXT NOT NULL,
                    deleted_at TEXT NOT NULL
                )
                """
            )
            connection.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")

    @staticmethod
    def _is_candidate_deleted(
        connection: sqlite3.Connection,
        candidate_id: str,
    ) -> bool:
        row = connection.execute(
            """
            SELECT 1
            FROM training_skill_candidate_tombstones
            WHERE candidate_id = ?
            """,
            (candidate_id,),
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
            FROM training_skill_candidate_source_tombstones
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


def _validate_personal_candidate_delete_identity(
    *,
    candidate_id: str,
    owner_student_id: str,
    source_session_id: str,
) -> None:
    if (
        not owner_student_id
        or not source_session_id
        or candidate_id != f"personal_skill_candidate_{source_session_id}"
    ):
        raise TrainingSkillCandidateOwnershipError(candidate_id)


def _decode_candidate(value: str, *, candidate_id: str) -> dict[str, Any]:
    candidate = json.loads(value)
    if not isinstance(candidate, dict):
        raise TrainingSkillCandidateOwnershipError(candidate_id)
    return candidate


def _global_candidate_source_cleanup_from_row(
    row: tuple[object, ...],
) -> GlobalCandidateSourceCleanup:
    return GlobalCandidateSourceCleanup(
        affected_candidate_ids=tuple(_decode_string_list(row[0])),
        deleted_candidate_ids=tuple(_decode_string_list(row[1])),
        stale_candidate_ids=tuple(_decode_string_list(row[2])),
    )


def _decode_string_list(value: object) -> list[str]:
    decoded = json.loads(str(value))
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded if str(item)]


def _payload_references_source(
    payload: dict[str, Any],
    *,
    source_session_id: str,
    source_report_id: str,
) -> bool:
    if str(payload.get("source_session_id", "")) == source_session_id:
        return True
    if source_session_id in _string_list(payload.get("source_session_ids")):
        return True
    if source_report_id in _string_list(payload.get("source_report_ids")):
        return True
    for pattern in _mapping_list(payload.get("source_turn_patterns")):
        if source_session_id in _string_list(pattern.get("session_ids")):
            return True
        if source_report_id in _string_list(pattern.get("source_report_ids")):
            return True
    return False


def _stale_global_candidate_without_source(
    candidate: dict[str, Any],
    *,
    source_session_id: str,
    source_report_id: str,
) -> dict[str, Any]:
    sanitized = dict(candidate)
    for key in (
        "teaching_action_plan",
        "problem_pattern",
        "router_index",
        "intervention",
        "effect_tracking",
        "teacher_analysis_context",
        "retrieved_knowledge_context",
        "knowledge_references",
        "rag_evidence_items",
        "approval_dialogue",
        "external_evidence_checks",
        "reasoning_pattern_labels",
        "trigger_item_labels",
        "student_visible_summary",
        "learning_action",
        "activation_summary",
        "source_summary",
    ):
        sanitized.pop(key, None)
    sanitized["title"] = "来源证据已变化的训练候选"
    sanitized["description"] = "原候选内容已失效，需基于剩余证据重新生成。"
    sanitized["suggested_strategy"] = "重新生成并完成评审后，方可再次启用。"
    sanitized["related_recommendations"] = []
    sanitized.pop("source_session_id", None)
    sanitized["source_session_ids"] = [
        value
        for value in _string_list(candidate.get("source_session_ids"))
        if value != source_session_id
    ]
    sanitized["source_report_ids"] = [
        value
        for value in _string_list(candidate.get("source_report_ids"))
        if value != source_report_id
    ]
    sanitized_patterns: list[dict[str, Any]] = []
    for pattern in _mapping_list(candidate.get("source_turn_patterns")):
        next_pattern = dict(pattern)
        next_pattern["session_ids"] = [
            value
            for value in _string_list(pattern.get("session_ids"))
            if value != source_session_id
        ]
        next_pattern["source_report_ids"] = [
            value
            for value in _string_list(pattern.get("source_report_ids"))
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
    applies_when = sanitized.get("applies_when")
    if isinstance(applies_when, dict):
        sanitized["applies_when"] = {
            **applies_when,
            "min_support_count": 0,
        }
    review = sanitized.get("review")
    if not isinstance(review, dict):
        review = {}
    sanitized["review"] = {
        "candidate_id": str(
            review.get("candidate_id")
            or sanitized.get("candidate_id")
            or ""
        ),
        "previous_status": str(
            review.get("previous_status")
            or review.get("status")
            or ""
        ),
        "status": "stale_requires_review",
        "regression_passed": False,
        "stale_reason": "source_session_deleted",
    }
    return sanitized


def _mapping_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _has_explicit_remaining_source_provenance(
    candidate: dict[str, Any],
) -> bool:
    if (
        str(candidate.get("source_provenance_schema_version", ""))
        != "training_candidate_sources.v1"
    ):
        return False
    if _string_list(candidate.get("source_session_ids")):
        return True
    if _string_list(candidate.get("source_report_ids")):
        return True
    return any(
        _string_list(pattern.get("session_ids"))
        or _string_list(pattern.get("source_report_ids"))
        for pattern in _mapping_list(candidate.get("source_turn_patterns"))
    )


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    review = candidate["review"]
    return {
        "candidate_id": candidate["candidate_id"],
        "trigger_item_id": candidate["trigger_item_id"],
        "trigger_item_ids": list(candidate.get("trigger_item_ids", [])),
        "case_ids": list(candidate.get("case_ids", [])),
        "skill_type": str(candidate.get("skill_type", "")),
        "stage_scope": list(candidate.get("stage_scope", [])),
        "effect_status": str(candidate.get("effect_status", "")),
        "related_recommendations": list(candidate.get("related_recommendations", [])),
        "title": candidate["title"],
        "status": review["status"],
        "regression_passed": review["regression_passed"],
        "source_report_count": candidate["source_report_count"],
        "support_count": candidate["support_count"],
    }


training_skill_candidate_store = TrainingSkillCandidateStore()
