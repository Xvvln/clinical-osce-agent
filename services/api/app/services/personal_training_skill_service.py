from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from app.models.case import Case
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_auto_approval_service import AUTO_APPROVAL_AGENT_ID, TrainingSkillApprovalAgent
from app.services.training_skill_candidate_service import (
    TrainingSkillCandidateContext,
    TrainingSkillCandidateGenerator,
    TrainingSkillCandidateMissedItem,
    create_default_training_skill_candidate_generator,
)
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_regression_gate import TrainingSkillRegressionGate
from app.services.training_skill_store import TrainingSkillStore

MAX_APPROVAL_AGENT_ROUNDS = 3


def build_not_ready_personal_skill_payload() -> dict[str, Any]:
    return {
        "personal_skill_candidate": {
            "status": "not_complete",
            "reason": "final_submission_required",
            "scope": "personal",
            "candidate_id": None,
            "skill_id": None,
            "web_check_status": "not_configured",
            "external_evidence_checks": [],
        },
        "ai_reflection_review": {
            "status": "not_ready",
            "reason": "final_submission_required",
            "summary": "提交诊断并生成完整评分报告后，系统会生成 AI 复盘和下一轮个人训练 Skill。",
            "source_references": [],
            "source_reference_items": [],
        },
    }


class PersonalTrainingSkillService:
    def __init__(
        self,
        *,
        generator: TrainingSkillCandidateGenerator | None = None,
        approval_agent: TrainingSkillApprovalAgent | None = None,
        regression_gate: TrainingSkillRegressionGate | None = None,
    ) -> None:
        self._generator = generator or create_default_training_skill_candidate_generator()
        self._approval_agent = approval_agent or TrainingSkillApprovalAgent()
        self._regression_gate = regression_gate or TrainingSkillRegressionGate()

    def generate_for_completed_session(
        self,
        *,
        session: Any,
        case: Case,
        report: dict[str, Any],
        candidate_store: TrainingSkillCandidateStore,
        skill_store: TrainingSkillStore,
        event_store: TrainingEventStore,
    ) -> dict[str, Any]:
        candidate_id = _personal_candidate_id(str(session.session_id))
        existing_candidate = candidate_store.get_candidate(candidate_id)
        if existing_candidate is not None:
            return {
                "personal_skill_candidate": _report_candidate_summary(existing_candidate),
                "ai_reflection_review": _build_ai_reflection_review(report),
            }

        candidate = self._generate_candidate(session=session, case=case, report=report)
        candidate, review, approval_dialogue = self._review_candidate(candidate, case)
        candidate["approval_dialogue"] = approval_dialogue
        candidate["review"] = review
        candidate_store.save_candidate(candidate, review)
        if review["status"] == "approved":
            skill_store.enable_candidate(candidate)

        skill_id = _personal_skill_id(str(session.session_id))
        _append_personal_skill_events(
            candidate=candidate,
            review=review,
            event_store=event_store,
            session=session,
            skill_id=skill_id,
        )
        return {
            "personal_skill_candidate": _report_candidate_summary(candidate),
            "ai_reflection_review": _build_ai_reflection_review(report),
        }

    def _generate_candidate(self, *, session: Any, case: Case, report: dict[str, Any]) -> dict[str, Any]:
        session_id = str(session.session_id)
        report_id = str(report.get("report_id") or f"{session_id}_report")
        missed_items = _missed_items_from_report(report, case.case_id)
        context = TrainingSkillCandidateContext(
            pattern_id=f"personal_{session_id}",
            missed_items=missed_items,
            support_count=1,
            case_ids=[case.case_id],
            source_report_count=1,
            related_recommendations=_related_recommendations(report),
        )
        candidate = self._generator.generate_candidate(context)
        trigger_item_ids = [item.item_id for item in missed_items] or ["reflection:structured_expression"]
        stage_scope = ["case_intro", "history_taking", "physical_exam", "auxiliary_testing", "diagnosis_submission"]
        candidate.update(
            {
                "candidate_id": _personal_candidate_id(session_id),
                "trigger_item_id": f"personal_{session_id}",
                "trigger_item_ids": trigger_item_ids,
                "case_ids": [case.case_id],
                "scope": "personal",
                "owner_student_id": str(session.student_id),
                "source_session_id": session_id,
                "source_session_ids": [session_id],
                "source_report_ids": [report_id],
                "source_report_count": 1,
                "support_count": 1,
                "stage_scope": stage_scope,
                "effect_status": "insufficient_samples",
                "applies_when": {
                    "case_ids": [case.case_id],
                    "stage_scope": stage_scope,
                    "trigger_item_ids": trigger_item_ids,
                    "current_missing_evidence": trigger_item_ids,
                    "min_support_count": 1,
                    "owner_student_id": str(session.student_id),
                    "source_session_id": session_id,
                },
                "rag_evidence_items": _rag_evidence_items(report),
                "web_check_status": "not_configured",
                "external_evidence_checks": [],
            }
        )
        if candidate.get("title") == "OSCE 训练模式纠偏提示":
            candidate["title"] = "个人复盘训练 Skill"
        return candidate

    def _review_candidate(self, candidate: dict[str, Any], case: Case) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        current_candidate = deepcopy(candidate)
        approval_dialogue: list[dict[str, Any]] = []
        protected_terms = [case.diagnosis.main_diagnosis, *case.diagnosis.main_diagnosis_synonyms]
        review: dict[str, Any] = {}
        for round_index in range(1, MAX_APPROVAL_AGENT_ROUNDS + 1):
            reviewed_candidate = self._approval_agent.review_candidate(
                current_candidate,
                protected_terms=protected_terms,
            )
            review = self._regression_gate.review_candidate(reviewed_candidate, _passing_batch_result())
            approved = review["status"] == "ready_for_review"
            agent_review = reviewed_candidate.get("approval_agent_review", {})
            approval_dialogue.append(
                {
                    "round": round_index,
                    "agent_id": AUTO_APPROVAL_AGENT_ID,
                    "decision": "approved" if approved else "revise",
                    "revision_status": agent_review.get("revision_status", "unchanged"),
                    "changed_fields": list(agent_review.get("changed_fields", [])),
                    "rag_reference_count": len(reviewed_candidate.get("rag_evidence_items", [])),
                    "web_check_status": reviewed_candidate.get("web_check_status", "not_configured"),
                    "blocking_failures": list(review.get("blocking_failures", [])),
                    "candidate_safety_violations": list(review.get("candidate_safety_violations", [])),
                    "candidate_context_violations": list(review.get("candidate_context_violations", [])),
                }
            )
            current_candidate = reviewed_candidate
            if approved:
                return current_candidate, {
                    **review,
                    "status": "approved",
                    "reviewer_id": AUTO_APPROVAL_AGENT_ID,
                    "approval_mode": "auto_agent_personal",
                }, approval_dialogue
        return current_candidate, {
            **review,
            "status": "blocked_by_regression",
            "reviewer_id": AUTO_APPROVAL_AGENT_ID,
            "approval_mode": "auto_agent_personal",
        }, approval_dialogue


