from app.services import vertex_embedding_retriever


def test_vertex_embedding_client_calls_vertex_adc_with_gemini_embedding_model(monkeypatch) -> None:
    class FakeEmbedding:
        def __init__(self, values: list[float]) -> None:
            self.values = values

    class FakeResponse:
        def __init__(self, values: list[float]) -> None:
            self.embeddings = [FakeEmbedding(values)]

    class FakeModels:
        calls: list[dict[str, object]] = []

        def embed_content(self, *, model: str, contents: str, config: object) -> FakeResponse:
            self.calls.append(
                {
                    "model": model,
                    "contents": contents,
                    "task_type": getattr(config, "task_type"),
                    "output_dimensionality": getattr(config, "output_dimensionality"),
                }
            )
            return FakeResponse([float(len(self.calls)), 0.5])

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
            "contents": "症状片段",
            "task_type": "RETRIEVAL_DOCUMENT",
            "output_dimensionality": 3072,
        },
        {
            "model": "gemini-embedding-001",
            "contents": "评分片段",
            "task_type": "RETRIEVAL_DOCUMENT",
            "output_dimensionality": 3072,
        },
    ]
