from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SchemaVersion = Literal["1.1"]
CourseModule = Literal[
    "腹痛",
    "胸痛",
    "发热",
    "头痛",
    "咳嗽",
    "呼吸困难",
    "心悸",
    "消瘦",
    "黄疸",
    "水肿",
]
HistoryTopic = Literal[
    "现病史",
    "既往史",
    "家族史",
    "月经史",
    "生殖史",
    "个人史",
    "用药史",
    "过敏史",
    "社会史",
    "系统回顾",
    "ICE",
]
HistorySlot = Literal[
    "onset",
    "duration",
    "location",
    "character",
    "radiation",
    "severity",
    "aggravating",
    "relieving",
    "progression",
    "associated_symptom",
    "frequency",
    "timing",
    "context",
    "negation",
]
BlockingRule = Literal[
    "reveal_on_direct_question",
    "reveal_after_stage",
    "never_auto_reveal",
]
TestCategory = Literal["实验室", "影像", "心电", "内镜", "病理", "其他"]
ReasoningKind = Literal["支持", "排除", "鉴别"]


class RubricRef(BaseModel):
    rubric_id: str
    version: str = "v1"


class SourceAttribution(BaseModel):
    source_id: str
    transformation: str
    attribution_note: str
    modified: bool = True


class TeachingErrorPattern(BaseModel):
    pattern_id: str = Field(..., pattern=r"^[a-z0-9_]+_\d{3}\.pattern\.[a-z0-9_]+$")
    title: str
    focus: str
    related_rubric_items: list[str] = Field(default_factory=list)


class CaseTeachingFocus(BaseModel):
    learning_objectives: list[str] = Field(default_factory=list)
    common_error_patterns: list[TeachingErrorPattern] = Field(default_factory=list)
    recommended_training_path: list[str] = Field(default_factory=list)


class PatientProfile(BaseModel):
    name_placeholder: str = "×××"
    age_value: int = Field(..., ge=0, le=120)
    age_unit: Literal["岁", "月", "周"]
    gender: Literal["男", "女"]
    occupation: str
    marital_status: Literal["未婚", "已婚", "离异", "丧偶", "未知"] = "未知"
    address_city: str | None = None
    social_background: str | None = None
    hospital_department: str
    idea: str | None = None
    concern: str | None = None
    expectation: str | None = None


class HiddenFact(BaseModel):
    fact_id: str
    topic: HistoryTopic
    slot: HistorySlot | None = None
    canonical_answer: str
    variants: list[str] = Field(default_factory=list)
    trigger_intents: list[str] = Field(default_factory=list, min_length=1)
    blocking_rule: BlockingRule = "reveal_on_direct_question"
    linked_rubric_items: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_slot_requirement(self) -> "HiddenFact":
        if self.topic in {"现病史", "系统回顾"} and self.slot is None:
            raise ValueError("slot is required for current illness or system review facts")
        return self


class HistoryTaking(BaseModel):
    present_illness_summary: str
    hidden_facts: list[HiddenFact] = Field(..., min_length=1)
    past_medical_history: str | None = None
    surgery_injury_history: str | None = None
    transfusion_history: str | None = None
    infection_history: str | None = None
    allergy_history: str | None = None
    personal_history: str | None = None
    menstrual_history: str | None = None
    reproductive_history: str | None = None
    family_history: str | None = None


