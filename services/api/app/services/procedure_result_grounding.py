from __future__ import annotations

import json
import re
from typing import Any


MAX_PROCEDURE_GROUNDING_PAYLOAD_BYTES = 32 * 1024
MAX_HISTORY_FACTS = 20
MAX_CONFIGURED_RESULTS = 32
MAX_KNOWLEDGE_SNIPPETS = 3
MAX_GROUNDING_TEXT_BYTES = 1_200


def build_procedure_result_grounding(
    *,
    patient_context: dict[str, Any],
    configured_results: list[dict[str, str]],
    retrieved_knowledge_context: list[dict[str, Any]],
    forbidden_terms: list[str],
) -> dict[str, Any]:
    """Project a de-identified, bounded case basis for pre-submit generation.

    The projection intentionally excludes case identifiers, diagnosis fields,
    rubric data, source identifiers and internal fact identifiers.  It keeps
    only the clinical facts needed to make a conservative simulated finding.
    """

    grounding: dict[str, Any] = {
        "patient": _project_patient_context(patient_context, forbidden_terms),
        "configured_findings": _project_configured_results(
            configured_results,
            forbidden_terms,
        ),
        "teaching_knowledge": _project_knowledge_context(
            retrieved_knowledge_context,
            forbidden_terms,
        ),
    }
    return _fit_grounding_budget(grounding)


def sanitize_grounding_text(value: Any, forbidden_terms: list[str]) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for term in forbidden_terms:
        normalized_term = str(term or "").strip()
        if normalized_term:
            text = re.sub(
                re.escape(normalized_term),
                "相关诊断",
                text,
                flags=re.IGNORECASE,
            )
    return _truncate_utf8(text, MAX_GROUNDING_TEXT_BYTES)


def _project_patient_context(
    patient_context: dict[str, Any],
    forbidden_terms: list[str],
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key in (
        "age",
        "gender",
        "occupation",
        "department",
        "chief_complaint",
        "present_illness_summary",
    ):
        value = sanitize_grounding_text(patient_context.get(key), forbidden_terms)
        if value:
            projected[key] = value

    history_facts: list[dict[str, str]] = []
    raw_history_facts = patient_context.get("history_facts", [])
    if isinstance(raw_history_facts, list):
        for raw_fact in raw_history_facts[:MAX_HISTORY_FACTS]:
            if not isinstance(raw_fact, dict):
                continue
            answer = sanitize_grounding_text(raw_fact.get("answer"), forbidden_terms)
            if not answer:
                continue
            history_facts.append(
                {
                    "topic": sanitize_grounding_text(raw_fact.get("topic"), forbidden_terms),
                    "slot": sanitize_grounding_text(raw_fact.get("slot"), forbidden_terms),
                    "answer": answer,
                }
            )
    if history_facts:
        projected["history_facts"] = history_facts
    return projected


def _project_configured_results(
    configured_results: list[dict[str, str]],
    forbidden_terms: list[str],
) -> list[dict[str, str]]:
    projected: list[dict[str, str]] = []
    for raw_result in configured_results[:MAX_CONFIGURED_RESULTS]:
        if not isinstance(raw_result, dict):
            continue
        result_text = sanitize_grounding_text(raw_result.get("result"), forbidden_terms)
        name = sanitize_grounding_text(raw_result.get("name_cn"), forbidden_terms)
        if not name or not result_text:
            continue
        projected.append(
            {
                "kind": sanitize_grounding_text(raw_result.get("kind"), forbidden_terms),
                "name_cn": name,
                "result": result_text,
            }
        )
    return projected


def _project_knowledge_context(
    retrieved_knowledge_context: list[dict[str, Any]],
    forbidden_terms: list[str],
) -> list[dict[str, str]]:
    projected: list[dict[str, str]] = []
    for raw_item in retrieved_knowledge_context[:MAX_KNOWLEDGE_SNIPPETS]:
        if not isinstance(raw_item, dict):
            continue
        snippet = sanitize_grounding_text(raw_item.get("snippet"), forbidden_terms)
        if not snippet:
            continue
        projected.append(
            {
                "title": sanitize_grounding_text(raw_item.get("title"), forbidden_terms),
                "snippet": snippet,
            }
        )
    return projected


def _fit_grounding_budget(grounding: dict[str, Any]) -> dict[str, Any]:
    bounded = {
        "patient": dict(grounding.get("patient") or {}),
        "configured_findings": list(grounding.get("configured_findings") or []),
        "teaching_knowledge": list(grounding.get("teaching_knowledge") or []),
    }
    while _json_size(bounded) > MAX_PROCEDURE_GROUNDING_PAYLOAD_BYTES:
        if bounded["teaching_knowledge"]:
            bounded["teaching_knowledge"].pop()
            continue
        if bounded["configured_findings"]:
            bounded["configured_findings"].pop()
            continue
        patient = bounded["patient"]
        history_facts = patient.get("history_facts")
        if isinstance(history_facts, list) and history_facts:
            history_facts.pop()
            if not history_facts:
                patient.pop("history_facts", None)
            continue
        break
    return bounded


def _json_size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


__all__ = [
    "MAX_PROCEDURE_GROUNDING_PAYLOAD_BYTES",
    "build_procedure_result_grounding",
    "sanitize_grounding_text",
]
