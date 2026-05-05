import os

from app.services import gemini_patient_responder as module


class FakeModels:
    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        raise AssertionError("本测试只验证客户端创建，不应触发模型调用")


class FakeVertexClient:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.models = FakeModels()


def test_create_configured_patient_responder_uses_vertex_adc_without_api_key(monkeypatch) -> None:
    captured_clients: list[FakeVertexClient] = []

    def fake_client(**kwargs: object) -> FakeVertexClient:
        client = FakeVertexClient(**kwargs)
        captured_clients.append(client)
        return client

    monkeypatch.setattr(module.genai, "Client", fake_client)
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_USE_VERTEX", "true")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_PROJECT", "demo-project")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_LOCATION", "global")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_MODEL", "gemini-3.1-flash-lite-preview")
    monkeypatch.setenv("OSCE_GEMINI_PATIENT_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:7897")

    responder = module._create_configured_responder()

    assert responder._settings.api_key == ""
    assert responder._settings.use_vertex is True
    assert responder._settings.project == "demo-project"
    assert responder._settings.location == "global"
    assert responder._settings.model == "gemini-3.1-flash-lite-preview"
    assert captured_clients[0].kwargs == {
        "vertexai": True,
        "project": "demo-project",
        "location": "global",
    }
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7897"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7897"
    assert os.environ["ALL_PROXY"] == "http://127.0.0.1:7897"
