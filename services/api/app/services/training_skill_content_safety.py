from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT_DIR = Path(__file__).resolve().parents[4]
CASES_DIR = ROOT_DIR / "data" / "cases"
RUBRICS_DIR = ROOT_DIR / "data" / "rubrics"
PROTECTED_DIAGNOSIS_PLACEHOLDER = "当前病例诊断假设"


def candidate_case_ids(candidate: dict[str, Any]) -> list[str]:
    case_ids = {
        str(case_id).strip()
        for case_id in candidate.get("case_ids", [])
        if str(case_id).strip()
    }
    applies_when = candidate.get("applies_when")
    if isinstance(applies_when, dict):
        case_ids.update(
            str(case_id).strip()
            for case_id in applies_when.get("case_ids", [])
            if str(case_id).strip()
        )
    return sorted(case_ids)


def case_protected_terms(case_ids: Iterable[str]) -> list[str]:
    protected_terms: list[str] = []
    for case_id in sorted({str(case_id).strip() for case_id in case_ids if str(case_id).strip()}):
        case_path = CASES_DIR / f"{case_id}.json"
        rubric_path = RUBRICS_DIR / f"{case_id}_rubric.yaml"
        for term in _case_protected_terms_for_asset_version(
            case_id,
            _asset_version(case_path),
            _asset_version(rubric_path),
        ):
            _append_protected_text(protected_terms, term)
    return sorted(protected_terms, key=lambda term: (-len(term), term))


@lru_cache(maxsize=256)
def _case_protected_terms_for_asset_version(
    case_id: str,
    _case_asset_version: tuple[int, int] | None,
    _rubric_asset_version: tuple[int, int] | None,
) -> tuple[str, ...]:
    protected_terms: list[str] = []
    case_path = CASES_DIR / f"{case_id}.json"
    if not case_path.is_file():
        return ()
    try:
        case_payload = json.loads(case_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()

    diagnosis = _dict(case_payload.get("diagnosis"))
    _append_protected_text(protected_terms, diagnosis.get("main_diagnosis"))
    for synonym in diagnosis.get("main_diagnosis_synonyms") or []:
        _append_protected_text(protected_terms, synonym)
    for differential in diagnosis.get("differential_diagnoses") or []:
        if not isinstance(differential, dict):
            continue
        _append_protected_text(protected_terms, differential.get("disease_name"))
        _append_protected_text(protected_terms, differential.get("key_distinction"))
    for reasoning_point in diagnosis.get("reasoning_points") or []:
        if isinstance(reasoning_point, dict):
            _append_protected_text(protected_terms, reasoning_point.get("statement"))

    history = _dict(case_payload.get("history"))
    for hidden_fact in history.get("hidden_facts") or []:
        if not isinstance(hidden_fact, dict):
            continue
        _append_protected_text(protected_terms, hidden_fact.get("canonical_answer"))
        for variant in hidden_fact.get("variants") or []:
            _append_protected_text(protected_terms, variant)

    _append_result_terms(protected_terms, case_payload.get("physical_exam"))
    _append_result_terms(protected_terms, case_payload.get("auxiliary_tests"))
    _append_rubric_diagnosis_terms(protected_terms, case_id)
    return tuple(sorted(protected_terms, key=lambda term: (-len(term), term)))


def _asset_version(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def sanitize_case_protected_text(
    text: str,
    case_ids: Iterable[str],
    *,
    replacement: str = PROTECTED_DIAGNOSIS_PLACEHOLDER,
) -> str:
    sanitized = str(text)
    for protected_term in case_protected_terms(case_ids):
        sanitized = sanitized.replace(protected_term, replacement)
    return sanitized


def _append_result_terms(protected_terms: list[str], section: Any) -> None:
    if not isinstance(section, dict):
        return
    for list_value in section.values():
        if not isinstance(list_value, list):
            continue
        for item in list_value:
            if isinstance(item, dict):
                _append_protected_text(protected_terms, item.get("result"))


def _append_rubric_diagnosis_terms(protected_terms: list[str], case_id: str) -> None:
    rubric_path = RUBRICS_DIR / f"{case_id}_rubric.yaml"
    if not rubric_path.is_file():
        return
    try:
        rubric_payload = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return
    if not isinstance(rubric_payload, dict):
        return
    for dimension in rubric_payload.get("dimensions") or []:
        if not isinstance(dimension, dict):
            continue
        for item in dimension.get("items") or []:
            if not isinstance(item, dict):
                continue
            match_rule = _dict(item.get("match_rule"))
            if match_rule.get("kind") != "diagnosis_concept":
                continue
            spec = _dict(match_rule.get("spec"))
            _append_protected_text(protected_terms, spec.get("target"))
            for synonym in spec.get("synonyms") or []:
                _append_protected_text(protected_terms, synonym)
                _append_diagnosis_synonym_as_written(
                    protected_terms,
                    synonym,
                    item.get("description"),
                )


def _append_diagnosis_synonym_as_written(
    protected_terms: list[str],
    synonym: Any,
    description: Any,
) -> None:
    normalized_synonym = str(synonym or "").strip()
    normalized_description = str(description or "").strip()
    if not normalized_synonym or not normalized_description:
        return
    for suffix in ["病", "炎", "癌", "瘤", "综合征", "结石"]:
        rendered_term = f"{normalized_synonym}{suffix}"
        if rendered_term in normalized_description:
            _append_protected_text(protected_terms, rendered_term)


def _append_protected_text(protected_terms: list[str], value: Any) -> None:
    normalized = str(value or "").strip()
    if len(normalized) >= 3 and normalized not in protected_terms:
        protected_terms.append(normalized)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


__all__ = [
    "PROTECTED_DIAGNOSIS_PLACEHOLDER",
    "candidate_case_ids",
    "case_protected_terms",
    "sanitize_case_protected_text",
]
