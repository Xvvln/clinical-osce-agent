from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services import dashscope_reranker
from app.services import retrieval_index as retrieval_index_module
from app.services.retrieval_index import RetrievalDocument


class FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class FakeHttpClient:
    created_options: list[dict[str, object]] = []
    posts: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        self.created_options.append(kwargs)

    def __enter__(self) -> FakeHttpClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeHttpResponse:
        self.posts.append({"url": url, "headers": headers, "json": json})
        return FakeHttpResponse(
            {
                "object": "list",
                "model": "qwen3-rerank",
                "results": [
                    {"index": 1, "relevance_score": 0.91},
                    {"index": 0, "relevance_score": 0.38},
                ],
            }
        )


class DashScopeRerankerTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeHttpClient.created_options.clear()
        FakeHttpClient.posts.clear()

    @patch.dict("os.environ", {"OSCE_DASHSCOPE_RERANK_ENABLED": "false"}, clear=True)
    def test_dashscope_reranker_is_disabled_by_default(self) -> None:
        self.assertIsNone(dashscope_reranker.build_dashscope_reranker_from_environment())

    @patch.object(dashscope_reranker.httpx, "Client", FakeHttpClient)
    def test_qwen3_reranker_posts_flat_payload_and_parses_results(self) -> None:
        settings = dashscope_reranker.DashScopeRerankSettings(
            api_key="sk-test",
            base_url="https://dashscope.aliyuncs.com/compatible-api/v1",
            model="qwen3-rerank",
            top_k=2,
            candidate_k=30,
            instruct="Retrieve semantically similar text.",
            proxy_url="direct",
        )
        reranker = dashscope_reranker.DashScopeReranker(settings)

        results = reranker.rerank(
            "右下腹痛需要查什么",
            ["腹痛病例评分项", "右下腹反跳痛和白细胞升高"],
            top_k=2,
        )

        self.assertEqual([result.index for result in results], [1, 0])
        self.assertEqual(results[0].relevance_score, 0.91)
        self.assertEqual(FakeHttpClient.created_options, [{"timeout": 15.0, "trust_env": False}])
        self.assertEqual(FakeHttpClient.posts[0]["url"], "https://dashscope.aliyuncs.com/compatible-api/v1/reranks")
        self.assertEqual(
            FakeHttpClient.posts[0]["json"],
            {
                "model": "qwen3-rerank",
                "query": "右下腹痛需要查什么",
                "documents": ["腹痛病例评分项", "右下腹反跳痛和白细胞升高"],
                "top_n": 2,
                "instruct": "Retrieve semantically similar text.",
            },
        )
        self.assertEqual(FakeHttpClient.posts[0]["headers"]["Authorization"], "Bearer sk-test")

    def test_retrieval_results_are_reranked_when_enabled(self) -> None:
        class FakeReranker:
            def candidate_limit(self, result_limit: int) -> int:
                return max(result_limit, 2)

            def top_limit(self, result_limit: int, document_count: int) -> int:
                return min(result_limit, document_count)

            def rerank(self, query: str, documents: list[str], *, top_k: int) -> list[dashscope_reranker.DashScopeRerankResult]:
                self.query = query
                self.documents = documents
                self.top_k = top_k
                return [
                    dashscope_reranker.DashScopeRerankResult(index=1, relevance_score=0.95),
                    dashscope_reranker.DashScopeRerankResult(index=0, relevance_score=0.2),
                ]

        reranker = FakeReranker()
        documents = [
            RetrievalDocument(reference="source:a", source_type="source", title="A", snippet="泛泛相关", score=0.9),
            RetrievalDocument(reference="source:b", source_type="source", title="B", snippet="真正相关", score=0.8),
        ]

        with patch.object(retrieval_index_module, "build_dashscope_reranker_from_environment", lambda: reranker):
            results = retrieval_index_module._apply_dashscope_rerank("右下腹痛", documents, limit=2)

        self.assertEqual([result.reference for result in results], ["source:b", "source:a"])
        self.assertEqual(results[0].score, 0.95)
        self.assertEqual(reranker.top_k, 2)

    def test_retrieval_keeps_vector_order_when_rerank_fails(self) -> None:
        class FailingReranker:
            def candidate_limit(self, result_limit: int) -> int:
                return max(result_limit, 2)

            def top_limit(self, result_limit: int, document_count: int) -> int:
                return min(result_limit, document_count)

            def rerank(self, query: str, documents: list[str], *, top_k: int) -> list[dashscope_reranker.DashScopeRerankResult]:
                raise RuntimeError("dashscope unavailable")

        documents = [
            RetrievalDocument(reference="source:a", source_type="source", title="A", snippet="泛泛相关", score=0.9),
            RetrievalDocument(reference="source:b", source_type="source", title="B", snippet="真正相关", score=0.8),
        ]

        with patch.object(retrieval_index_module, "build_dashscope_reranker_from_environment", lambda: FailingReranker()):
            results = retrieval_index_module._apply_dashscope_rerank("右下腹痛", documents, limit=1)

        self.assertEqual([result.reference for result in results], ["source:a"])


if __name__ == "__main__":
    unittest.main()
