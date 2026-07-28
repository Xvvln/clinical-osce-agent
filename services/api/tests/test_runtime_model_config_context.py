from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import AUTH_COOKIE_NAME
from app.models.rubric import LlmRubricRequest, LlmRubricResponse
from app.services import gemini_patient_responder as patient_responder_module
from app.services.auth_store import AuthStore
from app.services.google_genai_http_options import (
    INVALID_GOOGLE_GENAI_PROXY_MESSAGE,
    RUNTIME_VERTEX_ADC_PROXY_UNSUPPORTED_MESSAGE,
)
from app.services.runtime_model_config_store import RuntimeModelConfig, runtime_model_config_store
from app.services.osce_session_service import OsceSessionService


@pytest.fixture(autouse=True)
def allow_runtime_context_test_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CLINICAL_OSCE_ACCOUNT_MODEL_ALLOWED_HOSTS",
        ",".join(
            [
                "lazy-provider-a.example",
                "lazy-provider-b.example",
                "process-provider.example",
                "provider-a.example",
                "provider-b.example",
                "report-provider.example",
                "request-provider.example",
                "scorer-provider-a.example",
                "scorer-provider-b.example",
                "user-provider.example",
            ]
        ),
    )


class _ConcurrentSessionService:
    def __init__(self, sessions: dict[str, dict[str, object]], barrier: Barrier) -> None:
        self._sessions = sessions
        self._barrier = barrier

    def get_session(self, session_id: str) -> dict[str, object] | None:
        session = self._sessions.get(session_id)
        return dict(session) if session is not None else None

    def handle_message(self, session_id: str, message: str) -> dict[str, object]:
        self._barrier.wait(timeout=5)
        runtime_config = runtime_model_config_store.get_active_config()
        return {
            **self._sessions[session_id],
            "message": message,
            "runtime_model": runtime_config.model if runtime_config is not None else "",
        }


class _ReportSessionService:
    def __init__(self, session: dict[str, object]) -> None:
        self._session = session
        self.observed_models: list[tuple[str, str]] = []

    def get_session(self, session_id: str) -> dict[str, object] | None:
        if session_id != self._session["session_id"]:
            return None
        return dict(self._session)

    def get_report(self, session_id: str, *, include_optional_agents: bool = True) -> dict[str, object] | None:
        if session_id != self._session["session_id"]:
            return None
        runtime_config = runtime_model_config_store.get_active_config()
        self.observed_models.append(("foreground", runtime_config.model if runtime_config is not None else ""))
        return {
            "session_id": session_id,
            "personal_skill_candidate": {
                "status": "generation_pending" if not include_optional_agents else "generated",
            },
        }

    def enrich_report_optional_agents(self, session_id: str) -> dict[str, object] | None:
        runtime_config = runtime_model_config_store.get_active_config()
        self.observed_models.append(("background", runtime_config.model if runtime_config is not None else ""))
        return {
            "session_id": session_id,
            "personal_skill_candidate": {"status": "generated"},
        }


def _client_for_token(token: str) -> TestClient:
    client = TestClient(main.app)
    client.cookies.set(AUTH_COOKIE_NAME, token)
    return client


def _runtime_config(*, api_key: str, model: str, base_url: str) -> RuntimeModelConfig:
    return RuntimeModelConfig(
        provider="openai_compatible",
        api_key=api_key,
        model=model,
        base_url=base_url,
        proxy_url="direct",
    )


