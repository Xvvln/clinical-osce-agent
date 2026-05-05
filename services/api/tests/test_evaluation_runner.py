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


class ReportWithoutRagSourcesService:
    def create_session(self, case_id: str, student_id: str) -> dict[str, str]:
        return {"session_id": "session_without_rag_sources"}

    def handle_message(self, session_id: str, message: str) -> None:
        return None

    def request_physical_exam(self, session_id: str, exam_code: str) -> None:
        return None

    def request_auxiliary_test(self, session_id: str, test_code: str) -> None:
        return None

    def submit_diagnosis(self, session_id: str, diagnosis: str, reasoning: str) -> None:
        return None

    def get_report(self, session_id: str) -> dict[str, object]:
        return {"total_score": 32, "missed_items": ["ht_migration"], "source_reference_items": []}


class ReportWithPartialRubricSourcesService(ReportWithoutRagSourcesService):
    def create_session(self, case_id: str, student_id: str) -> dict[str, str]:
        return {"session_id": "session_with_partial_rubric_sources"}

    def get_report(self, session_id: str) -> dict[str, object]:
        return {
            "case_id": "appendicitis_001",
            "total_score": 32,
            "missed_items": ["ht_migration", "ht_character"],
            "source_reference_items": [
                {
                    "reference": "case:appendicitis_001",
                    "source_type": "case",
                    "title": "右下腹痛教学病例",
                    "metadata": {},
                },
                {
                    "reference": "rubric:appendicitis_001_rubric.item.ht_migration",
                    "source_type": "rubric",
                    "title": "追问疼痛部位及转移特征",
                    "metadata": {},
                },
            ],
        }


class ReportWithExplanationTextWithoutExplanationSourcesService(ReportWithoutRagSourcesService):
    def create_session(self, case_id: str, student_id: str) -> dict[str, str]:
        return {"session_id": "session_with_explanation_text_without_sources"}

    def get_report(self, session_id: str) -> dict[str, object]:
        return {
            "case_id": "appendicitis_001",
            "total_score": 32,
            "missed_items": [],
            "rubric_scores": {
                "dx_main": {
                    "dimension_id": "main_diagnosis",
                    "description": "主要诊断命中急性阑尾炎",
                    "score": 15,
                    "max_score": 15,
                }
            },
            "strengths": ["主要诊断命中急性阑尾炎：已完成。"],
            "reasoning_errors": [],
            "llm_reasoning_feedback": [],
            "source_reference_items": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.dx_main",
                    "source_type": "rubric",
                    "title": "主要诊断命中急性阑尾炎",
                    "metadata": {},
                }
            ],
        }


class ReportWithExplanationMissingRubricReferenceService(ReportWithExplanationTextWithoutExplanationSourcesService):
    def create_session(self, case_id: str, student_id: str) -> dict[str, str]:
        return {"session_id": "session_with_explanation_missing_rubric_reference"}

    def get_report(self, session_id: str) -> dict[str, object]:
        report = dict(super().get_report(session_id))
        report["explanation_source_items"] = [
            {
                "kind": "strength",
                "text": "主要诊断命中急性阑尾炎：已完成。",
                "rubric_item_id": "dx_main",
                "source_references": [],
            }
        ]
        return report


class ReportWithExplanationReferenceOutsideReportSourcesService(ReportWithExplanationTextWithoutExplanationSourcesService):
    def create_session(self, case_id: str, student_id: str) -> dict[str, str]:
        return {"session_id": "session_with_explanation_reference_outside_report_sources"}

    def get_report(self, session_id: str) -> dict[str, object]:
        report = dict(super().get_report(session_id))
        report["source_reference_items"] = [
            {
                "reference": "case:appendicitis_001",
                "source_type": "case",
                "title": "右下腹痛教学病例",
                "metadata": {},
            }
        ]
        report["explanation_source_items"] = [
            {
                "kind": "strength",
                "text": "主要诊断命中急性阑尾炎：已完成。",
                "rubric_item_id": "dx_main",
                "source_references": ["rubric:appendicitis_001_rubric.item.dx_main"],
            }
        ]
        return report


