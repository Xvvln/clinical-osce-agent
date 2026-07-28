from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from threading import Lock

from google import genai
from google.genai import types

from app.services.api_call_log_service import api_call_log_store
from app.services.google_genai_http_options import (
    build_google_genai_http_options,
    require_direct_runtime_vertex_adc_proxy,
)
from app.services.model_call_policy import run_model_provider_call
from app.services.runtime_model_config_store import runtime_model_config_store

DEFAULT_VERTEX_EMBEDDING_LOCATION = "global"
DEFAULT_VERTEX_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY = 3072
DEFAULT_VERTEX_EMBEDDING_PROXY_URL = "http://127.0.0.1:7897"
DEFAULT_VERTEX_EMBEDDING_BATCH_SIZE = 32
MAX_VERTEX_EMBEDDING_BATCH_SIZE = 250
DEFAULT_VERTEX_EMBEDDING_BATCH_MAX_BYTES = 64 * 1024
MAX_VERTEX_EMBEDDING_BATCH_MAX_BYTES = 256 * 1024
DEFAULT_VERTEX_EMBEDDING_QUOTA_COOLDOWN_SECONDS = 90
MAX_VERTEX_EMBEDDING_QUOTA_COOLDOWN_ENTRIES = 128
_vertex_embedding_quota_cooldowns: OrderedDict[tuple[str, ...], float] = OrderedDict()
_vertex_embedding_quota_cooldown_lock = Lock()


class VertexEmbeddingInputTooLargeError(ValueError):
    def __init__(self, *, input_index: int, input_bytes: int, max_bytes: int) -> None:
        self.input_index = input_index
        self.input_bytes = input_bytes
        self.max_bytes = max_bytes
        super().__init__(
            "Vertex embedding input "
            f"at index {input_index} exceeds the UTF-8 byte limit "
            f"({input_bytes} > {max_bytes})"
        )


@dataclass(frozen=True)
class VertexEmbeddingSettings:
    project: str = ""
    api_key: str = ""
    location: str = DEFAULT_VERTEX_EMBEDDING_LOCATION
    model: str = DEFAULT_VERTEX_EMBEDDING_MODEL
    output_dimensionality: int = DEFAULT_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY
    proxy_url: str = DEFAULT_VERTEX_EMBEDDING_PROXY_URL
    batch_size: int = DEFAULT_VERTEX_EMBEDDING_BATCH_SIZE
    batch_max_bytes: int = DEFAULT_VERTEX_EMBEDDING_BATCH_MAX_BYTES


class VertexTextEmbeddingClient:
    def __init__(self, settings: VertexEmbeddingSettings) -> None:
        self._settings = settings
        self._batch_size = _bounded_positive_int(
            settings.batch_size,
            default=DEFAULT_VERTEX_EMBEDDING_BATCH_SIZE,
            maximum=MAX_VERTEX_EMBEDDING_BATCH_SIZE,
        )
        self._batch_max_bytes = _bounded_positive_int(
            settings.batch_max_bytes,
            default=DEFAULT_VERTEX_EMBEDDING_BATCH_MAX_BYTES,
            maximum=MAX_VERTEX_EMBEDDING_BATCH_MAX_BYTES,
        )
        if settings.api_key:
            self._client = genai.Client(
                vertexai=True,
                api_key=settings.api_key,
                http_options=build_google_genai_http_options(settings.proxy_url),
            )
        else:
            self._client = genai.Client(
                vertexai=True,
                project=settings.project,
                location=settings.location,
                http_options=build_google_genai_http_options(settings.proxy_url),
            )

    def embed_texts(self, texts: Sequence[str], *, task_type: str) -> list[list[float]]:
        normalized_texts = [str(text) for text in texts]
        if not normalized_texts:
            return []
        batches = _batch_embedding_texts(
            normalized_texts,
            batch_size=self._batch_size,
            batch_max_bytes=self._batch_max_bytes,
        )
        config = types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=self._settings.output_dimensionality,
        )
        vectors: list[list[float]] = []
        for batch in batches:
            started_at = time.perf_counter()
            try:
                response = run_model_provider_call(
                    lambda batch=batch: self._client.models.embed_content(
                        model=self._settings.model,
                        contents=batch,
                        config=config,
                    )
                )
                if not response.embeddings:
                    raise RuntimeError("Vertex embedding response did not include embeddings")
                batch_vectors = [
                    [float(value) for value in embedding.values]
                    for embedding in response.embeddings
                ]
                if len(batch_vectors) != len(batch):
                    raise RuntimeError(
                        "Vertex embedding response count did not match input text count"
                    )
            except Exception as exc:
                if _is_resource_exhausted_error(exc):
                    mark_vertex_embedding_quota_exhausted(settings=self._settings)
                api_call_log_store.record(
                    provider="vertex_gemini_embedding",
                    operation="embed_content",
                    model=self._settings.model,
                    endpoint="vertex://embed_content",
                    success=False,
                    duration_ms=(time.perf_counter() - started_at) * 1000,
                    error=exc,
                )
                raise
            api_call_log_store.record(
                provider="vertex_gemini_embedding",
                operation="embed_content",
                model=self._settings.model,
                endpoint="vertex://embed_content",
                success=True,
                duration_ms=(time.perf_counter() - started_at) * 1000,
            )
            vectors.extend(batch_vectors)
        return vectors


