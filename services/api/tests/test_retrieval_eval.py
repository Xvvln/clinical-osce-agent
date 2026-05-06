import pytest

from app.graph.osce_graph import evaluation_node
from app.services.retrieval_eval_service import RetrievalGoldQuery, compute_retrieval_metrics


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
