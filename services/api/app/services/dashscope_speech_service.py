from __future__ import annotations

import base64
import ipaddress
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit

import httpx

from app.services.api_call_log_service import api_call_log_store
from app.services.dashscope_credential_service import (
    DASHSCOPE_SHARED_API_KEY_ENV_NAME,
    resolve_dashscope_feature_api_key,
)
from app.services.model_call_policy import (
    ModelProviderTimeoutError,
    run_async_model_provider_call,
)

DEFAULT_DASHSCOPE_ASR_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_DASHSCOPE_TTS_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
DEFAULT_DASHSCOPE_ASR_MODEL = "qwen3-asr-flash"
DEFAULT_DASHSCOPE_TTS_MODEL = "qwen3-tts-flash"
DEFAULT_DASHSCOPE_TTS_VOICE = "Serena"
DEFAULT_DASHSCOPE_SPEECH_TIMEOUT_SECONDS = 60.0
MAX_DASHSCOPE_TTS_INSTRUCTIONS_LENGTH = 1000
DASHSCOPE_TRUSTED_AUDIO_HOST_SUFFIX = ".aliyuncs.com"

MIME_FORMAT_MAP = {
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "mp4",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
}

FORMAT_MIME_MAP = {
    "webm": "audio/webm",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "mp4": "audio/mp4",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
}


class DashScopeSpeechServiceError(RuntimeError):
    pass


class SpeechServiceConfigurationError(DashScopeSpeechServiceError):
    pass


@dataclass(frozen=True)
class DashScopeSpeechSettings:
    api_key: str
    asr_endpoint: str = DEFAULT_DASHSCOPE_ASR_ENDPOINT
    tts_endpoint: str = DEFAULT_DASHSCOPE_TTS_ENDPOINT
    asr_model: str = DEFAULT_DASHSCOPE_ASR_MODEL
    tts_model: str = DEFAULT_DASHSCOPE_TTS_MODEL
    tts_voice: str = DEFAULT_DASHSCOPE_TTS_VOICE
    proxy_url: str = "direct"
    timeout_seconds: float = DEFAULT_DASHSCOPE_SPEECH_TIMEOUT_SECONDS


@dataclass(frozen=True)
class SpeechTranscriptionResult:
    text: str
    provider: str
    model: str
    language: str | None = None
    emotion: str | None = None
    duration_seconds: float | None = None
    usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class SpeechSynthesisResult:
    audio_bytes: bytes
    mime_type: str
    provider: str
    model: str
    voice: str
    request_id: str | None = None
    usage: dict[str, Any] | None = None


