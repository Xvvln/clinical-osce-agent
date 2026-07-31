from __future__ import annotations

import asyncio
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app.services import dashscope_speech_service
from app.services.api_call_log_service import ApiCallLogStore
from app.services.model_call_policy import (
    ModelProviderTimeoutError,
    model_call_budget,
)


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
                "output": {
                    "audio": {
                        "url": (
                            "https://dashscope-result.oss-cn-hangzhou.aliyuncs.com/"
                            "audio.wav"
                        )
                    }
                },
                "usage": {"characters": 8},
            }
        )

    async def get(self, url: str) -> FakeHttpResponse:
        self.gets.append(url)
        return FakeHttpResponse(content=b"RIFFfakewav", headers={"content-type": "audio/wav"})


class PrivateAudioUrlAsyncClient(FakeAsyncClient):
    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> FakeHttpResponse:
        self.posts.append({"url": url, "headers": headers, "json": json})
        return FakeHttpResponse(
            {
                "request_id": "tts-private-url",
                "output": {
                    "audio": {
                        "url": "https://169.254.169.254/latest/meta-data/"
                    }
                },
            }
        )

    async def get(self, url: str) -> FakeHttpResponse:
        raise AssertionError(f"untrusted audio URL must not be fetched: {url}")


class SlowAudioDownloadAsyncClient(FakeAsyncClient):
    async def get(self, url: str) -> FakeHttpResponse:
        self.gets.append(url)
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class SlowSpeechPostAsyncClient(FakeAsyncClient):
    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> FakeHttpResponse:
        self.posts.append({"url": url, "headers": headers, "json": json})
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class UpstreamFailureAsyncClient(FakeAsyncClient):
    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> httpx.Response:
        self.posts.append({"url": url, "headers": headers, "json": json})
        request = httpx.Request("POST", url)
        return httpx.Response(
            502,
            request=request,
            json={
                "error": {
                    "message": "upstream-secret-patient-context",
                }
            },
        )


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

    @patch.dict(
        "os.environ",
        {"DASHSCOPE_API_KEY": "shared-dashscope-test-key"},
        clear=True,
    )
    def test_environment_builder_reuses_shared_dashscope_key(self) -> None:
        service = (
            dashscope_speech_service.build_dashscope_speech_service_from_environment()
        )

        self.assertEqual(
            service._settings.api_key,
            "shared-dashscope-test-key",
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

    @patch.object(
        dashscope_speech_service.httpx,
        "AsyncClient",
        SlowSpeechPostAsyncClient,
    )
    async def test_transcribe_deadline_covers_async_post(self) -> None:
        service = dashscope_speech_service.DashScopeSpeechService(
            dashscope_speech_service.DashScopeSpeechSettings(
                api_key="sk-test",
                timeout_seconds=60,
            )
        )

        with self.assertRaises(ModelProviderTimeoutError):
            with model_call_budget(0.02):
                await service.transcribe(
                    b"voice-bytes",
                    mime_type="audio/webm",
                )

        self.assertEqual(len(FakeAsyncClient.posts), 1)

    async def test_transcribe_logs_sanitized_diagnostic_without_response_body(
        self,
    ) -> None:
        service = dashscope_speech_service.DashScopeSpeechService(
            dashscope_speech_service.DashScopeSpeechSettings(api_key="sk-test")
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "model_api_calls.jsonl"
            log_store = ApiCallLogStore(log_path)
            with (
                patch.object(
                    dashscope_speech_service,
                    "api_call_log_store",
                    log_store,
                ),
                patch.object(
                    dashscope_speech_service.httpx,
                    "AsyncClient",
                    UpstreamFailureAsyncClient,
                ),
            ):
                with self.assertRaises(
                    dashscope_speech_service.DashScopeSpeechServiceError
                ) as exc_info:
                    await service.transcribe(
                        b"voice-bytes",
                        mime_type="audio/webm",
                    )

            log = log_store.build_admin_payload(limit=1)["logs"][0]
            serialized_log = log_path.read_text(encoding="utf-8")

        self.assertEqual(str(exc_info.exception), "DashScope ASR 调用失败。")
        self.assertEqual(log["status_code"], 502)
        self.assertEqual(
            log["error_type"],
            "DashScopeSpeechServiceError",
        )
        self.assertEqual(
            log["error_message"],
            "speech provider call failed",
        )
        self.assertNotIn(
            "upstream-secret-patient-context",
            serialized_log,
        )

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
        self.assertEqual(
            FakeAsyncClient.gets,
            [
                "https://dashscope-result.oss-cn-hangzhou.aliyuncs.com/"
                "audio.wav"
            ],
        )
        payload = FakeAsyncClient.posts[0]["json"]
        self.assertEqual(payload["model"], "qwen3-tts-flash")
        self.assertEqual(payload["input"]["voice"], "Serena")  # type: ignore[index]

    @patch.object(
        dashscope_speech_service.httpx,
        "AsyncClient",
        PrivateAudioUrlAsyncClient,
    )
    async def test_synthesize_rejects_private_audio_url_before_get(self) -> None:
        service = dashscope_speech_service.DashScopeSpeechService(
            dashscope_speech_service.DashScopeSpeechSettings(api_key="sk-test")
        )

        with self.assertRaises(
            dashscope_speech_service.DashScopeSpeechServiceError
        ):
            await service.synthesize("我现在右下腹疼。")

        self.assertEqual(FakeAsyncClient.gets, [])

    @patch.object(
        dashscope_speech_service.httpx,
        "AsyncClient",
        SlowAudioDownloadAsyncClient,
    )
    async def test_synthesize_deadline_covers_audio_download(self) -> None:
        service = dashscope_speech_service.DashScopeSpeechService(
            dashscope_speech_service.DashScopeSpeechSettings(
                api_key="sk-test",
                timeout_seconds=60,
            )
        )

        with self.assertRaises(ModelProviderTimeoutError):
            with model_call_budget(0.02):
                await service.synthesize("我现在右下腹疼。")

        self.assertEqual(
            FakeAsyncClient.gets,
            [
                "https://dashscope-result.oss-cn-hangzhou.aliyuncs.com/"
                "audio.wav"
            ],
        )

    def test_tts_audio_url_policy_rejects_untrusted_targets(self) -> None:
        rejected_urls = [
            "http://dashscope.aliyuncs.com/audio.wav",
            "https://user:password@dashscope.aliyuncs.com/audio.wav",
            "https://localhost/audio.wav",
            "https://127.0.0.1/audio.wav",
            "https://10.0.0.1/audio.wav",
            "https://169.254.169.254/latest/meta-data/",
            "https://untrusted.example/audio.wav",
        ]

        for audio_url in rejected_urls:
            with self.subTest(audio_url=audio_url):
                with self.assertRaises(RuntimeError):
                    dashscope_speech_service._validated_tts_audio_url(
                        audio_url,
                        tts_endpoint=(
                            "https://dashscope.aliyuncs.com/api/v1/"
                            "services/aigc/multimodal-generation/generation"
                        ),
                    )

    def test_tts_audio_url_policy_accepts_official_and_same_origin_hosts(
        self,
    ) -> None:
        official_url = (
            "https://dashscope-result.oss-cn-hangzhou.aliyuncs.com/"
            "audio.wav?signature=temporary"
        )
        same_origin_url = "https://speech-gateway.example/audio.wav"

        self.assertEqual(
            dashscope_speech_service._validated_tts_audio_url(
                official_url,
                tts_endpoint=(
                    "https://dashscope.aliyuncs.com/api/v1/"
                    "services/aigc/multimodal-generation/generation"
                ),
            ),
            official_url,
        )
        self.assertEqual(
            dashscope_speech_service._validated_tts_audio_url(
                same_origin_url,
                tts_endpoint="https://speech-gateway.example/v1/tts",
            ),
            same_origin_url,
        )

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
