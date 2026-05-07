from __future__ import annotations

import os
from typing import Any

from app.services.chroma_retriever import (
    ChromaRetrievalSettings,
    build_chroma_manifest_status,
    resolve_chroma_persist_directory,
)
from app.services.deployment_config import get_deployment_mode, is_runtime_model_config_write_supported
from app.services.retrieval_index import ROOT_DIR, get_chroma_source_documents
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services.vertex_embedding_retriever import DEFAULT_VERTEX_EMBEDDING_MODEL


def build_admin_model_config() -> dict[str, Any]:
    deployment_mode = get_deployment_mode()
    runtime_write_supported = is_runtime_model_config_write_supported(deployment_mode)
    return {
        "policy": {
            "secrets_persisted": False,
            "runtime_write_supported": runtime_write_supported,
            "configuration_source": "environment_or_runtime_memory" if runtime_write_supported else "environment_only",
            "deployment_mode": deployment_mode,
        },
        "providers": [
            _gemini_patient_api_config(),
            _gemini_patient_vertex_config(),
            _vertex_rubric_scorer_config(),
            _vertex_skill_candidate_config(),
            _vertex_embedding_retrieval_config(),
            _chroma_retrieval_config(),
            _openai_compatible_config(),
        ],
    }


def _gemini_patient_api_config() -> dict[str, Any]:
    api_key_names = ["OSCE_GEMINI_PATIENT_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"]
    secret_configured = _has_any_env(api_key_names)
    use_vertex = _truthy_env("OSCE_GEMINI_PATIENT_USE_VERTEX")
    configured = secret_configured and not use_vertex
    return _provider_config(
        provider_id="gemini_patient_api",
        label="Gemini Developer API",
        capability="标准化病人自然语言改写",
        enabled=not use_vertex and secret_configured,
        configured=configured,
        secret_configured=secret_configured,
        auth_mode="api_key",
        model=_env("OSCE_GEMINI_PATIENT_MODEL", "gemini-3.1-pro-preview"),
        proxy_url=_env("OSCE_GEMINI_PATIENT_PROXY_URL", "http://127.0.0.1:7897"),
        required_env=["OSCE_GEMINI_PATIENT_API_KEY 或 GEMINI_API_KEY 或 GOOGLE_API_KEY"],
        missing_env=[] if configured else ["OSCE_GEMINI_PATIENT_API_KEY 或 GEMINI_API_KEY 或 GOOGLE_API_KEY"],
        integration_status="wired",
        notes="用于学生端问诊时把病例 canonical_answer 改写为标准化病人口吻；密钥只从环境变量读取。",
    )


def _gemini_patient_vertex_config() -> dict[str, Any]:
    runtime_vertex_config = runtime_model_config_store.get_vertex_gemini_config()
    runtime_active = runtime_vertex_config is not None
    enabled = runtime_active or _truthy_env("OSCE_GEMINI_PATIENT_USE_VERTEX")
    vertex_api_key = (
        runtime_vertex_config.api_key
        if runtime_active and runtime_vertex_config.provider == "vertex_gemini_api_key"
        else _env("OSCE_GEMINI_PATIENT_API_KEY") or _env("OSCE_VERTEX_API_KEY")
    )
    project = runtime_vertex_config.project if runtime_active else _env("OSCE_GEMINI_PATIENT_PROJECT") or _env("OSCE_VERTEX_PROJECT")
    model = runtime_vertex_config.model if runtime_active else _env("OSCE_GEMINI_PATIENT_MODEL") or _env("OSCE_VERTEX_MODEL", "gemini-3.1-pro-preview")
    location = runtime_vertex_config.location if runtime_active else _env("OSCE_GEMINI_PATIENT_LOCATION") or _env("OSCE_VERTEX_LOCATION", "global")
    proxy_url = runtime_vertex_config.proxy_url if runtime_active else _env("OSCE_GEMINI_PATIENT_PROXY_URL") or _env("OSCE_VERTEX_PROXY_URL", "http://127.0.0.1:7897")
    secret_configured = bool(vertex_api_key)
    configured = enabled and (bool(project) or secret_configured)
    return _provider_config(
        provider_id="gemini_patient_vertex",
        label="Vertex Gemini 标准化病人",
        capability="标准化病人自然语言改写",
        enabled=enabled,
        configured=configured,
        secret_configured=secret_configured,
        auth_mode="vertex_api_key" if secret_configured else "vertex_adc",
        model=model,
        project=project,
        location=location,
        proxy_url=proxy_url,
        required_env=[
            "OSCE_GEMINI_PATIENT_USE_VERTEX=true",
            "OSCE_GEMINI_PATIENT_PROJECT/OSCE_VERTEX_PROJECT 或 OSCE_GEMINI_PATIENT_API_KEY/OSCE_VERTEX_API_KEY",
        ],
        missing_env=[] if configured else _missing_when_enabled(
            enabled,
            [
                (
                    "OSCE_GEMINI_PATIENT_PROJECT/OSCE_VERTEX_PROJECT 或 OSCE_GEMINI_PATIENT_API_KEY/OSCE_VERTEX_API_KEY",
                    project or ("configured" if secret_configured else ""),
                )
            ],
        ),
        integration_status="wired",
        notes="支持 Google Application Default Credentials 或 Vertex Express/API Key；密钥只来自环境变量或本次运行时内存，不落库也不回显。",
    )


