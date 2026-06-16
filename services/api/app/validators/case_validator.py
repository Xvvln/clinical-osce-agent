from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.models.case import Case
from app.models.rubric import Rubric

ROOT_DIR = Path(__file__).resolve().parents[4]
SOURCE_REGISTRY_PATH = ROOT_DIR / "data" / "attribution" / "source_registry" / "sources.json"


@lru_cache(maxsize=1)
def _load_source_ids() -> set[str]:
    payload = json.loads(SOURCE_REGISTRY_PATH.read_text(encoding="utf-8"))
    return {entry["source_id"] for entry in payload}


def validate_case(json_data: dict[str, Any]) -> Case:
    case = Case.model_validate(json_data)
    if case.source_attribution.source_id not in _load_source_ids():
        raise ValueError(f"unknown source_id: {case.source_attribution.source_id}")
    return case


def validate_rubric(yaml_data: dict[str, Any]) -> Rubric:
    return Rubric.model_validate(yaml_data)


def validate_case_rubric_pair(case: Case, rubric: Rubric) -> None:
    if case.case_id != rubric.case_id:
        raise ValueError("case_id mismatch between case and rubric")
    if case.rubric_ref.rubric_id != rubric.rubric_id:
        raise ValueError("rubric_id mismatch between case and rubric")

    evidence_pool = {
        hidden_fact.fact_id for hidden_fact in case.history.hidden_facts
    }
    evidence_pool.update(
        exam.exam_code
        for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]
    )
    evidence_pool.update(
        test.test_code
        for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]
    )
    evidence_pool.update(point.point_id for point in case.diagnosis.reasoning_points)

    missing_evidence = []
    for dimension in rubric.dimensions:
        for item in dimension.items:
            for evidence in item.evidence_expected:
                if evidence not in evidence_pool:
                    missing_evidence.append((item.item_id, evidence))

    if missing_evidence:
        raise ValueError(f"rubric evidence missing from case: {missing_evidence}")

    rubric_item_ids = {
        item.item_id
        for dimension in rubric.dimensions
        for item in dimension.items
    }
    missing_linked_items = [
        (source_type, source_id, item_id)
        for source_type, source_id, item_id in _case_linked_rubric_items(case)
        if item_id not in rubric_item_ids
    ]
    if missing_linked_items:
        raise ValueError(f"case linked_rubric_items missing from rubric: {missing_linked_items}")


def _case_linked_rubric_items(case: Case) -> list[tuple[str, str, str]]:
    linked_items: list[tuple[str, str, str]] = []
    for hidden_fact in case.history.hidden_facts:
        linked_items.extend(
            ("history_fact", hidden_fact.fact_id, item_id)
            for item_id in hidden_fact.linked_rubric_items
        )
    for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]:
        linked_items.extend(
            ("physical_exam", exam.exam_code, item_id)
            for item_id in exam.linked_rubric_items
        )
    for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]:
        linked_items.extend(
            ("auxiliary_test", test.test_code, item_id)
            for item_id in test.linked_rubric_items
        )
    return linked_items
