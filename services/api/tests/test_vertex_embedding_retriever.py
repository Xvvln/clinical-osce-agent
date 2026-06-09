from app.services import vertex_embedding_retriever


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

        def __init__(self, *, vertexai: bool, project: str, location: str) -> None:
            self.created.append(
                {
                    "vertexai": vertexai,
                    "project": project,
                    "location": location,
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

    assert FakeClient.created == [
        {
            "vertexai": True,
            "project": "demo-project",
            "location": "global",
        }
    ]
    assert vectors == [[1.0, 0.5], [2.0, 0.5]]
    assert FakeModels.calls == [
        {
            "model": "gemini-embedding-001",
            "contents": ["症状片段", "评分片段"],
            "task_type": "RETRIEVAL_DOCUMENT",
            "output_dimensionality": 3072,
        }
    ]


def test_vertex_embedding_client_uses_environment_api_key_without_project(monkeypatch) -> None:
    class FakeClient:
        created: list[dict[str, object]] = []

        def __init__(self, **kwargs: object) -> None:
            self.created.append(kwargs)
            self.models = object()

    monkeypatch.setattr(vertex_embedding_retriever.genai, "Client", FakeClient)
    monkeypatch.setattr(
        vertex_embedding_retriever.runtime_model_config_store,
        "get_vertex_gemini_config",
        lambda: None,
    )
    vertex_embedding_retriever.clear_vertex_embedding_quota_cooldown()
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_API_KEY", "test-vertex-api-key")
    monkeypatch.delenv("OSCE_VERTEX_EMBEDDING_PROJECT", raising=False)
    monkeypatch.delenv("OSCE_VERTEX_PROJECT", raising=False)

    client = vertex_embedding_retriever.build_vertex_embedding_client_from_environment()

    assert client is not None
    assert FakeClient.created == [{"vertexai": True, "api_key": "test-vertex-api-key"}]


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
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_PROJECT", "demo-project")

    assert vertex_embedding_retriever.build_vertex_embedding_client_from_environment() is not None
