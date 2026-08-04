from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
import base64
import json
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
import yaml

from app import main
from app.graph.osce_graph import build_osce_graph
from app.services import agent_rag_context_service as agent_rag_context_module
from app.services import training_skill_auto_approval_service as auto_approval_module
from app.services import retrieval_index as retrieval_index_module
from app.services import gemini_patient_responder as gemini_patient_responder_module
from app.services.agent_rag_context_service import retrieve_agent_context
from app.services.admin_audit_store import AdminAuditStore
from app.services.admin_asset_version_store import AdminAssetVersionStore
from app.services.admin_evaluation_config_store import AdminEvaluationConfigStore
from app.services.auth_store import AuthStore
from app.services.api_call_log_service import ApiCallLogStore
from app.services.classroom_store import ClassroomStore
from app.services.evaluation_result_store import EvaluationResultStore
from app.services.evaluation_runner import EvaluationBatchResult, EvaluationResult
from app.services.osce_session_service import OsceSession, OsceSessionService, osce_session_service
from app.services.osce_session_store import OsceSessionStore
from app.services.report_store import ReportStore
from app.services.rag_document_ingestion_service import RagDocumentChunk
from app.services.rag_knowledge_store import RagKnowledgeStore
from app.services.retrieval_index import RetrievalDocument
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_candidate_service import TemplateTrainingSkillCandidateGenerator, TrainingSkillCandidateService
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_store import TrainingSkillStore
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services.training_skill_auto_approval_service import TrainingSkillAutoApprovalSettingsStore


@pytest.fixture(autouse=True)
def isolate_training_skill_auto_approval_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "training_skill_auto_approval_settings_store",
        TrainingSkillAutoApprovalSettingsStore(tmp_path / "training_skill_auto_approval.sqlite3"),
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "classroom_store",
        ClassroomStore(tmp_path / "classrooms.sqlite3"),
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "admin_audit_store",
        AdminAuditStore(tmp_path / "admin_audit.sqlite3"),
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "admin_asset_version_store",
        AdminAssetVersionStore(tmp_path / "admin_asset_versions.sqlite3"),
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "admin_evaluation_config_store",
        AdminEvaluationConfigStore(tmp_path / "admin_evaluation_config.sqlite3"),
        raising=False,
    )


@contextmanager
def authenticated_admin_client(
    tmp_path,
    monkeypatch,
    *,
    raise_server_exceptions: bool = True,
) -> Iterator[TestClient]:
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"), raising=False)
    with TestClient(main.app, raise_server_exceptions=raise_server_exceptions) as client:
        response = client.post(
            "/api/auth/login",
            json={
                "email": main._get_demo_admin_email(),
                "password": main._get_demo_admin_password(),
            },
        )
        assert response.status_code == 200
        yield client


def load_case_and_rubric_payload(case_id: str = "appendicitis_001") -> tuple[dict[str, object], dict[str, object]]:
    repo_root = Path(__file__).resolve().parents[3]
    case_payload = json.loads((repo_root / "data" / "cases" / f"{case_id}.json").read_text(encoding="utf-8"))
    rubric_payload = yaml.safe_load((repo_root / "data" / "rubrics" / f"{case_id}_rubric.yaml").read_text(encoding="utf-8"))
    return case_payload, rubric_payload


def canonical_patient_responder(request: object) -> str:
    return str(getattr(request, "canonical_answer"))


def configure_case_import_directories(tmp_path, monkeypatch) -> tuple[Path, Path]:
    cases_dir = tmp_path / "cases"
    rubrics_dir = tmp_path / "rubrics"
    cases_dir.mkdir()
    rubrics_dir.mkdir()
    monkeypatch.setattr(main, "CASES_DIR", cases_dir, raising=False)
    monkeypatch.setattr(main, "RUBRICS_DIR", rubrics_dir, raising=False)
    return cases_dir, rubrics_dir


def mock_vector_rag_hits_for_store(monkeypatch, store: RagKnowledgeStore) -> None:
    def fake_search_retrieval_documents(
        query: str,
        limit: int,
        *,
        allowed_references: set[str],
    ) -> list[RetrievalDocument]:
        return [
            RetrievalDocument(
                reference=f"rag_knowledge:{item['knowledge_id']}",
                source_type="rag_knowledge",
                title=str(item.get("title", "")),
                snippet=str(item.get("text", "")),
                score=max(0.0, 1.0 - index * 0.01),
            )
            for index, item in enumerate(store.list_items())
            if f"rag_knowledge:{item['knowledge_id']}" in allowed_references
        ][:limit]

    monkeypatch.setattr(
        agent_rag_context_module,
        "search_retrieval_documents",
        fake_search_retrieval_documents,
        raising=False,
    )


def expected_training_skill_action_plan(stage_scope: list[str], trigger_item_ids: list[str], suggested_strategy: str) -> list[dict[str, object]]:
    return [
        {
            "action_type": "hint_ladder",
            "level": 1,
            "stage_scope": stage_scope,
            "trigger_item_ids": trigger_item_ids,
            "message_template": suggested_strategy,
        },
        {
            "action_type": "reflection_prompt",
            "level": 1,
            "stage_scope": ["diagnosis_submission"],
            "trigger_item_ids": trigger_item_ids,
            "message_template": "训练结束后，请对照本轮反复漏掉的评分项复盘证据链，不补写标准答案或隐藏事实。",
        },
    ]


def expected_training_skill_policy() -> dict[str, object]:
    return {
        "forbid_main_diagnosis": True,
        "forbid_hidden_facts": True,
        "forbid_test_results": True,
        "forbid_treatment_plan": True,
        "forbid_dose": True,
        "allowed_scope": "teaching_strategy_only",
    }


def expected_training_skill_success_metrics() -> list[str]:
    return [
        "target_rubric_item_recovery_rate",
        "stage_completion_rate",
        "hint_after_skill_usage",
    ]


def without_skill_memory_fields(skill: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in skill.items()
        if key
        not in {
            "memory_layer",
            "skill_memory_version",
            "problem_pattern",
            "router_index",
            "intervention",
            "effect_tracking",
        }
    }