class ReportWithPartialExplanationSourcesService(ReportWithoutRagSourcesService):
    def create_session(self, case_id: str, student_id: str) -> dict[str, str]:
        return {"session_id": "session_with_partial_explanation_sources"}

    def get_report(self, session_id: str) -> dict[str, object]:
        return {
            "case_id": "appendicitis_001",
            "total_score": 32,
            "missed_items": [],
            "rubric_scores": {
                "dx_main": {
                    "dimension_id": "main_diagnosis",
                    "description": "主要诊断命中急性阑尾炎",
                    "score": 15,
                    "max_score": 15,
                },
                "ax_cbc": {
                    "dimension_id": "auxiliary_test",
                    "description": "申请血常规",
                    "score": 5,
                    "max_score": 5,
                },
            },
            "strengths": ["主要诊断命中急性阑尾炎：已完成。", "申请血常规：已完成。"],
            "reasoning_errors": [],
            "llm_reasoning_feedback": [],
            "source_reference_items": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.dx_main",
                    "source_type": "rubric",
                    "title": "主要诊断命中急性阑尾炎",
                    "metadata": {},
                },
                {
                    "reference": "rubric:appendicitis_001_rubric.item.ax_cbc",
                    "source_type": "rubric",
                    "title": "申请血常规",
                    "metadata": {},
                },
            ],
            "explanation_source_items": [
                {
                    "kind": "strength",
                    "text": "主要诊断命中急性阑尾炎：已完成。",
                    "rubric_item_id": "dx_main",
                    "source_references": ["rubric:appendicitis_001_rubric.item.dx_main"],
                }
            ],
        }


class ReportWithExplanationMissingEvidenceReferenceService(ReportWithoutRagSourcesService):
    def create_session(self, case_id: str, student_id: str) -> dict[str, str]:
        return {"session_id": "session_with_explanation_missing_evidence_reference"}

    def get_report(self, session_id: str) -> dict[str, object]:
        return {
            "case_id": "appendicitis_001",
            "total_score": 32,
            "missed_items": [],
            "rubric_scores": {
                "dx_main": {
                    "dimension_id": "main_diagnosis",
                    "description": "主要诊断命中急性阑尾炎",
                    "score": 15,
                    "max_score": 15,
                }
            },
            "dimension_traces": {
                "main_diagnosis": [
                    {
                        "rubric_item_id": "dx_main",
                        "awarded_score": 15,
                        "max_score": 15,
                        "match_kind": "diagnosis_concept",
                        "matched_evidence": ["急性阑尾炎"],
                    }
                ]
            },
            "strengths": ["主要诊断命中急性阑尾炎：已完成。"],
            "reasoning_errors": [],
            "llm_reasoning_feedback": [],
            "source_reference_items": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.dx_main",
                    "source_type": "rubric",
                    "title": "主要诊断命中急性阑尾炎",
                    "metadata": {},
                },
                {
                    "reference": "evidence:急性阑尾炎",
                    "source_type": "evidence",
                    "title": "急性阑尾炎",
                    "metadata": {},
                },
            ],
            "explanation_source_items": [
                {
                    "kind": "strength",
                    "text": "主要诊断命中急性阑尾炎：已完成。",
                    "rubric_item_id": "dx_main",
                    "source_references": ["rubric:appendicitis_001_rubric.item.dx_main"],
                }
            ],
        }