def _passing_batch_result() -> Any:
    return SimpleNamespace(
        total_cases=0,
        passed_cases=0,
        failed_cases=0,
        results=[],
        passed=True,
        total_duration_ms=0,
    )


def _missed_items_from_report(report: dict[str, Any], case_id: str) -> list[TrainingSkillCandidateMissedItem]:
    missed_items = [str(item_id) for item_id in report.get("missed_items", []) if str(item_id)]
    if not missed_items:
        missed_items = ["reflection:structured_expression"]
    return [
        TrainingSkillCandidateMissedItem(
            item_id=item_id,
            count=1,
            case_ids=[case_id],
        )
        for item_id in missed_items[:8]
    ]


def _related_recommendations(report: dict[str, Any]) -> list[str]:
    references = [
        str(recommendation.get("reference"))
        for recommendation in report.get("knowledge_recommendations", [])
        if isinstance(recommendation, dict) and recommendation.get("reference")
    ]
    if references:
        return references
    return [str(reference) for reference in report.get("source_references", [])[:8]]


def _rag_evidence_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    source_items = report.get("source_reference_items", [])
    if not isinstance(source_items, list):
        return []
    return [
        {
            "reference": str(item.get("reference", "")),
            "source_type": str(item.get("source_type", "")),
            "title": str(item.get("title", "")),
            "metadata": item.get("metadata", {}),
        }
        for item in source_items
        if isinstance(item, dict) and item.get("reference")
    ][:12]


