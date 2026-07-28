import pytest

from app.services import vertex_embedding_retriever
from app.services.runtime_model_config_store import RuntimeModelConfig, runtime_model_config_store


def test_vertex_embedding_client_calls_vertex_adc_with_gemini_embedding_model(monkeypatch) -> None:
    class FakeEmbedding:
        def __init__(self, values: list[float]) -> None:
            self.values = values

    class FakeResponse:
        def __init__(self, values_by_text: list[list[float]]) -> None:
            self.embeddings = [FakeEmbedding(values) for values in values_by_text]

    class FakeModels:
        calls: list[dict[str, object]] = []

        def embed_content(self, *, model: str, contents: list[str], config: object) -> FakeResponse:
            self.calls.append(
                {
                    "model": model,
                    "contents": contents,
                    "task_type": getattr(config, "task_type"),
                    "output_dimensionality": getattr(config, "output_dimensionality"),
                }
            )
            return FakeResponse([[float(index + 1), 0.5] for index, _ in enumerate(contents)])

    class FakeClient:
        created: list[dict[str, object]] = []

        def __init__(self, *, vertexai: bool, project: str, location: str, http_options: object) -> None:
            self.created.append(
                {
                    "vertexai": vertexai,
                    "project": project,
                    "location": location,
                    "http_options": http_options,
                }
            )
            self.models = FakeModels()

    monkeypatch.setattr(vertex_embedding_retriever.genai, "Client", FakeClient)
    settings = vertex_embedding_retriever.VertexEmbeddingSettings(
        project="demo-project",
        location="global",
        model="gemini-embedding-001",
        output_dimensionality=3072,
        proxy_url="direct",
    )

    client = vertex_embedding_retriever.VertexTextEmbeddingClient(settings)
    vectors = client.embed_texts(["症状片段", "评分片段"], task_type="RETRIEVAL_DOCUMENT")

    client_kwargs = FakeClient.created[0]
    assert {key: value for key, value in client_kwargs.items() if key != "http_options"} == {
        "vertexai": True,
        "project": "demo-project",
        "location": "global",
    }
    assert client_kwargs["http_options"].client_args == {"trust_env": False}
    assert client_kwargs["http_options"].async_client_args["trust_env"] is False
    assert vectors == [[1.0, 0.5], [2.0, 0.5]]
    assert FakeModels.calls == [
        {
            "model": "gemini-embedding-001",
            "contents": ["症状片段", "评分片段"],
            "task_type": "RETRIEVAL_DOCUMENT",
            "output_dimensionality": 3072,
        }
    ]


def test_vertex_embedding_quota_error_opens_cooldown(monkeypatch) -> None:
    class FakeModels:
        def embed_content(self, **kwargs: object):
            raise RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded for gemini-embedding")

    class FakeClient:
        created_count = 0

        def __init__(self, **kwargs: object) -> None:
            FakeClient.created_count += 1
            self.models = FakeModels()

    now = {"value": 1000.0}
    monkeypatch.setattr(vertex_embedding_retriever.time, "time", lambda: now["value"])
    monkeypatch.setattr(vertex_embedding_retriever.genai, "Client", FakeClient)
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_PROJECT", "demo-project")
    vertex_embedding_retriever.clear_vertex_embedding_quota_cooldown()

    settings = vertex_embedding_retriever.VertexEmbeddingSettings(
        project="demo-project",
        model="gemini-embedding-001",
        proxy_url="direct",
    )
    client = vertex_embedding_retriever.VertexTextEmbeddingClient(settings)
    try:
        client.embed_texts(["腹痛问诊"], task_type="RETRIEVAL_QUERY")
    except RuntimeError:
        pass

    assert vertex_embedding_retriever.build_vertex_embedding_client_from_environment() is None
    assert FakeClient.created_count == 1

    now["value"] += vertex_embedding_retriever.DEFAULT_VERTEX_EMBEDDING_QUOTA_COOLDOWN_SECONDS + 1

    assert vertex_embedding_retriever.build_vertex_embedding_client_from_environment() is not None


def test_vertex_embedding_quota_cooldown_is_isolated_by_runtime_account(monkeypatch) -> None:
    class FakeModels:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def embed_content(self, **kwargs: object) -> object:
            if self.api_key == "embedding-key-a":
                raise RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded for account A")
            raise AssertionError("account B should only be constructed in this test")

    class FakeClient:
        created_api_keys: list[str] = []

        def __init__(self, **kwargs: object) -> None:
            api_key = str(kwargs.get("api_key", ""))
            self.created_api_keys.append(api_key)
            self.models = FakeModels(api_key)

    first_config = RuntimeModelConfig(
        provider="vertex_gemini_api_key",
        api_key="embedding-key-a",
        model="gemini-2.5-flash",
        base_url="",
        proxy_url="direct",
        location="global",
    )
    second_config = RuntimeModelConfig(
        provider="vertex_gemini_api_key",
        api_key="embedding-key-b",
        model="gemini-2.5-flash",
        base_url="",
        proxy_url="direct",
        location="global",
    )
    monkeypatch.setattr(vertex_embedding_retriever.genai, "Client", FakeClient)
    vertex_embedding_retriever.clear_vertex_embedding_quota_cooldown()

    try:
        with runtime_model_config_store.use_config(first_config):
            first_client = vertex_embedding_retriever.build_vertex_embedding_client_from_environment()
            assert first_client is not None
            with pytest.raises(RuntimeError, match="RESOURCE_EXHAUSTED"):
                first_client.embed_texts(["账号 A 查询"], task_type="RETRIEVAL_QUERY")
            assert vertex_embedding_retriever.build_vertex_embedding_client_from_environment() is None

        with runtime_model_config_store.use_config(second_config):
            second_client = vertex_embedding_retriever.build_vertex_embedding_client_from_environment()
            assert second_client is not None
    finally:
        vertex_embedding_retriever.clear_vertex_embedding_quota_cooldown()

    assert FakeClient.created_api_keys == ["embedding-key-a", "embedding-key-b"]
