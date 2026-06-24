from __future__ import annotations

import os
from typing import Any

from app.services.chroma_retriever import (
    ChromaRetrievalSettings,
    build_chroma_manifest_status,
    resolve_chroma_persist_directory,
)
from app.services.dashscope_reranker import (
    DEFAULT_DASHSCOPE_RERANK_BASE_URL,
    DEFAULT_DASHSCOPE_RERANK_CANDIDATE_K,
    DEFAULT_DASHSCOPE_RERANK_MODEL,
    DEFAULT_DASHSCOPE_RERANK_TOP_K,
)
from app.services.deployment_config import get_deployment_mode, is_runtime_model_config_write_supported
from app.services.local_embedding_retriever import DEFAULT_LOCAL_EMBEDDING_MODEL
from app.services.retrieval_index import ROOT_DIR, get_chroma_source_documents
from app.services.vertex_embedding_retriever import DEFAULT_VERTEX_EMBEDDING_MODEL


def build_admin_model_config() -> dict[str, Any]:
    deployment_mode = get_deployment_mode()
    runtime_write_supported = is_runtime_model_config_write_supported(deployment_mode)
    return {
        "policy": {
            "secrets_persisted": False,
            "runtime_write_supported": runtime_write_supported,
            "configuration_source": "environment_default_only",
            "account_runtime_scope": "per_authenticated_user",
            "account_runtime_visible": False,
            "deployment_mode": deployment_mode,
        },
        "providers": [
            _gemini_patient_api_config(),
            _gemini_patient_vertex_config(),
            _vertex_rubric_scorer_config(),
            _vertex_skill_candidate_config(),
            _vertex_embedding_retrieval_config(),
            _local_embedding_retrieval_config(),
            _chroma_retrieval_config(),
            _dashscope_rerank_config(),
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
        capability="标准化病人自然语言改写、TeacherAgent 教学提示生成",
        enabled=not use_vertex and secret_configured,
        configured=configured,
        secret_configured=secret_configured,
        auth_mode="api_key",
        model=_env("OSCE_GEMINI_PATIENT_MODEL", "gemini-3.1-pro-preview"),
        proxy_url=_env("OSCE_GEMINI_PATIENT_PROXY_URL", "http://127.0.0.1:7897"),
        required_env=["OSCE_GEMINI_PATIENT_API_KEY 或 GEMINI_API_KEY 或 GOOGLE_API_KEY"],
        missing_env=[] if configured else ["OSCE_GEMINI_PATIENT_API_KEY 或 GEMINI_API_KEY 或 GOOGLE_API_KEY"],
        integration_status="wired",
        notes="用于学生端问诊时把病例 canonical_answer 改写为标准化病人口吻，并生成受控 TeacherAgent 教学提示；密钥只从环境变量读取。",
    )


def _gemini_patient_vertex_config() -> dict[str, Any]:
    enabled = _truthy_env("OSCE_GEMINI_PATIENT_USE_VERTEX")
    vertex_api_key = _env("OSCE_GEMINI_PATIENT_API_KEY") or _env("OSCE_VERTEX_API_KEY")
    project = _env("OSCE_GEMINI_PATIENT_PROJECT") or _env("OSCE_VERTEX_PROJECT")
    model = _env("OSCE_GEMINI_PATIENT_MODEL") or _env("OSCE_VERTEX_MODEL", "gemini-3.1-pro-preview")
    location = _env("OSCE_GEMINI_PATIENT_LOCATION") or _env("OSCE_VERTEX_LOCATION", "global")
    proxy_url = _env("OSCE_GEMINI_PATIENT_PROXY_URL") or _env("OSCE_VERTEX_PROXY_URL", "http://127.0.0.1:7897")
    secret_configured = bool(vertex_api_key)
    configured = enabled and (bool(project) or secret_configured)
    return _provider_config(
        provider_id="gemini_patient_vertex",
        label="Vertex Gemini 标准化病人",
        capability="标准化病人自然语言改写、Turn Intent 意图识别、TeacherAgent 教学提示生成",
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
        notes="服务端默认能力支持 Google Application Default Credentials 或 Vertex Express/API Key；账号级 API 配置不在本页展示。",
    )


def _vertex_rubric_scorer_config() -> dict[str, Any]:
    enabled = _truthy_env("OSCE_VERTEX_ENABLED")
    vertex_api_key = _env("OSCE_VERTEX_API_KEY")
    project = _env("OSCE_VERTEX_PROJECT")
    model = _env("OSCE_VERTEX_MODEL", "gemini-3.1-pro-preview")
    location = _env("OSCE_VERTEX_LOCATION", "global")
    proxy_url = _env("OSCE_VERTEX_PROXY_URL", "http://127.0.0.1:7897")
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
    enabled = _truthy_env("OSCE_VERTEX_SKILL_CANDIDATE_ENABLED")
    vertex_api_key = _env("OSCE_VERTEX_API_KEY")
    project = _env("OSCE_VERTEX_PROJECT")
    model = _env("OSCE_VERTEX_SKILL_CANDIDATE_MODEL", "gemini-3.1-pro-preview")
    location = _env("OSCE_VERTEX_LOCATION", "global")
    proxy_url = _env("OSCE_VERTEX_PROXY_URL", "http://127.0.0.1:7897")
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
    vertex_api_key = _env("OSCE_VERTEX_EMBEDDING_API_KEY") or _env("OSCE_VERTEX_API_KEY")
    project = _env("OSCE_VERTEX_EMBEDDING_PROJECT") or _env("OSCE_VERTEX_PROJECT")
    model = _env("OSCE_VERTEX_EMBEDDING_MODEL", "gemini-embedding-001")
    location = _env("OSCE_VERTEX_EMBEDDING_LOCATION") or _env("OSCE_VERTEX_LOCATION", "global")
    proxy_url = _env("OSCE_VERTEX_EMBEDDING_PROXY_URL") or _env("OSCE_VERTEX_PROXY_URL", "http://127.0.0.1:7897")
    secret_configured = bool(vertex_api_key)
    configured = enabled and bool(project or secret_configured)
    return _provider_config(
        provider_id="vertex_embedding_retrieval",
        label="Vertex Gemini RAG 向量检索",
        capability="RAG 反馈解释、学习推荐和来源片段召回",
        enabled=enabled,
        configured=configured,
        secret_configured=secret_configured,
        auth_mode="vertex_api_key" if secret_configured else "vertex_adc",
        model=model,
        project=project,
        location=location,
        proxy_url=proxy_url,
        required_env=["OSCE_VERTEX_EMBEDDING_ENABLED=true + OSCE_VERTEX_EMBEDDING_PROJECT/OSCE_VERTEX_PROJECT 或 OSCE_VERTEX_EMBEDDING_API_KEY/OSCE_VERTEX_API_KEY"],
        missing_env=[] if configured else _missing_when_enabled(
            enabled,
            [("OSCE_VERTEX_EMBEDDING_PROJECT/OSCE_VERTEX_PROJECT 或 OSCE_VERTEX_EMBEDDING_API_KEY/OSCE_VERTEX_API_KEY", project or ("configured" if secret_configured else ""))],
        ),
        integration_status="wired_optional",
        notes="只用于 RAG 来源片段相似度召回；不参与标准诊断、rubric、评分裁判或病例隐藏信息决策。",
    )


def _chroma_retrieval_config() -> dict[str, Any]:
    embedding_configured = _embedding_retrieval_available()
    enabled = _chroma_enabled(embedding_configured=embedding_configured)
    persist_directory = _env("CHROMA_PERSIST_DIRECTORY", "./data/processed/chroma")
    collection = _env("OSCE_CHROMA_COLLECTION", "clinical_osce_retrieval")
    configured = enabled and embedding_configured and bool(persist_directory) and bool(collection)
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
        required_env=["运行态 Vertex/Embedding 配置；OSCE_CHROMA_ENABLED 可显式关闭或开启", "CHROMA_PERSIST_DIRECTORY", "OSCE_CHROMA_COLLECTION"],
        missing_env=[] if configured else _missing_when_enabled(
            enabled,
            [
                ("向量模型配置", "configured" if embedding_configured else ""),
                ("CHROMA_PERSIST_DIRECTORY", persist_directory),
                ("OSCE_CHROMA_COLLECTION", collection),
            ],
        ),
        integration_status="wired_optional",
        notes="通过本地 ChromaDB PersistentClient 持久化 RAG 来源片段向量；当前搭配 Vertex embedding 使用，只用于反馈解释、学习推荐和引用展示，不参与诊断或评分裁判。",
    )