class DashScopeSpeechService:
    def __init__(self, settings: DashScopeSpeechSettings) -> None:
        if not settings.api_key:
            raise SpeechServiceConfigurationError("DASHSCOPE_API_KEY 未配置，无法使用语音输入或语音播放。")
        self._settings = settings

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str | None = None,
        filename: str | None = None,
        language: str | None = None,
    ) -> SpeechTranscriptionResult:
        if not audio_bytes:
            raise ValueError("没有收到语音文件。")

        audio_format = _audio_format(mime_type, filename)
        audio_mime = _audio_mime(audio_format)
        audio_payload = base64.b64encode(audio_bytes).decode("ascii")
        asr_options: dict[str, Any] = {"enable_itn": True}
        if language:
            asr_options["language"] = language

        payload = {
            "model": self._settings.asr_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": f"data:{audio_mime};base64,{audio_payload}",
                                "format": audio_format,
                            },
                        }
                    ],
                }
            ],
            "stream": False,
            "asr_options": asr_options,
        }

        started_at = time.perf_counter()

        async def send_request() -> tuple[Any, SpeechTranscriptionResult]:
            async with httpx.AsyncClient(**self._client_options()) as client:
                response = await client.post(
                    self._settings.asr_endpoint,
                    headers=self._headers(),
                    json=payload,
                )
            response.raise_for_status()
            return response, _parse_transcription_response(
                response.json(),
                model=self._settings.asr_model,
            )

        try:
            response, result = await run_async_model_provider_call(
                send_request,
                timeout_seconds=self._settings.timeout_seconds,
            )
        except ModelProviderTimeoutError as exc:
            self._record_failure(
                "transcribe",
                self._settings.asr_model,
                self._settings.asr_endpoint,
                started_at,
                exc,
            )
            raise
        except httpx.TimeoutException as exc:
            self._record_failure(
                "transcribe",
                self._settings.asr_model,
                self._settings.asr_endpoint,
                started_at,
                exc,
            )
            raise ModelProviderTimeoutError(
                "DashScope ASR exceeded its total time budget"
            ) from exc
        except Exception as exc:
            self._record_failure(
                "transcribe",
                self._settings.asr_model,
                self._settings.asr_endpoint,
                started_at,
                exc,
            )
            raise DashScopeSpeechServiceError("DashScope ASR 调用失败。") from exc

        self._record_call(
            "transcribe",
            self._settings.asr_model,
            self._settings.asr_endpoint,
            started_at,
            True,
            status_code=response.status_code,
        )
        return result

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        model: str | None = None,
        instructions: str | None = None,
        optimize_instructions: bool | None = None,
    ) -> SpeechSynthesisResult:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("TTS 文本不能为空。")
        selected_model = model.strip() if model else self._settings.tts_model
        selected_voice = voice.strip() if voice else self._settings.tts_voice
        clean_instructions = instructions.strip()[:MAX_DASHSCOPE_TTS_INSTRUCTIONS_LENGTH] if instructions else None
        payload = {
            "model": selected_model,
            "input": {
                "text": clean_text[:2000],
                "voice": selected_voice,
                "language_type": "Chinese",
            },
        }
        if clean_instructions:
            payload["input"]["instructions"] = clean_instructions
        if optimize_instructions is not None:
            payload["input"]["optimize_instructions"] = optimize_instructions

        started_at = time.perf_counter()

        async def send_request() -> tuple[Any, dict[str, Any], bytes, str]:
            async with httpx.AsyncClient(**self._client_options()) as client:
                response = await client.post(
                    self._settings.tts_endpoint,
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                audio_bytes, mime_type = await _resolve_tts_audio(
                    client,
                    data,
                    tts_endpoint=self._settings.tts_endpoint,
                )
            return response, data, audio_bytes, mime_type

        try:
            response, data, audio_bytes, mime_type = (
                await run_async_model_provider_call(
                    send_request,
                    timeout_seconds=self._settings.timeout_seconds,
                )
            )
        except ModelProviderTimeoutError as exc:
            self._record_failure(
                "synthesize",
                selected_model,
                self._settings.tts_endpoint,
                started_at,
                exc,
            )
            raise
        except httpx.TimeoutException as exc:
            self._record_failure(
                "synthesize",
                selected_model,
                self._settings.tts_endpoint,
                started_at,
                exc,
            )
            raise ModelProviderTimeoutError(
                "DashScope TTS exceeded its total time budget"
            ) from exc
        except Exception as exc:
            self._record_failure(
                "synthesize",
                selected_model,
                self._settings.tts_endpoint,
                started_at,
                exc,
            )
            raise DashScopeSpeechServiceError("DashScope TTS 调用失败。") from exc

        self._record_call(
            "synthesize",
            selected_model,
            self._settings.tts_endpoint,
            started_at,
            True,
            status_code=response.status_code,
        )
        return SpeechSynthesisResult(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            provider="dashscope",
            model=selected_model,
            voice=selected_voice,
            request_id=str(data.get("request_id")) if data.get("request_id") else None,
            usage=data.get("usage") if isinstance(data.get("usage"), dict) else None,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Content-Type": "application/json",
        }

    def _client_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "timeout": self._settings.timeout_seconds,
            "trust_env": False,
        }
        if _should_use_proxy(self._settings.proxy_url):
            options["proxy"] = self._settings.proxy_url
        return options

    def _record_call(
        self,
        operation: str,
        model: str,
        endpoint: str,
        started_at: float,
        success: bool,
        error: Exception | None = None,
        status_code: int | None = None,
    ) -> None:
        api_call_log_store.record(
            provider="dashscope_speech",
            operation=operation,
            model=model,
            endpoint=endpoint,
            success=success,
            duration_ms=(time.perf_counter() - started_at) * 1000,
            status_code=status_code,
            error=error,
        )

    def _record_failure(
        self,
        operation: str,
        model: str,
        endpoint: str,
        started_at: float,
        error: Exception,
    ) -> None:
        status_code = (
            error.response.status_code
            if isinstance(error, httpx.HTTPStatusError)
            else None
        )
        safe_error: Exception
        if isinstance(error, (ModelProviderTimeoutError, httpx.TimeoutException)):
            safe_error = ModelProviderTimeoutError(
                "speech provider call exceeded its time budget"
            )
        else:
            safe_error = DashScopeSpeechServiceError(
                "speech provider call failed"
            )
        self._record_call(
            operation,
            model,
            endpoint,
            started_at,
            False,
            safe_error,
            status_code=status_code,
        )


