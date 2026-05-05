from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"
RUBRICS_DIR = ROOT_DIR / "data" / "rubrics"
SOURCE_REGISTRY_PATH = ROOT_DIR / "data" / "attribution" / "source_registry" / "sources.json"


@dataclass(frozen=True)
class FeedbackSourceItem:
    reference: str
    source_type: str
    title: str
    metadata: dict[str, Any] = field(default_factory=dict)


def retrieve_feedback_sources(report: dict[str, Any], revealed_facts: list[str]) -> list[str]:
    return [item.reference for item in retrieve_feedback_source_items(report, revealed_facts)]


def retrieve_feedback_source_items(report: dict[str, Any], revealed_facts: list[str]) -> list[FeedbackSourceItem]:
    case_id = report["case_id"]
    references = _collect_references(report, revealed_facts)
    return [_resolve_reference(reference, case_id) for reference in references]


def _collect_references(report: dict[str, Any], revealed_facts: list[str]) -> list[str]:
    case_id = report["case_id"]
    rubric_scores = report.get("rubric_scores", {})
    references = [f"case:{case_id}"]
    source_id = _case_payload(case_id).get("source_attribution", {}).get("source_id", "")
    if source_id:
        references.append(f"source:{source_id}")

    for item_id in report.get("missed_items", []):
        if item_id in rubric_scores:
            references.append(f"rubric:{case_id}_rubric.item.{item_id}")

    for item_id in rubric_scores:
        if isinstance(item_id, str):
            references.append(f"rubric:{case_id}_rubric.item.{item_id}")

    for fact_id in revealed_facts:
        references.append(f"evidence:{fact_id}")

    for traces in report.get("dimension_traces", {}).values():
        for trace in traces:
            if trace.get("match_kind") == "intent_keyword":
                continue
            for evidence in trace.get("matched_evidence", []):
                references.append(f"evidence:{evidence}")

    return _deduplicate(references)


def _resolve_reference(reference: str, case_id: str) -> FeedbackSourceItem:
    if reference.startswith("case:"):
        referenced_case_id = reference.removeprefix("case:")
        case_payload = _case_payload(referenced_case_id)
        return FeedbackSourceItem(reference=reference, source_type="case", title=case_payload["case_title"])

    if reference.startswith("source:"):
        source_id = reference.removeprefix("source:")
        source_payload = _source_registry().get(source_id, {})
        return FeedbackSourceItem(
            reference=reference,
            source_type="source",
            title=source_payload.get("source_name", source_id),
            metadata=source_payload,
        )

    if reference.startswith("rubric:"):
        _, item_id = reference.split(".item.", maxsplit=1)
        item = _rubric_items(case_id).get(item_id, {})
        return FeedbackSourceItem(reference=reference, source_type="rubric", title=item.get("description", item_id))

    if reference.startswith("evidence:"):
        evidence_id = reference.removeprefix("evidence:")
        return FeedbackSourceItem(reference=reference, source_type="evidence", title=_evidence_title(case_id, evidence_id))

    return FeedbackSourceItem(reference=reference, source_type="other", title=reference)


@lru_cache(maxsize=None)
def _case_payload(case_id: str) -> dict[str, Any]:
    case_path = CASES_DIR / f"{case_id}.json"
    return json.loads(case_path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _source_registry() -> dict[str, dict[str, Any]]:
    payload = json.loads(SOURCE_REGISTRY_PATH.read_text(encoding="utf-8"))
    return {item["source_id"]: item for item in payload}


@lru_cache(maxsize=None)
def _rubric_items(case_id: str) -> dict[str, dict[str, Any]]:
    rubric_path = RUBRICS_DIR / f"{case_id}_rubric.yaml"
    rubric_payload = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    items: dict[str, dict[str, Any]] = {}
    for dimension in rubric_payload.get("dimensions", []):
        for item in dimension.get("items", []):
            items[item["item_id"]] = item
    return items


def _evidence_title(case_id: str, evidence_id: str) -> str:
    case_payload = _case_payload(case_id)
    for fact in case_payload.get("history", {}).get("hidden_facts", []):
        if fact.get("fact_id") == evidence_id:
            return fact.get("canonical_answer", evidence_id)

    for exam in case_payload.get("physical_exam", {}).get("must_items", []) + case_payload.get("physical_exam", {}).get("optional_items", []):
        if exam.get("exam_code") == evidence_id:
            return exam.get("result", evidence_id)

    for test in case_payload.get("auxiliary_tests", {}).get("must_items", []) + case_payload.get("auxiliary_tests", {}).get("optional_items", []):
        if test.get("test_code") == evidence_id:
            return test.get("result", evidence_id)

    for point in case_payload.get("diagnosis", {}).get("reasoning_points", []):
        if point.get("point_id") == evidence_id:
            return point.get("statement", evidence_id)

    return evidence_id


def _deduplicate(values: list[str]) -> list[str]:
    deduplicated: list[str] = []
    for value in values:
        if value not in deduplicated:
            deduplicated.append(value)
    return deduplicated
