from pathlib import Path

from app.services import model_config_service
from app.services.model_config_service import build_admin_model_config


def test_admin_model_config_reports_anthropic_environment(monkeypatch) -> None:
    monkeypatch.setenv("OSCE_ANTHROPIC_ENABLED", "true")
    monkeypatch.setenv("OSCE_ANTHROPIC_API_KEY", "private-test-key")
    monkeypatch.setenv("OSCE_ANTHROPIC_MODEL", "test-anthropic-model")
    monkeypatch.setenv(
        "OSCE_ANTHROPIC_BASE_URL",
        "https://private-anthropic-gateway.example",
    )
    monkeypatch.setenv(
        "OSCE_ANTHROPIC_PROXY_URL",
        "http://private-proxy.example:8080",
    )

    providers = {
        provider["provider_id"]: provider
        for provider in build_admin_model_config()["providers"]
    }

    anthropic = providers["anthropic"]
    assert anthropic["enabled"] is True
    assert anthropic["configured"] is True
    assert anthropic["secret_configured"] is True
    assert anthropic["model"] == "test-anthropic-model"
    assert anthropic["base_url"] == ""
    assert anthropic["proxy_url"] == ""
    assert "private-test-key" not in str(anthropic)
    assert "private-anthropic-gateway.example" not in str(anthropic)
    assert "private-proxy.example" not in str(anthropic)


def test_admin_model_config_recognizes_one_shared_dashscope_key(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "shared-dashscope-test-key")
    monkeypatch.setenv("OSCE_OPENAI_ENABLED", "true")
    monkeypatch.setenv(
        "OSCE_OPENAI_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setenv("OSCE_OPENAI_MODEL", "qwen-plus")
    monkeypatch.setenv("OSCE_DASHSCOPE_RERANK_ENABLED", "true")

    providers = {
        provider["provider_id"]: provider
        for provider in build_admin_model_config(
            include_retrieval_manifest=False,
        )["providers"]
    }

    text_model = providers["openai_compatible"]
    assert text_model["label"] == "阿里云百炼 Qwen（OpenAI 兼容）"
    assert text_model["configured"] is True
    assert text_model["auth_mode"] == "dashscope_shared_api_key"
    assert providers["dashscope_speech"]["configured"] is True
    assert providers["dashscope_speech"]["auth_mode"] == "dashscope_shared_api_key"
    assert providers["dashscope_rerank"]["configured"] is True
    assert providers["dashscope_rerank"]["auth_mode"] == "dashscope_shared_api_key"
    assert "shared-dashscope-test-key" not in str(providers)


def test_admin_model_config_rejects_shared_key_for_custom_text_gateway(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "must-not-be-used")
    monkeypatch.setenv("OSCE_OPENAI_ENABLED", "true")
    monkeypatch.setenv("OSCE_OPENAI_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("OSCE_OPENAI_MODEL", "custom-model")

    providers = {
        provider["provider_id"]: provider
        for provider in build_admin_model_config(
            include_retrieval_manifest=False,
        )["providers"]
    }

    text_model = providers["openai_compatible"]
    assert text_model["configured"] is False
    assert text_model["secret_configured"] is False
    assert text_model["label"] == "OpenAI 兼容模型"


def test_model_config_can_skip_retrieval_manifest_io(monkeypatch) -> None:
    def reject_manifest_access(**_kwargs) -> dict[str, object]:
        raise AssertionError("readiness must not inspect the retrieval manifest")

    monkeypatch.setattr(
        model_config_service,
        "_chroma_index_manifest_status",
        reject_manifest_access,
    )

    providers = {
        provider["provider_id"]: provider
        for provider in build_admin_model_config(
            include_retrieval_manifest=False,
        )["providers"]
    }

    assert providers["chroma_retrieval"]["index_manifest"] == {}


def test_blank_vertex_embedding_model_keeps_chroma_unconfigured(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_API_KEY", "configured")
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_MODEL", "")
    monkeypatch.setenv("OSCE_CHROMA_ENABLED", "true")

    providers = {
        provider["provider_id"]: provider
        for provider in build_admin_model_config(
            include_retrieval_manifest=False,
        )["providers"]
    }

    assert providers["vertex_embedding_retrieval"]["configured"] is False
    assert providers["chroma_retrieval"]["configured"] is False
    assert "向量模型配置" in providers["chroma_retrieval"]["missing_env"]


def test_env_example_uses_the_anthropic_settings_prefix() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    env_example = (repo_root / ".env.example").read_text(encoding="utf-8")

    assert "\nANTHROPIC_API_KEY=" not in f"\n{env_example}"
    assert "OSCE_ANTHROPIC_ENABLED=false" in env_example
    assert "OSCE_ANTHROPIC_API_KEY=" in env_example
    assert "OSCE_ANTHROPIC_BASE_URL=https://api.anthropic.com" in env_example
    assert "OSCE_ANTHROPIC_MODEL=" in env_example
    assert "OSCE_ANTHROPIC_PROXY_URL=direct" in env_example
