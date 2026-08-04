from datetime import UTC, datetime, timedelta

import pytest

from app.services.admin_evaluation_config_store import AdminEvaluationConfigStore


def default_case() -> dict[str, object]:
    return {
        "case_key": "appendicitis_flow",
        "label": "阑尾炎链路",
        "case_id": "appendicitis_001",
        "steps": [{"kind": "submit_diagnosis", "value": "急性阑尾炎", "reasoning": "证据"}],
        "expected_total_score": 22,
        "forbidden_terms": [],
        "enabled": True,
    }


def default_suite() -> dict[str, object]:
    return {
        "suite_id": "default_regression",
        "label": "默认回归",
        "description": "核心链路",
        "case_keys": ["appendicitis_flow"],
        "thresholds": {"minimum_batch_pass_rate": 1.0},
        "enabled": True,
    }


def test_evaluation_config_store_persists_cases_suites_and_schedule(tmp_path) -> None:
    database_path = tmp_path / "evaluation_config.sqlite3"
    store = AdminEvaluationConfigStore(database_path)
    store.ensure_defaults(evaluation_case=default_case(), suite=default_suite())

    saved_case = store.upsert_case(
        {
            **default_case(),
            "case_key": "pneumonia_flow",
            "case_id": "pneumonia_001",
            "label": "肺炎链路",
        },
        updated_by="teacher@example.com",
    )
    saved_suite = store.upsert_suite(
        {
            **default_suite(),
            "suite_id": "respiratory_regression",
            "label": "呼吸系统回归",
            "case_keys": ["pneumonia_flow"],
        },
        updated_by="teacher@example.com",
    )
    schedule = store.update_schedule(
        {
            "enabled": True,
            "suite_id": "respiratory_regression",
            "interval_minutes": 60,
        },
        updated_by="teacher@example.com",
    )

    reloaded = AdminEvaluationConfigStore(database_path)
    assert reloaded.get_case("pneumonia_flow") == saved_case
    assert reloaded.get_suite("respiratory_regression") == saved_suite
    assert reloaded.get_schedule() == schedule
    assert schedule["status"] == "scheduled"
    assert schedule["next_run_at"]


def test_evaluation_config_store_claims_due_schedule_once_and_records_completion(tmp_path) -> None:
    store = AdminEvaluationConfigStore(tmp_path / "evaluation_config.sqlite3")
    store.ensure_defaults(evaluation_case=default_case(), suite=default_suite())
    schedule = store.update_schedule(
        {"enabled": True, "suite_id": "default_regression", "interval_minutes": 30},
        updated_by="admin@example.com",
    )
    due_at = datetime.fromisoformat(schedule["next_run_at"]) + timedelta(seconds=1)

    claimed = store.claim_due_schedule(due_at)

    assert claimed is not None
    assert claimed["status"] == "running"
    assert store.claim_due_schedule(due_at) is None
    completed = store.complete_schedule_run(batch_id="scheduled_batch")
    assert completed["status"] == "scheduled"
    assert completed["last_batch_id"] == "scheduled_batch"
    assert completed["last_error"] == ""


def test_evaluation_config_store_protects_referenced_and_builtin_records(tmp_path) -> None:
    store = AdminEvaluationConfigStore(tmp_path / "evaluation_config.sqlite3")
    store.ensure_defaults(evaluation_case=default_case(), suite=default_suite())
    custom_case = {
        **default_case(),
        "case_key": "custom_flow",
        "label": "自定义链路",
    }
    store.upsert_case(custom_case, updated_by="admin@example.com")
    store.upsert_suite(
        {
            **default_suite(),
            "suite_id": "custom_suite",
            "case_keys": ["custom_flow"],
        },
        updated_by="admin@example.com",
    )

    with pytest.raises(ValueError, match="built-in"):
        store.delete_case("appendicitis_flow")
    with pytest.raises(ValueError, match="used by a suite"):
        store.delete_case("custom_flow")
    with pytest.raises(ValueError, match="built-in"):
        store.delete_suite("default_regression")

    assert datetime.now(UTC).tzinfo is not None
