import json
import sqlite3

from app.services.evaluation_result_store import EvaluationResultStore
from app.services.evaluation_runner import EvaluationBatchResult, EvaluationResult


def test_evaluation_result_store_persists_batch_result_across_instances(tmp_path) -> None:
    database_path = tmp_path / "evaluation_results.sqlite3"
    batch_result = EvaluationBatchResult(
        total_cases=2,
        passed_cases=1,
        failed_cases=1,
        results=[
            EvaluationResult(
                session_id="session_pass",
                actual_total_score=55,
                expected_total_score=55,
                forbidden_term_violations=[],
                source_reference_count=4,
                source_reference_types=["case", "source", "rubric", "evidence"],
                rag_source_coverage_passed=True,
                rag_rubric_reference_coverage_ratio=1.0,
                missing_rubric_references=[],
                rag_explanation_coverage_passed=True,
                rag_explanation_coverage_ratio=1.0,
                missing_explanation_references=[],
                rag_evidence_coverage_passed=True,
                rag_evidence_coverage_ratio=1.0,
                missing_evidence_references=[],
                passed=True,
                duration_ms=12,
            ),
            EvaluationResult(
                session_id="session_fail",
                actual_total_score=10,
                expected_total_score=55,
                forbidden_term_violations=["治疗方案"],
                source_reference_count=0,
                source_reference_types=[],
                rag_source_coverage_passed=False,
                rag_rubric_reference_coverage_ratio=0.0,
                missing_rubric_references=["rubric:appendicitis_001_rubric.item.ht_migration"],
                rag_explanation_coverage_passed=False,
                rag_explanation_coverage_ratio=0.0,
                missing_explanation_references=["explanation:strength:dx_main"],
                rag_evidence_coverage_passed=False,
                rag_evidence_coverage_ratio=0.0,
                missing_evidence_references=["evidence:急性阑尾炎"],
                passed=False,
                duration_ms=34,
            ),
        ],
        passed=False,
        total_duration_ms=46,
    )

    EvaluationResultStore(database_path).save_batch_result("batch_demo", batch_result)
    loaded_result = EvaluationResultStore(database_path).get_batch_result("batch_demo")

    assert loaded_result == {
        "batch_id": "batch_demo",
        "total_cases": 2,
        "passed_cases": 1,
        "failed_cases": 1,
        "passed": False,
        "total_duration_ms": 46,
        "results": [
            {
                "session_id": "session_pass",
                "actual_total_score": 55,
                "expected_total_score": 55,
                "forbidden_term_violations": [],
                "source_reference_count": 4,
                "source_reference_types": ["case", "source", "rubric", "evidence"],
                "rag_source_coverage_passed": True,
                "rag_rubric_reference_coverage_ratio": 1.0,
                "missing_rubric_references": [],
                "rag_explanation_coverage_passed": True,
                "rag_explanation_coverage_ratio": 1.0,
                "missing_explanation_references": [],
                "rag_evidence_coverage_passed": True,
                "rag_evidence_coverage_ratio": 1.0,
                "missing_evidence_references": [],
                "passed": True,
                "duration_ms": 12,
            },
            {
                "session_id": "session_fail",
                "actual_total_score": 10,
                "expected_total_score": 55,
                "forbidden_term_violations": ["治疗方案"],
                "source_reference_count": 0,
                "source_reference_types": [],
                "rag_source_coverage_passed": False,
                "rag_rubric_reference_coverage_ratio": 0.0,
                "missing_rubric_references": ["rubric:appendicitis_001_rubric.item.ht_migration"],
                "rag_explanation_coverage_passed": False,
                "rag_explanation_coverage_ratio": 0.0,
                "missing_explanation_references": ["explanation:strength:dx_main"],
                "rag_evidence_coverage_passed": False,
                "rag_evidence_coverage_ratio": 0.0,
                "missing_evidence_references": ["evidence:急性阑尾炎"],
                "passed": False,
                "duration_ms": 34,
            },
        ],
    }


def test_evaluation_result_store_normalizes_legacy_results_without_rag_fields(tmp_path) -> None:
    database_path = tmp_path / "evaluation_results.sqlite3"
    store = EvaluationResultStore(database_path)
    store._initialize()
    legacy_result = {
        "batch_id": "legacy_batch",
        "total_cases": 1,
        "passed_cases": 1,
        "failed_cases": 0,
        "results": [
            {
                "session_id": "legacy_session",
                "actual_total_score": 32,
                "expected_total_score": 32,
                "forbidden_term_violations": [],
                "passed": True,
                "duration_ms": 10,
            }
        ],
        "passed": True,
        "total_duration_ms": 10,
    }
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO evaluation_results (batch_id, result_json) VALUES (?, ?)",
            ("legacy_batch", json.dumps(legacy_result, ensure_ascii=False)),
        )

    loaded_result = EvaluationResultStore(database_path).get_batch_result("legacy_batch")

    assert loaded_result["results"][0] == {
        "session_id": "legacy_session",
        "actual_total_score": 32,
        "expected_total_score": 32,
        "forbidden_term_violations": [],
        "source_reference_count": 0,
        "source_reference_types": [],
        "rag_source_coverage_passed": False,
        "rag_rubric_reference_coverage_ratio": 0.0,
        "missing_rubric_references": [],
        "rag_explanation_coverage_passed": False,
        "rag_explanation_coverage_ratio": 0.0,
        "missing_explanation_references": [],
        "rag_evidence_coverage_passed": False,
        "rag_evidence_coverage_ratio": 0.0,
        "missing_evidence_references": [],
        "passed": True,
        "duration_ms": 10,
    }


def test_evaluation_result_store_lists_batch_summaries_in_insert_order(tmp_path) -> None:
    database_path = tmp_path / "evaluation_results.sqlite3"
    store = EvaluationResultStore(database_path)

    store.save_batch_result(
        "batch_one",
        EvaluationBatchResult(total_cases=1, passed_cases=1, failed_cases=0, results=[], passed=True),
    )
    store.save_batch_result(
        "batch_two",
        EvaluationBatchResult(total_cases=2, passed_cases=1, failed_cases=1, results=[], passed=False),
    )

    summaries = EvaluationResultStore(database_path).list_batch_summaries()

    assert summaries == [
        {
            "batch_id": "batch_one",
            "total_cases": 1,
            "passed_cases": 1,
            "failed_cases": 0,
            "passed": True,
        },
        {
            "batch_id": "batch_two",
            "total_cases": 2,
            "passed_cases": 1,
            "failed_cases": 1,
            "passed": False,
        },
    ]
