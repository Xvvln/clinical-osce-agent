import json
import sqlite3
from copy import deepcopy
from dataclasses import asdict

import pytest
import httpx
from fastapi.testclient import TestClient

from app import main
from app.graph.osce_graph import build_osce_graph
from app.main import AUTH_COOKIE_NAME, app
from app.services.auth_store import AuthStore
from app.services.osce_session_service import (
    SessionClosedError,
    SessionDeletionConflictError,
    _ensure_personal_skill_report_defaults,
    load_case_node,
    osce_session_service,
)
from app.services.osce_session_store import (
    OsceSessionStore,
    SessionDeletedError,
    SessionNotFoundError,
    SessionWriteConflictError,
)
from app.services.report_store import ReportStore
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services.student_profile_store import StudentProfileStore
from app.services.training_event_store import TrainingEventStore
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.training_skill_store import TrainingSkillStore


client = TestClient(app)
AGENT_EVENT_TYPES = {"agent_decision_traced", "agent_reflection_recorded"}


def canonical_patient_responder(request: object) -> str:
    return str(getattr(request, "canonical_answer"))


def failing_openai_patient_responder(request: object) -> str:
    http_request = httpx.Request("POST", "https://fallback-gateway.example/v1/chat/completions")
    http_response = httpx.Response(
        status_code=401,
        request=http_request,
        json={
            "error": {
                "message": "Invalid API Key",
                "code": "invalid_key",
            }
        },
    )
    raise httpx.HTTPStatusError("401 Invalid API Key", request=http_request, response=http_response)


def failing_google_turn_intent_agent(request: object) -> object:
    from google.genai import errors as google_genai_errors

    raise google_genai_errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "message": "Resource has been exhausted (e.g. check quota).",
                "status": "RESOURCE_EXHAUSTED",
            }
        },
    )


def failing_google_adc_turn_intent_agent(request: object) -> object:
    from google.auth import exceptions as google_auth_exceptions

    raise google_auth_exceptions.DefaultCredentialsError("Your default credentials were not found.")


def assert_training_progress_hides_diagnosis(progress: dict[str, object]) -> None:
    progress_text = str(progress)
    assert "急性阑尾炎" not in progress_text
    assert "阑尾炎" not in progress_text
    assert "Acute appendicitis" not in progress_text
    assert "appendicitis" not in progress_text


def assert_student_payload_hides_unrevealed_case_evidence(
    payload: dict[str, object],
    *,
    revealed_fact_ids: set[str] | None = None,
    requested_exam_codes: set[str] | None = None,
    requested_test_codes: set[str] | None = None,
) -> None:
    case = load_case_node(str(payload["case_id"]))
    payload_text = json.dumps(payload, ensure_ascii=False)
    revealed_fact_ids = revealed_fact_ids or set()
    requested_exam_codes = requested_exam_codes or set()
    requested_test_codes = requested_test_codes or set()

    for fact in case.history.hidden_facts:
        if fact.fact_id not in revealed_fact_ids:
            assert fact.canonical_answer not in payload_text
    for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]:
        if exam.exam_code not in requested_exam_codes:
            assert exam.result not in payload_text
    for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]:
        if test.test_code not in requested_test_codes:
            assert test.result not in payload_text

    forbidden_keys = {
        "active_skill_context",
        "agent_decision_trace",
        "action_timeline",
        "coverage_map",
        "diagnostic_role",
        "dynamic_teaching_focus",
        "evolution_candidates",
        "inquiry_guidance",
        "is_abnormal",
        "linked_rubric_items",
        "missing_rubric_items",
        "missed_items",
        "must_pending_codes",
        "must_requested",
        "must_total",
        "patient_affect_state",
        "pending_codes",
        "pending_evidence",
        "pending_fact_ids",
        "pending_signal_ids",
        "reflection_summary",
        "retrieved_knowledge_context",
        "retrieved_sources",
        "rubric_scores",
        "rules_out",
        "safe_pending_points",
        "selected_skill_ids",
        "selected_skill_reasons",
        "skill_context",
        "source_references",
        "teaching_focus",
    }
    assert not (forbidden_keys & _recursive_dict_keys(payload))


def _recursive_dict_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {
            *[str(key) for key in value],
            *(
                nested_key
                for nested_value in value.values()
                for nested_key in _recursive_dict_keys(nested_value)
            ),
        }
    if isinstance(value, list):
        return {
            nested_key
            for nested_value in value
            for nested_key in _recursive_dict_keys(nested_value)
        }
    return set()


def business_events(events: list[dict[str, object]]) -> list[dict[str, object]]:
    return [event for event in events if event["event_type"] not in AGENT_EVENT_TYPES]


def find_event(events: list[dict[str, object]], event_type: str) -> dict[str, object]:
    return next(event for event in events if event["event_type"] == event_type)


@pytest.fixture(autouse=True)
def use_canonical_patient_responder() -> None:
    osce_session_service.osce_graph = build_osce_graph(patient_responder=canonical_patient_responder)


@pytest.fixture(autouse=True)
def authenticated_user(tmp_path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(main, "auth_store", auth_store)
    user = auth_store.create_user("student@example.test", "safe-password-123", "学生甲")
    assert user is not None
    token = auth_store.create_session(user["user_id"])
    client.cookies.clear()
    client.cookies.set(AUTH_COOKIE_NAME, token)
    yield user
    client.cookies.clear()


@pytest.fixture
def isolated_procedure_api_storage(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        osce_session_service,
        "session_store",
        OsceSessionStore(tmp_path / "procedure_api_sessions.sqlite3"),
    )
    monkeypatch.setattr(
        osce_session_service,
        "training_event_store",
        TrainingEventStore(tmp_path / "procedure_api_events.sqlite3"),
    )
    osce_session_service._sessions.clear()
    yield
    osce_session_service._sessions.clear()


def test_create_session_requires_logged_in_user() -> None:
    with TestClient(app) as anonymous_client:
        create_response = anonymous_client.post("/api/sessions", json={"case_id": "appendicitis_001"})

    assert create_response.status_code == 401
    assert create_response.json() == {"detail": "not authenticated"}


def test_legacy_report_defaults_include_deep_report_analysis() -> None:
    report = _ensure_personal_skill_report_defaults({"report_id": "legacy_report"})

    assert report["deep_report_analysis"]["status"] == "legacy_report"
    assert report["deep_report_analysis"]["diagnostic_contrast_analysis"]["classification"] == "unsupported"


def test_procedure_catalog_does_not_expose_case_specific_configuration() -> None:
    catalog_response = client.get("/api/procedure-catalog")

    assert catalog_response.status_code == 200
    catalog = catalog_response.json()
    for item in [*catalog["physical_exams"], *catalog["auxiliary_tests"]]:
        assert "known_case_ids" not in item
        assert "case_id" not in item
        assert "result" not in item
        assert "is_abnormal" not in item


@pytest.mark.parametrize(
    ("endpoint_suffix", "request_payload", "expected_detail"),
    [
        pytest.param(
            "/physical-exam",
            {"exam_code": "unknown.exam"},
            "unknown physical exam code",
            id="physical-exam-single",
        ),
        pytest.param(
            "/physical-exams",
            {
                "exam_codes": [
                    "abd.palpation.rebound",
                    "unknown.exam",
                ]
            },
            "unknown physical exam code",
            id="physical-exam-batch",
        ),
        pytest.param(
            "/auxiliary-test",
            {"test_code": "unknown.test"},
            "unknown auxiliary test code",
            id="auxiliary-test-single",
        ),
        pytest.param(
            "/auxiliary-tests",
            {
                "test_codes": [
                    "lab.cbc",
                    "unknown.test",
                ]
            },
            "unknown auxiliary test code",
            id="auxiliary-test-batch",
        ),
    ],
)
def test_unknown_procedure_api_requests_return_fixed_422_without_side_effects(
    isolated_procedure_api_storage: None,
    endpoint_suffix: str,
    request_payload: dict[str, object],
    expected_detail: str,
) -> None:
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001"},
    )
    assert create_response.status_code == 200
    session_id = str(create_response.json()["session_id"])
    held_session = osce_session_service._get_session(session_id)
    stored_before = osce_session_service.session_store.get_session(session_id)
    assert held_session is not None
    assert stored_before is not None
    live_session_before = asdict(held_session)
    persisted_session_before = deepcopy(stored_before.payload)
    events_before = deepcopy(
        osce_session_service.training_event_store.list_session_events(session_id)
    )

    response = client.post(
        f"/api/sessions/{session_id}{endpoint_suffix}",
        json=request_payload,
    )

    stored_after = osce_session_service.session_store.get_session(session_id)
    assert response.status_code == 422
    assert response.json() == {"detail": expected_detail}
    assert asdict(held_session) == live_session_before
    assert stored_after is not None
    assert stored_after.revision == stored_before.revision
    assert stored_after.payload == persisted_session_before
    assert (
        osce_session_service.training_event_store.list_session_events(session_id)
        == events_before
    )


@pytest.mark.parametrize(
    (
        "endpoint_suffix",
        "request_payload",
        "requested_field",
        "existing_code",
        "expected_detail",
    ),
    [
        pytest.param(
            "/physical-exam",
            {"exam_code": "vital.blood_pressure"},
            "requested_exams",
            "abd.palpation.rebound",
            "本次训练申请的查体项目已达到上限。",
            id="physical-exam",
        ),
        pytest.param(
            "/auxiliary-test",
            {"test_code": "ecg.st_segment"},
            "requested_tests",
            "lab.cbc",
            "本次训练申请的辅助检查项目已达到上限。",
            id="auxiliary-test",
        ),
    ],
)
def test_procedure_api_limit_returns_fixed_409_without_side_effects(
    isolated_procedure_api_storage: None,
    endpoint_suffix: str,
    request_payload: dict[str, object],
    requested_field: str,
    existing_code: str,
    expected_detail: str,
) -> None:
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001"},
    )
    assert create_response.status_code == 200
    session_id = str(create_response.json()["session_id"])
    held_session = osce_session_service._get_session(session_id)
    assert held_session is not None
    setattr(
        held_session,
        requested_field,
        [
            existing_code,
            *[
                f"legacy.procedure.{index}"
                for index in range(63)
            ],
        ],
    )
    osce_session_service._save_session(held_session)
    stored_before = osce_session_service.session_store.get_session(session_id)
    assert stored_before is not None
    live_session_before = asdict(held_session)
    persisted_session_before = deepcopy(stored_before.payload)
    events_before = deepcopy(
        osce_session_service.training_event_store.list_session_events(session_id)
    )

    response = client.post(
        f"/api/sessions/{session_id}{endpoint_suffix}",
        json=request_payload,
    )

    stored_after = osce_session_service.session_store.get_session(session_id)
    assert response.status_code == 409
    assert response.json() == {"detail": expected_detail}
    assert asdict(held_session) == live_session_before
    assert stored_after is not None
    assert stored_after.revision == stored_before.revision
    assert stored_after.payload == persisted_session_before
    assert (
        osce_session_service.training_event_store.list_session_events(session_id)
        == events_before
    )


def test_create_session_requires_runtime_model_config_when_training_gate_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_model_config_store.clear()
    monkeypatch.setenv("OSCE_REQUIRE_RUNTIME_MODEL_CONFIG_FOR_TRAINING", "1")

    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})

    assert create_response.status_code == 409
    assert create_response.json() == {"detail": "请先在 API 配置中应用可用模型，再开始训练。"}


def test_create_session_uses_persisted_user_runtime_model_config_after_runtime_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OSCE_REQUIRE_RUNTIME_MODEL_CONFIG_FOR_TRAINING", "1")
    save_response = client.post(
        "/api/model-config/runtime",
        json={
            "provider": "openai_compatible",
            "api_key": "student-openai-secret",
            "model": "teaching-model",
            "base_url": "https://api.proxy.example/v1",
            "proxy_url": "direct",
        },
    )
    runtime_model_config_store.clear()

    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})

    assert save_response.status_code == 200
    assert create_response.status_code == 200
    assert create_response.json()["case_id"] == "appendicitis_001"


def test_message_provider_auth_error_returns_readable_gateway_error() -> None:
    osce_session_service.osce_graph = build_osce_graph(patient_responder=failing_openai_patient_responder)
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]

    with TestClient(app, raise_server_exceptions=False) as error_client:
        error_client.cookies.set(AUTH_COOKIE_NAME, client.cookies.get(AUTH_COOKIE_NAME))
        response = error_client.post(
            f"/api/sessions/{session_id}/message",
            json={"message": "什么时候开始疼的？"},
        )

    assert create_response.status_code == 200
    assert response.status_code == 502
    assert response.json()["detail"] == "模型服务调用失败：HTTP 401：Invalid API Key；invalid_key"


def test_session_write_conflict_returns_refreshable_http_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]

    def raise_conflict(_: str, __: str) -> None:
        raise SessionWriteConflictError(
            session_id,
            expected_revision=1,
            current_revision=2,
        )

    monkeypatch.setattr(osce_session_service, "handle_message", raise_conflict)
    response = client.post(
        f"/api/sessions/{session_id}/message",
        json={"message": "什么时候开始疼的？"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "训练会话已被其他请求更新，请刷新后重试。",
    }


@pytest.mark.parametrize(
    "persistence_error",
    [SessionDeletedError, SessionNotFoundError],
)
def test_deleted_or_missing_session_during_write_returns_http_404(
    monkeypatch: pytest.MonkeyPatch,
    persistence_error: type[SessionDeletedError] | type[SessionNotFoundError],
) -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]

    def raise_missing(_: str, __: str) -> None:
        raise persistence_error(session_id)

    monkeypatch.setattr(osce_session_service, "record_hypothesis", raise_missing)
    response = client.post(
        f"/api/sessions/{session_id}/hypotheses",
        json={"hypothesis": "急性阑尾炎"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "session not found"}


def test_message_google_provider_quota_error_returns_readable_gateway_error() -> None:
    osce_session_service.osce_graph = build_osce_graph(
        patient_responder=canonical_patient_responder,
        turn_intent_agent=failing_google_turn_intent_agent,
    )
    create_response = client.post("/api/sessions", json={"case_id": "hyperthyroid_001"})
    session_id = create_response.json()["session_id"]

    with TestClient(app, raise_server_exceptions=False) as error_client:
        error_client.cookies.set(AUTH_COOKIE_NAME, client.cookies.get(AUTH_COOKIE_NAME))
        response = error_client.post(
            f"/api/sessions/{session_id}/message",
            json={"message": "心慌什么时候开始？有没有手抖、怕热、多汗、体重下降？"},
        )

    assert create_response.status_code == 200
    assert response.status_code == 502
    assert response.json()["detail"] == (
        "模型服务调用失败：HTTP 429：Resource has been exhausted (e.g. check quota).；RESOURCE_EXHAUSTED"
    )


def test_message_google_adc_missing_error_returns_readable_gateway_error() -> None:
    osce_session_service.osce_graph = build_osce_graph(
        patient_responder=canonical_patient_responder,
        turn_intent_agent=failing_google_adc_turn_intent_agent,
    )
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]

    with TestClient(app, raise_server_exceptions=False) as error_client:
        error_client.cookies.set(AUTH_COOKIE_NAME, client.cookies.get(AUTH_COOKIE_NAME))
        response = error_client.post(
            f"/api/sessions/{session_id}/message",
            json={"message": "什么时候开始疼的？"},
        )

    assert create_response.status_code == 200
    assert response.status_code == 502
    assert "Google ADC" in response.json()["detail"]


def test_report_google_provider_quota_error_returns_readable_gateway_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from google.genai import errors as google_genai_errors

    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "已提交诊断，准备生成报告。"},
    )

    def failing_report(_: str, **__: object) -> dict[str, object]:
        raise google_genai_errors.ClientError(
            429,
            {
                "error": {
                    "code": 429,
                    "message": "Resource has been exhausted (e.g. check quota).",
                    "status": "RESOURCE_EXHAUSTED",
                }
            },
        )

    monkeypatch.setattr(main.osce_session_service, "generate_report", failing_report)

    with TestClient(app, raise_server_exceptions=False) as error_client:
        error_client.cookies.set(AUTH_COOKIE_NAME, client.cookies.get(AUTH_COOKIE_NAME))
        response = error_client.post(f"/api/sessions/{session_id}/report/generate")

    assert create_response.status_code == 200
    assert response.status_code == 502
    assert response.json()["detail"] == (
        "模型服务调用失败：HTTP 429：Resource has been exhausted (e.g. check quota).；RESOURCE_EXHAUSTED"
    )


