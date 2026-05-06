from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path

from fastapi.testclient import TestClient
import yaml

from app import main
from app.services import gemini_patient_responder as gemini_patient_responder_module
from app.services.auth_store import AuthStore
from app.services.evaluation_result_store import EvaluationResultStore
from app.services.evaluation_runner import EvaluationBatchResult, EvaluationResult
from app.services.osce_session_service import OsceSession, OsceSessionService, osce_session_service
from app.services.osce_session_store import OsceSessionStore
from app.services.report_store import ReportStore
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_candidate_service import TemplateTrainingSkillCandidateGenerator, TrainingSkillCandidateService
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_store import TrainingSkillStore
from app.services.runtime_model_config_store import runtime_model_config_store


@contextmanager
def authenticated_admin_client(
    tmp_path,
    monkeypatch,
    *,
    raise_server_exceptions: bool = True,
) -> Iterator[TestClient]:
    monkeypatch.setenv("CLINICAL_OSCE_ADMIN_EMAILS", "admin@example.test")
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"), raising=False)
    with TestClient(main.app, raise_server_exceptions=raise_server_exceptions) as client:
        response = client.post(
            "/api/auth/register",
            json={"email": "admin@example.test", "password": "safe-admin-password", "display_name": "管理员"},
        )
        assert response.status_code == 200
        yield client


def load_case_and_rubric_payload(case_id: str = "appendicitis_001") -> tuple[dict[str, object], dict[str, object]]:
    repo_root = Path(__file__).resolve().parents[3]
    case_payload = json.loads((repo_root / "data" / "cases" / f"{case_id}.json").read_text(encoding="utf-8"))
    rubric_payload = yaml.safe_load((repo_root / "data" / "rubrics" / f"{case_id}_rubric.yaml").read_text(encoding="utf-8"))
    return case_payload, rubric_payload


def configure_case_import_directories(tmp_path, monkeypatch) -> tuple[Path, Path]:
    cases_dir = tmp_path / "cases"
    rubrics_dir = tmp_path / "rubrics"
    cases_dir.mkdir()
    rubrics_dir.mkdir()
    monkeypatch.setattr(main, "CASES_DIR", cases_dir, raising=False)
    monkeypatch.setattr(main, "RUBRICS_DIR", rubrics_dir, raising=False)
    return cases_dir, rubrics_dir


