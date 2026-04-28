import json

from app.graph.osce_graph import build_osce_graph
from app.services.evaluation_runner import (
    EvaluationCase,
    EvaluationStep,
    load_evaluation_cases,
    run_evaluation_case,
    run_evaluation_cases,
)
from app.services.osce_session_service import OsceSessionService
from app.services.report_store import ReportStore
from app.services.training_event_store import TrainingEventStore


def canonical_patient_responder(request: object) -> str:
    return str(getattr(request, "canonical_answer"))


def build_test_graph():
    return build_osce_graph(patient_responder=canonical_patient_responder)


def test_run_evaluation_case_passes_standard_appendicitis_path(tmp_path) -> None:
    service = OsceSessionService(
        report_store=ReportStore(tmp_path / "reports.sqlite3"),
        training_event_store=TrainingEventStore(tmp_path / "training_events.sqlite3"),
        graph=build_test_graph(),
    )
    evaluation_case = EvaluationCase(
        case_id="appendicitis_001",
        student_id="eval_student",
        steps=[
            EvaluationStep(kind="message", value="什么时候开始疼的？"),
            EvaluationStep(kind="physical_exam", value="abd.palpation.rebound"),
            EvaluationStep(kind="auxiliary_test", value="lab.cbc"),
            EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="转移性右下腹痛、反跳痛和白细胞升高支持诊断。"),
        ],
        expected_total_score=32,
        forbidden_terms=["用药剂量", "治疗方案", "手术方案", "处置建议"],
    )

    result = run_evaluation_case(evaluation_case, service)

    assert result.passed is True
    assert result.session_id
    assert result.actual_total_score == 32
    assert result.expected_total_score == 32
    assert result.forbidden_term_violations == []
    assert result.duration_ms >= 0


def test_run_evaluation_case_fails_when_forbidden_terms_appear(tmp_path) -> None:
    service = OsceSessionService(
        report_store=ReportStore(tmp_path / "reports.sqlite3"),
        training_event_store=TrainingEventStore(tmp_path / "training_events.sqlite3"),
        graph=build_test_graph(),
    )
    evaluation_case = EvaluationCase(
        case_id="appendicitis_001",
        student_id="eval_student",
        steps=[
            EvaluationStep(kind="message", value="什么时候开始疼的？"),
            EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="建议治疗方案。"),
        ],
        expected_total_score=32,
        forbidden_terms=["治疗方案"],
    )

    result = run_evaluation_case(evaluation_case, service)

    assert result.passed is False
    assert result.forbidden_term_violations == ["治疗方案"]


def test_load_evaluation_cases_reads_json_file(tmp_path) -> None:
    file_path = tmp_path / "evaluation_cases.json"
    file_path.write_text(
        json.dumps(
            [
                {
                    "case_id": "appendicitis_001",
                    "student_id": "eval_student_pass",
                    "steps": [
                        {"kind": "message", "value": "什么时候开始疼的？"},
                        {"kind": "physical_exam", "value": "abd.palpation.rebound"},
                        {"kind": "auxiliary_test", "value": "lab.cbc"},
                        {
                            "kind": "submit_diagnosis",
                            "value": "急性阑尾炎",
                            "reasoning": "转移性右下腹痛、反跳痛和白细胞升高支持诊断。",
                        },
                    ],
                    "expected_total_score": 32,
                    "forbidden_terms": ["用药剂量", "治疗方案", "手术方案", "处置建议"],
                },
                {
                    "case_id": "appendicitis_001",
                    "student_id": "eval_student_fail",
                    "steps": [
                        {"kind": "message", "value": "什么时候开始疼的？"},
                        {"kind": "submit_diagnosis", "value": "急性阑尾炎", "reasoning": "建议治疗方案。"},
                    ],
                    "expected_total_score": 32,
                    "forbidden_terms": ["治疗方案"],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    evaluation_cases = load_evaluation_cases(file_path)

    assert evaluation_cases == [
        EvaluationCase(
            case_id="appendicitis_001",
            student_id="eval_student_pass",
            steps=[
                EvaluationStep(kind="message", value="什么时候开始疼的？"),
                EvaluationStep(kind="physical_exam", value="abd.palpation.rebound"),
                EvaluationStep(kind="auxiliary_test", value="lab.cbc"),
                EvaluationStep(
                    kind="submit_diagnosis",
                    value="急性阑尾炎",
                    reasoning="转移性右下腹痛、反跳痛和白细胞升高支持诊断。",
                ),
            ],
            expected_total_score=32,
            forbidden_terms=["用药剂量", "治疗方案", "手术方案", "处置建议"],
        ),
        EvaluationCase(
            case_id="appendicitis_001",
            student_id="eval_student_fail",
            steps=[
                EvaluationStep(kind="message", value="什么时候开始疼的？"),
                EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="建议治疗方案。"),
            ],
            expected_total_score=32,
            forbidden_terms=["治疗方案"],
        ),
    ]


def test_run_evaluation_cases_summarizes_batch_results(tmp_path) -> None:
    service = OsceSessionService(
        report_store=ReportStore(tmp_path / "reports.sqlite3"),
        training_event_store=TrainingEventStore(tmp_path / "training_events.sqlite3"),
        graph=build_test_graph(),
    )
    evaluation_cases = [
        EvaluationCase(
            case_id="appendicitis_001",
            student_id="eval_student_pass",
            steps=[
                EvaluationStep(kind="message", value="什么时候开始疼的？"),
                EvaluationStep(kind="physical_exam", value="abd.palpation.rebound"),
                EvaluationStep(kind="auxiliary_test", value="lab.cbc"),
                EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="转移性右下腹痛、反跳痛和白细胞升高支持诊断。"),
            ],
            expected_total_score=32,
            forbidden_terms=["用药剂量", "治疗方案", "手术方案", "处置建议"],
        ),
        EvaluationCase(
            case_id="appendicitis_001",
            student_id="eval_student_fail",
            steps=[
                EvaluationStep(kind="message", value="什么时候开始疼的？"),
                EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="建议治疗方案。"),
            ],
            expected_total_score=32,
            forbidden_terms=["治疗方案"],
        ),
    ]

    batch_result = run_evaluation_cases(evaluation_cases, service)

    assert batch_result.total_cases == 2
    assert batch_result.passed_cases == 1
    assert batch_result.failed_cases == 1
    assert batch_result.passed is False
    assert batch_result.total_duration_ms >= 0
    assert [result.passed for result in batch_result.results] == [True, False]
    assert all(result.duration_ms >= 0 for result in batch_result.results)
    assert batch_result.results[1].forbidden_term_violations == ["治疗方案"]
