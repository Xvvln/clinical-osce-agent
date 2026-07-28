import json
import sqlite3

import pytest

from app.services.training_skill_candidate_store import (
    TrainingSkillCandidateSourceDeletedError,
    TrainingSkillCandidateDeletedError,
    TrainingSkillCandidateOwnershipError,
    TrainingSkillCandidateStore,
)


def test_training_skill_candidate_store_persists_candidate_with_review_across_instances(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    candidate = {
        "candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "title": "临床推理链纠偏提示",
        "description": "3 份报告中有 2 次漏掉 reasoning_core，涉及病例：appendicitis_001、pneumonia_001。",
        "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
        "status": "draft",
        "source_report_count": 3,
        "support_count": 2,
        "related_recommendations": [
            "rubric:appendicitis_001_rubric.item.reasoning_core",
            "knowledge:appendicitis_001.rp_03",
        ],
    }
    review = {
        "candidate_id": "skill_candidate_reasoning_core",
        "status": "ready_for_review",
        "regression_passed": True,
        "evaluation_total_cases": 2,
        "evaluation_passed_cases": 2,
        "evaluation_failed_cases": 0,
        "blocking_failures": [],
    }

    TrainingSkillCandidateStore(database_path).save_candidate(candidate, review)
    loaded_candidate = TrainingSkillCandidateStore(database_path).get_candidate("skill_candidate_reasoning_core")

    assert loaded_candidate == {
        **candidate,
        "review": review,
    }


def test_training_skill_candidate_store_lists_candidate_summaries_in_insert_order(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    store = TrainingSkillCandidateStore(database_path)

    store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "status": "draft",
            "source_report_count": 3,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )
    store.save_candidate(
        {
            "candidate_id": "skill_candidate_ht_location",
            "trigger_item_id": "ht_location",
            "title": "OSCE 漏项纠偏提示",
            "status": "draft",
            "source_report_count": 4,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_ht_location",
            "status": "blocked_by_regression",
            "regression_passed": False,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 1,
            "evaluation_failed_cases": 1,
            "blocking_failures": [
                {
                    "session_id": "session_fail",
                    "actual_total_score": 0,
                    "expected_total_score": 55,
                    "forbidden_term_violations": ["治疗方案"],
                }
            ],
        },
    )

    summaries = TrainingSkillCandidateStore(database_path).list_candidate_summaries()

    assert summaries == [
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "trigger_item_ids": [],
            "case_ids": [],
            "skill_type": "",
            "stage_scope": [],
            "effect_status": "",
            "related_recommendations": [],
            "title": "临床推理链纠偏提示",
            "status": "ready_for_review",
            "regression_passed": True,
            "source_report_count": 3,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_ht_location",
            "trigger_item_id": "ht_location",
            "trigger_item_ids": [],
            "case_ids": [],
            "skill_type": "",
            "stage_scope": [],
            "effect_status": "",
            "related_recommendations": [],
            "title": "OSCE 漏项纠偏提示",
            "status": "blocked_by_regression",
            "regression_passed": False,
            "source_report_count": 4,
            "support_count": 2,
        },
    ]


def test_training_skill_candidate_store_does_not_overwrite_reviewed_candidate_when_saving_unless_reviewed(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    store = TrainingSkillCandidateStore(database_path)
    store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "status": "draft",
            "source_report_count": 2,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )
    assert store.approve_candidate("skill_candidate_reasoning_core", reviewer_id="teacher_demo") is True

    saved = store.save_candidate_unless_reviewed(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "刷新后的候选",
            "status": "draft",
            "source_report_count": 5,
            "support_count": 5,
        },
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "blocked_by_regression",
            "regression_passed": False,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 1,
            "evaluation_failed_cases": 1,
            "blocking_failures": [],
        },
    )

    candidate = TrainingSkillCandidateStore(database_path).get_candidate("skill_candidate_reasoning_core")
    assert saved is False
    assert candidate["title"] == "临床推理链纠偏提示"
    assert candidate["source_report_count"] == 2
    assert candidate["support_count"] == 2
    assert candidate["review"]["status"] == "approved"
    assert candidate["review"]["reviewer_id"] == "teacher_demo"