def _build_ai_reflection_review(report: dict[str, Any]) -> dict[str, Any]:
    missed_items = [str(item_id) for item_id in report.get("missed_items", [])]
    source_reference_items = _rag_evidence_items(report)
    source_references = [item["reference"] for item in source_reference_items]
    if missed_items:
        summary = f"本轮主要问题集中在 {len(missed_items)} 个训练点：证据采集、鉴别诊断或推理表达仍有缺口。"
        teacher_feedback = "建议下一轮先说明为什么要问、查或检验，再把证据串成支持与排除依据。"
    else:
        summary = "本轮评分项覆盖较完整，后续可继续训练结构化表达和迁移到相似病例。"
        teacher_feedback = "保持先证据、再假设、后结论的节奏，重点提升表达清晰度。"
    return {
        "status": "generated",
        "summary": summary,
        "mistake_patterns": missed_items[:8],
        "teacher_feedback": teacher_feedback,
        "next_focus": "下一轮 Coach 会优先围绕本轮个人 Skill 给出针对性提示。",
        "source_references": source_references,
        "source_reference_items": source_reference_items,
        "generated_by": "personal_training_skill_agent",
        "safety_note": "AI 复盘仅用于 OSCE 教学训练，不改变病例事实、rubric、标准诊断或评分规则。",
    }


def _append_personal_skill_events(
    *,
    candidate: dict[str, Any],
    review: dict[str, Any],
    event_store: TrainingEventStore,
    session: Any,
    skill_id: str,
) -> None:
    event_store.append_event(
        session_id=str(session.session_id),
        case_id=str(session.case_id),
        student_id=str(session.student_id),
        event_type="personal_training_skill_generated",
        payload={
            "candidate_id": candidate["candidate_id"],
            "skill_id": skill_id if review["status"] == "approved" else None,
            "review_status": review["status"],
            "scope": "personal",
            "web_check_status": candidate.get("web_check_status", "not_configured"),
        },
    )
    for event_type, payload in [
        (
            "personal_skill_candidate_generated",
            {
                "candidate_id": candidate["candidate_id"],
                "source_session_id": candidate["source_session_id"],
                "source_report_ids": list(candidate.get("source_report_ids", [])),
            },
        ),
        (
            "personal_skill_candidate_agent_reviewed",
            {
                "candidate_id": candidate["candidate_id"],
                "review_status": review["status"],
                "approval_dialogue": list(candidate.get("approval_dialogue", [])),
                "web_check_status": candidate.get("web_check_status", "not_configured"),
            },
        ),
    ]:
        event_store.append_event(
            session_id=str(candidate["candidate_id"]),
            case_id=str(candidate["trigger_item_id"]),
            student_id=AUTO_APPROVAL_AGENT_ID,
            event_type=event_type,
            payload=payload,
        )
    if review["status"] == "approved":
        event_store.append_event(
            session_id=str(candidate["candidate_id"]),
            case_id=str(candidate["trigger_item_id"]),
            student_id=AUTO_APPROVAL_AGENT_ID,
            event_type="personal_skill_candidate_auto_enabled",
            payload={
                "candidate_id": candidate["candidate_id"],
                "skill_id": skill_id,
                "scope": "personal",
                "owner_student_id": candidate["owner_student_id"],
            },
        )


def _report_candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    review = candidate.get("review", {})
    skill_id = _personal_skill_id(str(candidate.get("source_session_id", "") or "").strip())
    if not skill_id:
        skill_id = f"skill_{candidate['trigger_item_id']}"
    return {
        "status": review.get("status", candidate.get("status", "draft")),
        "candidate_id": candidate["candidate_id"],
        "skill_id": skill_id,
        "title": candidate["title"],
        "scope": candidate.get("scope", "personal"),
        "owner_student_id": candidate.get("owner_student_id", ""),
        "source_session_id": candidate.get("source_session_id", ""),
        "source_report_ids": list(candidate.get("source_report_ids", [])),
        "trigger_item_ids": list(candidate.get("trigger_item_ids", [])),
        "review": review,
        "approval_agent_review": candidate.get("approval_agent_review", {}),
        "approval_dialogue": list(candidate.get("approval_dialogue", [])),
        "rag_evidence_items": list(candidate.get("rag_evidence_items", [])),
        "web_check_status": candidate.get("web_check_status", "not_configured"),
        "external_evidence_checks": list(candidate.get("external_evidence_checks", [])),
    }


def _personal_candidate_id(session_id: str) -> str:
    return f"personal_skill_candidate_{session_id}"


def _personal_skill_id(session_id: str) -> str:
    return f"skill_personal_{session_id}" if session_id else ""


personal_training_skill_service = PersonalTrainingSkillService()
