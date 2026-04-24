from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"


def retrieve_feedback_sources(report: dict[str, Any], revealed_facts: list[str]) -> list[str]:
    case_id = report["case_id"]
    rubric_scores = report.get("rubric_scores", {})
    references = [f"case:{case_id}"]
    source_id = _case_source_id(case_id)
    if source_id:
        references.append(f"source:{source_id}")

    for item_id in report.get("missed_items", []):
        if item_id in rubric_scores:
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


def _case_source_id(case_id: str) -> str:
    case_path = CASES_DIR / f"{case_id}.json"
    case_payload = json.loads(case_path.read_text(encoding="utf-8"))
    return case_payload.get("source_attribution", {}).get("source_id", "")


def _deduplicate(values: list[str]) -> list[str]:
    deduplicated: list[str] = []
    for value in values:
        if value not in deduplicated:
            deduplicated.append(value)
    return deduplicated
