from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

from google import genai
from google.genai import types

DEFAULT_VERTEX_EMBEDDING_LOCATION = "global"
DEFAULT_VERTEX_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY = 3072
DEFAULT_VERTEX_EMBEDDING_PROXY_URL = "http://127.0.0.1:7897"


@dataclass(frozen=True)
class VertexEmbeddingSettings:
    project: str
    location: str = DEFAULT_VERTEX_EMBEDDING_LOCATION
    model: str = DEFAULT_VERTEX_EMBEDDING_MODEL
    output_dimensionality: int = DEFAULT_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY
    proxy_url: str = DEFAULT_VERTEX_EMBEDDING_PROXY_URL


class VertexTextEmbeddingClient:
    def __init__(self, settings: VertexEmbeddingSettings) -> None:
        self._settings = settings
        _apply_process_proxy(settings.proxy_url)
        self._client = genai.Client(
            vertexai=True,
            project=settings.project,
            location=settings.location,
        )

    def embed_texts(self, texts: Sequence[str], *, task_type: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        config = types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=self._settings.output_dimensionality,
        )
        for text in texts:
            response = self._client.models.embed_content(
                model=self._settings.model,
                contents=text,
                config=config,
            )
            if not response.embeddings:
                raise RuntimeError("Vertex embedding response did not include embeddings")
            vectors.append([float(value) for value in response.embeddings[0].values])
        return vectors


def build_vertex_embedding_client_from_environment() -> VertexTextEmbeddingClient | None:
    if not _truthy_env("OSCE_VERTEX_EMBEDDING_ENABLED"):
        return None

    project = _env("OSCE_VERTEX_EMBEDDING_PROJECT") or _env("OSCE_VERTEX_PROJECT")
    if not project:
        return None

    settings = VertexEmbeddingSettings(
        project=project,
        location=_env("OSCE_VERTEX_EMBEDDING_LOCATION") or _env("OSCE_VERTEX_LOCATION", DEFAULT_VERTEX_EMBEDDING_LOCATION),
        model=_env("OSCE_VERTEX_EMBEDDING_MODEL", DEFAULT_VERTEX_EMBEDDING_MODEL),
        output_dimensionality=_int_env("OSCE_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY", DEFAULT_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY),
        proxy_url=_env("OSCE_VERTEX_EMBEDDING_PROXY_URL") or _env("OSCE_VERTEX_PROXY_URL", DEFAULT_VERTEX_EMBEDDING_PROXY_URL),
    )
    return VertexTextEmbeddingClient(settings)


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


def _apply_process_proxy(proxy_url: str) -> None:
    if not _should_use_proxy(proxy_url):
        return
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url
    os.environ["ALL_PROXY"] = proxy_url


def _should_use_proxy(proxy_url: str) -> bool:
    normalized = proxy_url.strip().lower()
    return bool(normalized and normalized not in {"direct", "none", "false", "off", "no"})


__all__ = [
    "DEFAULT_VERTEX_EMBEDDING_MODEL",
    "DEFAULT_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY",
    "VertexEmbeddingSettings",
    "VertexTextEmbeddingClient",
    "build_vertex_embedding_client_from_environment",
]