def build_vertex_embedding_client_from_environment() -> VertexTextEmbeddingClient | None:
    settings = _resolve_vertex_embedding_settings()
    if settings is None or _vertex_embedding_quota_cooldown_active(settings):
        return None
    return VertexTextEmbeddingClient(settings)


def _resolve_vertex_embedding_settings() -> VertexEmbeddingSettings | None:
    runtime_vertex_config = runtime_model_config_store.get_vertex_gemini_config()
    if runtime_vertex_config is not None:
        if runtime_vertex_config.provider == "vertex_gemini_adc":
            require_direct_runtime_vertex_adc_proxy(runtime_vertex_config.proxy_url)
        settings = VertexEmbeddingSettings(
            project=runtime_vertex_config.project,
            api_key=runtime_vertex_config.api_key if runtime_vertex_config.provider == "vertex_gemini_api_key" else "",
            location=_env("OSCE_VERTEX_EMBEDDING_LOCATION") or runtime_vertex_config.location,
            model=_env("OSCE_VERTEX_EMBEDDING_MODEL", DEFAULT_VERTEX_EMBEDDING_MODEL),
            output_dimensionality=_int_env(
                "OSCE_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY",
                DEFAULT_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY,
            ),
            proxy_url=_env("OSCE_VERTEX_EMBEDDING_PROXY_URL")
            or runtime_vertex_config.proxy_url
            or DEFAULT_VERTEX_EMBEDDING_PROXY_URL,
            batch_size=_bounded_int_env(
                "OSCE_VERTEX_EMBEDDING_BATCH_SIZE",
                DEFAULT_VERTEX_EMBEDDING_BATCH_SIZE,
                maximum=MAX_VERTEX_EMBEDDING_BATCH_SIZE,
            ),
            batch_max_bytes=_bounded_int_env(
                "OSCE_VERTEX_EMBEDDING_BATCH_MAX_BYTES",
                DEFAULT_VERTEX_EMBEDDING_BATCH_MAX_BYTES,
                maximum=MAX_VERTEX_EMBEDDING_BATCH_MAX_BYTES,
            ),
        )
        if settings.project or settings.api_key:
            return settings

    if not _truthy_env("OSCE_VERTEX_EMBEDDING_ENABLED"):
        return None

    project = _env("OSCE_VERTEX_EMBEDDING_PROJECT") or _env("OSCE_VERTEX_PROJECT")
    api_key = _env("OSCE_VERTEX_EMBEDDING_API_KEY") or _env("OSCE_VERTEX_API_KEY")
    if not project and not api_key:
        return None

    settings = VertexEmbeddingSettings(
        project=project,
        api_key=api_key,
        location=_env("OSCE_VERTEX_EMBEDDING_LOCATION") or _env("OSCE_VERTEX_LOCATION", DEFAULT_VERTEX_EMBEDDING_LOCATION),
        model=_env("OSCE_VERTEX_EMBEDDING_MODEL", DEFAULT_VERTEX_EMBEDDING_MODEL),
        output_dimensionality=_int_env("OSCE_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY", DEFAULT_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY),
        proxy_url=_env("OSCE_VERTEX_EMBEDDING_PROXY_URL") or _env("OSCE_VERTEX_PROXY_URL", DEFAULT_VERTEX_EMBEDDING_PROXY_URL),
        batch_size=_bounded_int_env(
            "OSCE_VERTEX_EMBEDDING_BATCH_SIZE",
            DEFAULT_VERTEX_EMBEDDING_BATCH_SIZE,
            maximum=MAX_VERTEX_EMBEDDING_BATCH_SIZE,
        ),
        batch_max_bytes=_bounded_int_env(
            "OSCE_VERTEX_EMBEDDING_BATCH_MAX_BYTES",
            DEFAULT_VERTEX_EMBEDDING_BATCH_MAX_BYTES,
            maximum=MAX_VERTEX_EMBEDDING_BATCH_MAX_BYTES,
        ),
    )
    return settings


def mark_vertex_embedding_quota_exhausted(
    *,
    settings: VertexEmbeddingSettings | None = None,
    cooldown_seconds: int = DEFAULT_VERTEX_EMBEDDING_QUOTA_COOLDOWN_SECONDS,
) -> None:
    active_settings = settings or _resolve_vertex_embedding_settings()
    if active_settings is None:
        return
    cooldown_key = _vertex_embedding_quota_cooldown_key(active_settings)
    now = time.time()
    with _vertex_embedding_quota_cooldown_lock:
        _prune_vertex_embedding_quota_cooldowns(now)
        current_until = _vertex_embedding_quota_cooldowns.pop(cooldown_key, 0.0)
        _vertex_embedding_quota_cooldowns[cooldown_key] = max(
            current_until,
            now + max(cooldown_seconds, 1),
        )
        while len(_vertex_embedding_quota_cooldowns) > MAX_VERTEX_EMBEDDING_QUOTA_COOLDOWN_ENTRIES:
            _vertex_embedding_quota_cooldowns.popitem(last=False)


