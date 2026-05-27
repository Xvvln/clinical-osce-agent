import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CASES_DIR = PROJECT_ROOT / "data" / "cases"


def _load_cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for case_path in sorted(CASES_DIR.glob("*.json")):
        cases.append(json.loads(case_path.read_text(encoding="utf-8")))
    return cases


def _valid_case_source_ids(case: dict[str, object]) -> set[str]:
    history = case["history"]
    physical_exam = case["physical_exam"]
    auxiliary_tests = case["auxiliary_tests"]
    diagnosis = case["diagnosis"]
    return {
        *[
            str(item["fact_id"])
            for item in history["hidden_facts"]  # type: ignore[index]
        ],
        *[
            str(item["exam_code"])
            for item in physical_exam["must_items"]  # type: ignore[index]
        ],
        *[
            str(item["exam_code"])
            for item in physical_exam.get("optional_items", [])  # type: ignore[union-attr]
        ],
        *[
            str(item["test_code"])
            for item in auxiliary_tests["must_items"]  # type: ignore[index]
        ],
        *[
            str(item["test_code"])
            for item in auxiliary_tests.get("optional_items", [])  # type: ignore[union-attr]
        ],
        *[
            str(item["point_id"])
            for item in diagnosis["reasoning_points"]  # type: ignore[index]
        ],
    }


def test_all_demo_cases_have_teaching_focus_content() -> None:
    for case in _load_cases():
        teaching_focus = case["teaching_focus"]

        assert len(teaching_focus["learning_objectives"]) >= 3, case["case_id"]  # type: ignore[index]
        assert len(teaching_focus["common_error_patterns"]) >= 3, case["case_id"]  # type: ignore[index]
        assert len(teaching_focus["recommended_training_path"]) >= 3, case["case_id"]  # type: ignore[index]


def test_all_demo_cases_have_enough_structured_training_material() -> None:
    for case in _load_cases():
        history = case["history"]
        physical_exam = case["physical_exam"]
        auxiliary_tests = case["auxiliary_tests"]
        diagnosis = case["diagnosis"]

        exam_count = len(physical_exam["must_items"]) + len(physical_exam.get("optional_items", []))  # type: ignore[union-attr]
        test_count = len(auxiliary_tests["must_items"]) + len(auxiliary_tests.get("optional_items", []))  # type: ignore[union-attr]

        assert len(history["hidden_facts"]) >= 8, case["case_id"]  # type: ignore[index]
        assert exam_count >= 5, case["case_id"]
        assert test_count >= 4, case["case_id"]
        assert len(diagnosis["reasoning_points"]) >= 5, case["case_id"]  # type: ignore[index]
        assert len(diagnosis["differential_diagnoses"]) >= 3, case["case_id"]  # type: ignore[index]
        assert len(case.get("negative_findings", [])) >= 2, case["case_id"]
        assert len(case.get("distractor_clues", [])) >= 1, case["case_id"]


def test_all_demo_cases_have_reasoning_graph_for_every_reasoning_point() -> None:
    for case in _load_cases():
        graph = case["evidence_graph"]
        reasoning_point_ids = {str(item["point_id"]) for item in case["diagnosis"]["reasoning_points"]}  # type: ignore[index]
        graph_reasoning_sources = {
            str(node["source_id"])
            for node in graph["evidence_nodes"]  # type: ignore[index]
            if node["node_type"] == "reasoning_point"
        }

        assert reasoning_point_ids <= graph_reasoning_sources, case["case_id"]


def test_all_demo_cases_have_traceable_evidence_graph_content() -> None:
    required_node_types = {"history_fact", "physical_exam", "auxiliary_test", "reasoning_point"}

    for case in _load_cases():
        graph = case["evidence_graph"]
        nodes = graph["evidence_nodes"]  # type: ignore[index]
        edges = graph["evidence_edges"]  # type: ignore[index]
        valid_source_ids = _valid_case_source_ids(case)
        node_ids = {str(node["node_id"]) for node in nodes}
        node_types = {str(node["node_type"]) for node in nodes}

        assert required_node_types <= node_types, case["case_id"]
        assert len(edges) >= 3, case["case_id"]

        for node in nodes:
            assert node["source_id"] in valid_source_ids, (case["case_id"], node["source_id"])
            assert str(node["label"]).strip(), (case["case_id"], node["node_id"])

        for edge in edges:
            assert edge["from_node"] in node_ids, (case["case_id"], edge)
            assert edge["to_node"] in node_ids, (case["case_id"], edge)
