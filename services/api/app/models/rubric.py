from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

DimensionId = Literal[
    "history_taking",
    "physical_exam",
    "auxiliary_test",
    "main_diagnosis",
    "differential_diagnosis",
    "reasoning",
]
ScoringMode = Literal["rule", "llm", "hybrid"]
MatchKind = Literal[
    "intent_keyword",
    "exam_code",
    "test_code",
    "diagnosis_concept",
    "reasoning_coverage",
    "llm_rubric",
]

REQUIRED_SPEC_KEYS: dict[str, set[str]] = {
    "intent_keyword": {"topic", "slot", "any_of_keywords"},
    "exam_code": {"exam_code", "must"},
    "test_code": {"test_code", "must", "deduct_if_forbidden"},
    "diagnosis_concept": {"target", "synonyms", "icd10_hint"},
    "reasoning_coverage": {"required_evidence", "min_coverage_ratio"},
    "llm_rubric": {"prompt_id", "max_score"},
}


class MatchRule(BaseModel):
    kind: MatchKind
    spec: dict[str, Any]

    @field_validator("spec")
    @classmethod
    def validate_spec_shape(cls, value: dict[str, Any], info: Any) -> dict[str, Any]:
        kind = info.data.get("kind")
        if kind is None:
            return value
        required_keys = REQUIRED_SPEC_KEYS[kind]
        missing_keys = sorted(required_keys - set(value.keys()))
        if missing_keys:
            raise ValueError(f"missing spec keys for {kind}: {missing_keys}")
        return value


class RubricItem(BaseModel):
    item_id: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$")
    description: str
    max_score: int = Field(..., ge=1, le=25)
    match_rule: MatchRule
    evidence_expected: list[str] = Field(default_factory=list)


class RubricDimension(BaseModel):
    dimension_id: DimensionId
    weight: int = Field(..., ge=1)
    scoring_mode: ScoringMode
    items: list[RubricItem] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_item_scores(self) -> "RubricDimension":
        oversized_items = [item.item_id for item in self.items if item.max_score > self.weight]
        if oversized_items:
            raise ValueError(f"item score exceeds dimension weight: {oversized_items}")
        return self


class LlmRubricRequest(BaseModel):
    rubric_item_id: str
    description: str
    max_score: int
    student_final_reasoning: str
    relevant_facts_revealed: list[str]
    required_evidence: list[str]


class LlmRubricResponse(BaseModel):
    score: int = Field(..., ge=0)
    covered_evidence: list[str]
    missing_evidence: list[str]
    rationale: str = Field(..., max_length=120)


class ScoreTrace(BaseModel):
    rubric_item_id: str
    awarded_score: int = Field(..., ge=0)
    max_score: int = Field(..., ge=1)
    match_kind: MatchKind
    matched_evidence: list[str]
    llm_rationale: str | None = None
    fallback_reason: str | None = None


class Rubric(BaseModel):
    rubric_id: str = Field(..., pattern=r"^[a-z0-9_]+_\d{3}_rubric(_[a-z]+)?$")
    case_id: str
    version: str = "v1"
    total_score: int = 100
    dimensions: list[RubricDimension] = Field(..., min_length=1)
    schema_version: Literal["1.1"] = "1.1"

    @model_validator(mode="after")
    def validate_scoring(self) -> "Rubric":
        total_weight = sum(dimension.weight for dimension in self.dimensions)
        if total_weight != self.total_score:
            raise ValueError("rubric dimension weights must sum to total_score")

        rule_score = sum(
            item.max_score
            for dimension in self.dimensions
            for item in dimension.items
            if item.match_rule.kind != "llm_rubric"
        )
        if rule_score / self.total_score < 0.65:
            raise ValueError("rule-based score ratio must be at least 0.65")

        return self


__all__ = [
    "DimensionId",
    "LlmRubricRequest",
    "LlmRubricResponse",
    "MatchKind",
    "MatchRule",
    "Rubric",
    "RubricDimension",
    "RubricItem",
    "ScoreTrace",
    "ScoringMode",
]