def test_parallel_training_requests_keep_user_runtime_config_isolated(tmp_path, monkeypatch) -> None:
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(main, "auth_store", auth_store)
    first_user = auth_store.create_user("runtime-a@example.test", "safe-password-123", "A")
    second_user = auth_store.create_user("runtime-b@example.test", "safe-password-123", "B")
    assert first_user is not None
    assert second_user is not None

    first_token = auth_store.create_session(first_user["user_id"])
    second_token = auth_store.create_session(second_user["user_id"])
    main.user_model_config_store.save_runtime_config(
        first_user["user_id"],
        _runtime_config(
            api_key="secret-a",
            model="model-a",
            base_url="https://provider-a.example/v1",
        ),
    )
    main.user_model_config_store.save_runtime_config(
        second_user["user_id"],
        _runtime_config(
            api_key="secret-b",
            model="model-b",
            base_url="https://provider-b.example/v1",
        ),
    )

    first_session_id = "runtime-session-a"
    second_session_id = "runtime-session-b"
    session_service = _ConcurrentSessionService(
        {
            first_session_id: {
                "session_id": first_session_id,
                "student_id": first_user["user_id"],
                "stage": "history_taking",
            },
            second_session_id: {
                "session_id": second_session_id,
                "student_id": second_user["user_id"],
                "stage": "history_taking",
            },
        },
        Barrier(2),
    )
    monkeypatch.setattr(main, "osce_session_service", session_service)

    first_client = _client_for_token(first_token)
    second_client = _client_for_token(second_token)

    def send(client: TestClient, session_id: str) -> Any:
        return client.post(f"/api/sessions/{session_id}/message", json={"message": "并发问诊"})

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(send, first_client, first_session_id)
        second_future = executor.submit(send, second_client, second_session_id)
        first_response = first_future.result(timeout=10)
        second_response = second_future.result(timeout=10)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["runtime_model"] == "model-a"
    assert second_response.json()["runtime_model"] == "model-b"
    assert runtime_model_config_store.get_active_config() is None


def test_runtime_config_post_and_status_get_do_not_change_process_fallback(tmp_path, monkeypatch) -> None:
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(main, "auth_store", auth_store)
    user = auth_store.create_user("runtime-status@example.test", "safe-password-123", "学生")
    assert user is not None
    token = auth_store.create_session(user["user_id"])
    client = _client_for_token(token)

    process_fallback = runtime_model_config_store.apply_config(
        {
            "provider": "openai_compatible",
            "api_key": "process-secret",
            "model": "process-model",
            "base_url": "https://process-provider.example/v1",
            "proxy_url": "direct",
        }
    )

    save_response = client.post(
        "/api/model-config/runtime",
        json={
            "provider": "openai_compatible",
            "api_key": "user-secret",
            "model": "user-model",
            "base_url": "https://user-provider.example/v1",
            "proxy_url": "direct",
        },
    )
    active_after_post = runtime_model_config_store.get_active_config()
    status_response = client.get("/api/model-config/runtime")
    active_after_get = runtime_model_config_store.get_active_config()

    assert save_response.status_code == 200
    assert status_response.status_code == 200
    assert status_response.json()["model"] == "user-model"
    assert active_after_post == process_fallback
    assert active_after_get == process_fallback


def test_runtime_model_context_resets_after_exception() -> None:
    process_fallback = runtime_model_config_store.apply_config(
        {
            "provider": "openai_compatible",
            "api_key": "process-secret",
            "model": "process-model",
            "base_url": "https://process-provider.example/v1",
            "proxy_url": "direct",
        }
    )
    request_config = _runtime_config(
        api_key="request-secret",
        model="request-model",
        base_url="https://request-provider.example/v1",
    )

    with pytest.raises(RuntimeError, match="request failed"):
        with runtime_model_config_store.use_config(request_config):
            assert runtime_model_config_store.get_active_config() == request_config
            raise RuntimeError("request failed")

    assert runtime_model_config_store.get_active_config() == process_fallback