def _dashscope_rerank_config() -> dict[str, Any]:
    enabled = _truthy_env("OSCE_DASHSCOPE_RERANK_ENABLED")
    api_key = _env("OSCE_DASHSCOPE_RERANK_API_KEY") or _env("DASHSCOPE_API_KEY")
    base_url = _env("OSCE_DASHSCOPE_RERANK_BASE_URL", DEFAULT_DASHSCOPE_RERANK_BASE_URL)
    model = _env("OSCE_DASHSCOPE_RERANK_MODEL", DEFAULT_DASHSCOPE_RERANK_MODEL)
    top_k = _env("OSCE_DASHSCOPE_RERANK_TOP_K", str(DEFAULT_DASHSCOPE_RERANK_TOP_K))
    candidate_k = _env("OSCE_DASHSCOPE_RERANK_CANDIDATE_K", str(DEFAULT_DASHSCOPE_RERANK_CANDIDATE_K))
    proxy_url = _env("OSCE_DASHSCOPE_RERANK_PROXY_URL", "direct")
    secret_configured = bool(api_key)
    configured = enabled and secret_configured and bool(base_url) and bool(model)
    return _provider_config(
        provider_id="dashscope_rerank",
        label="DashScope Qwen3 RAG 重排序",
        capability="对向量召回候选片段做可选 rerank，提升 RAG 来源片段排序质量",
        enabled=enabled,
        configured=configured,
        secret_configured=secret_configured,
        auth_mode="api_key",
        model=model,
        base_url=base_url,
        proxy_url=proxy_url,
        required_env=[
            "OSCE_DASHSCOPE_RERANK_ENABLED=true",
            "OSCE_DASHSCOPE_RERANK_API_KEY 或 DASHSCOPE_API_KEY",
            "OSCE_DASHSCOPE_RERANK_BASE_URL",
            "OSCE_DASHSCOPE_RERANK_MODEL",
        ],
        missing_env=[] if configured else _missing_when_enabled(
            enabled,
            [
                ("OSCE_DASHSCOPE_RERANK_API_KEY 或 DASHSCOPE_API_KEY", "configured" if secret_configured else ""),
                ("OSCE_DASHSCOPE_RERANK_BASE_URL", base_url),
                ("OSCE_DASHSCOPE_RERANK_MODEL", model),
            ],
        ),
        integration_status="wired_optional",
        notes=f"默认关闭；开启后先召回最多 {candidate_k} 个候选，再重排返回最多 {top_k} 个结果。失败时回退原向量排序，不参与评分裁判。",
    )


