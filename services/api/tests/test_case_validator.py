from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Callable

import pytest


ValidateCase = Callable[[dict[str, Any]], Any]
ValidateRubric = Callable[[dict[str, Any]], Any]
ValidateCaseRubricPair = Callable[[Any, Any], None]


def _load_module(module_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        pytest.fail(
            "红灯：Step 2 合同尚未落地，无法导入模块 "
            f"{module_name!r}。缺少模块：{exc.name!r}。"
            "请先实现文档约定的模型与校验器，再让此测试转绿。"
        )


def _load_step2_contract() -> tuple[type[Any], type[Any], ValidateCase, ValidateRubric, ValidateCaseRubricPair]:
    case_module = _load_module("app.models.case")
    rubric_module = _load_module("app.models.rubric")
    validator_module = _load_module("app.validators.case_validator")

    case_type = getattr(case_module, "Case", None)
    if case_type is None:
        pytest.fail("红灯：`app.models.case.Case` 尚未实现。")

    rubric_type = getattr(rubric_module, "Rubric", None)
    if rubric_type is None:
        pytest.fail("红灯：`app.models.rubric.Rubric` 尚未实现。")

    validate_case = getattr(validator_module, "validate_case", None)
    if validate_case is None:
        pytest.fail("红灯：`app.validators.case_validator.validate_case` 尚未实现。")

    validate_rubric = getattr(validator_module, "validate_rubric", None)
    if validate_rubric is None:
        pytest.fail("红灯：`app.validators.case_validator.validate_rubric` 尚未实现。")

    validate_case_rubric_pair = getattr(validator_module, "validate_case_rubric_pair", None)
    if validate_case_rubric_pair is None:
        pytest.fail("红灯：`app.validators.case_validator.validate_case_rubric_pair` 尚未实现。")

    return case_type, rubric_type, validate_case, validate_rubric, validate_case_rubric_pair


def _load_yaml_module() -> Any:
    try:
        return importlib.import_module("yaml")
    except ModuleNotFoundError:
        pytest.fail("红灯：缺少 `yaml` 模块，无法读取未来的 rubric YAML 样例文件。")


def build_valid_case_payload() -> dict[str, Any]:
    case_id = "abdominal_pain_001"

    return {
        "case_id": case_id,
        "case_title": "右下腹痛教学病例",
        "course_module": "腹痛",
        "difficulty": "初级",
        "patient_profile": {
            "name_placeholder": "×××",
            "age_value": 22,
            "age_unit": "岁",
            "gender": "男",
            "occupation": "学生",
            "marital_status": "未婚",
            "address_city": "北京",
            "social_background": "无烟酒嗜好",
            "hospital_department": "急诊外科",
            "idea": "担心是不是吃坏了肚子",
            "concern": "怕要做手术",
            "expectation": "希望尽快明确原因并缓解疼痛",
        },
        "chief_complaint": "转移性右下腹痛 24 小时，伴恶心、低热",
        "history": {
            "present_illness_summary": "24 小时前出现上腹隐痛，后转移至右下腹，伴恶心和低热。",
            "hidden_facts": [
                {
                    "fact_id": f"{case_id}.hf_01",
                    "topic": "现病史",
                    "slot": "onset",
                    "canonical_answer": "24 小时前开始，最初是上腹部隐痛。",
                    "variants": ["昨天开始的", "差不多一天前开始"],
                    "trigger_intents": ["ask_onset"],
                    "blocking_rule": "reveal_on_direct_question",
                    "linked_rubric_items": ["ht_onset"],
                },
                {
                    "fact_id": f"{case_id}.hf_02",
                    "topic": "现病史",
                    "slot": "location",
                    "canonical_answer": "疼痛后来转移并固定到右下腹。",
                    "variants": ["后来跑到右下腹了"],
                    "trigger_intents": ["ask_location"],
                    "blocking_rule": "never_auto_reveal",
                    "linked_rubric_items": ["ht_location"],
                },
                {
                    "fact_id": f"{case_id}.hf_03",
                    "topic": "现病史",
                    "slot": "associated_symptom",
                    "canonical_answer": "伴有恶心，没有明显腹泻。",
                    "variants": ["有点恶心", "没有拉肚子"],
                    "trigger_intents": ["ask_associated_symptom"],
                    "blocking_rule": "reveal_on_direct_question",
                    "linked_rubric_items": ["ht_associated_symptom"],
                },
                {
                    "fact_id": f"{case_id}.hf_04",
                    "topic": "既往史",
                    "slot": None,
                    "canonical_answer": "既往体健，无腹部手术史。",
                    "variants": ["以前身体还可以"],
                    "trigger_intents": ["ask_past_medical_history"],
                    "blocking_rule": "reveal_on_direct_question",
                    "linked_rubric_items": ["ht_past_history"],
                },
            ],
            "past_medical_history": "既往体健。",
            "surgery_injury_history": "无腹部手术史。",
            "transfusion_history": "无。",
            "infection_history": "无特殊。",
            "allergy_history": "无药物过敏史。",
            "personal_history": "否认烟酒嗜好。",
            "menstrual_history": None,
            "reproductive_history": None,
            "family_history": "家族中无类似病史。",
        },
        "physical_exam": {
            "must_items": [
                {
                    "exam_code": "abd.palpation.tenderness",
                    "exam_name_cn": "右下腹压痛",
                    "result": "右下腹局限性压痛阳性。",
                    "is_abnormal": True,
                    "linked_rubric_items": ["pe_tenderness"],
                },
                {
                    "exam_code": "abd.palpation.rebound",
                    "exam_name_cn": "反跳痛",
                    "result": "右下腹反跳痛阳性。",
                    "is_abnormal": True,
                    "linked_rubric_items": ["pe_rebound"],
                },
            ],
            "optional_items": [],
        },
        "auxiliary_tests": {
            "must_items": [
                {
                    "test_code": "lab.cbc",
                    "test_name_cn": "血常规",
                    "category": "实验室",
                    "invasiveness": "无创",
                    "cost_hint": "基础",
                    "result": "白细胞升高，中性粒细胞比例升高。",
                    "is_abnormal": True,
                    "linked_rubric_items": ["at_cbc"],
                }
            ],
            "optional_items": [],
            "forbidden_items": ["img.abd_ct"],
        },
        "diagnosis": {
            "main_diagnosis": "急性阑尾炎",
            "main_diagnosis_synonyms": ["阑尾炎", "Acute appendicitis"],
            "icd10_hint": "K35",
            "differential_diagnoses": [
                {
                    "disease_name": "急性胃肠炎",
                    "icd10_hint": "A09",
                    "expected_action": "排除",
                    "key_distinction": "通常腹泻更明显，转移性右下腹痛不典型。",
                },
                {
                    "disease_name": "输尿管结石",
                    "icd10_hint": "N20",
                    "expected_action": "排除",
                    "key_distinction": "常有绞痛及血尿，腹膜刺激征不典型。",
                },
            ],
            "reasoning_points": [
                {
                    "point_id": f"{case_id}.rp_01",
                    "statement": "转移并固定的右下腹痛支持急性阑尾炎。",
                    "kind": "支持",
                    "required_evidence": [f"{case_id}.hf_02"],
                    "weight": 8,
                },
                {
                    "point_id": f"{case_id}.rp_02",
                    "statement": "右下腹压痛和反跳痛提示局部腹膜刺激征。",
                    "kind": "支持",
                    "required_evidence": [
                        "abd.palpation.tenderness",
                        "abd.palpation.rebound",
                    ],
                    "weight": 8,
                },
                {
                    "point_id": f"{case_id}.rp_03",
                    "statement": "白细胞升高支持急性炎症过程。",
                    "kind": "支持",
                    "required_evidence": ["lab.cbc"],
                    "weight": 7,
                },
            ],
            "suggested_next_steps": "建议进一步外科评估并结合病情决定后续处理。",
        },
        "rubric_ref": {
            "rubric_id": f"{case_id}_rubric",
            "version": "v1",
        },
        "safety_notes": "本病例仅用于医学教育模拟，不替代真实诊疗决策。",
        "source_attribution": {
            "source_id": "easymed_repo",
            "transformation": "基于公开资料改写并补充教学字段。",
            "attribution_note": "公开资料改写，仅用于教学模拟。",
            "modified": True,
        },
        "schema_version": "1.1",
        "tags": ["腹痛", "急腹症"],
    }


def build_valid_rubric_payload(case_id: str = "abdominal_pain_001") -> dict[str, Any]:
    return {
        "rubric_id": f"{case_id}_rubric",
        "case_id": case_id,
        "version": "v1",
        "total_score": 100,
        "schema_version": "1.1",
        "dimensions": [
            {
                "dimension_id": "history_taking",
                "weight": 25,
                "scoring_mode": "rule",
                "items": [
                    {
                        "item_id": "ht_onset",
                        "description": "追问起病时间",
                        "max_score": 10,
                        "match_rule": {
                            "kind": "intent_keyword",
                            "spec": {
                                "topic": "现病史",
                                "slot": "onset",
                                "any_of_keywords": ["什么时候", "起病", "开始"],
                            },
                        },
                        "evidence_expected": [f"{case_id}.hf_01"],
                    },
                    {
                        "item_id": "ht_location",
                        "description": "追问疼痛部位与转移",
                        "max_score": 15,
                        "match_rule": {
                            "kind": "intent_keyword",
                            "spec": {
                                "topic": "现病史",
                                "slot": "location",
                                "any_of_keywords": ["哪里疼", "部位", "转移"],
                            },
                        },
                        "evidence_expected": [f"{case_id}.hf_02"],
                    },
                ],
            },
            {
                "dimension_id": "physical_exam",
                "weight": 15,
                "scoring_mode": "rule",
                "items": [
                    {
                        "item_id": "pe_rebound",
                        "description": "请求右下腹反跳痛检查",
                        "max_score": 15,
                        "match_rule": {
                            "kind": "exam_code",
                            "spec": {
                                "exam_code": "abd.palpation.rebound",
                                "must": True,
                            },
                        },
                        "evidence_expected": ["abd.palpation.rebound"],
                    }
                ],
            },
            {
                "dimension_id": "auxiliary_test",
                "weight": 15,
                "scoring_mode": "rule",
                "items": [
                    {
                        "item_id": "at_cbc",
                        "description": "请求血常规",
                        "max_score": 15,
                        "match_rule": {
                            "kind": "test_code",
                            "spec": {
                                "test_code": "lab.cbc",
                                "must": True,
                                "deduct_if_forbidden": 0,
                            },
                        },
                        "evidence_expected": ["lab.cbc"],
                    }
                ],
            },
            {
                "dimension_id": "main_diagnosis",
                "weight": 15,
                "scoring_mode": "rule",
                "items": [
                    {
                        "item_id": "dx_appendicitis",
                        "description": "主诊断命中急性阑尾炎",
                        "max_score": 15,
                        "match_rule": {
                            "kind": "diagnosis_concept",
                            "spec": {
                                "target": "急性阑尾炎",
                                "synonyms": ["阑尾炎", "Acute appendicitis"],
                                "icd10_hint": "K35",
                            },
                        },
                        "evidence_expected": [],
                    }
                ],
            },
            {
                "dimension_id": "differential_diagnosis",
                "weight": 15,
                "scoring_mode": "llm",
                "items": [
                    {
                        "item_id": "dd_reasonable",
                        "description": "鉴别诊断覆盖常见右下腹痛病因且表述合理",
                        "max_score": 15,
                        "match_rule": {
                            "kind": "llm_rubric",
                            "spec": {
                                "prompt_id": "differential_quality_v1",
                                "max_score": 15,
                            },
                        },
                        "evidence_expected": [f"{case_id}.rp_01"],
                    }
                ],
            },
            {
                "dimension_id": "reasoning",
                "weight": 15,
                "scoring_mode": "llm",
                "items": [
                    {
                        "item_id": "reasoning_core",
                        "description": "推理链覆盖关键证据并能自圆其说",
                        "max_score": 15,
                        "match_rule": {
                            "kind": "llm_rubric",
                            "spec": {
                                "prompt_id": "reasoning_quality_v1",
                                "max_score": 15,
                            },
                        },
                        "evidence_expected": [
                            f"{case_id}.rp_01",
                            f"{case_id}.rp_02",
                            f"{case_id}.rp_03",
                        ],
                    }
                ],
            },
        ],
    }


def test_case_missing_reasoning_rejected() -> None:
    _, _, validate_case, _, _ = _load_step2_contract()
    payload = build_valid_case_payload()
    payload["diagnosis"].pop("reasoning_points")

    with pytest.raises(Exception):
        validate_case(payload)


def test_hidden_fact_leaks_diagnosis_rejected() -> None:
    _, _, validate_case, _, _ = _load_step2_contract()
    payload = build_valid_case_payload()
    payload["history"]["hidden_facts"][0]["canonical_answer"] = "医生已经告诉我是急性阑尾炎了。"

    with pytest.raises(Exception):
        validate_case(payload)


def test_teaching_focus_leaks_diagnosis_rejected() -> None:
    _, _, validate_case, _, _ = _load_step2_contract()
    payload = build_valid_case_payload()
    payload["teaching_focus"] = {
        "learning_objectives": ["直接识别急性阑尾炎并提交标准诊断。"],
        "common_error_patterns": [
            {
                "pattern_id": "appendicitis_001.pattern.leak",
                "title": "诊断泄露",
                "focus": "提醒学生本病例标准诊断是急性阑尾炎。",
                "related_rubric_items": ["dx_main"],
            }
        ],
        "recommended_training_path": ["先说出急性阑尾炎，再补问诊。"],
    }

    with pytest.raises(Exception, match="teaching focus leaks diagnosis term"):
        validate_case(payload)


def test_rubric_weight_sum_must_equal_100() -> None:
    _, _, _, validate_rubric, _ = _load_step2_contract()
    payload = build_valid_rubric_payload()
    payload["dimensions"][0]["weight"] = 24

    with pytest.raises(Exception):
        validate_rubric(payload)


def test_rubric_evidence_must_exist_in_case() -> None:
    _, _, validate_case, validate_rubric, validate_case_rubric_pair = _load_step2_contract()
    case_payload = build_valid_case_payload()
    rubric_payload = build_valid_rubric_payload(case_id=case_payload["case_id"])
    rubric_payload["dimensions"][0]["items"][0]["evidence_expected"] = ["missing.evidence_id"]

    case_model = validate_case(case_payload)
    rubric_model = validate_rubric(rubric_payload)

    with pytest.raises(Exception):
        validate_case_rubric_pair(case_model, rubric_model)


def _assert_case_rubric_roundtrip(case_name: str) -> None:
    case_type, rubric_type, validate_case, validate_rubric, validate_case_rubric_pair = _load_step2_contract()
    repo_root = Path(__file__).resolve().parents[3]
    case_path = repo_root / "data" / "cases" / f"{case_name}.json"
    rubric_path = repo_root / "data" / "rubrics" / f"{case_name}_rubric.yaml"

    assert case_path.exists(), (
        f"红灯：缺少未来样例文件 `data/cases/{case_name}.json`，"
        "Step 2/3 落地后此测试应改为通过。"
    )
    assert rubric_path.exists(), (
        f"红灯：缺少未来样例文件 `data/rubrics/{case_name}_rubric.yaml`，"
        "Step 2/3 落地后此测试应改为通过。"
    )

    case_payload = json.loads(case_path.read_text(encoding="utf-8"))
    yaml_module = _load_yaml_module()
    rubric_payload = yaml_module.safe_load(rubric_path.read_text(encoding="utf-8"))

    case_model = validate_case(case_payload)
    rubric_model = validate_rubric(rubric_payload)

    assert isinstance(case_model, case_type)
    assert isinstance(rubric_model, rubric_type)

    validate_case_rubric_pair(case_model, rubric_model)

    assert case_model.model_dump(mode="json") == case_payload
    assert rubric_model.case_id == case_model.case_id


def test_appendicitis_001_roundtrip() -> None:
    _assert_case_rubric_roundtrip("appendicitis_001")


def test_pneumonia_001_roundtrip() -> None:
    _assert_case_rubric_roundtrip("pneumonia_001")


def test_acs_001_roundtrip() -> None:
    _assert_case_rubric_roundtrip("acs_001")


def test_heart_failure_001_roundtrip() -> None:
    _assert_case_rubric_roundtrip("heart_failure_001")