def test_real_lazy_patient_responder_keeps_parallel_runtime_clients_isolated(monkeypatch) -> None:
    assignment_barrier = Barrier(2)
    call_barrier = Barrier(2)
    start_barrier = Barrier(2)

    class TaggedResponder:
        def __init__(self, model: str) -> None:
            self.model = model

        def __call__(self, request: object) -> str:
            call_barrier.wait(timeout=5)
            return self.model

    def create_tagged_responder() -> TaggedResponder:
        runtime_config = runtime_model_config_store.get_active_config()
        assert runtime_config is not None
        return TaggedResponder(runtime_config.model)

    class AssignmentBarrierLazyResponder(patient_responder_module.LazyGeminiPatientResponder):
        """Makes the former shared-attribute race deterministic without replacing Lazy.__call__."""

        def __init__(self) -> None:
            self._trap_assignments = False
            super().__init__()
            self._trap_assignments = True

        @property
        def _responder(self) -> object | None:
            return self.__dict__.get("_test_responder")

        @_responder.setter
        def _responder(self, value: object | None) -> None:
            self.__dict__["_test_responder"] = value
            if self._trap_assignments and value is not None:
                assignment_barrier.wait(timeout=5)

    monkeypatch.setattr(patient_responder_module, "_create_configured_responder", create_tagged_responder)
    lazy_responder = AssignmentBarrierLazyResponder()
    first_config = _runtime_config(
        api_key="lazy-secret-a",
        model="lazy-model-a",
        base_url="https://lazy-provider-a.example/v1",
    )
    second_config = _runtime_config(
        api_key="lazy-secret-b",
        model="lazy-model-b",
        base_url="https://lazy-provider-b.example/v1",
    )
    process_fallback = runtime_model_config_store.get_active_config()

    def invoke(config: RuntimeModelConfig) -> str:
        with runtime_model_config_store.use_config(config):
            start_barrier.wait(timeout=5)
            return lazy_responder(object())  # type: ignore[arg-type,return-value]

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(invoke, first_config)
        second_future = executor.submit(invoke, second_config)
        first_result = first_future.result(timeout=10)
        second_result = second_future.result(timeout=10)

    assert first_result == "lazy-model-a"
    assert second_result == "lazy-model-b"
    assert runtime_model_config_store.get_active_config() == process_fallback


def test_default_osce_session_scorer_resolves_current_runtime_config_at_evaluation(monkeypatch) -> None:
    factory_models: list[str] = []
    scorer_models: list[str] = []

    def create_runtime_scorer() -> Any:
        runtime_config = runtime_model_config_store.get_active_config()
        assert runtime_config is not None
        model = runtime_config.model
        factory_models.append(model)

        def score(request: LlmRubricRequest) -> LlmRubricResponse:
            scorer_models.append(model)
            return LlmRubricResponse(
                score=request.max_score,
                covered_evidence=list(request.required_evidence),
                missing_evidence=[],
                rationale=f"{model} runtime scorer",
            )

        return score

    monkeypatch.setattr(
        "app.services.osce_session_service.create_default_vertex_gemini_scorer",
        create_runtime_scorer,
    )
    service = OsceSessionService(patient_responder=lambda request: str(request.canonical_answer))
    assert factory_models == []

    first_config = _runtime_config(
        api_key="scorer-secret-a",
        model="scorer-model-a",
        base_url="https://scorer-provider-a.example/v1",
    )
    second_config = _runtime_config(
        api_key="scorer-secret-b",
        model="scorer-model-b",
        base_url="https://scorer-provider-b.example/v1",
    )

    def evaluate(config: RuntimeModelConfig, session_id: str) -> dict[str, object]:
        with runtime_model_config_store.use_config(config):
            return service.osce_graph.invoke(
                {
                    "session_id": session_id,
                    "case_id": "appendicitis_001",
                    "stage": "diagnosis_submission",
                    "case_title": "右下腹痛教学病例",
                    "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
                    "report_requested": True,
                    "messages": [],
                    "asked_questions": ["什么时候开始疼的？"],
                    "intent_history": ["ask_onset"],
                    "revealed_facts": ["appendicitis_001.hf_01", "appendicitis_001.hf_02"],
                    "requested_exams": ["abd.palpation.rebound"],
                    "requested_tests": ["lab.cbc"],
                    "student_hypotheses": ["急性阑尾炎"],
                    "final_submission": {
                        "diagnosis": "急性阑尾炎",
                        "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。",
                    },
                    "rubric_scores": {},
                    "missed_items": [],
                    "retrieved_sources": [],
                    "feedback_report": None,
                    "safety_flags": [],
                    "evolution_candidates": [],
                }
            )

    first_result = evaluate(first_config, "runtime-scorer-a")
    second_result = evaluate(second_config, "runtime-scorer-b")

    assert factory_models == ["scorer-model-a", "scorer-model-b"]
    assert scorer_models == ["scorer-model-a", "scorer-model-b"]
    assert first_result["rubric_scores"]["rs_exclude"]["rationale"] == "scorer-model-a runtime scorer"
    assert second_result["rubric_scores"]["rs_exclude"]["rationale"] == "scorer-model-b runtime scorer"