def test_current_user_report_google_adc_missing_error_returns_readable_gateway_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from google.auth import exceptions as google_auth_exceptions

    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "已提交诊断，准备生成报告。"},
    )

    def failing_report(_: str, **__: object) -> dict[str, object]:
        raise google_auth_exceptions.DefaultCredentialsError("Your default credentials were not found.")

    monkeypatch.setattr(main.osce_session_service, "generate_report", failing_report)

    with TestClient(app, raise_server_exceptions=False) as error_client:
        error_client.cookies.set(AUTH_COOKIE_NAME, client.cookies.get(AUTH_COOKIE_NAME))
        response = error_client.post(f"/api/sessions/{session_id}/report/generate")

    assert create_response.status_code == 200
    assert response.status_code == 502
    assert "Google ADC" in response.json()["detail"]


def test_create_session_uses_authenticated_user_id(authenticated_user: dict[str, str]) -> None:
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "spoofed_student"},
    )

    assert create_response.status_code == 200
    assert create_response.json()["student_id"] == authenticated_user["user_id"]


def test_create_session_persists_training_difficulty(tmp_path, authenticated_user: dict[str, str]) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service._sessions.clear()

    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "training_difficulty": "advanced"},
    )

    assert create_response.status_code == 200
    payload = create_response.json()
    assert payload["training_difficulty"] == "advanced"

    osce_session_service._sessions.clear()
    reloaded_payload = client.get(f"/api/sessions/{payload['session_id']}").json()
    session_summaries = client.get("/api/me/sessions").json()["sessions"]

    assert reloaded_payload["training_difficulty"] == "advanced"
    assert session_summaries[0]["training_difficulty"] == "advanced"


def test_create_session_returns_patient_opening_utterance_in_patient_voice() -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})

    assert create_response.status_code == 200
    payload = create_response.json()
    assert payload["patient_opening_utterance"] == "医生您好，我这次主要是肚子疼，后来右下腹更明显，有点想吐，也有点发热。"
    assert "转移性右下腹痛" not in payload["patient_opening_utterance"]
    assert "低热" not in payload["patient_opening_utterance"]


def test_session_teaching_focus_returns_dynamic_runtime_patterns(authenticated_user: dict[str, str]) -> None:
    create_response = client.post("/api/sessions", json={"case_id": "acs_001"})
    session_id = create_response.json()["session_id"]

    response = client.get(f"/api/sessions/{session_id}/teaching-focus")

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == "acs_001"
    assert payload["session_id"] == session_id
    assert payload["scope"] == "session_runtime"
    assert payload["patterns"][0]["focus_id"] == "session_runtime:acs_001:history_taking"
    assert payload["patterns"][0]["trigger_item_ids"] == ["ht_onset", "ht_character", "ht_radiation"]
    visible_text = "\n".join(
        [
            payload["patterns"][0]["title"],
            payload["patterns"][0]["description"],
            payload["patterns"][0]["training_suggestion"],
            payload["patterns"][0]["why_now"],
        ]
    )
    assert "急性冠脉综合征" not in visible_text
    assert "ACS" not in visible_text
    assert "急性心肌梗死" not in visible_text


def test_message_runtime_error_is_recorded_for_admin_diagnostics(tmp_path, authenticated_user: dict[str, str]) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service._sessions.clear()

    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "training_difficulty": "advanced"},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]

    class FailingGraph:
        def invoke(self, state: dict[str, object]) -> dict[str, object]:
            raise RuntimeError("fastembed is required when OSCE_LOCAL_EMBEDDING_ENABLED=true")

    osce_session_service.osce_graph = FailingGraph()
    with TestClient(app, raise_server_exceptions=False) as error_client:
        error_client.cookies.set(AUTH_COOKIE_NAME, client.cookies.get(AUTH_COOKIE_NAME))
        response = error_client.post(
            f"/api/sessions/{session_id}/message",
            json={"message": "有没有吃坏肚子啊？"},
        )

    assert response.status_code == 500
    assert "训练流程异常" in response.text
    events = osce_session_service.training_event_store.list_session_events(session_id)
    runtime_error_event = find_event(events, "session_runtime_error")
    payload = runtime_error_event["payload"]
    assert payload["operation"] == "message"
    assert payload["training_difficulty"] == "advanced"
    assert payload["error_type"] == "RuntimeError"
    assert "fastembed is required" in payload["message"]
    assert payload["student_message"] == "有没有吃坏肚子啊？"
    assert payload["trace_id"]
    assert "stack_trace" in payload


def test_agent_decision_trace_is_persisted(tmp_path, authenticated_user: dict[str, str]) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service._sessions.clear()
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]

    client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})
    before_reload_payload = client.get(f"/api/sessions/{session_id}").json()
    before_reload_session = osce_session_service._get_session(session_id)
    assert before_reload_session is not None
    before_reload_trace = json.loads(json.dumps(before_reload_session.agent_decision_trace))
    osce_session_service._sessions.clear()
    after_reload_payload = client.get(f"/api/sessions/{session_id}").json()
    after_reload_session = osce_session_service._get_session(session_id)

    assert "agent_decision_trace" not in before_reload_payload
    assert "agent_decision_trace" not in after_reload_payload
    assert before_reload_trace
    assert after_reload_session is not None
    assert after_reload_session.agent_decision_trace == before_reload_trace
    assert after_reload_session.agent_decision_trace[0]["node"] == "training_strategy_node"


def test_history_message_returns_backend_processing_trace_with_timestamps() -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]

    response = client.post(
        f"/api/sessions/{session_id}/message",
        json={"message": "什么时候开始疼的？现在具体哪里疼？"},
    )

    assert create_response.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    patient_turn = next(
        turn
        for turn in reversed(payload["agent_turn_memory"])
        if turn["reply_role"] == "patient" and turn["reply"] == payload["reply"]
    )
    assert isinstance(patient_turn["processing_duration_ms"], int)
    assert patient_turn["processing_duration_ms"] >= 0
    trace = patient_turn["processing_trace"]
    assert [step["step_id"] for step in trace] == [
        "intent",
        "case_context",
        "patient_reply",
        "response",
    ]
    for step in trace:
        assert step["label"]
        assert step["status"] in {"completed", "skipped", "error"}
        assert isinstance(step["duration_ms"], int)
        assert step["duration_ms"] >= 0
        assert step["started_at"].endswith("+00:00")
        assert step["completed_at"].endswith("+00:00")


def test_session_processing_status_exposes_current_backend_step() -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]

    osce_session_service.begin_message_processing_status(session_id)
    osce_session_service.update_message_processing_status(
        session_id,
        step_id="intent",
        label="解析问诊意图",
        status="active",
    )

    response = client.get(f"/api/sessions/{session_id}/processing-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "running"
    assert payload["current_step_id"] == "intent"
    assert payload["current_label"] == "解析问诊意图"
    assert payload["summary"] == "当前：解析问诊意图。"
    assert payload["steps"] == [
        {
            "step_id": "intent",
            "label": "解析问诊意图",
            "status": "active",
        }
    ]


def test_agent_state_recovers_with_session(tmp_path, authenticated_user: dict[str, str]) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service._sessions.clear()
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]

    client.post(f"/api/sessions/{session_id}/physical-exam", json={"exam_code": "abd.palpation.rebound"})
    expected_payload = client.get(f"/api/sessions/{session_id}").json()
    expected_session = osce_session_service._get_session(session_id)
    assert expected_session is not None
    expected_state = json.loads(json.dumps(expected_session.pedagogy_state))
    osce_session_service._sessions.clear()
    loaded_payload = client.get(f"/api/sessions/{session_id}").json()
    loaded_session = osce_session_service._get_session(session_id)

    assert loaded_payload["pedagogy_state"] == expected_payload["pedagogy_state"]
    assert "training_phase" not in loaded_payload["pedagogy_state"]
    assert loaded_session is not None
    assert loaded_session.pedagogy_state == expected_state
    assert loaded_session.pedagogy_state["training_phase"] == "physical_exam"
    assert loaded_session.pedagogy_state["next_best_action"]


def session_operation_requests(session_id: str) -> list[tuple[str, str, dict[str, str] | None]]:
    return [
        ("GET", f"/api/sessions/{session_id}", None),
        ("POST", f"/api/sessions/{session_id}/message", {"message": "什么时候开始疼的？"}),
        ("POST", f"/api/sessions/{session_id}/physical-exam", {"exam_code": "abd.palpation.rebound"}),
        ("POST", f"/api/sessions/{session_id}/auxiliary-test", {"test_code": "lab.cbc"}),
        ("POST", f"/api/sessions/{session_id}/hypotheses", {"hypothesis": "急性阑尾炎"}),
        ("POST", f"/api/sessions/{session_id}/hint", None),
        ("GET", f"/api/sessions/{session_id}/teaching-focus", None),
        (
            "POST",
            f"/api/sessions/{session_id}/submit-diagnosis",
            {"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
        ),
        ("GET", f"/api/sessions/{session_id}/report", None),
        ("POST", f"/api/sessions/{session_id}/report/generate", None),
        ("POST", f"/api/sessions/{session_id}/report/enrich", None),
    ]


def test_session_operations_require_logged_in_user() -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]

    with TestClient(app) as anonymous_client:
        for method, path, json_body in session_operation_requests(session_id):
            response = anonymous_client.request(method, path, json=json_body)

            assert response.status_code == 401
            assert response.json() == {"detail": "not authenticated"}


def test_session_operations_reject_other_authenticated_user() -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    other_user = main.auth_store.create_user("other-student@example.test", "safe-password-456", "学生乙")
    assert other_user is not None
    other_token = main.auth_store.create_session(other_user["user_id"])

    with TestClient(app) as other_client:
        other_client.cookies.set(AUTH_COOKIE_NAME, other_token)
        for method, path, json_body in session_operation_requests(session_id):
            response = other_client.request(method, path, json=json_body)

            assert response.status_code == 404
            assert response.json() == {"detail": "session not found"}


def test_current_user_sessions_require_logged_in_user() -> None:
    with TestClient(app) as anonymous_client:
        response = anonymous_client.get("/api/me/sessions")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


def test_current_user_sessions_list_only_owned_sessions(tmp_path, authenticated_user: dict[str, str]) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service._sessions.clear()
    current_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    other_user = main.auth_store.create_user("other-history@example.test", "safe-password-456", "学生乙")
    assert other_user is not None
    other_token = main.auth_store.create_session(other_user["user_id"])

    with TestClient(app) as other_client:
        other_client.cookies.set(AUTH_COOKIE_NAME, other_token)
        other_response = other_client.post("/api/sessions", json={"case_id": "pneumonia_001"})

    response = client.get("/api/me/sessions")

    assert current_response.status_code == 200
    assert other_response.status_code == 200
    assert response.status_code == 200
    sessions = response.json()["sessions"]
    assert len(sessions) == 1
    assert {
        key: sessions[0][key]
        for key in [
            "session_id",
            "case_id",
            "case_title",
            "stage",
            "is_completed",
            "can_continue",
            "has_report",
            "completion_status",
        ]
    } == {
        "session_id": current_response.json()["session_id"],
        "case_id": "appendicitis_001",
        "case_title": "右下腹痛教学病例",
        "stage": "case_intro",
        "is_completed": False,
        "can_continue": True,
        "has_report": False,
        "completion_status": "in_progress",
    }
    assert sessions[0]["session_id"] != other_response.json()["session_id"]
    assert sessions[0]["created_at"]
    assert sessions[0]["updated_at"]
    assert isinstance(sessions[0]["active_skill_context"], dict)


def test_current_user_sessions_mark_completed_after_diagnosis_submission(
    tmp_path,
    authenticated_user: dict[str, str],
) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service._sessions.clear()
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]

    before_submit_response = client.get("/api/me/sessions")

    submit_response = client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
    )
    after_submit_response = client.get("/api/me/sessions")
    report_response = client.post(f"/api/sessions/{session_id}/report/generate")
    after_report_response = client.get("/api/me/sessions")

    assert create_response.status_code == 200
    assert before_submit_response.status_code == 200
    assert before_submit_response.json()["sessions"][0]["is_completed"] is False
    assert before_submit_response.json()["sessions"][0]["can_continue"] is True
    assert before_submit_response.json()["sessions"][0]["has_report"] is False
    assert before_submit_response.json()["sessions"][0]["completion_status"] == "in_progress"
    assert submit_response.status_code == 200
    assert after_submit_response.status_code == 200
    assert after_submit_response.json()["sessions"][0]["is_completed"] is True
    assert after_submit_response.json()["sessions"][0]["can_continue"] is False
    assert after_submit_response.json()["sessions"][0]["has_report"] is False
    assert after_submit_response.json()["sessions"][0]["completion_status"] == "diagnosis_submitted"
    assert report_response.status_code == 200
    assert after_report_response.status_code == 200
    assert after_report_response.json()["sessions"][0]["is_completed"] is True
    assert after_report_response.json()["sessions"][0]["can_continue"] is False
    assert after_report_response.json()["sessions"][0]["has_report"] is True
    assert after_report_response.json()["sessions"][0]["completion_status"] == "report_ready"


def test_completed_session_rejects_further_training_actions(tmp_path, authenticated_user: dict[str, str]) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service._sessions.clear()
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    submit_response = client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
    )

    blocked_responses = [
        client.post(f"/api/sessions/{session_id}/message", json={"message": "现在还疼吗？"}),
        client.post(f"/api/sessions/{session_id}/physical-exam", json={"exam_code": "abd.palpation.rebound"}),
        client.post(f"/api/sessions/{session_id}/auxiliary-test", json={"test_code": "lab.cbc"}),
        client.post(f"/api/sessions/{session_id}/hypotheses", json={"hypothesis": "急性阑尾炎"}),
        client.post(f"/api/sessions/{session_id}/hint"),
        client.post(
            f"/api/sessions/{session_id}/submit-diagnosis",
            json={"diagnosis": "急性阑尾炎", "reasoning": "再次提交。"},
        ),
    ]

    assert create_response.status_code == 200
    assert submit_response.status_code == 200
    assert [response.status_code for response in blocked_responses] == [409, 409, 409, 409, 409, 409]
    assert {response.json()["detail"] for response in blocked_responses} == {"训练已结束，请查看报告。"}


