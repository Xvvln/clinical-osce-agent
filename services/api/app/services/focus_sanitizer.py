from __future__ import annotations

from app.models.case import Case


STUDENT_VISIBLE_FOCUS_KEYS = {
    "title",
    "description",
    "training_suggestion",
    "why_now",
}

UNSAFE_MEDICAL_ACTION_TERMS = [
    "真实用药剂量",
    "用药剂量",
    "给药剂量",
    "治疗方案",
    "手术方案",
    "急症处置方案",
    "处置建议",
]


def assert_student_safe_focus_text(text: str, case: Case | None = None) -> None:
    normalized_text = text.lower()
    if any(term.lower() in normalized_text for term in UNSAFE_MEDICAL_ACTION_TERMS):
        raise ValueError("unsafe medical action language")

    if case is None:
        return

    diagnosis_terms = [
        case.diagnosis.main_diagnosis,
        *case.diagnosis.main_diagnosis_synonyms,
    ]
    if any(term.strip().lower() in normalized_text for term in diagnosis_terms if term and term.strip()):
        raise ValueError("focus text leaks diagnosis")

    for hidden_fact in case.history.hidden_facts:
        if hidden_fact.canonical_answer.strip() and hidden_fact.canonical_answer.lower() in normalized_text:
            raise ValueError("focus text leaks hidden fact")


def assert_student_safe_focus_payload(payload: object, case: Case) -> None:
    for text in _student_visible_focus_texts(payload):
        assert_student_safe_focus_text(text, case)


def _student_visible_focus_texts(payload: object) -> list[str]:
    if isinstance(payload, dict):
        texts: list[str] = []
        for key, value in payload.items():
            if key in STUDENT_VISIBLE_FOCUS_KEYS and isinstance(value, str):
                texts.append(value)
                continue
            if isinstance(value, dict | list):
                texts.extend(_student_visible_focus_texts(value))
        return texts
    if isinstance(payload, list):
        texts: list[str] = []
        for value in payload:
            texts.extend(_student_visible_focus_texts(value))
        return texts
    return []