def build_dashscope_speech_service_from_environment() -> DashScopeSpeechService:
    asr_endpoint = _env(
        "OSCE_DASHSCOPE_ASR_ENDPOINT",
        DEFAULT_DASHSCOPE_ASR_ENDPOINT,
    )
    tts_endpoint = _env(
        "OSCE_DASHSCOPE_TTS_ENDPOINT",
        DEFAULT_DASHSCOPE_TTS_ENDPOINT,
    )
    api_key = resolve_dashscope_feature_api_key(
        _env("OSCE_DASHSCOPE_SPEECH_API_KEY"),
        target_urls=(asr_endpoint, tts_endpoint),
        fallback_env_names=(DASHSCOPE_SHARED_API_KEY_ENV_NAME,),
    )
    settings = DashScopeSpeechSettings(
        api_key=api_key,
        asr_endpoint=asr_endpoint,
        tts_endpoint=tts_endpoint,
        asr_model=_env("OSCE_DASHSCOPE_ASR_MODEL", DEFAULT_DASHSCOPE_ASR_MODEL),
        tts_model=_env("OSCE_DASHSCOPE_TTS_MODEL", DEFAULT_DASHSCOPE_TTS_MODEL),
        tts_voice=_env("OSCE_DASHSCOPE_TTS_VOICE", DEFAULT_DASHSCOPE_TTS_VOICE),
        proxy_url=_env("OSCE_DASHSCOPE_SPEECH_PROXY_URL", "direct"),
        timeout_seconds=_float_env("OSCE_DASHSCOPE_SPEECH_TIMEOUT_SECONDS", DEFAULT_DASHSCOPE_SPEECH_TIMEOUT_SECONDS),
    )
    return DashScopeSpeechService(settings)


