from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.retrieval_index import RetrievalDocument, search_retrieval_documents

ROOT_DIR = Path(__file__).resolve().parents[4]
DEFAULT_RETRIEVAL_GOLD_PATH = ROOT_DIR / "services" / "api" / "evals" / "retrieval" / "gold_queries.json"


@dataclass(frozen=True)
class RetrievalGoldQuery:
    query_id: str
    query: str
    expected_references: list[str]


def run_retrieval_eval(
    *,
    gold_path: Path = DEFAULT_RETRIEVAL_GOLD_PATH,
    search_fn: Callable[[str, int], Sequence[RetrievalDocument]] = search_retrieval_documents,
) -> dict[str, Any]:
    gold_queries = load_retrieval_gold_queries(gold_path)
    results: list[dict[str, Any]] = []
    results_by_query: dict[str, list[str]] = {}
    for gold_query in gold_queries:
        retrieved_documents = list(search_fn(gold_query.query, 5))
        retrieved_references = [document.reference for document in retrieved_documents]
        results_by_query[gold_query.query_id] = retrieved_references
        results.append(
            {
                "query_id": gold_query.query_id,
                "query": gold_query.query,
                "expected_references": gold_query.expected_references,
                "retrieved_references": retrieved_references,
                "hits_at_5": [
                    reference for reference in retrieved_references[:5]
                    if reference in set(gold_query.expected_references)
                ],
            }
        )

    return {
        "gold_set": {
            "path": gold_path.as_posix(),
            "query_count": len(gold_queries),
        },
        "metrics": compute_retrieval_metrics(gold_queries, results_by_query),
        "results": results,
        "boundary": {
            "rag_usage": "feedback_explanation_learning_recommendation_traceability_only",
            "chroma_scope": "ChromaDB 是本地可选持久向量检索，不是生产级向量基础设施。",
            "scoring_boundary": "RAG 检索结果不得进入标准诊断裁判、rubric 评分、隐藏事实披露或真实诊疗建议。",
        },
    }


def load_retrieval_gold_queries(path: Path = DEFAULT_RETRIEVAL_GOLD_PATH) -> list[RetrievalGoldQuery]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        RetrievalGoldQuery(
            query_id=str(item["query_id"]),
            query=str(item["query"]),
            expected_references=[str(reference) for reference in item.get("expected_references", [])],
        )
        for item in payload
    ]


def compute_retrieval_metrics(
    gold_queries: Sequence[RetrievalGoldQuery],
    results_by_query: dict[str, list[str]],
) -> dict[str, float | int]:
    if not gold_queries:
        return {
            "query_count": 0,
            "recall_at_3": 0.0,
            "recall_at_5": 0.0,
            "mrr_at_5": 0.0,
            "ndcg_at_5": 0.0,
            "source_coverage": 0.0,
        }

    return {
        "query_count": len(gold_queries),
        "recall_at_3": _round_metric(_average_recall_at(gold_queries, results_by_query, 3)),
        "recall_at_5": _round_metric(_average_recall_at(gold_queries, results_by_query, 5)),
        "mrr_at_5": _round_metric(_average_mrr_at(gold_queries, results_by_query, 5)),
        "ndcg_at_5": _round_metric(_average_ndcg_at(gold_queries, results_by_query, 5)),
        "source_coverage": _round_metric(_source_coverage(gold_queries, results_by_query, 5)),
    }


def _average_recall_at(
    gold_queries: Sequence[RetrievalGoldQuery],
    results_by_query: dict[str, list[str]],
    limit: int,
) -> float:
    recalls = []
    for gold_query in gold_queries:
        expected = set(gold_query.expected_references)
        retrieved = set(results_by_query.get(gold_query.query_id, [])[:limit])
        recalls.append(len(expected & retrieved) / len(expected) if expected else 0.0)
    return sum(recalls) / len(recalls)


def _average_mrr_at(
    gold_queries: Sequence[RetrievalGoldQuery],
    results_by_query: dict[str, list[str]],
    limit: int,
) -> float:
    reciprocal_ranks = []
    for gold_query in gold_queries:
        expected = set(gold_query.expected_references)
        reciprocal_rank = 0.0
        for index, reference in enumerate(results_by_query.get(gold_query.query_id, [])[:limit], start=1):
            if reference in expected:
                reciprocal_rank = 1 / index
                break
        reciprocal_ranks.append(reciprocal_rank)
    return sum(reciprocal_ranks) / len(reciprocal_ranks)


def _average_ndcg_at(
    gold_queries: Sequence[RetrievalGoldQuery],
    results_by_query: dict[str, list[str]],
    limit: int,
) -> float:
    scores = []
    for gold_query in gold_queries:
        expected = set(gold_query.expected_references)
        retrieved = results_by_query.get(gold_query.query_id, [])[:limit]
        dcg = sum(
            1 / math.log2(rank + 1)
            for rank, reference in enumerate(retrieved, start=1)
            if reference in expected
        )
        ideal_hits = min(len(expected), limit)
        ideal_dcg = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
        scores.append(dcg / ideal_dcg if ideal_dcg else 0.0)
    return sum(scores) / len(scores)


def _source_coverage(
    gold_queries: Sequence[RetrievalGoldQuery],
    results_by_query: dict[str, list[str]],
    limit: int,
) -> float:
    expected_references = {
        reference for gold_query in gold_queries for reference in gold_query.expected_references
    }
    retrieved_references = {
        reference for references in results_by_query.values() for reference in references[:limit]
    }
    return len(expected_references & retrieved_references) / len(expected_references) if expected_references else 0.0


def _round_metric(value: float) -> float:
    return round(value, 4)
