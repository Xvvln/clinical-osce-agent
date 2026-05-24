from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any


DEFAULT_LOCAL_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_LOCAL_EMBEDDING_BATCH_SIZE = 32


@dataclass(frozen=True)
class LocalEmbeddingSettings:
    model: str = DEFAULT_LOCAL_EMBEDDING_MODEL
    device: str = "cpu"
    cache_folder: str = ""
    batch_size: int = DEFAULT_LOCAL_EMBEDDING_BATCH_SIZE


class LocalFastEmbedEmbeddingClient:
    def __init__(self, settings: LocalEmbeddingSettings) -> None:
        self._settings = settings
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
    )
    return _cached_client(settings)


def get_local_embedding_model_name_from_environment() -> str:
    return _env("OSCE_LOCAL_EMBEDDING_MODEL", DEFAULT_LOCAL_EMBEDDING_MODEL)


@lru_cache(maxsize=4)
def _cached_client(settings: LocalEmbeddingSettings) -> LocalFastEmbedEmbeddingClient:
    return LocalFastEmbedEmbeddingClient(settings)


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
    return value if value > 0 else default


def _truthy_env(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


__all__ = [
    "DEFAULT_LOCAL_EMBEDDING_BATCH_SIZE",
    "DEFAULT_LOCAL_EMBEDDING_MODEL",
    "LocalFastEmbedEmbeddingClient",
    "LocalEmbeddingSettings",
    "build_local_embedding_client_from_environment",
    "get_local_embedding_model_name_from_environment",
]