class ReportWithExplanationEvidenceReferenceOutsideReportSourcesService(ReportWithExplanationMissingEvidenceReferenceService):
    def create_session(self, case_id: str, student_id: str) -> dict[str, str]:
        return {"session_id": "session_with_explanation_evidence_reference_outside_report_sources"}

    def get_report(self, session_id: str) -> dict[str, object]:
        report = dict(super().get_report(session_id))
        report["source_reference_items"] = [
            {
                "reference": "rubric:appendicitis_001_rubric.item.dx_main",
                "source_type": "rubric",
                "title": "主要诊断命中急性阑尾炎",
                "metadata": {},
            }
        ]
        report["explanation_source_items"] = [
            {
                "kind": "strength",
                "text": "主要诊断命中急性阑尾炎：已完成。",
                "rubric_item_id": "dx_main",
                "source_references": ["rubric:appendicitis_001_rubric.item.dx_main", "evidence:急性阑尾炎"],
            }
        ]
        return report


class ReportWithPartialExplanationEvidenceSourcesService(ReportWithoutRagSourcesService):
    def create_session(self, case_id: str, student_id: str) -> dict[str, str]:
        return {"session_id": "session_with_partial_explanation_evidence_sources"}

    def get_report(self, session_id: str) -> dict[str, object]:
        return {
            "case_id": "appendicitis_001",
            "total_score": 32,
            "missed_items": [],
            "rubric_scores": {
                "dx_main": {
                    "dimension_id": "main_diagnosis",
                    "description": "主要诊断命中急性阑尾炎",
                    "score": 15,
                    "max_score": 15,
                },
                "ax_cbc": {
                    "dimension_id": "auxiliary_test",
                    "description": "申请血常规",
                    "score": 5,
                    "max_score": 5,
                },
            },
            "dimension_traces": {
                "main_diagnosis": [
                    {
                        "rubric_item_id": "dx_main",
                        "awarded_score": 15,
                        "max_score": 15,
                        "match_kind": "diagnosis_concept",
                        "matched_evidence": ["急性阑尾炎"],
                    }
                ],
                "auxiliary_test": [
                    {
                        "rubric_item_id": "ax_cbc",
                        "awarded_score": 5,
                        "max_score": 5,
                        "match_kind": "test_code",
                        "matched_evidence": ["lab.cbc"],
                    }
                ],
            },
            "strengths": ["主要诊断命中急性阑尾炎：已完成。", "申请血常规：已完成。"],
            "reasoning_errors": [],
            "llm_reasoning_feedback": [],
            "source_reference_items": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.dx_main",
                    "source_type": "rubric",
                    "title": "主要诊断命中急性阑尾炎",
                    "metadata": {},
                },
                {
                    "reference": "rubric:appendicitis_001_rubric.item.ax_cbc",
                    "source_type": "rubric",
                    "title": "申请血常规",
                    "metadata": {},
                },
                {
                    "reference": "evidence:急性阑尾炎",
                    "source_type": "evidence",
                    "title": "急性阑尾炎",
                    "metadata": {},
                },
                {
                    "reference": "evidence:lab.cbc",
                    "source_type": "evidence",
                    "title": "血常规",
                    "metadata": {},
                },
            ],
            "explanation_source_items": [
                {
                    "kind": "strength",
                    "text": "主要诊断命中急性阑尾炎：已完成。",
                    "rubric_item_id": "dx_main",
                    "source_references": ["rubric:appendicitis_001_rubric.item.dx_main", "evidence:急性阑尾炎"],
                },
                {
                    "kind": "strength",
                    "text": "申请血常规：已完成。",
                    "rubric_item_id": "ax_cbc",
                    "source_references": ["rubric:appendicitis_001_rubric.item.ax_cbc"],
                },
            ],
        }


