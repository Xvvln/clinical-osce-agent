import json

import yaml

import app.services.training_skill_content_safety as content_safety_module
from app.services.admin_display_resolver import (
    enrich_training_skill_candidate,
    rubric_item_label,
    trigger_item_label,
)
from app.services.training_skill_content_safety import (
    case_protected_terms,
    sanitize_case_protected_text,
)


def test_case_protected_terms_cover_answers_hidden_facts_and_results() -> None:
    protected_terms = case_protected_terms(["appendicitis_001"])

    assert "急性阑尾炎" in protected_terms
    assert "输尿管结石" in protected_terms
    assert "开始在上腹部，大约 8 小时前转移并固定到右下腹。" in protected_terms
    assert any("McBurney" in term for term in protected_terms)


def test_skill_labels_are_sanitized_without_changing_scoring_labels() -> None:
    safe_trigger_label = trigger_item_label("dx_main", ["appendicitis_001"])
    scoring_label = rubric_item_label("dx_main", ["appendicitis_001"])

    assert safe_trigger_label == "主要诊断命中当前病例诊断假设"
    assert scoring_label == "主要诊断命中急性阑尾炎"


def test_skill_candidate_source_labels_do_not_reintroduce_case_answers() -> None:
    candidate = enrich_training_skill_candidate(
        {
            "candidate_id": "skill_candidate_safe_labels",
            "case_ids": ["appendicitis_001"],
            "trigger_item_ids": ["dx_main", "dxd_urolith"],
            "related_recommendations": [
                "rubric:appendicitis_001_rubric.item.dx_main",
                "rubric:appendicitis_001_rubric.item.dxd_urolith",
            ],
        }
    )

    candidate_text = str(candidate)
    assert "急性阑尾炎" not in candidate_text
    assert "输尿管结石" not in candidate_text
    assert trigger_item_label("dxd_crohn", ["appendicitis_001"]) == (
        "提出当前病例诊断假设并说明排除依据"
    )
    assert candidate["trigger_item_labels"] == [
        "主要诊断命中当前病例诊断假设",
        "提出当前病例诊断假设并说明排除依据",
    ]


def test_hidden_fact_text_is_redacted_from_runtime_metadata() -> None:
    sanitized = sanitize_case_protected_text(
        "训练备注：开始在上腹部，大约 8 小时前转移并固定到右下腹。",
        ["appendicitis_001"],
    )

    assert "8 小时前" not in sanitized
    assert "当前病例诊断假设" in sanitized


def test_protected_term_cache_refreshes_after_case_asset_changes(tmp_path, monkeypatch) -> None:
    cases_dir = tmp_path / "cases"
    rubrics_dir = tmp_path / "rubrics"
    cases_dir.mkdir()
    rubrics_dir.mkdir()
    case_id = "cache_refresh_case"
    case_path = cases_dir / f"{case_id}.json"
    rubric_path = rubrics_dir / f"{case_id}_rubric.yaml"
    rubric_path.write_text(yaml.safe_dump({"dimensions": []}), encoding="utf-8")
    monkeypatch.setattr(content_safety_module, "CASES_DIR", cases_dir)
    monkeypatch.setattr(content_safety_module, "RUBRICS_DIR", rubrics_dir)

    case_path.write_text(
        json.dumps({"diagnosis": {"main_diagnosis": "旧诊断名称"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert "旧诊断名称" in case_protected_terms([case_id])

    case_path.write_text(
        json.dumps({"diagnosis": {"main_diagnosis": "更新后的诊断名称"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    refreshed_terms = case_protected_terms([case_id])
    assert "更新后的诊断名称" in refreshed_terms
    assert "旧诊断名称" not in refreshed_terms