class PhysicalExamItem(BaseModel):
    exam_code: str = Field(..., pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    exam_name_cn: str
    result: str
    is_abnormal: bool
    linked_rubric_items: list[str] = Field(default_factory=list)


class PhysicalExamBundle(BaseModel):
    must_items: list[PhysicalExamItem] = Field(default_factory=list)
    optional_items: list[PhysicalExamItem] = Field(default_factory=list)


class AuxiliaryTestItem(BaseModel):
    test_code: str = Field(..., pattern=r"^(lab|img|ecg|endo|path|other)\.[a-z][a-z0-9_]*$")
    test_name_cn: str
    category: TestCategory
    invasiveness: Literal["无创", "微创", "有创"]
    cost_hint: Literal["基础", "中等", "昂贵"]
    result: str
    is_abnormal: bool
    linked_rubric_items: list[str] = Field(default_factory=list)


class AuxiliaryTestBundle(BaseModel):
    must_items: list[AuxiliaryTestItem] = Field(default_factory=list)
    optional_items: list[AuxiliaryTestItem] = Field(default_factory=list)
    forbidden_items: list[str] = Field(default_factory=list)


class ReasoningPoint(BaseModel):
    point_id: str
    statement: str
    kind: ReasoningKind
    required_evidence: list[str] = Field(default_factory=list)
    weight: int = Field(..., ge=1, le=10)


class DifferentialDiagnosis(BaseModel):
    disease_name: str
    icd10_hint: str | None = None
    expected_action: Literal["支持", "排除"]
    key_distinction: str


class DiagnosisSpec(BaseModel):
    main_diagnosis: str
    main_diagnosis_synonyms: list[str] = Field(default_factory=list)
    icd10_hint: str | None = None
    differential_diagnoses: list[DifferentialDiagnosis] = Field(..., min_length=2)
    reasoning_points: list[ReasoningPoint] = Field(..., min_length=1)
    suggested_next_steps: str


class Case(BaseModel):
    case_id: str = Field(..., pattern=r"^[a-z0-9_]+_\d{3}$")
    case_title: str
    course_module: CourseModule
    difficulty: Literal["初级", "中级", "高级"]
    patient_profile: PatientProfile
    chief_complaint: str
    history: HistoryTaking
    physical_exam: PhysicalExamBundle
    auxiliary_tests: AuxiliaryTestBundle
    diagnosis: DiagnosisSpec
    rubric_ref: RubricRef
    safety_notes: str = Field(..., min_length=1)
    source_attribution: SourceAttribution
    teaching_focus: CaseTeachingFocus = Field(default_factory=CaseTeachingFocus)
    schema_version: SchemaVersion = "1.1"
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return [tag for tag in value if tag]

    @model_validator(mode="after")
    def validate_business_rules(self) -> "Case":
        support_points = [point for point in self.diagnosis.reasoning_points if point.kind == "支持"]
        if len(support_points) < 3:
            raise ValueError("case must include at least 3 supporting reasoning points")

        forbidden_terms = [self.diagnosis.main_diagnosis, *self.diagnosis.main_diagnosis_synonyms]
        normalized_terms = [term.strip().lower() for term in forbidden_terms if term and term.strip()]
        for hidden_fact in self.history.hidden_facts:
            answer = hidden_fact.canonical_answer.lower()
            if any(term in answer for term in normalized_terms):
                raise ValueError("hidden fact leaks diagnosis term")

        for teaching_text in _teaching_focus_texts(self.teaching_focus):
            normalized_text = teaching_text.lower()
            if any(term in normalized_text for term in normalized_terms):
                raise ValueError("teaching focus leaks diagnosis term")

        reasoning_evidence = {
            evidence
            for point in self.diagnosis.reasoning_points
            for evidence in point.required_evidence
        }
        abnormal_codes = [
            exam.exam_code
            for exam in [*self.physical_exam.must_items, *self.physical_exam.optional_items]
            if exam.is_abnormal
        ]
        abnormal_codes.extend(
            test.test_code
            for test in [*self.auxiliary_tests.must_items, *self.auxiliary_tests.optional_items]
            if test.is_abnormal
        )
        missing_abnormal = [code for code in abnormal_codes if code not in reasoning_evidence]
        if missing_abnormal:
            raise ValueError(f"abnormal findings missing from reasoning evidence: {missing_abnormal}")

        banned_phrases = [
            "替代医生诊断",
            "替代医生作出诊断",
            "可替代医生诊断",
            "真实用药剂量",
            "急症处置方案",
        ]
        if any(phrase in self.safety_notes for phrase in banned_phrases):
            raise ValueError("safety notes contain banned medical claim")

        return self


def _teaching_focus_texts(teaching_focus: CaseTeachingFocus) -> list[str]:
    texts = [*teaching_focus.learning_objectives, *teaching_focus.recommended_training_path]
    for pattern in teaching_focus.common_error_patterns:
        texts.extend([pattern.title, pattern.focus])
    return texts


__all__ = [
    "AuxiliaryTestBundle",
    "AuxiliaryTestItem",
    "BlockingRule",
    "CaseTeachingFocus",
    "Case",
    "CourseModule",
    "DiagnosisSpec",
    "DifferentialDiagnosis",
    "HiddenFact",
    "HistorySlot",
    "HistoryTaking",
    "HistoryTopic",
    "PatientProfile",
    "PhysicalExamBundle",
    "PhysicalExamItem",
    "ReasoningKind",
    "ReasoningPoint",
    "RubricRef",
    "SchemaVersion",
    "SourceAttribution",
    "TeachingErrorPattern",
    "TestCategory",
]