class ReportWithInvalidSourceItemsService(ReportWithoutRagSourcesService):
    def create_session(self, case_id: str, student_id: str) -> dict[str, str]:
        return {"session_id": "session_with_invalid_source_items"}

    def get_report(self, session_id: str) -> dict[str, object]:
        return {"case_id": "appendicitis_001", "total_score": 32, "missed_items": [], "source_reference_items": [{}]}


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
    assert result.rag_source_coverage_passed is True
    assert result.source_reference_count >= 3
    assert result.source_reference_types[:3] == ["case", "source", "rubric"]
    assert result.rag_rubric_reference_coverage_ratio == 1.0
    assert result.missing_rubric_references == []
    assert result.rag_explanation_coverage_passed is True
    assert result.rag_explanation_coverage_ratio == 1.0
    assert result.missing_explanation_references == []
    assert result.rag_evidence_coverage_passed is True
    assert result.rag_evidence_coverage_ratio == 1.0
    assert result.missing_evidence_references == []
    assert result.duration_ms >= 0


def test_run_evaluation_case_fails_when_rag_sources_are_missing() -> None:
    evaluation_case = EvaluationCase(
        case_id="appendicitis_001",
        student_id="eval_student",
        steps=[EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="转移性右下腹痛支持诊断。")],
        expected_total_score=32,
        forbidden_terms=[],
    )

    result = run_evaluation_case(evaluation_case, ReportWithoutRagSourcesService())

    assert result.passed is False
    assert result.rag_source_coverage_passed is False
    assert result.source_reference_count == 0
    assert result.source_reference_types == []
    assert result.rag_rubric_reference_coverage_ratio == 0.0
    assert result.missing_rubric_references == ["rubric:appendicitis_001_rubric.item.ht_migration"]


def test_run_evaluation_case_fails_when_some_missed_items_lack_rubric_sources() -> None:
    evaluation_case = EvaluationCase(
        case_id="appendicitis_001",
        student_id="eval_student",
        steps=[EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="转移性右下腹痛支持诊断。")],
        expected_total_score=32,
        forbidden_terms=[],
    )

    result = run_evaluation_case(evaluation_case, ReportWithPartialRubricSourcesService())

    assert result.passed is False
    assert result.rag_source_coverage_passed is False
    assert result.source_reference_count == 2
    assert result.source_reference_types == ["case", "rubric"]
    assert result.rag_rubric_reference_coverage_ratio == 0.5
    assert result.missing_rubric_references == ["rubric:appendicitis_001_rubric.item.ht_character"]


def test_run_evaluation_case_fails_when_explanation_text_lacks_source_items() -> None:
    evaluation_case = EvaluationCase(
        case_id="appendicitis_001",
        student_id="eval_student",
        steps=[EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="转移性右下腹痛支持诊断。")],
        expected_total_score=32,
        forbidden_terms=[],
    )

    result = run_evaluation_case(evaluation_case, ReportWithExplanationTextWithoutExplanationSourcesService())

    assert result.passed is False
    assert result.rag_source_coverage_passed is True
    assert result.rag_explanation_coverage_passed is False
    assert result.rag_explanation_coverage_ratio == 0.0
    assert result.missing_explanation_references == ["explanation:strength:dx_main"]


def test_run_evaluation_case_fails_when_explanation_item_lacks_its_rubric_reference() -> None:
    evaluation_case = EvaluationCase(
        case_id="appendicitis_001",
        student_id="eval_student",
        steps=[EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="转移性右下腹痛支持诊断。")],
        expected_total_score=32,
        forbidden_terms=[],
    )

    result = run_evaluation_case(evaluation_case, ReportWithExplanationMissingRubricReferenceService())

    assert result.passed is False
    assert result.rag_source_coverage_passed is True
    assert result.rag_explanation_coverage_passed is False
    assert result.rag_explanation_coverage_ratio == 0.0
    assert result.missing_explanation_references == ["explanation:strength:dx_main"]


def test_run_evaluation_case_fails_when_explanation_reference_is_missing_from_report_sources() -> None:
    evaluation_case = EvaluationCase(
        case_id="appendicitis_001",
        student_id="eval_student",
        steps=[EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="转移性右下腹痛支持诊断。")],
        expected_total_score=32,
        forbidden_terms=[],
    )

    result = run_evaluation_case(evaluation_case, ReportWithExplanationReferenceOutsideReportSourcesService())

    assert result.passed is False
    assert result.rag_source_coverage_passed is True
    assert result.rag_explanation_coverage_passed is False
    assert result.rag_explanation_coverage_ratio == 0.0
    assert result.missing_explanation_references == ["explanation:strength:dx_main"]