def _vertex_rubric_scorer_config() -> dict[str, Any]:
    runtime_vertex_config = runtime_model_config_store.get_vertex_gemini_config()
    runtime_active = runtime_vertex_config is not None
    enabled = runtime_active or _truthy_env("OSCE_VERTEX_ENABLED")
    vertex_api_key = (
        runtime_vertex_config.api_key
        if runtime_active and runtime_vertex_config.provider == "vertex_gemini_api_key"
        else _env("OSCE_VERTEX_API_KEY")
    )
    project = runtime_vertex_config.project if runtime_active else _env("OSCE_VERTEX_PROJECT")
    model = runtime_vertex_config.model if runtime_active else _env("OSCE_VERTEX_MODEL", "gemini-3.1-pro-preview")
    location = runtime_vertex_config.location if runtime_active else _env("OSCE_VERTEX_LOCATION", "global")
    proxy_url = runtime_vertex_config.proxy_url if runtime_active else _env("OSCE_VERTEX_PROXY_URL", "http://127.0.0.1:7897")
    secret_configured = bool(vertex_api_key)
    configured = enabled and (bool(project) or secret_configured)
    return _provider_config(
        provider_id="vertex_rubric_scorer",
        label="Vertex Gemini LLM 评分",
        capability="llm_rubric 语义评分",
        enabled=enabled,
        configured=configured,
        secret_configured=secret_configured,
        auth_mode="vertex_api_key" if secret_configured else "vertex_adc",
        model=model,
        project=project,
        location=location,
        proxy_url=proxy_url,
        required_env=["OSCE_VERTEX_ENABLED=true", "OSCE_VERTEX_PROJECT 或 OSCE_VERTEX_API_KEY"],
        missing_env=[] if configured else _missing_when_enabled(
            enabled,
            [("OSCE_VERTEX_PROJECT 或 OSCE_VERTEX_API_KEY", project or ("configured" if secret_configured else ""))],
        ),
        integration_status="wired",
        notes="只参与 rubric 中 llm_rubric 项的语义评分；可用 ADC 或 Vertex Express/API Key，规则评分仍由后端确定性执行。",
    )


