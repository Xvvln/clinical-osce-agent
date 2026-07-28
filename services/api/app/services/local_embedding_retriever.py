from __future__ import annotations

import math
import os
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.services.model_call_policy import (
    BoundedModelCallExecutor,
    run_model_provider_call,
)

DEFAULT_LOCAL_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_LOCAL_EMBEDDING_BATCH_SIZE = 32
DEFAULT_LOCAL_EMBEDDING_MAX_CONCURRENCY = 1
DEFAULT_LOCAL_EMBEDDING_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class LocalEmbeddingSettings:
    model: str = DEFAULT_LOCAL_EMBEDDING_MODEL
    device: str = "cpu"
    cache_folder: str = ""
    batch_size: int = DEFAULT_LOCAL_EMBEDDING_BATCH_SIZE
    timeout_seconds: float = DEFAULT_LOCAL_EMBEDDING_TIMEOUT_SECONDS


class LocalFastEmbedEmbeddingClient:
    def __init__(
        self,
        settings: LocalEmbeddingSettings,
        *,
        executor: BoundedModelCallExecutor,
    ) -> None:
        self._settings = settings
        self._executor = executor
        if settings.cache_folder and not os.environ.get("FASTEMBED_CACHE_PATH"):
            os.environ["FASTEMBED_CACHE_PATH"] = settings.cache_folder
        text_embedding_class = _load_text_embedding_class()
        kwargs: dict[str, object] = {"model_name": settings.model}
        if settings.device.lower() == "cuda":
            kwargs["providers"] = ["CUDAExecutionProvider"]
        self.model = text_embedding_class(**kwargs)

    def embed_texts(self, texts: Sequence[str], *, task_type: str) -> list[list[float]]:
        normalized_texts = [str(text) for text in texts]
        if not normalized_texts:
            return []
        return run_model_provider_call(
            lambda: self._embed_texts(normalized_texts, task_type=task_type),
            timeout_seconds=self._settings.timeout_seconds,
            executor=self._executor,
        )

    def _embed_texts(
        self,
        normalized_texts: list[str],
        *,
        task_type: str,
    ) -> list[list[float]]:
        if task_type == "RETRIEVAL_QUERY" and hasattr(self.model, "query_embed"):
            embeddings = self.model.query_embed(normalized_texts, batch_size=self._settings.batch_size)
        elif task_type == "RETRIEVAL_DOCUMENT" and hasattr(self.model, "passage_embed"):
            embeddings = self.model.passage_embed(normalized_texts, batch_size=self._settings.batch_size)
        else:
            embeddings = self.model.embed(normalized_texts, batch_size=self._settings.batch_size)
        return _vectors_to_float_lists(embeddings)


def build_local_embedding_client_from_environment() -> LocalFastEmbedEmbeddingClient | None:
    if not _truthy_env("OSCE_LOCAL_EMBEDDING_ENABLED"):
        return None
    settings = LocalEmbeddingSettings(
        model=get_local_embedding_model_name_from_environment(),
        device=_env("OSCE_LOCAL_EMBEDDING_DEVICE", "cpu"),
        cache_folder=_env("OSCE_LOCAL_EMBEDDING_CACHE_FOLDER"),
        batch_size=_int_env("OSCE_LOCAL_EMBEDDING_BATCH_SIZE", DEFAULT_LOCAL_EMBEDDING_BATCH_SIZE),
        timeout_seconds=_float_env(
            "OSCE_LOCAL_EMBEDDING_TIMEOUT_SECONDS",
            DEFAULT_LOCAL_EMBEDDING_TIMEOUT_SECONDS,
        ),
    )
    return run_model_provider_call(
        lambda: _cached_client(settings),
        timeout_seconds=settings.timeout_seconds,
        executor=local_embedding_executor,
    )


def get_local_embedding_model_name_from_environment() -> str:
    return _env("OSCE_LOCAL_EMBEDDING_MODEL", DEFAULT_LOCAL_EMBEDDING_MODEL)


@lru_cache(maxsize=4)
def _cached_client(settings: LocalEmbeddingSettings) -> LocalFastEmbedEmbeddingClient:
    return LocalFastEmbedEmbeddingClient(
        settings,
        executor=local_embedding_executor,
    )


def _load_text_embedding_class():
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:  # pragma: no cover - exercised only when optional dependency is absent.
        raise RuntimeError("fastembed is required when OSCE_LOCAL_EMBEDDING_ENABLED=true") from exc
    return TextEmbedding


def _vectors_to_float_lists(embeddings: Any) -> list[list[float]]:
    raw_vectors = embeddings.tolist() if hasattr(embeddings, "tolist") else embeddings
    return [
        [float(value) for value in vector]
        for vector in raw_vectors
    ]


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
    return value if math.isfinite(value) and value > 0 else default


def _float_env(name: str, default: float) -> float:
    raw_value = _env(name)
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        return default
    return value if math.isfinite(value) and value > 0 else default


def _truthy_env(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


LOCAL_EMBEDDING_MAX_CONCURRENCY = _int_env(
    "OSCE_LOCAL_EMBEDDING_MAX_CONCURRENCY",
    DEFAULT_LOCAL_EMBEDDING_MAX_CONCURRENCY,
)
local_embedding_executor = BoundedModelCallExecutor(
    max_concurrency=LOCAL_EMBEDDING_MAX_CONCURRENCY,
    thread_name_prefix="osce-local-embedding",
)


__all__ = [
    "DEFAULT_LOCAL_EMBEDDING_BATCH_SIZE",
    "DEFAULT_LOCAL_EMBEDDING_MAX_CONCURRENCY",
    "DEFAULT_LOCAL_EMBEDDING_MODEL",
    "DEFAULT_LOCAL_EMBEDDING_TIMEOUT_SECONDS",
    "LOCAL_EMBEDDING_MAX_CONCURRENCY",
    "LocalFastEmbedEmbeddingClient",
    "LocalEmbeddingSettings",
    "build_local_embedding_client_from_environment",
    "get_local_embedding_model_name_from_environment",
]
