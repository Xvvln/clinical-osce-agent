from pathlib import Path

import pytest

from app.graph.osce_graph import evaluation_node
from app.services.retrieval_eval_service import (
    RetrievalGoldQuery,
    compute_retrieval_metrics,
    load_retrieval_gold_queries,
    run_retrieval_eval,
)
from app.services.retrieval_index import RetrievalDocument


def test_api_docker_image_copies_retrieval_eval_gold_set() -> None:
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY services/api/evals ./evals" in dockerfile


def test_retrieval_eval_metrics_compute_correctly() -> None:
    gold_queries = [
        RetrievalGoldQuery(
            query_id="q1",
            query="腹痛问诊漏项",
            expected_references=["rubric:appendicitis_001_rubric.item.ht_onset", "source:fareez_osce_2022"],
        ),
        RetrievalGoldQuery(
            query_id="q2",
            query="胸痛病例",
            expected_references=["case:acs_001"],
        ),
    ]
    results_by_query = {
        "q1": [
            "rubric:appendicitis_001_rubric.item.ht_onset",
            "knowledge:appendicitis_001.rp_01",
            "source:fareez_osce_2022",
        ],
        "q2": ["rubric:acs_001_rubric.item.ht_onset", "case:acs_001"],
    }

    metrics = compute_retrieval_metrics(gold_queries, results_by_query)

    assert metrics["query_count"] == 2
    assert metrics["recall_at_3"] == 1.0
    assert metrics["recall_at_5"] == 1.0
    assert metrics["mrr_at_5"] == 0.75
    assert metrics["ndcg_at_5"] == pytest.approx(0.7753, abs=0.0001)
    assert metrics["source_coverage"] == 1.0
    assert metrics["hit_rate_at_5"] == 1.0
    assert metrics["zero_hit_query_count"] == 0


def test_default_gold_queries_deepen_appendicitis_flagship_case() -> None:
    gold_queries = load_retrieval_gold_queries()
    appendicitis_queries = [
        gold_query for gold_query in gold_queries if gold_query.query_id.startswith("appendicitis_")
    ]
    expected_references = {
        reference
        for gold_query in appendicitis_queries
        for reference in gold_query.expected_references
    }

    assert 8 <= len(appendicitis_queries) <= 12
    assert {
        "case:appendicitis_001",
        "source:fareez_osce_2022",
        "rubric:appendicitis_001_rubric.item.ht_migration",
        "rubric:appendicitis_001_rubric.item.pe_rebound",
        "rubric:appendicitis_001_rubric.item.ax_cbc",
        "rubric:appendicitis_001_rubric.item.ax_ua",
        "rubric:appendicitis_001_rubric.item.rs_exclude",
        "knowledge:appendicitis_001.rp_05",
        "knowledge:appendicitis_001.rp_06",
    }.issubset(expected_references)
    assert all(
        not reference.startswith(("case:acs_", "rubric:acs_", "knowledge:acs_"))
        for reference in expected_references
    )


def test_retrieval_eval_uses_batch_search_once_for_gold_queries(tmp_path) -> None:
    gold_path = tmp_path / "gold_queries.json"
    gold_path.write_text(
        """[
  {"query_id":"q1","query":"腹痛迁移","expected_references":["case:appendicitis_001"]},
  {"query_id":"q2","query":"反跳痛","expected_references":["rubric:appendicitis_001_rubric.item.pe_rebound"]}
]""",
        encoding="utf-8",
    )
    calls: list[tuple[list[str], int]] = []

    def batch_search(queries: list[str], limit: int) -> list[list[RetrievalDocument]]:
        calls.append((queries, limit))
        return [
            [
                RetrievalDocument(
                    reference="case:appendicitis_001",
                    source_type="case",
                    title="右下腹痛教学病例",
                    snippet="转移性右下腹痛。",
                    score=0.9,
                )
            ],
            [
                RetrievalDocument(
                    reference="rubric:appendicitis_001_rubric.item.pe_rebound",
                    source_type="rubric",
                    title="检查反跳痛",
                    snippet="腹膜刺激征。",
                    score=0.8,
                )
            ],
        ]

    def search_should_not_run(query: str, limit: int) -> list[RetrievalDocument]:
        raise AssertionError(f"retrieval eval should batch search gold queries, got {query}")

    result = run_retrieval_eval(
        gold_path=gold_path,
        search_fn=search_should_not_run,
        batch_search_fn=batch_search,
    )

    assert calls == [(["腹痛迁移", "反跳痛"], 5)]
    assert result["metrics"]["recall_at_5"] == 1.0
    assert result["results"][0]["expanded_query"] == "腹痛迁移"
    assert result["results"][0]["retrieved_items"][0] == {
        "reference": "case:appendicitis_001",
        "score": 0.9,
        "retrieval_methods": [],
    }


def test_rag_never_enters_scoring_judgement(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_rag_is_used(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("RAG retrieval must not be used by evaluation_node scoring")

    monkeypatch.setattr("app.services.source_retriever.retrieve_feedback_source_items", fail_if_rag_is_used)

    result = evaluation_node(
        {
            "session_id": "session_score_boundary",
            "case_id": "appendicitis_001",
            "asked_questions": ["什么时候开始疼的？"],
            "requested_exams": ["abd.palpation.rebound"],
            "requested_tests": ["lab.cbc"],
            "revealed_facts": ["appendicitis_001.hf_01"],
            "final_submission": {"diagnosis": "急性阑尾炎", "reasoning": "右下腹痛和反跳痛。"},
        }
    )

    assert result["stage"] == "evaluation"
    assert result["feedback_report"]["session_id"] == "session_score_boundary"
    assert "source_references" not in result["feedback_report"]
