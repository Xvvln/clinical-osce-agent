from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from app.services.rag_knowledge_store import rag_knowledge_store
from app.services.training_skill_policy import build_teaching_action_plan
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

SAFETY_SUFFIX = "仅提示训练步骤和证据链复盘，不透露病例答案或隐藏事实，不提供真实诊疗信息。"
SKILL_APPROVAL_RAG_VISIBILITIES = {"pre_submit_safe", "post_submit_review"}


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

        retrieved_knowledge_context = _retrieve_skill_approval_knowledge_context(reviewed_candidate)
        reviewed_candidate["approval_agent_review"] = {
            "agent_id": self.agent_id,
            "decision": "prepared_for_auto_apply",
            "revision_status": "modified" if changed_fields else "unchanged",
            "changed_fields": changed_fields,
            "reviewed_fields": ["title", "description", "suggested_strategy", "teaching_action_plan"],
            "protected_fields": list(PROTECTED_CANDIDATE_FIELDS),
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
        return reviewed_candidate


def _sanitize_training_text(text: str, protected_terms: list[str] | None = None) -> str:
    sanitized = text
    for forbidden_term in FORBIDDEN_CANDIDATE_TERMS:
        sanitized = sanitized.replace(forbidden_term, SAFE_TERM_REPLACEMENTS[forbidden_term])
    for violation_id, pattern in FORBIDDEN_CANDIDATE_PATTERNS.items():
        sanitized = re.sub(pattern, SAFE_PATTERN_REPLACEMENTS[violation_id], sanitized)
    for protected_term in protected_terms or []:
        if protected_term:
            sanitized = sanitized.replace(protected_term, "本病例标准答案")
    return sanitized.strip()


def _ensure_safety_suffix(text: str) -> str:
    if SAFETY_SUFFIX in text:
        return text
    if not text:
        return SAFETY_SUFFIX
    return f"{text.rstrip('。')}。{SAFETY_SUFFIX}"


def _retrieve_skill_approval_knowledge_context(candidate: dict[str, Any], *, limit: int = 3) -> list[dict[str, Any]]:
    database_path = getattr(rag_knowledge_store, "database_path", None)
    if isinstance(database_path, Path) and not database_path.exists():
        return []

    case_ids = {str(case_id) for case_id in candidate.get("case_ids", []) if str(case_id)}
    scored_items: list[tuple[int, str, dict[str, Any]]] = []
    for item in rag_knowledge_store.list_items():
        if not _skill_approval_can_read_knowledge_item(item, case_ids):
            continue
        score = _score_knowledge_item_for_candidate(candidate, item)
        if score <= 0:
            continue
        knowledge_id = str(item.get("knowledge_id", "")).strip()
        scored_items.append((score, knowledge_id, item))

    return [
        _serialize_approval_knowledge_item(item)
        for _, _, item in sorted(scored_items, key=lambda entry: (-entry[0], entry[1]))[:limit]
    ]


def _skill_approval_can_read_knowledge_item(item: dict[str, Any], case_ids: set[str]) -> bool:
    visibility = str(item.get("visibility", "")).strip()
    if visibility not in SKILL_APPROVAL_RAG_VISIBILITIES:
        return False
    allowed_agents = [str(agent).strip() for agent in item.get("allowed_agents", []) if str(agent).strip()]
    if allowed_agents and "skill_approval" not in allowed_agents:
        return False
    item_case_id = str(item.get("case_id", "")).strip()
    if item_case_id and item_case_id not in case_ids:
        return False
    if str(item.get("scope", "")).strip() == "case" and not item_case_id:
        return False
    return True


def _score_knowledge_item_for_candidate(candidate: dict[str, Any], item: dict[str, Any]) -> int:
    haystack = " ".join(
        [
            str(item.get("knowledge_id", "")),
            str(item.get("title", "")),
            str(item.get("text", "")),
            " ".join(str(tag) for tag in item.get("tags", []) if str(tag)),
        ]
    ).lower()
    return sum(1 for term in _candidate_rag_terms(candidate) if term.lower() in haystack)


def _candidate_rag_terms(candidate: dict[str, Any]) -> list[str]:
    raw_terms = [
        str(candidate.get("title", "")),
        str(candidate.get("description", "")),
        str(candidate.get("suggested_strategy", "")),
        *[str(item_id) for item_id in candidate.get("trigger_item_ids", []) if str(item_id)],
        *[str(case_id) for case_id in candidate.get("case_ids", []) if str(case_id)],
    ]
    terms: set[str] = set()
    for raw_term in raw_terms:
        normalized = raw_term.strip()
        if not normalized:
            continue
        terms.add(normalized)
        terms.update(token for token in re.split(r"[\s,，。；;:：、()（）]+", normalized) if token)
        terms.update(_cjk_ngrams(normalized, min_size=2, max_size=6))
    return sorted(terms, key=lambda term: (-len(term), term))


def _cjk_ngrams(text: str, *, min_size: int, max_size: int) -> set[str]:
    compact_text = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9_]+", "", text)
    if len(compact_text) < min_size:
        return set()
    return {
        compact_text[start : start + size]
        for size in range(min_size, min(max_size, len(compact_text)) + 1)
        for start in range(0, len(compact_text) - size + 1)
    }


def _serialize_approval_knowledge_item(item: dict[str, Any]) -> dict[str, Any]:
    knowledge_id = str(item.get("knowledge_id", "")).strip()
    return {
        "reference": f"rag_knowledge:{knowledge_id}",
        "knowledge_id": knowledge_id,
        "title": str(item.get("title", "")).strip(),
        "snippet": str(item.get("text", "")).strip(),
        "source_id": str(item.get("source_id", "")).strip(),
        "case_id": str(item.get("case_id", "")).strip(),
        "visibility": str(item.get("visibility", "")).strip(),
        "allowed_agents": [str(agent) for agent in item.get("allowed_agents", []) if str(agent)],
    }


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