def test_run_evaluation_case_fails_when_some_explanation_items_are_missing() -> None:
    evaluation_case = EvaluationCase(
        case_id="appendicitis_001",
        student_id="eval_student",
        steps=[EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="转移性右下腹痛支持诊断。")],
        expected_total_score=32,
        forbidden_terms=[],
    )

    result = run_evaluation_case(evaluation_case, ReportWithPartialExplanationSourcesService())

    assert result.passed is False
    assert result.rag_source_coverage_passed is True
    assert result.rag_explanation_coverage_passed is False
    assert result.rag_explanation_coverage_ratio == 0.5
    assert result.missing_explanation_references == ["explanation:strength:ax_cbc"]


def test_run_evaluation_case_fails_when_explanation_item_lacks_expected_evidence_reference() -> None:
    evaluation_case = EvaluationCase(
        case_id="appendicitis_001",
        student_id="eval_student",
        steps=[EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="转移性右下腹痛支持诊断。")],
        expected_total_score=32,
        forbidden_terms=[],
    )

    result = run_evaluation_case(evaluation_case, ReportWithExplanationMissingEvidenceReferenceService())

    assert result.passed is False
    assert result.rag_source_coverage_passed is True
    assert result.rag_explanation_coverage_passed is True
    assert result.rag_evidence_coverage_passed is False
    assert result.rag_evidence_coverage_ratio == 0.0
    assert result.missing_evidence_references == ["evidence:急性阑尾炎"]


def test_run_evaluation_case_fails_when_explanation_evidence_reference_is_missing_from_report_sources() -> None:
    evaluation_case = EvaluationCase(
        case_id="appendicitis_001",
        student_id="eval_student",
        steps=[EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="转移性右下腹痛支持诊断。")],
        expected_total_score=32,
        forbidden_terms=[],
    )

    result = run_evaluation_case(evaluation_case, ReportWithExplanationEvidenceReferenceOutsideReportSourcesService())

    assert result.passed is False
    assert result.rag_source_coverage_passed is True
    assert result.rag_explanation_coverage_passed is True
    assert result.rag_evidence_coverage_passed is False
    assert result.rag_evidence_coverage_ratio == 0.0
    assert result.missing_evidence_references == ["evidence:急性阑尾炎"]


def test_run_evaluation_case_fails_when_some_explanation_evidence_items_are_missing() -> None:
    evaluation_case = EvaluationCase(
        case_id="appendicitis_001",
        student_id="eval_student",
        steps=[EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="转移性右下腹痛支持诊断。")],
        expected_total_score=32,
        forbidden_terms=[],
    )

    result = run_evaluation_case(evaluation_case, ReportWithPartialExplanationEvidenceSourcesService())

    assert result.passed is False
    assert result.rag_source_coverage_passed is True
    assert result.rag_explanation_coverage_passed is True
    assert result.rag_evidence_coverage_passed is False
    assert result.rag_evidence_coverage_ratio == 0.5
    assert result.missing_evidence_references == ["evidence:lab.cbc"]


def test_run_evaluation_case_fails_when_source_items_are_not_valid_references() -> None:
    evaluation_case = EvaluationCase(
        case_id="appendicitis_001",
        student_id="eval_student",
        steps=[EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="转移性右下腹痛支持诊断。")],
        expected_total_score=32,
        forbidden_terms=[],
    )

    result = run_evaluation_case(evaluation_case, ReportWithInvalidSourceItemsService())

    assert result.passed is False
    assert result.rag_source_coverage_passed is False
    assert result.source_reference_count == 0
    assert result.source_reference_types == []


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