def _vertex_embedding_retrieval_available() -> bool:
    if not _truthy_env("OSCE_VERTEX_EMBEDDING_ENABLED"):
        return False
    return bool(_env("OSCE_VERTEX_EMBEDDING_PROJECT") or _env("OSCE_VERTEX_PROJECT") or _env("OSCE_VERTEX_EMBEDDING_API_KEY") or _env("OSCE_VERTEX_API_KEY"))


def _local_embedding_retrieval_config() -> dict[str, Any]:
    enabled = _truthy_env("OSCE_LOCAL_EMBEDDING_ENABLED")
    model = _env("OSCE_LOCAL_EMBEDDING_MODEL", DEFAULT_LOCAL_EMBEDDING_MODEL)
    device = _env("OSCE_LOCAL_EMBEDDING_DEVICE", "cpu")
    cache_folder = _env("OSCE_LOCAL_EMBEDDING_CACHE_FOLDER")
    configured = enabled and bool(model)
    return _provider_config(
        provider_id="local_embedding_retrieval",
        label="本地开源 RAG 向量模型",
        capability="用本地 fastembed / ONNX 模型为 RAG 来源片段和查询生成向量",
        enabled=enabled,
        configured=configured,
        secret_configured=False,
        auth_mode="local_fastembed",
        model=model,
        device=device,
        cache_folder=cache_folder,
        required_env=["OSCE_LOCAL_EMBEDDING_ENABLED=true", "OSCE_LOCAL_EMBEDDING_MODEL"],
        missing_env=[] if configured else _missing_when_enabled(enabled, [("OSCE_LOCAL_EMBEDDING_MODEL", model)]),
        integration_status="wired_optional",
        notes="本地 CPU 推理，不依赖 Google/Vertex；只用于 RAG 相似度召回，不参与诊断或评分裁判。",
    )