def test_session_closed_after_api_precheck_still_returns_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]

    def reject_after_precheck(_: str, __: str) -> dict[str, object]:
        raise SessionClosedError("训练已结束，请查看报告。")

    monkeypatch.setattr(osce_session_service, "handle_message", reject_after_precheck)

    response = client.post(
        f"/api/sessions/{session_id}/message",
        json={"message": "这个请求在预检之后才拿到会话锁"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "训练已结束，请查看报告。"}


def test_current_user_profile_requires_logged_in_user() -> None:
    with TestClient(app) as anonymous_client:
        response = anonymous_client.get("/api/me/profile")

    assert response.status_code == 401
    assert response.json() == {"detail": "not authenticated"}


def test_current_user_profile_aggregates_only_owned_sessions_and_reports(tmp_path, authenticated_user: dict[str, str]) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_candidate_store = TrainingSkillCandidateStore(
        tmp_path / "training_skill_candidates.sqlite3"
    )
    osce_session_service._sessions.clear()
    current_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    current_session_id = current_response.json()["session_id"]
    client.post(f"/api/sessions/{current_session_id}/message", json={"message": "什么时候开始疼的？"})
    client.post(f"/api/sessions/{current_session_id}/physical-exam", json={"exam_code": "abd.palpation.rebound"})
    client.post(f"/api/sessions/{current_session_id}/auxiliary-test", json={"test_code": "lab.cbc"})
    client.post(
        f"/api/sessions/{current_session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
    )
    current_report_response = client.post(f"/api/sessions/{current_session_id}/report/generate")
    current_enrich_response = client.post(f"/api/sessions/{current_session_id}/report/enrich")
    other_user = main.auth_store.create_user("other-profile@example.test", "safe-password-456", "学生乙")
    assert other_user is not None
    other_token = main.auth_store.create_session(other_user["user_id"])

    with TestClient(app) as other_client:
        other_client.cookies.set(AUTH_COOKIE_NAME, other_token)
        other_response = other_client.post("/api/sessions", json={"case_id": "pneumonia_001"})

    response = client.get("/api/me/profile")

    assert current_response.status_code == 200
    assert current_report_response.status_code == 200
    assert current_enrich_response.status_code == 202
    assert other_response.status_code == 200
    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["student_id"] == authenticated_user["user_id"]
    assert profile["total_sessions"] == 1
    assert profile["report_count"] == 1
    assert profile["average_score"] == 22
    assert profile["recent_sessions"][0]["session_id"] == current_session_id
    assert profile["recent_sessions"][0]["session_id"] != other_response.json()["session_id"]
    assert profile["recent_sessions"][0]["case_title"] == "右下腹痛教学病例"
    assert profile["recent_sessions"][0]["stage_label"] == "报告已生成"
    assert "active_skill_context" not in profile["recent_sessions"][0]
    assert profile["strongest_dimension"] == {
        "key": "main_diagnosis",
        "label": "主诊断",
        "average": 10,
        "sample_count": 1,
        "average_score": 10,
        "average_max_score": 10,
        "average_percentage": 100,
    }
    assert profile["weakest_dimension"] == {
        "key": "relationship_building",
        "label": "关系建立",
        "average": 0,
        "sample_count": 1,
        "average_score": 0,
        "average_max_score": 5,
        "average_percentage": 0,
    }
    assert profile["skill_accumulation"]["status"] == "active"
    assert profile["skill_accumulation"]["enabled_skill_count"] == 1
    assert profile["skill_accumulation"]["applied_skill_count"] == 0
    assert profile["skill_accumulation"]["enabled_skills"][0]["skill_id"].startswith("skill_personal_")
    assert profile["skill_accumulation"]["enabled_skills"][0]["effect_status"] == "insufficient_samples"
    personal_skill_id = profile["skill_accumulation"]["enabled_skills"][0]["skill_id"]
    assert profile["skill_profile_summary"]["recent_error_item_ids"] == [
        "ht_migration",
        "ht_character",
        "ht_severity",
        "ht_associated_gi",
        "ht_associated_fever",
        "ht_past_medical",
        "ht_allergy",
        "ht_ice",
    ]
    assert profile["skill_profile_summary"]["current_focus_item_ids"] == [
        "ht_migration",
        "ht_character",
        "ht_severity",
    ]
    assert profile["skill_profile_summary"]["current_focus_items"] == [
        {"item_id": "ht_migration", "label": "追问疼痛部位及转移特征"},
        {"item_id": "ht_character", "label": "追问疼痛性质"},
        {"item_id": "ht_severity", "label": "追问疼痛程度"},
    ]
    assert profile["skill_profile_summary"]["last_updated_from_report_count"] == 1
    assert profile["skill_profile_summary"]["skill_states"][personal_skill_id]["state"] == "active"
    assert profile["skill_profile_summary"]["skill_states"][personal_skill_id]["state_label"] == "正在生效"
    assert profile["skill_profile_summary"]["skill_states"][personal_skill_id]["effect_status_label"] == "样本不足"
    assert profile["skill_profile_summary"]["skill_states"][personal_skill_id]["matched_recent_error_items"][0] == {
        "item_id": "ht_migration",
        "label": "追问疼痛部位及转移特征",
    }
    assert "近期画像命中思维模式" in profile["skill_profile_summary"]["skill_states"][personal_skill_id][
        "selection_reason"
    ]
    assert profile["skill_profile_summary"]["skill_states"][personal_skill_id]["matched_recent_error_item_ids"] == [
        "ht_migration",
        "ht_character",
        "ht_severity",
        "ht_associated_gi",
        "ht_associated_fever",
        "ht_past_medical",
        "ht_allergy",
        "ht_ice",
    ]
    assert profile["skill_profile_summary"]["skill_states"][personal_skill_id]["priority"] >= 8
    teaching_effect = profile["skill_profile_summary"]["teaching_effect_summary"]
    assert teaching_effect["status"] == "insufficient_samples"
    assert teaching_effect["status_label"] == "样本不足"
    assert "不能判断趋势" in teaching_effect["summary"]
    assert teaching_effect["evidence_boundary"].startswith("教学效果观察只来自训练报告")
    assert profile["learning_path"][0] == {
        "task_type": "redo_same_case",
        "task_type_label": "复训当前病例",
        "case_id": "appendicitis_001",
        "case_title": "右下腹痛教学病例",
        "objective": "复训右下腹痛教学病例，优先补强关系建立并补齐本轮反复缺失的评分项。",
        "target_rubric_items": [
            "ht_migration",
            "ht_character",
            "ht_severity",
            "ht_associated_gi",
            "ht_associated_fever",
        ],
        "target_rubric_item_labels": [
            "追问疼痛部位及转移特征",
            "追问疼痛性质",
            "追问疼痛程度",
            "追问恶心呕吐腹泻",
            "追问发热",
        ],
        "source_report_count": 1,
        "source_references": [
            "rubric:appendicitis_001_rubric.item.ht_migration",
            "rubric:appendicitis_001_rubric.item.ht_character",
            "rubric:appendicitis_001_rubric.item.ht_severity",
            "rubric:appendicitis_001_rubric.item.ht_associated_gi",
            "rubric:appendicitis_001_rubric.item.ht_associated_fever",
        ],
        "source_reference_labels": [
            "评分项：追问疼痛部位及转移特征",
            "评分项：追问疼痛性质",
            "评分项：追问疼痛程度",
            "评分项：追问恶心呕吐腹泻",
            "评分项：追问发热",
        ],
    }
    assert profile["learning_path"][1] == {
        "task_type": "contrast_case",
        "task_type_label": "推荐对照病例",
        "case_id": "acs_001",
        "case_title": "胸痛伴出汗教学病例",
        "objective": "对照胸痛伴出汗教学病例，迁移本轮薄弱维度的问诊、检查选择和证据链表达。",
        "target_rubric_items": [
            "ht_migration",
            "ht_character",
            "ht_severity",
            "ht_associated_gi",
            "ht_associated_fever",
        ],
        "target_rubric_item_labels": [
            "追问疼痛部位及转移特征",
            "追问疼痛性质",
            "追问疼痛程度",
            "追问恶心呕吐腹泻",
            "追问发热",
        ],
        "source_report_count": 1,
        "source_references": ["case:acs_001"],
        "source_reference_labels": ["病例：胸痛伴出汗教学病例"],
    }


def test_learning_path_labels_mixed_case_missed_items_with_readable_text() -> None:
    reports = [
        {
            "case_id": "acs_001",
            "missed_items": ["dd_aortic_dissection", "dd_gerd", "reasoning_core"],
            "knowledge_recommendations": [],
        },
        {
            "case_id": "hyperthyroid_001",
            "missed_items": ["ht_family_history", "at_thyroid_us"],
            "knowledge_recommendations": [],
        },
    ]

    learning_path = main._build_learning_path(
        reports,
        {"key": "differential_diagnosis", "label": "鉴别诊断", "average": 0},
    )

    for task in learning_path:
        labels = task["target_rubric_item_labels"]
        assert "追问甲状腺相关家族史" in labels
        assert "申请甲状腺超声" in labels
        assert "ht_family_history" not in labels
        assert "at_thyroid_us" not in labels


def test_profile_dimension_averages_label_humanistic_dimensions() -> None:
    averages = main._get_dimension_averages(
        [
            {
                "dimension_scores": {
                    "relationship_building": 0,
                    "medical_ethics": 1,
                    "narrative_medicine": 3,
                    "communication_skill": 4,
                },
                "rubric_scores": {
                    "relationship": {
                        "dimension_id": "relationship_building",
                        "max_score": 5,
                    },
                    "ethics": {
                        "dimension_id": "medical_ethics",
                        "max_score": 7,
                    },
                    "narrative": {
                        "dimension_id": "narrative_medicine",
                        "max_score": 8,
                    },
                    "communication": {
                        "dimension_id": "communication_skill",
                        "max_score": 10,
                    },
                },
            }
        ]
    )

    labels_by_key = {item["key"]: item["label"] for item in averages}

    assert labels_by_key["relationship_building"] == "关系建立"
    assert labels_by_key["medical_ethics"] == "医学伦理"
    assert labels_by_key["narrative_medicine"] == "叙事医学"
    assert labels_by_key["communication_skill"] == "沟通技巧"


def test_profile_dimension_averages_rank_mixed_rubrics_by_completion_percentage() -> None:
    averages = main._get_dimension_averages(
        [
            {
                "dimension_scores": {
                    "history_taking": 9,
                    "relationship_building": 5,
                },
                "rubric_scores": {
                    "history": {
                        "dimension_id": "history_taking",
                        "max_score": 18,
                    },
                    "relationship": {
                        "dimension_id": "relationship_building",
                        "max_score": 5,
                    },
                },
            },
            {
                "dimension_scores": {
                    "history_taking": 20,
                },
                "rubric_scores": {
                    "history": {
                        "dimension_id": "history_taking",
                        "max_score": 25,
                    },
                },
            },
            {
                "dimension_scores": {
                    "history_taking": 99,
                },
                "rubric_scores": {},
            },
        ]
    )

    assert averages == [
        {
            "key": "relationship_building",
            "label": "关系建立",
            "average": 5,
            "sample_count": 1,
            "average_score": 5,
            "average_max_score": 5,
            "average_percentage": 100,
        },
        {
            "key": "history_taking",
            "label": "问诊",
            "average": 14.5,
            "sample_count": 2,
            "average_score": 14.5,
            "average_max_score": 21.5,
            "average_percentage": 65,
        },
    ]


def test_current_user_profile_reports_enabled_and_applied_training_skills(tmp_path) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service._sessions.clear()
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "case_ids": ["appendicitis_001"],
            "title": "临床推理链纠偏提示",
            "description": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "status": "draft",
            "source_report_count": 2,
            "support_count": 2,
            "related_recommendations": [],
            "review": {"status": "approved"},
        }
    )
    current_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    other_user = main.auth_store.create_user("other-skill-profile@example.test", "safe-password-456", "学生乙")
    assert other_user is not None
    other_token = main.auth_store.create_session(other_user["user_id"])

    with TestClient(app) as other_client:
        other_client.cookies.set(AUTH_COOKIE_NAME, other_token)
        other_response = other_client.post("/api/sessions", json={"case_id": "pneumonia_001"})

    response = client.get("/api/me/profile")

    assert current_response.status_code == 200
    assert other_response.status_code == 200
    assert response.status_code == 200
    assert response.json()["profile"]["skill_accumulation"] == {
        "status": "active",
        "description": "已启用 1 条教学 Skill，并在当前账号训练中应用 1 次。",
        "enabled_skill_count": 1,
        "applied_skill_count": 1,
        "enabled_skills": [
            {
                "skill_id": "skill_reasoning_core",
                "title": "临床推理链纠偏提示",
                "student_visible_summary": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
                "description": "2 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001。",
                "learning_action": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
                "activation_summary": "适用于右下腹痛教学病例；训练开始时，当当前缺口命中 1 个关联训练点时触发。",
                "source_summary": "来自 2 份报告，累计支持 2 次。",
                "effect_status_label": "样本不足",
                "scope_label": "全局 Skill",
                "support_count": 2,
                "source_report_count": 2,
                "effect_status": "insufficient_samples",
            }
        ],
    }


def test_current_user_profile_recent_session_uses_readable_stage_label(tmp_path) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service._sessions.clear()
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    message_response = client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})

    response = client.get("/api/me/profile")

    assert create_response.status_code == 200
    assert message_response.status_code == 200
    assert response.status_code == 200
    recent_session = response.json()["profile"]["recent_sessions"][0]
    assert recent_session["stage"] == "history_taking"
    assert recent_session["stage_label"] == "问诊阶段"


def test_completed_report_persists_student_profile_snapshot(tmp_path, authenticated_user: dict[str, str]) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_candidate_store = TrainingSkillCandidateStore(
        tmp_path / "training_skill_candidates.sqlite3"
    )
    osce_session_service.student_profile_store = StudentProfileStore(tmp_path / "student_profiles.sqlite3")
    osce_session_service._sessions.clear()
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})
    client.post(f"/api/sessions/{session_id}/physical-exam", json={"exam_code": "abd.palpation.rebound"})
    client.post(f"/api/sessions/{session_id}/auxiliary-test", json={"test_code": "lab.cbc"})
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "反跳痛和白细胞升高支持诊断。"},
    )

    report_response = client.post(f"/api/sessions/{session_id}/report/generate")
    enrich_response = client.post(f"/api/sessions/{session_id}/report/enrich")
    stored_profile = osce_session_service.student_profile_store.get_profile(authenticated_user["user_id"])

    assert create_response.status_code == 200
    assert report_response.status_code == 200
    assert enrich_response.status_code == 202
    assert stored_profile is not None
    assert stored_profile["student_id"] == authenticated_user["user_id"]
    assert stored_profile["last_updated_from_report_count"] == 1
    assert stored_profile["current_focus_items"][0]["label"] == "追问疼痛部位及转移特征"
    assert stored_profile["skill_states"]


def test_new_session_skill_selection_uses_recent_profile_errors(tmp_path) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service._sessions.clear()
    first_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    first_session_id = first_response.json()["session_id"]
    osce_session_service.report_store.save_report(
        {
            "session_id": first_session_id,
            "case_id": "appendicitis_001",
            "total_score": 20,
            "dimension_scores": {"history_taking": 1},
            "missed_items": ["ht_migration"],
        }
    )
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_generic_lab",
            "trigger_item_id": "ax_cbc",
            "trigger_item_ids": ["ax_cbc"],
            "case_ids": ["appendicitis_001"],
            "stage_scope": ["case_intro"],
            "title": "高支持次数通用检查训练",
            "description": "通用检查训练。",
            "suggested_strategy": "提醒学生考虑基础检查，但不泄露标准诊断。",
            "source_report_count": 20,
            "support_count": 20,
            "review": {"status": "approved", "regression_passed": True},
        }
    )
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_profile_migration",
            "trigger_item_id": "ht_migration",
            "trigger_item_ids": ["ht_migration"],
            "case_ids": ["appendicitis_001"],
            "stage_scope": ["case_intro"],
            "title": "近期漏项腹痛迁移追问",
            "description": "近期训练反复遗漏腹痛迁移。",
            "suggested_strategy": "优先追问疼痛是否从上腹转移到右下腹，以及迁移前后变化。",
            "source_report_count": 1,
            "support_count": 1,
            "review": {"status": "approved", "regression_passed": True},
        }
    )

    second_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert "active_skill_context" not in second_response.json()
    second_session = osce_session_service._get_session(second_response.json()["session_id"])
    assert second_session is not None
    selected_skills = second_session.active_skill_context["selected_skills"]
    assert [skill["skill_id"] for skill in selected_skills[:2]] == [
        "skill_ht_migration",
        "skill_ax_cbc",
    ]
    assert selected_skills[0]["why_candidate"] == "近期画像命中 ht_migration"



def test_current_user_session_detail_and_report_require_logged_in_user() -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]

    with TestClient(app) as anonymous_client:
        detail_response = anonymous_client.get(f"/api/me/sessions/{session_id}")
        report_response = anonymous_client.get(f"/api/me/sessions/{session_id}/report")

    assert detail_response.status_code == 401
    assert detail_response.json() == {"detail": "not authenticated"}
    assert report_response.status_code == 401
    assert report_response.json() == {"detail": "not authenticated"}


def test_current_user_session_detail_and_report_use_owned_session() -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
    )
    generate_response = client.post(f"/api/sessions/{session_id}/report/generate")
    other_user = main.auth_store.create_user("other-detail@example.test", "safe-password-456", "学生乙")
    assert other_user is not None
    other_token = main.auth_store.create_session(other_user["user_id"])

    detail_response = client.get(f"/api/me/sessions/{session_id}")
    report_response = client.get(f"/api/me/sessions/{session_id}/report")

    assert detail_response.status_code == 200
    assert generate_response.status_code == 200
    assert detail_response.json()["session_id"] == session_id
    assert report_response.status_code == 200
    assert report_response.json()["session_id"] == session_id

    with TestClient(app) as other_client:
        other_client.cookies.set(AUTH_COOKIE_NAME, other_token)
        other_detail_response = other_client.get(f"/api/me/sessions/{session_id}")
        other_report_response = other_client.get(f"/api/me/sessions/{session_id}/report")

    assert other_detail_response.status_code == 404
    assert other_detail_response.json() == {"detail": "session not found"}
    assert other_report_response.status_code == 404
    assert other_report_response.json() == {"detail": "session not found"}


def test_admin_login_cookie_can_still_read_student_report(tmp_path) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service._sessions.clear()
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    submit_response = client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
    )
    generate_response = client.post(f"/api/sessions/{session_id}/report/generate")

    admin_login_response = client.post("/api/auth/login", json={"email": "admin@osce.test", "password": "admin"})
    detail_response = client.get(f"/api/me/sessions/{session_id}")
    report_response = client.get(f"/api/me/sessions/{session_id}/report")

    assert create_response.status_code == 200
    assert submit_response.status_code == 200
    assert generate_response.status_code == 200
    assert admin_login_response.status_code == 200
    assert detail_response.status_code == 200
    assert detail_response.json()["session_id"] == session_id
    assert report_response.status_code == 200
    assert report_response.json()["session_id"] == session_id