def test_report_background_enrichment_rebinds_session_owner_runtime_config(tmp_path, monkeypatch) -> None:
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(main, "auth_store", auth_store)
    user = auth_store.create_user("report-owner@example.test", "safe-password-123", "学生")
    assert user is not None
    token = auth_store.create_session(user["user_id"])
    client = _client_for_token(token)
    main.user_model_config_store.save_runtime_config(
        user["user_id"],
        _runtime_config(
            api_key="report-secret",
            model="report-owner-model",
            base_url="https://report-provider.example/v1",
        ),
    )
    process_fallback = runtime_model_config_store.apply_config(
        {
            "provider": "openai_compatible",
            "api_key": "process-secret",
            "model": "process-model",
            "base_url": "https://process-provider.example/v1",
            "proxy_url": "direct",
        }
    )
    session_id = "report-runtime-session"
    session_service = _ReportSessionService(
        {
            "session_id": session_id,
            "student_id": user["user_id"],
            "stage": "feedback",
        }
    )
    monkeypatch.setattr(main, "osce_session_service", session_service)

    response = client.get(f"/api/me/sessions/{session_id}/report")

    assert response.status_code == 200
    assert session_service.observed_models == [
        ("foreground", "report-owner-model"),
        ("background", "report-owner-model"),
    ]
    assert runtime_model_config_store.get_active_config() == process_fallback


def test_runtime_vertex_adc_rejects_account_proxy_before_changing_process_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CLINICAL_OSCE_ALLOW_UNSAFE_ACCOUNT_MODEL_ENDPOINTS",
        "true",
    )
    process_fallback = runtime_model_config_store.apply_config(
        {
            "provider": "openai_compatible",
            "api_key": "process-secret",
            "model": "process-model",
            "base_url": "https://process-provider.example/v1",
            "proxy_url": "direct",
        }
    )

    with pytest.raises(ValueError, match=RUNTIME_VERTEX_ADC_PROXY_UNSUPPORTED_MESSAGE):
        runtime_model_config_store.apply_config(
            {
                "provider": "vertex_gemini_adc",
                "api_key": "",
                "model": "gemini-3.1-pro-preview",
                "base_url": "student-project",
                "proxy_url": "http://account-proxy.example:7897",
            }
        )

    assert runtime_model_config_store.get_active_config() == process_fallback


def test_runtime_vertex_adc_requires_explicit_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CLINICAL_OSCE_ALLOW_UNSAFE_ACCOUNT_MODEL_ENDPOINTS",
        "true",
    )
    with pytest.raises(ValueError, match="project is required for vertex_gemini_adc"):
        runtime_model_config_store.build_config(
            {
                "provider": "vertex_gemini_adc",
                "api_key": "",
                "model": "gemini-3.1-pro-preview",
                "base_url": "",
                "proxy_url": "direct",
            }
        )


def test_runtime_vertex_api_key_rejects_invalid_proxy_before_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CLINICAL_OSCE_ALLOW_UNSAFE_ACCOUNT_MODEL_ENDPOINTS",
        "true",
    )
    with pytest.raises(ValueError, match=INVALID_GOOGLE_GENAI_PROXY_MESSAGE):
        runtime_model_config_store.build_config(
            {
                "provider": "vertex_gemini_api_key",
                "api_key": "vertex-secret",
                "model": "gemini-2.5-flash",
                "base_url": "",
                "proxy_url": "socks5://unsupported-proxy.example:7897",
            }
        )