def _parse_transcription_response(payload: dict[str, Any], *, model: str) -> SpeechTranscriptionResult:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("DashScope ASR response missing choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise RuntimeError("DashScope ASR response missing message")
    text = str(message.get("content") or "").strip()
    annotation = next(
        (
            item
            for item in message.get("annotations", [])
            if isinstance(item, dict) and item.get("type") == "audio_info"
        ),
        {},
    )
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
    seconds = usage.get("seconds") if usage else None
    return SpeechTranscriptionResult(
        text=text,
        provider="dashscope",
        model=model,
        language=str(annotation.get("language")) if annotation.get("language") else None,
        emotion=str(annotation.get("emotion")) if annotation.get("emotion") else None,
        duration_seconds=float(seconds) if isinstance(seconds, int | float) else None,
        usage=usage,
    )


async def _resolve_tts_audio(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
    *,
    tts_endpoint: str,
) -> tuple[bytes, str]:
    audio = payload.get("output", {}).get("audio") if isinstance(payload.get("output"), dict) else None
    if not isinstance(audio, dict):
        raise RuntimeError("DashScope TTS response missing output.audio")

    audio_data = audio.get("data")
    if isinstance(audio_data, str) and audio_data:
        try:
            return base64.b64decode(audio_data), str(audio.get("mime_type") or "audio/wav")
        except ValueError as exc:
            raise RuntimeError("DashScope TTS response contains invalid base64 audio") from exc

    audio_url = audio.get("url")
    if not isinstance(audio_url, str) or not audio_url:
        raise RuntimeError("DashScope TTS response missing audio url")
    audio_url = _validated_tts_audio_url(
        audio_url,
        tts_endpoint=tts_endpoint,
    )

    response = await client.get(audio_url)
    response.raise_for_status()
    mime_type = response.headers.get("content-type", "audio/wav").split(";")[0].strip() or "audio/wav"
    return response.content, mime_type


def _validated_tts_audio_url(audio_url: str, *, tts_endpoint: str) -> str:
    normalized_url = audio_url.strip()
    try:
        parsed = urlsplit(normalized_url)
        endpoint_host = _normalized_url_hostname(urlsplit(tts_endpoint))
        audio_host = _normalized_url_hostname(parsed)
    except ValueError as exc:
        raise RuntimeError("DashScope TTS response contains an invalid audio url") from exc

    if (
        parsed.scheme.lower() != "https"
        or not audio_host
        or parsed.username is not None
        or parsed.password is not None
        or _is_unsafe_audio_host(audio_host)
    ):
        raise RuntimeError("DashScope TTS response contains an untrusted audio url")

    trusted_host = (
        audio_host == endpoint_host
        or audio_host == DASHSCOPE_TRUSTED_AUDIO_HOST_SUFFIX.removeprefix(".")
        or audio_host.endswith(DASHSCOPE_TRUSTED_AUDIO_HOST_SUFFIX)
    )
    if not trusted_host:
        raise RuntimeError("DashScope TTS response contains an untrusted audio url")
    return normalized_url


def _normalized_url_hostname(parsed_url: SplitResult) -> str:
    hostname = str(parsed_url.hostname or "").strip().rstrip(".").lower()
    if not hostname:
        return ""
    try:
        return hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return ""


def _is_unsafe_audio_host(hostname: str) -> bool:
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return not address.is_global


def _audio_format(mime_type: str | None, filename: str | None) -> str:
    clean_mime = (mime_type or "").split(";")[0].strip().lower()
    if clean_mime in MIME_FORMAT_MAP:
        return MIME_FORMAT_MAP[clean_mime]
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if suffix in FORMAT_MIME_MAP:
        return suffix
    return "webm"


def _audio_mime(audio_format: str) -> str:
    return FORMAT_MIME_MAP.get(audio_format, "audio/webm")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _float_env(name: str, default: float) -> float:
    raw_value = _env(name)
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default


def _should_use_proxy(proxy_url: str) -> bool:
    normalized = proxy_url.strip().lower()
    return bool(normalized and normalized not in {"direct", "none", "false", "off", "no"})


__all__ = [
    "DEFAULT_DASHSCOPE_ASR_ENDPOINT",
    "DEFAULT_DASHSCOPE_ASR_MODEL",
    "DEFAULT_DASHSCOPE_TTS_ENDPOINT",
    "DEFAULT_DASHSCOPE_TTS_MODEL",
    "DEFAULT_DASHSCOPE_TTS_VOICE",
    "DashScopeSpeechService",
    "DashScopeSpeechServiceError",
    "DashScopeSpeechSettings",
    "SpeechServiceConfigurationError",
    "SpeechSynthesisResult",
    "SpeechTranscriptionResult",
    "build_dashscope_speech_service_from_environment",
]
