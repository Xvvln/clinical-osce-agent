from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import main
from app.services.auth_store import AuthStore
from app.services.dashscope_speech_service import SpeechSynthesisResult


@pytest.fixture
def authenticated_client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main, "auth_store", AuthStore(tmp_path / "auth.sqlite3"))
    with TestClient(main.app) as client:
        response = client.post("/api/auth/login", json={"email": "student@osce.test", "password": "student"})
        assert response.status_code == 200
        yield client


def test_transcription_requires_authenticated_user() -> None:
    with TestClient(main.app) as client:
        response = client.post(
            "/api/audio/transcriptions",
            files={"file": ("question.webm", b"audio", "audio/webm")},
        )

    assert response.status_code == 401


def test_transcription_reports_missing_speech_key(authenticated_client: TestClient) -> None:
    response = authenticated_client.post(
        "/api/audio/transcriptions",
        files={"file": ("question.webm", b"audio", "audio/webm")},
    )

    assert response.status_code == 503
    assert "DASHSCOPE_API_KEY 未配置" in response.json()["detail"]


def test_speech_endpoint_streams_audio_bytes(authenticated_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSpeechService:
        async def synthesize(
            self,
            text: str,
            *,
            voice: str | None = None,
            model: str | None = None,
            instructions: str | None = None,
            optimize_instructions: bool | None = None,
        ) -> SpeechSynthesisResult:
            assert text == "我现在右下腹疼。"
            assert voice == "Serena"
            assert model is None
            assert instructions is None
            assert optimize_instructions is None
            return SpeechSynthesisResult(
                audio_bytes=b"RIFFfakewav",
                mime_type="audio/wav",
                provider="dashscope",
                model="qwen3-tts-flash",
                voice="Serena",
                request_id="tts-request-1",
            )

    monkeypatch.setattr(main, "build_dashscope_speech_service_from_environment", lambda: FakeSpeechService())

    response = authenticated_client.post("/api/audio/speech", json={"input": "我现在右下腹疼。", "voice": "Serena"})

    assert response.status_code == 200
    assert response.content == b"RIFFfakewav"
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers["x-osce-speech-provider"] == "dashscope"
    assert response.headers["x-osce-speech-request-id"] == "tts-request-1"


def test_speech_endpoint_uses_patient_profile_and_message_emotion(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_user = authenticated_client.get("/api/auth/me").json()["user"]

    class FakeSessionService:
        def get_session(self, session_id: str) -> dict[str, object]:
            assert session_id == "session-1"
            return {
                "session_id": session_id,
                "student_id": current_user["user_id"],
                "case_id": "appendicitis_001",
                "messages": [
                    {
                        "role": "patient",
                        "content": "我有点害怕，是不是需要马上开刀？",
                        "emotion": "焦虑",
                    }
                ],
            }

    class FakeSpeechService:
        async def synthesize(
            self,
            text: str,
            *,
            voice: str | None = None,
            model: str | None = None,
            instructions: str | None = None,
            optimize_instructions: bool | None = None,
        ) -> SpeechSynthesisResult:
            assert text == "我有点害怕，是不是需要马上开刀？"
            assert voice == "Ethan"
            assert model == "qwen3-tts-instruct-flash"
            assert instructions is not None
            assert "年轻男性患者" in instructions
            assert "焦虑" in instructions or "紧张" in instructions
            assert optimize_instructions is True
            return SpeechSynthesisResult(
                audio_bytes=b"RIFFpatientvoice",
                mime_type="audio/wav",
                provider="dashscope",
                model=model,
                voice=voice,
                request_id="tts-request-patient",
            )

    monkeypatch.setattr(main, "osce_session_service", FakeSessionService())
    monkeypatch.setattr(main, "build_dashscope_speech_service_from_environment", lambda: FakeSpeechService())

    response = authenticated_client.post(
        "/api/audio/speech",
        json={
            "input": "前端文本不能覆盖后端患者消息。",
            "session_id": "session-1",
            "message_index": 0,
        },
    )

    assert response.status_code == 200
    assert response.content == b"RIFFpatientvoice"
    assert response.headers["x-osce-speech-policy"] == "patient_context"
    assert response.headers["x-osce-speech-voice"] == "Ethan"
    assert response.headers["x-osce-speech-patient-gender"] == "male"
    assert response.headers["x-osce-speech-patient-age-band"] == "young_adult"
    assert response.headers["x-osce-speech-emotion"] == "anxious"
