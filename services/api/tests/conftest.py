import pytest

from app import main
from app.services.osce_session_service import osce_session_service
from app.services.runtime_model_config_store import runtime_model_config_store
from app.services.training_skill_candidate_store import TrainingSkillCandidateStore
from app.services.user_model_config_store import UserModelConfigStore


@pytest.fixture(autouse=True)
def clear_runtime_model_config_store(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    test_user_model_config_store = UserModelConfigStore(tmp_path / "user_model_configs.sqlite3")
    test_skill_candidate_store = TrainingSkillCandidateStore(tmp_path / "training_skill_candidates.sqlite3")
    monkeypatch.setattr(main, "user_model_config_store", test_user_model_config_store)
    monkeypatch.setattr(main, "training_skill_candidate_store", test_skill_candidate_store, raising=False)
    monkeypatch.setattr(osce_session_service, "training_skill_candidate_store", test_skill_candidate_store, raising=False)
    runtime_model_config_store.clear()
    for env_name in [
        "CLINICAL_OSCE_DEPLOYMENT_MODE",
        "CLINICAL_OSCE_SERVER_MANAGED_MODEL_CONFIG",
        "CLINICAL_OSCE_ADMIN_EMAILS",
        "CLINICAL_OSCE_DEMO_ADMIN_ENABLED",
        "CLINICAL_OSCE_DEMO_ADMIN_EMAIL",
        "CLINICAL_OSCE_DEMO_ADMIN_PASSWORD",
        "OSCE_OPENAI_ENABLED",
        "OSCE_OPENAI_API_KEY",
        "OSCE_OPENAI_BASE_URL",
        "OSCE_OPENAI_MODEL",
        "OSCE_OPENAI_PROXY_URL",
        "OSCE_OPENAI_FALLBACK_ENABLED",
        "OSCE_OPENAI_FALLBACK_API_KEY",
        "OSCE_OPENAI_FALLBACK_BASE_URL",
        "OSCE_OPENAI_FALLBACK_MODEL",
        "OSCE_OPENAI_FALLBACK_PROXY_URL",
        "OSCE_ANTHROPIC_ENABLED",
        "OSCE_ANTHROPIC_API_KEY",
        "OSCE_ANTHROPIC_BASE_URL",
        "OSCE_ANTHROPIC_MODEL",
        "OSCE_ANTHROPIC_PROXY_URL",
        "OSCE_GEMINI_PATIENT_API_KEY",
        "OSCE_GEMINI_PATIENT_USE_VERTEX",
        "OSCE_GEMINI_PATIENT_PROJECT",
        "OSCE_GEMINI_PATIENT_LOCATION",
        "OSCE_GEMINI_PATIENT_MODEL",
        "OSCE_GEMINI_PATIENT_PROXY_URL",
        "OSCE_VERTEX_ENABLED",
        "OSCE_VERTEX_API_KEY",
        "OSCE_VERTEX_PROJECT",
        "OSCE_VERTEX_LOCATION",
        "OSCE_VERTEX_MODEL",
        "OSCE_VERTEX_PROXY_URL",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OSCE_VERTEX_EMBEDDING_ENABLED",
        "OSCE_VERTEX_EMBEDDING_PROJECT",
        "OSCE_VERTEX_EMBEDDING_MODEL",
        "OSCE_VERTEX_EMBEDDING_LOCATION",
        "OSCE_VERTEX_EMBEDDING_PROXY_URL",
        "OSCE_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY",
        "OSCE_LOCAL_EMBEDDING_ENABLED",
        "OSCE_LOCAL_EMBEDDING_MODEL",
        "OSCE_LOCAL_EMBEDDING_DEVICE",
        "OSCE_LOCAL_EMBEDDING_CACHE_DIR",
        "OSCE_CHROMA_ENABLED",
        "CHROMA_PERSIST_DIRECTORY",
        "OSCE_CHROMA_COLLECTION",
        "OSCE_REQUIRE_RUNTIME_MODEL_CONFIG_FOR_TRAINING",
    ]:
        monkeypatch.delenv(env_name, raising=False)
    for env_name in [
        "OSCE_OPENAI_API_KEY",
        "OSCE_OPENAI_FALLBACK_API_KEY",
        "OSCE_ANTHROPIC_API_KEY",
        "OSCE_GEMINI_PATIENT_API_KEY",
        "OSCE_VERTEX_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ]:
        monkeypatch.setenv(env_name, "")
    monkeypatch.setenv("OSCE_OPENAI_ENABLED", "false")
    monkeypatch.setenv("OSCE_OPENAI_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("OSCE_ANTHROPIC_ENABLED", "false")
    monkeypatch.setenv("OSCE_VERTEX_ENABLED", "false")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_USE_VERTEX", "false")
    monkeypatch.setenv("OSCE_REQUIRE_RUNTIME_MODEL_CONFIG_FOR_TRAINING", "0")
    yield
    runtime_model_config_store.clear()