def _vertex_skill_candidate_config() -> dict[str, Any]:
    runtime_vertex_config = runtime_model_config_store.get_vertex_gemini_config()
    runtime_active = runtime_vertex_config is not None
    enabled = runtime_active or _truthy_env("OSCE_VERTEX_SKILL_CANDIDATE_ENABLED")
    vertex_api_key = (
        runtime_vertex_config.api_key
        if runtime_active and runtime_vertex_config.provider == "vertex_gemini_api_key"
        else _env("OSCE_VERTEX_API_KEY")
    )
    project = runtime_vertex_config.project if runtime_active else _env("OSCE_VERTEX_PROJECT")
    model = runtime_vertex_config.model if runtime_active else _env("OSCE_VERTEX_SKILL_CANDIDATE_MODEL", "gemini-3.1-pro-preview")
    location = runtime_vertex_config.location if runtime_active else _env("OSCE_VERTEX_LOCATION", "global")
    proxy_url = runtime_vertex_config.proxy_url if runtime_active else _env("OSCE_VERTEX_PROXY_URL", "http://127.0.0.1:7897")
    secret_configured = bool(vertex_api_key)
    configured = enabled and (bool(project) or secret_configured)
    return _provider_config(
        provider_id="vertex_skill_candidate",
        label="Vertex Gemini Skill 候选生成",
        capability="训练模式级候选 Skill 文案生成",
        enabled=enabled,
        configured=configured,
        secret_configured=secret_configured,
        auth_mode="vertex_api_key" if secret_configured else "vertex_adc",
        model=model,
        project=project,
        location=location,
        proxy_url=proxy_url,
        required_env=["OSCE_VERTEX_SKILL_CANDIDATE_ENABLED=true", "OSCE_VERTEX_PROJECT 或 OSCE_VERTEX_API_KEY"],
        missing_env=[] if configured else _missing_when_enabled(
            enabled,
            [("OSCE_VERTEX_PROJECT 或 OSCE_VERTEX_API_KEY", project or ("configured" if secret_configured else ""))],
        ),
        integration_status="wired",
        notes="LLM 只生成标题、说明和教学策略；candidate_id、pattern_id 和漏项聚合仍由后端确定性生成。",
    )


def _vertex_embedding_retrieval_config() -> dict[str, Any]:
    enabled = _truthy_env("OSCE_VERTEX_EMBEDDING_ENABLED")
    project = _env("OSCE_VERTEX_EMBEDDING_PROJECT") or _env("OSCE_VERTEX_PROJECT")
    model = _env("OSCE_VERTEX_EMBEDDING_MODEL", "gemini-embedding-001")
    location = _env("OSCE_VERTEX_EMBEDDING_LOCATION") or _env("OSCE_VERTEX_LOCATION", "global")
    proxy_url = _env("OSCE_VERTEX_EMBEDDING_PROXY_URL") or _env("OSCE_VERTEX_PROXY_URL", "http://127.0.0.1:7897")
    configured = enabled and bool(project)
    return _provider_config(
        provider_id="vertex_embedding_retrieval",
        label="Vertex Gemini RAG 向量检索",
        capability="RAG 反馈解释、学习推荐和来源片段召回",
        enabled=enabled,
        configured=configured,
        secret_configured=False,
        auth_mode="vertex_adc",
        model=model,
        project=project,
        location=location,
        proxy_url=proxy_url,
        required_env=["OSCE_VERTEX_EMBEDDING_ENABLED=true", "OSCE_VERTEX_EMBEDDING_PROJECT 或 OSCE_VERTEX_PROJECT"],
        missing_env=[] if configured else _missing_when_enabled(enabled, [("OSCE_VERTEX_EMBEDDING_PROJECT 或 OSCE_VERTEX_PROJECT", project)]),
        integration_status="wired_optional",
        notes="只用于 RAG 来源片段相似度召回；不参与标准诊断、rubric、评分裁判或病例隐藏信息决策。",
    )


def _chroma_retrieval_config() -> dict[str, Any]:
    enabled = _truthy_env("OSCE_CHROMA_ENABLED")
    persist_directory = _env("CHROMA_PERSIST_DIRECTORY", "./data/processed/chroma")
    collection = _env("OSCE_CHROMA_COLLECTION", "clinical_osce_retrieval")
    configured = enabled and bool(persist_directory) and bool(collection)
    index_manifest = _chroma_index_manifest_status(
        persist_directory=persist_directory,
        collection=collection,
    )
    return _provider_config(
        provider_id="chroma_retrieval",
        label="ChromaDB RAG 持久向量库",
        capability="RAG 来源片段持久向量索引和相似度召回",
        enabled=enabled,
        configured=configured,
        secret_configured=False,
        auth_mode="local_persistent_vector_store",
        persist_directory=persist_directory,
        collection=collection,
        index_manifest=index_manifest,
        required_env=["OSCE_CHROMA_ENABLED=true", "CHROMA_PERSIST_DIRECTORY", "OSCE_CHROMA_COLLECTION"],
        missing_env=[] if configured else _missing_when_enabled(
            enabled,
            [("CHROMA_PERSIST_DIRECTORY", persist_directory), ("OSCE_CHROMA_COLLECTION", collection)],
        ),
        integration_status="wired_optional",
        notes="通过本地 ChromaDB PersistentClient 持久化 RAG 来源片段向量；当前搭配 Vertex embedding 使用，只用于反馈解释、学习推荐和引用展示，不参与诊断或评分裁判。",
    )