def test_current_user_can_delete_only_owned_session(tmp_path) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(
        tmp_path / "training_events.sqlite3"
    )
    osce_session_service.training_skill_store = TrainingSkillStore(
        tmp_path / "training_skills.sqlite3"
    )
    osce_session_service.training_skill_candidate_store = TrainingSkillCandidateStore(
        tmp_path / "training_skill_candidates.sqlite3"
    )
    osce_session_service.student_profile_store = StudentProfileStore(
        tmp_path / "student_profiles.sqlite3"
    )
    osce_session_service._sessions.clear()
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    other_user = main.auth_store.create_user("other-delete@example.test", "safe-password-456", "学生乙")
    assert other_user is not None
    other_token = main.auth_store.create_session(other_user["user_id"])

    with TestClient(app) as anonymous_client:
        anonymous_response = anonymous_client.delete(f"/api/me/sessions/{session_id}")

    with TestClient(app) as other_client:
        other_client.cookies.set(AUTH_COOKIE_NAME, other_token)
        other_response = other_client.delete(f"/api/me/sessions/{session_id}")

    delete_response = client.delete(f"/api/me/sessions/{session_id}")
    repeated_delete_response = client.delete(f"/api/me/sessions/{session_id}")
    with TestClient(app) as other_client:
        other_client.cookies.set(AUTH_COOKIE_NAME, other_token)
        other_retry_response = other_client.delete(f"/api/me/sessions/{session_id}")
    detail_response = client.get(f"/api/me/sessions/{session_id}")
    list_response = client.get("/api/me/sessions")

    assert anonymous_response.status_code == 401
    assert anonymous_response.json() == {"detail": "not authenticated"}
    assert other_response.status_code == 404
    assert other_response.json() == {"detail": "session not found"}
    assert delete_response.status_code == 200
    assert delete_response.json() == {"status": "deleted", "session_id": session_id}
    assert repeated_delete_response.status_code == 200
    assert repeated_delete_response.json() == {
        "status": "deleted",
        "session_id": session_id,
    }
    assert other_retry_response.status_code == 404
    assert other_retry_response.json() == {"detail": "session not found"}
    assert detail_response.status_code == 404
    assert detail_response.json() == {"detail": "session not found"}
    assert list_response.status_code == 200
    assert list_response.json() == {"sessions": []}


def test_current_user_can_recover_and_delete_owned_legacy_tombstone(
    tmp_path,
    authenticated_user: dict[str, str],
) -> None:
    osce_session_service.session_store = OsceSessionStore(
        tmp_path / "osce_sessions.sqlite3"
    )
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(
        tmp_path / "training_events.sqlite3"
    )
    osce_session_service.training_skill_store = TrainingSkillStore(
        tmp_path / "training_skills.sqlite3"
    )
    osce_session_service.training_skill_candidate_store = TrainingSkillCandidateStore(
        tmp_path / "training_skill_candidates.sqlite3"
    )
    osce_session_service.student_profile_store = StudentProfileStore(
        tmp_path / "student_profiles.sqlite3"
    )
    osce_session_service._sessions.clear()
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001"},
    )
    session_id = create_response.json()["session_id"]
    osce_session_service.report_store.create_base_report(
        {
            "report_id": f"{session_id}_report",
            "session_id": session_id,
            "case_id": "appendicitis_001",
            "student_id": authenticated_user["user_id"],
            "total_score": 80,
            "missed_items": [],
        },
        enrichment_required=False,
    )
    assert osce_session_service.session_store.delete_session(session_id) is True
    with sqlite3.connect(
        osce_session_service.session_store.database_path
    ) as connection:
        connection.execute(
            """
            UPDATE osce_session_tombstones
            SET user_id = '', case_id = '', cleanup_status = 'completed',
                cleanup_completed_at = deleted_at
            WHERE session_id = ?
            """,
            (session_id,),
        )

    other_user = main.auth_store.create_user(
        "other-legacy-delete@example.test",
        "safe-password-456",
        "学生乙",
    )
    assert other_user is not None
    other_token = main.auth_store.create_session(other_user["user_id"])
    with TestClient(app) as other_client:
        other_client.cookies.set(AUTH_COOKIE_NAME, other_token)
        other_response = other_client.delete(
            f"/api/me/sessions/{session_id}"
        )

    delete_response = client.delete(f"/api/me/sessions/{session_id}")

    assert other_response.status_code == 404
    assert other_response.json() == {"detail": "session not found"}
    assert delete_response.status_code == 200
    assert delete_response.json() == {
        "status": "deleted",
        "session_id": session_id,
    }
    deletion = osce_session_service.session_store.get_session_deletion(
        session_id
    )
    assert deletion is not None
    assert deletion.user_id == authenticated_user["user_id"]
    assert deletion.cleanup_status == "completed"
    assert osce_session_service.report_store.get_report(session_id) is None
    assert (
        osce_session_service.training_event_store.list_session_events(session_id)
        == []
    )


def test_session_deletion_conflict_returns_generic_http_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_conflict(
        _: str,
        *,
        expected_student_id: str | None = None,
    ) -> bool:
        assert expected_student_id is not None
        raise SessionDeletionConflictError("sensitive ownership details")

    monkeypatch.setattr(osce_session_service, "delete_session", raise_conflict)

    response = client.delete("/api/me/sessions/session-conflict")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "会话关联数据存在冲突，无法安全删除。"
    }
    assert "sensitive" not in response.text


def test_create_session_does_not_return_case_specific_diagnosis_draft() -> None:
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "pneumonia_001", "student_id": "student_demo"},
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["case_id"] == "pneumonia_001"
    assert created["diagnosis_draft"] == {
        "diagnosis": "",
        "reasoning": "",
    }


def test_create_session_returns_student_visible_patient_profile() -> None:
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )

    assert create_response.status_code == 200
    patient_profile = create_response.json()["patient_profile"]
    assert patient_profile == {
        "age": "22岁",
        "gender": "男",
        "occupation": "学生",
        "hospital_department": "急诊外科",
    }
    assert "idea" not in patient_profile
    assert "concern" not in patient_profile
    assert "expectation" not in patient_profile
    assert "social_background" not in patient_profile


def test_create_session_returns_opening_task_card_without_hidden_inquiry_guidance() -> None:
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["opening_task_card"] == {
        "role": "你是急诊外科接诊医生。",
        "scenario": "一名22岁男性学生因转移性右下腹痛 24 小时，伴恶心、低热来诊。",
        "tasks": [
            "进行有重点的病史采集",
            "判断需要哪些查体",
            "选择必要辅助检查",
            "提出诊断假设和鉴别诊断",
            "最终提交诊断与推理依据",
        ],
    }
    assert "inquiry_guidance" not in created
    assert "急性阑尾炎" not in str(created["opening_task_card"])


def test_osce_session_routes_real_medical_request_to_safety_event(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    osce_session_service.training_event_store = TrainingEventStore(database_path)
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_candidate_store = TrainingSkillCandidateStore(
        tmp_path / "training_skill_candidates.sqlite3"
    )
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]
    message = "我现实中右下腹痛，应该吃什么药和用药剂量？"

    response = client.post(f"/api/sessions/{session_id}/message", json={"message": message})

    assert response.status_code == 200
    payload = response.json()
    assert "current_intent" not in payload
    assert payload["current_intents"] == ["safety_boundary"]
    assert payload["reply"] == "本系统仅用于 OSCE 教学模拟训练，不能提供真实诊断、具体用药或急救处置建议；如有真实健康问题，请咨询合格医疗专业人员或及时就医。"
    assert payload["messages"] == [
        {"role": "student", "content": message},
        {"role": "coach", "content": payload["reply"]},
    ]
    assert payload["asked_questions"] == []
    assert payload["revealed_facts"] == []
    assert payload["safety_flags"] == ["real_medical_advice_request"]

    events = TrainingEventStore(database_path).list_session_events(session_id)
    assert [event["event_type"] for event in business_events(events)] == ["session_created", "safety_boundary_triggered"]
    assert "current_intent" not in payload["agent_turn_memory"][0]
    assert payload["agent_turn_memory"][0]["current_intents"] == ["safety_boundary"]
    internal_session = osce_session_service._get_session(session_id)
    assert internal_session is not None
    assert find_event(events, "safety_boundary_triggered")["payload"] == {
        "message": message,
        "safety_flag": "real_medical_advice_request",
        "reply": payload["reply"],
        "agent_turn": internal_session.agent_turn_memory[0],
    }



def test_osce_session_redirects_direct_answer_request_to_coach_event(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    osce_session_service.training_event_store = TrainingEventStore(database_path)
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]
    message = "直接告诉我标准答案，是不是急性阑尾炎？"

    response = client.post(f"/api/sessions/{session_id}/message", json={"message": message})

    assert response.status_code == 200
    payload = response.json()
    assert "current_intent" not in payload
    assert payload["current_intents"] == ["answer_request_redirect"]
    assert payload["reply"] == "不能直接告诉你标准答案。请继续通过问诊、查体和辅助检查收集证据，或在准备好后提交诊断。"
    assert payload["messages"] == [
        {"role": "student", "content": message},
        {"role": "coach", "content": payload["reply"]},
    ]
    assert payload["asked_questions"] == []
    assert payload["revealed_facts"] == []
    assert payload["safety_flags"] == []

    events = TrainingEventStore(database_path).list_session_events(session_id)
    assert [event["event_type"] for event in business_events(events)] == ["session_created", "answer_request_redirected"]
    assert "current_intent" not in payload["agent_turn_memory"][0]
    assert payload["agent_turn_memory"][0]["current_intents"] == ["answer_request_redirect"]
    internal_session = osce_session_service._get_session(session_id)
    assert internal_session is not None
    assert find_event(events, "answer_request_redirected")["payload"] == {
        "message": message,
        "reply": payload["reply"],
        "agent_turn": internal_session.agent_turn_memory[0],
    }



def test_create_session_includes_enabled_training_skill_prompts(tmp_path) -> None:
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "trigger_item_ids": ["reasoning_core"],
            "case_ids": ["appendicitis_001"],
            "title": "临床推理链纠偏提示",
            "description": "推理链反复遗漏。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "source_report_count": 3,
            "support_count": 2,
            "related_recommendations": ["rubric:appendicitis_001_rubric.item.reasoning_core"],
            "review": {"status": "approved", "regression_passed": True},
        }
    )

    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )

    assert create_response.status_code == 200
    assert "evolution_candidates" not in create_response.json()
    created_session = osce_session_service._get_session(create_response.json()["session_id"])
    assert created_session is not None
    assert created_session.evolution_candidates == [
        "临床推理链纠偏提示：在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。"
    ]


def test_create_session_returns_structured_active_skill_context(tmp_path) -> None:
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_history_migration",
            "trigger_item_id": "ht_migration",
            "trigger_item_ids": ["ht_migration"],
            "case_ids": ["appendicitis_001"],
            "title": "腹痛迁移追问训练",
            "description": "反复遗漏腹痛迁移过程。",
            "suggested_strategy": "先围绕起病部位、迁移过程和疼痛变化做聚焦追问。",
            "source_report_count": 2,
            "support_count": 3,
            "related_recommendations": ["rubric:appendicitis_001_rubric.item.ht_migration"],
            "review": {"status": "approved", "regression_passed": True},
        }
    )

    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )

    assert create_response.status_code == 200
    assert "active_skill_context" not in create_response.json()
    created_session = osce_session_service._get_session(create_response.json()["session_id"])
    assert created_session is not None
    active_skill_context = created_session.active_skill_context
    assert active_skill_context["skill_index"] == [
        {
            "skill_id": "skill_ht_migration",
            "title": "腹痛迁移追问训练",
            "scope": "global",
            "stage_scope": ["case_intro"],
            "trigger_item_ids": ["ht_migration"],
            "trigger_item_labels": ["追问疼痛部位及转移特征"],
            "priority": 0,
            "why_candidate": "适用训练点 ht_migration",
            "why_selected_label": "适用训练点：追问疼痛部位及转移特征。",
            "summary": "腹痛迁移追问训练：反复遗漏腹痛迁移过程。",
            "when_to_use": "当学生在训练开始阶段暴露出病史采集结构化不足，且当前上下文命中关联训练点时使用。",
            "when_not_to_use": "空白开局、学生尚未暴露相关错误模式、该问题已冷却/退休，或提示会泄露标准答案 / 隐藏事实时不要使用。",
            "risk": "仅用于教学提示和复盘，不得透露标准诊断、隐藏事实或真实临床处理细节。",
        }
    ]
    assert active_skill_context["selected_skills"][0]["suggested_strategy"] == "先围绕起病部位、迁移过程和疼痛变化做聚焦追问。"
    assert active_skill_context["selected_skills"][0]["skill_id"] == "skill_ht_migration"
    assert active_skill_context["skipped_reasons"] == []


def test_active_skill_context_refreshes_after_session_stage_changes(tmp_path) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service._sessions.clear()
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_history_migration",
            "trigger_item_id": "ht_migration",
            "trigger_item_ids": ["ht_migration"],
            "case_ids": ["appendicitis_001"],
            "stage_scope": ["case_intro"],
            "title": "腹痛迁移追问训练",
            "description": "反复遗漏腹痛迁移过程。",
            "suggested_strategy": "先围绕起病部位、迁移过程和疼痛变化做聚焦追问。",
            "source_report_count": 2,
            "support_count": 3,
            "review": {"status": "approved", "regression_passed": True},
        }
    )
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_physical_tenderness",
            "trigger_item_id": "pe_tenderness",
            "trigger_item_ids": ["pe_tenderness"],
            "case_ids": ["appendicitis_001"],
            "stage_scope": ["physical_exam"],
            "title": "右下腹压痛查体训练",
            "description": "进入查体阶段后提醒学生验证右下腹体征。",
            "suggested_strategy": "已进入查体阶段，优先确认右下腹压痛和腹膜刺激征，不透露诊断答案。",
            "source_report_count": 2,
            "support_count": 4,
            "review": {"status": "approved", "regression_passed": True},
        }
    )

    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    created_session = osce_session_service._get_session(session_id)
    assert created_session is not None
    initial_skill_id = created_session.active_skill_context["selected_skills"][0]["skill_id"]
    exam_response = client.post(
        f"/api/sessions/{session_id}/physical-exam",
        json={"exam_code": "abd.palpation.rebound"},
    )
    hint_response = client.post(f"/api/sessions/{session_id}/hint")

    assert create_response.status_code == 200
    assert "active_skill_context" not in create_response.json()
    assert initial_skill_id == "skill_ht_migration"
    assert exam_response.status_code == 200
    assert exam_response.json()["stage"] == "physical_exam"
    assert "active_skill_context" not in exam_response.json()
    refreshed_session = osce_session_service._get_session(session_id)
    assert refreshed_session is not None
    assert refreshed_session.active_skill_context["selected_skills"][0]["skill_id"] == "skill_pe_tenderness"
    assert hint_response.status_code == 200
    assert "右下腹压痛查体训练" in hint_response.json()["hint"]
    assert "selected_skill_ids" not in hint_response.json()["agent_turn_memory"][-1]
    assert refreshed_session.agent_turn_memory[-1]["selected_skill_ids"] == ["skill_pe_tenderness"]


def test_create_session_does_not_inject_enabled_training_skill_for_unrelated_case(tmp_path) -> None:
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_abdominal_pattern",
            "trigger_item_id": "training_pattern_dxd_crohn_dxd_gastroenteritis",
            "trigger_item_ids": ["dxd_crohn", "dxd_gastroenteritis"],
            "case_ids": ["appendicitis_001"],
            "title": "急腹症鉴别诊断与全面评估逻辑训练",
            "description": "急腹症鉴别诊断反复遗漏。",
            "suggested_strategy": "只在腹痛病例中提示学生系统性排除急腹症相关鉴别诊断。",
            "source_report_count": 7,
            "support_count": 7,
            "related_recommendations": ["rubric:appendicitis_001_rubric.item.dxd_crohn"],
            "review": {"status": "approved", "regression_passed": True},
        }
    )

    create_response = client.post(
        "/api/sessions",
        json={"case_id": "acs_001", "student_id": "student_demo"},
    )

    assert create_response.status_code == 200
    assert "evolution_candidates" not in create_response.json()
    created_session = osce_session_service._get_session(create_response.json()["session_id"])
    assert created_session is not None
    assert created_session.evolution_candidates == []


