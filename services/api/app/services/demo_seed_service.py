from __future__ import annotations

from typing import Any

from app.services.auth_store import AuthStore
from app.services.osce_session_service import OsceSessionService
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_policy import build_prohibited_content_policy, build_success_metrics, build_teaching_action_plan

DEMO_STUDENT_EMAIL = "student-demo@example.test"
DEMO_STUDENT_PASSWORD = "safe-student-password"
DEMO_STUDENT_DISPLAY_NAME = "演示学生"
DEMO_ADMIN_DISPLAY_NAME = "演示管理员"
DEMO_CANDIDATE_ID = "demo_skill_candidate_abdominal_pain_history_bundle"
DEMO_TRIGGER_ITEM_ID = "training_pattern_abdominal_pain_history_bundle"
DEMO_SKILL_ID = f"skill_{DEMO_TRIGGER_ITEM_ID}"
DEMO_CASE_ID = "appendicitis_001"
DEMO_TRIGGER_ITEM_IDS = ["ht_migration", "ht_associated_gi", "ax_ua", "rs_exclude"]
DEMO_STAGE_SCOPE = ["case_intro", "history_taking", "auxiliary_test", "diagnosis_submission"]


def seed_demo_data(
    *,
    auth_store: AuthStore,
    osce_service: OsceSessionService,
    candidate_store: TrainingSkillCandidateStore,
    reviewer_email: str,
    admin_email: str,
    admin_password: str,
) -> dict[str, Any]:
    student = auth_store.upsert_user_password(
        DEMO_STUDENT_EMAIL,
        DEMO_STUDENT_PASSWORD,
        DEMO_STUDENT_DISPLAY_NAME,
    )
    auth_store.upsert_user_password(admin_email, admin_password, DEMO_ADMIN_DISPLAY_NAME)

    seeded_sessions: list[dict[str, str]] = []
    seeded_reports: list[str] = []
    existing_report_count = _demo_report_count(osce_service, student["user_id"])
    for script_index in range(max(0, 2 - existing_report_count)):
        session_id = _create_demo_report_session(osce_service, student["user_id"], script_index)
        seeded_sessions.append({"session_id": session_id, "case_id": DEMO_CASE_ID, "purpose": "source_report"})
        seeded_reports.append(session_id)

    candidate = _demo_skill_candidate()
    if candidate_store.get_candidate(DEMO_CANDIDATE_ID) is None:
        candidate_store.save_candidate(candidate, _ready_for_review_payload())
        _append_demo_candidate_event(osce_service, reviewer_email, "admin_skill_candidate_generated")
    stored_candidate = candidate_store.get_candidate(DEMO_CANDIDATE_ID)
    if stored_candidate is not None and stored_candidate.get("review", {}).get("status") == "ready_for_review":
        candidate_store.approve_candidate(DEMO_CANDIDATE_ID, reviewer_email)
        _append_demo_candidate_event(osce_service, reviewer_email, "admin_skill_candidate_approved")

    approved_candidate = candidate_store.get_candidate(DEMO_CANDIDATE_ID)
    if approved_candidate is not None:
        osce_service.training_skill_store.enable_candidate(approved_candidate)

    if not _has_demo_skill_application(osce_service, student["user_id"]):
        post_skill_session = osce_service.create_session(DEMO_CASE_ID, student["user_id"])
        seeded_sessions.append(
            {
                "session_id": str(post_skill_session["session_id"]),
                "case_id": DEMO_CASE_ID,
                "purpose": "post_skill_application",
            }
        )

    enabled_skill = osce_service.training_skill_store.get_skill(DEMO_SKILL_ID)
    stored_candidate = candidate_store.get_candidate(DEMO_CANDIDATE_ID)
    return {
        "student": {
            "email": DEMO_STUDENT_EMAIL,
            "password": DEMO_STUDENT_PASSWORD,
            "display_name": DEMO_STUDENT_DISPLAY_NAME,
        },
        "admin": {
            "email": admin_email,
            "password": admin_password,
            "display_name": DEMO_ADMIN_DISPLAY_NAME,
        },
        "sessions": seeded_sessions,
        "session_count": len(seeded_sessions),
        "report_count": len(seeded_reports),
        "candidate": {
            "candidate_id": DEMO_CANDIDATE_ID,
            "status": str(stored_candidate.get("review", {}).get("status")) if stored_candidate else "missing",
        },
        "enabled_skill": {
            "skill_id": DEMO_SKILL_ID,
            "status": str(enabled_skill.get("status")) if enabled_skill else "missing",
        },
    }


