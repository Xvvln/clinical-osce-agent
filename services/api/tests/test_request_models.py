import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main


def test_student_request_models_accept_declared_boundaries() -> None:
    main.AuthRegisterRequest(
        email=f"{'a' * 246}@mail.io",
        password="p" * main.AUTH_PASSWORD_MAX_CHARS,
        display_name="n" * main.DISPLAY_NAME_MAX_CHARS,
    )
    main.CreateSessionRequest(
        case_id="c" * main.IDENTIFIER_MAX_CHARS,
        student_id="s" * main.IDENTIFIER_MAX_CHARS,
        training_difficulty="advanced",
    )
    main.MessageRequest(message="q" * main.QUESTION_MAX_CHARS)
    main.AudioSpeechRequest(
        input="s" * main.SPEECH_INPUT_MAX_CHARS,
        voice="v" * main.IDENTIFIER_MAX_CHARS,
        model="m" * main.MODEL_NAME_MAX_CHARS,
        session_id="i" * main.IDENTIFIER_MAX_CHARS,
        message_index=0,
        emotion="e" * 32,
    )
    main.PhysicalExamBatchRequest(
        exam_codes=[
            "e" * main.PROCEDURE_CODE_MAX_CHARS
            for _ in range(main.PROCEDURE_BATCH_MAX_ITEMS)
        ]
    )
    main.AuxiliaryTestBatchRequest(
        test_codes=[
            "t" * main.PROCEDURE_CODE_MAX_CHARS
            for _ in range(main.PROCEDURE_BATCH_MAX_ITEMS)
        ]
    )
    main.ProcedureFreeTextRequest(
        request_text="p" * main.PROCEDURE_REQUEST_MAX_CHARS
    )
    main.SubmitDiagnosisRequest(
        diagnosis="d" * main.DIAGNOSIS_MAX_CHARS,
        reasoning="r" * main.DIAGNOSIS_REASONING_MAX_CHARS,
    )
    main.HypothesisRequest(hypothesis="h" * main.HYPOTHESIS_MAX_CHARS)


@pytest.mark.parametrize(
    "build_request",
    [
        lambda: main.AuthLoginRequest(
            email="e" * (main.AUTH_EMAIL_MAX_CHARS + 1),
            password="password",
        ),
        lambda: main.AuthLoginRequest(
            email="student@example.com",
            password="p" * (main.AUTH_PASSWORD_MAX_CHARS + 1),
        ),
        lambda: main.CreateSessionRequest(
            case_id="case",
            training_difficulty="e" * 65,
        ),
        lambda: main.MessageRequest(message="q" * (main.QUESTION_MAX_CHARS + 1)),
        lambda: main.AudioSpeechRequest(
            input="s" * (main.SPEECH_INPUT_MAX_CHARS + 1)
        ),
        lambda: main.AudioSpeechRequest(input="hello", emotion="e" * 33),
        lambda: main.PhysicalExamRequest(
            exam_code="e" * (main.PROCEDURE_CODE_MAX_CHARS + 1)
        ),
        lambda: main.PhysicalExamBatchRequest(
            exam_codes=[
                "exam"
                for _ in range(main.PROCEDURE_BATCH_MAX_ITEMS + 1)
            ]
        ),
        lambda: main.AuxiliaryTestBatchRequest(
            test_codes=[
                "t" * (main.PROCEDURE_CODE_MAX_CHARS + 1)
            ]
        ),
        lambda: main.ProcedureFreeTextRequest(
            request_text="p" * (main.PROCEDURE_REQUEST_MAX_CHARS + 1)
        ),
        lambda: main.SubmitDiagnosisRequest(
            diagnosis="d" * (main.DIAGNOSIS_MAX_CHARS + 1),
            reasoning="reason",
        ),
        lambda: main.SubmitDiagnosisRequest(
            diagnosis="diagnosis",
            reasoning="r" * (main.DIAGNOSIS_REASONING_MAX_CHARS + 1),
        ),
        lambda: main.HypothesisRequest(
            hypothesis="h" * (main.HYPOTHESIS_MAX_CHARS + 1)
        ),
    ],
)
def test_student_request_models_reject_values_over_declared_boundaries(
    build_request: object,
) -> None:
    with pytest.raises(ValidationError):
        build_request()  # type: ignore[operator]