def test_create_session_filters_enabled_skill_with_case_incompatible_teaching_content(tmp_path) -> None:
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.training_event_store = event_store
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service._sessions.clear()
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_training_pattern_dxd_crohn_dxd_ectopic_dxd_urolith",
            "trigger_item_id": "training_pattern_dxd_crohn_dxd_ectopic_dxd_urolith",
            "trigger_item_ids": ["dxd_crohn", "dxd_ectopic", "dxd_urolith", "rs_exclude"],
            "case_ids": ["appendicitis_001"],
            "stage_scope": ["case_intro"],
            "applies_when": {
                "case_ids": ["appendicitis_001"],
                "stage_scope": ["case_intro"],
                "trigger_item_ids": ["dxd_crohn", "dxd_ectopic", "dxd_urolith", "rs_exclude"],
                "current_missing_evidence": ["dxd_crohn", "dxd_urolith", "rs_exclude"],
                "min_support_count": 3,
            },
            "title": "急腹症鉴别诊断与全面评估逻辑训练",
            "description": "急腹症鉴别诊断反复遗漏，需补充妇科、泌尿及肠道系统排除。",
            "suggested_strategy": "面对急性腹痛患者时，请系统排除妇科、异位妊娠、泌尿科及肠道相关疾病。",
            "source_report_count": 7,
            "support_count": 7,
            "related_recommendations": ["rubric:appendicitis_001_rubric.item.rs_exclude"],
            "review": {"status": "approved", "regression_passed": True},
        }
    )

    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]

    assert create_response.status_code == 200
    assert "evolution_candidates" not in create_response.json()
    created_session = osce_session_service._get_session(session_id)
    assert created_session is not None
    assert created_session.evolution_candidates == []
    assert [event["event_type"] for event in business_events(event_store.list_session_events(session_id))] == [
        "session_created"
    ]


def test_create_session_respects_enabled_training_skill_stage_scope(tmp_path) -> None:
    event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.training_event_store = event_store
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service._sessions.clear()
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_feedback_review",
            "trigger_item_id": "training_pattern_reasoning_core",
            "trigger_item_ids": ["reasoning_core"],
            "case_ids": ["appendicitis_001"],
            "title": "报告复盘阶段提示",
            "description": "仅在报告复盘阶段提示学生复盘推理链。",
            "suggested_strategy": "报告生成后再复盘推理链，不在开局直接注入。",
            "source_report_count": 2,
            "support_count": 2,
            "stage_scope": ["feedback_review"],
            "applies_when": {
                "case_ids": ["appendicitis_001"],
                "stage_scope": ["feedback_review"],
                "trigger_item_ids": ["reasoning_core"],
                "current_missing_evidence": ["reasoning_core"],
                "min_support_count": 2,
            },
            "review": {"status": "approved", "regression_passed": True},
        }
    )

    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]

    assert create_response.status_code == 200
    assert "evolution_candidates" not in create_response.json()
    created_session = osce_session_service._get_session(session_id)
    assert created_session is not None
    assert created_session.evolution_candidates == []
    assert [event["event_type"] for event in business_events(event_store.list_session_events(session_id))] == [
        "session_created"
    ]


def test_osce_session_returns_training_progress_map() -> None:
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )

    assert create_response.status_code == 200
    created = create_response.json()
    session_id = created["session_id"]
    progress = created["training_progress"]
    assert created["payload_schema_version"] == "student_session.v2"
    assert progress["history"] == {
        "total": 10,
        "covered": 0,
    }
    assert progress["physical_exam"] == {
        "total": 7,
        "requested": 0,
    }
    assert progress["auxiliary_test"] == {
        "total": 5,
        "requested": 0,
    }
    assert progress["reasoning"] == {
        "collected_evidence_count": 0,
        "ready_for_hypothesis": False,
    }
    assert progress["revealed_items"] == {
        "history": [],
        "physical_exam": [],
        "auxiliary_test": [],
        "reasoning": [],
    }
    assert progress["next_focus"] == "先用开放式问题明确起病、部位、性质、程度和伴随症状。"
    assert created["collected_procedure_results"] == {
        "physical_exams": [],
        "auxiliary_tests": [],
    }
    assert_student_payload_hides_unrevealed_case_evidence(created)
    assert_training_progress_hides_diagnosis(progress)

    message_response = client.post(
        f"/api/sessions/{session_id}/message",
        json={"message": "什么时候开始疼的？"},
    )

    assert message_response.status_code == 200
    message_progress = message_response.json()["training_progress"]
    assert_training_progress_hides_diagnosis(message_progress)
    history_progress = message_progress["history"]
    assert history_progress["covered"] == 1
    assert message_progress["revealed_items"]["history"] == [
        {
            "id": "hf_01",
            "label": "24 小时前开始，最初是上腹部隐痛。",
            "topic": "现病史",
            "slot": "onset",
        }
    ]
    assert_student_payload_hides_unrevealed_case_evidence(
        message_response.json(),
        revealed_fact_ids={"appendicitis_001.hf_01"},
    )

    exam_response = client.post(
        f"/api/sessions/{session_id}/physical-exam",
        json={"exam_code": "abd.palpation.rebound"},
    )

    assert exam_response.status_code == 200
    exam_progress = exam_response.json()["training_progress"]
    assert_training_progress_hides_diagnosis(exam_progress)
    assert exam_progress["physical_exam"]["requested"] == 1
    assert exam_progress["revealed_items"]["physical_exam"] == [
        {"id": "abd.palpation.rebound", "label": "反跳痛（Blumberg 征）"}
    ]
    assert exam_response.json()["collected_procedure_results"]["physical_exams"] == [
        {
            "exam_code": "abd.palpation.rebound",
            "exam_name_cn": "反跳痛（Blumberg 征）",
            "result": "右下腹反跳痛阳性。",
        }
    ]
    assert exam_progress["next_focus"] == "你已经获得部分病史和查体信息，可以申请能验证当前假设的辅助检查。"
    assert_student_payload_hides_unrevealed_case_evidence(
        exam_response.json(),
        revealed_fact_ids={"appendicitis_001.hf_01"},
        requested_exam_codes={"abd.palpation.rebound"},
    )

    test_response = client.post(
        f"/api/sessions/{session_id}/auxiliary-test",
        json={"test_code": "lab.cbc"},
    )

    assert test_response.status_code == 200
    test_progress = test_response.json()["training_progress"]
    assert_training_progress_hides_diagnosis(test_progress)
    assert test_progress["auxiliary_test"]["requested"] == 1
    assert test_progress["revealed_items"]["auxiliary_test"] == [
        {"id": "lab.cbc", "label": "血常规"}
    ]
    assert test_response.json()["collected_procedure_results"]["auxiliary_tests"] == [
        {
            "test_code": "lab.cbc",
            "test_name_cn": "血常规",
            "result": "白细胞 14.2×10^9/L，中性粒细胞比例 85%。",
        }
    ]
    assert test_progress["reasoning"]["ready_for_hypothesis"] is True
    assert test_progress["next_focus"] == "已有病史、查体和辅助检查证据，先记录一个诊断假设，再继续补齐关键证据。"
    assert_student_payload_hides_unrevealed_case_evidence(
        test_response.json(),
        revealed_fact_ids={"appendicitis_001.hf_01"},
        requested_exam_codes={"abd.palpation.rebound"},
        requested_test_codes={"lab.cbc"},
    )


@pytest.mark.parametrize("training_difficulty", ["intermediate", "advanced"])
def test_non_beginner_session_does_not_expose_case_specific_quick_options(
    training_difficulty: str,
) -> None:
    response = client.post(
        "/api/sessions",
        json={
            "case_id": "appendicitis_001",
            "training_difficulty": training_difficulty,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["training_difficulty"] == training_difficulty
    assert payload["physical_exam_options"] == []
    assert payload["auxiliary_test_options"] == []
    assert_student_payload_hides_unrevealed_case_evidence(payload)


def test_session_resume_restores_only_collected_procedure_results() -> None:
    created = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001"},
    ).json()
    session_id = created["session_id"]

    exam_response = client.post(
        f"/api/sessions/{session_id}/physical-exam",
        json={"exam_code": "abd.palpation.rebound"},
    )
    assert exam_response.status_code == 200

    resumed_response = client.get(f"/api/sessions/{session_id}")
    assert resumed_response.status_code == 200
    resumed = resumed_response.json()
    assert resumed["collected_procedure_results"] == {
        "physical_exams": [
            {
                "exam_code": "abd.palpation.rebound",
                "exam_name_cn": "反跳痛（Blumberg 征）",
                "result": "右下腹反跳痛阳性。",
            }
        ],
        "auxiliary_tests": [],
    }
    assert_student_payload_hides_unrevealed_case_evidence(
        resumed,
        requested_exam_codes={"abd.palpation.rebound"},
    )


def test_osce_session_minimal_training_loop(authenticated_user: dict[str, str]) -> None:
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )

    assert create_response.status_code == 200
    created = create_response.json()
    session_id = created["session_id"]
    assert created["case_id"] == "appendicitis_001"
    assert created["student_id"] == authenticated_user["user_id"]
    assert created["stage"] == "case_intro"
    assert created["case_title"] == "右下腹痛教学病例"
    assert created["chief_complaint"] == "转移性右下腹痛 24 小时，伴恶心、低热"
    assert created["diagnosis_draft"] == {
        "diagnosis": "",
        "reasoning": "",
    }
    assert created["physical_exam_options"] == [
        {"exam_code": "vital.temperature", "exam_name_cn": "体温"},
        {"exam_code": "abd.inspection", "exam_name_cn": "腹部视诊"},
        {"exam_code": "abd.palpation.tenderness", "exam_name_cn": "McBurney 点压痛"},
        {"exam_code": "abd.palpation.rebound", "exam_name_cn": "反跳痛（Blumberg 征）"},
        {"exam_code": "abd.palpation.guarding", "exam_name_cn": "肌紧张"},
        {"exam_code": "abd.special.rovsing", "exam_name_cn": "Rovsing 征"},
        {"exam_code": "abd.special.psoas", "exam_name_cn": "腰大肌征"},
    ]
    assert created["auxiliary_test_options"] == [
        {
            "test_code": "lab.cbc",
            "test_name_cn": "血常规",
            "category": "实验室",
            "invasiveness": "微创",
            "cost_hint": "基础",
        },
        {
            "test_code": "lab.crp",
            "test_name_cn": "C 反应蛋白",
            "category": "实验室",
            "invasiveness": "微创",
            "cost_hint": "基础",
        },
        {
            "test_code": "img.abd_us",
            "test_name_cn": "腹部超声",
            "category": "影像",
            "invasiveness": "无创",
            "cost_hint": "基础",
        },
        {
            "test_code": "lab.urinalysis",
            "test_name_cn": "尿常规",
            "category": "实验室",
            "invasiveness": "无创",
            "cost_hint": "基础",
        },
        {
            "test_code": "img.abd_ct",
            "test_name_cn": "腹部 CT",
            "category": "影像",
            "invasiveness": "无创",
            "cost_hint": "中等",
        },
    ]
    assert_student_payload_hides_unrevealed_case_evidence(created)

    procedure_catalog_response = client.get("/api/procedure-catalog")
    procedure_catalog = procedure_catalog_response.json()

    assert procedure_catalog_response.status_code == 200
    assert procedure_catalog["mode"] == "intermediate_catalog"
    rebound_catalog_item = next(
        item for item in procedure_catalog["physical_exams"] if item["exam_code"] == "abd.palpation.rebound"
    )
    assert rebound_catalog_item["exam_name_cn"] == "反跳痛（Blumberg 征）"
    assert rebound_catalog_item["category"] == "腹部查体"
    assert "result" not in rebound_catalog_item
    assert any(item["exam_code"] == "vital.blood_pressure" for item in procedure_catalog["physical_exams"])
    assert any(item["test_code"] == "ecg.st_segment" for item in procedure_catalog["auxiliary_tests"])

    message_response = client.post(
        f"/api/sessions/{session_id}/message",
        json={"message": "什么时候开始疼的？"},
    )

    assert message_response.status_code == 200
    message_payload = message_response.json()
    assert "24 小时前开始" in message_payload["reply"]
    assert "急性阑尾炎" not in message_payload["reply"]
    assert "appendicitis_001.hf_01" in message_payload["revealed_facts"]

    exam_response = client.post(
        f"/api/sessions/{session_id}/physical-exam",
        json={"exam_code": "abd.palpation.rebound"},
    )

    assert exam_response.status_code == 200
    exam_payload = exam_response.json()
    assert exam_payload["exam_code"] == "abd.palpation.rebound"
    assert exam_payload["result"] == "右下腹反跳痛阳性。"
    assert "abd.palpation.rebound" in exam_payload["requested_exams"]

    test_response = client.post(
        f"/api/sessions/{session_id}/auxiliary-test",
        json={"test_code": "lab.cbc"},
    )

    assert test_response.status_code == 200
    test_payload = test_response.json()
    assert test_payload["test_code"] == "lab.cbc"
    assert test_payload["result"] == "白细胞 14.2×10^9/L，中性粒细胞比例 85%。"
    assert "lab.cbc" in test_payload["requested_tests"]

    batch_exam_response = client.post(
        f"/api/sessions/{session_id}/physical-exams",
        json={"exam_codes": ["abd.palpation.rebound", "vital.blood_pressure"]},
    )
    batch_exam_payload = batch_exam_response.json()

    assert batch_exam_response.status_code == 200
    assert [item["exam_code"] for item in batch_exam_payload["exam_results"]] == [
        "abd.palpation.rebound",
        "vital.blood_pressure",
    ]
    assert batch_exam_payload["exam_results"][0]["availability_status"] == "case_configured"
    assert batch_exam_payload["exam_results"][0]["result"] == "右下腹反跳痛阳性。"
    assert batch_exam_payload["exam_results"][1]["availability_status"] == "not_available_for_case"
    assert batch_exam_payload["exam_results"][1]["exam_name_cn"] == "血压"
    assert batch_exam_payload["exam_results"][1]["result"] == "该项目已记录，但本训练站点未提供该查体结果。"
    assert "vital.blood_pressure" in batch_exam_payload["requested_exams"]

    batch_test_response = client.post(
        f"/api/sessions/{session_id}/auxiliary-tests",
        json={"test_codes": ["lab.cbc", "ecg.st_segment"]},
    )
    batch_test_payload = batch_test_response.json()

    assert batch_test_response.status_code == 200
    assert [item["test_code"] for item in batch_test_payload["test_results"]] == ["lab.cbc", "ecg.st_segment"]
    assert batch_test_payload["test_results"][0]["availability_status"] == "case_configured"
    assert batch_test_payload["test_results"][1]["availability_status"] == "not_available_for_case"
    assert batch_test_payload["test_results"][1]["test_name_cn"] == "心电图"
    assert batch_test_payload["test_results"][1]["result"] == "该项目已记录，但本训练站点未提供该辅助检查结果。"
    assert "ecg.st_segment" in batch_test_payload["requested_tests"]

    free_text_procedure_response = client.post(
        f"/api/sessions/{session_id}/procedure-request",
        json={"request_text": "我想查反跳痛和血常规，再看看心电图和胃镜"},
    )
    assert free_text_procedure_response.status_code == 409
    assert free_text_procedure_response.json() == {
        "detail": "free-text procedure requests require advanced training"
    }

    submit_response = client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
    )

    assert submit_response.status_code == 200
    submit_payload = submit_response.json()
    assert submit_payload["stage"] == "diagnosis_submission"
    assert submit_payload["final_submission"] == {
        "diagnosis": "急性阑尾炎",
        "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。",
    }

    state_response = client.get(f"/api/sessions/{session_id}")

    assert state_response.status_code == 200
    state_payload = state_response.json()
    assert state_payload["stage"] == "diagnosis_submission"
    assert state_payload["revealed_facts"] == ["appendicitis_001.hf_01"]
    assert state_payload["requested_exams"] == ["abd.palpation.rebound", "vital.blood_pressure"]
    assert state_payload["requested_tests"] == ["lab.cbc", "ecg.st_segment"]
    internal_session = osce_session_service._get_session(session_id)
    assert internal_session is not None
    expected_action_timeline = [
        {
            "turn_index": 1,
            "action_type": "history_fact_revealed",
            "source_id": "appendicitis_001.hf_01",
            "label": "追问起病时间",
        },
        {
            "turn_index": 2,
            "action_type": "physical_exam_requested",
            "source_id": "abd.palpation.rebound",
            "label": "反跳痛（Blumberg 征）",
        },
        {
            "turn_index": 3,
            "action_type": "auxiliary_test_requested",
            "source_id": "lab.cbc",
            "label": "血常规",
        },
        {
            "turn_index": 4,
            "action_type": "physical_exam_requested",
            "source_id": "vital.blood_pressure",
            "label": "血压",
        },
        {
            "turn_index": 5,
            "action_type": "auxiliary_test_requested",
            "source_id": "ecg.st_segment",
            "label": "心电图",
        },
        {
            "turn_index": 6,
            "action_type": "diagnosis_submitted",
            "source_id": "final_submission",
            "label": "提交诊断",
        },
    ]
    assert [
        {
            "turn_index": item["turn_index"],
            "action_type": item["action_type"],
            "source_id": item["source_id"],
            "label": item["label"],
        }
        for item in internal_session.action_timeline
    ] == expected_action_timeline
    assert all(
        isinstance(item.get("message_turn_index"), int) and item["message_turn_index"] >= 1
        for item in internal_session.action_timeline
    )

    report_response = client.post(f"/api/sessions/{session_id}/report/generate")

    assert report_response.status_code == 200
    report_payload = report_response.json()
    assert report_payload["session_id"] == session_id
    assert report_payload["case_id"] == "appendicitis_001"
    assert report_payload["total_score"] == 22
    assert report_payload["dimension_scores"] == {
        "history_taking": 2,
        "physical_exam": 4,
        "auxiliary_test": 3,
        "main_diagnosis": 10,
        "differential_diagnosis": 0,
        "reasoning": 3,
        "narrative_medicine": 0,
        "communication_skill": 0,
        "medical_ethics": 0,
        "relationship_building": 0,
    }
    assert report_payload["rubric_scores"]["ht_onset"]["score"] == 2
    assert report_payload["rubric_scores"]["ht_migration"]["score"] == 0
    assert report_payload["rubric_scores"]["pe_rebound"]["score"] == 4
    assert report_payload["rubric_scores"]["ax_cbc"]["score"] == 3
    assert report_payload["rubric_scores"]["dx_main"]["score"] == 10
    assert report_payload["rubric_scores"]["rs_support"]["score"] == 3
    assert "ht_migration" in report_payload["missed_items"]
    assert report_payload["procedure_simulation_audit_items"] == []
    assert "ecg.st_segment" not in report_payload["source_references"]
    assert report_payload["strengths"] == [
        "追问起病时间：已完成。",
        "检查反跳痛：已完成。",
        "申请血常规：已完成。",
        "主要诊断命中急性阑尾炎：已完成。",
        "推理表达覆盖典型阑尾炎支持证据（转移性痛、压痛反跳痛、WBC/CRP 升高、超声）：已完成。",
    ]
    assert report_payload["reasoning_errors"] == [
        "提出输尿管结石并说明排除依据：评分轨迹未找到足够证据。",
        "提出克罗恩病并说明排除依据：评分轨迹未找到足够证据。",
        "提出急性胃肠炎并说明排除依据：评分轨迹未找到足够证据。",
        "推理表达覆盖典型阑尾炎支持证据（转移性痛、压痛反跳痛、WBC/CRP 升高、超声）：评分轨迹未找到足够证据。",
        "推理表达覆盖关键排除依据：评分轨迹未找到足够证据。",
    ]
    expected_recommendations = [
        "下一轮训练重点：追问疼痛部位及转移特征。",
        "下一轮训练重点：追问疼痛性质。",
        "下一轮训练重点：追问疼痛程度。",
        "下一轮训练重点：追问恶心呕吐腹泻。",
        "下一轮训练重点：追问发热。",
        "下一轮训练重点：追问既往病史。",
        "下一轮训练重点：追问过敏史。",
        "下一轮训练重点：询问患者想法担忧与期望（ICE）。",
        "下一轮训练重点：测量体温。",
        "下一轮训练重点：腹部视诊。",
        "下一轮训练重点：检查腹部压痛。",
        "下一轮训练重点：申请 CRP。",
        "下一轮训练重点：申请腹部超声。",
        "下一轮训练重点：合理申请尿常规排除输尿管结石。",
        "下一轮训练重点：提出输尿管结石并说明排除依据。",
        "下一轮训练重点：提出克罗恩病并说明排除依据。",
        "下一轮训练重点：提出急性胃肠炎并说明排除依据。",
        "下一轮训练重点：推理表达覆盖典型阑尾炎支持证据（转移性痛、压痛反跳痛、WBC/CRP 升高、超声）。",
        "下一轮训练重点：推理表达覆盖关键排除依据。",
    ]
    for expected_recommendation in expected_recommendations:
        assert expected_recommendation in report_payload["next_recommendations"]
    assert "下一轮训练重点：自我介绍并说明问诊目的。" in report_payload["next_recommendations"]
    assert "下一轮训练重点：查体或检查前说明目的并征得同意。" in report_payload["next_recommendations"]
    assert "下一轮训练重点：患者表达担忧后给予共情回应。" in report_payload["next_recommendations"]
    assert {
        "case:appendicitis_001",
        "source:fareez_osce_2022",
        "rubric:appendicitis_001_rubric.item.ht_migration",
        "rubric:appendicitis_001_rubric.item.rs_support",
        "rubric:appendicitis_001_rubric.item.comm_intro_purpose",
        "rubric:appendicitis_001_rubric.item.eth_exam_consent",
        "rubric:appendicitis_001_rubric.item.rel_empathy_response",
        "rubric:appendicitis_001_rubric.item.ht_onset",
        "rubric:appendicitis_001_rubric.item.pe_rebound",
        "rubric:appendicitis_001_rubric.item.ax_cbc",
        "rubric:appendicitis_001_rubric.item.dx_main",
        "evidence:appendicitis_001.hf_01",
        "evidence:abd.palpation.rebound",
        "evidence:lab.cbc",
        "evidence:急性阑尾炎",
    } <= set(report_payload["source_references"])
    evidence_graph_summary = report_payload["evidence_graph_summary"]
    assert evidence_graph_summary["case_id"] == "appendicitis_001"
    assert evidence_graph_summary["total_evidence_node_count"] == 5
    assert evidence_graph_summary["covered_evidence_node_count"] == 2
    assert evidence_graph_summary["missing_evidence_node_count"] == 3
    assert evidence_graph_summary["coverage_ratio"] == 0.4
    assert [node["node_id"] for node in evidence_graph_summary["covered_evidence_nodes"]] == [
        "ev_peritoneal_signs",
        "ev_wbc_crp_elevated",
    ]
    assert [node["node_id"] for node in evidence_graph_summary["missing_evidence_nodes"]] == [
        "ev_migratory_rlq_pain",
        "ev_ultrasound_appendix",
        "nf_urinalysis_negative",
    ]
    assert [edge["from_node"] for edge in evidence_graph_summary["covered_edges"]] == [
        "ev_peritoneal_signs",
        "ev_wbc_crp_elevated",
    ]
    assert [edge["from_node"] for edge in evidence_graph_summary["missing_edges"]] == [
        "ev_migratory_rlq_pain",
        "ev_ultrasound_appendix",
        "nf_urinalysis_negative",
    ]
    assert report_payload["feedback_summary"] == "已根据评分轨迹生成教学反馈，内容仅用于 OSCE 训练复盘。"
    report_text = str(report_payload)
    for forbidden_term in ["用药剂量", "治疗方案", "手术方案", "处置建议"]:
        assert forbidden_term not in report_text


