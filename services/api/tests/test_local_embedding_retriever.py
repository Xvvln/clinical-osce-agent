from __future__ import annotations

from app.services import local_embedding_retriever as local_embedding_retriever_module


class FakeTextEmbedding:
    created_args: list[dict[str, object]] = []

    def __init__(self, model_name: str, **kwargs: object) -> None:
        self.model_name = model_name
        self.kwargs = kwargs
        self.query_embed_calls: list[dict[str, object]] = []
        self.created_args.append({"model_name": model_name, **kwargs})

    def query_embed(self, texts: list[str], **kwargs: object):
        self.query_embed_calls.append({"texts": texts, **kwargs})
        return [[float(index), 0.5, 1.0] for index, _ in enumerate(texts)]


def test_local_embedding_client_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("OSCE_LOCAL_EMBEDDING_ENABLED", raising=False)

    client = local_embedding_retriever_module.build_local_embedding_client_from_environment()

    assert client is None


def test_local_embedding_client_uses_fastembed_with_query_batches(monkeypatch) -> None:
    FakeTextEmbedding.created_args = []
    monkeypatch.setenv("OSCE_LOCAL_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("OSCE_LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    monkeypatch.setenv("OSCE_LOCAL_EMBEDDING_DEVICE", "cpu")
    monkeypatch.setenv("OSCE_LOCAL_EMBEDDING_CACHE_FOLDER", "/tmp/hf-cache")
    monkeypatch.setenv("OSCE_LOCAL_EMBEDDING_BATCH_SIZE", "7")
    monkeypatch.setattr(
        local_embedding_retriever_module,
        "_load_text_embedding_class",
        lambda: FakeTextEmbedding,
    )

    client = local_embedding_retriever_module.build_local_embedding_client_from_environment()
    vectors = client.embed_texts(["腹痛", "发热"], task_type="RETRIEVAL_QUERY")

    assert client is not None
    assert FakeTextEmbedding.created_args == [{"model_name": "BAAI/bge-small-zh-v1.5"}]
    assert vectors == [[0.0, 0.5, 1.0], [1.0, 0.5, 1.0]]
    assert client.model.query_embed_calls == [
        {
            "texts": ["腹痛", "发热"],
            "batch_size": 7,
        }
    ]