def test_admin_endpoints_require_login(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"), raising=False)

    with TestClient(main.app) as unauthenticated_client:
        responses = [
            unauthenticated_client.get("/api/admin/evolution/candidates"),
            unauthenticated_client.get("/api/admin/evolution/candidates/missing_candidate"),
            unauthenticated_client.get("/api/admin/evolution/candidates/missing_candidate/events"),
            unauthenticated_client.get("/api/admin/evolution/events"),
            unauthenticated_client.get("/api/admin/evolution/skill-effects"),
            unauthenticated_client.post("/api/admin/evolution/candidates/generate"),
            unauthenticated_client.post("/api/admin/evolution/approve", json={"candidate_id": "missing_candidate"}),
            unauthenticated_client.post("/api/admin/evolution/reject", json={"candidate_id": "missing_candidate"}),
            unauthenticated_client.get("/api/admin/insights"),
            unauthenticated_client.get("/api/admin/evaluations"),
            unauthenticated_client.get("/api/admin/evaluations/missing_batch"),
            unauthenticated_client.post("/api/admin/evals/run", json={"batch_id": "batch_manual"}),
            unauthenticated_client.get("/api/cases/appendicitis_001/raw"),
            unauthenticated_client.get("/api/admin/cases/appendicitis_001/raw"),
            unauthenticated_client.patch("/api/admin/cases/appendicitis_001/raw", json={"case_title": "演示病例"}),
            unauthenticated_client.post("/api/admin/cases/validate", json={"case": {}, "rubric": {}}),
            unauthenticated_client.post("/api/admin/cases/import", json={"case": {}, "rubric": {}}),
            unauthenticated_client.get("/api/admin/rubrics/appendicitis_001_rubric"),
            unauthenticated_client.patch("/api/admin/rubrics/appendicitis_001_rubric/items/ht_onset", json={"description": "追问起病时间"}),
            unauthenticated_client.get("/api/admin/sources"),
            unauthenticated_client.get("/api/admin/model-config"),
            unauthenticated_client.get("/api/admin/retrieval-eval"),
            unauthenticated_client.get("/api/admin/reports"),
            unauthenticated_client.get("/api/admin/sessions"),
            unauthenticated_client.get("/api/admin/sessions/missing_session/report"),
            unauthenticated_client.get("/api/admin/sessions/missing_session/events"),
            unauthenticated_client.get("/api/admin/teaching-focus/patterns"),
            unauthenticated_client.get("/api/admin/teaching-focus/patterns/case_baseline:appendicitis_001:history_taking"),
        ]

    assert [response.status_code for response in responses] == [401] * len(responses)
    assert all(response.json() == {"detail": "not authenticated"} for response in responses)


def test_admin_endpoints_reject_authenticated_non_admin_user(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_ADMIN_EMAILS", "admin@example.test")
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"), raising=False)

    with TestClient(main.app) as client:
        register_response = client.post(
            "/api/auth/register",
            json={"email": "student@example.test", "password": "safe-student-password", "display_name": "学生"},
        )
        assert register_response.status_code == 200

        responses = [
            client.get("/api/admin/evolution/candidates"),
            client.get("/api/admin/evolution/candidates/missing_candidate"),
            client.get("/api/admin/evolution/candidates/missing_candidate/events"),
            client.get("/api/admin/evolution/events"),
            client.get("/api/admin/evolution/skill-effects"),
            client.post("/api/admin/evolution/candidates/generate"),
            client.post("/api/admin/evolution/approve", json={"candidate_id": "missing_candidate"}),
            client.post("/api/admin/evolution/reject", json={"candidate_id": "missing_candidate"}),
            client.get("/api/admin/insights"),
            client.get("/api/admin/evaluations"),
            client.get("/api/admin/evaluations/missing_batch"),
            client.post("/api/admin/evals/run", json={"batch_id": "batch_manual"}),
            client.get("/api/cases/appendicitis_001/raw"),
            client.get("/api/admin/cases/appendicitis_001/raw"),
            client.patch("/api/admin/cases/appendicitis_001/raw", json={"case_title": "演示病例"}),
            client.post("/api/admin/cases/validate", json={"case": {}, "rubric": {}}),
            client.post("/api/admin/cases/import", json={"case": {}, "rubric": {}}),
            client.get("/api/admin/rubrics/appendicitis_001_rubric"),
            client.patch("/api/admin/rubrics/appendicitis_001_rubric/items/ht_onset", json={"description": "追问起病时间"}),
            client.get("/api/admin/sources"),
            client.get("/api/admin/model-config"),
            client.get("/api/admin/retrieval-eval"),
            client.get("/api/admin/reports"),
            client.get("/api/admin/sessions"),
            client.get("/api/admin/sessions/missing_session/report"),
            client.get("/api/admin/sessions/missing_session/events"),
            client.get("/api/admin/teaching-focus/patterns"),
            client.get("/api/admin/teaching-focus/patterns/case_baseline:appendicitis_001:history_taking"),
        ]

    assert [response.status_code for response in responses] == [403] * len(responses)
    assert all(response.json() == {"detail": "admin access required"} for response in responses)


def test_admin_review_request_schema_only_exposes_candidate_id() -> None:
    main.app.openapi_schema = None

    schema = main.app.openapi()["components"]["schemas"]["AdminTrainingSkillReviewRequest"]

    assert schema["required"] == ["candidate_id"]
    assert list(schema["properties"]) == ["candidate_id"]


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
    assert "ChromaDB 是本地可选持久向量检索" in payload["boundary"]["chroma_scope"]


def test_demo_admin_can_login_with_hardcoded_credentials_without_env(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CLINICAL_OSCE_ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("CLINICAL_OSCE_DEMO_ADMIN_ENABLED", raising=False)
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"), raising=False)

    with TestClient(main.app) as client:
        login_response = client.post(
            "/api/auth/login",
            json={"email": "admin-demo@example.test", "password": "safe-admin-password"},
        )
        assert login_response.status_code == 200
        assert login_response.json()["user"]["email"] == "admin-demo@example.test"
        admin_response = client.get("/api/admin/model-config")

    assert admin_response.status_code == 200


def test_demo_admin_hardcoded_credentials_can_be_disabled(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CLINICAL_OSCE_ADMIN_EMAILS", raising=False)
    monkeypatch.setenv("CLINICAL_OSCE_DEMO_ADMIN_ENABLED", "false")
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"), raising=False)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/auth/login",
            json={"email": "admin-demo@example.test", "password": "safe-admin-password"},
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
    payload = response.json()
    assert payload["policy"] == {
        "secrets_persisted": False,
        "runtime_write_supported": True,
        "configuration_source": "environment_or_runtime_memory",
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
    assert providers["openai_compatible"]["base_url"] == "https://api.openai.example/v1"
    assert providers["openai_compatible"]["integration_status"] == "wired"


def test_admin_model_config_reports_runtime_vertex_gemini_adc(tmp_path, monkeypatch) -> None:
    runtime_model_config_store.clear()
    runtime_model_config_store.apply_config(
        {
            "provider": "vertex_gemini_adc",
            "api_key": "",
            "model": "gemini-3.1-pro-preview",
            "base_url": "demo-project",
            "proxy_url": "http://127.0.0.1:7897",
        }
    )

    try:
        with authenticated_admin_client(tmp_path, monkeypatch) as client:
            response = client.get("/api/admin/model-config")
    finally:
        runtime_model_config_store.clear()

    assert response.status_code == 200
    providers = {provider["provider_id"]: provider for provider in response.json()["providers"]}
    assert providers["gemini_patient_vertex"]["configured"] is True
    assert providers["gemini_patient_vertex"]["project"] == "demo-project"
    assert providers["gemini_patient_vertex"]["model"] == "gemini-3.1-pro-preview"
    assert providers["vertex_rubric_scorer"]["configured"] is True
    assert providers["vertex_rubric_scorer"]["project"] == "demo-project"
    assert providers["vertex_skill_candidate"]["configured"] is True
    assert providers["vertex_skill_candidate"]["project"] == "demo-project"
    assert providers["vertex_embedding_retrieval"]["configured"] is False
    assert providers["vertex_embedding_retrieval"]["model"] == "gemini-embedding-001"
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
    assert response.json() == {
        "candidates": [
            {
                "candidate_id": "skill_candidate_reasoning_core",
                "trigger_item_id": "reasoning_core",
                "title": "临床推理链纠偏提示",
                "status": "ready_for_review",
                "regression_passed": True,
                "source_report_count": 3,
                "support_count": 2,
            }
        ],
        "pagination": {"limit": 1, "offset": 0, "total": 1},
    }


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


def test_admin_can_list_training_session_summaries(tmp_path, monkeypatch) -> None:
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    session_store.save_session(
        OsceSession(
            session_id="session_admin_old",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="history",
        )
    )
    session_store.save_session(
        OsceSession(
            session_id="session_admin_recent",
            student_id="student_b",
            case_id="hyperthyroid_001",
            stage="diagnosis_submitted",
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
    assert payload["sessions"][0]["stage"] == "diagnosis_submitted"
    assert isinstance(payload["sessions"][0]["created_at"], str)
    assert isinstance(payload["sessions"][0]["updated_at"], str)
    assert payload["pagination"] == {"limit": 2, "offset": 0, "total": 2}



def test_admin_can_paginate_training_session_summaries(tmp_path, monkeypatch) -> None:
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    session_store.save_session(
        OsceSession(
            session_id="session_admin_old",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="history",
        )
    )
    session_store.save_session(
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
    session_store.save_session(
        OsceSession(
            session_id="session_admin_old",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="history",
        )
    )
    session_store.save_session(
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
    session_store.save_session(
        OsceSession(
            session_id="session_insight_one",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="report_ready",
        )
    )
    session_store.save_session(
        OsceSession(
            session_id="session_insight_two",
            student_id="student_b",
            case_id="pneumonia_001",
            stage="report_ready",
        )
    )
    session_store.save_session(
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
            "session_count": 2,
            "report_count": 2,
            "frequent_missed_items": [
                {"item_id": "reasoning_core", "count": 2, "case_ids": ["appendicitis_001", "pneumonia_001"]},
                {"item_id": "ht_location", "count": 1, "case_ids": ["appendicitis_001"]},
            ],
            "frequent_learning_recommendations": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                    "title": "补充临床推理证据链",
                    "count": 1,
                },
                {
                    "reference": "rubric:pneumonia_001_rubric.item.reasoning_core",
                    "title": "补充临床推理证据链",
                    "count": 1,
                },
            ],
            "frequent_source_references": [
                {
                    "reference": "source:fareez_osce_2022",
                    "source_type": "source",
                    "title": "Fareez OSCE 数据集",
                    "count": 2,
                    "case_ids": ["appendicitis_001", "pneumonia_001"],
                    "metadata": {"license": "CC BY 4.0"},
                }
            ],
        }
    }


def test_admin_can_read_training_skill_effect_summary_with_insufficient_samples(tmp_path, monkeypatch) -> None:
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    session_store.save_session(
        OsceSession(
            session_id="session_effect_with_skill",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="report_ready",
        )
    )
    session_store.save_session(
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
    assert rubric["dimensions"][0]["weight"] == 25
    assert rubric["dimensions"][0]["scoring_mode"] == "rule"
    assert rubric["dimensions"][0]["items"][0] == {
        "item_id": "ht_onset",
        "description": "追问起病时间",
        "max_score": 3,
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
    assert len(payload["sources"]) == 5
    assert payload["sources"][0] == {
        "source_id": "fareez_osce_2022",
        "source_name": "A dataset of simulated patient-physician medical interviews with a focus on respiratory cases",
        "source_url": "https://doi.org/10.6084/m9.figshare.c.5545842.v1",
        "license": "CC BY 4.0",
        "data_type": "dialogue",
        "allowed_usage": ["training_reference", "evaluation_reference", "demo_reference"],
        "transformation": "download original zip, then extract and convert into structured OSCE case assets",
        "attribution_required": True,
        "risk_note": "原始数据偏呼吸系统问诊，不足以直接覆盖完整病例闭环。",
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
            {"batch_id": "batch_smoke", "total_cases": 2, "passed_cases": 2, "failed_cases": 0, "passed": True},
            {"batch_id": "batch_regression", "total_cases": 3, "passed_cases": 2, "failed_cases": 1, "passed": False},
        ],
        "pagination": {"limit": 2, "offset": 0, "total": 2},
    }


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

    def fake_run_evaluation_cases(evaluation_cases, service):
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
                "duration_ms": 42,
            }
        ],
        "passed": True,
        "total_duration_ms": 42,
    }
    assert response.status_code == 200
    assert response.json() == {"evaluation": expected_evaluation}
    assert evaluation_store.get_batch_result("batch_admin_manual") == expected_evaluation
    assert captured_case_ids == ["appendicitis_001"]
    assert isinstance(captured_service, OsceSessionService)
    assert captured_service is not osce_session_service
    assert captured_service.report_store is osce_session_service.report_store
    assert captured_service.training_event_store is osce_session_service.training_event_store
    assert captured_service.training_skill_store is osce_session_service.training_skill_store
    assert captured_service.session_store is osce_session_service.session_store



def test_admin_can_generate_training_skill_candidates_from_training_logs(tmp_path, monkeypatch) -> None:
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    session_store.save_session(
        OsceSession(
            session_id="session_skill_candidate_one",
            student_id="student_a",
            case_id="appendicitis_001",
            stage="report_ready",
        )
    )
    session_store.save_session(
        OsceSession(
            session_id="session_skill_candidate_two",
            student_id="student_b",
            case_id="pneumonia_001",
            stage="report_ready",
        )
    )
    session_store.save_session(
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

    def fake_run_evaluation_cases(evaluation_cases, service):
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
    monkeypatch.setattr(main, "evaluation_result_store", evaluation_store, raising=False)
    monkeypatch.setattr(main, "run_evaluation_cases", fake_run_evaluation_cases, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post("/api/admin/evolution/candidates/generate")
        candidates_response = client.get("/api/admin/evolution/candidates")
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
    assert response.json() == {
        "generated_count": 1,
        "saved_count": 1,
        "ready_for_review_count": 1,
        "blocked_by_regression_count": 0,
        "candidates": [expected_candidate_summary],
    }
    assert candidates_response.status_code == 200
    assert candidates_response.json() == {
        "candidates": [expected_candidate_summary],
        "pagination": {"limit": 1, "offset": 0, "total": 1},
    }
    assert evaluation_store.get_batch_result("admin_skill_candidate_generation_smoke")["passed"] is True
    assert audit_response.status_code == 200
    assert audit_response.json()["pagination"] == {"limit": 1, "offset": 0, "total": 1}
    assert len(audit_response.json()["events"]) == 1
    assert audit_response.json()["events"][0]["event_type"] == "admin_skill_candidate_generated"
    assert audit_response.json()["events"][0]["payload"] == {
        "candidate_id": "skill_candidate_training_pattern_reasoning_core",
        "review_status": "ready_for_review",
        "support_count": 2,
        "source_report_count": 2,
    }
    assert captured_case_ids == ["appendicitis_001"]
    assert isinstance(captured_service, OsceSessionService)
    assert captured_service is not osce_session_service
    assert captured_service.report_store is osce_session_service.report_store
    assert captured_service.training_event_store is osce_session_service.training_event_store
    assert captured_service.training_skill_store is osce_session_service.training_skill_store
    assert captured_service.session_store is osce_session_service.session_store



def test_admin_generate_training_skill_candidates_does_not_overwrite_reviewed_candidates(tmp_path, monkeypatch) -> None:
    session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    for session_id, student_id, case_id in [
        ("session_reviewed_one", "student_a", "appendicitis_001"),
        ("session_reviewed_two", "student_b", "pneumonia_001"),
    ]:
        session_store.save_session(
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

    def fake_run_evaluation_cases(evaluation_cases, service):
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

    assert response.status_code == 200
    assert response.json() == {
        "reports": [second_report, first_report],
        "pagination": {"limit": 2, "offset": 0, "total": 2},
    }



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
        "reports": [first_report],
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
        "reports": [second_report],
        "pagination": {"limit": 5, "offset": 0, "total": 1},
    }



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
            "student_id": "student_admin_report",
            "total_score": 82,
            "dimension_scores": {"history_taking": 18, "reasoning": 14},
            "missed_items": ["reasoning_core"],
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
    assert response.json() == {
        "candidate": {
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
    }


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
    assert candidate_store.get_candidate("skill_candidate_reasoning_core")["review"]["reviewer_id"] == "admin@example.test"
    assert skill_store.get_skill("skill_reasoning_core") == {
        "skill_id": "skill_reasoning_core",
        "source_candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "trigger_item_ids": [],
        "case_ids": [],
        "skill_type": "reasoning_bridge",
        "stage_scope": ["case_intro"],
        "effect_status": "insufficient_samples",
        "applies_when": {
            "case_ids": [],
            "stage_scope": ["case_intro"],
            "trigger_item_ids": [],
            "current_missing_evidence": [],
            "min_support_count": 2,
        },
        "title": "临床推理链纠偏提示",
        "description": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
        "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
        "status": "enabled",
        "source_report_count": 2,
        "support_count": 2,
        "related_recommendations": [],
    }
    audit_events = event_store.list_session_events("skill_candidate_reasoning_core")
    assert len(audit_events) == 1
    assert audit_events[0]["case_id"] == "reasoning_core"
    assert audit_events[0]["student_id"] == "admin@example.test"
    assert audit_events[0]["event_type"] == "admin_skill_candidate_approved"
    assert audit_events[0]["payload"] == {
        "candidate_id": "skill_candidate_reasoning_core",
        "reviewer_email": "admin@example.test",
        "skill_id": "skill_reasoning_core",
    }


def test_http_training_skill_loop_applies_reviewed_skill_to_later_training(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CLINICAL_OSCE_ADMIN_EMAILS", "admin@example.test")
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
    candidate_service = TrainingSkillCandidateService(generator=TemplateTrainingSkillCandidateGenerator())

    monkeypatch.setattr(main, "auth_store", auth_store, raising=False)
    monkeypatch.setattr(main, "osce_session_service", session_service, raising=False)
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)
    monkeypatch.setattr(main, "training_skill_candidate_service", candidate_service, raising=False)
    monkeypatch.setattr(main, "evaluation_result_store", evaluation_store, raising=False)

    with TestClient(main.app) as client:
        student_register = client.post(
            "/api/auth/register",
            json={"email": "student-loop@example.test", "password": "safe-student-password", "display_name": "学生"},
        )
        assert student_register.status_code == 200

        for _ in range(2):
            session_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
            assert session_response.status_code == 200
            session_id = session_response.json()["session_id"]
            submit_response = client.post(
                f"/api/sessions/{session_id}/submit-diagnosis",
                json={"diagnosis": "暂不确定", "reasoning": "证据不足，先提交一次低质量训练。"},
            )
            assert submit_response.status_code == 200
            report_response = client.get(f"/api/sessions/{session_id}/report")
            assert report_response.status_code == 200
            report = report_response.json()
            assert report["source_reference_items"]
            assert report["explanation_source_items"]

        admin_register = client.post(
            "/api/auth/register",
            json={"email": "admin@example.test", "password": "safe-admin-password", "display_name": "管理员"},
        )
        assert admin_register.status_code == 200

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

        approve_response = client.post("/api/admin/evolution/approve", json={"candidate_id": candidate_id})
        assert approve_response.status_code == 200
        skill_id = approve_response.json()["skill_id"]

        student_login = client.post(
            "/api/auth/login",
            json={"email": "student-loop@example.test", "password": "safe-student-password"},
        )
        assert student_login.status_code == 200
        later_session_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
        assert later_session_response.status_code == 200
        later_session = later_session_response.json()
        later_session_id = later_session["session_id"]
        assert later_session["evolution_candidates"] == [
            f"{candidate['title']}：{candidate['suggested_strategy']}"
        ]

        hint_response = client.post(f"/api/sessions/{later_session_id}/hint")
        assert hint_response.status_code == 200
        assert "本轮训练重点" in hint_response.json()["hint"]
        profile_response = client.get("/api/me/profile")
        assert profile_response.status_code == 200
        assert profile_response.json()["profile"]["skill_accumulation"]["enabled_skill_count"] == 1
        assert profile_response.json()["profile"]["skill_accumulation"]["applied_skill_count"] == 1
        assert profile_response.json()["profile"]["skill_accumulation"]["enabled_skills"][0]["effect_status"] == "insufficient_samples"

        admin_login = client.post(
            "/api/auth/login",
            json={"email": "admin@example.test", "password": "safe-admin-password"},
        )
        assert admin_login.status_code == 200
        later_events_response = client.get(f"/api/admin/sessions/{later_session_id}/events")
        assert later_events_response.status_code == 200
        later_events = later_events_response.json()["events"]
        later_business_events = [
            event for event in later_events if event["event_type"] not in {"agent_decision_traced", "agent_reflection_recorded"}
        ]
        assert [event["event_type"] for event in later_business_events][:2] == [
            "session_created",
            "training_skill_applied",
        ]
        assert later_business_events[1]["payload"]["skill_id"] == skill_id
        assert any(event["event_type"] == "agent_decision_traced" for event in later_events)


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
    assert candidate_store.get_candidate("skill_candidate_reasoning_core")["review"]["reviewer_id"] == "admin@example.test"
    assert skill_store.list_enabled_skills() == []
    audit_events = event_store.list_session_events("skill_candidate_reasoning_core")
    assert len(audit_events) == 1
    assert audit_events[0]["case_id"] == "reasoning_core"
    assert audit_events[0]["student_id"] == "admin@example.test"
    assert audit_events[0]["event_type"] == "admin_skill_candidate_rejected"
    assert audit_events[0]["payload"] == {
        "candidate_id": "skill_candidate_reasoning_core",
        "reviewer_email": "admin@example.test",
    }


def test_admin_review_returns_404_for_missing_candidate(tmp_path, monkeypatch) -> None:
    candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    monkeypatch.setattr(main, "training_skill_candidate_store", candidate_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_skill_store", skill_store, raising=False)

    with authenticated_admin_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/admin/evolution/approve",
            json={"candidate_id": "missing_candidate", "reviewer_id": "admin@example.test"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "candidate not found or not ready for review"}