def test_advanced_procedure_request_does_not_fabricate_unmatched_patient_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProcedureRequestRouter:
        calls: list[object] = []

        def __call__(self, request: object) -> dict[str, object]:
            self.calls.append(request)
            assert getattr(request, "unmatched_requests") == ["身高体重姓名"]
            return {
                "routed_items": [
                    {
                        "raw_text": "身高体重姓名",
                        "decision": "generate",
                        "kind": "patient_profile",
                        "name_cn": "身高体重姓名",
                        "rationale": "基础身份与体格信息可作为高级训练补充结果，不进入评分。",
                        "safety_issues": [],
                    }
                ]
            }

    class UnexpectedProcedureResultSimulator:
        def __call__(self, request: object) -> dict[str, object]:
            raise AssertionError(f"unconfigured patient facts must not be simulated: {request}")

    fake_router = FakeProcedureRequestRouter()
    monkeypatch.setattr(osce_session_service, "procedure_request_router", fake_router, raising=False)
    monkeypatch.setattr(
        osce_session_service,
        "procedure_result_simulator",
        UnexpectedProcedureResultSimulator(),
        raising=False,
    )

    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "training_difficulty": "advanced"},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]

    response = client.post(
        f"/api/sessions/{session_id}/procedure-request",
        json={"request_text": "身高体重姓名"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["standardized_request"]["unmatched_requests"] == ["身高体重姓名"]
    assert payload["standardized_request"]["routed_unmatched_requests"] == [
        {
            "raw_text": "身高体重姓名",
            "decision": "block",
            "kind": "patient_profile",
            "name_cn": "身高体重姓名",
            "rationale": "病例未配置该患者信息，训练中不得编造姓名、身高、体重或其他患者事实。",
            "safety_issues": ["unconfigured_patient_fact"],
        }
    ]
    assert payload["standardized_request"]["generated_result_policy"] == "disabled"
    assert payload["matched_procedure_results"] == []
    assert "procedure_simulation_audit_items" not in payload
    assert "175 cm" not in str(payload)
    assert "68 kg" not in str(payload)
    assert len(fake_router.calls) == 1


def test_advanced_unconfigured_procedure_returns_unavailable_without_invoking_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnexpectedAgent:
        def __call__(self, request: object) -> dict[str, object]:
            raise AssertionError(f"unconfigured procedures must not invoke an LLM: {request}")

    monkeypatch.setattr(osce_session_service, "procedure_result_simulator", UnexpectedAgent(), raising=False)
    monkeypatch.setattr(osce_session_service, "procedure_result_approval_agent", UnexpectedAgent(), raising=False)

    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "training_difficulty": "advanced"},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]

    procedure_response = client.post(
        f"/api/sessions/{session_id}/procedure-request",
        json={"request_text": "我想查心电图"},
    )

    assert procedure_response.status_code == 200
    procedure_payload = procedure_response.json()
    unavailable_result = procedure_payload["matched_procedure_results"][0]
    assert unavailable_result["availability_status"] == "not_available_for_case"
    assert unavailable_result["generated_by_ai"] is False
    assert unavailable_result["approval_status"] == "not_required"
    assert unavailable_result["scoring_eligible"] is False
    assert procedure_payload["standardized_request"]["generated_result_policy"] == "disabled"
    assert "procedure_simulation_audit_items" not in procedure_payload


@pytest.mark.parametrize("training_difficulty", ["beginner", "intermediate"])
def test_procedure_request_rejects_non_advanced_session(
    training_difficulty: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnexpectedRouter:
        def __call__(self, request: object) -> dict[str, object]:
            raise AssertionError(f"non-advanced request must stop before routing: {request}")

    monkeypatch.setattr(osce_session_service, "procedure_request_router", UnexpectedRouter(), raising=False)
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "training_difficulty": training_difficulty},
    )
    session_id = create_response.json()["session_id"]

    response = client.post(
        f"/api/sessions/{session_id}/procedure-request",
        json={"request_text": "我想查心电图"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "free-text procedure requests require advanced training"}


def test_osce_session_records_diagnosis_hypothesis_before_final_submission(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    osce_session_service.training_event_store = TrainingEventStore(database_path)
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]
    client.post(f"/api/sessions/{session_id}/message", json={"message": "哪里最疼？"})

    hypothesis_response = client.post(
        f"/api/sessions/{session_id}/hypotheses",
        json={"hypothesis": "急性阑尾炎"},
    )

    assert hypothesis_response.status_code == 200
    payload = hypothesis_response.json()
    assert payload["stage"] == "history_taking"
    assert payload["student_hypotheses"] == ["急性阑尾炎"]
    assert payload["final_submission"] is None
    assert "rubric_scores" not in payload
    internal_session = osce_session_service._get_session(session_id)
    assert internal_session is not None
    assert internal_session.rubric_scores == {}

    events = TrainingEventStore(database_path).list_session_events(session_id)
    assert [event["event_type"] for event in business_events(events)] == [
        "session_created",
        "history_message",
        "hypothesis_recorded",
    ]
    assert find_event(events, "hypothesis_recorded")["payload"] == {"hypothesis": "急性阑尾炎"}


def test_osce_session_returns_socratic_hint_without_revealing_diagnosis(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    osce_session_service.training_event_store = TrainingEventStore(database_path)
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]
    client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})

    hint_response = client.post(f"/api/sessions/{session_id}/hint")

    assert hint_response.status_code == 200
    payload = hint_response.json()
    assert payload["stage"] == "history_taking"
    assert payload["hint"] == "病史线索还偏少，先继续补齐起病、部位变化、性质、程度和伴随症状，再决定查体。"
    assert payload["training_progress"]["next_focus"] == "已获得部分病史，下一步选择关键查体来验证当前线索。"
    assert payload["messages"][-1] == {"role": "coach", "content": payload["hint"]}
    assert payload["final_submission"] is None
    assert "rubric_scores" not in payload
    for forbidden_term in ["急性阑尾炎", "阑尾炎", "手术", "治疗方案"]:
        assert forbidden_term not in payload["hint"]

    events = TrainingEventStore(database_path).list_session_events(session_id)
    assert [event["event_type"] for event in business_events(events)] == [
        "session_created",
        "history_message",
        "hint_requested",
    ]
    hint_event_payload = find_event(events, "hint_requested")["payload"]
    internal_session = osce_session_service._get_session(session_id)
    assert internal_session is not None
    assert hint_event_payload == {
        "hint": payload["hint"],
        "agent_turn": internal_session.agent_turn_memory[-1],
    }
    assert "agent_path" not in payload["agent_turn_memory"][-1]
    assert "current_intent" not in hint_event_payload["agent_turn"]
    assert hint_event_payload["agent_turn"]["current_intents"] == ["socratic_hint"]
    assert hint_event_payload["agent_turn"]["turn_policy"] == "teaching_hint"
    assert hint_event_payload["agent_turn"]["agent_path"] == ["socratic_hint_node", "coach_agent"]


def test_osce_session_uses_enabled_training_skill_when_requesting_socratic_hint(tmp_path) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    osce_session_service.training_event_store = TrainingEventStore(database_path)
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "case_ids": ["appendicitis_001"],
            "title": "临床推理链纠偏提示",
            "description": "推理链反复遗漏。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "source_report_count": 3,
            "support_count": 2,
            "review": {"status": "approved", "regression_passed": True},
        }
    )
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]
    client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})

    hint_response = client.post(f"/api/sessions/{session_id}/hint")

    assert hint_response.status_code == 200
    payload = hint_response.json()
    assert payload["hint"] == "本轮训练重点是临床推理链纠偏提示。提交诊断前，请按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。"
    assert payload["messages"][-1] == {"role": "coach", "content": payload["hint"]}
    assert payload["final_submission"] is None
    assert "rubric_scores" not in payload
    for forbidden_term in ["急性阑尾炎", "阑尾炎", "手术", "治疗方案"]:
        assert forbidden_term not in payload["hint"]

    events = TrainingEventStore(database_path).list_session_events(session_id)
    assert [event["event_type"] for event in business_events(events)] == [
        "session_created",
        "training_skill_applied",
        "history_message",
        "hint_requested",
    ]
    hint_event_payload = find_event(events, "hint_requested")["payload"]
    internal_session = osce_session_service._get_session(session_id)
    assert internal_session is not None
    assert hint_event_payload == {
        "hint": payload["hint"],
        "agent_turn": internal_session.agent_turn_memory[-1],
    }
    assert "agent_path" not in payload["agent_turn_memory"][-1]
    assert "current_intent" not in hint_event_payload["agent_turn"]
    assert hint_event_payload["agent_turn"]["current_intents"] == ["socratic_hint"]
    assert hint_event_payload["agent_turn"]["turn_policy"] == "teaching_hint"
    assert hint_event_payload["agent_turn"]["agent_path"] == ["socratic_hint_node", "skill_router", "coach_agent"]


def test_session_report_can_be_read_after_session_memory_is_cleared(tmp_path) -> None:
    database_path = tmp_path / "reports.sqlite3"
    osce_session_service.report_store = ReportStore(database_path)
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]

    client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})
    client.post(f"/api/sessions/{session_id}/physical-exam", json={"exam_code": "abd.palpation.rebound"})
    client.post(f"/api/sessions/{session_id}/auxiliary-test", json={"test_code": "lab.cbc"})
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
    )
    generated_report = client.post(f"/api/sessions/{session_id}/report/generate").json()

    osce_session_service._sessions.clear()
    loaded_response = client.get(f"/api/sessions/{session_id}/report")

    assert loaded_response.status_code == 200
    assert loaded_response.json() == generated_report