def _chroma_index_manifest_status(*, persist_directory: str, collection: str) -> dict[str, Any]:
    settings = ChromaRetrievalSettings(
        persist_directory=resolve_chroma_persist_directory(persist_directory, root_dir=ROOT_DIR),
        collection_name=collection,
        embedding_model=_env("OSCE_VERTEX_EMBEDDING_MODEL", DEFAULT_VERTEX_EMBEDDING_MODEL),
    )
    return build_chroma_manifest_status(settings=settings, documents=get_chroma_source_documents())


def _openai_compatible_config() -> dict[str, Any]:
    runtime_config = runtime_model_config_store.get_active_config()
    runtime_active = runtime_config is not None and runtime_config.provider == "openai_compatible"
    enabled = runtime_active or _truthy_env("OSCE_OPENAI_ENABLED")
    secret_configured = runtime_active or bool(_env("OSCE_OPENAI_API_KEY"))
    model = runtime_config.model if runtime_active else _env("OSCE_OPENAI_MODEL")
    base_url = runtime_config.base_url if runtime_active else _env("OSCE_OPENAI_BASE_URL", "https://api.openai.com/v1")
    proxy_url = runtime_config.proxy_url if runtime_active else _env("OSCE_OPENAI_PROXY_URL", "http://127.0.0.1:7897")
    configured = enabled and secret_configured and bool(model)
    return _provider_config(
        provider_id="openai_compatible",
        label="OpenAI 兼容模型",
        capability="标准化病人、llm_rubric 语义评分、训练模式级候选 Skill 文案生成",
        enabled=enabled,
        configured=configured,
        secret_configured=secret_configured,
        auth_mode="api_key",
        model=model,
        base_url=base_url,
        proxy_url=proxy_url,
        required_env=["OSCE_OPENAI_ENABLED=true", "OSCE_OPENAI_API_KEY", "OSCE_OPENAI_MODEL"],
        missing_env=[] if configured else _missing_when_enabled(enabled, [("OSCE_OPENAI_API_KEY", "configured" if secret_configured else ""), ("OSCE_OPENAI_MODEL", model)]),
        integration_status="wired",
        notes="支持环境变量或学生端本次运行时配置；密钥只保存在进程内存，不写入文件或数据库。",
    )


def _provider_config(**kwargs: Any) -> dict[str, Any]:
    return {
        "provider_id": kwargs["provider_id"],
        "label": kwargs["label"],
        "capability": kwargs["capability"],
        "enabled": kwargs["enabled"],
        "configured": kwargs["configured"],
        "secret_configured": kwargs["secret_configured"],
        "auth_mode": kwargs["auth_mode"],
        "model": kwargs.get("model", ""),
        "base_url": kwargs.get("base_url", ""),
        "project": kwargs.get("project", ""),
        "location": kwargs.get("location", ""),
        "proxy_url": kwargs.get("proxy_url", ""),
        "persist_directory": kwargs.get("persist_directory", ""),
        "collection": kwargs.get("collection", ""),
        "index_manifest": kwargs.get("index_manifest", {}),
        "required_env": kwargs["required_env"],
        "missing_env": kwargs["missing_env"],
        "integration_status": kwargs["integration_status"],
        "notes": kwargs["notes"],
    }


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _has_any_env(names: list[str]) -> bool:
    return any(bool(_env(name)) for name in names)


def _truthy_env(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


def _missing_when_enabled(enabled: bool, requirements: list[tuple[str, str]]) -> list[str]:
    if not enabled:
        return []
    return [name for name, value in requirements if not value]


__all__ = ["build_admin_model_config"]
