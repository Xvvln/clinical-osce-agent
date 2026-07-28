from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services import dashscope_reranker
from app.services import retrieval_index as retrieval_index_module
from app.services.model_call_policy import (
    TEXT_MODEL_ENVELOPE_MAX_BYTES,
    ModelProviderPayloadTooLargeError,
    json_envelope_utf8_size,
)
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
    request_bodies: list[bytes] = []

    def __init__(self, **kwargs: object) -> None:
        self.created_options.append(kwargs)

    def __enter__(self) -> FakeHttpClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeHttpResponse:
        self.posts.append({"url": url, "headers": headers, "json": json})
        request = dashscope_reranker.httpx.Request(
            "POST",
            url,
            headers=headers,
            json=json,
        )
        self.request_bodies.append(request.content)
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


class NetworkMustNotStartHttpClient:
    construction_count = 0

    def __init__(self, **kwargs: object) -> None:
        del kwargs
        self.__class__.construction_count += 1
        raise AssertionError("HTTP client must not be constructed")


class DashScopeRerankerTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeHttpClient.created_options.clear()
        FakeHttpClient.posts.clear()
        FakeHttpClient.request_bodies.clear()
        NetworkMustNotStartHttpClient.construction_count = 0

    @patch.dict("os.environ", {"OSCE_DASHSCOPE_RERANK_ENABLED": "false"}, clear=True)
    def test_dashscope_reranker_is_disabled_by_default(self) -> None:
        self.assertIsNone(dashscope_reranker.build_dashscope_reranker_from_environment())

    def test_candidate_and_top_limits_have_hard_caps(self) -> None:
        default_reranker = dashscope_reranker.DashScopeReranker(
            dashscope_reranker.DashScopeRerankSettings(api_key="sk-test")
        )
        self.assertEqual(default_reranker.candidate_limit(1), 30)
        self.assertEqual(default_reranker.candidate_limit(10_000), 30)
        self.assertEqual(default_reranker.top_limit(10_000, 10_000), 5)

        oversized_reranker = dashscope_reranker.DashScopeReranker(
            dashscope_reranker.DashScopeRerankSettings(
                api_key="sk-test",
                top_k=10_000,
                candidate_k=10_000,
            )
        )
        self.assertEqual(oversized_reranker.candidate_limit(1), 30)
        self.assertEqual(oversized_reranker.top_limit(10_000, 10_000), 30)

    @patch.dict(
        "os.environ",
        {
            "OSCE_DASHSCOPE_RERANK_ENABLED": "true",
            "OSCE_DASHSCOPE_RERANK_API_KEY": "sk-test",
            "OSCE_DASHSCOPE_RERANK_TOP_K": "1000000",
            "OSCE_DASHSCOPE_RERANK_CANDIDATE_K": "1000000",
        },
        clear=True,
    )
    def test_huge_environment_limits_are_clamped(self) -> None:
        reranker = dashscope_reranker.build_dashscope_reranker_from_environment()

        self.assertIsNotNone(reranker)
        assert reranker is not None
        self.assertEqual(reranker._settings.top_k, 30)
        self.assertEqual(reranker._settings.candidate_k, 30)
        self.assertEqual(reranker.candidate_limit(10_000), 30)
        self.assertEqual(reranker.top_limit(10_000, 10_000), 30)

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

    @patch.object(dashscope_reranker.httpx, "Client", FakeHttpClient)
    def test_large_rag_payload_is_projected_under_envelope_and_keeps_indexes(self) -> None:
        hostile_text = '病例😀"\\\n' * 2_000
        settings = dashscope_reranker.DashScopeRerankSettings(
            api_key="sk-test",
            top_k=1_000_000,
            candidate_k=1_000_000,
            instruct=hostile_text,
        )
        reranker = dashscope_reranker.DashScopeReranker(settings)
        documents = ["   "] + [
            f"{index}:{hostile_text}"
            for index in range(50)
        ]

        results = reranker.rerank(
            f"查询:{hostile_text}",
            documents,
            top_k=1_000_000,
        )

        self.assertEqual([result.index for result in results], [2, 1])
        payload = FakeHttpClient.posts[0]["json"]
        self.assertEqual(payload["top_n"], 30)
        self.assertEqual(len(payload["documents"]), 30)
        self.assertLessEqual(
            len(payload["query"].encode("utf-8")),
            dashscope_reranker.MAX_DASHSCOPE_RERANK_QUERY_BYTES,
        )
        self.assertLessEqual(
            len(payload["instruct"].encode("utf-8")),
            dashscope_reranker.MAX_DASHSCOPE_RERANK_INSTRUCT_BYTES,
        )
        self.assertTrue(
            all(
                len(document.encode("utf-8"))
                <= dashscope_reranker.MAX_DASHSCOPE_RERANK_DOCUMENT_BYTES
                for document in payload["documents"]
            )
        )
        self.assertEqual(
            len(FakeHttpClient.request_bodies[0]),
            json_envelope_utf8_size(payload),
        )
        self.assertLessEqual(
            len(FakeHttpClient.request_bodies[0]),
            TEXT_MODEL_ENVELOPE_MAX_BYTES,
        )

    @patch.object(dashscope_reranker.httpx, "Client", FakeHttpClient)
    def test_exact_envelope_boundary_is_sent(self) -> None:
        base_payload = {
            "model": "",
            "query": "q",
            "documents": ["d"],
            "top_n": 1,
        }
        model = "m" * (
            TEXT_MODEL_ENVELOPE_MAX_BYTES
            - json_envelope_utf8_size(base_payload)
        )
        reranker = dashscope_reranker.DashScopeReranker(
            dashscope_reranker.DashScopeRerankSettings(
                api_key="sk-test",
                model=model,
                top_k=1,
                candidate_k=1,
                instruct="",
            )
        )

        results = reranker.rerank("q", ["d"], top_k=1)

        self.assertEqual([result.index for result in results], [0])
        self.assertEqual(
            len(FakeHttpClient.request_bodies[0]),
            TEXT_MODEL_ENVELOPE_MAX_BYTES,
        )

    @patch.object(
        dashscope_reranker.httpx,
        "Client",
        NetworkMustNotStartHttpClient,
    )
    def test_unfulfillable_envelope_fails_before_network(self) -> None:
        base_payload = {
            "model": "",
            "query": "q",
            "documents": ["d"],
            "top_n": 1,
        }
        model = "m" * (
            TEXT_MODEL_ENVELOPE_MAX_BYTES
            - json_envelope_utf8_size(base_payload)
            + 1
        )
        reranker = dashscope_reranker.DashScopeReranker(
            dashscope_reranker.DashScopeRerankSettings(
                api_key="sk-test",
                model=model,
                top_k=1,
                candidate_k=1,
                instruct="",
            )
        )

        with self.assertRaises(ModelProviderPayloadTooLargeError):
            reranker.rerank("q", ["d"], top_k=1)

        self.assertEqual(
            NetworkMustNotStartHttpClient.construction_count,
            0,
        )

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

    def test_retrieval_does_not_swallow_payload_policy_errors(self) -> None:
        class PolicyFailingReranker:
            def top_limit(self, result_limit: int, document_count: int) -> int:
                return min(result_limit, document_count)

            def rerank(
                self,
                query: str,
                documents: list[str],
                *,
                top_k: int,
            ) -> list[dashscope_reranker.DashScopeRerankResult]:
                raise ModelProviderPayloadTooLargeError("payload too large")

        documents = [
            RetrievalDocument(
                reference="source:a",
                source_type="source",
                title="A",
                snippet="泛泛相关",
                score=0.9,
            ),
            RetrievalDocument(
                reference="source:b",
                source_type="source",
                title="B",
                snippet="真正相关",
                score=0.8,
            ),
        ]

        with self.assertRaises(ModelProviderPayloadTooLargeError):
            retrieval_index_module._apply_dashscope_rerank(
                "右下腹痛",
                documents,
                limit=2,
                reranker=PolicyFailingReranker(),
            )


if __name__ == "__main__":
    unittest.main()