def test_completed_training_generates_personal_skill_and_ai_reflection_for_next_session(
    tmp_path,
    authenticated_user: dict[str, str],
) -> None:
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_candidate_store = TrainingSkillCandidateStore(
        tmp_path / "training_skill_candidates.sqlite3"
    )
    osce_session_service._sessions.clear()

    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})
    client.post(f"/api/sessions/{session_id}/physical-exam", json={"exam_code": "abd.palpation.rebound"})
    client.post(f"/api/sessions/{session_id}/auxiliary-test", json={"test_code": "lab.cbc"})
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
    )

    base_report_response = client.post(f"/api/sessions/{session_id}/report/generate")
    enrich_response = client.post(f"/api/sessions/{session_id}/report/enrich")
    report_response = client.get(f"/api/sessions/{session_id}/report")
    report = report_response.json()
    personal_candidate = report["personal_skill_candidate"]

    assert base_report_response.status_code == 200
    assert enrich_response.status_code == 202
    assert report_response.status_code == 200
    assert report["ai_reflection_review"]["status"] == "generated"
    assert report["ai_reflection_review"]["source_references"]
    reflection = report["ai_reflection_review"]
    assert reflection["generated_by"] in {"teacher_reflection_agent", "teacher_agent_deterministic"}
    assert reflection["teaching_prompt_version"] == "teacher_reflection_v3"
    if reflection["generated_by"] == "teacher_agent_deterministic":
        assert reflection["teacher_analysis_context"]["analysis_mode"] == "deterministic_baseline"
    assert reflection["reasoning_trace_summary"]["dominant_patterns"]
    assert "证据链" in reflection["overall_comment"]
    assert reflection["strengths_review"]
    assert reflection["reasoning_chain_review"]
    assert reflection["next_practice_plan"]
    assert 1 <= len(reflection["major_issues"]) <= 4
    first_issue = reflection["major_issues"][0]
    assert first_issue["title"]
    assert first_issue["observed_behavior"]
    assert first_issue["why_it_matters"]
    assert first_issue["correct_approach"]
    assert first_issue["next_action"]
    assert first_issue["linked_items"]
    assert "ht_" not in first_issue["title"]
    assert "rubric" not in first_issue["observed_behavior"]
    reflection_text = json.dumps(reflection, ensure_ascii=False)
    assert "37.8" not in reflection_text
    assert "CRP 48" not in reflection_text
    assert "管状低回声" not in reflection_text
    assert "测量体温、体温" not in reflection_text
    assert "右下腹痛教学病例" in reflection["summary"]
    assert "老师视角" in reflection["teacher_feedback"]
    assert "为什么" in reflection["teacher_feedback"]
    assert "病例评估链条" in reflection["teacher_feedback"]
    assert "病史补全" in reflection["next_focus"]
    assert "下一轮 Coach" not in reflection["next_focus"]
    assert "AI 复盘" not in reflection["safety_note"]
    assert personal_candidate["scope"] == "personal"
    assert personal_candidate["owner_student_id"] == authenticated_user["user_id"]
    assert personal_candidate["source_session_id"] == session_id
    assert personal_candidate["review"]["status"] == "approved"
    assert personal_candidate["approval_agent_review"]["agent_id"] == "skill_auto_approval_agent"
    assert personal_candidate["description"]
    assert personal_candidate["suggested_strategy"]
    assert len(personal_candidate["approval_dialogue"]) >= 1
    assert personal_candidate["web_check_status"] == "not_configured"
    assert personal_candidate["external_evidence_checks"] == []
    assert personal_candidate["rag_evidence_items"]

    candidate_id = personal_candidate["candidate_id"]
    skill_id = personal_candidate["skill_id"]
    stored_candidate = osce_session_service.training_skill_candidate_store.get_candidate(candidate_id)
    enabled_skill = osce_session_service.training_skill_store.get_skill(skill_id)
    assert stored_candidate is not None
    assert stored_candidate["candidate_id"] == candidate_id
    assert enabled_skill is not None
    assert enabled_skill["scope"] == "personal"
    assert enabled_skill["owner_student_id"] == authenticated_user["user_id"]

    next_session_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    next_session = next_session_response.json()
    next_events = TrainingEventStore(tmp_path / "training_events.sqlite3").list_session_events(
        next_session["session_id"]
    )
    skill_events = [event for event in next_events if event["event_type"] == "training_skill_applied"]

    assert next_session_response.status_code == 200
    assert "evolution_candidates" not in next_session
    next_internal_session = osce_session_service._get_session(next_session["session_id"])
    assert next_internal_session is not None
    assert next_internal_session.evolution_candidates == [
        f"{enabled_skill['title']}：{enabled_skill['suggested_strategy']}"
    ]
    assert skill_events[0]["payload"]["skill_id"] == skill_id
    assert skill_events[0]["payload"]["scope"] == "personal"
    assert skill_events[0]["payload"]["source_session_id"] == session_id

    other_user = main.auth_store.create_user("other-personal-skill@example.test", "safe-password-456", "学生乙")
    assert other_user is not None
    other_token = main.auth_store.create_session(other_user["user_id"])
    with TestClient(app) as other_client:
        other_client.cookies.set(AUTH_COOKIE_NAME, other_token)
        other_session_response = other_client.post("/api/sessions", json={"case_id": "appendicitis_001"})

    assert other_session_response.status_code == 200
    other_session_payload = other_session_response.json()
    assert "evolution_candidates" not in other_session_payload
    other_internal_session = osce_session_service._get_session(other_session_payload["session_id"])
    assert other_internal_session is not None
    assert other_internal_session.evolution_candidates == []


def test_report_generation_and_optional_enrichment_require_explicit_posts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "已提交诊断，准备生成报告。"},
    )
    calls: dict[str, object] = {}

    pending_report = {
        "report_id": f"{session_id}_report",
        "session_id": session_id,
        "case_id": "appendicitis_001",
        "total_score": 0,
        "dimension_scores": {},
        "rubric_scores": {},
        "missed_items": [],
        "source_references": [],
        "source_reference_items": [],
        "explanation_source_items": [],
        "feedback_summary": "基础报告。",
        "personal_skill_candidate": {"status": "generation_pending", "scope": "personal"},
    }

    def generate_report(
        session_id_arg: str,
        *,
        include_optional_agents: bool = True,
    ) -> dict[str, object]:
        calls["session_id"] = session_id_arg
        calls["include_optional_agents"] = include_optional_agents
        return pending_report

    def read_report(session_id_arg: str) -> dict[str, object]:
        calls["read_session_id"] = session_id_arg
        return pending_report

    def enrich_report(session_id_arg: str) -> dict[str, object]:
        calls["enriched_session_id"] = session_id_arg
        return {
            "report_id": f"{session_id_arg}_report",
            "session_id": session_id_arg,
            "case_id": "appendicitis_001",
            "total_score": 0,
            "dimension_scores": {},
            "rubric_scores": {},
            "missed_items": [],
            "source_references": [],
            "source_reference_items": [],
            "explanation_source_items": [],
            "feedback_summary": "基础报告。",
            "personal_skill_candidate": {"status": "approved", "scope": "personal"},
        }

    monkeypatch.setattr(main.osce_session_service, "generate_report", generate_report)
    monkeypatch.setattr(main.osce_session_service, "read_report", read_report)
    monkeypatch.setattr(main.osce_session_service, "enrich_report_optional_agents", enrich_report)

    generate_response = client.post(f"/api/sessions/{session_id}/report/generate")
    read_response = client.get(f"/api/me/sessions/{session_id}/report")

    assert generate_response.status_code == 200
    assert read_response.status_code == 200
    assert calls["session_id"] == session_id
    assert calls["include_optional_agents"] is False
    assert calls["read_session_id"] == session_id
    assert "enriched_session_id" not in calls
    assert read_response.json()["personal_skill_candidate"]["status"] == "generation_pending"

    enrich_response = client.post(f"/api/sessions/{session_id}/report/enrich")

    assert enrich_response.status_code == 202
    assert calls["enriched_session_id"] == session_id
    assert enrich_response.json()["personal_skill_candidate"]["status"] == "generation_pending"


def test_report_generation_does_not_return_stale_payload_after_concurrent_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "已提交诊断，准备生成报告。"},
    )

    monkeypatch.setattr(
        main.osce_session_service,
        "generate_report",
        lambda *_args, **_kwargs: {"session_id": session_id, "report_id": f"{session_id}_report"},
    )
    monkeypatch.setattr(main.osce_session_service, "read_report", lambda _session_id: None)

    response = client.post(f"/api/sessions/{session_id}/report/generate")

    assert response.status_code == 404
    assert response.json() == {"detail": "session not found"}


def test_background_report_conflict_keeps_pending_report_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    enrichment_attempts = 0

    def pending_report(session_id_arg: str) -> dict[str, object]:
        assert session_id_arg == session_id
        return {
            "report_id": f"{session_id_arg}_report",
            "session_id": session_id_arg,
            "case_id": "appendicitis_001",
            "total_score": 0,
            "dimension_scores": {},
            "rubric_scores": {},
            "missed_items": [],
            "source_references": [],
            "source_reference_items": [],
            "explanation_source_items": [],
            "feedback_summary": "基础报告。",
            "personal_skill_candidate": {
                "status": "generation_pending",
                "scope": "personal",
            },
        }

    def enrich_report(session_id_arg: str) -> dict[str, object]:
        nonlocal enrichment_attempts
        assert session_id_arg == session_id
        enrichment_attempts += 1
        if enrichment_attempts == 1:
            raise SessionWriteConflictError(
                session_id,
                expected_revision=1,
                current_revision=2,
            )
        return {
            "session_id": session_id,
            "personal_skill_candidate": {
                "status": "approved",
                "scope": "personal",
            },
        }

    monkeypatch.setattr(main.osce_session_service, "read_report", pending_report)
    monkeypatch.setattr(main.osce_session_service, "enrich_report_optional_agents", enrich_report)

    first_response = client.post(f"/api/sessions/{session_id}/report/enrich")
    second_response = client.post(f"/api/sessions/{session_id}/report/enrich")

    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert first_response.json()["personal_skill_candidate"]["status"] == "generation_pending"
    assert second_response.json()["personal_skill_candidate"]["status"] == "generation_pending"
    assert enrichment_attempts == 2


def test_report_get_ignores_legacy_enrich_query_and_remains_pure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    read_calls: list[str] = []
    enrichment_calls: list[str] = []

    def report_for_poll(session_id_arg: str) -> dict[str, object]:
        assert session_id_arg == session_id
        read_calls.append(session_id_arg)
        return {
            "report_id": f"{session_id_arg}_report",
            "session_id": session_id_arg,
            "case_id": "appendicitis_001",
            "total_score": 0,
            "dimension_scores": {},
            "rubric_scores": {},
            "missed_items": [],
            "source_references": [],
            "source_reference_items": [],
            "explanation_source_items": [],
            "feedback_summary": "基础报告。",
            "personal_skill_candidate": {
                "status": "generation_pending",
                "scope": "personal",
            },
        }

    def enrich_report(session_id_arg: str) -> dict[str, object]:
        enrichment_calls.append(session_id_arg)
        return report_for_poll(session_id_arg)

    monkeypatch.setattr(main.osce_session_service, "read_report", report_for_poll)
    monkeypatch.setattr(main.osce_session_service, "enrich_report_optional_agents", enrich_report)

    response = client.get(f"/api/me/sessions/{session_id}/report?enrich=1")

    assert response.status_code == 200
    assert read_calls == [session_id]
    assert enrichment_calls == []
    assert response.json()["personal_skill_candidate"]["status"] == "generation_pending"


def test_report_can_return_before_personal_skill_agent_finishes(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TrackingPersonalSkillService:
        def __init__(self) -> None:
            self.call_count = 0

        def generate_for_completed_session(self, **_: object) -> dict[str, object]:
            self.call_count += 1
            return {
                "personal_skill_candidate": {
                    "status": "approved",
                    "scope": "personal",
                    "candidate_id": "personal_candidate_deferred",
                    "skill_id": "skill_personal_deferred",
                    "review": {"status": "approved"},
                    "rag_evidence_items": [],
                    "web_check_status": "not_configured",
                    "external_evidence_checks": [],
                },
                "ai_reflection_review": {"status": "generated", "summary": "后台增强已完成。"},
            }

    tracking_service = TrackingPersonalSkillService()
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_candidate_store = TrainingSkillCandidateStore(
        tmp_path / "training_skill_candidates.sqlite3"
    )
    osce_session_service._sessions.clear()
    monkeypatch.setattr(osce_session_service, "personal_skill_service", tracking_service)

    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "只完成部分问诊，仍希望先生成基础报告。"},
    )

    initial_report = osce_session_service.generate_report(session_id, include_optional_agents=False)
    assert initial_report is not None
    assert initial_report["personal_skill_candidate"]["status"] == "generation_pending"
    assert tracking_service.call_count == 0

    enriched_report = osce_session_service.enrich_report_optional_agents(session_id)

    assert enriched_report is not None
    assert tracking_service.call_count == 1
    assert enriched_report["personal_skill_candidate"]["status"] == "approved"
    assert osce_session_service.report_store.get_report(session_id)["personal_skill_candidate"]["status"] == "approved"


def test_pending_personal_skill_poll_does_not_resave_deferred_report(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TrackingPersonalSkillService:
        def generate_for_completed_session(self, **_: object) -> dict[str, object]:
            return {
                "personal_skill_candidate": {
                    "status": "approved",
                    "scope": "personal",
                    "candidate_id": "personal_candidate_poll_race",
                    "skill_id": "skill_personal_poll_race",
                    "review": {"status": "approved"},
                    "rag_evidence_items": [],
                    "web_check_status": "not_configured",
                    "external_evidence_checks": [],
                },
                "ai_reflection_review": {"status": "generated", "summary": "后台增强已完成。"},
            }

    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_candidate_store = TrainingSkillCandidateStore(
        tmp_path / "training_skill_candidates.sqlite3"
    )
    osce_session_service._sessions.clear()
    monkeypatch.setattr(osce_session_service, "personal_skill_service", TrackingPersonalSkillService())

    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "先生成基础报告，再后台生成个人 Skill。"},
    )

    pending_report = osce_session_service.generate_report(session_id, include_optional_agents=False)
    assert pending_report is not None
    assert pending_report["personal_skill_candidate"]["status"] == "generation_pending"

    save_calls: list[str] = []
    original_save_report = osce_session_service.report_store.save_report

    def tracking_save_report(report: dict[str, object]) -> None:
        save_calls.append(str(report.get("personal_skill_candidate", {}).get("status")))
        original_save_report(report)

    monkeypatch.setattr(osce_session_service.report_store, "save_report", tracking_save_report)

    repeated_poll_report = osce_session_service.read_report(session_id)
    enriched_report = osce_session_service.enrich_report_optional_agents(session_id)

    assert repeated_poll_report is not None
    assert repeated_poll_report["personal_skill_candidate"]["status"] == "generation_pending"
    assert save_calls == []
    assert enriched_report is not None
    assert enriched_report["personal_skill_candidate"]["status"] == "approved"
    assert osce_session_service.report_store.get_report(session_id)["personal_skill_candidate"]["status"] == "approved"


