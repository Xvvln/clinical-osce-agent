from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

from app.services import dashscope_speech_service


class FakeHttpResponse:
    def __init__(
        self,
        payload: dict[str, object] | None = None,
        *,
        content: bytes = b"",
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload or {}
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class FakeAsyncClient:
    created_options: list[dict[str, object]] = []
    posts: list[dict[str, object]] = []
    gets: list[str] = []

    def __init__(self, **kwargs: object) -> None:
        self.created_options.append(kwargs)

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeHttpResponse:
        self.posts.append({"url": url, "headers": headers, "json": json})
        if url.endswith("/chat/completions"):
            return FakeHttpResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "疼痛什么时候开始的？",
                                "annotations": [
                                    {
                                        "type": "audio_info",
                                        "language": "zh",
                                        "emotion": "neutral",
                                    }
                                ],
                            }
                        }
                    ],
                    "usage": {"seconds": 1.2},
                }
            )
        return FakeHttpResponse(
            {
                "request_id": "tts-request-1",
                "output": {"audio": {"url": "http://dashscope.example/audio.wav"}},
                "usage": {"characters": 8},
            }
        )

    async def get(self, url: str) -> FakeHttpResponse:
        self.gets.append(url)
        return FakeHttpResponse(content=b"RIFFfakewav", headers={"content-type": "audio/wav"})


class DashScopeSpeechServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeAsyncClient.created_options.clear()
        FakeAsyncClient.posts.clear()
        FakeAsyncClient.gets.clear()

    def test_missing_api_key_fails_before_network_call(self) -> None:
        with self.assertRaises(dashscope_speech_service.SpeechServiceConfigurationError):
            dashscope_speech_service.DashScopeSpeechService(
                dashscope_speech_service.DashScopeSpeechSettings(api_key="")
            )

    @patch.object(dashscope_speech_service.httpx, "AsyncClient", FakeAsyncClient)
    async def test_transcribe_posts_base64_audio_to_dashscope_asr(self) -> None:
        service = dashscope_speech_service.DashScopeSpeechService(
            dashscope_speech_service.DashScopeSpeechSettings(
                api_key="sk-test",
                asr_endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                asr_model="qwen3-asr-flash",
            )
        )

        result = await service.transcribe(b"voice-bytes", mime_type="audio/webm;codecs=opus", filename="question.webm")

        self.assertEqual(result.text, "疼痛什么时候开始的？")
        self.assertEqual(result.language, "zh")
        self.assertEqual(result.duration_seconds, 1.2)
        self.assertEqual(FakeAsyncClient.posts[0]["headers"]["Authorization"], "Bearer sk-test")
        payload = FakeAsyncClient.posts[0]["json"]
        self.assertEqual(payload["model"], "qwen3-asr-flash")
        input_audio = payload["messages"][0]["content"][0]["input_audio"]  # type: ignore[index]
        self.assertEqual(input_audio["format"], "webm")
        self.assertEqual(input_audio["data"], f"data:audio/webm;base64,{base64.b64encode(b'voice-bytes').decode('ascii')}")

    @patch.object(dashscope_speech_service.httpx, "AsyncClient", FakeAsyncClient)
    async def test_transcribe_preserves_ten_mib_audio_capability_outside_text_guard(self) -> None:
        service = dashscope_speech_service.DashScopeSpeechService(
            dashscope_speech_service.DashScopeSpeechSettings(
                api_key="sk-test",
                asr_endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                asr_model="qwen3-asr-flash",
            )
        )
        audio_bytes = b"x" * (10 * 1024 * 1024)

        result = await service.transcribe(
            audio_bytes,
            mime_type="audio/webm",
            filename="ten-mib.webm",
        )

        self.assertEqual(result.text, "疼痛什么时候开始的？")
        payload = FakeAsyncClient.posts[0]["json"]
        input_audio = payload["messages"][0]["content"][0]["input_audio"]  # type: ignore[index]
        encoded_audio = input_audio["data"]
        self.assertGreater(len(encoded_audio.encode("utf-8")), 10 * 1024 * 1024)

    @patch.object(dashscope_speech_service.httpx, "AsyncClient", FakeAsyncClient)
    async def test_synthesize_downloads_dashscope_audio_url(self) -> None:
        service = dashscope_speech_service.DashScopeSpeechService(
            dashscope_speech_service.DashScopeSpeechSettings(
                api_key="sk-test",
                tts_endpoint="https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
                tts_model="qwen3-tts-flash",
                tts_voice="Serena",
            )
        )

        result = await service.synthesize("我现在右下腹疼。")

        self.assertEqual(result.audio_bytes, b"RIFFfakewav")
        self.assertEqual(result.mime_type, "audio/wav")
        self.assertEqual(result.request_id, "tts-request-1")
        self.assertEqual(FakeAsyncClient.gets, ["https://dashscope.example/audio.wav"])
        payload = FakeAsyncClient.posts[0]["json"]
        self.assertEqual(payload["model"], "qwen3-tts-flash")
        self.assertEqual(payload["input"]["voice"], "Serena")  # type: ignore[index]

    @patch.object(dashscope_speech_service.httpx, "AsyncClient", FakeAsyncClient)
    async def test_synthesize_sends_patient_voice_instructions_to_dashscope(self) -> None:
        service = dashscope_speech_service.DashScopeSpeechService(
            dashscope_speech_service.DashScopeSpeechSettings(
                api_key="sk-test",
                tts_endpoint="https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
                tts_model="qwen3-tts-flash",
                tts_voice="Serena",
            )
        )

        await service.synthesize(
            "我有点担心是不是要开刀。",
            voice="Ethan",
            model="qwen3-tts-instruct-flash",
            instructions="年轻男性患者，语气带焦虑和紧张，真实克制，不要播报舞台说明。",
            optimize_instructions=True,
        )

        payload = FakeAsyncClient.posts[0]["json"]
        self.assertEqual(payload["model"], "qwen3-tts-instruct-flash")
        self.assertEqual(payload["input"]["voice"], "Ethan")  # type: ignore[index]
        self.assertEqual(payload["input"]["instructions"], "年轻男性患者，语气带焦虑和紧张，真实克制，不要播报舞台说明。")  # type: ignore[index]
        self.assertIs(payload["input"]["optimize_instructions"], True)  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
