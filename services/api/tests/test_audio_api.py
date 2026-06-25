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
        async def synthesize(self, text: str, *, voice: str | None = None, model: str | None = None) -> SpeechSynthesisResult:
            assert text == "我现在右下腹疼。"
            assert voice == "Serena"
            assert model is None
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
