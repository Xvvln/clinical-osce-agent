import pytest

from app.services.runtime_model_config_store import runtime_model_config_store


@pytest.fixture(autouse=True)
def clear_runtime_model_config_store(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_model_config_store.clear()
    for env_name in [
        "OSCE_OPENAI_ENABLED",
        "OSCE_OPENAI_API_KEY",
        "OSCE_OPENAI_BASE_URL",
        "OSCE_OPENAI_MODEL",
        "OSCE_OPENAI_PROXY_URL",
    ]:
        monkeypatch.delenv(env_name, raising=False)
    yield
    runtime_model_config_store.clear()