def test_training_skill_candidate_store_refreshes_unreviewed_candidate_when_saving_unless_reviewed(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    store = TrainingSkillCandidateStore(database_path)
    store.save_candidate(
        {
            "candidate_id": "skill_candidate_ht_location",
            "trigger_item_id": "ht_location",
            "title": "旧候选",
            "status": "draft",
            "source_report_count": 2,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_ht_location",
            "status": "blocked_by_regression",
            "regression_passed": False,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 1,
            "evaluation_failed_cases": 1,
            "blocking_failures": [],
        },
    )

    saved = store.save_candidate_unless_reviewed(
        {
            "candidate_id": "skill_candidate_ht_location",
            "trigger_item_id": "ht_location",
            "title": "刷新后的候选",
            "status": "draft",
            "source_report_count": 4,
            "support_count": 4,
        },
        {
            "candidate_id": "skill_candidate_ht_location",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )

    candidate = TrainingSkillCandidateStore(database_path).get_candidate("skill_candidate_ht_location")
    assert saved is True
    assert candidate["title"] == "刷新后的候选"
    assert candidate["source_report_count"] == 4
    assert candidate["support_count"] == 4
    assert candidate["review"]["status"] == "ready_for_review"


def test_training_skill_candidate_store_approves_ready_candidate(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    store = TrainingSkillCandidateStore(database_path)
    store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "status": "draft",
            "source_report_count": 3,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )

    approved = store.approve_candidate("skill_candidate_reasoning_core", reviewer_id="teacher_demo")

    assert approved is True
    assert TrainingSkillCandidateStore(database_path).get_candidate("skill_candidate_reasoning_core") == {
        "candidate_id": "skill_candidate_reasoning_core",
        "trigger_item_id": "reasoning_core",
        "title": "临床推理链纠偏提示",
        "status": "draft",
        "source_report_count": 3,
        "support_count": 2,
        "review": {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "approved",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
            "reviewer_id": "teacher_demo",
        },
    }


def test_training_skill_candidate_store_rejects_ready_candidate(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    store = TrainingSkillCandidateStore(database_path)
    store.save_candidate(
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "临床推理链纠偏提示",
            "status": "draft",
            "source_report_count": 3,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_reasoning_core",
            "status": "ready_for_review",
            "regression_passed": True,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 2,
            "evaluation_failed_cases": 0,
            "blocking_failures": [],
        },
    )

    rejected = store.reject_candidate("skill_candidate_reasoning_core", reviewer_id="teacher_demo")

    assert rejected is True
    assert TrainingSkillCandidateStore(database_path).get_candidate("skill_candidate_reasoning_core")["review"]["status"] == "rejected"


def test_training_skill_candidate_store_does_not_approve_blocked_candidate(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    store = TrainingSkillCandidateStore(database_path)
    store.save_candidate(
        {
            "candidate_id": "skill_candidate_ht_location",
            "trigger_item_id": "ht_location",
            "title": "OSCE 漏项纠偏提示",
            "status": "draft",
            "source_report_count": 4,
            "support_count": 2,
        },
        {
            "candidate_id": "skill_candidate_ht_location",
            "status": "blocked_by_regression",
            "regression_passed": False,
            "evaluation_total_cases": 2,
            "evaluation_passed_cases": 1,
            "evaluation_failed_cases": 1,
            "blocking_failures": [],
        },
    )

    approved = store.approve_candidate("skill_candidate_ht_location", reviewer_id="teacher_demo")

    assert approved is False
    assert TrainingSkillCandidateStore(database_path).get_candidate("skill_candidate_ht_location")["review"]["status"] == "blocked_by_regression"


def test_global_candidate_source_cleanup_deletes_unreviewed_stales_reviewed_and_fences_late_writes(
    tmp_path,
) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    store = TrainingSkillCandidateStore(database_path)
    source_session_id = "source-session"
    source_report_id = f"{source_session_id}_report"

    def candidate(candidate_id: str, review_status: str) -> dict[str, object]:
        return {
            "candidate_id": candidate_id,
            "trigger_item_id": candidate_id,
            "title": candidate_id,
            "description": "derived candidate",
            "suggested_strategy": "review evidence",
            "scope": "global",
            "source_session_ids": [source_session_id, "kept-session"],
            "source_report_ids": [source_report_id, "kept-session_report"],
            "source_turn_patterns": [
                {
                    "pattern_id": "turn-pattern",
                    "count": 2,
                    "session_ids": [source_session_id, "kept-session"],
                    "source_report_ids": [
                        source_report_id,
                        "kept-session_report",
                    ],
                    "source_report_count": 2,
                }
            ],
            "source_report_count": 2,
            "support_count": 2,
            "review": {
                "candidate_id": candidate_id,
                "status": review_status,
                "regression_passed": True,
            },
        }

    unreviewed = candidate("candidate-unreviewed", "ready_for_review")
    reviewed = candidate("candidate-reviewed", "approved")
    unrelated = {
        **candidate("candidate-unrelated", "approved"),
        "source_session_ids": ["unrelated-session"],
        "source_report_ids": ["unrelated-session_report"],
        "source_turn_patterns": [],
    }
    for item in (unreviewed, reviewed, unrelated):
        store.save_candidate(item, dict(item["review"]))

    cleanup = store.remove_global_source_contributions(
        source_session_id=source_session_id,
        owner_student_id="student-a",
        source_report_id=source_report_id,
    )

    assert cleanup.deleted_candidate_ids == ("candidate-unreviewed",)
    assert cleanup.stale_candidate_ids == ("candidate-reviewed",)
    assert cleanup.affected_candidate_ids == (
        "candidate-reviewed",
        "candidate-unreviewed",
    )
    assert store.get_candidate("candidate-unreviewed") is None
    stale = store.get_candidate("candidate-reviewed")
    assert stale is not None
    assert stale["source_session_ids"] == ["kept-session"]
    assert stale["source_report_ids"] == ["kept-session_report"]
    assert source_session_id not in str(stale)
    assert source_report_id not in str(stale)
    assert stale["support_count"] == 0
    assert stale["review"]["status"] == "stale_requires_review"
    assert stale["title"] == "来源证据已变化的训练候选"
    assert "derived candidate" not in str(stale)
    assert store.get_candidate("candidate-unrelated") is not None
    assert TrainingSkillCandidateStore(
        database_path
    ).remove_global_source_contributions(
        source_session_id=source_session_id,
        owner_student_id="student-a",
        source_report_id=source_report_id,
    ) == cleanup

    with pytest.raises(TrainingSkillCandidateSourceDeletedError):
        store.save_candidate(unreviewed, dict(unreviewed["review"]))

    regenerated = {
        **unreviewed,
        "source_provenance_schema_version": "training_candidate_sources.v1",
        "source_session_ids": ["kept-session"],
        "source_report_ids": ["kept-session_report"],
        "source_turn_patterns": [],
    }
    store.save_candidate(regenerated, dict(regenerated["review"]))
    assert store.get_candidate("candidate-unreviewed") is not None

    with pytest.raises(TrainingSkillCandidateOwnershipError):
        store.remove_global_source_contributions(
            source_session_id=source_session_id,
            owner_student_id="student-b",
            source_report_id=source_report_id,
        )


def test_reviewed_candidate_stays_stale_when_remaining_source_is_later_deleted(
    tmp_path,
) -> None:
    store = TrainingSkillCandidateStore(
        tmp_path / "training_skill_candidates.sqlite3"
    )
    candidate = {
        "candidate_id": "candidate-reviewed-sequential",
        "trigger_item_id": "reviewed-sequential",
        "title": "source-derived title",
        "description": "source-derived description",
        "suggested_strategy": "source-derived strategy",
        "scope": "global",
        "source_provenance_schema_version": "training_candidate_sources.v1",
        "source_session_ids": ["source-a", "source-b"],
        "source_report_ids": ["source-a_report", "source-b_report"],
        "source_report_count": 2,
        "support_count": 2,
        "review": {
            "candidate_id": "candidate-reviewed-sequential",
            "status": "approved",
            "regression_passed": True,
        },
    }
    store.save_candidate(candidate, dict(candidate["review"]))

    first = store.remove_global_source_contributions(
        source_session_id="source-a",
        owner_student_id="student-a",
        source_report_id="source-a_report",
    )
    second = store.remove_global_source_contributions(
        source_session_id="source-b",
        owner_student_id="student-a",
        source_report_id="source-b_report",
    )

    assert first.stale_candidate_ids == (
        "candidate-reviewed-sequential",
    )
    assert second.stale_candidate_ids == (
        "candidate-reviewed-sequential",
    )
    stale = store.get_candidate("candidate-reviewed-sequential")
    assert stale is not None
    assert stale["review"]["status"] == "stale_requires_review"
    assert stale["source_session_ids"] == []
    assert stale["source_report_ids"] == []


def test_personal_candidate_delete_is_exact_idempotent_and_blocks_late_saves(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    store = TrainingSkillCandidateStore(database_path)
    target, target_review = _personal_candidate(
        session_id="session_delete",
        owner_student_id="student_a",
    )
    other, other_review = _personal_candidate(
        session_id="session_keep",
        owner_student_id="student_a",
    )
    global_candidate = {
        **target,
        "candidate_id": "skill_candidate_global_keep",
        "trigger_item_id": "global_keep",
        "scope": "global",
        "owner_student_id": "",
        "source_session_id": "",
    }
    global_review = {**target_review, "candidate_id": "skill_candidate_global_keep"}
    store.save_candidate(target, target_review)
    store.save_candidate(other, other_review)
    store.save_candidate(global_candidate, global_review)

    with pytest.raises(TrainingSkillCandidateOwnershipError):
        store.delete_personal_candidate(
            candidate_id="personal_skill_candidate_session_delete",
            owner_student_id="student_b",
            source_session_id="session_delete",
        )
    assert store.get_candidate("personal_skill_candidate_session_delete") is not None

    assert store.delete_personal_candidate(
        candidate_id="personal_skill_candidate_session_delete",
        owner_student_id="student_a",
        source_session_id="session_delete",
    ) is True
    assert TrainingSkillCandidateStore(database_path).delete_personal_candidate(
        candidate_id="personal_skill_candidate_session_delete",
        owner_student_id="student_a",
        source_session_id="session_delete",
    ) is False
    assert store.get_candidate("personal_skill_candidate_session_delete") is None
    assert store.get_candidate("personal_skill_candidate_session_keep") is not None
    assert store.get_candidate("skill_candidate_global_keep") is not None

    with pytest.raises(TrainingSkillCandidateDeletedError):
        store.save_candidate(target, target_review)
    with pytest.raises(TrainingSkillCandidateDeletedError):
        store.save_candidate_unless_reviewed(target, target_review)

    assert store.delete_personal_candidate(
        candidate_id="personal_skill_candidate_session_missing",
        owner_student_id="student_a",
        source_session_id="session_missing",
    ) is False
    missing_candidate, missing_review = _personal_candidate(
        session_id="session_missing",
        owner_student_id="student_a",
    )
    with pytest.raises(TrainingSkillCandidateDeletedError):
        store.save_candidate(missing_candidate, missing_review)


def test_personal_candidate_delete_migrates_legacy_schema_and_never_deletes_global_record(tmp_path) -> None:
    database_path = tmp_path / "training_skill_candidates.sqlite3"
    session_id = "session_global_conflict"
    candidate_id = f"personal_skill_candidate_{session_id}"
    global_candidate, review = _personal_candidate(
        session_id=session_id,
        owner_student_id="student_a",
    )
    global_candidate["scope"] = "global"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE training_skill_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id TEXT NOT NULL UNIQUE,
                candidate_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO training_skill_candidates (candidate_id, candidate_json)
            VALUES (?, ?)
            """,
            (
                candidate_id,
                json.dumps({**global_candidate, "review": review}, ensure_ascii=False),
            ),
        )

    store = TrainingSkillCandidateStore(database_path)
    with pytest.raises(TrainingSkillCandidateOwnershipError):
        store.delete_personal_candidate(
            candidate_id=candidate_id,
            owner_student_id="student_a",
            source_session_id=session_id,
        )

    assert store.get_candidate(candidate_id) is not None
    with sqlite3.connect(database_path) as connection:
        tombstone_table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'training_skill_candidate_tombstones'
            """
        ).fetchone()
        tombstone_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM training_skill_candidate_tombstones
            WHERE candidate_id = ?
            """,
            (candidate_id,),
        ).fetchone()[0]
    assert tombstone_table == ("training_skill_candidate_tombstones",)
    assert tombstone_count == 0


def _personal_candidate(
    *,
    session_id: str,
    owner_student_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    candidate_id = f"personal_skill_candidate_{session_id}"
    candidate: dict[str, object] = {
        "candidate_id": candidate_id,
        "trigger_item_id": f"personal_{session_id}",
        "title": "个人复盘训练 Skill",
        "description": "根据本次训练生成的个人复盘建议。",
        "suggested_strategy": "提醒学生复盘证据链，不透露标准答案。",
        "status": "draft",
        "scope": "personal",
        "owner_student_id": owner_student_id,
        "source_session_id": session_id,
        "source_report_count": 1,
        "support_count": 1,
        "related_recommendations": [],
    }
    review: dict[str, object] = {
        "candidate_id": candidate_id,
        "status": "ready_for_review",
        "regression_passed": True,
        "evaluation_total_cases": 1,
        "evaluation_passed_cases": 1,
        "evaluation_failed_cases": 0,
        "blocking_failures": [],
    }
    return candidate, review