def _demo_report_count(osce_service: OsceSessionService, student_id: str) -> int:
    return sum(
        1
        for session in osce_service.session_store.list_user_session_summaries(student_id)
        if osce_service.report_store.get_report(str(session["session_id"])) is not None
    )


def _create_demo_report_session(osce_service: OsceSessionService, student_id: str, script_index: int) -> str:
    session = osce_service.create_session(DEMO_CASE_ID, student_id)
    session_id = str(session["session_id"])
    first_message = "什么时候开始疼的？" if script_index == 0 else "有没有恶心发热？"
    osce_service.handle_message(session_id, first_message)
    osce_service.request_physical_exam(session_id, "abd.palpation.rebound")
    osce_service.request_auxiliary_test(session_id, "lab.cbc")
    osce_service.submit_diagnosis(
        session_id,
        "急性阑尾炎",
        "右下腹痛、反跳痛和白细胞升高支持诊断，但鉴别诊断和排除证据仍需补充。",
    )
    osce_service.get_report(session_id)
    return session_id


def _has_demo_skill_application(osce_service: OsceSessionService, student_id: str) -> bool:
    for session in osce_service.session_store.list_user_session_summaries(student_id):
        events = osce_service.training_event_store.list_session_events(str(session["session_id"]))
        if any(
            event["student_id"] == student_id
            and event["event_type"] == "training_skill_applied"
            and event.get("payload", {}).get("skill_id") == DEMO_SKILL_ID
            for event in events
        ):
            return True
    return False


def _demo_skill_candidate() -> dict[str, Any]:
    suggested_strategy = "训练学生先按腹痛演变、伴随症状、排除性检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。"
    return {
        "candidate_id": DEMO_CANDIDATE_ID,
        "pattern_id": DEMO_TRIGGER_ITEM_ID,
        "trigger_item_id": DEMO_TRIGGER_ITEM_ID,
        "trigger_item_ids": list(DEMO_TRIGGER_ITEM_IDS),
        "case_ids": [DEMO_CASE_ID],
        "skill_type": "history_bundle",
        "stage_scope": list(DEMO_STAGE_SCOPE),
        "applies_when": {
            "case_ids": [DEMO_CASE_ID],
            "stage_scope": list(DEMO_STAGE_SCOPE),
            "trigger_item_ids": list(DEMO_TRIGGER_ITEM_IDS),
            "current_missing_evidence": list(DEMO_TRIGGER_ITEM_IDS),
            "min_support_count": 2,
        },
        "effect_status": "insufficient_samples",
        "title": "腹痛问诊与排除性证据链训练",
        "description": "演示数据中多轮训练反复暴露腹痛演变、伴随症状、尿常规排除和鉴别诊断证据链不足。",
        "suggested_strategy": suggested_strategy,
        "status": "draft",
        "source_report_count": 2,
        "support_count": 2,
        "related_recommendations": [
            f"rubric:{DEMO_CASE_ID}_rubric.item.ht_migration",
            f"rubric:{DEMO_CASE_ID}_rubric.item.ht_associated_gi",
            f"rubric:{DEMO_CASE_ID}_rubric.item.ax_ua",
            f"rubric:{DEMO_CASE_ID}_rubric.item.rs_exclude",
        ],
        "teaching_action_plan": build_teaching_action_plan(
            stage_scope=list(DEMO_STAGE_SCOPE),
            trigger_item_ids=list(DEMO_TRIGGER_ITEM_IDS),
            suggested_strategy=suggested_strategy,
        ),
        "prohibited_content_policy": build_prohibited_content_policy(),
        "success_metrics": build_success_metrics(),
    }


def _ready_for_review_payload() -> dict[str, Any]:
    return {
        "candidate_id": DEMO_CANDIDATE_ID,
        "status": "ready_for_review",
        "regression_passed": True,
        "evaluation_total_cases": 1,
        "evaluation_passed_cases": 1,
        "evaluation_failed_cases": 0,
        "blocking_failures": [],
    }


def _append_demo_candidate_event(osce_service: OsceSessionService, reviewer_email: str, event_type: str) -> None:
    osce_service.training_event_store.append_event(
        session_id=DEMO_CANDIDATE_ID,
        case_id=DEMO_TRIGGER_ITEM_ID,
        student_id=reviewer_email,
        event_type=event_type,
        payload={
            "candidate_id": DEMO_CANDIDATE_ID,
            "skill_id": DEMO_SKILL_ID,
            "support_count": 2,
            "source_report_count": 2,
        },
    )
