import json

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
    assert client_kwargs["http_options"].client_args == {
        "follow_redirects": False,
        "trust_env": False,
    }
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


def test_vertex_embedding_client_batches_by_item_count_and_utf8_bytes(monkeypatch) -> None:
    vector_by_text = {
        "a": [1.0],
        "bb": [2.0],
        "你": [3.0],
        "dd": [4.0],
        "eee": [5.0],
    }

    class FakeEmbedding:
        def __init__(self, values: list[float]) -> None:
            self.values = values

    class FakeResponse:
        def __init__(self, contents: list[str]) -> None:
            self.embeddings = [
                FakeEmbedding(vector_by_text[text])
                for text in contents
            ]

    class FakeModels:
        calls: list[list[str]] = []

        def embed_content(self, *, contents: list[str], **kwargs: object) -> FakeResponse:
            self.calls.append(contents)
            return FakeResponse(contents)

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            self.models = FakeModels()

    monkeypatch.setattr(vertex_embedding_retriever.genai, "Client", FakeClient)
    client = vertex_embedding_retriever.VertexTextEmbeddingClient(
        vertex_embedding_retriever.VertexEmbeddingSettings(
            project="demo-project",
            proxy_url="direct",
            batch_size=2,
            batch_max_bytes=10,
        )
    )

    vectors = client.embed_texts(
        ["a", "bb", "你", "dd", "eee"],
        task_type="RETRIEVAL_DOCUMENT",
    )

    assert vectors == [[1.0], [2.0], [3.0], [4.0], [5.0]]
    assert FakeModels.calls == [["a", "bb"], ["你"], ["dd"], ["eee"]]
    assert all(len(batch) <= 2 for batch in FakeModels.calls)
    assert all(
        len(
            json.dumps(
                batch,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        <= 10
        for batch in FakeModels.calls
    )


def test_vertex_embedding_client_rejects_oversized_text_before_network_call(monkeypatch) -> None:
    class FakeModels:
        calls: list[list[str]] = []

        def embed_content(self, *, contents: list[str], **kwargs: object) -> object:
            self.calls.append(contents)
            raise AssertionError("oversized input must be rejected before a provider call")

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            self.models = FakeModels()

    monkeypatch.setattr(vertex_embedding_retriever.genai, "Client", FakeClient)
    client = vertex_embedding_retriever.VertexTextEmbeddingClient(
        vertex_embedding_retriever.VertexEmbeddingSettings(
            project="demo-project",
            proxy_url="direct",
            batch_size=2,
            batch_max_bytes=9,
        )
    )

    with pytest.raises(
        vertex_embedding_retriever.VertexEmbeddingInputTooLargeError,
        match=r"at index 1 exceeds the UTF-8 byte limit \(10 > 9\)",
    ) as exc_info:
        client.embed_texts(["ok", "你好"], task_type="RETRIEVAL_DOCUMENT")

    assert exc_info.value.input_index == 1
    assert exc_info.value.input_bytes == 10
    assert exc_info.value.max_bytes == 9
    assert FakeModels.calls == []


def test_vertex_embedding_byte_limit_counts_json_escaping(
    monkeypatch,
) -> None:
    class FakeModels:
        calls: list[list[str]] = []

        def embed_content(self, *, contents: list[str], **kwargs: object) -> object:
            self.calls.append(contents)
            raise AssertionError("escaped oversized input must not reach provider")

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            self.models = FakeModels()

    monkeypatch.setattr(vertex_embedding_retriever.genai, "Client", FakeClient)
    client = vertex_embedding_retriever.VertexTextEmbeddingClient(
        vertex_embedding_retriever.VertexEmbeddingSettings(
            project="demo-project",
            proxy_url="direct",
            batch_max_bytes=11,
        )
    )

    with pytest.raises(
        vertex_embedding_retriever.VertexEmbeddingInputTooLargeError,
    ) as exc_info:
        client.embed_texts(['""""'], task_type="RETRIEVAL_DOCUMENT")

    assert len('""""'.encode("utf-8")) == 4
    assert exc_info.value.input_bytes == 12
    assert FakeModels.calls == []


@pytest.mark.parametrize(
    ("raw_batch_size", "raw_batch_max_bytes", "expected_batch_size", "expected_batch_max_bytes"),
    [
        (
            "999999",
            "999999999",
            vertex_embedding_retriever.MAX_VERTEX_EMBEDDING_BATCH_SIZE,
            vertex_embedding_retriever.MAX_VERTEX_EMBEDDING_BATCH_MAX_BYTES,
        ),
        (
            "0",
            "invalid",
            vertex_embedding_retriever.DEFAULT_VERTEX_EMBEDDING_BATCH_SIZE,
            vertex_embedding_retriever.DEFAULT_VERTEX_EMBEDDING_BATCH_MAX_BYTES,
        ),
    ],
)
def test_vertex_embedding_environment_bounds_batch_limits(
    monkeypatch,
    raw_batch_size: str,
    raw_batch_max_bytes: str,
    expected_batch_size: int,
    expected_batch_max_bytes: int,
) -> None:
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_PROJECT", "demo-project")
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_BATCH_SIZE", raw_batch_size)
    monkeypatch.setenv("OSCE_VERTEX_EMBEDDING_BATCH_MAX_BYTES", raw_batch_max_bytes)

    with runtime_model_config_store.use_config(None):
        settings = vertex_embedding_retriever._resolve_vertex_embedding_settings()

    assert settings is not None
    assert settings.batch_size == expected_batch_size
    assert settings.batch_max_bytes == expected_batch_max_bytes


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
