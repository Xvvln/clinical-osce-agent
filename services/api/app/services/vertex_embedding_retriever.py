from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

from google import genai
from google.genai import types

from app.services.runtime_model_config_store import runtime_model_config_store

DEFAULT_VERTEX_EMBEDDING_LOCATION = "global"
DEFAULT_VERTEX_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY = 3072
DEFAULT_VERTEX_EMBEDDING_PROXY_URL = "http://127.0.0.1:7897"


@dataclass(frozen=True)
class VertexEmbeddingSettings:
    project: str = ""
    api_key: str = ""
    location: str = DEFAULT_VERTEX_EMBEDDING_LOCATION
    model: str = DEFAULT_VERTEX_EMBEDDING_MODEL
    output_dimensionality: int = DEFAULT_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY
    proxy_url: str = DEFAULT_VERTEX_EMBEDDING_PROXY_URL


class VertexTextEmbeddingClient:
    def __init__(self, settings: VertexEmbeddingSettings) -> None:
        self._settings = settings
        _apply_process_proxy(settings.proxy_url)
        if settings.api_key:
            self._client = genai.Client(vertexai=True, api_key=settings.api_key)
        else:
            self._client = genai.Client(
                vertexai=True,
                project=settings.project,
                location=settings.location,
            )

    def embed_texts(self, texts: Sequence[str], *, task_type: str) -> list[list[float]]:
        normalized_texts = [str(text) for text in texts]
        if not normalized_texts:
            return []
        config = types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=self._settings.output_dimensionality,
        )
        response = self._client.models.embed_content(
            model=self._settings.model,
            contents=normalized_texts,
            config=config,
        )
        if not response.embeddings:
            raise RuntimeError("Vertex embedding response did not include embeddings")
        vectors = [[float(value) for value in embedding.values] for embedding in response.embeddings]
        if len(vectors) != len(normalized_texts):
            raise RuntimeError("Vertex embedding response count did not match input text count")
        return vectors


def build_vertex_embedding_client_from_environment() -> VertexTextEmbeddingClient | None:
    runtime_vertex_config = runtime_model_config_store.get_vertex_gemini_config()
    if runtime_vertex_config is not None:
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
        )
        if settings.project or settings.api_key:
            return VertexTextEmbeddingClient(settings)

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