def test_model_config_and_rag_requests_are_bounded() -> None:
    main.StudentModelConfigTestRequest(
        provider="openai_compatible",
        api_key="k" * main.MODEL_API_KEY_MAX_CHARS,
        model="m" * main.MODEL_NAME_MAX_CHARS,
        base_url="u" * main.MODEL_URL_MAX_CHARS,
        proxy_url="p" * main.MODEL_URL_MAX_CHARS,
    )
    main.AdminRagKnowledgeItemRequest(
        allowed_agents=["coach"] * main.RAG_ALLOWED_AGENTS_MAX_ITEMS,
        tags=["tag"] * main.RAG_TAGS_MAX_ITEMS,
        text="t" * main.RAG_TEXT_MAX_CHARS,
        version=2_147_483_647,
    )

    invalid_requests = [
        lambda: main.StudentModelConfigTestRequest(provider="p" * 65),
        lambda: main.StudentModelConfigTestRequest(
            provider="gemini",
            api_key="k" * (main.MODEL_API_KEY_MAX_CHARS + 1),
        ),
        lambda: main.AdminRagKnowledgeItemRequest(
            allowed_agents=[
                "coach"
                for _ in range(main.RAG_ALLOWED_AGENTS_MAX_ITEMS + 1)
            ]
        ),
        lambda: main.AdminRagKnowledgeItemRequest(
            tags=["tag" for _ in range(main.RAG_TAGS_MAX_ITEMS + 1)]
        ),
        lambda: main.AdminRagKnowledgeItemRequest(
            text="t" * (main.RAG_TEXT_MAX_CHARS + 1)
        ),
        lambda: main.AdminRagKnowledgeItemRequest(version=2_147_483_648),
    ]

    for build_request in invalid_requests:
        with pytest.raises(ValidationError):
            build_request()


def test_admin_case_requests_use_utf8_logical_size_limit() -> None:
    empty_payload_size = len(
        json.dumps(
            {"case": {"text": ""}, "rubric": None},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    exact_size_case = {
        "text": "x" * (main.ADMIN_CASE_REQUEST_MAX_BYTES - empty_payload_size)
    }
    main.AdminCaseValidationRequest(case=exact_size_case)

    with pytest.raises(ValidationError):
        main.AdminCaseValidationRequest(
            case={"text": f"{exact_size_case['text']}x"}
        )

    with pytest.raises(ValidationError):
        main.AdminCaseValidationRequest(case={"text": "中" * 100_000})

    with pytest.raises(ValidationError):
        main.AdminCaseImportRequest(
            case={"text": "x" * 140_000},
            rubric={"text": "x" * 140_000},
        )


def test_previously_strict_admin_request_models_still_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        main.AdminCaseFieldUpdateRequest(case_title="title", unexpected=True)

    with pytest.raises(ValidationError):
        main.AdminRagKnowledgeItemRequest(unexpected=True)


def test_oversized_message_is_rejected_before_service_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_called = False

    def fail_if_called(*args: object, **kwargs: object) -> object:
        nonlocal service_called
        service_called = True
        raise AssertionError("service must not execute")

    monkeypatch.setattr(main.osce_session_service, "handle_message", fail_if_called)
    client = TestClient(main.app)

    response = client.post(
        "/api/sessions/not-reached/message",
        json={"message": "q" * (main.QUESTION_MAX_CHARS + 1)},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": main.REQUEST_VALIDATION_ERROR_DETAIL}
    assert "q" * 64 not in response.text
    assert len(response.content) < 256
    assert service_called is False


def test_validation_response_does_not_reflect_sensitive_model_input() -> None:
    client = TestClient(main.app)
    sensitive_api_key = "SENSITIVE-KEY-" + (
        "k" * main.MODEL_API_KEY_MAX_CHARS
    )

    response = client.post(
        "/api/model-config/test",
        json={
            "provider": "gemini",
            "api_key": sensitive_api_key,
            "model": "gemini-test",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": main.REQUEST_VALIDATION_ERROR_DETAIL}
    assert sensitive_api_key not in response.text
    assert "SENSITIVE-KEY-" not in response.text
    assert len(response.content) < 256


def test_audio_language_is_rejected_before_provider_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_called = False

    def fail_if_called() -> object:
        nonlocal provider_called
        provider_called = True
        raise AssertionError("speech provider must not execute")

    monkeypatch.setattr(
        main,
        "build_dashscope_speech_service_from_environment",
        fail_if_called,
    )
    with TestClient(main.app) as client:
        login_response = client.post(
            "/api/auth/login",
            json={
                "email": "student@osce.test",
                "password": "student",
            },
        )
        assert login_response.status_code == 200
        response = client.post(
            "/api/audio/transcriptions",
            data={"language": "l" * 17},
            files={"file": ("sample.wav", b"audio", "audio/wav")},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": main.REQUEST_VALIDATION_ERROR_DETAIL}
    assert provider_called is False