def _local_embedding_retrieval_available() -> bool:
    return _truthy_env("OSCE_LOCAL_EMBEDDING_ENABLED") and bool(_env("OSCE_LOCAL_EMBEDDING_MODEL", DEFAULT_LOCAL_EMBEDDING_MODEL))


def _embedding_retrieval_available() -> bool:
    return _vertex_embedding_retrieval_available() or _local_embedding_retrieval_available()


def _chroma_enabled(*, embedding_configured: bool) -> bool:
    raw_enabled = _env("OSCE_CHROMA_ENABLED")
    if raw_enabled:
        return raw_enabled.lower() in {"1", "true", "yes", "on"}
    return embedding_configured


def _chroma_index_manifest_status(*, persist_directory: str, collection: str) -> dict[str, Any]:
    settings = ChromaRetrievalSettings(
        persist_directory=resolve_chroma_persist_directory(persist_directory, root_dir=ROOT_DIR),
        collection_name=collection,
        embedding_model=_configured_embedding_model_name(),
    )
    return build_chroma_manifest_status(settings=settings, documents=get_chroma_source_documents())


def _configured_embedding_model_name() -> str:
    if _vertex_embedding_retrieval_available():
        return _env("OSCE_VERTEX_EMBEDDING_MODEL", DEFAULT_VERTEX_EMBEDDING_MODEL)
    if _local_embedding_retrieval_available():
        return _env("OSCE_LOCAL_EMBEDDING_MODEL", DEFAULT_LOCAL_EMBEDDING_MODEL)
    return _env("OSCE_VERTEX_EMBEDDING_MODEL", DEFAULT_VERTEX_EMBEDDING_MODEL)


def _openai_compatible_config() -> dict[str, Any]:
    enabled = _truthy_env("OSCE_OPENAI_ENABLED")
    secret_configured = bool(_env("OSCE_OPENAI_API_KEY"))
    model = _env("OSCE_OPENAI_MODEL")
    configured = enabled and secret_configured and bool(model)
    return _provider_config(
        provider_id="openai_compatible",
        label="OpenAI 兼容模型",
        capability="标准化病人、Turn Intent 意图识别、TeacherAgent 教学提示、llm_rubric 语义评分、训练模式级候选 Skill 文案生成",
        enabled=enabled,
        configured=configured,
        secret_configured=secret_configured,
        auth_mode="api_key",
        model=model,
        base_url="",
        proxy_url="",
        required_env=["OSCE_OPENAI_ENABLED=true", "OSCE_OPENAI_API_KEY", "OSCE_OPENAI_MODEL"],
        missing_env=[] if configured else _missing_when_enabled(enabled, [("OSCE_OPENAI_API_KEY", "configured" if secret_configured else ""), ("OSCE_OPENAI_MODEL", model)]),
        integration_status="wired",
        notes="这里只展示服务端环境变量默认能力和配置状态；私有网关地址、代理地址和密钥不通过管理端回显。",
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
        "device": kwargs.get("device", ""),
        "cache_folder": kwargs.get("cache_folder", ""),
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