def test_completed_training_hydrates_legacy_stored_report_with_ai_reflection_and_coverage_snapshot(
    tmp_path,
    authenticated_user: dict[str, str],
) -> None:
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_candidate_store = TrainingSkillCandidateStore(
        tmp_path / "training_skill_candidates.sqlite3"
    )
    osce_session_service._sessions.clear()

    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})
    client.post(f"/api/sessions/{session_id}/physical-exam", json={"exam_code": "abd.palpation.rebound"})
    client.post(f"/api/sessions/{session_id}/auxiliary-test", json={"test_code": "lab.cbc"})
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
    )
    osce_session_service.report_store.save_report(
        {
            "report_id": f"{session_id}_report",
            "session_id": session_id,
            "case_id": "appendicitis_001",
            "total_score": 8,
            "dimension_scores": {},
            "rubric_scores": {},
            "missed_items": ["ht_migration"],
            "strengths": [],
            "reasoning_errors": ["未完整追问疼痛部位及转移特征。"],
            "next_recommendations": ["下一轮训练重点：追问疼痛部位及转移特征。"],
            "knowledge_recommendations": [],
            "source_references": ["rubric:appendicitis_001_rubric.item.ht_migration"],
            "source_reference_items": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.ht_migration",
                    "source_type": "rubric",
                    "title": "追问疼痛部位及转移特征",
                    "metadata": {},
                }
            ],
            "explanation_source_items": [],
            "llm_reasoning_feedback": [],
            "evidence_graph_summary": None,
            "feedback_summary": "历史报告。",
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
                "summary": "提交诊断并生成完整评分报告后，系统会生成教师复盘和下一轮个人训练 Skill。",
                "mistake_patterns": [],
                "teacher_feedback": "",
                "next_focus": "",
                "source_references": [],
                "source_reference_items": [],
            },
        }
    )

    generate_response = client.post(f"/api/sessions/{session_id}/report/generate")
    enrich_response = client.post(f"/api/sessions/{session_id}/report/enrich")
    report_response = client.get(f"/api/sessions/{session_id}/report")
    report = report_response.json()

    assert generate_response.status_code == 200
    assert enrich_response.status_code == 202
    assert report_response.status_code == 200
    assert report["ai_reflection_review"]["status"] == "generated"
    assert report["personal_skill_candidate"]["status"] == "approved"
    assert report["personal_skill_candidate"]["owner_student_id"] == authenticated_user["user_id"]
    assert report["training_progress_snapshot"]["coverage_map"]["history"]
    assert any(
        item["status"] == "covered"
        for item in report["training_progress_snapshot"]["coverage_map"]["physical_exam"]
    )
    stored_report = osce_session_service.report_store.get_report(session_id)
    assert stored_report is not None
    assert stored_report["ai_reflection_review"]["status"] == "generated"
    assert stored_report["training_progress_snapshot"]["coverage_map"]["auxiliary_test"]


def test_completed_training_report_survives_personal_skill_generation_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.training_skill_candidate_service import TrainingSkillCandidateGenerationError

    class FailingPersonalSkillService:
        def generate_for_completed_session(self, **_: object) -> dict[str, object]:
            raise TrainingSkillCandidateGenerationError("Skill candidate generation failed")

    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_candidate_store = TrainingSkillCandidateStore(
        tmp_path / "training_skill_candidates.sqlite3"
    )
    osce_session_service._sessions.clear()
    monkeypatch.setattr(osce_session_service, "personal_skill_service", FailingPersonalSkillService())

    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    client.post(f"/api/sessions/{session_id}/physical-exam", json={"exam_code": "abd.palpation.rebound"})
    client.post(f"/api/sessions/{session_id}/auxiliary-test", json={"test_code": "lab.cbc"})
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "反跳痛和白细胞升高支持诊断，但病史补充不足。"},
    )

    generate_response = client.post(f"/api/sessions/{session_id}/report/generate")
    enrich_response = client.post(f"/api/sessions/{session_id}/report/enrich")
    response = client.get(f"/api/sessions/{session_id}/report")

    assert generate_response.status_code == 200
    assert enrich_response.status_code == 202
    assert response.status_code == 200
    report = response.json()
    assert report["personal_skill_candidate"]["status"] == "generation_failed"
    assert report["personal_skill_candidate"]["reason"] == "skill_candidate_generation_failed"
    assert report["ai_reflection_review"]["status"] == "generated"


def test_completed_training_report_records_warning_when_personal_skill_crashes(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CrashingPersonalSkillService:
        def generate_for_completed_session(self, **_: object) -> dict[str, object]:
            raise RuntimeError("unexpected personal skill crash")

    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_candidate_store = TrainingSkillCandidateStore(
        tmp_path / "training_skill_candidates.sqlite3"
    )
    osce_session_service._sessions.clear()
    monkeypatch.setattr(osce_session_service, "personal_skill_service", CrashingPersonalSkillService())

    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "只完成部分问诊，仍希望生成基础报告。"},
    )

    generate_response = client.post(f"/api/sessions/{session_id}/report/generate")
    enrich_response = client.post(f"/api/sessions/{session_id}/report/enrich")
    response = client.get(f"/api/sessions/{session_id}/report")

    assert generate_response.status_code == 200
    assert enrich_response.status_code == 202
    assert response.status_code == 200
    report = response.json()
    assert report["report_id"] == f"{session_id}_report"
    assert report["personal_skill_candidate"]["status"] == "generation_failed"
    assert report["ai_reflection_review"]["status"] == "generated"
    assert report["generation_warnings"] == [
        {
            "module": "personal_skill_generation",
            "error_type": "RuntimeError",
            "message": "unexpected personal skill crash",
        }
    ]


def test_completed_training_rehydrates_legacy_generic_ai_reflection_text(
    tmp_path,
    authenticated_user: dict[str, str],
) -> None:
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_candidate_store = TrainingSkillCandidateStore(
        tmp_path / "training_skill_candidates.sqlite3"
    )
    osce_session_service._sessions.clear()

    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    client.post(f"/api/sessions/{session_id}/physical-exam", json={"exam_code": "abd.palpation.rebound"})
    client.post(f"/api/sessions/{session_id}/auxiliary-test", json={"test_code": "lab.cbc"})
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "反跳痛和白细胞升高支持诊断，但病史补充不足。"},
    )
    client.post(f"/api/sessions/{session_id}/report/generate")
    client.post(f"/api/sessions/{session_id}/report/enrich")
    generated_report = client.get(f"/api/sessions/{session_id}/report").json()
    osce_session_service.report_store.save_report(
        {
            **generated_report,
            "ai_reflection_review": {
                "status": "generated",
                "summary": "本轮主要问题集中在 6 个训练点：证据采集、鉴别诊断或推理表达仍有缺口。",
                "mistake_patterns": ["ht_onset"],
                "teacher_feedback": "建议下一轮先说明为什么要问、查或检验，再把证据串成支持与排除依据。",
                "next_focus": "下一轮 Coach 会优先围绕本轮个人 Skill 给出针对性提示。",
                "source_references": [],
                "source_reference_items": [],
                "safety_note": "AI 复盘仅用于 OSCE 教学训练，不改变病例事实、rubric、标准诊断或评分规则。",
            },
        }
    )

    stored_before_read = osce_session_service.report_store.get_stored_report(session_id)
    report = client.get(f"/api/sessions/{session_id}/report").json()
    stored_after_read = osce_session_service.report_store.get_stored_report(session_id)

    assert "右下腹痛教学病例" in report["ai_reflection_review"]["summary"]
    assert "老师视角" in report["ai_reflection_review"]["teacher_feedback"]
    assert "下一轮 Coach" not in report["ai_reflection_review"]["next_focus"]
    assert "AI 复盘" not in report["ai_reflection_review"]["safety_note"]
    assert stored_before_read == stored_after_read


def test_orphan_legacy_report_rehydrates_generic_ai_reflection_from_report_fields(tmp_path) -> None:
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.training_skill_candidate_store = TrainingSkillCandidateStore(
        tmp_path / "training_skill_candidates.sqlite3"
    )
    osce_session_service._sessions.clear()
    session_id = "orphan-legacy-report"
    osce_session_service.report_store.save_report(
        {
            "report_id": f"{session_id}_report",
            "session_id": session_id,
            "case_id": "appendicitis_001",
            "total_score": 62,
            "max_score": 100,
            "missed_items": ["ht_onset", "ax_ua"],
            "knowledge_recommendations": [],
            "source_references": ["rubric:appendicitis_001_rubric.item.ht_onset"],
            "source_reference_items": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.ht_onset",
                    "source_type": "rubric",
                    "title": "追问起病时间",
                    "metadata": {},
                }
            ],
            "ai_reflection_review": {
                "status": "generated",
                "summary": "本轮主要问题集中在 2 个训练点：证据采集、鉴别诊断或推理表达仍有缺口。",
                "mistake_patterns": ["ht_onset", "ax_ua"],
                "teacher_feedback": "建议下一轮先说明为什么要问、查或检验，再把证据串成支持与排除依据。",
                "next_focus": "下一轮 Coach 会优先围绕本轮个人 Skill 给出针对性提示。",
                "source_references": [],
                "source_reference_items": [],
                "safety_note": "AI 复盘仅用于 OSCE 教学训练，不改变病例事实、rubric、标准诊断或评分规则。",
            },
        }
    )

    report = osce_session_service.get_report(session_id)

    assert report is not None
    assert "右下腹痛教学病例" in report["ai_reflection_review"]["summary"]
    assert "老师视角" in report["ai_reflection_review"]["teacher_feedback"]
    assert "AI 复盘" not in report["ai_reflection_review"]["safety_note"]


def test_incomplete_training_report_does_not_generate_personal_skill(tmp_path) -> None:
    osce_session_service.report_store = ReportStore(tmp_path / "reports.sqlite3")
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    osce_session_service.training_event_store = TrainingEventStore(tmp_path / "training_events.sqlite3")
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_candidate_store = TrainingSkillCandidateStore(
        tmp_path / "training_skill_candidates.sqlite3"
    )
    osce_session_service._sessions.clear()

    create_response = client.post("/api/sessions", json={"case_id": "appendicitis_001"})
    session_id = create_response.json()["session_id"]
    missing_report_response = client.get(f"/api/sessions/{session_id}/report")
    blocked_generate_response = client.post(f"/api/sessions/{session_id}/report/generate")
    report = osce_session_service.generate_report(session_id, include_optional_agents=False)
    loaded_report_response = client.get(f"/api/sessions/{session_id}/report")

    assert missing_report_response.status_code == 404
    assert missing_report_response.json() == {"detail": "report not found"}
    assert blocked_generate_response.status_code == 409
    assert blocked_generate_response.json() == {"detail": "请先提交诊断，再生成评分报告。"}
    assert report is not None
    assert report["personal_skill_candidate"]["status"] == "not_complete"
    assert report["ai_reflection_review"]["status"] == "not_ready"
    assert loaded_report_response.status_code == 200
    assert loaded_report_response.json()["personal_skill_candidate"]["status"] == "not_complete"
    assert osce_session_service.training_skill_store.list_enabled_skills() == []


def test_osce_session_state_can_be_read_after_session_memory_is_cleared(tmp_path) -> None:
    osce_session_service.session_store = OsceSessionStore(tmp_path / "osce_sessions.sqlite3")
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]

    message_response = client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})
    exam_response = client.post(f"/api/sessions/{session_id}/physical-exam", json={"exam_code": "abd.palpation.rebound"})
    hypothesis_response = client.post(
        f"/api/sessions/{session_id}/hypotheses",
        json={"hypothesis": "先考虑急腹症，需要继续查体和检查验证。"},
    )
    assert message_response.status_code == 200
    assert exam_response.status_code == 200
    assert hypothesis_response.status_code == 200

    osce_session_service._sessions.clear()
    loaded_response = client.get(f"/api/sessions/{session_id}")

    assert loaded_response.status_code == 200
    payload = loaded_response.json()
    assert payload["session_id"] == session_id
    assert payload["messages"] == message_response.json()["messages"]
    assert payload["revealed_facts"] == ["appendicitis_001.hf_01"]
    assert payload["requested_exams"] == ["abd.palpation.rebound"]
    assert payload["student_hypotheses"] == ["先考虑急腹症，需要继续查体和检查验证。"]


def test_osce_session_records_training_events(tmp_path, authenticated_user: dict[str, str]) -> None:
    database_path = tmp_path / "training_events.sqlite3"
    osce_session_service.training_event_store = TrainingEventStore(database_path)
    osce_session_service.training_skill_store = TrainingSkillStore(tmp_path / "training_skills.sqlite3")
    osce_session_service.training_skill_store.enable_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "case_ids": ["appendicitis_001"],
            "title": "临床推理链纠偏提示",
            "description": "推理链反复遗漏。",
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "source_report_count": 3,
            "support_count": 2,
            "review": {"status": "approved", "regression_passed": True},
        }
    )
    create_response = client.post(
        "/api/sessions",
        json={"case_id": "appendicitis_001", "student_id": "student_demo"},
    )
    session_id = create_response.json()["session_id"]

    client.post(f"/api/sessions/{session_id}/message", json={"message": "什么时候开始疼的？"})
    client.post(f"/api/sessions/{session_id}/physical-exam", json={"exam_code": "abd.palpation.rebound"})
    client.post(f"/api/sessions/{session_id}/auxiliary-test", json={"test_code": "lab.cbc"})
    client.post(
        f"/api/sessions/{session_id}/submit-diagnosis",
        json={"diagnosis": "急性阑尾炎", "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。"},
    )
    client.post(f"/api/sessions/{session_id}/report/generate")
    client.post(f"/api/sessions/{session_id}/report/enrich")
    state_payload = client.get(f"/api/sessions/{session_id}").json()
    internal_session = osce_session_service._get_session(session_id)
    assert internal_session is not None

    events = TrainingEventStore(database_path).list_session_events(session_id)

    filtered_business_events = business_events(events)
    assert [event["event_type"] for event in filtered_business_events] == [
        "session_created",
        "training_skill_applied",
        "history_message",
        "physical_exam_requested",
        "auxiliary_test_requested",
        "diagnosis_submitted",
        "report_generated",
        "personal_training_skill_generated",
        "report_enriched",
    ]
    assert filtered_business_events[0]["case_id"] == "appendicitis_001"
    assert filtered_business_events[0]["student_id"] == authenticated_user["user_id"]
    assert filtered_business_events[1]["payload"] == {
        "skill_id": "skill_reasoning_core",
        "title": "临床推理链纠偏提示",
        "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
        "skill_type": "reasoning_bridge",
        "stage_scope": ["case_intro"],
        "effect_status": "insufficient_samples",
    }
    assert filtered_business_events[2]["payload"] == {
        "message": "什么时候开始疼的？",
        "current_intents": ["ask_onset"],
        "reply": "24 小时前开始，最初是上腹部隐痛。",
        "agent_turn": internal_session.agent_turn_memory[0],
    }
    assert "agent_path" not in state_payload["agent_turn_memory"][0]
    assert filtered_business_events[3]["payload"] == {"exam_code": "abd.palpation.rebound", "result": "右下腹反跳痛阳性。"}
    assert filtered_business_events[4]["payload"] == {"test_code": "lab.cbc", "result": "白细胞 14.2×10^9/L，中性粒细胞比例 85%。"}
    assert filtered_business_events[5]["payload"] == {
        "diagnosis": "急性阑尾炎",
        "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。",
    }
    report_event_payload = filtered_business_events[6]["payload"]
    assert report_event_payload["report_id"] == f"{session_id}_report"
    assert report_event_payload["total_score"] == 22
    assert {"ht_migration", "rs_support", "comm_intro_purpose", "eth_exam_consent", "rel_empathy_response"} <= set(
        report_event_payload["missed_items"]
    )
    recommendation_references = {
        recommendation["reference"]
        for recommendation in report_event_payload["knowledge_recommendations"]
    }
    assert {
        "rubric:appendicitis_001_rubric.item.ht_migration",
        "rubric:appendicitis_001_rubric.item.rs_support",
        "rubric:appendicitis_001_rubric.item.comm_intro_purpose",
        "rubric:appendicitis_001_rubric.item.eth_exam_consent",
        "rubric:appendicitis_001_rubric.item.rel_empathy_response",
        "case:acs_001",
    } <= recommendation_references
    assert report_event_payload["source_references"][:3] == [
        "case:appendicitis_001",
        "source:fareez_osce_2022",
        "rubric:appendicitis_001_rubric.item.ht_migration",
    ]
    assert report_event_payload["source_reference_items"][0] == {
        "reference": "case:appendicitis_001",
        "source_type": "case",
        "title": "右下腹痛教学病例",
        "metadata": {},
    }
    assert report_event_payload["source_reference_items"][1]["metadata"]["license"] == "CC BY 4.0"
    assert filtered_business_events[7]["payload"]["scope"] == "personal"
    assert filtered_business_events[7]["payload"]["skill_id"].startswith("skill_personal_")
    enriched_event_payload = filtered_business_events[8]["payload"]
    assert enriched_event_payload["report_id"] == f"{session_id}_report"
    assert enriched_event_payload["report_revision"] > report_event_payload["report_revision"]
    assert enriched_event_payload["personal_skill_candidate"]["status"] == "approved"
    agent_event_types = [event["event_type"] for event in events if event["event_type"] in AGENT_EVENT_TYPES]
    assert agent_event_types.count("agent_decision_traced") >= 5
    assert "agent_reflection_recorded" in agent_event_types
    agent_decision_payload = find_event(events, "agent_decision_traced")["payload"]
    assert agent_decision_payload["latest_decision"]["node"] == "training_strategy_node"
    assert agent_decision_payload["pedagogy_state"]["safety_mode"] == "teaching_only"
    reflection_payload = find_event(events, "agent_reflection_recorded")["payload"]
    assert reflection_payload["reflection_summary"]["reflection_summary_id"] == f"reflection:appendicitis_001:{len(report_event_payload['missed_items'])}"