def test_admin_endpoints_require_login(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"), raising=False)

    with TestClient(main.app) as unauthenticated_client:
        responses = [
            unauthenticated_client.get("/api/admin/evolution/candidates"),
            unauthenticated_client.get("/api/admin/evolution/candidates/missing_candidate"),
            unauthenticated_client.get("/api/admin/evolution/candidates/missing_candidate/events"),
            unauthenticated_client.get("/api/admin/evolution/events"),
            unauthenticated_client.get("/api/admin/evolution/settings"),
            unauthenticated_client.patch("/api/admin/evolution/settings", json={"auto_apply_enabled": True}),
            unauthenticated_client.get("/api/admin/evolution/skill-effects"),
            unauthenticated_client.post("/api/admin/evolution/candidates/generate"),
            unauthenticated_client.post("/api/admin/evolution/approve", json={"candidate_id": "missing_candidate"}),
            unauthenticated_client.post("/api/admin/evolution/reject", json={"candidate_id": "missing_candidate"}),
            unauthenticated_client.get("/api/admin/insights"),
            unauthenticated_client.get("/api/admin/learning-analytics"),
            unauthenticated_client.get("/api/admin/users"),
            unauthenticated_client.post(
                "/api/admin/users",
                json={"email": "new@example.test", "password": "safe-password", "display_name": "新用户"},
            ),
            unauthenticated_client.patch("/api/admin/users/missing-user", json={"status": "disabled"}),
            unauthenticated_client.post("/api/admin/users/missing-user/reset-password", json={"password": "new-password"}),
            unauthenticated_client.delete("/api/admin/users/missing-user"),
            unauthenticated_client.get("/api/admin/classrooms"),
            unauthenticated_client.post("/api/admin/classrooms/import", json={"csv_text": "班级名称\n一班"}),
            unauthenticated_client.post(
                "/api/admin/classrooms",
                json={"name": "临床一班", "member_user_ids": []},
            ),
            unauthenticated_client.put(
                "/api/admin/classrooms/missing-classroom",
                json={"name": "临床一班", "member_user_ids": []},
            ),
            unauthenticated_client.delete("/api/admin/classrooms/missing-classroom"),
            unauthenticated_client.post(
                "/api/admin/classrooms/missing-classroom/members/transfer",
                json={"target_classroom_id": "target", "member_user_ids": ["member"]},
            ),
            unauthenticated_client.get("/api/admin/evaluations"),
            unauthenticated_client.get("/api/admin/evaluations/missing_batch"),
            unauthenticated_client.get("/api/admin/evaluation-config"),
            unauthenticated_client.delete("/api/admin/evaluation-cases/custom_case"),
            unauthenticated_client.delete("/api/admin/evaluation-suites/custom_suite"),
            unauthenticated_client.patch(
                "/api/admin/evaluation-schedule",
                json={"enabled": False, "suite_id": "default_regression", "interval_minutes": 60},
            ),
            unauthenticated_client.post("/api/admin/evals/run", json={"batch_id": "batch_manual"}),
            unauthenticated_client.get("/api/cases/appendicitis_001/raw"),
            unauthenticated_client.get("/api/admin/cases/appendicitis_001/raw"),
            unauthenticated_client.patch("/api/admin/cases/appendicitis_001/raw", json={"case_title": "演示病例"}),
            unauthenticated_client.get("/api/admin/cases/appendicitis_001/assets"),
            unauthenticated_client.put(
                "/api/admin/cases/appendicitis_001/assets",
                json={"case": {}, "rubric": {}, "change_note": "测试"},
            ),
            unauthenticated_client.post(
                "/api/admin/cases/appendicitis_001/review",
                json={"review_status": "approved", "medical_review_note": "测试"},
            ),
            unauthenticated_client.get("/api/admin/cases/appendicitis_001/versions"),
            unauthenticated_client.get("/api/admin/cases/appendicitis_001/diff?from_version=1&to_version=2"),
            unauthenticated_client.post("/api/admin/cases/appendicitis_001/rollback", json={"version": 1}),
            unauthenticated_client.post("/api/admin/cases/validate", json={"case": {}, "rubric": {}}),
            unauthenticated_client.post("/api/admin/cases/import", json={"case": {}, "rubric": {}}),
            unauthenticated_client.get("/api/admin/rubrics/appendicitis_001_rubric"),
            unauthenticated_client.patch("/api/admin/rubrics/appendicitis_001_rubric/items/ht_onset", json={"description": "追问起病时间"}),
            unauthenticated_client.get("/api/admin/sources"),
            unauthenticated_client.post(
                "/api/admin/sources",
                json={"source_id": "source_demo", "source_name": "来源", "data_type": "reference"},
            ),
            unauthenticated_client.put(
                "/api/admin/sources/source_demo",
                json={"source_id": "source_demo", "source_name": "来源", "data_type": "reference"},
            ),
            unauthenticated_client.post(
                "/api/admin/sources/source_demo/review",
                json={"last_reviewed_at": "2026-08-04", "review_basis": "测试"},
            ),
            unauthenticated_client.delete("/api/admin/sources/source_demo"),
            unauthenticated_client.get("/api/admin/sources/source_demo/versions"),
            unauthenticated_client.get("/api/admin/sources/source_demo/diff?from_version=1&to_version=2"),
            unauthenticated_client.post("/api/admin/sources/source_demo/rollback", json={"version": 1}),
            unauthenticated_client.get("/api/admin/model-config"),
            unauthenticated_client.get("/api/admin/model-api-logs"),
            unauthenticated_client.get("/api/admin/audit-events"),
            unauthenticated_client.get("/api/admin/audit-events/export?format=json"),
            unauthenticated_client.get("/api/admin/retrieval-eval"),
            unauthenticated_client.get("/api/admin/rag/knowledge"),
            unauthenticated_client.post("/api/admin/rag/knowledge", json={}),
            unauthenticated_client.get("/api/admin/rag/documents"),
            unauthenticated_client.post("/api/admin/rag/documents", json={}),
            unauthenticated_client.patch("/api/admin/rag/documents/missing_document/enabled", json={"enabled": False}),
            unauthenticated_client.delete("/api/admin/rag/documents/missing_document"),
            unauthenticated_client.get("/api/admin/rag/knowledge/case:appendicitis_001:teaching:history_migration"),
            unauthenticated_client.delete("/api/admin/rag/knowledge/case:appendicitis_001:teaching:history_migration"),
            unauthenticated_client.get("/api/admin/reports"),
            unauthenticated_client.get("/api/admin/reports/export?format=json"),
            unauthenticated_client.get("/api/admin/reports/missing_report"),
            unauthenticated_client.get("/api/admin/sessions"),
            unauthenticated_client.get("/api/admin/procedure-simulation-audits"),
            unauthenticated_client.get("/api/admin/sessions/missing_session/report"),
            unauthenticated_client.get("/api/admin/sessions/missing_session/events"),
            unauthenticated_client.get("/api/admin/teaching-focus/patterns"),
            unauthenticated_client.get("/api/admin/teaching-focus/patterns/case_baseline:appendicitis_001:history_taking"),
            unauthenticated_client.post("/api/admin/demo/seed"),
        ]

    assert [response.status_code for response in responses] == [401] * len(responses)
    assert all(response.json() == {"detail": "not authenticated"} for response in responses)


def test_admin_endpoints_reject_authenticated_non_admin_user(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"), raising=False)

    with TestClient(main.app) as client:
        login_response = client.post("/api/auth/login", json={"email": "student@osce.test", "password": "student"})
        assert login_response.status_code == 200

        responses = [
            client.get("/api/admin/evolution/candidates"),
            client.get("/api/admin/evolution/candidates/missing_candidate"),
            client.get("/api/admin/evolution/candidates/missing_candidate/events"),
            client.get("/api/admin/evolution/events"),
            client.get("/api/admin/evolution/settings"),
            client.patch("/api/admin/evolution/settings", json={"auto_apply_enabled": True}),
            client.get("/api/admin/evolution/skill-effects"),
            client.post("/api/admin/evolution/candidates/generate"),
            client.post("/api/admin/evolution/approve", json={"candidate_id": "missing_candidate"}),
            client.post("/api/admin/evolution/reject", json={"candidate_id": "missing_candidate"}),
            client.get("/api/admin/insights"),
            client.get("/api/admin/learning-analytics"),
            client.get("/api/admin/users"),
            client.post(
                "/api/admin/users",
                json={"email": "new@example.test", "password": "safe-password", "display_name": "新用户"},
            ),
            client.patch("/api/admin/users/missing-user", json={"status": "disabled"}),
            client.post("/api/admin/users/missing-user/reset-password", json={"password": "new-password"}),
            client.delete("/api/admin/users/missing-user"),
            client.get("/api/admin/classrooms"),
            client.post("/api/admin/classrooms/import", json={"csv_text": "班级名称\n一班"}),
            client.post(
                "/api/admin/classrooms",
                json={"name": "临床一班", "member_user_ids": []},
            ),
            client.put(
                "/api/admin/classrooms/missing-classroom",
                json={"name": "临床一班", "member_user_ids": []},
            ),
            client.delete("/api/admin/classrooms/missing-classroom"),
            client.post(
                "/api/admin/classrooms/missing-classroom/members/transfer",
                json={"target_classroom_id": "target", "member_user_ids": ["member"]},
            ),
            client.get("/api/admin/evaluations"),
            client.get("/api/admin/evaluations/missing_batch"),
            client.get("/api/admin/evaluation-config"),
            client.delete("/api/admin/evaluation-cases/custom_case"),
            client.delete("/api/admin/evaluation-suites/custom_suite"),
            client.patch(
                "/api/admin/evaluation-schedule",
                json={"enabled": False, "suite_id": "default_regression", "interval_minutes": 60},
            ),
            client.post("/api/admin/evals/run", json={"batch_id": "batch_manual"}),
            client.get("/api/cases/appendicitis_001/raw"),
            client.get("/api/admin/cases/appendicitis_001/raw"),
            client.patch("/api/admin/cases/appendicitis_001/raw", json={"case_title": "演示病例"}),
            client.get("/api/admin/cases/appendicitis_001/assets"),
            client.put(
                "/api/admin/cases/appendicitis_001/assets",
                json={"case": {}, "rubric": {}, "change_note": "测试"},
            ),
            client.post(
                "/api/admin/cases/appendicitis_001/review",
                json={"review_status": "approved", "medical_review_note": "测试"},
            ),
            client.get("/api/admin/cases/appendicitis_001/versions"),
            client.get("/api/admin/cases/appendicitis_001/diff?from_version=1&to_version=2"),
            client.post("/api/admin/cases/appendicitis_001/rollback", json={"version": 1}),
            client.post("/api/admin/cases/validate", json={"case": {}, "rubric": {}}),
            client.post("/api/admin/cases/import", json={"case": {}, "rubric": {}}),
            client.get("/api/admin/rubrics/appendicitis_001_rubric"),
            client.patch("/api/admin/rubrics/appendicitis_001_rubric/items/ht_onset", json={"description": "追问起病时间"}),
            client.get("/api/admin/sources"),
            client.post(
                "/api/admin/sources",
                json={"source_id": "source_demo", "source_name": "来源", "data_type": "reference"},
            ),
            client.put(
                "/api/admin/sources/source_demo",
                json={"source_id": "source_demo", "source_name": "来源", "data_type": "reference"},
            ),
            client.post(
                "/api/admin/sources/source_demo/review",
                json={"last_reviewed_at": "2026-08-04", "review_basis": "测试"},
            ),
            client.delete("/api/admin/sources/source_demo"),
            client.get("/api/admin/sources/source_demo/versions"),
            client.get("/api/admin/sources/source_demo/diff?from_version=1&to_version=2"),
            client.post("/api/admin/sources/source_demo/rollback", json={"version": 1}),
            client.get("/api/admin/model-config"),
            client.get("/api/admin/model-api-logs"),
            client.get("/api/admin/audit-events"),
            client.get("/api/admin/audit-events/export?format=json"),
            client.get("/api/admin/retrieval-eval"),
            client.get("/api/admin/rag/knowledge"),
            client.post("/api/admin/rag/knowledge", json={}),
            client.get("/api/admin/rag/documents"),
            client.post("/api/admin/rag/documents", json={}),
            client.patch("/api/admin/rag/documents/missing_document/enabled", json={"enabled": False}),
            client.delete("/api/admin/rag/documents/missing_document"),
            client.get("/api/admin/rag/knowledge/case:appendicitis_001:teaching:history_migration"),
            client.delete("/api/admin/rag/knowledge/case:appendicitis_001:teaching:history_migration"),
            client.get("/api/admin/reports"),
            client.get("/api/admin/reports/export?format=json"),
            client.get("/api/admin/reports/missing_report"),
            client.get("/api/admin/sessions"),
            client.get("/api/admin/procedure-simulation-audits"),
            client.get("/api/admin/sessions/missing_session/report"),
            client.get("/api/admin/sessions/missing_session/events"),
            client.get("/api/admin/teaching-focus/patterns"),
            client.get("/api/admin/teaching-focus/patterns/case_baseline:appendicitis_001:history_taking"),
            client.post("/api/admin/demo/seed"),
        ]

    assert [response.status_code for response in responses] == [403] * len(responses)
    assert all(response.json() == {"detail": "admin access required"} for response in responses)


def test_admin_can_manage_classroom_members_from_existing_users(tmp_path, monkeypatch) -> None:
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        student_a = main.auth_store.create_user(
            "student-a@example.test",
            "safe-password-a",
            "张三",
        )
        student_b = main.auth_store.create_user(
            "student-b@example.test",
            "safe-password-b",
            "李四",
        )
        assert student_a is not None
        assert student_b is not None

        users_response = client.get("/api/admin/users")
        assert users_response.status_code == 200
        users = users_response.json()["users"]
        assert {user["display_name"] for user in users} >= {"演示管理员", "张三", "李四"}
        assert all("password_hash" not in user for user in users)
        assert next(user for user in users if user["user_id"] == student_a["user_id"])[
            "eligible_for_classroom"
        ] is True
        admin_user = next(user for user in users if user["is_admin"])
        assert admin_user["eligible_for_classroom"] is False

        create_response = client.post(
            "/api/admin/classrooms",
            json={
                "name": "2026 级临床一班",
                "description": "春季 OSCE 综合训练",
                "member_user_ids": [student_a["user_id"], student_b["user_id"]],
            },
        )
        assert create_response.status_code == 201
        classroom = create_response.json()["classroom"]
        assert classroom["member_count"] == 2
        assert [member["display_name"] for member in classroom["members"]] == ["张三", "李四"]

        classroom_id = classroom["classroom_id"]
        update_response = client.put(
            f"/api/admin/classrooms/{classroom_id}",
            json={
                "name": "2026 级临床一班 A 组",
                "description": "本周重点练习急腹症",
                "member_user_ids": [student_b["user_id"]],
            },
        )
        assert update_response.status_code == 200
        updated = update_response.json()["classroom"]
        assert updated["name"] == "2026 级临床一班 A 组"
        assert updated["member_user_ids"] == [student_b["user_id"]]

        list_response = client.get("/api/admin/classrooms")
        assert list_response.status_code == 200
        assert list_response.json()["classrooms"] == [updated]

        analytics_response = client.get(
            f"/api/admin/learning-analytics?classroom_id={classroom_id}"
        )
        assert analytics_response.status_code == 200
        cohort = analytics_response.json()["learning_analytics"]["cohort_analytics"]
        assert cohort["scope"] == f"classroom:{classroom_id}"
        assert cohort["scope_label"] == "2026 级临床一班 A 组"
        assert cohort["student_count"] == 0

        delete_response = client.delete(f"/api/admin/classrooms/{classroom_id}")
        assert delete_response.status_code == 200
        assert client.get("/api/admin/classrooms").json()["classrooms"] == []


def test_admin_classroom_rejects_admin_unknown_and_duplicate_names(
    tmp_path,
    monkeypatch,
) -> None:
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        users = client.get("/api/admin/users").json()["users"]
        admin_user = next(user for user in users if user["is_admin"])

        admin_member_response = client.post(
            "/api/admin/classrooms",
            json={
                "name": "管理员不可加入",
                "member_user_ids": [admin_user["user_id"]],
            },
        )
        unknown_member_response = client.post(
            "/api/admin/classrooms",
            json={
                "name": "未知用户不可加入",
                "member_user_ids": ["missing-user"],
            },
        )
        assert admin_member_response.status_code == 400
        assert unknown_member_response.status_code == 400

        first_response = client.post(
            "/api/admin/classrooms",
            json={"name": "Clinical A", "member_user_ids": []},
        )
        duplicate_response = client.post(
            "/api/admin/classrooms",
            json={"name": "clinical a", "member_user_ids": []},
        )
        assert first_response.status_code == 201
        assert duplicate_response.status_code == 409


def test_admin_classroom_rejects_blank_name_and_unknown_classroom(
    tmp_path,
    monkeypatch,
) -> None:
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        blank_name_response = client.post(
            "/api/admin/classrooms",
            json={"name": "   ", "member_user_ids": []},
        )
        missing_update_response = client.put(
            "/api/admin/classrooms/missing-classroom",
            json={"name": "临床一班", "member_user_ids": []},
        )
        missing_delete_response = client.delete(
            "/api/admin/classrooms/missing-classroom"
        )
        missing_analytics_response = client.get(
            "/api/admin/learning-analytics?classroom_id=missing-classroom"
        )

    assert blank_name_response.status_code == 422
    assert missing_update_response.status_code == 404
    assert missing_delete_response.status_code == 404
    assert missing_analytics_response.status_code == 404


def test_classroom_excludes_member_who_later_becomes_an_admin(
    tmp_path,
    monkeypatch,
) -> None:
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        student = main.auth_store.create_user(
            "promoted@example.test",
            "safe-password",
            "待晋升学生",
        )
        assert student is not None
        create_response = client.post(
            "/api/admin/classrooms",
            json={
                "name": "临床二班",
                "member_user_ids": [student["user_id"]],
            },
        )
        assert create_response.status_code == 201
        classroom_id = create_response.json()["classroom"]["classroom_id"]

        monkeypatch.setenv(
            "CLINICAL_OSCE_ADMIN_EMAILS",
            f"{main._get_demo_admin_email()},{student['email']}",
        )
        classroom = client.get("/api/admin/classrooms").json()["classrooms"][0]
        analytics = client.get(
            f"/api/admin/learning-analytics?classroom_id={classroom_id}"
        ).json()["learning_analytics"]

    assert classroom["member_count"] == 0
    assert classroom["member_user_ids"] == []
    assert analytics["summary"]["student_count"] == 0


def test_admin_manages_user_lifecycle_roles_and_audit_exports(
    tmp_path,
    monkeypatch,
) -> None:
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        teacher_response = client.post(
            "/api/admin/users",
            json={
                "email": "teacher@example.test",
                "password": "teacher-password",
                "display_name": "王老师",
                "role": "teacher",
            },
        )
        second_admin_response = client.post(
            "/api/admin/users",
            json={
                "email": "second-admin@example.test",
                "password": "second-admin-password",
                "display_name": "第二管理员",
                "role": "admin",
            },
        )
        assert teacher_response.status_code == 201
        assert second_admin_response.status_code == 201
        teacher = teacher_response.json()["user"]
        second_admin = second_admin_response.json()["user"]
        assert teacher["role"] == "teacher"
        assert second_admin["is_admin"] is True

        duplicate = client.post(
            "/api/admin/users",
            json={
                "email": "TEACHER@example.test",
                "password": "another-password",
                "display_name": "重复老师",
                "role": "teacher",
            },
        )
        assert duplicate.status_code == 409

        disabled_response = client.patch(
            f"/api/admin/users/{teacher['user_id']}",
            json={"status": "disabled", "display_name": "王老师（停用）"},
        )
        assert disabled_response.status_code == 200
        assert disabled_response.json()["user"]["status"] == "disabled"
        assert main.auth_store.authenticate_user(
            "teacher@example.test",
            "teacher-password",
        ) is None

        reenabled_response = client.patch(
            f"/api/admin/users/{teacher['user_id']}",
            json={"status": "active"},
        )
        reset_response = client.post(
            f"/api/admin/users/{teacher['user_id']}/reset-password",
            json={"password": "rotated-teacher-password"},
        )
        assert reenabled_response.status_code == 200
        assert reset_response.status_code == 200
        assert main.auth_store.authenticate_user(
            "teacher@example.test",
            "rotated-teacher-password",
        ) is not None

        with TestClient(main.app) as second_admin_client:
            login_response = second_admin_client.post(
                "/api/auth/login",
                json={
                    "email": "second-admin@example.test",
                    "password": "second-admin-password",
                },
            )
            assert login_response.status_code == 200
            assert second_admin_client.get("/api/admin/users").status_code == 200
            self_demotion = second_admin_client.patch(
                f"/api/admin/users/{second_admin['user_id']}",
                json={"role": "student"},
            )
            assert self_demotion.status_code == 400

        delete_response = client.delete(
            f"/api/admin/users/{teacher['user_id']}"
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["user"]["status"] == "deleted"

        audit_response = client.get("/api/admin/audit-events?limit=100")
        json_export = client.get("/api/admin/audit-events/export?format=json")
        csv_export = client.get("/api/admin/audit-events/export?format=csv")

    assert audit_response.status_code == 200
    actions = {event["action"] for event in audit_response.json()["events"]}
    assert {
        "user.created",
        "user.updated",
        "user.password_reset",
        "user.deleted",
    } <= actions
    assert json_export.status_code == 200
    assert "attachment;" in json_export.headers["content-disposition"]
    assert csv_export.status_code == 200
    assert csv_export.text.startswith("\ufeffevent_id,created_at")


def test_admin_assigns_teacher_archives_imports_and_moves_class_members(
    tmp_path,
    monkeypatch,
) -> None:
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        teacher = client.post(
            "/api/admin/users",
            json={
                "email": "teacher@example.test",
                "password": "teacher-password",
                "display_name": "带教老师",
                "role": "teacher",
            },
        ).json()["user"]
        student_a = client.post(
            "/api/admin/users",
            json={
                "email": "student-a@example.test",
                "password": "student-a-password",
                "display_name": "学生甲",
                "role": "student",
            },
        ).json()["user"]
        student_b = client.post(
            "/api/admin/users",
            json={
                "email": "student-b@example.test",
                "password": "student-b-password",
                "display_name": "学生乙",
                "role": "student",
            },
        ).json()["user"]

        source_response = client.post(
            "/api/admin/classrooms",
            json={
                "name": "临床一班",
                "description": "第一轮训练",
                "member_user_ids": [student_a["user_id"], student_b["user_id"]],
                "teacher_user_id": teacher["user_id"],
                "status": "active",
            },
        )
        target_response = client.post(
            "/api/admin/classrooms",
            json={
                "name": "临床二班",
                "member_user_ids": [],
                "teacher_user_id": teacher["user_id"],
                "status": "active",
            },
        )
        assert source_response.status_code == 201
        source = source_response.json()["classroom"]
        target = target_response.json()["classroom"]
        assert source["teacher"]["display_name"] == "带教老师"

        transfer_response = client.post(
            f"/api/admin/classrooms/{source['classroom_id']}/members/transfer",
            json={
                "target_classroom_id": target["classroom_id"],
                "member_user_ids": [student_b["user_id"]],
                "mode": "move",
            },
        )
        archive_response = client.put(
            f"/api/admin/classrooms/{source['classroom_id']}",
            json={
                "name": "临床一班",
                "description": "已结课",
                "member_user_ids": [student_a["user_id"]],
                "teacher_user_id": teacher["user_id"],
                "status": "archived",
            },
        )
        assert transfer_response.status_code == 200
        assert transfer_response.json()["source_classroom"]["member_count"] == 1
        assert transfer_response.json()["target_classroom"]["member_count"] == 1
        assert archive_response.status_code == 200
        assert archive_response.json()["classroom"]["status"] == "archived"

        import_response = client.post(
            "/api/admin/classrooms/import",
            json={
                "mode": "merge",
                "csv_text": (
                    "班级名称,班级说明,负责教师邮箱,学生邮箱,状态\n"
                    "临床三班,周五训练,teacher@example.test,student-a@example.test,启用\n"
                    "临床三班,周五训练,teacher@example.test,student-b@example.test,启用\n"
                ),
            },
        )
        assert import_response.status_code == 200
        imported = import_response.json()["classrooms"][0]
        assert imported["name"] == "临床三班"
        assert imported["member_count"] == 2
        assert imported["teacher"]["user_id"] == teacher["user_id"]

        invalid_import = client.post(
            "/api/admin/classrooms/import",
            json={
                "mode": "replace",
                "csv_text": (
                    "班级名称,学生邮箱\n"
                    "错误班级,missing@example.test\n"
                ),
            },
        )

    assert invalid_import.status_code == 400
    assert "CSV 校验失败" in invalid_import.text


def test_admin_can_read_model_api_logs(tmp_path, monkeypatch) -> None:
    log_store = ApiCallLogStore(tmp_path / "model_api_calls.jsonl")
    log_store.record(
        provider="openai_compatible",
        operation="chat.completions",
        model="gemini-3.5-flash",
        endpoint="https://gateway.example/v1/chat/completions",
        success=True,
        duration_ms=100,
        status_code=200,
    )
    log_store.record(
        provider="openai_compatible",
        operation="chat.completions",
        model="gemini-3.5-flash",
        endpoint="https://gateway.example/v1/chat/completions",
        success=False,
        duration_ms=200,
        status_code=500,
    )
    monkeypatch.setattr(main, "api_call_log_store", log_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/model-api-logs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total_calls"] == 2
    assert payload["summary"]["success_rate"] == 0.5
    assert payload["summary_by_provider"][0]["provider"] == "openai_compatible"
    assert [item["success"] for item in payload["logs"]] == [False, True]


def test_admin_can_seed_demo_training_loop(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_EMAIL", "seed-admin@example.test")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_PASSWORD", "seed-admin-password")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_EMAIL", "seed-student@example.test")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_STUDENT_PASSWORD", "seed-student-password")
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.osce_graph = build_osce_graph(patient_responder=canonical_patient_responder, llm_scorer=None)
    osce_session_service._sessions.clear()
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "seed_demo_data.py"

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/admin/demo/seed")

    assert script_path.exists()
    assert response.status_code == 200
    payload = response.json()
    assert payload["student"] == {
        "email": "seed-student@example.test",
        "password": "seed-student-password",
        "display_name": "演示学生",
    }
    assert payload["admin"]["email"] == "seed-admin@example.test"
    assert payload["admin"]["password"] == "seed-admin-password"
    assert payload["session_count"] == 3
    assert payload["report_count"] == 2
    assert len(payload["sessions"]) == 3
    assert payload["candidate"]["candidate_id"] == "demo_skill_candidate_abdominal_pain_history_bundle"
    assert payload["candidate"]["status"] == "approved"
    assert payload["enabled_skill"]["skill_id"] == "skill_training_pattern_abdominal_pain_history_bundle"
    assert payload["enabled_skill"]["status"] == "enabled"
    stored_candidate = candidate_store.get_candidate(payload["candidate"]["candidate_id"])
    assert stored_candidate is not None
    assert stored_candidate["approval_agent_review"]["decision"] == "ready_for_human_review"
    assert stored_candidate["approval_agent_review"]["quality_review"]["passed"] is True
    assert stored_candidate["review"]["regression_passed"] is True
    candidate_events = osce_session_service.training_event_store.list_session_events(
        payload["candidate"]["candidate_id"]
    )
    assert [event["event_type"] for event in candidate_events] == [
        "admin_skill_candidate_generated",
        "admin_skill_candidate_agent_reviewed",
        "admin_skill_candidate_approved",
    ]
    applied_events = [
        event
        for event in osce_session_service.training_event_store.list_session_events(payload["sessions"][-1]["session_id"])
        if event["event_type"] == "training_skill_applied"
    ]
    assert applied_events
    assert any(
        event["payload"]["skill_id"] == "skill_training_pattern_abdominal_pain_history_bundle"
        for event in applied_events
    )


def test_admin_demo_seed_rejects_overlapping_role_emails_before_writes(
    tmp_path,
    monkeypatch,
) -> None:
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        monkeypatch.setenv(
            "CLINICAL_OSCE_ADMIN_EMAILS",
            "admin@osce.test",
        )
        monkeypatch.setenv(
            "CLINICAL_OSCE_DEMO_ADMIN_EMAIL",
            "shared-seed-role@example.test",
        )
        monkeypatch.setenv(
            "CLINICAL_OSCE_DEMO_ADMIN_PASSWORD",
            "configured-admin-password",
        )
        monkeypatch.setenv(
            "CLINICAL_OSCE_DEMO_STUDENT_EMAIL",
            "SHARED-SEED-ROLE@example.test",
        )
        monkeypatch.setenv(
            "CLINICAL_OSCE_DEMO_STUDENT_PASSWORD",
            "configured-student-password",
        )

        response = client.post("/api/admin/demo/seed")

    assert response.status_code == 409
    assert response.json() == {
        "detail": main.DEMO_SEED_CONFIG_ERROR_MESSAGE,
    }
    assert (
        main.auth_store.authenticate_user(
            "shared-seed-role@example.test",
            "configured-student-password",
        )
        is None
    )


def test_admin_demo_seed_fails_closed_when_student_credentials_are_incomplete(tmp_path, monkeypatch) -> None:
    seed_called = False

    def unexpected_seed(**_: object) -> dict[str, object]:
        nonlocal seed_called
        seed_called = True
        return {}

    monkeypatch.setattr(main, "seed_demo_data", unexpected_seed)
    with authenticated_admin_client(tmp_path, monkeypatch, raise_server_exceptions=False) as client:
        monkeypatch.delenv("CLINICAL_OSCE_DEMO_STUDENT_PASSWORD", raising=False)
        response = client.post("/api/admin/demo/seed")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "demo admin and student credentials must be explicitly configured in a local deployment"
    }
    assert seed_called is False


def test_demo_seed_script_fails_closed_without_complete_explicit_credentials(monkeypatch) -> None:
    from scripts import seed_demo_data as seed_demo_script

    def unexpected_seed(**_: object) -> dict[str, object]:
        raise AssertionError("seed service must not run with incomplete credentials")

    monkeypatch.delenv("CLINICAL_OSCE_DEMO_STUDENT_PASSWORD", raising=False)
    monkeypatch.setattr(seed_demo_script, "seed_demo_data", unexpected_seed)

    with pytest.raises(
        RuntimeError,
        match="demo admin and student credentials must be explicitly configured in a local deployment",
    ):
        seed_demo_script.run()


def test_admin_review_request_schema_only_exposes_candidate_id() -> None:
    main.app.openapi_schema = None

    schema = main.app.openapi()["components"]["schemas"]["AdminTrainingSkillReviewRequest"]

    assert schema["required"] == ["candidate_id"]
    assert list(schema["properties"]) == ["candidate_id"]


def test_admin_can_toggle_training_skill_auto_approval_settings(tmp_path, monkeypatch) -> None:
    settings_store = TrainingSkillAutoApprovalSettingsStore(tmp_path / "training_skill_auto_approval.sqlite3")
    monkeypatch.setattr(main, "training_skill_auto_approval_settings_store", settings_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        default_response = client.get("/api/admin/evolution/settings")
        update_response = client.patch("/api/admin/evolution/settings", json={"auto_apply_enabled": True})
        persisted_response = client.get("/api/admin/evolution/settings")

    assert default_response.status_code == 200
    assert default_response.json()["settings"] == {
        "auto_apply_enabled": False,
        "approval_agent_id": "skill_auto_approval_agent",
        "updated_by": "",
        "updated_at": None,
    }
    assert update_response.status_code == 200
    updated_settings = update_response.json()["settings"]
    assert updated_settings["auto_apply_enabled"] is True
    assert updated_settings["approval_agent_id"] == "skill_auto_approval_agent"
    assert updated_settings["updated_by"] == "admin@osce.test"
    assert isinstance(updated_settings["updated_at"], str)
    assert persisted_response.json()["settings"] == updated_settings
    assert main.admin_audit_store.list_events()["events"][0]["action"] == "skill.auto_apply_enabled"


def test_admin_can_manage_rag_knowledge_items_with_visibility_and_source_binding(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "rag_knowledge_store", RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3"), raising=False)

    payload = {
        "knowledge_id": "case:appendicitis_001:teaching:history_migration",
        "scope": "case",
        "case_id": "appendicitis_001",
        "content_kind": "teaching_note",
        "visibility": "pre_submit_safe",
        "allowed_agents": ["coach", "skill_approval"],
        "stage_scope": ["history_taking"],
        "source_id": "fareez_osce_2022",
        "title": "右下腹痛问诊中的疼痛迁移",
        "text": "追问疼痛是否从上腹或脐周转移到右下腹，用于训练疼痛演变采集。",
        "tags": ["abdominal_pain", "history_taking"],
        "version": 1,
    }

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        create_response = client.post("/api/admin/rag/knowledge", json=payload)
        list_response = client.get("/api/admin/rag/knowledge?case_id=appendicitis_001&visibility=pre_submit_safe&q=疼痛迁移&limit=1")
        detail_response = client.get("/api/admin/rag/knowledge/case:appendicitis_001:teaching:history_migration")
        delete_response = client.delete("/api/admin/rag/knowledge/case:appendicitis_001:teaching:history_migration")
        empty_detail_response = client.get("/api/admin/rag/knowledge/case:appendicitis_001:teaching:history_migration")
        audit_actions = {
            event["action"]
            for event in client.get("/api/admin/audit-events?limit=100").json()["events"]
        }

    assert create_response.status_code == 200
    created_item = create_response.json()["knowledge_item"]
    assert created_item == {
        **payload,
        "char_count": len(payload["text"]),
        "case_title": "右下腹痛教学病例",
        "quality_warnings": ["short_chunk"],
        "review_note": "",
        "review_status": "approved",
        "reviewed_at": "",
        "reviewed_by": "",
        "risk_flags": [],
        "source_title": "A dataset of simulated patient-physician medical interviews with a focus on respiratory cases",
        "stage_scope_labels": ["问诊阶段"],
        "updated_by": "admin@osce.test",
        "updated_at": created_item["updated_at"],
    }
    assert created_item["updated_at"]

    assert list_response.status_code == 200
    assert list_response.json()["knowledge_items"] == [created_item]
    assert list_response.json()["pagination"] == {"limit": 1, "offset": 0, "total": 1}

    assert detail_response.status_code == 200
    assert detail_response.json()["knowledge_item"] == created_item

    assert delete_response.status_code == 200
    assert delete_response.json() == {
        "knowledge_id": "case:appendicitis_001:teaching:history_migration",
        "deleted": True,
    }
    assert empty_detail_response.status_code == 404
    assert audit_actions >= {"rag_knowledge.created", "rag_knowledge.deleted"}


def test_admin_can_upload_toggle_and_retrieve_case_rag_document(tmp_path, monkeypatch) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    monkeypatch.setattr(main, "rag_knowledge_store", store, raising=False)
    monkeypatch.setattr(retrieval_index_module, "rag_knowledge_store", store, raising=False)
    retrieval_index_module._retrieval_documents.cache_clear()
    document_text = (
        """
# 右下腹痛教学知识库

训练目标是让学生按病史、查体、检查、诊断假设的顺序推进，而不是直接猜答案。

## 腹痛问诊

需要追问起病时间、起病部位、疼痛迁移、疼痛性质、疼痛程度、伴随症状和既往病史。
如果学生只问当前疼痛部位，Coach 可以提示其回到疼痛演变和诱发缓解因素。

## 查体与检查

腹部查体应覆盖视诊、听诊、触诊、压痛、反跳痛和肌紧张。
血常规、尿常规和腹部超声用于支持或修正诊断假设。

## 教学提示

如果学生过早进入检查申请，Coach 应提示其说明为什么当前已经具备进入检查阶段的依据。
如果学生已经收集到病史但遗漏腹膜刺激征，Coach 应提醒其把病史推理转化为有目的的查体。
如果学生完成查体后仍没有提出鉴别诊断，Coach 应提示其比较阑尾炎、输尿管结石和急性胃肠炎的证据链。

## 复盘重点

复盘时不需要重新证明学生确实漏项，而应解释该漏项为什么会破坏临床推理链。
复盘可以把未覆盖的病史、查体和检查事实合并成一个错误模式，避免机械地为每个 missed_item 生成一个 Skill。
复盘还应标注知识来源、适用 agent、可见性和病例绑定关系，便于管理员追溯知识库是否被正确应用。
""".strip()
        + "\n\n"
        + "\n".join(
            [
                "补充材料：教学知识库应支持 Coach 在训练中根据学生已问内容和未覆盖线索给出下一步建议，"
                "也应支持复盘与 Skill 审批在提交后读取更完整的医学解释。"
                for _ in range(8)
            ]
        )
    )

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        upload_response = client.post(
            "/api/admin/rag/documents",
            json={
                "case_id": "appendicitis_001",
                "file_name": "appendicitis_teaching.md",
                "content_base64": base64.b64encode(document_text.encode("utf-8")).decode("ascii"),
                "visibility": "pre_submit_safe",
                "allowed_agents": ["coach", "reflection", "skill_generation", "skill_approval"],
                "stage_scope": ["history_taking"],
                "source_id": "fareez_osce_2022",
                "tags": ["abdominal_pain", "teacher_document"],
            },
        )
        documents_response = client.get("/api/admin/rag/documents?case_id=appendicitis_001")

        assert upload_response.status_code == 200
        uploaded_document = upload_response.json()["document"]
        assert uploaded_document["case_id"] == "appendicitis_001"
        assert uploaded_document["case_title"] == "右下腹痛教学病例"
        assert uploaded_document["file_name"] == "appendicitis_teaching.md"
        assert uploaded_document["chunk_count"] >= 2
        assert uploaded_document["enabled"] is True
        assert uploaded_document["stage_scope"] == ["history_taking"]
        assert uploaded_document["stage_scope_labels"] == ["问诊阶段"]
        assert uploaded_document["source_title"] == "A dataset of simulated patient-physician medical interviews with a focus on respiratory cases"

        assert documents_response.status_code == 200
        assert documents_response.json()["documents"] == [uploaded_document]

        stored_chunks = store.list_items(case_id="appendicitis_001")
        assert len(stored_chunks) == uploaded_document["chunk_count"]
        assert {item["document_id"] for item in stored_chunks} == {uploaded_document["document_id"]}
        assert all(item["content_kind"] == "document_chunk" for item in stored_chunks)
        assert all(item["enabled"] is True for item in stored_chunks)
        assert all(item["stage_scope"] == ["history_taking"] for item in stored_chunks)
        assert all(item["source_location"].startswith("appendicitis_teaching.md") for item in stored_chunks)

        mock_vector_rag_hits_for_store(monkeypatch, store)
        enabled_context = retrieve_agent_context(
            agent_role="coach",
            case_ids=["appendicitis_001"],
            query_terms=["疼痛迁移 诱发缓解因素"],
            allowed_visibilities={"pre_submit_safe"},
            stage_scope=["history_taking"],
            store=store,
        )
        assert enabled_context
        assert enabled_context[0]["knowledge_id"].startswith(uploaded_document["document_id"])
        assert (
            retrieve_agent_context(
                agent_role="coach",
                case_ids=["appendicitis_001"],
                query_terms=["疼痛迁移 诱发缓解因素"],
                allowed_visibilities={"pre_submit_safe"},
                stage_scope=["physical_exam"],
                store=store,
            )
            == []
        )

        disabled_response = client.patch(
            f"/api/admin/rag/documents/{uploaded_document['document_id']}/enabled",
            json={"enabled": False},
        )

    assert disabled_response.status_code == 200
    disabled_document = disabled_response.json()["document"]
    assert disabled_document["document_id"] == uploaded_document["document_id"]
    assert disabled_document["enabled"] is False
    assert all(item["enabled"] is False for item in store.list_items(case_id="appendicitis_001"))
    assert (
        retrieve_agent_context(
            agent_role="coach",
            case_ids=["appendicitis_001"],
            query_terms=["疼痛迁移 诱发缓解因素"],
            allowed_visibilities={"pre_submit_safe"},
            stage_scope=["history_taking"],
            store=store,
        )
        == []
    )


def test_admin_can_search_paginate_and_delete_complete_rag_document(
    tmp_path,
    monkeypatch,
) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    monkeypatch.setattr(main, "rag_knowledge_store", store, raising=False)
    document_text = "# 医患沟通知识\n\n" + ("开放式提问、复述确认与共情回应可帮助学生修复沟通。\n" * 40)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        upload_response = client.post(
            "/api/admin/rag/documents",
            json={
                "case_id": "",
                "scope": "global",
                "file_name": "communication_teaching.md",
                "content_base64": base64.b64encode(document_text.encode("utf-8")).decode("ascii"),
                "visibility": "post_submit_review",
                "allowed_agents": ["reflection", "skill_generation"],
                "stage_scope": ["feedback"],
                "source_id": "",
                "tags": ["communication"],
            },
        )
        assert upload_response.status_code == 200, upload_response.text
        document = upload_response.json()["document"]

        list_response = client.get(
            "/api/admin/rag/documents",
            params={"q": "communication_teaching", "limit": 1, "offset": 0},
        )
        assert list_response.status_code == 200
        assert list_response.json()["documents"] == [document]
        assert list_response.json()["pagination"] == {"limit": 1, "offset": 0, "total": 1}

        item_response = client.get(
            "/api/admin/rag/knowledge",
            params={"document_id": document["document_id"], "limit": 500},
        )
        assert item_response.status_code == 200
        assert len(item_response.json()["knowledge_items"]) == document["chunk_count"]
        assert {
            item["document_id"] for item in item_response.json()["knowledge_items"]
        } == {document["document_id"]}

        delete_response = client.delete(
            f"/api/admin/rag/documents/{document['document_id']}"
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["deleted_chunk_count"] == document["chunk_count"]
        assert store.list_document_items(document["document_id"]) == []
        assert client.get("/api/admin/rag/documents").json()["documents"] == []

        audit_actions = {
            event["action"]
            for event in client.get("/api/admin/audit-events?limit=100").json()["events"]
        }
        assert audit_actions >= {"rag_document.uploaded", "rag_document.deleted"}


def test_admin_rag_document_upload_defaults_apply_to_all_generative_agents(tmp_path, monkeypatch) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    monkeypatch.setattr(main, "rag_knowledge_store", store, raising=False)
    monkeypatch.setattr(retrieval_index_module, "rag_knowledge_store", store, raising=False)
    retrieval_index_module._retrieval_documents.cache_clear()
    document_text = "疼痛迁移训练：Coach 应在训练中提示学生追问起病部位、转移过程和伴随症状。"

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        upload_response = client.post(
            "/api/admin/rag/documents",
            json={
                "case_id": "appendicitis_001",
                "file_name": "coach_ready_teaching.txt",
                "content_base64": base64.b64encode(document_text.encode("utf-8")).decode("ascii"),
            },
        )

    assert upload_response.status_code == 200
    uploaded_document = upload_response.json()["document"]
    assert uploaded_document["visibility"] == "pre_submit_safe"
    assert uploaded_document["stage_scope"] == ["any"]
    assert uploaded_document["stage_scope_labels"] == ["全部训练阶段"]
    assert set(uploaded_document["allowed_agents"]) == {
        "coach",
        "reflection",
        "skill_generation",
        "skill_approval",
    }

    mock_vector_rag_hits_for_store(monkeypatch, store)
    for agent_role in ["coach", "reflection", "skill_generation", "skill_approval"]:
        context = retrieve_agent_context(
            agent_role=agent_role,
            case_ids=["appendicitis_001"],
            query_terms=["疼痛迁移训练 起病部位 伴随症状"],
            allowed_visibilities={"pre_submit_safe", "post_submit_review"},
            store=store,
        )
        assert context, agent_role
        assert context[0]["knowledge_id"].startswith(uploaded_document["document_id"])


def test_admin_can_upload_global_rag_document_and_scope_document_listing(tmp_path, monkeypatch) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    monkeypatch.setattr(main, "rag_knowledge_store", store, raising=False)
    monkeypatch.setattr(retrieval_index_module, "rag_knowledge_store", store, raising=False)
    retrieval_index_module._retrieval_documents.cache_clear()

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        global_response = client.post(
            "/api/admin/rag/documents",
            json={
                "scope": "global",
                "file_name": "global_osce_framework.md",
                "content_base64": base64.b64encode(
                    "# OSCE 通用问诊框架\n\n训练中应先明确主诉、起病、部位、性质、程度和伴随症状。".encode("utf-8")
                ).decode("ascii"),
            },
        )
        case_response = client.post(
            "/api/admin/rag/documents",
            json={
                "case_id": "appendicitis_001",
                "file_name": "appendicitis_case_teaching.txt",
                "content_base64": base64.b64encode("病例专项知识库：右下腹痛需要追问疼痛迁移。".encode("utf-8")).decode("ascii"),
            },
        )
        global_documents_response = client.get("/api/admin/rag/documents?scope=global")
        case_documents_response = client.get("/api/admin/rag/documents?scope=case&case_id=appendicitis_001")

    assert global_response.status_code == 200
    assert case_response.status_code == 200
    global_document = global_response.json()["document"]
    case_document = case_response.json()["document"]
    assert global_document["scope"] == "global"
    assert global_document["case_id"] == ""
    assert global_document["case_title"] == "全局知识库"
    assert case_document["scope"] == "case"
    assert case_document["case_id"] == "appendicitis_001"
    assert case_document["case_title"] == "右下腹痛教学病例"

    assert global_documents_response.status_code == 200
    assert [document["document_id"] for document in global_documents_response.json()["documents"]] == [
        global_document["document_id"]
    ]
    assert case_documents_response.status_code == 200
    assert [document["document_id"] for document in case_documents_response.json()["documents"]] == [
        case_document["document_id"]
    ]

    mock_vector_rag_hits_for_store(monkeypatch, store)
    context = retrieve_agent_context(
        agent_role="coach",
        case_ids=["appendicitis_001"],
        query_terms=["OSCE 通用问诊框架 主诉 起病 部位"],
        allowed_visibilities={"pre_submit_safe"},
        store=store,
    )
    assert context
    assert context[0]["knowledge_id"].startswith(global_document["document_id"])


def test_admin_rag_document_upload_persists_chunk_quality_metadata(tmp_path, monkeypatch) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    monkeypatch.setattr(main, "rag_knowledge_store", store, raising=False)
    monkeypatch.setattr(retrieval_index_module, "rag_knowledge_store", store, raising=False)
    retrieval_index_module._retrieval_documents.cache_clear()

    def fake_chunk_rag_document(**kwargs):
        return [
            RagDocumentChunk(
                document_id=kwargs["document_id"],
                chunk_index=0,
                text="References\n\nSmith J. Example article.",
                section_title="References",
                page_number=8,
                source_location="paper.pdf · 第 8 页 · References · 片段 1",
                chunking_strategy="unstructured_by_title",
                chunk_categories=["Title", "NarrativeText"],
                quality_warnings=["low_value_section"],
                risk_flags=["references_section"],
                char_count=34,
            )
        ]

    monkeypatch.setattr(main, "chunk_rag_document", fake_chunk_rag_document, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/admin/rag/documents",
            json={
                "scope": "global",
                "file_name": "paper.pdf",
                "content_base64": base64.b64encode(b"pretend-pdf").decode("ascii"),
            },
        )

    assert response.status_code == 200
    saved_item = response.json()["knowledge_items"][0]
    assert saved_item["chunking_strategy"] == "unstructured_by_title"
    assert saved_item["chunk_categories"] == ["Title", "NarrativeText"]
    assert saved_item["quality_warnings"] == ["low_value_section"]
    assert saved_item["risk_flags"] == ["references_section"]
    assert saved_item["char_count"] == 34
    assert saved_item["review_status"] == "pending_review"
    assert response.json()["document"]["pending_review_chunk_count"] == 1
    assert response.json()["document"]["indexable_chunk_count"] == 0


def test_rag_risk_review_blocks_pre_submit_answers_and_preserves_chunk_metadata_on_edit(
    tmp_path,
    monkeypatch,
) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    monkeypatch.setattr(main, "rag_knowledge_store", store, raising=False)
    monkeypatch.setattr(retrieval_index_module, "rag_knowledge_store", store, raising=False)
    retrieval_index_module._retrieval_documents.cache_clear()

    def fake_chunk_rag_document(**kwargs):
        return [
            RagDocumentChunk(
                document_id=kwargs["document_id"],
                chunk_index=0,
                text="最终诊断为急性阑尾炎，本段只能在提交后用于复盘。",
                section_title="诊断复盘",
                page_number=2,
                source_location="review.pdf · 第 2 页 · 诊断复盘 · 片段 1",
                chunking_strategy="local_pdf_page_window",
                chunk_categories=["OCRText"],
                quality_warnings=["short_chunk"],
                risk_flags=["diagnosis_answer_content"],
                char_count=29,
            )
        ]

    monkeypatch.setattr(main, "chunk_rag_document", fake_chunk_rag_document, raising=False)
    mock_vector_rag_hits_for_store(monkeypatch, store)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        upload_response = client.post(
            "/api/admin/rag/documents",
            json={
                "case_id": "appendicitis_001",
                "file_name": "review.pdf",
                "content_base64": base64.b64encode(b"pretend-pdf").decode("ascii"),
                "visibility": "pre_submit_safe",
                "allowed_agents": ["coach"],
            },
        )
        uploaded_item = upload_response.json()["knowledge_items"][0]
        blocked_approval = client.patch(
            f"/api/admin/rag/knowledge/{uploaded_item['knowledge_id']}/review",
            json={"decision": "approved", "note": "训练前不应批准"},
        )
        edit_response = client.post(
            "/api/admin/rag/knowledge",
            json={
                "knowledge_id": uploaded_item["knowledge_id"],
                "scope": "case",
                "case_id": "appendicitis_001",
                "content_kind": "document_chunk",
                "visibility": "post_submit_review",
                "allowed_agents": ["reflection"],
                "stage_scope": ["feedback"],
                "source_id": "",
                "title": "诊断复盘",
                "text": uploaded_item["text"],
                "tags": ["review"],
                "version": 2,
            },
        )
        edited_item = edit_response.json()["knowledge_item"]
        approval_response = client.patch(
            f"/api/admin/rag/knowledge/{uploaded_item['knowledge_id']}/review",
            json={"decision": "approved", "note": "仅用于提交后复盘"},
        )

    assert upload_response.status_code == 200
    assert uploaded_item["review_status"] == "pending_review"
    assert blocked_approval.status_code == 409
    assert "pre-submit" in blocked_approval.json()["detail"]
    assert (
        retrieve_agent_context(
            agent_role="coach",
            case_ids=["appendicitis_001"],
            query_terms=["最终诊断"],
            allowed_visibilities={"pre_submit_safe"},
            store=store,
        )
        == []
    )

    assert edit_response.status_code == 200
    assert edited_item["document_id"] == uploaded_item["document_id"]
    assert edited_item["source_location"] == "review.pdf · 第 2 页 · 诊断复盘 · 片段 1"
    assert edited_item["chunk_categories"] == ["OCRText"]
    assert edited_item["risk_flags"] == ["diagnosis_answer_content"]
    assert edited_item["review_status"] == "pending_review"

    assert approval_response.status_code == 200
    approved_item = approval_response.json()["knowledge_item"]
    assert approved_item["review_status"] == "approved"
    assert approved_item["reviewed_by"] == "admin@osce.test"
    assert approved_item["review_note"] == "仅用于提交后复盘"
    assert approval_response.json()["document"]["approved_chunk_count"] == 1
    approved_context = retrieve_agent_context(
        agent_role="reflection",
        case_ids=["appendicitis_001"],
        query_terms=["最终诊断"],
        allowed_visibilities={"post_submit_review"},
        stage_scope=["feedback"],
        store=store,
    )
    assert approved_context
    assert approved_context[0]["knowledge_id"] == uploaded_item["knowledge_id"]


def test_admin_can_reject_all_pending_chunks_in_document(tmp_path, monkeypatch) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    monkeypatch.setattr(main, "rag_knowledge_store", store, raising=False)

    def fake_chunk_rag_document(**kwargs):
        return [
            RagDocumentChunk(
                document_id=kwargs["document_id"],
                chunk_index=0,
                text="References\nSmith J.",
                section_title="References",
                page_number=5,
                source_location="paper.pdf · 第 5 页",
                risk_flags=["references_section"],
            ),
            RagDocumentChunk(
                document_id=kwargs["document_id"],
                chunk_index=1,
                text="问诊时应先建立疼痛时间线。",
                section_title="病史采集",
                page_number=1,
                source_location="paper.pdf · 第 1 页",
            ),
        ]

    monkeypatch.setattr(main, "chunk_rag_document", fake_chunk_rag_document, raising=False)
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        upload_response = client.post(
            "/api/admin/rag/documents",
            json={
                "scope": "global",
                "file_name": "paper.pdf",
                "content_base64": base64.b64encode(b"pretend-pdf").decode("ascii"),
            },
        )
        document = upload_response.json()["document"]
        review_response = client.patch(
            f"/api/admin/rag/documents/{document['document_id']}/review",
            json={"decision": "rejected", "note": "参考文献段不入库"},
        )

    assert document["approved_chunk_count"] == 1
    assert document["pending_review_chunk_count"] == 1
    assert review_response.status_code == 200
    reviewed_document = review_response.json()["document"]
    assert reviewed_document["review_status"] == "mixed"
    assert reviewed_document["approved_chunk_count"] == 1
    assert reviewed_document["rejected_chunk_count"] == 1
    assert reviewed_document["pending_review_chunk_count"] == 0
    assert {item["review_status"] for item in review_response.json()["knowledge_items"]} == {
        "approved",
        "rejected",
    }


def test_admin_rejects_unsafe_or_unbound_rag_knowledge_items(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "rag_knowledge_store", RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3"), raising=False)
    base_payload = {
        "knowledge_id": "case:appendicitis_001:teaching:history_migration",
        "scope": "case",
        "case_id": "appendicitis_001",
        "content_kind": "teaching_note",
        "visibility": "pre_submit_safe",
        "allowed_agents": ["coach"],
        "source_id": "fareez_osce_2022",
        "title": "右下腹痛问诊中的疼痛迁移",
        "text": "追问疼痛演变。",
        "tags": ["history_taking"],
        "version": 1,
    }

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        missing_case_response = client.post(
            "/api/admin/rag/knowledge",
            json={**base_payload, "case_id": ""},
        )
        unknown_source_response = client.post(
            "/api/admin/rag/knowledge",
            json={**base_payload, "source_id": "unknown_source"},
        )
        superseded_source_response = client.post(
            "/api/admin/rag/knowledge",
            json={**base_payload, "source_id": "aafp_chronic_heart_failure_2007"},
        )
        secret_for_coach_response = client.post(
            "/api/admin/rag/knowledge",
            json={**base_payload, "visibility": "secret_scoring_only", "allowed_agents": ["coach"]},
        )
        unknown_stage_response = client.post(
            "/api/admin/rag/knowledge",
            json={**base_payload, "stage_scope": ["any", "operating_room"]},
        )
        empty_content_response = client.post(
            "/api/admin/rag/knowledge",
            json={
                "scope": "global",
                "content_kind": "",
                "visibility": "pre_submit_safe",
                "allowed_agents": ["coach"],
                "title": "",
                "text": "",
            },
        )

    assert missing_case_response.status_code == 400
    assert missing_case_response.json()["detail"] == "case knowledge requires a valid case_id"
    assert unknown_source_response.status_code == 400
    assert unknown_source_response.json()["detail"] == "source_id is not registered"
    assert superseded_source_response.status_code == 409
    assert superseded_source_response.json()["detail"] == (
        "source_id is not current; review the source ledger or select an active source"
    )
    assert secret_for_coach_response.status_code == 400
    assert secret_for_coach_response.json()["detail"] == "secret scoring knowledge cannot be exposed to generative agents"
    assert unknown_stage_response.status_code == 400
    assert unknown_stage_response.json()["detail"] == "unsupported knowledge stage scope"
    assert empty_content_response.status_code == 400
    assert empty_content_response.json()["detail"] == "knowledge content requires kind, title and text"


def test_admin_can_list_dynamic_teaching_focus_patterns(tmp_path, monkeypatch) -> None:
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/teaching-focus/patterns")

    assert response.status_code == 200
    payload = response.json()
    assert "patterns" in payload
    pattern_ids = [pattern["focus_id"] for pattern in payload["patterns"]]
    assert "case_baseline:appendicitis_001:history_taking" in pattern_ids
    assert "case_baseline:acs_001:auxiliary_test" in pattern_ids
    acs_pattern = next(pattern for pattern in payload["patterns"] if pattern["focus_id"] == "case_baseline:acs_001:auxiliary_test")
    assert acs_pattern["trigger_item_ids"] == ["at_ecg", "at_troponin"]
    assert acs_pattern["trigger_item_labels"] == ["申请心电图", "申请肌钙蛋白"]
    assert acs_pattern["source_reference_labels"] == ["评分项：申请心电图", "评分项：申请肌钙蛋白"]
    assert acs_pattern["case_titles"] == ["胸痛伴出汗教学病例"]
    assert acs_pattern["scope_label"] == "病例基础教学重点"
    assert acs_pattern["severity_label"] == "中等优先级"
    assert acs_pattern["source_report_count"] == 0
    assert acs_pattern["visibility_level"] == "student_safe"
    visible_text = "\n".join(
        [
            acs_pattern["title"],
            acs_pattern["description"],
            acs_pattern["training_suggestion"],
            acs_pattern["why_now"],
        ]
    )
    assert "急性冠脉综合征" not in visible_text
    assert "ACS" not in visible_text


def test_admin_can_read_dynamic_teaching_focus_pattern_detail(tmp_path, monkeypatch) -> None:
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/teaching-focus/patterns/case_baseline:appendicitis_001:history_taking")

    assert response.status_code == 200
    payload = response.json()
    assert payload["pattern"]["focus_id"] == "case_baseline:appendicitis_001:history_taking"
    assert payload["pattern"]["trigger_item_ids"][:2] == ["ht_onset", "ht_migration"]
    assert payload["pattern"]["trigger_item_labels"][:2] == ["追问起病时间", "追问疼痛部位及转移特征"]
    assert payload["pattern"]["source_reference_labels"][:2] == ["评分项：追问起病时间", "评分项：追问疼痛部位及转移特征"]


def test_admin_can_read_retrieval_eval_metrics(tmp_path, monkeypatch) -> None:
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/retrieval-eval")

    assert response.status_code == 200
    payload = response.json()["retrieval_eval"]
    assert payload["gold_set"]["path"].endswith("services/api/evals/retrieval/gold_queries.json")
    assert payload["metrics"]["query_count"] >= 3
    assert "recall_at_3" in payload["metrics"]
    assert "recall_at_5" in payload["metrics"]
    assert "mrr_at_5" in payload["metrics"]
    assert "ndcg_at_5" in payload["metrics"]
    assert "source_coverage" in payload["metrics"]
    assert payload["boundary"]["rag_usage"] == "feedback_explanation_learning_recommendation_traceability_only"
    assert "ChromaDB 是本地持久向量主路径" in payload["boundary"]["chroma_scope"]
    assert "BM25 词法召回" in payload["boundary"]["chroma_scope"]


def test_demo_admin_is_disabled_without_explicit_environment_config(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CLINICAL_OSCE_ADMIN_EMAILS", raising=False)
    for env_name in [
        "CLINICAL_OSCE_DEMO_ADMIN_ENABLED",
        "CLINICAL_OSCE_DEMO_ADMIN_EMAIL",
        "CLINICAL_OSCE_DEMO_ADMIN_PASSWORD",
    ]:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"), raising=False)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/auth/login",
            json={"email": "admin@osce.test", "password": "admin"},
        )

    assert response.status_code == 401


def test_demo_admin_enabled_without_password_does_not_use_hardcoded_fallback(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CLINICAL_OSCE_ADMIN_EMAILS", raising=False)
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_ENABLED", "true")
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_EMAIL", "admin@osce.test")
    monkeypatch.delenv("CLINICAL_OSCE_DEMO_ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"), raising=False)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/auth/login",
            json={"email": "admin@osce.test", "password": "admin"},
        )

    assert response.status_code == 401


def test_admin_can_read_model_config_without_secret_values(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_API_KEY", "gemini-secret-value")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_MODEL", "gemini-demo-model")
    monkeypatch.setenv("OSCE_VERTEX_ENABLED", "true")
    monkeypatch.setenv("OSCE_VERTEX_PROJECT", "demo-project")
    monkeypatch.setenv("OSCE_VERTEX_MODEL", "gemini-rubric-model")
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_PROJECT", "demo-project")
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "true")
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", str(tmp_path / "chroma-index"))
    monkeypatch.setenv("OSCE_CHROMA_COLLECTION", "osce_demo_retrieval")
    monkeypatch.setenv("OSCE_OPENAI_ENABLED", "true")
    monkeypatch.setenv("OSCE_OPENAI_API_KEY", "openai-secret-value")
    monkeypatch.setenv("OSCE_OPENAI_MODEL", "openai-demo-model")
    monkeypatch.setenv("OSCE_OPENAI_BASE_URL", "https://api.openai.example/v1")

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/model-config")

    assert response.status_code == 200
    response_text = response.text
    assert "gemini-secret-value" not in response_text
    assert "openai-secret-value" not in response_text
    assert "https://api.openai.example/v1" not in response_text
    payload = response.json()
    assert payload["policy"] == {
        "secrets_persisted": False,
        "runtime_write_supported": True,
        "configuration_source": "environment_default_only",
        "account_runtime_scope": "per_authenticated_user",
        "account_runtime_visible": False,
        "deployment_mode": "local-dev",
    }
    providers = {provider["provider_id"]: provider for provider in payload["providers"]}
    assert providers["gemini_patient_api"]["configured"] is True
    assert providers["gemini_patient_api"]["secret_configured"] is True
    assert providers["gemini_patient_api"]["model"] == "gemini-demo-model"
    assert providers["vertex_rubric_scorer"]["enabled"] is True
    assert providers["vertex_rubric_scorer"]["configured"] is True
    assert providers["vertex_rubric_scorer"]["missing_env"] == []
    assert providers["vertex_embedding_retrieval"]["enabled"] is True
    assert providers["vertex_embedding_retrieval"]["configured"] is True
    assert providers["vertex_embedding_retrieval"]["model"] == "gemini-embedding-001"
    assert providers["vertex_embedding_retrieval"]["project"] == "demo-project"
    assert providers["vertex_embedding_retrieval"]["integration_status"] == "wired_optional"
    assert providers["chroma_retrieval"]["enabled"] is True
    assert providers["chroma_retrieval"]["configured"] is True
    assert providers["chroma_retrieval"]["persist_directory"] == str(tmp_path / "chroma-index")
    assert providers["chroma_retrieval"]["collection"] == "osce_demo_retrieval"
    assert providers["chroma_retrieval"]["integration_status"] == "wired_optional"
    assert providers["openai_compatible"]["enabled"] is True
    assert providers["openai_compatible"]["configured"] is True
    assert providers["openai_compatible"]["model"] == "openai-demo-model"
    assert providers["openai_compatible"]["base_url"] == ""
    assert providers["openai_compatible"]["integration_status"] == "wired"


def test_admin_model_config_reports_chroma_index_manifest_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "true")
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", str(tmp_path / "chroma-index"))
    monkeypatch.setenv("OSCE_CHROMA_COLLECTION", "osce_demo_retrieval")
    monkeypatch.setenv("OSCE_CHROMA_SEARCH_EF", "733")
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_PROJECT", "demo-project")

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/model-config")

    assert response.status_code == 200
    providers = {provider["provider_id"]: provider for provider in response.json()["providers"]}
    manifest = providers["chroma_retrieval"]["index_manifest"]
    assert manifest["status"] == "missing"
    assert manifest["rebuild_required"] is True
    assert manifest["collection"] == "osce_demo_retrieval"
    assert manifest["embedding_model"] == "gemini-embedding-001"
    assert manifest["index_config"] == {"hnsw:space": "cosine", "hnsw:search_ef": 733}
    assert manifest["source_count"] >= 5
    assert "appendicitis_001" in manifest["case_ids"]
    assert manifest["manifest_path"].endswith("retrieval_index_manifest.json")


def test_admin_model_config_reports_local_embedding_and_chroma(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OSCE_VERTEX_EMBEDDING_ENABLED", raising=False)
    monkeypatch.setenv("OSCE_LOCAL_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("OSCE_LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    monkeypatch.setenv("OSCE_LOCAL_EMBEDDING_DEVICE", "cpu")
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "true")
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", str(tmp_path / "chroma-index"))

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/model-config")

    assert response.status_code == 200
    providers = {provider["provider_id"]: provider for provider in response.json()["providers"]}
    assert providers["local_embedding_retrieval"]["enabled"] is True
    assert providers["local_embedding_retrieval"]["configured"] is True
    assert providers["local_embedding_retrieval"]["model"] == "BAAI/bge-small-zh-v1.5"
    assert providers["local_embedding_retrieval"]["device"] == "cpu"
    assert providers["local_embedding_retrieval"]["integration_status"] == "wired_optional"
    assert providers["chroma_retrieval"]["enabled"] is True
    assert providers["chroma_retrieval"]["configured"] is True
    assert providers["chroma_retrieval"]["index_manifest"]["embedding_model"] == "BAAI/bge-small-zh-v1.5"


def test_admin_model_config_does_not_merge_account_runtime_vertex_gemini_adc(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", str(tmp_path / "chroma-index"))
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "vertex_gemini_adc",
            "api_key": "",
            "model": "gemini-3.1-pro-preview",
            "base_url": "demo-project",
            "proxy_url": "direct",
        }
    )

    try:
        with authenticated_admin_client(tmp_path, monkeypatch) as client:
            response = client.get("/api/admin/model-config")
    finally:
        runtime_model_config_store.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["policy"]["configuration_source"] == "environment_default_only"
    assert payload["policy"]["account_runtime_scope"] == "per_authenticated_user"
    assert payload["policy"]["account_runtime_visible"] is False
    providers = {provider["provider_id"]: provider for provider in response.json()["providers"]}
    assert providers["gemini_patient_vertex"]["configured"] is False
    assert providers["gemini_patient_vertex"]["project"] == ""
    assert providers["vertex_rubric_scorer"]["configured"] is False
    assert providers["vertex_skill_candidate"]["configured"] is False
    assert providers["vertex_embedding_retrieval"]["enabled"] is False
    assert providers["vertex_embedding_retrieval"]["configured"] is False
    assert providers["chroma_retrieval"]["enabled"] is False
    assert providers["chroma_retrieval"]["configured"] is False
    assert providers["chroma_retrieval"]["persist_directory"] == str(tmp_path / "chroma-index")


def test_admin_model_config_does_not_merge_account_runtime_vertex_gemini_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", str(tmp_path / "chroma-index"))
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "vertex_gemini_api_key",
            "api_key": "student-vertex-secret",
            "model": "gemini-2.5-flash",
            "base_url": "",
            "proxy_url": "http://127.0.0.1:7897",
        }
    )

    try:
        with authenticated_admin_client(tmp_path, monkeypatch) as client:
            response = client.get("/api/admin/model-config")
    finally:
        runtime_model_config_store.clear()

    assert response.status_code == 200
    response_text = response.text
    assert "student-vertex-secret" not in response_text
    providers = {provider["provider_id"]: provider for provider in response.json()["providers"]}
    for provider_id in ["gemini_patient_vertex", "vertex_rubric_scorer", "vertex_skill_candidate"]:
        assert providers[provider_id]["configured"] is False
        assert providers[provider_id]["secret_configured"] is False
        assert providers[provider_id]["project"] == ""
    assert providers["vertex_embedding_retrieval"]["enabled"] is False
    assert providers["vertex_embedding_retrieval"]["configured"] is False
    assert providers["vertex_embedding_retrieval"]["secret_configured"] is False
    assert providers["chroma_retrieval"]["enabled"] is False
    assert providers["chroma_retrieval"]["configured"] is False


def test_admin_can_read_raw_case_through_admin_namespace(tmp_path, monkeypatch) -> None:
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/cases/appendicitis_001/raw")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"case"}
    case_payload = payload["case"]
    assert case_payload["case_id"] == "appendicitis_001"
    assert case_payload["history"]["hidden_facts"][0]["canonical_answer"] == "24 小时前开始，最初是上腹部隐痛。"
    assert case_payload["diagnosis"]["reasoning_points"][0]["point_id"] == "appendicitis_001.rp_01"



def test_admin_can_validate_case_and_rubric_payload(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/admin/cases/validate", json={"case": case_payload, "rubric": rubric_payload})

    assert response.status_code == 200
    assert response.json() == {
        "valid": True,
        "case_id": "appendicitis_001",
        "rubric_id": "appendicitis_001_rubric",
        "errors": [],
    }



def test_admin_case_validate_returns_invalid_for_case_schema_error(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()
    invalid_case = deepcopy(case_payload)
    invalid_case["diagnosis"].pop("reasoning_points")

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/admin/cases/validate", json={"case": invalid_case, "rubric": rubric_payload})

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is False
    assert payload["case_id"] == "appendicitis_001"
    assert payload["rubric_id"] == "appendicitis_001_rubric"
    assert len(payload["errors"]) >= 1
    assert "reasoning_points" in " ".join(payload["errors"])



def test_admin_case_validate_returns_invalid_for_case_rubric_pair_error(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()
    invalid_rubric = deepcopy(rubric_payload)
    invalid_rubric["dimensions"][0]["items"][0]["evidence_expected"] = ["missing.evidence_id"]

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/admin/cases/validate", json={"case": case_payload, "rubric": invalid_rubric})

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is False
    assert payload["case_id"] == "appendicitis_001"
    assert payload["rubric_id"] == "appendicitis_001_rubric"
    assert len(payload["errors"]) == 1
    assert "rubric evidence missing from case" in payload["errors"][0]
    assert "missing.evidence_id" in payload["errors"][0]



def test_admin_can_import_valid_case_and_rubric_payload(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()
    cases_dir, rubrics_dir = configure_case_import_directories(tmp_path, monkeypatch)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/admin/cases/import", json={"case": case_payload, "rubric": rubric_payload})

    assert response.status_code == 200
    assert response.json() == {
        "imported": True,
        "case_id": "appendicitis_001",
        "rubric_id": "appendicitis_001_rubric",
        "errors": [],
    }
    assert json.loads((cases_dir / "appendicitis_001.json").read_text(encoding="utf-8")) == case_payload
    assert yaml.safe_load((rubrics_dir / "appendicitis_001_rubric.yaml").read_text(encoding="utf-8")) == rubric_payload



def test_admin_case_import_rejects_existing_case_without_overwrite(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()
    cases_dir, rubrics_dir = configure_case_import_directories(tmp_path, monkeypatch)
    existing_case_path = cases_dir / "appendicitis_001.json"
    existing_case_path.write_text('{"existing": true}', encoding="utf-8")

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/admin/cases/import", json={"case": case_payload, "rubric": rubric_payload})

    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] is False
    assert payload["case_id"] == "appendicitis_001"
    assert payload["rubric_id"] == "appendicitis_001_rubric"
    assert payload["errors"] == ["case already exists: appendicitis_001"]
    assert existing_case_path.read_text(encoding="utf-8") == '{"existing": true}'
    assert not (rubrics_dir / "appendicitis_001_rubric.yaml").exists()



def test_admin_case_import_rejects_existing_rubric_without_overwrite(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()
    cases_dir, rubrics_dir = configure_case_import_directories(tmp_path, monkeypatch)
    existing_rubric_path = rubrics_dir / "appendicitis_001_rubric.yaml"
    existing_rubric_path.write_text("rubric_id: existing\n", encoding="utf-8")

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/admin/cases/import", json={"case": case_payload, "rubric": rubric_payload})

    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] is False
    assert payload["case_id"] == "appendicitis_001"
    assert payload["rubric_id"] == "appendicitis_001_rubric"
    assert payload["errors"] == ["rubric already exists: appendicitis_001_rubric"]
    assert not (cases_dir / "appendicitis_001.json").exists()
    assert existing_rubric_path.read_text(encoding="utf-8") == "rubric_id: existing\n"



def test_admin_case_import_rejects_case_created_after_preflight_without_overwrite(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()
    cases_dir, rubrics_dir = configure_case_import_directories(tmp_path, monkeypatch)
    case_path = cases_dir / "appendicitis_001.json"
    original_open = Path.open

    def racing_open(self, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if self == case_path and ("w" in mode or "x" in mode):
            with original_open(self, "w", encoding="utf-8") as file:
                file.write('{"raced": true}')
            raise FileExistsError(str(self))
        return original_open(self, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", racing_open)

    with authenticated_admin_client(tmp_path, monkeypatch, raise_server_exceptions=False) as client:
        response = client.post("/api/admin/cases/import", json={"case": case_payload, "rubric": rubric_payload})

    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] is False
    assert payload["case_id"] == "appendicitis_001"
    assert payload["rubric_id"] == "appendicitis_001_rubric"
    assert payload["errors"] == ["case already exists: appendicitis_001"]
    assert case_path.read_text(encoding="utf-8") == '{"raced": true}'
    assert not (rubrics_dir / "appendicitis_001_rubric.yaml").exists()



def test_admin_case_import_rolls_back_case_when_rubric_write_fails(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()
    cases_dir, rubrics_dir = configure_case_import_directories(tmp_path, monkeypatch)
    rubric_path = rubrics_dir / "appendicitis_001_rubric.yaml"
    original_open = Path.open

    def failing_rubric_open(self, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if self == rubric_path and ("w" in mode or "x" in mode):
            raise OSError("rubric disk unavailable")
        return original_open(self, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", failing_rubric_open)

    with authenticated_admin_client(tmp_path, monkeypatch, raise_server_exceptions=False) as client:
        response = client.post("/api/admin/cases/import", json={"case": case_payload, "rubric": rubric_payload})

    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] is False
    assert payload["case_id"] == "appendicitis_001"
    assert payload["rubric_id"] == "appendicitis_001_rubric"
    assert len(payload["errors"]) == 1
    assert "import write failed" in payload["errors"][0]
    assert "rubric disk unavailable" in payload["errors"][0]
    assert not (cases_dir / "appendicitis_001.json").exists()
    assert not rubric_path.exists()



def test_admin_case_import_rejects_invalid_payload_without_writing(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()
    invalid_case = deepcopy(case_payload)
    invalid_case["diagnosis"].pop("reasoning_points")
    cases_dir, rubrics_dir = configure_case_import_directories(tmp_path, monkeypatch)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/admin/cases/import", json={"case": invalid_case, "rubric": rubric_payload})

    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] is False
    assert payload["case_id"] == "appendicitis_001"
    assert payload["rubric_id"] == "appendicitis_001_rubric"
    assert len(payload["errors"]) >= 1
    assert "reasoning_points" in " ".join(payload["errors"])
    assert not (cases_dir / "appendicitis_001.json").exists()
    assert not (rubrics_dir / "appendicitis_001_rubric.yaml").exists()



def test_admin_case_import_rejects_path_traversal_ids(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()
    unsafe_case = deepcopy(case_payload)
    unsafe_rubric = deepcopy(rubric_payload)
    unsafe_case["case_id"] = "../appendicitis_unsafe"
    unsafe_case["rubric_ref"]["rubric_id"] = "../appendicitis_unsafe_rubric"
    unsafe_rubric["case_id"] = "../appendicitis_unsafe"
    unsafe_rubric["rubric_id"] = "../appendicitis_unsafe_rubric"
    cases_dir, rubrics_dir = configure_case_import_directories(tmp_path, monkeypatch)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/admin/cases/import", json={"case": unsafe_case, "rubric": unsafe_rubric})

    assert response.status_code == 200
    assert response.json() == {
        "imported": False,
        "case_id": "../appendicitis_unsafe",
        "rubric_id": "../appendicitis_unsafe_rubric",
        "errors": ["invalid case_id: ../appendicitis_unsafe", "invalid rubric_id: ../appendicitis_unsafe_rubric"],
    }
    assert list(cases_dir.iterdir()) == []
    assert list(rubrics_dir.iterdir()) == []


def test_admin_can_update_case_metadata_fields(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()
    cases_dir, rubrics_dir = configure_case_import_directories(tmp_path, monkeypatch)
    case_path = cases_dir / "appendicitis_001.json"
    rubric_path = rubrics_dir / "appendicitis_001_rubric.yaml"
    case_path.write_text(json.dumps(case_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rubric_path.write_text(yaml.safe_dump(rubric_payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.patch(
            "/api/admin/cases/appendicitis_001/raw",
            json={
                "case_title": "急性右下腹痛追问训练",
                "chief_complaint": "转移性右下腹痛 12 小时",
                "course_module": "腹痛",
                "difficulty": "高级",
                "safety_notes": "仅用于 OSCE 教学训练，不能替代真实医生诊疗。",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["updated"] is True
    assert payload["case_id"] == "appendicitis_001"
    assert payload["rubric_id"] == "appendicitis_001_rubric"
    assert payload["errors"] == []
    assert payload["case"]["case_title"] == "急性右下腹痛追问训练"
    assert payload["case"]["chief_complaint"] == "转移性右下腹痛 12 小时"
    assert payload["case"]["difficulty"] == "高级"
    assert json.loads(case_path.read_text(encoding="utf-8"))["case_title"] == "急性右下腹痛追问训练"
    assert yaml.safe_load(rubric_path.read_text(encoding="utf-8")) == rubric_payload


def test_admin_case_update_rejects_invalid_metadata_without_writing(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()
    cases_dir, rubrics_dir = configure_case_import_directories(tmp_path, monkeypatch)
    case_path = cases_dir / "appendicitis_001.json"
    rubric_path = rubrics_dir / "appendicitis_001_rubric.yaml"
    case_path.write_text(json.dumps(case_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rubric_path.write_text(yaml.safe_dump(rubric_payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.patch(
            "/api/admin/cases/appendicitis_001/raw",
            json={"difficulty": "专家级"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["updated"] is False
    assert payload["case_id"] == "appendicitis_001"
    assert payload["rubric_id"] == "appendicitis_001_rubric"
    assert "difficulty" in " ".join(payload["errors"])
    assert json.loads(case_path.read_text(encoding="utf-8")) == case_payload


def test_admin_case_update_rejects_non_whitelisted_fields_without_writing(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()
    cases_dir, rubrics_dir = configure_case_import_directories(tmp_path, monkeypatch)
    case_path = cases_dir / "appendicitis_001.json"
    rubric_path = rubrics_dir / "appendicitis_001_rubric.yaml"
    case_path.write_text(json.dumps(case_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rubric_path.write_text(yaml.safe_dump(rubric_payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.patch(
            "/api/admin/cases/appendicitis_001/raw",
            json={
                "case_title": "不应写入",
                "diagnosis": {"main_diagnosis": "不应允许在线改写"},
            },
        )

    assert response.status_code == 422
    assert json.loads(case_path.read_text(encoding="utf-8")) == case_payload


def test_admin_can_update_rubric_item_description_field(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()
    cases_dir, rubrics_dir = configure_case_import_directories(tmp_path, monkeypatch)
    case_path = cases_dir / "appendicitis_001.json"
    rubric_path = rubrics_dir / "appendicitis_001_rubric.yaml"
    case_path.write_text(json.dumps(case_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rubric_path.write_text(yaml.safe_dump(rubric_payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.patch(
            "/api/admin/rubrics/appendicitis_001_rubric/items/ht_onset",
            json={"description": "追问腹痛起病时间与诱因"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["updated"] is True
    assert payload["rubric_id"] == "appendicitis_001_rubric"
    assert payload["case_id"] == "appendicitis_001"
    assert payload["item_id"] == "ht_onset"
    assert payload["errors"] == []
    assert payload["rubric"]["dimensions"][0]["items"][0]["description"] == "追问腹痛起病时间与诱因"
    assert json.loads(case_path.read_text(encoding="utf-8")) == case_payload
    assert yaml.safe_load(rubric_path.read_text(encoding="utf-8"))["dimensions"][0]["items"][0]["description"] == "追问腹痛起病时间与诱因"


def test_admin_rubric_item_update_rejects_non_whitelisted_fields_without_writing(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()
    cases_dir, rubrics_dir = configure_case_import_directories(tmp_path, monkeypatch)
    case_path = cases_dir / "appendicitis_001.json"
    rubric_path = rubrics_dir / "appendicitis_001_rubric.yaml"
    case_path.write_text(json.dumps(case_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rubric_path.write_text(yaml.safe_dump(rubric_payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.patch(
            "/api/admin/rubrics/appendicitis_001_rubric/items/ht_onset",
            json={
                "description": "不应写入",
                "match_rule": {"kind": "intent_keyword", "spec": {}},
            },
        )

    assert response.status_code == 422
    assert yaml.safe_load(rubric_path.read_text(encoding="utf-8")) == rubric_payload


def test_admin_rubric_item_update_rejects_unknown_item_without_writing(tmp_path, monkeypatch) -> None:
    case_payload, rubric_payload = load_case_and_rubric_payload()
    cases_dir, rubrics_dir = configure_case_import_directories(tmp_path, monkeypatch)
    case_path = cases_dir / "appendicitis_001.json"
    rubric_path = rubrics_dir / "appendicitis_001_rubric.yaml"
    case_path.write_text(json.dumps(case_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rubric_path.write_text(yaml.safe_dump(rubric_payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.patch(
            "/api/admin/rubrics/appendicitis_001_rubric/items/missing_item",
            json={"description": "不会写入"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "rubric item not found"}
    assert yaml.safe_load(rubric_path.read_text(encoding="utf-8")) == rubric_payload



def test_admin_can_list_training_skill_candidate_summaries(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    candidate_store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "status": "draft",
            "source_report_count": 3,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/evolution/candidates")

    assert response.status_code == 200
    payload = response.json()
    assert payload["pagination"] == {"limit": 1, "offset": 0, "total": 1}
    assert len(payload["candidates"]) == 1
    candidate = payload["candidates"][0]
    assert {
        "candidate_id": candidate["candidate_id"],
        "trigger_item_id": candidate["trigger_item_id"],
        "title": candidate["title"],
        "status": candidate["status"],
        "regression_passed": candidate["regression_passed"],
        "source_report_count": candidate["source_report_count"],
        "support_count": candidate["support_count"],
    } == {
        "candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "title": "临床推理链纠偏提示",
        "status": "ready_for_review",
        "regression_passed": True,
        "source_report_count": 3,
        "support_count": 2,
    }
    assert "trigger_item_labels" in candidate
    assert "case_titles" in candidate
    assert "skill_type_label" in candidate
    assert "stage_scope_labels" in candidate
    assert "effect_status_label" in candidate


def test_admin_candidate_summary_marks_case_incompatible_approved_candidate_blocked(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    candidate_store.save_candidate(
        {
            "candidate_id": "skill_candidate_training_pattern_dxd_ectopic",
            "trigger_item_id": "training_pattern_dxd_ectopic",
            "trigger_item_ids": ["dxd_ectopic", "dxd_urolith"],
            "case_ids": ["appendicitis_001"],
            "title": "急腹症鉴别诊断与全面评估逻辑训练",
            "description": "急腹症鉴别诊断反复遗漏，需补充妇科和泌尿系统排除。",
            "suggested_strategy": "面对急性腹痛患者时，请系统排除妇科、异位妊娠、泌尿科及肠道相关疾病。",
            "status": "draft",
            "source_report_count": 7,
            "support_count": 7,
        },
        {
            "candidate_id": "skill_candidate_training_pattern_dxd_ectopic",
            "status": "approved",
            "regression_passed": True,
            "evaluation_total_cases": 1,
            "evaluation_passed_cases": 1,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/evolution/candidates")
        detail_response = client.get("/api/admin/evolution/candidates/skill_candidate_training_pattern_dxd_ectopic")

    assert response.status_code == 200
    assert response.json()["candidates"][0]["status"] == "blocked_by_regression"
    assert response.json()["candidates"][0]["regression_passed"] is False
    assert detail_response.status_code == 200
    review = detail_response.json()["candidate"]["review"]
    assert review["status"] == "blocked_by_regression"
    assert review["regression_passed"] is False
    assert review["candidate_context_violations"][0]["case_id"] == "appendicitis_001"


def test_admin_can_paginate_and_filter_training_skill_candidate_summaries(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    for candidate_id, title, support_count in [
        ("skill_candidate_history_gap", "问诊漏项提醒", 1),
        ("skill_candidate_reasoning_core", "临床推理链纠偏提示", 2),
    ]:
        candidate_store.save_candidate(
            {
                "candidate_id": candidate_id,
                "trigger_item_id": candidate_id.replace("skill_candidate_", ""),
                "title": title,
                "status": "draft",
                "source_report_count": 3,
                "support_count": support_count,
            },
            {
                "candidate_id": candidate_id,
                "status": "ready_for_review",
                "regression_passed": True,
                "evaluation_total_cases": 2,
                "evaluation_passed_cases": 2,
                "evaluation_failed_cases": 0,
                "blocking_failures": [],
            },
        )
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        paged_response = client.get("/api/admin/evolution/candidates?limit=1&offset=1")
        filtered_response = client.get("/api/admin/evolution/candidates", params={"q": "推理链", "limit": 5})

    assert paged_response.status_code == 200
    paged_payload = paged_response.json()
    assert [candidate["candidate_id"] for candidate in paged_payload["candidates"]] == ["skill_candidate_reasoning_core"]
    assert paged_payload["pagination"] == {"limit": 1, "offset": 1, "total": 2}

    assert filtered_response.status_code == 200
    filtered_payload = filtered_response.json()
    assert [candidate["candidate_id"] for candidate in filtered_payload["candidates"]] == ["skill_candidate_reasoning_core"]
    assert filtered_payload["pagination"] == {"limit": 5, "offset": 0, "total": 1}


def test_admin_can_filter_training_skill_candidates_by_review_status(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    candidate_store.save_candidate(
        {
            "candidate_id": "skill_candidate_ready",
            "trigger_item_id": "ht_onset",
            "trigger_item_ids": ["ht_onset"],
            "case_ids": ["appendicitis_001"],
            "skill_type": "history_bundle",
            "stage_scope": ["history_taking"],
            "effect_status": "insufficient_samples",
            "applies_when": {
                "case_ids": ["appendicitis_001"],
                "stage_scope": ["history_taking"],
                "trigger_item_ids": ["ht_onset"],
            },
            "title": "临床推理链纠偏提示",
            "status": "draft",
            "source_report_count": 3,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_ready",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )
    candidate_store.save_candidate(
        {
            "candidate_id": "skill_candidate_blocked",
            "trigger_item_id": "training_pattern_dxd_ectopic",
            "trigger_item_ids": ["dxd_ectopic"],
            "case_ids": ["appendicitis_001"],
            "title": "急腹症鉴别诊断与全面评估逻辑训练",
            "description": "急腹症鉴别诊断反复遗漏，需补充妇科和泌尿系统排除。",
            "suggested_strategy": "面对急性腹痛患者时，请系统排除妇科、异位妊娠、泌尿科及肠道相关疾病。",
            "status": "draft",
            "source_report_count": 7,
            "support_count": 7,
            "related_recommendations": [
                "rubric:appendicitis_001_rubric.item.dxd_urolith",
                "rubric:appendicitis_001_rubric.item.dxd_ectopic",
            ],
        },
        {
            "candidate_id": "skill_candidate_blocked",
            "status": "approved",
            "regression_passed": True,
            "evaluation_total_cases": 1,
            "evaluation_passed_cases": 1,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )
    candidate_store.save_candidate(
        {
            "candidate_id": "skill_candidate_rejected",
            "trigger_item_id": "history_gap",
            "title": "问诊漏项提醒",
            "status": "draft",
            "source_report_count": 1,
            "support_count": 1,
        },
        {
            "candidate_id": "skill_candidate_rejected",
            "status": "rejected",
            "regression_passed": True,
            "evaluation_total_cases": 1,
            "evaluation_passed_cases": 1,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        ready_response = client.get("/api/admin/evolution/candidates", params={"review_status": "ready_for_review"})
        blocked_response = client.get("/api/admin/evolution/candidates", params={"review_status": "blocked_by_regression"})
        processed_response = client.get("/api/admin/evolution/candidates", params={"review_status": "processed"})
        detail_response = client.get("/api/admin/evolution/candidates/skill_candidate_ready")

    assert ready_response.status_code == 200
    ready_payload = ready_response.json()
    assert [candidate["candidate_id"] for candidate in ready_payload["candidates"]] == ["skill_candidate_ready"]
    assert ready_payload["pagination"]["total"] == 1
    assert ready_payload["candidates"][0]["case_titles"] == ["右下腹痛教学病例"]
    assert ready_payload["candidates"][0]["trigger_item_labels"] == ["追问起病时间"]
    assert ready_payload["candidates"][0]["skill_type_label"] == "病史采集训练"
    assert ready_payload["candidates"][0]["stage_scope_labels"] == ["问诊阶段"]
    assert ready_payload["candidates"][0]["effect_status_label"] == "样本不足"

    assert blocked_response.status_code == 200
    blocked_payload = blocked_response.json()
    assert [candidate["candidate_id"] for candidate in blocked_payload["candidates"]] == ["skill_candidate_blocked"]
    assert blocked_payload["candidates"][0]["status"] == "blocked_by_regression"
    assert blocked_payload["pagination"]["total"] == 1
    assert blocked_payload["candidates"][0]["trigger_item_labels"] == ["鉴别诊断：异位妊娠（历史字段）"]
    assert blocked_payload["candidates"][0]["related_recommendation_labels"] == [
        "评分项：提出当前病例诊断假设并说明排除依据",
        "评分项：鉴别诊断：异位妊娠（历史字段）",
    ]

    assert processed_response.status_code == 200
    assert [candidate["candidate_id"] for candidate in processed_response.json()["candidates"]] == ["skill_candidate_rejected"]
    assert processed_response.json()["pagination"]["total"] == 1

    assert detail_response.status_code == 200
    detail_candidate = detail_response.json()["candidate"]
    assert detail_candidate["case_titles"] == ["右下腹痛教学病例"]
    assert detail_candidate["trigger_item_labels"] == ["追问起病时间"]
    assert detail_candidate["skill_type_label"] == "病史采集训练"
    assert detail_candidate["stage_scope_labels"] == ["问诊阶段"]
    assert detail_candidate["effect_status_label"] == "样本不足"


def test_admin_enriches_skill_candidate_labels_from_related_references(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    candidate_store.save_candidate(
        {
            "candidate_id": "skill_candidate_reference_labels",
            "trigger_item_id": "training_pattern_dxd_urolith",
            "trigger_item_ids": ["dxd_urolith"],
            "title": "鉴别诊断证据链训练",
            "status": "draft",
            "source_report_count": 2,
            "support_count": 2,
            "related_recommendations": [
                "rubric:appendicitis_001_rubric.item.dxd_urolith",
            ],
        },
        {
            "candidate_id": "skill_candidate_reference_labels",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 1,
            "evaluation_passed_cases": 1,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        list_response = client.get("/api/admin/evolution/candidates", params={"review_status": "ready_for_review"})
        detail_response = client.get("/api/admin/evolution/candidates/skill_candidate_reference_labels")

    assert list_response.status_code == 200
    candidate_summary = list_response.json()["candidates"][0]
    assert candidate_summary["case_titles"] == ["右下腹痛教学病例"]
    assert candidate_summary["trigger_item_labels"] == ["提出当前病例诊断假设并说明排除依据"]
    assert candidate_summary["related_recommendation_labels"] == [
        "评分项：提出当前病例诊断假设并说明排除依据"
    ]

    assert detail_response.status_code == 200
    detail_candidate = detail_response.json()["candidate"]
    assert detail_candidate["case_titles"] == ["右下腹痛教学病例"]
    assert detail_candidate["trigger_item_labels"] == ["提出当前病例诊断假设并说明排除依据"]
    assert detail_candidate["related_recommendation_labels"] == [
        "评分项：提出当前病例诊断假设并说明排除依据"
    ]


def test_admin_can_list_training_session_summaries(tmp_path, monkeypatch) -> None:
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    session_store.create_session(
        OsceSession(
            session_id="session_admin_old",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="history",
        )
    )
    session_store.create_session(
        OsceSession(
            session_id="session_admin_recent",
            student_id="student_b",
            case_id="hyperthyroid_001",
            stage="diagnosis_submitted",
            active_skill_context={
                "skill_index": [],
                "selected_skills": [],
                "skipped_reasons": [
                    {"skill_id": "skill_history_bundle", "reason": "stage_mismatch"},
                    {"skill_id": "skill_retired_history", "reason": "profile_state_retired"},
                ],
            },
        )
    )
    monkeypatch.setattr(osce_session_service, "session_store", session_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/sessions")

    assert response.status_code == 200
    payload = response.json()
    assert [session["session_id"] for session in payload["sessions"]] == ["session_admin_recent", "session_admin_old"]
    assert payload["sessions"][0]["student_id"] == "student_b"
    assert payload["sessions"][0]["case_id"] == "hyperthyroid_001"
    assert payload["sessions"][0]["case_title"] == "心慌、手抖与消瘦教学病例"
    assert payload["sessions"][0]["stage"] == "diagnosis_submitted"
    assert payload["sessions"][0]["stage_label"] == "诊断已提交"
    assert isinstance(payload["sessions"][0]["created_at"], str)
    assert isinstance(payload["sessions"][0]["updated_at"], str)
    assert payload["sessions"][0]["active_skill_context"]["skipped_reasons"] == [
        {
            "skill_id": "skill_history_bundle",
            "reason": "stage_mismatch",
            "reason_label": "阶段不匹配",
            "reason_group": "适用范围",
            "reason_description": "该 Skill 适用阶段与当前训练阶段不同，本轮暂不注入。",
        },
        {
            "skill_id": "skill_retired_history",
            "reason": "profile_state_retired",
            "reason_label": "画像已退休",
            "reason_group": "学习画像",
            "reason_description": "学习画像显示该训练点长期稳定，默认不再注入。",
        },
    ]
    assert payload["pagination"] == {"limit": 2, "offset": 0, "total": 2}



def test_admin_can_paginate_training_session_summaries(tmp_path, monkeypatch) -> None:
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    session_store.create_session(
        OsceSession(
            session_id="session_admin_old",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="history",
        )
    )
    session_store.create_session(
        OsceSession(
            session_id="session_admin_recent",
            student_id="student_b",
            case_id="hyperthyroid_001",
            stage="diagnosis_submitted",
        )
    )
    monkeypatch.setattr(osce_session_service, "session_store", session_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/sessions?limit=1&offset=1")

    assert response.status_code == 200
    payload = response.json()
    assert [session["session_id"] for session in payload["sessions"]] == ["session_admin_old"]
    assert payload["pagination"] == {"limit": 1, "offset": 1, "total": 2}



def test_admin_can_filter_training_session_summaries(tmp_path, monkeypatch) -> None:
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    session_store.create_session(
        OsceSession(
            session_id="session_admin_old",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="history",
        )
    )
    session_store.create_session(
        OsceSession(
            session_id="session_admin_recent",
            student_id="student_b",
            case_id="hyperthyroid_001",
            stage="diagnosis_submitted",
        )
    )
    monkeypatch.setattr(osce_session_service, "session_store", session_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/sessions", params={"q": "student_b", "limit": 5})

    assert response.status_code == 200
    payload = response.json()
    assert [session["session_id"] for session in payload["sessions"]] == ["session_admin_recent"]
    assert payload["pagination"] == {"limit": 5, "offset": 0, "total": 1}



def test_admin_can_read_session_training_events(tmp_path, monkeypatch) -> None:
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    event_store.append_event(
        session_id="session_admin_log",
        case_id="appendicitis_001",
        student_id="student_admin_log",
        event_type="session_created",
        payload={"stage": "history"},
    )
    event_store.append_event(
        session_id="session_admin_log",
        case_id="appendicitis_001",
        student_id="student_admin_log",
        event_type="history_message",
        payload={"message": "右下腹痛多久了？"},
    )
    monkeypatch.setattr(osce_session_service, "training_event_store", event_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/sessions/session_admin_log/events")

    assert response.status_code == 200
    payload = response.json()
    assert [event["event_type"] for event in payload["events"]] == ["session_created", "history_message"]
    assert payload["events"][0]["session_id"] == "session_admin_log"
    assert payload["events"][0]["case_id"] == "appendicitis_001"
    assert payload["events"][0]["student_id"] == "student_admin_log"
    assert payload["events"][0]["payload"] == {"stage": "history"}
    assert payload["events"][1]["payload"] == {"message": "右下腹痛多久了？"}
    assert isinstance(payload["events"][0]["created_at"], str)



def test_admin_can_read_training_insights_from_all_sessions(tmp_path, monkeypatch) -> None:
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    session_store.create_session(
        OsceSession(
            session_id="session_insight_one",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="report_ready",
        )
    )
    session_store.create_session(
        OsceSession(
            session_id="session_insight_two",
            student_id="student_b",
            case_id="pneumonia_001",
            stage="report_ready",
        )
    )
    session_store.create_session(
        OsceSession(
            session_id="session_admin_eval",
            student_id="admin_eval_student_pass",
            case_id="appendicitis_001",
            stage="report_ready",
        )
    )
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    event_store.append_event(
        session_id="session_insight_one",
        case_id="appendicitis_001",
        student_id="student_a",
        event_type="report_generated",
        payload={
            "report_id": "report_one",
            "total_score": 55,
            "missed_items": ["ht_location", "reasoning_core"],
            "knowledge_recommendations": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                    "title": "补充临床推理证据链",
                },
                {
                    "reference": "case:acs_001",
                    "title": "胸痛伴出汗教学病例",
                },
            ],
            "source_reference_items": [
                {
                    "reference": "source:fareez_osce_2022",
                    "source_type": "source",
                    "title": "Fareez OSCE 数据集",
                    "metadata": {"license": "CC BY 4.0"},
                }
            ],
        },
    )
    event_store.append_event(
        session_id="session_insight_two",
        case_id="pneumonia_001",
        student_id="student_b",
        event_type="report_generated",
        payload={
            "report_id": "report_two",
            "total_score": 68,
            "missed_items": ["reasoning_core"],
            "knowledge_recommendations": [
                {
                    "reference": "rubric:pneumonia_001_rubric.item.reasoning_core",
                    "title": "补充临床推理证据链",
                }
            ],
            "source_reference_items": [
                {
                    "reference": "source:fareez_osce_2022",
                    "source_type": "source",
                    "title": "Fareez OSCE 数据集",
                    "metadata": {"license": "CC BY 4.0"},
                }
            ],
        },
    )
    event_store.append_event(
        session_id="session_admin_eval",
        case_id="appendicitis_001",
        student_id="admin_eval_student_pass",
        event_type="report_generated",
        payload={
            "report_id": "report_admin_eval",
            "total_score": 32,
            "missed_items": ["admin_eval_only"],
            "knowledge_recommendations": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.admin_eval_only",
                    "title": "系统评测专用漏项",
                }
            ],
            "source_reference_items": [
                {
                    "reference": "source:admin_eval_fixture",
                    "source_type": "source",
                    "title": "系统评测固定数据",
                    "metadata": {},
                }
            ],
        },
    )
    monkeypatch.setattr(osce_session_service, "session_store", session_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_event_store", event_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/insights")

    assert response.status_code == 200
    assert response.json() == {
        "insights": {
            "analysis_session_ids": [
                "session_insight_two",
                "session_insight_one",
            ],
            "analysis_report_ids": ["report_one", "report_two"],
            "session_count": 2,
            "report_count": 2,
            "frequent_missed_items": [
                {
                    "item_id": "reasoning_core",
                    "item_label": "推理链覆盖感染症状、体征和影像证据",
                    "count": 2,
                    "case_ids": ["appendicitis_001", "pneumonia_001"],
                    "session_ids": [
                        "session_insight_one",
                        "session_insight_two",
                    ],
                    "source_report_ids": ["report_one", "report_two"],
                    "case_titles": ["右下腹痛教学病例", "发热咳嗽伴胸痛教学病例"],
                },
                {
                    "item_id": "ht_location",
                    "item_label": "ht_location",
                    "count": 1,
                    "case_ids": ["appendicitis_001"],
                    "session_ids": ["session_insight_one"],
                    "source_report_ids": ["report_one"],
                    "case_titles": ["右下腹痛教学病例"],
                },
            ],
            "frequent_learning_recommendations": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                    "reference_label": "评分项：右下腹痛教学病例 / reasoning_core（当前 Rubric 未收录）",
                    "title": "补充临床推理证据链",
                    "count": 1,
                    "session_ids": ["session_insight_one"],
                    "source_report_ids": ["report_one"],
                },
                {
                    "reference": "rubric:pneumonia_001_rubric.item.reasoning_core",
                    "reference_label": "评分项：推理链覆盖感染症状、体征和影像证据",
                    "title": "补充临床推理证据链",
                    "count": 1,
                    "session_ids": ["session_insight_two"],
                    "source_report_ids": ["report_two"],
                },
            ],
            "frequent_source_references": [
                {
                    "reference": "source:fareez_osce_2022",
                    "reference_label": "来源：A dataset of simulated patient-physician medical interviews with a focus on respiratory cases",
                    "source_type": "source",
                    "title": "Fareez OSCE 数据集",
                    "count": 2,
                    "case_ids": ["appendicitis_001", "pneumonia_001"],
                    "case_titles": ["右下腹痛教学病例", "发热咳嗽伴胸痛教学病例"],
                    "metadata": {"license": "CC BY 4.0"},
                }
            ],
            "frequent_turn_patterns": [],
            "humanistic_communication": {
                "report_count": 0,
                "score_sample_count": 0,
                "average_score": 0,
                "max_score": 0,
                "average_percentage": None,
                "dimension_averages": [],
                "frequent_gaps": [],
                "frequent_missed_opportunities": [],
                "anchor_candidate_count": 0,
                "anchor_candidates_by_status": [],
                "trend": {
                    "previous_average_score": 0,
                    "recent_average_score": 0,
                    "delta": 0,
                },
                "percentage_trend": {
                    "previous_average_score": 0,
                    "recent_average_score": 0,
                    "delta": 0,
                },
            },
        }
    }


def test_admin_can_read_case_and_student_learning_analytics(tmp_path, monkeypatch) -> None:
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    report_store = ReportStore(tmp_path / "reports.sqlite3")
    session_store.create_session(
        OsceSession(
            session_id="session_admin_learning_one",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="feedback",
            patient_affect_state={
                "trajectory": [
                    {"event": "patient_signal_detected", "turn_id": "turn:1"},
                    {"event": "emotion_ignored", "turn_id": "turn:2"},
                ]
            },
        )
    )
    session_store.create_session(
        OsceSession(
            session_id="session_admin_learning_two",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="feedback",
            patient_affect_state={
                "trajectory": [
                    {"event": "patient_signal_detected", "turn_id": "turn:1"},
                    {"event": "emotion_repaired", "turn_id": "turn:2"},
                ]
            },
        )
    )
    session_store.create_session(
        OsceSession(
            session_id="session_admin_learning_other",
            student_id="student_b",
            case_id="pneumonia_001",
            stage="feedback",
        )
    )
    report_store.save_report(
        {
            "session_id": "session_admin_learning_one",
            "case_id": "appendicitis_001",
            "student_id": "student_a",
            "total_score": 60,
            "score_groups": {
                "clinical_osce": {"score": 43, "max_score": 70},
                "humanistic_communication": {"score": 17, "max_score": 30},
            },
            "missed_items": ["reasoning_core"],
            "training_gaps": [
                {
                    "gap_type": "relationship_empathy_missing",
                    "dimension_id": "relationship_building",
                    "label": "未回应患者担忧",
                    "missing_score": 3,
                    "next_training_action": "患者表达担忧后先回应情绪。",
                }
            ],
            "missed_opportunities": [
                {
                    "gap_type": "relationship_empathy_missing",
                    "expected_response": "先承认患者担忧，再继续问诊。",
                }
            ],
        }
    )
    report_store.save_report(
        {
            "session_id": "session_admin_learning_two",
            "case_id": "appendicitis_001",
            "student_id": "student_a",
            "total_score": 70,
            "score_groups": {
                "clinical_osce": {"score": 50, "max_score": 70},
                "humanistic_communication": {"score": 20, "max_score": 30},
            },
            "missed_items": ["reasoning_core"],
            "training_gaps": [
                {
                    "gap_type": "ethics_consent_missing",
                    "dimension_id": "medical_ethics",
                    "label": "查体前缺少同意",
                    "missing_score": 2,
                    "next_training_action": "查体前说明目的并征得同意。",
                }
            ],
            "missed_opportunities": [],
        }
    )
    report_store.save_report(
        {
            "session_id": "session_admin_learning_other",
            "case_id": "pneumonia_001",
            "student_id": "student_b",
            "total_score": 82,
            "score_groups": {
                "clinical_osce": {"score": 59, "max_score": 70},
                "humanistic_communication": {"score": 23, "max_score": 30},
            },
            "missed_items": [],
            "training_gaps": [],
            "missed_opportunities": [],
        }
    )
    monkeypatch.setattr(osce_session_service, "session_store", session_store, raising=False)
    monkeypatch.setattr(osce_session_service, "report_store", report_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/learning-analytics?case_id=appendicitis_001&student_id=student_a")

    assert response.status_code == 200
    analytics = response.json()["learning_analytics"]
    assert analytics["summary"] == {
        "session_count": 2,
        "report_count": 2,
        "case_count": 1,
        "student_count": 1,
    }
    assert analytics["cohort_analytics"]["scope"] == "all_users"
    assert analytics["cohort_analytics"]["student_count"] == 1
    assert analytics["cohort_analytics"]["average_total_score"] == 65
    assert analytics["cohort_analytics"]["frequent_humanistic_gaps"][0]["gap_type"] == "ethics_consent_missing"
    assert any("全用户" in action for action in analytics["cohort_analytics"]["teaching_actions"])
    assert any(
        drill["scope"] == "all_users" and drill["target_gap_type"] == "ethics_consent_missing"
        for drill in analytics["cohort_analytics"]["training_drills"]
    )
    assert analytics["case_analytics"][0]["case_id"] == "appendicitis_001"
    assert analytics["case_analytics"][0]["average_total_score"] == 65
    assert analytics["case_analytics"][0]["frequent_missed_items"][0] == {"item_id": "reasoning_core", "count": 2}
    assert analytics["case_analytics"][0]["frequent_humanistic_gaps"][0]["gap_type"] == "ethics_consent_missing"
    assert analytics["case_analytics"][0]["frequent_missed_opportunities"][0]["gap_type"] == "relationship_empathy_missing"
    assert analytics["case_analytics"][0]["affect_signals"] == {"signal_count": 2, "repaired_count": 1, "ignored_count": 1}
    assert analytics["case_analytics"][0]["training_drills"][0]["scope"] == "case"
    assert analytics["student_analytics"][0]["student_id"] == "student_a"
    assert analytics["student_analytics"][0]["current_humanistic_gaps"][0]["gap_type"] == "ethics_consent_missing"
    assert analytics["student_analytics"][0]["persistent_gaps"] == []
    assert any("查体前说明目的" in action for action in analytics["student_analytics"][0]["recommended_next_actions"])
    assert any(
        drill["source"] == "clinical_missed_item"
        and drill["target_gap_type"] == "reasoning_core"
        and drill["source_count"] == 2
        for drill in analytics["student_analytics"][0]["training_drills"]
    )
    assert analytics["student_analytics"][0]["training_drills"][0]["scope"] == "student"


def test_admin_can_read_training_skill_effect_summary_with_insufficient_samples(tmp_path, monkeypatch) -> None:
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    session_store.create_session(
        OsceSession(
            session_id="session_effect_with_skill",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="report_ready",
        )
    )
    session_store.create_session(
        OsceSession(
            session_id="session_effect_without_skill",
            student_id="student_b",
            case_id="appendicitis_001",
            stage="report_ready",
        )
    )
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    event_store.append_event(
        session_id="session_effect_with_skill",
        case_id="appendicitis_001",
        student_id="student_a",
        event_type="training_skill_applied",
        payload={
            "skill_id": "skill_training_pattern_reasoning_core",
            "title": "训练模式纠偏提示",
            "suggested_strategy": "提醒学生复盘证据链。",
        },
    )
    event_store.append_event(
        session_id="session_effect_with_skill",
        case_id="appendicitis_001",
        student_id="student_a",
        event_type="report_generated",
        payload={
            "report_id": "report_with_skill",
            "total_score": 70,
            "missed_items": ["ht_location"],
            "knowledge_recommendations": [],
        },
    )
    event_store.append_event(
        session_id="session_effect_without_skill",
        case_id="appendicitis_001",
        student_id="student_b",
        event_type="report_generated",
        payload={
            "report_id": "report_without_skill",
            "total_score": 55,
            "missed_items": ["ht_location", "reasoning_core"],
            "knowledge_recommendations": [],
        },
    )
    monkeypatch.setattr(osce_session_service, "session_store", session_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_event_store", event_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/evolution/skill-effects")

    assert response.status_code == 200
    assert response.json() == {
        "skill_effects": {
            "status": "insufficient_samples",
            "label": "样本不足",
            "min_sessions_per_group": 2,
            "score_delta": None,
            "with_skill": {
                "session_count": 1,
                "average_total_score": 70.0,
                "missed_item_counts": {"ht_location": 1},
                "skill_ids": ["skill_training_pattern_reasoning_core"],
            },
            "without_skill": {
                "session_count": 1,
                "average_total_score": 55.0,
                "missed_item_counts": {"ht_location": 1, "reasoning_core": 1},
                "skill_ids": [],
            },
        }
    }


def test_admin_can_read_rubric_detail(tmp_path, monkeypatch) -> None:
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/rubrics/appendicitis_001_rubric")

    assert response.status_code == 200
    rubric = response.json()["rubric"]
    assert rubric["rubric_id"] == "appendicitis_001_rubric"
    assert rubric["case_id"] == "appendicitis_001"
    assert rubric["version"] == "v1"
    assert rubric["total_score"] == 100
    assert rubric["schema_version"] == "1.1"
    assert rubric["dimensions"][0]["dimension_id"] == "history_taking"
    assert rubric["dimensions"][0]["weight"] == 18
    assert rubric["dimensions"][0]["scoring_mode"] == "rule"
    assert rubric["dimensions"][0]["items"][0] == {
        "item_id": "ht_onset",
        "description": "追问起病时间",
        "max_score": 2,
        "match_rule": {
            "kind": "intent_keyword",
            "spec": {
                "topic": "现病史",
                "slot": "onset",
                "any_of_keywords": ["什么时候", "何时", "起病", "开始"],
            },
        },
        "evidence_expected": ["appendicitis_001.hf_01"],
    }


def test_admin_rubric_detail_returns_404_for_missing_rubric(tmp_path, monkeypatch) -> None:
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/rubrics/missing_rubric")

    assert response.status_code == 404
    assert response.json() == {"detail": "rubric not found"}


def test_admin_can_list_source_registry_entries(tmp_path, monkeypatch) -> None:
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/sources")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["sources"]) >= 17
    assert {source["source_id"] for source in payload["sources"]} >= {
        "aafp_acute_abdominal_pain_2023",
        "merck_appendicitis_professional",
        "statpearls_appendicitis_2025",
        "statpearls_acute_abdomen_2025",
        "aha_acc_chest_pain_guideline_2021",
        "aha_acc_hf_guideline_2022",
        "ata_hyperthyroidism_guideline_2016",
        "ats_idsa_cap_guideline_2019",
    }
    first_source = payload["sources"][0]
    assert first_source["source_id"] == "fareez_osce_2022"
    assert first_source["title"] == first_source["source_name"]
    assert first_source["source_type"] == "dialogue"
    assert first_source["freshness_status"] == "current"
    assert first_source["review_due_at"] == "2028-08-03"
    assert first_source["selectable_for_new_knowledge"] is True
    assert payload["freshness_summary"] == {
        "total": 17,
        "current": 13,
        "review_due": 0,
        "superseded": 4,
        "unverified": 0,
    }


def test_admin_can_create_review_version_rollback_and_deactivate_source(
    tmp_path,
    monkeypatch,
) -> None:
    source_registry_path = tmp_path / "sources.json"
    source_registry_path.write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(main, "SOURCE_REGISTRY_PATH", source_registry_path, raising=False)
    base_payload = {
        "source_id": "clinical_guideline_demo_2026",
        "source_name": "临床指南演示来源",
        "source_url": "https://example.test/guideline",
        "license": "CC BY 4.0",
        "data_type": "clinical_guideline",
        "allowed_usage": ["training_reference"],
        "transformation": "人工结构化摘录",
        "attribution_required": True,
        "risk_note": "仅用于教学演示",
        "source_version": "v1",
        "last_reviewed_at": "2026-08-04",
        "review_interval_days": 365,
        "source_status": "active",
        "superseded_by": "",
        "review_basis": "核对原始指南页面",
        "search_aliases": ["演示指南"],
        "change_note": "创建演示来源",
        "medical_review_note": "初次登记",
    }

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        create_response = client.post("/api/admin/sources", json=base_payload)
        assert create_response.status_code == 201
        assert create_response.json()["version"]["version"] == 1

        updated_payload = {
            **base_payload,
            "source_name": "临床指南演示来源（修订）",
            "source_version": "v2",
            "change_note": "更新来源版本",
        }
        update_response = client.put(
            "/api/admin/sources/clinical_guideline_demo_2026",
            json=updated_payload,
        )
        assert update_response.status_code == 200
        assert update_response.json()["version"]["version"] == 2

        review_response = client.post(
            "/api/admin/sources/clinical_guideline_demo_2026/review",
            json={
                "last_reviewed_at": "2026-08-04",
                "review_interval_days": 730,
                "review_basis": "医学教师复核来源正文与许可",
                "source_status": "active",
                "superseded_by": "",
                "medical_review_note": "可继续用于教学知识库",
            },
        )
        assert review_response.status_code == 200
        assert review_response.json()["version"]["version"] == 3

        versions_response = client.get(
            "/api/admin/sources/clinical_guideline_demo_2026/versions"
        )
        assert versions_response.status_code == 200
        assert [item["version"] for item in versions_response.json()["versions"]] == [3, 2, 1]

        diff_response = client.get(
            "/api/admin/sources/clinical_guideline_demo_2026/diff?from_version=1&to_version=2"
        )
        assert diff_response.status_code == 200
        assert {change["path"] for change in diff_response.json()["changes"]} >= {
            "$.source_name",
            "$.source_version",
        }

        rollback_response = client.post(
            "/api/admin/sources/clinical_guideline_demo_2026/rollback",
            json={"version": 1, "change_note": "恢复初始来源"},
        )
        assert rollback_response.status_code == 200
        assert rollback_response.json()["source"]["source_name"] == "临床指南演示来源"
        assert rollback_response.json()["version"]["version"] == 4

        deactivate_response = client.delete(
            "/api/admin/sources/clinical_guideline_demo_2026"
        )
        assert deactivate_response.status_code == 200
        assert deactivate_response.json()["source"]["source_status"] == "inactive"
        assert deactivate_response.json()["source"]["selectable_for_new_knowledge"] is False

        audit_actions = {
            event["action"]
            for event in client.get("/api/admin/audit-events?limit=100").json()["events"]
        }
        assert audit_actions >= {
            "source.created",
            "source.updated",
            "source.reviewed",
            "source.rolled_back",
            "source.deactivated",
        }


def test_admin_can_replace_review_diff_and_rollback_complete_case_assets(
    tmp_path,
    monkeypatch,
) -> None:
    cases_dir, rubrics_dir = configure_case_import_directories(tmp_path, monkeypatch)
    case_payload, rubric_payload = load_case_and_rubric_payload()
    case_path = cases_dir / "appendicitis_001.json"
    rubric_path = rubrics_dir / "appendicitis_001_rubric.yaml"
    case_path.write_text(json.dumps(case_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rubric_path.write_text(yaml.safe_dump(rubric_payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        initial_response = client.get("/api/admin/cases/appendicitis_001/assets")
        assert initial_response.status_code == 200
        assert initial_response.json()["current_version"]["version"] == 1

        edited_case = deepcopy(case_payload)
        edited_case["history"]["hidden_facts"][0]["canonical_answer"] = "昨晚九点左右开始疼。"
        edited_rubric = deepcopy(rubric_payload)
        edited_rubric["dimensions"][0]["weight"] = 19
        edited_rubric["dimensions"][0]["items"][0]["max_score"] += 1
        edited_rubric["dimensions"][1]["weight"] = 9
        edited_rubric["dimensions"][1]["items"][-1]["max_score"] -= 1
        replace_response = client.put(
            "/api/admin/cases/appendicitis_001/assets",
            json={
                "case": edited_case,
                "rubric": edited_rubric,
                "change_note": "修订起病时间表达并调整维度权重",
                "review_status": "unreviewed",
                "medical_review_note": "等待教师复核",
            },
        )
        assert replace_response.status_code == 200, replace_response.text
        assert replace_response.json()["current_version"]["version"] == 2
        assert json.loads(case_path.read_text(encoding="utf-8"))["history"]["hidden_facts"][0]["canonical_answer"] == "昨晚九点左右开始疼。"

        diff_response = client.get(
            "/api/admin/cases/appendicitis_001/diff?from_version=1&to_version=2"
        )
        assert diff_response.status_code == 200
        changed_paths = {change["path"] for change in diff_response.json()["changes"]}
        assert "$.case.history.hidden_facts[0].canonical_answer" in changed_paths
        assert "$.rubric.dimensions[0].weight" in changed_paths

        review_response = client.post(
            "/api/admin/cases/appendicitis_001/review",
            json={
                "review_status": "approved",
                "medical_review_note": "医学教师核对病例事实与评分权重后通过",
            },
        )
        assert review_response.status_code == 200
        assert review_response.json()["current_version"]["version"] == 3
        assert review_response.json()["current_version"]["review_status"] == "approved"

        rollback_response = client.post(
            "/api/admin/cases/appendicitis_001/rollback",
            json={"version": 1, "change_note": "恢复答辩基线"},
        )
        assert rollback_response.status_code == 200
        assert rollback_response.json()["current_version"]["version"] == 4
        restored_case = json.loads(case_path.read_text(encoding="utf-8"))
        assert restored_case["history"]["hidden_facts"][0]["canonical_answer"] == case_payload["history"]["hidden_facts"][0]["canonical_answer"]

        versions = client.get("/api/admin/cases/appendicitis_001/versions").json()["versions"]
        assert [item["version"] for item in versions] == [4, 3, 2, 1]
        audit_actions = {
            event["action"]
            for event in client.get("/api/admin/audit-events?limit=100").json()["events"]
        }
        assert audit_actions >= {
            "case.assets_updated",
            "case.approved",
            "case.rolled_back",
        }


def test_admin_can_list_evaluation_batch_summaries(tmp_path, monkeypatch) -> None:
    evaluation_store = EvaluationResultStore(tmp_path / "evaluation_results.sqlite3")
    evaluation_store.save_batch_result(
        "batch_smoke",
        EvaluationBatchResult(total_cases=2, passed_cases=2, failed_cases=0, results=[], passed=True, total_duration_ms=120),
    )
    evaluation_store.save_batch_result(
        "batch_regression",
        EvaluationBatchResult(total_cases=3, passed_cases=2, failed_cases=1, results=[], passed=False, total_duration_ms=300),
    )
    monkeypatch.setattr(main, "evaluation_result_store", evaluation_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/evaluations")

    assert response.status_code == 200
    assert response.json() == {
        "evaluations": [
            {
                "batch_id": "batch_smoke",
                "batch_label": "冒烟评测批次",
                "total_cases": 2,
                "passed_cases": 2,
                "failed_cases": 0,
                "passed": True,
            },
            {
                "batch_id": "batch_regression",
                "batch_label": "回归评测批次",
                "total_cases": 3,
                "passed_cases": 2,
                "failed_cases": 1,
                "passed": False,
            },
        ],
        "pagination": {"limit": 2, "offset": 0, "total": 2},
    }


def test_admin_evaluation_service_uses_deterministic_agents(monkeypatch) -> None:
    graph = object()
    graph_options: dict[str, object] = {}

    def build_graph(**kwargs):
        graph_options.update(kwargs)
        return graph

    monkeypatch.setattr(main, "build_osce_graph", build_graph)

    service = main._build_admin_evaluation_service()

    assert service.osce_graph is graph
    assert isinstance(graph_options["coach_agent"], main.DeterministicCoachAgent)
    assert isinstance(graph_options["turn_intent_agent"], main.DeterministicTurnIntentAgent)
    assert graph_options["llm_scorer"] is None
    assert isinstance(service.personal_skill_service, main.PersonalTrainingSkillService)
    assert isinstance(
        service.personal_skill_service._generator,
        main.TemplateTrainingSkillCandidateGenerator,
    )
    assert isinstance(
        service.personal_skill_service._teacher_agent,
        main.DeterministicTeacherAgent,
    )


def test_admin_can_manage_evaluation_cases_suites_thresholds_and_schedule(
    tmp_path,
    monkeypatch,
) -> None:
    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        initial_config = client.get("/api/admin/evaluation-config")
        assert initial_config.status_code == 200
        assert [item["suite_id"] for item in initial_config.json()["suites"]] == [
            "default_regression"
        ]

        case_response = client.put(
            "/api/admin/evaluation-cases/pneumonia_communication",
            json={
                "case_key": "pneumonia_communication",
                "label": "肺炎问诊与诊断链路",
                "case_id": "pneumonia_001",
                "steps": [
                    {"kind": "message", "value": "什么时候开始发热和咳嗽？"},
                    {
                        "kind": "submit_diagnosis",
                        "value": "社区获得性肺炎",
                        "reasoning": "发热、咳嗽和胸痛支持肺炎。",
                    },
                ],
                "expected_total_score": 18,
                "forbidden_terms": ["抗生素剂量"],
                "enabled": True,
            },
        )
        assert case_response.status_code == 200, case_response.text

        suite_response = client.put(
            "/api/admin/evaluation-suites/respiratory_regression",
            json={
                "suite_id": "respiratory_regression",
                "label": "呼吸系统回归套件",
                "description": "验证肺炎问诊、诊断和 RAG 证据。",
                "case_keys": ["pneumonia_communication"],
                "thresholds": {
                    "maximum_score_delta": 2,
                    "minimum_batch_pass_rate": 0.8,
                    "minimum_rag_explanation_coverage_ratio": 0.9,
                    "minimum_rag_evidence_coverage_ratio": 0.9,
                    "require_rag_source_coverage": True,
                    "maximum_case_duration_ms": 120000,
                },
                "enabled": True,
            },
        )
        assert suite_response.status_code == 200, suite_response.text
        assert suite_response.json()["suite"]["case_keys"] == [
            "pneumonia_communication"
        ]

        schedule_response = client.patch(
            "/api/admin/evaluation-schedule",
            json={
                "enabled": True,
                "suite_id": "respiratory_regression",
                "interval_minutes": 60,
            },
        )
        assert schedule_response.status_code == 200, schedule_response.text
        assert schedule_response.json()["schedule"]["status"] == "scheduled"
        assert schedule_response.json()["schedule"]["next_run_at"]

        referenced_delete = client.delete(
            "/api/admin/evaluation-cases/pneumonia_communication"
        )
        assert referenced_delete.status_code == 409

        config = client.get("/api/admin/evaluation-config").json()
        assert {item["case_key"] for item in config["evaluation_cases"]} == {
            "appendicitis_complete_flow",
            "pneumonia_communication",
        }
        assert {item["suite_id"] for item in config["suites"]} == {
            "default_regression",
            "respiratory_regression",
        }
        audit_actions = {
            event["action"]
            for event in client.get("/api/admin/audit-events?limit=100").json()["events"]
        }
        assert audit_actions >= {
            "evaluation_case.created",
            "evaluation_suite.created",
            "evaluation_schedule.enabled",
        }


def test_due_evaluation_schedule_runs_persists_and_audits(tmp_path, monkeypatch) -> None:
    evaluation_config_store = AdminEvaluationConfigStore(
        tmp_path / "admin_evaluation_config.sqlite3"
    )
    evaluation_result_store = EvaluationResultStore(
        tmp_path / "evaluation_results.sqlite3"
    )
    audit_store = AdminAuditStore(tmp_path / "admin_audit.sqlite3")
    monkeypatch.setattr(
        main,
        "admin_evaluation_config_store",
        evaluation_config_store,
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "evaluation_result_store",
        evaluation_result_store,
        raising=False,
    )
    monkeypatch.setattr(main, "admin_audit_store", audit_store, raising=False)
    main._ensure_admin_evaluation_config_defaults()
    schedule = evaluation_config_store.update_schedule(
        {
            "enabled": True,
            "suite_id": "default_regression",
            "interval_minutes": 5,
        },
        updated_by="admin@example.com",
    )

    fake_result = EvaluationBatchResult(
        total_cases=1,
        passed_cases=1,
        failed_cases=0,
        results=[],
        passed=True,
        total_duration_ms=10,
    )
    monkeypatch.setattr(
        main,
        "_run_admin_evaluation_suite",
        lambda suite_id: (
            fake_result,
            evaluation_config_store.get_suite(suite_id),
        ),
    )
    due_at = datetime.fromisoformat(schedule["next_run_at"]) + timedelta(seconds=1)

    result = main._run_due_admin_evaluation_schedule(due_at)

    assert result is not None
    assert result["passed"] is True
    persisted = evaluation_result_store.get_batch_result(result["batch_id"])
    assert persisted is not None
    assert persisted["triggered_by"] == "schedule"
    completed_schedule = evaluation_config_store.get_schedule()
    assert completed_schedule["last_batch_id"] == result["batch_id"]
    assert completed_schedule["status"] == "scheduled"
    assert audit_store.list_events()["events"][0]["action"] == "evaluation.schedule_completed"


def test_admin_can_paginate_and_filter_evaluation_batch_summaries(tmp_path, monkeypatch) -> None:
    evaluation_store = EvaluationResultStore(tmp_path / "evaluation_results.sqlite3")
    evaluation_store.save_batch_result(
        "batch_smoke",
        EvaluationBatchResult(total_cases=2, passed_cases=2, failed_cases=0, results=[], passed=True, total_duration_ms=120),
    )
    evaluation_store.save_batch_result(
        "batch_regression",
        EvaluationBatchResult(total_cases=3, passed_cases=2, failed_cases=1, results=[], passed=False, total_duration_ms=300),
    )
    monkeypatch.setattr(main, "evaluation_result_store", evaluation_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        paged_response = client.get("/api/admin/evaluations?limit=1&offset=1")
        filtered_response = client.get("/api/admin/evaluations", params={"q": "regression", "limit": 5})

    assert paged_response.status_code == 200
    paged_payload = paged_response.json()
    assert [evaluation["batch_id"] for evaluation in paged_payload["evaluations"]] == ["batch_regression"]
    assert paged_payload["pagination"] == {"limit": 1, "offset": 1, "total": 2}

    assert filtered_response.status_code == 200
    filtered_payload = filtered_response.json()
    assert [evaluation["batch_id"] for evaluation in filtered_payload["evaluations"]] == ["batch_regression"]
    assert filtered_payload["pagination"] == {"limit": 5, "offset": 0, "total": 1}



def test_admin_can_read_evaluation_batch_detail(tmp_path, monkeypatch) -> None:
    evaluation_store = EvaluationResultStore(tmp_path / "evaluation_results.sqlite3")
    evaluation_store.save_batch_result(
        "batch_regression",
        EvaluationBatchResult(
            total_cases=1,
            passed_cases=0,
            failed_cases=1,
            results=[
                EvaluationResult(
                    session_id="session_eval_failed",
                    actual_total_score=40,
                    expected_total_score=80,
                    forbidden_term_violations=["治疗方案"],
                    passed=False,
                    duration_ms=66,
                )
            ],
            passed=False,
            total_duration_ms=66,
        ),
    )
    monkeypatch.setattr(main, "evaluation_result_store", evaluation_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/evaluations/batch_regression")

    assert response.status_code == 200
    assert response.json() == {
        "evaluation": {
            "batch_id": "batch_regression",
            "batch_label": "回归评测批次",
            "total_cases": 1,
            "passed_cases": 0,
            "failed_cases": 1,
            "passed": False,
            "total_duration_ms": 66,
            "results": [
                {
                    "session_id": "session_eval_failed",
                    "actual_total_score": 40,
                    "expected_total_score": 80,
                    "forbidden_term_violations": ["治疗方案"],
                    "passed": False,
                    "source_reference_count": 0,
                    "source_reference_types": [],
                    "rag_source_coverage_passed": False,
                    "rag_rubric_reference_coverage_ratio": 0.0,
                    "missing_rubric_references": [],
                    "rag_explanation_coverage_passed": False,
                    "rag_explanation_coverage_ratio": 0.0,
                    "missing_explanation_references": [],
                    "rag_evidence_coverage_passed": False,
                    "rag_evidence_coverage_ratio": 0.0,
                    "missing_evidence_references": [],
                    "rag_knowledge_safety_passed": True,
                    "forbidden_rag_knowledge_references": [],
                    "rag_score_isolation_passed": True,
                    "rag_score_isolation_violations": [],
                    "rag_agent_grounding_passed": True,
                    "missing_agent_knowledge_references": [],
                    "duration_ms": 66,
                }
            ],
        }
    }



def test_admin_evaluation_detail_returns_404_for_missing_batch(tmp_path, monkeypatch) -> None:
    evaluation_store = EvaluationResultStore(tmp_path / "evaluation_results.sqlite3")
    monkeypatch.setattr(main, "evaluation_result_store", evaluation_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/evaluations/missing_batch")

    assert response.status_code == 404
    assert response.json() == {"detail": "evaluation batch not found"}



def test_admin_can_run_real_evaluation_batch_without_gemini_patient_api_key(tmp_path, monkeypatch) -> None:
    evaluation_store = EvaluationResultStore(tmp_path / "evaluation_results.sqlite3")
    session_service = OsceSessionService(
        report_store=ReportStore(tmp_path / "reports.sqlite3"),
        training_event_store=TrainingEventStore(tmp_path / "training_events.sqlite3"),
        training_skill_store=TrainingSkillStore(tmp_path / "training_skills.sqlite3"),
        session_store=OsceSessionStore(tmp_path / "osce_sessions.sqlite3"),
    )

    def fail_if_gemini_responder_is_used():
        raise AssertionError("admin eval should not call Gemini patient responder")

    monkeypatch.setattr(main, "evaluation_result_store", evaluation_store, raising=False)
    monkeypatch.setattr(main, "osce_session_service", session_service, raising=False)
    monkeypatch.setattr(
        gemini_patient_responder_module,
        "_create_configured_responder",
        fail_if_gemini_responder_is_used,
        raising=False,
    )

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/admin/evals/run", json={"batch_id": "batch_admin_real"})

    assert response.status_code == 200
    evaluation = response.json()["evaluation"]
    assert evaluation["batch_id"] == "batch_admin_real"
    assert evaluation["total_cases"] == 1
    assert evaluation["results"][0]["source_reference_count"] > 0
    assert evaluation["results"][0]["rag_source_coverage_passed"] is True
    assert evaluation["results"][0]["rag_explanation_coverage_passed"] is True
    assert evaluation["results"][0]["rag_evidence_coverage_passed"] is True
    assert evaluation_store.get_batch_result("batch_admin_real") == evaluation



def test_admin_can_run_evaluation_batch(tmp_path, monkeypatch) -> None:
    evaluation_store = EvaluationResultStore(tmp_path / "evaluation_results.sqlite3")
    captured_case_ids: list[str] = []
    captured_service = None

    def fake_run_evaluation_cases(evaluation_cases, service, thresholds=None):
        nonlocal captured_service
        captured_case_ids.extend(evaluation_case.case_id for evaluation_case in evaluation_cases)
        captured_service = service
        return EvaluationBatchResult(
            total_cases=1,
            passed_cases=1,
            failed_cases=0,
            results=[
                EvaluationResult(
                    session_id="session_admin_eval",
                    actual_total_score=32,
                    expected_total_score=32,
                    forbidden_term_violations=[],
                    source_reference_count=3,
                    source_reference_types=["case", "source", "rubric"],
                    rag_source_coverage_passed=True,
                    rag_rubric_reference_coverage_ratio=1.0,
                    missing_rubric_references=[],
                    rag_explanation_coverage_passed=True,
                    rag_explanation_coverage_ratio=1.0,
                    missing_explanation_references=[],
                    rag_evidence_coverage_passed=True,
                    rag_evidence_coverage_ratio=1.0,
                    missing_evidence_references=[],
                    passed=True,
                    duration_ms=42,
                )
            ],
            passed=True,
            total_duration_ms=42,
        )

    monkeypatch.setattr(main, "evaluation_result_store", evaluation_store, raising=False)
    monkeypatch.setattr(main, "run_evaluation_cases", fake_run_evaluation_cases, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/admin/evals/run", json={"batch_id": "batch_admin_manual"})

        expected_evaluation = {
            "batch_id": "batch_admin_manual",
            "batch_label": "系统评测批次",
            "total_cases": 1,
        "passed_cases": 1,
        "failed_cases": 0,
        "results": [
            {
                "session_id": "session_admin_eval",
                "actual_total_score": 32,
                "expected_total_score": 32,
                "forbidden_term_violations": [],
                "passed": True,
                "source_reference_count": 3,
                "source_reference_types": ["case", "source", "rubric"],
                "rag_source_coverage_passed": True,
                "rag_rubric_reference_coverage_ratio": 1.0,
                "missing_rubric_references": [],
                "rag_explanation_coverage_passed": True,
                "rag_explanation_coverage_ratio": 1.0,
                "missing_explanation_references": [],
                "rag_evidence_coverage_passed": True,
                "rag_evidence_coverage_ratio": 1.0,
                "missing_evidence_references": [],
                "rag_knowledge_safety_passed": True,
                "forbidden_rag_knowledge_references": [],
                "rag_score_isolation_passed": True,
                "rag_score_isolation_violations": [],
                "rag_agent_grounding_passed": True,
                "missing_agent_knowledge_references": [],
                "duration_ms": 42,
            }
        ],
        "passed": True,
        "total_duration_ms": 42,
    }
    assert response.status_code == 200
    returned_evaluation = response.json()["evaluation"]
    assert returned_evaluation["suite_id"] == "default_regression"
    assert returned_evaluation["suite_label"] == "默认核心回归套件"
    assert returned_evaluation["triggered_by"] == main._get_demo_admin_email()
    assert returned_evaluation["created_at"]
    assert returned_evaluation["thresholds"]["minimum_batch_pass_rate"] == 1.0
    assert {
        key: value
        for key, value in returned_evaluation.items()
        if key not in {"suite_id", "suite_label", "triggered_by", "created_at", "thresholds"}
    } == expected_evaluation
    assert evaluation_store.get_batch_result("batch_admin_manual") == returned_evaluation
    assert captured_case_ids == ["appendicitis_001"]
    assert isinstance(captured_service, OsceSessionService)
    assert captured_service is not osce_session_service
    assert captured_service.report_store is osce_session_service.report_store
    assert captured_service.training_event_store is osce_session_service.training_event_store
    assert captured_service.training_skill_store is osce_session_service.training_skill_store
    assert captured_service.session_store is osce_session_service.session_store



def test_admin_can_generate_training_skill_candidates_from_training_logs(tmp_path, monkeypatch) -> None:
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    session_store.create_session(
        OsceSession(
            session_id="session_skill_candidate_one",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="report_ready",
        )
    )
    session_store.create_session(
        OsceSession(
            session_id="session_skill_candidate_two",
            student_id="student_b",
            case_id="pneumonia_001",
            stage="report_ready",
        )
    )
    session_store.create_session(
        OsceSession(
            session_id="session_skill_candidate_admin_eval",
            student_id="admin_eval_student_pass",
            case_id="appendicitis_001",
            stage="report_ready",
        )
    )
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    event_store.append_event(
        session_id="session_skill_candidate_one",
        case_id="appendicitis_001",
        student_id="student_a",
        event_type="report_generated",
        payload={
            "report_id": "report_one",
            "total_score": 55,
            "missed_items": ["reasoning_core"],
            "knowledge_recommendations": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                    "title": "补充临床推理证据链",
                }
            ],
        },
    )
    event_store.append_event(
        session_id="session_skill_candidate_two",
        case_id="pneumonia_001",
        student_id="student_b",
        event_type="report_generated",
        payload={
            "report_id": "report_two",
            "total_score": 68,
            "missed_items": ["reasoning_core"],
            "knowledge_recommendations": [
                {
                    "reference": "rubric:pneumonia_001_rubric.item.reasoning_core",
                    "title": "补充临床推理证据链",
                }
            ],
        },
    )
    event_store.append_event(
        session_id="session_skill_candidate_admin_eval",
        case_id="appendicitis_001",
        student_id="admin_eval_student_pass",
        event_type="report_generated",
        payload={
            "report_id": "report_admin_eval",
            "total_score": 32,
            "missed_items": ["reasoning_core"],
            "knowledge_recommendations": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                    "title": "系统评测专用推理漏项",
                }
            ],
        },
    )
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    evaluation_store = EvaluationResultStore(tmp_path / "evaluation_results.sqlite3")
    captured_case_ids: list[str] = []
    captured_service = None

    def fake_run_evaluation_cases(evaluation_cases, service, thresholds=None):
        nonlocal captured_service
        captured_case_ids.extend(evaluation_case.case_id for evaluation_case in evaluation_cases)
        captured_service = service
        return EvaluationBatchResult(
            total_cases=1,
            passed_cases=1,
            failed_cases=0,
            results=[],
            passed=True,
            total_duration_ms=20,
        )

    monkeypatch.setattr(osce_session_service, "session_store", session_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_event_store", event_store, raising=False)
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)
    monkeypatch.setattr(
        main,
        "training_skill_candidate_service",
        TrainingSkillCandidateService(generator=TemplateTrainingSkillCandidateGenerator()),
        raising=False,
    )
    monkeypatch.setattr(main, "evaluation_result_store", evaluation_store, raising=False)
    monkeypatch.setattr(main, "run_evaluation_cases", fake_run_evaluation_cases, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/admin/evolution/candidates/generate")
        candidates_response = client.get("/api/admin/evolution/candidates")
        candidate_response = client.get(
            "/api/admin/evolution/candidates/skill_candidate_training_pattern_reasoning_core"
        )
        audit_response = client.get("/api/admin/evolution/events")

    expected_candidate_summary = {
        "candidate_id": "skill_candidate_training_pattern_reasoning_core",
        "trigger_item_id": "training_pattern_reasoning_core",
        "title": "OSCE 训练模式纠偏提示",
        "status": "ready_for_review",
        "regression_passed": True,
        "source_report_count": 2,
        "support_count": 2,
    }
    assert response.status_code == 200
    response_payload = response.json()
    assert {key: response_payload[key] for key in [
        "generated_count",
        "saved_count",
        "ready_for_review_count",
        "blocked_by_regression_count",
        "auto_apply_enabled",
        "auto_approved_count",
        "approval_agent_modified_count",
    ]} == {
        "generated_count": 1,
        "saved_count": 1,
        "ready_for_review_count": 1,
        "blocked_by_regression_count": 0,
        "auto_apply_enabled": False,
        "auto_approved_count": 0,
        "approval_agent_modified_count": 1,
    }
    assert len(response_payload["candidates"]) == 1
    assert {key: response_payload["candidates"][0][key] for key in expected_candidate_summary} == expected_candidate_summary
    assert response_payload["candidates"][0]["case_titles"] == ["右下腹痛教学病例", "发热咳嗽伴胸痛教学病例"]
    assert candidates_response.status_code == 200
    candidates_payload = candidates_response.json()
    assert candidates_payload["pagination"] == {"limit": 1, "offset": 0, "total": 1}
    assert len(candidates_payload["candidates"]) == 1
    assert {key: candidates_payload["candidates"][0][key] for key in expected_candidate_summary} == expected_candidate_summary
    assert candidates_payload["candidates"][0]["case_titles"] == ["右下腹痛教学病例", "发热咳嗽伴胸痛教学病例"]
    assert candidate_response.status_code == 200
    approval_review = candidate_response.json()["candidate"]["approval_agent_review"]
    assert approval_review["decision"] == "ready_for_human_review"
    assert approval_review["quality_review"]["passed"] is True
    assert approval_review["role_policy"]["passed"] is True
    assert approval_review["regression_gate"] == {
        "status": "ready_for_review",
        "passed": True,
        "evaluation_total_cases": 1,
        "evaluation_passed_cases": 1,
        "evaluation_failed_cases": 0,
        "blocking_failures": [],
        "candidate_safety_violations": [],
        "candidate_context_violations": [],
        "approval_agent_violations": [],
    }
    assert evaluation_store.get_batch_result("admin_skill_candidate_generation_smoke")["passed"] is True
    assert audit_response.status_code == 200
    assert audit_response.json()["pagination"] == {"limit": 2, "offset": 0, "total": 2}
    assert len(audit_response.json()["events"]) == 2
    assert [event["event_type"] for event in audit_response.json()["events"]] == [
        "admin_skill_candidate_agent_reviewed",
        "admin_skill_candidate_generated",
    ]
    assert audit_response.json()["events"][1]["payload"] == {
        "candidate_id": "skill_candidate_training_pattern_reasoning_core",
        "review_status": "ready_for_review",
        "support_count": 2,
        "source_report_count": 2,
    }
    assert audit_response.json()["events"][0]["payload"]["decision"] == "ready_for_human_review"
    assert audit_response.json()["events"][0]["payload"]["regression_gate"]["passed"] is True
    assert captured_case_ids == ["appendicitis_001"]
    assert isinstance(captured_service, OsceSessionService)
    assert captured_service is not osce_session_service
    assert captured_service.report_store is osce_session_service.report_store
    assert captured_service.training_event_store is osce_session_service.training_event_store
    assert captured_service.training_skill_store is osce_session_service.training_skill_store
    assert captured_service.session_store is osce_session_service.session_store



def test_admin_auto_approval_agent_revises_and_enables_generated_skill(tmp_path, monkeypatch) -> None:
    class UnsafeSkillCandidateGenerator:
        def generate_candidate(self, context):
            candidate = TemplateTrainingSkillCandidateGenerator().generate_candidate(context)
            candidate["title"] = "推理链与用药剂量纠偏"
            candidate["description"] = "训练中反复漏掉 reasoning_core，需要提醒学生补充用药剂量。"
            candidate["suggested_strategy"] = "提交诊断前提示学生补充推理链，并给出用药剂量。"
            candidate["teaching_action_plan"] = expected_training_skill_action_plan(
                candidate["stage_scope"],
                candidate["trigger_item_ids"],
                candidate["suggested_strategy"],
            )
            return candidate

    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    for session_id, student_id in [
        ("session_auto_skill_one", "student_a"),
        ("session_auto_skill_two", "student_b"),
    ]:
        session_store.create_session(
            OsceSession(
                session_id=session_id,
                student_id=student_id,
                case_id="appendicitis_001",
                stage="report_ready",
            )
        )
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    for session_id, student_id in [
        ("session_auto_skill_one", "student_a"),
        ("session_auto_skill_two", "student_b"),
    ]:
        event_store.append_event(
            session_id=session_id,
            case_id="appendicitis_001",
            student_id=student_id,
            event_type="report_generated",
            payload={
                "report_id": f"report_{session_id}",
                "total_score": 58,
                "missed_items": ["reasoning_core"],
                "knowledge_recommendations": [
                    {
                        "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                        "title": "补充临床推理证据链",
                    }
                ],
            },
        )
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    evaluation_store = EvaluationResultStore(tmp_path / "evaluation_results.sqlite3")
    settings_store = TrainingSkillAutoApprovalSettingsStore(tmp_path / "training_skill_auto_approval.sqlite3")
    settings_store.update_settings(auto_apply_enabled=True, updated_by="admin@example.test")

    def fake_run_evaluation_cases(evaluation_cases, service, thresholds=None):
        return EvaluationBatchResult(
            total_cases=1,
            passed_cases=1,
            failed_cases=0,
            results=[],
            passed=True,
            total_duration_ms=20,
        )

    monkeypatch.setattr(osce_session_service, "session_store", session_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_event_store", event_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_skill_store", skill_store, raising=False)
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)
    monkeypatch.setattr(main, "training_skill_candidate_service", TrainingSkillCandidateService(generator=UnsafeSkillCandidateGenerator()), raising=False)
    monkeypatch.setattr(main, "training_skill_auto_approval_settings_store", settings_store, raising=False)
    monkeypatch.setattr(main, "evaluation_result_store", evaluation_store, raising=False)
    monkeypatch.setattr(main, "run_evaluation_cases", fake_run_evaluation_cases, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/admin/evolution/candidates/generate")
        candidate_response = client.get("/api/admin/evolution/candidates/skill_candidate_training_pattern_reasoning_core")

    assert response.status_code == 200
    payload = response.json()
    assert payload["auto_apply_enabled"] is True
    assert payload["auto_approved_count"] == 1
    assert payload["approval_agent_modified_count"] == 1
    assert payload["ready_for_review_count"] == 0
    assert payload["candidates"][0]["status"] == "approved"

    assert candidate_response.status_code == 200
    candidate = candidate_response.json()["candidate"]
    assert candidate["review"]["status"] == "approved"
    assert candidate["review"]["reviewer_id"] == "skill_auto_approval_agent"
    assert candidate["review"]["approval_mode"] == "auto_agent"
    assert "用药剂量" not in candidate["title"]
    assert "用药剂量" not in candidate["description"]
    assert "用药剂量" not in candidate["suggested_strategy"]
    assert candidate["approval_agent_review"]["agent_id"] == "skill_auto_approval_agent"
    assert candidate["approval_agent_review"]["revision_status"] == "modified"
    assert {
        changed_field["field"]
        for changed_field in candidate["approval_agent_review"]["changed_fields"]
    } >= {"title", "description", "suggested_strategy", "teaching_action_plan", "intervention", "router_index"}
    assert "intervention" in candidate["approval_agent_review"]["reviewed_fields"]
    assert "candidate_id" in candidate["approval_agent_review"]["protected_fields"]
    assert "用药剂量" not in candidate["router_index"]["summary"]
    assert "用药剂量" not in candidate["router_index"]["when_to_use"]
    assert "用药剂量" not in candidate["intervention"]["coach_strategy"]
    assert "用药剂量" not in " ".join(candidate["intervention"]["hint_ladder"])
    assert candidate["intervention"]["coach_strategy"] == candidate["suggested_strategy"]
    assert candidate["intervention"]["teaching_sop"]["version"] == "teaching_sop_v1"
    quality_review = candidate["approval_agent_review"]["quality_review"]
    assert quality_review["passed"] is True
    assert {
        check["check_id"]
        for check in quality_review["checks"]
    } >= {
        "protected_fields_preserved",
        "unsafe_terms_removed",
        "skill_body_complete",
        "teaching_sop_complete",
        "rag_visibility_filtered",
    }
    assert all(check["passed"] for check in quality_review["checks"])

    enabled_skill = skill_store.get_skill("skill_training_pattern_reasoning_core")
    assert enabled_skill is not None
    assert enabled_skill["status"] == "enabled"
    assert "用药剂量" not in enabled_skill["suggested_strategy"]
    assert "用药剂量" not in enabled_skill["intervention"]["coach_strategy"]

    audit_events = event_store.list_session_events("skill_candidate_training_pattern_reasoning_core")
    assert [event["event_type"] for event in audit_events] == [
        "admin_skill_candidate_generated",
        "admin_skill_candidate_agent_reviewed",
        "admin_skill_candidate_auto_approved",
    ]
    assert audit_events[1]["payload"]["revision_status"] == "modified"
    assert audit_events[2]["payload"]["skill_id"] == "skill_training_pattern_reasoning_core"


def test_admin_generate_training_skill_candidates_does_not_overwrite_reviewed_candidates(tmp_path, monkeypatch) -> None:
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    for session_id, student_id, case_id in [
        ("session_reviewed_one", "student_a", "appendicitis_001"),
        ("session_reviewed_two", "student_b", "pneumonia_001"),
    ]:
        session_store.create_session(
            OsceSession(
                session_id=session_id,
                student_id=student_id,
                case_id=case_id,
                stage="report_ready",
            )
        )
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    for session_id, student_id, case_id in [
        ("session_reviewed_one", "student_a", "appendicitis_001"),
        ("session_reviewed_two", "student_b", "pneumonia_001"),
    ]:
        event_store.append_event(
            session_id=session_id,
            case_id=case_id,
            student_id=student_id,
            event_type="report_generated",
            payload={
                "report_id": f"report_{session_id}",
                "total_score": 70,
                "missed_items": ["reasoning_core", "ht_location"],
                "knowledge_recommendations": [],
            },
        )
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    evaluation_store = EvaluationResultStore(tmp_path / "evaluation_results.sqlite3")
    reviewed_candidate_id = "skill_candidate_training_pattern_ht_location_reasoning_core"
    candidate_store.save_candidate(
        {
            "candidate_id": reviewed_candidate_id,
            "trigger_item_id": "training_pattern_ht_location_reasoning_core",
            "trigger_item_ids": ["ht_location", "reasoning_core"],
            "title": "已审核训练模式候选",
            "status": "draft",
            "source_report_count": 1,
            "support_count": 1,
            "approval_agent_review": {
                "agent_id": "skill_auto_approval_agent",
                "decision": "ready_for_human_review",
                "quality_review": {"passed": True, "failed_checks": []},
                "role_policy": {"passed": True},
            },
        },
        {
            "candidate_id": reviewed_candidate_id,
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 1,
            "evaluation_passed_cases": 1,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )
    assert candidate_store.approve_candidate(reviewed_candidate_id, reviewer_id="teacher_demo") is True

    def fake_run_evaluation_cases(evaluation_cases, service, thresholds=None):
        return EvaluationBatchResult(
            total_cases=1,
            passed_cases=1,
            failed_cases=0,
            results=[],
            passed=True,
            total_duration_ms=20,
        )

    monkeypatch.setattr(osce_session_service, "session_store", session_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_event_store", event_store, raising=False)
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)
    monkeypatch.setattr(main, "evaluation_result_store", evaluation_store, raising=False)
    monkeypatch.setattr(main, "run_evaluation_cases", fake_run_evaluation_cases, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/admin/evolution/candidates/generate")

    assert response.status_code == 200
    assert response.json()["generated_count"] == 1
    assert response.json()["saved_count"] == 0
    approved_candidate = candidate_store.get_candidate("skill_candidate_training_pattern_ht_location_reasoning_core")
    assert approved_candidate["title"] == "已审核训练模式候选"
    assert approved_candidate["source_report_count"] == 1
    assert approved_candidate["support_count"] == 1
    assert approved_candidate["review"]["status"] == "approved"



def test_admin_can_list_session_reports(tmp_path, monkeypatch) -> None:
    report_store = ReportStore(tmp_path / "reports.sqlite3")
    first_report = {
        "report_id": "report_session_first",
        "session_id": "session_first",
        "case_id": "appendicitis_001",
        "student_id": "student_first",
        "total_score": 78,
        "dimension_scores": {"history_taking": 16, "reasoning": 13},
        "missed_items": ["reasoning_core"],
        "knowledge_recommendations": [],
    }
    second_report = {
        "report_id": "report_session_second",
        "session_id": "session_second",
        "case_id": "appendicitis_002",
        "student_id": "student_second",
        "total_score": 91,
        "dimension_scores": {"history_taking": 20, "reasoning": 18},
        "missed_items": [],
        "knowledge_recommendations": [
            {"title": "保持鉴别诊断结构", "reference": "rubric:appendicitis_002_rubric.item.reasoning_core"}
        ],
    }
    report_store.save_report(first_report)
    report_store.save_report(second_report)
    monkeypatch.setattr(osce_session_service, "report_store", report_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/reports")
        detail_response = client.get("/api/admin/reports/report_session_second")
        csv_response = client.get("/api/admin/reports/export?format=csv&q=student_second")
        json_response = client.get("/api/admin/reports/export?format=json&q=student_second")

    assert response.status_code == 200
    assert response.json() == {
        "reports": [
            {
                **second_report,
                "case_title": "appendicitis_002",
                "missed_item_labels": [],
            },
            {
                **first_report,
                "case_title": "右下腹痛教学病例",
                "missed_item_labels": ["reasoning_core"],
            },
        ],
        "pagination": {"limit": 2, "offset": 0, "total": 2},
    }
    assert detail_response.status_code == 200
    assert detail_response.json()["report"]["report_id"] == "report_session_second"
    assert csv_response.status_code == 200
    assert "report_session_second" in csv_response.text
    assert "report_session_first" not in csv_response.text
    assert csv_response.headers["content-disposition"] == 'attachment; filename="admin-reports.csv"'
    assert json_response.status_code == 200
    assert [report["report_id"] for report in json_response.json()] == ["report_session_second"]



def test_admin_can_paginate_session_reports(tmp_path, monkeypatch) -> None:
    report_store = ReportStore(tmp_path / "reports.sqlite3")
    first_report = {
        "report_id": "report_session_first",
        "session_id": "session_first",
        "case_id": "appendicitis_001",
        "student_id": "student_first",
        "total_score": 78,
        "dimension_scores": {"history_taking": 16, "reasoning": 13},
        "missed_items": ["reasoning_core"],
        "knowledge_recommendations": [],
    }
    second_report = {
        "report_id": "report_session_second",
        "session_id": "session_second",
        "case_id": "appendicitis_002",
        "student_id": "student_second",
        "total_score": 91,
        "dimension_scores": {"history_taking": 20, "reasoning": 18},
        "missed_items": [],
        "knowledge_recommendations": [
            {"title": "保持鉴别诊断结构", "reference": "rubric:appendicitis_002_rubric.item.reasoning_core"}
        ],
    }
    report_store.save_report(first_report)
    report_store.save_report(second_report)
    monkeypatch.setattr(osce_session_service, "report_store", report_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/reports?limit=1&offset=1")

    assert response.status_code == 200
    assert response.json() == {
        "reports": [
            {
                **first_report,
                "case_title": "右下腹痛教学病例",
                "missed_item_labels": ["reasoning_core"],
            }
        ],
        "pagination": {"limit": 1, "offset": 1, "total": 2},
    }



def test_admin_can_filter_session_reports(tmp_path, monkeypatch) -> None:
    report_store = ReportStore(tmp_path / "reports.sqlite3")
    first_report = {
        "report_id": "report_session_first",
        "session_id": "session_first",
        "case_id": "appendicitis_001",
        "student_id": "student_first",
        "total_score": 78,
        "dimension_scores": {"history_taking": 16, "reasoning": 13},
        "missed_items": ["reasoning_core"],
        "knowledge_recommendations": [],
    }
    second_report = {
        "report_id": "report_session_second",
        "session_id": "session_second",
        "case_id": "appendicitis_002",
        "student_id": "student_second",
        "total_score": 91,
        "dimension_scores": {"history_taking": 20, "reasoning": 18},
        "missed_items": [],
        "knowledge_recommendations": [
            {"title": "保持鉴别诊断结构", "reference": "rubric:appendicitis_002_rubric.item.reasoning_core"}
        ],
    }
    report_store.save_report(first_report)
    report_store.save_report(second_report)
    monkeypatch.setattr(osce_session_service, "report_store", report_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/reports", params={"q": "保持鉴别诊断结构", "limit": 5})

    assert response.status_code == 200
    assert response.json() == {
        "reports": [
            {
                **second_report,
                "case_title": "appendicitis_002",
                "missed_item_labels": [],
            }
        ],
        "pagination": {"limit": 5, "offset": 0, "total": 1},
    }


def test_admin_can_list_procedure_simulation_audits(tmp_path, monkeypatch) -> None:
    report_store = ReportStore(tmp_path / "reports.sqlite3")
    report_store.save_report(
        {
            "report_id": "report_procedure_audit",
            "session_id": "session_procedure_audit",
            "case_id": "appendicitis_001",
            "student_id": "student_procedure_audit",
            "total_score": 74,
            "dimension_scores": {},
            "missed_items": [],
            "knowledge_recommendations": [],
            "procedure_simulation_audit_items": [
                {
                    "procedure_id": "test:ecg.st_segment",
                    "kind": "test",
                    "code": "ecg.st_segment",
                    "label": "心电图",
                    "result": "AI 模拟：窦性心律，未见明确急性 ST 段抬高或压低。（训练参考，不进入评分。）",
                    "approval_status": "approved_by_procedure_result_approval_agent",
                    "approval_agent_review": {
                        "agent_id": "procedure_result_approval_agent",
                        "decision": "approved",
                        "approval_mode": "approval_agent_error_fallback",
                        "rationale": "审批 Agent 调用失败，已使用本地安全门禁降级审核。",
                        "safety_issues": [],
                        "revised_result": "",
                    },
                    "source_context_references": [
                        "policy:advanced_procedure_simulation.not_for_scoring",
                    ],
                    "scoring_eligible": False,
                    "safety_boundary": "AI 模拟补充结果仅用于高级训练反馈，不写入病例标准事实，不进入标准评分。",
                }
            ],
        }
    )
    report_store.save_report(
        {
            "report_id": "report_without_procedure_audit",
            "session_id": "session_without_procedure_audit",
            "case_id": "acs_001",
            "student_id": "student_without_procedure_audit",
            "total_score": 91,
            "dimension_scores": {},
            "missed_items": [],
            "knowledge_recommendations": [],
            "procedure_simulation_audit_items": [],
        }
    )
    monkeypatch.setattr(osce_session_service, "report_store", report_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/procedure-simulation-audits", params={"limit": 10})

    assert response.status_code == 200
    assert response.json() == {
        "procedure_simulation_audits": [
            {
                "report_id": "report_procedure_audit",
                "session_id": "session_procedure_audit",
                "case_id": "appendicitis_001",
                "case_title": "右下腹痛教学病例",
                "student_id": "student_procedure_audit",
                "procedure_id": "test:ecg.st_segment",
                "kind": "test",
                "code": "ecg.st_segment",
                "label": "心电图",
                "result": "AI 模拟：窦性心律，未见明确急性 ST 段抬高或压低。（训练参考，不进入评分。）",
                "approval_status": "approved_by_procedure_result_approval_agent",
                "approval_decision": "approved",
                "approval_mode": "approval_agent_error_fallback",
                "approval_rationale": "审批 Agent 调用失败，已使用本地安全门禁降级审核。",
                "safety_issues": [],
                "source_context_references": [
                    "policy:advanced_procedure_simulation.not_for_scoring",
                ],
                "scoring_eligible": False,
                "safety_boundary": "AI 模拟补充结果仅用于高级训练反馈，不写入病例标准事实，不进入标准评分。",
            }
        ],
        "summary": {
            "total": 1,
            "by_approval_status": {"approved_by_procedure_result_approval_agent": 1},
            "by_case_title": {"右下腹痛教学病例": 1},
        },
        "pagination": {"limit": 10, "offset": 0, "total": 1},
    }


def test_admin_session_read_routes_hide_pending_deletion_residue(tmp_path, monkeypatch) -> None:
    deleted_session_id = "session_pending_deletion"
    visible_session_id = "session_still_visible"
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    report_store = ReportStore(tmp_path / "reports.sqlite3")
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")

    for session_id in [deleted_session_id, visible_session_id]:
        session_store.create_session(
            OsceSession(
                session_id=session_id,
                student_id=f"student_{session_id}",
                case_id="appendicitis_001",
                stage="report_ready",
            )
        )
        report_store.save_report(
            {
                "report_id": f"report_{session_id}",
                "session_id": session_id,
                "case_id": "appendicitis_001",
                "student_id": f"student_{session_id}",
                "total_score": 80,
                "dimension_scores": {},
                "missed_items": [],
                "knowledge_recommendations": [],
                "procedure_simulation_audit_items": [
                    {
                        "procedure_id": f"test:{session_id}",
                        "kind": "test",
                        "code": session_id,
                        "label": session_id,
                        "result": "训练模拟结果",
                        "approval_status": "approved",
                        "approval_agent_review": {"decision": "approved"},
                    }
                ],
            }
        )
        event_store.append_event(
            session_id=session_id,
            case_id="appendicitis_001",
            student_id=f"student_{session_id}",
            event_type="session_created",
            payload={"stage": "history"},
        )

    stale_session_summaries = session_store.list_session_summaries()
    pending_deletion = session_store.begin_session_deletion(
        deleted_session_id,
        f"student_{deleted_session_id}",
    )
    assert pending_deletion is not None
    assert pending_deletion.cleanup_status == "pending"
    assert session_store.is_session_deleted(deleted_session_id) is True
    monkeypatch.setattr(session_store, "list_session_summaries", lambda: stale_session_summaries)
    monkeypatch.setattr(osce_session_service, "session_store", session_store, raising=False)
    monkeypatch.setattr(osce_session_service, "report_store", report_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_event_store", event_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        sessions_response = client.get("/api/admin/sessions")
        reports_response = client.get("/api/admin/reports")
        audits_response = client.get("/api/admin/procedure-simulation-audits")
        deleted_report_response = client.get(f"/api/admin/sessions/{deleted_session_id}/report")
        deleted_events_response = client.get(f"/api/admin/sessions/{deleted_session_id}/events")
        visible_report_response = client.get(f"/api/admin/sessions/{visible_session_id}/report")
        visible_events_response = client.get(f"/api/admin/sessions/{visible_session_id}/events")

    assert sessions_response.status_code == 200
    assert [item["session_id"] for item in sessions_response.json()["sessions"]] == [visible_session_id]
    assert sessions_response.json()["pagination"]["total"] == 1
    assert reports_response.status_code == 200
    assert [item["session_id"] for item in reports_response.json()["reports"]] == [visible_session_id]
    assert reports_response.json()["pagination"]["total"] == 1
    assert audits_response.status_code == 200
    assert [
        item["session_id"]
        for item in audits_response.json()["procedure_simulation_audits"]
    ] == [visible_session_id]
    assert audits_response.json()["summary"]["total"] == 1
    assert audits_response.json()["pagination"]["total"] == 1
    assert deleted_report_response.status_code == 404
    assert deleted_report_response.json() == {"detail": "report not found"}
    assert deleted_events_response.status_code == 404
    assert deleted_events_response.json() == {"detail": "session not found"}
    assert visible_report_response.status_code == 200
    assert visible_events_response.status_code == 200



def test_admin_can_read_session_report(tmp_path, monkeypatch) -> None:
    report_store = ReportStore(tmp_path / "reports.sqlite3")
    report_store.save_report(
        {
            "report_id": "report_session_admin_report",
            "session_id": "session_admin_report",
            "case_id": "appendicitis_001",
            "student_id": "student_admin_report",
            "total_score": 82,
            "dimension_scores": {"history_taking": 18, "reasoning": 14},
            "missed_items": ["reasoning_core"],
            "ai_reflection_review": {
                "reasoning_trace_summary": {
                    "trace_version": "clinical_reasoning_trace_v1",
                    "sequence_flags": [
                        {
                            "flag_id": "auxiliary_before_exam",
                            "label": "辅助检查早于关键查体",
                            "severity": "medium",
                            "evidence": "学生先申请腹部超声，再补查体。",
                        }
                    ],
                    "evidence_chain_breakpoints": [
                        {
                            "breakpoint_id": "rp_exclude",
                            "statement": "排除性证据链不完整",
                            "kind": "missing_required_evidence",
                            "status": "missing",
                            "missing_evidence": ["appendicitis_001.rp_05"],
                            "missing_evidence_labels": ["输尿管结石排除证据"],
                            "teacher_action": "先让学生补足鉴别诊断需要的排除依据。",
                        }
                    ],
                }
            },
            "knowledge_recommendations": [
                {"title": "补充鉴别诊断证据链", "reference": "rubric:appendicitis_001_rubric.item.reasoning_core"}
            ],
        }
    )
    monkeypatch.setattr(osce_session_service, "report_store", report_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/sessions/session_admin_report/report")

    assert response.status_code == 200
    assert response.json() == {
        "report": {
            "report_id": "report_session_admin_report",
            "session_id": "session_admin_report",
            "case_id": "appendicitis_001",
            "case_title": "右下腹痛教学病例",
            "student_id": "student_admin_report",
            "total_score": 82,
            "dimension_scores": {"history_taking": 18, "reasoning": 14},
            "missed_items": ["reasoning_core"],
            "missed_item_labels": ["reasoning_core"],
            "ai_reflection_review": {
                "reasoning_trace_summary": {
                    "trace_version": "clinical_reasoning_trace_v1",
                    "sequence_flags": [
                        {
                            "flag_id": "auxiliary_before_exam",
                            "label": "辅助检查早于关键查体",
                            "severity": "medium",
                            "evidence": "学生先申请腹部超声，再补查体。",
                        }
                    ],
                    "evidence_chain_breakpoints": [
                        {
                            "breakpoint_id": "rp_exclude",
                            "statement": "排除性证据链不完整",
                            "kind": "missing_required_evidence",
                            "status": "missing",
                            "missing_evidence": ["appendicitis_001.rp_05"],
                            "missing_evidence_labels": ["输尿管结石排除证据"],
                            "teacher_action": "先让学生补足鉴别诊断需要的排除依据。",
                        }
                    ],
                }
            },
            "reasoning_trace_summary": {
                "trace_version": "clinical_reasoning_trace_v1",
                "sequence_flags": [
                    {
                        "flag_id": "auxiliary_before_exam",
                        "label": "辅助检查早于关键查体",
                        "severity": "medium",
                        "evidence": "学生先申请腹部超声，再补查体。",
                    }
                ],
                "evidence_chain_breakpoints": [
                    {
                        "breakpoint_id": "rp_exclude",
                        "statement": "排除性证据链不完整",
                        "kind": "missing_required_evidence",
                        "status": "missing",
                        "missing_evidence": ["appendicitis_001.rp_05"],
                        "missing_evidence_labels": ["输尿管结石排除证据"],
                        "teacher_action": "先让学生补足鉴别诊断需要的排除依据。",
                    }
                ],
            },
            "knowledge_recommendations": [
                {"title": "补充鉴别诊断证据链", "reference": "rubric:appendicitis_001_rubric.item.reasoning_core"}
            ],
        }
    }



def test_admin_session_report_returns_404_for_missing_report(tmp_path, monkeypatch) -> None:
    report_store = ReportStore(tmp_path / "reports.sqlite3")
    monkeypatch.setattr(osce_session_service, "report_store", report_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/sessions/missing_session/report")

    assert response.status_code == 404
    assert response.json() == {"detail": "report not found"}



def test_admin_can_read_training_skill_candidate_detail(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    candidate_store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "description": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "status": "draft",
            "source_report_count": 2,
            "support_count": 2,
            "related_recommendations": ["补充鉴别诊断证据链"],
        },
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/evolution/candidates/skill_candidate_reasoning_core")

    assert response.status_code == 200
    candidate = response.json()["candidate"]
    assert {
        "candidate_id": candidate["candidate_id"],
        "trigger_item_id": candidate["trigger_item_id"],
        "title": candidate["title"],
        "description": candidate["description"],
        "suggested_strategy": candidate["suggested_strategy"],
        "status": candidate["status"],
        "source_report_count": candidate["source_report_count"],
        "support_count": candidate["support_count"],
        "related_recommendations": candidate["related_recommendations"],
        "review": candidate["review"],
    } == {
        "candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "title": "临床推理链纠偏提示",
        "description": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
        "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
        "status": "draft",
        "source_report_count": 2,
        "support_count": 2,
        "related_recommendations": ["补充鉴别诊断证据链"],
        "review": {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    }
    assert "trigger_item_labels" in candidate
    assert "case_titles" in candidate
    assert "skill_type_label" in candidate
    assert "stage_scope_labels" in candidate
    assert "effect_status_label" in candidate


def test_admin_candidate_detail_returns_404_for_missing_candidate(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/evolution/candidates/missing_candidate")

    assert response.status_code == 404
    assert response.json() == {"detail": "candidate not found"}


def test_admin_can_list_training_skill_review_audit_events(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    candidate_store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "status": "draft",
            "source_report_count": 2,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "approved",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )
    candidate_store.save_candidate(
        {
            "candidate_id": "skill_candidate_history_gap",
            "trigger_item_id": "history_gap",
            "title": "问诊漏项提醒",
            "status": "draft",
            "source_report_count": 1,
            "support_count": 1,
        },
        {
            "candidate_id": "skill_candidate_history_gap",
            "status": "rejected",
            "regression_passed": False,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 1,
            "evaluation_failed_cases": 1,
            "blocking_failures": [],
        },
    )
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    event_store.append_event(
        session_id="skill_candidate_reasoning_core",
        case_id="reasoning_core",
        student_id="admin@example.test",
        event_type="admin_skill_candidate_approved",
        payload={
            "candidate_id": "skill_candidate_reasoning_core",
            "reviewer_email": "admin@example.test",
            "skill_id": "skill_reasoning_core",
        },
    )
    event_store.append_event(
        session_id="skill_candidate_history_gap",
        case_id="history_gap",
        student_id="admin@example.test",
        event_type="admin_skill_candidate_rejected",
        payload={
            "candidate_id": "skill_candidate_history_gap",
            "reviewer_email": "admin@example.test",
        },
    )
    event_store.append_event(
        session_id="student_session",
        case_id="appendicitis_001",
        student_id="student@example.test",
        event_type="history_message",
        payload={"message": "疼痛多久了？"},
    )
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_event_store", event_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/evolution/events")

    assert response.status_code == 200
    events = response.json()["events"]
    assert len(events) == 2
    assert {event["session_id"] for event in events} == {
        "skill_candidate_reasoning_core",
        "skill_candidate_history_gap",
    }
    assert {event["event_type"] for event in events} == {
        "admin_skill_candidate_approved",
        "admin_skill_candidate_rejected",
    }
    assert all(event["student_id"] == "admin@example.test" for event in events)
    assert all(event["payload"]["reviewer_email"] == "admin@example.test" for event in events)
    assert response.json()["pagination"] == {"limit": 2, "offset": 0, "total": 2}


def test_admin_can_paginate_and_filter_training_skill_review_audit_events(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    for candidate_id, trigger_item_id, title in [
        ("skill_candidate_reasoning_core", "reasoning_core", "临床推理链纠偏提示"),
        ("skill_candidate_history_gap", "history_gap", "问诊漏项提醒"),
    ]:
        candidate_store.save_candidate(
            {
                "candidate_id": candidate_id,
                "trigger_item_id": trigger_item_id,
                "title": title,
                "status": "draft",
                "source_report_count": 2,
                "support_count": 2,
            },
            {
                "candidate_id": candidate_id,
                "status": "ready_for_review",
                "regression_passed": True,
                "evaluation_total_cases": 2,
                "evaluation_passed_cases": 2,
                "evaluation_failed_cases": 0,
                "blocking_failures": [],
            },
        )
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    event_store.append_event(
        session_id="skill_candidate_reasoning_core",
        case_id="reasoning_core",
        student_id="admin@example.test",
        event_type="admin_skill_candidate_approved",
        payload={"candidate_id": "skill_candidate_reasoning_core", "reviewer_email": "admin@example.test"},
    )
    event_store.append_event(
        session_id="skill_candidate_history_gap",
        case_id="history_gap",
        student_id="admin@example.test",
        event_type="admin_skill_candidate_rejected",
        payload={"candidate_id": "skill_candidate_history_gap", "reviewer_email": "admin@example.test"},
    )
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_event_store", event_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        paged_response = client.get("/api/admin/evolution/events?limit=1&offset=1")
        filtered_response = client.get("/api/admin/evolution/events", params={"q": "reasoning_core", "limit": 5})

    assert paged_response.status_code == 200
    paged_payload = paged_response.json()
    assert len(paged_payload["events"]) == 1
    assert paged_payload["pagination"] == {"limit": 1, "offset": 1, "total": 2}

    assert filtered_response.status_code == 200
    filtered_payload = filtered_response.json()
    assert [event["session_id"] for event in filtered_payload["events"]] == ["skill_candidate_reasoning_core"]
    assert filtered_payload["pagination"] == {"limit": 5, "offset": 0, "total": 1}


def test_admin_can_list_training_skill_candidate_audit_events(tmp_path, monkeypatch) -> None:
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    event_store.append_event(
        session_id="skill_candidate_reasoning_core",
        case_id="reasoning_core",
        student_id="admin@example.test",
        event_type="admin_skill_candidate_approved",
        payload={
            "candidate_id": "skill_candidate_reasoning_core",
            "reviewer_email": "admin@example.test",
            "skill_id": "skill_reasoning_core",
        },
    )
    event_store.append_event(
        session_id="skill_candidate_reasoning_core",
        case_id="reasoning_core",
        student_id="admin@example.test",
        event_type="admin_skill_candidate_rejected",
        payload={
            "candidate_id": "skill_candidate_reasoning_core",
            "reviewer_email": "admin@example.test",
        },
    )
    monkeypatch.setattr(osce_session_service, "training_event_store", event_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.get("/api/admin/evolution/candidates/skill_candidate_reasoning_core/events")

    assert response.status_code == 200
    events = response.json()["events"]
    assert len(events) == 2
    assert [event["session_id"] for event in events] == ["skill_candidate_reasoning_core"] * 2
    assert [event["case_id"] for event in events] == ["reasoning_core"] * 2
    assert [event["student_id"] for event in events] == ["admin@example.test"] * 2
    assert [event["event_type"] for event in events] == [
        "admin_skill_candidate_approved",
        "admin_skill_candidate_rejected",
    ]
    assert events[0]["payload"] == {
        "candidate_id": "skill_candidate_reasoning_core",
        "reviewer_email": "admin@example.test",
        "skill_id": "skill_reasoning_core",
    }
    assert events[1]["payload"] == {
        "candidate_id": "skill_candidate_reasoning_core",
        "reviewer_email": "admin@example.test",
    }
    assert all(event["created_at"] for event in events)


def test_admin_can_approve_candidate_and_enable_training_skill(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    candidate_store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "description": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "status": "draft",
            "source_report_count": 2,
            "support_count": 2,
            "related_recommendations": [],
            "approval_agent_review": {
                "agent_id": "skill_auto_approval_agent",
                "decision": "ready_for_human_review",
                "quality_review": {"passed": True, "failed_checks": []},
                "role_policy": {"passed": True},
            },
        },
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_skill_store", skill_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_event_store", event_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/admin/evolution/approve",
            json={"candidate_id": "skill_candidate_reasoning_core", "reviewer_id": "spoofed@example.test"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "candidate_id": "skill_candidate_reasoning_core",
        "status": "approved",
        "skill_id": "skill_reasoning_core",
    }
    assert candidate_store.get_candidate("skill_candidate_reasoning_core")["review"]["reviewer_id"] == "admin@osce.test"
    enabled_skill = skill_store.get_skill("skill_reasoning_core")
    assert without_skill_memory_fields(enabled_skill) == {
        "skill_id": "skill_reasoning_core",
        "source_candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "trigger_item_ids": ["reasoning_core"],
        "case_ids": [],
        "skill_type": "reasoning_bridge",
        "stage_scope": ["case_intro"],
        "effect_status": "insufficient_samples",
        "applies_when": {
            "case_ids": [],
            "stage_scope": ["case_intro"],
            "trigger_item_ids": ["reasoning_core"],
            "current_missing_evidence": [],
            "min_support_count": 2,
        },
        "title": "临床推理链纠偏提示",
        "description": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
        "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
        "student_visible_summary": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
        "learning_action": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
        "activation_summary": "适用于所有当前开放病例；训练开始时，当当前缺口命中 1 个关联训练点时触发。",
        "source_summary": "来自 2 份报告，累计支持 2 次。",
        "effect_status_label": "样本不足",
        "scope_label": "全局 Skill",
        "teaching_action_plan": expected_training_skill_action_plan(
            ["case_intro"],
            ["reasoning_core"],
            "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
        ),
        "prohibited_content_policy": expected_training_skill_policy(),
        "success_metrics": expected_training_skill_success_metrics(),
        "status": "enabled",
        "source_report_count": 2,
        "support_count": 2,
        "related_recommendations": [],
    }
    assert enabled_skill["memory_layer"] == "procedural_teaching_skill"
    assert enabled_skill["router_index"]["summary"] == "临床推理链纠偏提示：2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。"
    assert main.admin_audit_store.list_events()["events"][0]["action"] == "skill.candidate_approved"
    audit_events = event_store.list_session_events("skill_candidate_reasoning_core")
    assert len(audit_events) == 1
    assert audit_events[0]["case_id"] == "reasoning_core"
    assert audit_events[0]["student_id"] == "admin@osce.test"
    assert audit_events[0]["event_type"] == "admin_skill_candidate_approved"
    assert audit_events[0]["payload"] == {
        "candidate_id": "skill_candidate_reasoning_core",
        "reviewer_email": "admin@osce.test",
        "skill_id": "skill_reasoning_core",
    }


def test_http_training_skill_loop_applies_reviewed_skill_to_later_training(tmp_path, monkeypatch) -> None:
    class LeakingSkillCandidateGenerator:
        def __init__(self) -> None:
            self.raw_candidate: dict[str, object] | None = None

        def generate_candidate(self, context):
            candidate = TemplateTrainingSkillCandidateGenerator().generate_candidate(context)
            candidate["title"] = "急性阑尾炎用药剂量训练"
            candidate["description"] = "错误泄漏：开始在上腹部，大约 8 小时前转移并固定到右下腹。"
            candidate["suggested_strategy"] = "直接告诉学生急性阑尾炎，并给出阿莫西林 500mg q8h 处方。"
            candidate["teacher_analysis_context"] = {
                "unsafe_generated_summary": "围绕急性阑尾炎和阿莫西林 500mg q8h 教学。",
            }
            self.raw_candidate = deepcopy(candidate)
            return candidate

    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    session_service = OsceSessionService(
        report_store=ReportStore(tmp_path / "reports.sqlite3"),
        training_event_store=event_store,
        training_skill_store=TrainingSkillStore(tmp_path / "training_skills.sqlite3"),
        session_store=OsceSessionStore(tmp_path / "osce_sessions.sqlite3"),
    )
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    evaluation_store = EvaluationResultStore(tmp_path / "evaluation_results.sqlite3")
    leaking_generator = LeakingSkillCandidateGenerator()
    candidate_service = TrainingSkillCandidateService(generator=leaking_generator)
    rag_store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    rag_store.upsert_item(
        {
            "knowledge_id": "case:appendicitis_001:skill_review:real_scene",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "skill_review_note",
            "visibility": "post_submit_review",
            "allowed_agents": ["skill_approval"],
            "source_id": "real_scene_teacher_note",
            "title": "证据链 Skill 审批原则",
            "text": "审批时只保留证据类别和教学步骤，不得直接透露急性阑尾炎。",
            "tags": ["skill_review", "reasoning"],
            "version": 1,
        },
        updated_by="real-scene-teacher@example.test",
    )
    rag_store.upsert_item(
        {
            "knowledge_id": "case:appendicitis_001:secret:real_scene",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "internal_answer",
            "visibility": "secret_scoring_only",
            "allowed_agents": ["scoring"],
            "source_id": "",
            "title": "真实场景隐藏答案",
            "text": "急性阑尾炎；开始在上腹部，大约 8 小时前转移并固定到右下腹。",
            "tags": ["internal"],
            "version": 1,
        },
        updated_by="real-scene-teacher@example.test",
    )

    monkeypatch.setattr(main, "auth_store", auth_store, raising=False)
    monkeypatch.setattr(main, "osce_session_service", session_service, raising=False)
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)
    monkeypatch.setattr(main, "training_skill_candidate_service", candidate_service, raising=False)
    monkeypatch.setattr(main, "evaluation_result_store", evaluation_store, raising=False)
    monkeypatch.setattr(auto_approval_module, "rag_knowledge_store", rag_store, raising=False)
    monkeypatch.setattr(
        agent_rag_context_module,
        "search_retrieval_documents",
        lambda query, limit, *, allowed_references=None: [
            RetrievalDocument(
                reference="rag_knowledge:case:appendicitis_001:skill_review:real_scene",
                source_type="rag_knowledge",
                title="real scene approval hit",
                snippet="real scene approval hit",
                score=0.99,
            )
        ],
        raising=False,
    )

    with TestClient(main.app) as client:
        student_login = client.post("/api/auth/login", json={"email": "student@osce.test", "password": "student"})
        assert student_login.status_code == 200

        for _ in range(2):
            session_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
            assert session_response.status_code == 200
            session_id = session_response.json()["session_id"]
            submit_response = client.post(
                f"/api/sessions/{session_id}/submit-diagnosis",
                json={"diagnosis": "暂不确定", "reasoning": "证据不足，先提交一次低质量训练。"},
            )
            assert submit_response.status_code == 200
            report_response = client.post(f"/api/sessions/{session_id}/report/generate")
            assert report_response.status_code == 200
            report = report_response.json()
            assert report["source_reference_items"]
            assert report["explanation_source_items"]

        admin_login = client.post("/api/auth/login", json={"email": "admin@osce.test", "password": "admin"})
        assert admin_login.status_code == 200

        insights_response = client.get("/api/admin/insights")
        assert insights_response.status_code == 200
        assert insights_response.json()["insights"]["report_count"] == 2

        generate_response = client.post("/api/admin/evolution/candidates/generate")
        assert generate_response.status_code == 200
        generated_payload = generate_response.json()
        assert generated_payload["generated_count"] == 1
        assert generated_payload["ready_for_review_count"] == 1
        candidate_id = generated_payload["candidates"][0]["candidate_id"]

        candidate_detail_response = client.get(f"/api/admin/evolution/candidates/{candidate_id}")
        assert candidate_detail_response.status_code == 200
        candidate = candidate_detail_response.json()["candidate"]
        assert candidate["candidate_id"].startswith("skill_candidate_training_pattern_")
        assert len(candidate["trigger_item_ids"]) > 1
        assert candidate["source_report_count"] == 2
        assert candidate["support_count"] == 2
        assert candidate["review"]["status"] == "ready_for_review"
        assert candidate["review"]["regression_passed"] is True
        assert leaking_generator.raw_candidate is not None
        for protected_field in auto_approval_module.PROTECTED_CANDIDATE_FIELDS:
            if protected_field in leaking_generator.raw_candidate:
                assert candidate[protected_field] == leaking_generator.raw_candidate[protected_field]
        candidate_text = str(candidate)
        for leaked_text in [
            "急性阑尾炎",
            "输尿管结石",
            "克罗恩病",
            "急性胃肠炎",
            "开始在上腹部，大约 8 小时前转移并固定到右下腹。",
            "阿莫西林",
            "500mg",
            "q8h",
        ]:
            assert leaked_text not in candidate_text
        approval_review = candidate["approval_agent_review"]
        assert approval_review["decision"] == "ready_for_human_review"
        assert approval_review["quality_review"]["passed"] is True
        assert approval_review["role_policy"]["passed"] is True
        assert approval_review["knowledge_references"] == [
            "rag_knowledge:case:appendicitis_001:skill_review:real_scene"
        ]
        assert approval_review["retrieved_knowledge_context"][0]["visibility"] == "post_submit_review"
        assert approval_review["regression_gate"]["passed"] is True
        assert approval_review["regression_gate"]["evaluation_total_cases"] == 1
        assert {
            change["field"] for change in approval_review["changed_fields"]
        } >= {"title", "description", "suggested_strategy", "teacher_analysis_context", "intervention"}

        approve_response = client.post("/api/admin/evolution/approve", json={"candidate_id": candidate_id})
        assert approve_response.status_code == 200
        skill_id = approve_response.json()["skill_id"]

        student_login = client.post(
            "/api/auth/login",
            json={"email": "student@osce.test", "password": "student"},
        )
        assert student_login.status_code == 200
        later_session_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
        assert later_session_response.status_code == 200
        later_session = later_session_response.json()
        later_session_id = later_session["session_id"]
        assert "evolution_candidates" not in later_session
        later_internal_session = session_service._get_session(later_session_id)
        assert later_internal_session is not None
        assert later_internal_session.evolution_candidates == []
        assert later_internal_session.active_skill_context["selected_skills"][0]["activation_ready"] is False

        opening_hint_response = client.post(f"/api/sessions/{later_session_id}/hint")
        assert opening_hint_response.status_code == 200
        assert "本轮训练重点" not in opening_hint_response.json()["hint"]
        assert "selected_skill_ids" not in opening_hint_response.json()["agent_turn_memory"][-1]
        assert later_internal_session.agent_turn_memory[-1]["selected_skill_ids"] == []

        message_response = client.post(f"/api/sessions/{later_session_id}/message", json={"message": "什么时候开始疼的？"})
        assert message_response.status_code == 200
        first_progress_hint_response = client.post(f"/api/sessions/{later_session_id}/hint")
        assert first_progress_hint_response.status_code == 200
        assert "本轮训练重点" not in first_progress_hint_response.json()["hint"]

        second_message_response = client.post(
            f"/api/sessions/{later_session_id}/message",
            json={"message": "疼痛是什么性质，有多严重？"},
        )
        assert second_message_response.status_code == 200
        hint_response = client.post(f"/api/sessions/{later_session_id}/hint")
        assert hint_response.status_code == 200
        assert hint_response.json()["hint"]
        assert "selected_skill_ids" not in hint_response.json()["agent_turn_memory"][-1]
        assert later_internal_session.agent_turn_memory[-1]["selected_skill_ids"]
        profile_response = client.get("/api/me/profile")
        assert profile_response.status_code == 200
        skill_accumulation = profile_response.json()["profile"]["skill_accumulation"]
        assert skill_accumulation["enabled_skill_count"] >= 1
        assert skill_accumulation["applied_skill_count"] >= 1
        assert any(
            skill["skill_id"] == skill_id and skill["effect_status"] == "insufficient_samples"
            for skill in skill_accumulation["enabled_skills"]
        )

        admin_login = client.post(
            "/api/auth/login",
            json={"email": "admin@osce.test", "password": "admin"},
        )
        assert admin_login.status_code == 200
        later_events_response = client.get(f"/api/admin/sessions/{later_session_id}/events")
        assert later_events_response.status_code == 200
        later_events = later_events_response.json()["events"]
        later_business_events = [
            event for event in later_events if event["event_type"] not in {"agent_decision_traced", "agent_reflection_recorded"}
        ]
        assert later_business_events[0]["event_type"] == "session_created"
        assert any(
            event["event_type"] == "training_skill_applied" and event["payload"]["skill_id"] == skill_id
            for event in later_business_events
        )
        assert any(event["event_type"] == "agent_decision_traced" for event in later_events)

        candidate_events_response = client.get(f"/api/admin/evolution/candidates/{candidate_id}/events")
        assert candidate_events_response.status_code == 200
        assert [event["event_type"] for event in candidate_events_response.json()["events"]] == [
            "admin_skill_candidate_generated",
            "admin_skill_candidate_agent_reviewed",
            "admin_skill_candidate_approved",
        ]
        enabled_skill = session_service.training_skill_store.get_skill(skill_id)
        assert enabled_skill is not None
        assert all(
            leaked_text not in str(enabled_skill)
            for leaked_text in [
                "急性阑尾炎",
                "输尿管结石",
                "克罗恩病",
                "急性胃肠炎",
                "阿莫西林",
                "500mg",
                "q8h",
            ]
        )


def test_admin_can_reject_candidate_without_enabling_training_skill(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    candidate_store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "description": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "status": "draft",
            "source_report_count": 2,
            "support_count": 2,
            "related_recommendations": [],
        },
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_skill_store", skill_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_event_store", event_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/admin/evolution/reject",
            json={"candidate_id": "skill_candidate_reasoning_core", "reviewer_id": "spoofed@example.test"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "candidate_id": "skill_candidate_reasoning_core",
        "status": "rejected",
    }
    assert candidate_store.get_candidate("skill_candidate_reasoning_core")["review"]["reviewer_id"] == "admin@osce.test"
    assert skill_store.list_enabled_skills() == []
    audit_events = event_store.list_session_events("skill_candidate_reasoning_core")
    assert len(audit_events) == 1
    assert audit_events[0]["case_id"] == "reasoning_core"
    assert audit_events[0]["student_id"] == "admin@osce.test"
    assert audit_events[0]["event_type"] == "admin_skill_candidate_rejected"
    assert audit_events[0]["payload"] == {
        "candidate_id": "skill_candidate_reasoning_core",
        "reviewer_email": "admin@osce.test",
    }
    assert main.admin_audit_store.list_events()["events"][0]["action"] == "skill.candidate_rejected"


def test_admin_review_returns_404_for_missing_candidate(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_skill_store", skill_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/admin/evolution/approve",
            json={"candidate_id": "missing_candidate", "reviewer_id": "admin@osce.test"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "candidate not found or not ready for review"}