def clear_vertex_embedding_quota_cooldown() -> None:
    with _vertex_embedding_quota_cooldown_lock:
        _vertex_embedding_quota_cooldowns.clear()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int_env(name: str, default: int) -> int:
    raw_value = _env(name)
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default


def _bounded_int_env(name: str, default: int, *, maximum: int) -> int:
    raw_value = _env(name)
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return _bounded_positive_int(value, default=default, maximum=maximum)


def _bounded_positive_int(value: int, *, default: int, maximum: int) -> int:
    if value <= 0:
        return default
    return min(value, maximum)


def _batch_embedding_texts(
    texts: Sequence[str],
    *,
    batch_size: int,
    batch_max_bytes: int,
) -> list[list[str]]:
    text_sizes: list[int] = []
    for input_index, text in enumerate(texts):
        encoded_text_bytes = _embedding_text_json_bytes(text)
        input_bytes = encoded_text_bytes + 2
        if input_bytes > batch_max_bytes:
            raise VertexEmbeddingInputTooLargeError(
                input_index=input_index,
                input_bytes=input_bytes,
                max_bytes=batch_max_bytes,
            )
        text_sizes.append(encoded_text_bytes)

    batches: list[list[str]] = []
    current_batch: list[str] = []
    current_batch_bytes = 2
    for text, encoded_text_bytes in zip(texts, text_sizes, strict=True):
        exceeds_item_limit = len(current_batch) >= batch_size
        exceeds_byte_limit = (
            current_batch_bytes
            + (1 if current_batch else 0)
            + encoded_text_bytes
            > batch_max_bytes
        )
        if current_batch and (exceeds_item_limit or exceeds_byte_limit):
            batches.append(current_batch)
            current_batch = []
            current_batch_bytes = 2
        if current_batch:
            current_batch_bytes += 1
        current_batch.append(text)
        current_batch_bytes += encoded_text_bytes
    if current_batch:
        batches.append(current_batch)
    return batches


def _embedding_text_json_bytes(text: str) -> int:
    return len(
        json.dumps(
            text,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _truthy_env(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


def _vertex_embedding_quota_cooldown_active(settings: VertexEmbeddingSettings) -> bool:
    now = time.time()
    cooldown_key = _vertex_embedding_quota_cooldown_key(settings)
    with _vertex_embedding_quota_cooldown_lock:
        _prune_vertex_embedding_quota_cooldowns(now)
        cooldown_until = _vertex_embedding_quota_cooldowns.get(cooldown_key, 0.0)
        if cooldown_until > now:
            _vertex_embedding_quota_cooldowns.move_to_end(cooldown_key)
            return True
        return False


def _vertex_embedding_quota_cooldown_key(settings: VertexEmbeddingSettings) -> tuple[str, ...]:
    credential_identity = (
        f"api_key:{sha256(settings.api_key.encode('utf-8')).hexdigest()}"
        if settings.api_key
        else f"project:{settings.project}"
    )
    return (
        credential_identity,
        settings.location,
        settings.model,
    )


def _prune_vertex_embedding_quota_cooldowns(now: float) -> None:
    expired_keys = [
        cooldown_key
        for cooldown_key, cooldown_until in _vertex_embedding_quota_cooldowns.items()
        if cooldown_until <= now
    ]
    for cooldown_key in expired_keys:
        _vertex_embedding_quota_cooldowns.pop(cooldown_key, None)


def _is_resource_exhausted_error(error: BaseException) -> bool:
    message = str(error)
    return "RESOURCE_EXHAUSTED" in message or "quota exceeded" in message.lower()


__all__ = [
    "DEFAULT_VERTEX_EMBEDDING_BATCH_MAX_BYTES",
    "DEFAULT_VERTEX_EMBEDDING_BATCH_SIZE",
    "DEFAULT_VERTEX_EMBEDDING_QUOTA_COOLDOWN_SECONDS",
    "DEFAULT_VERTEX_EMBEDDING_MODEL",
    "DEFAULT_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY",
    "MAX_VERTEX_EMBEDDING_BATCH_MAX_BYTES",
    "MAX_VERTEX_EMBEDDING_BATCH_SIZE",
    "VertexEmbeddingInputTooLargeError",
    "VertexEmbeddingSettings",
    "VertexTextEmbeddingClient",
    "build_vertex_embedding_client_from_environment",
    "clear_vertex_embedding_quota_cooldown",
    "mark_vertex_embedding_quota_exhausted",
]
