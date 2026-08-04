import json
from datetime import date
from pathlib import Path

from app.services.rag_knowledge_store import RagKnowledgeStore
from app.services.source_freshness_service import enrich_source_freshness


ROOT_DIR = Path(__file__).resolve().parents[3]


def test_rag_knowledge_store_persists_and_filters_items(tmp_path) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")

    case_item = store.upsert_item(
        {
            "knowledge_id": "case:appendicitis_001:teaching:history_migration",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "teaching_note",
            "visibility": "pre_submit_safe",
            "allowed_agents": ["coach", "skill_approval"],
            "stage_scope": ["history"],
            "source_id": "fareez_osce_2022",
            "title": "右下腹痛问诊中的疼痛迁移",
            "text": "追问疼痛是否从上腹或脐周转移到右下腹，用于训练疼痛演变采集。",
            "tags": ["abdominal_pain", "history_taking"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )
    store.upsert_item(
        {
            "knowledge_id": "global:osce:history:pain_timeline",
            "scope": "global",
            "case_id": "",
            "content_kind": "teaching_note",
            "visibility": "pre_submit_safe",
            "allowed_agents": ["coach"],
            "source_id": "",
            "title": "疼痛时间线",
            "text": "腹痛问诊应先明确起病时间、演变、部位、性质和伴随表现。",
            "tags": ["history_taking"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )

    assert case_item["updated_by"] == "admin@example.test"
    assert case_item["allowed_agents"] == ["coach", "skill_approval"]
    assert case_item["stage_scope"] == ["history_taking"]
    assert case_item["tags"] == ["abdominal_pain", "history_taking"]
    assert case_item["updated_at"]

    assert store.get_item("case:appendicitis_001:teaching:history_migration") == case_item
    assert [item["knowledge_id"] for item in store.list_items(scope="case")] == [
        "case:appendicitis_001:teaching:history_migration"
    ]
    assert [item["knowledge_id"] for item in store.list_items(case_id="appendicitis_001")] == [
        "case:appendicitis_001:teaching:history_migration"
    ]
    assert len(store.list_items(visibility="pre_submit_safe")) == 2
    assert store.get_item("global:osce:history:pain_timeline")["stage_scope"] == ["any"]

    assert store.delete_item("case:appendicitis_001:teaching:history_migration")
    assert store.get_item("case:appendicitis_001:teaching:history_migration") is None
    assert not store.delete_item("case:appendicitis_001:teaching:history_migration")


def test_rag_knowledge_store_persists_review_audit_and_document_counts(tmp_path) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    document_id = "kbdoc:global:risk-review"
    for chunk_index, review_status in enumerate(["approved", "pending_review"]):
        store.upsert_item(
            {
                "knowledge_id": f"{document_id}:chunk:{chunk_index:04d}",
                "scope": "global",
                "case_id": "",
                "content_kind": "document_chunk",
                "visibility": "post_submit_review",
                "allowed_agents": ["reflection"],
                "source_id": "",
                "title": f"片段 {chunk_index + 1}",
                "text": "教学复盘内容",
                "tags": ["review"],
                "document_id": document_id,
                "document_name": "review.md",
                "chunk_index": chunk_index,
                "chunk_count": 2,
                "review_status": review_status,
                "enabled": True,
            },
            updated_by="admin@example.test",
        )

    before_review = store.list_documents()[0]
    assert before_review["review_status"] == "pending_review"
    assert before_review["approved_chunk_count"] == 1
    assert before_review["pending_review_chunk_count"] == 1
    assert before_review["indexable_chunk_count"] == 1

    reviewed_document = store.set_document_review_status(
        document_id,
        review_status="rejected",
        review_note="内容不适合入库",
        reviewed_by="reviewer@example.test",
    )

    assert reviewed_document is not None
    assert reviewed_document["review_status"] == "mixed"
    assert reviewed_document["approved_chunk_count"] == 1
    assert reviewed_document["rejected_chunk_count"] == 1
    rejected_item = store.get_item(f"{document_id}:chunk:0001")
    assert rejected_item is not None
    assert rejected_item["review_status"] == "rejected"
    assert rejected_item["review_note"] == "内容不适合入库"
    assert rejected_item["reviewed_by"] == "reviewer@example.test"
    assert rejected_item["reviewed_at"]


def test_rag_knowledge_store_can_seed_public_appendicitis_teaching_items(tmp_path) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3", seed_defaults=True)

    seeded_items = store.list_items(case_id="appendicitis_001")
    seeded_ids = {item["knowledge_id"] for item in seeded_items}

    assert "case:appendicitis_001:coach:abdominal_pain_history_sequence" in seeded_ids
    assert "case:appendicitis_001:reflection:appendicitis_reasoning_review" in seeded_ids
    coach_item = store.get_item("case:appendicitis_001:coach:abdominal_pain_history_sequence")
    assert coach_item is not None
    assert coach_item["visibility"] == "pre_submit_safe"
    assert coach_item["allowed_agents"] == ["coach"]
    assert coach_item["stage_scope"] == ["case_intro", "history_taking"]
    assert coach_item["source_id"] == "aafp_acute_abdominal_pain_2023"
    assert "急性阑尾炎" not in coach_item["text"]

    reflection_item = store.get_item("case:appendicitis_001:reflection:appendicitis_reasoning_review")
    assert reflection_item is not None
    assert reflection_item["visibility"] == "post_submit_review"
    assert reflection_item["stage_scope"] == ["feedback"]
    assert "急性阑尾炎" in reflection_item["text"]


def test_rag_knowledge_store_seeds_coach_notes_for_each_demo_case(tmp_path) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3", seed_defaults=True)

    expected_diagnoses = {
        "appendicitis_001": "急性阑尾炎",
        "acs_001": "急性冠脉综合征",
        "heart_failure_001": "心力衰竭",
        "hyperthyroid_001": "甲状腺功能亢进",
        "pneumonia_001": "社区获得性肺炎",
    }

    for case_id, diagnosis in expected_diagnoses.items():
        case_items = store.list_items(case_id=case_id)
        pre_submit_items = [
            item
            for item in case_items
            if item["visibility"] == "pre_submit_safe"
        ]
        post_submit_items = [
            item
            for item in case_items
            if item["visibility"] == "post_submit_review"
        ]

        assert len(pre_submit_items) == 3
        assert {tuple(item["stage_scope"]) for item in pre_submit_items} == {
            ("case_intro", "history_taking"),
            ("physical_exam",),
            ("auxiliary_test",),
        }
        assert all(item["allowed_agents"] == ["coach"] for item in pre_submit_items)
        assert diagnosis not in " ".join(item["text"] for item in pre_submit_items)

        assert len(post_submit_items) == 2
        assert {item["content_kind"] for item in post_submit_items} == {
            "reflection_note",
            "skill_generation_note",
        }
        assert all("reflection" in item["allowed_agents"] for item in post_submit_items)
        assert all("skill_generation" in item["allowed_agents"] for item in post_submit_items)


def test_rag_knowledge_store_exposes_default_items_as_approved_builtin_documents(tmp_path) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3", seed_defaults=True)

    documents = store.list_documents()

    assert len(documents) == 26
    assert all(document["document_id"].startswith("builtin:") for document in documents)
    assert all(document["file_name"].startswith("内置知识｜") for document in documents)
    assert all(document["chunk_count"] == 1 for document in documents)
    assert all(document["review_status"] == "approved" for document in documents)
    assert all(document["enabled"] is True for document in documents)
    assert all(document["indexable_chunk_count"] == 1 for document in documents)

    pneumonia_item = store.get_item(
        "case:pneumonia_001:coach:cough_fever_history_sequence"
    )
    assert pneumonia_item is not None
    pneumonia_document = next(
        document
        for document in documents
        if document["document_id"] == pneumonia_item["document_id"]
    )
    assert pneumonia_document["case_id"] == "pneumonia_001"
    assert pneumonia_document["allowed_agents"] == ["coach"]
    assert pneumonia_document["stage_scope"] == ["case_intro", "history_taking"]


def test_default_knowledge_only_uses_current_registered_sources() -> None:
    default_items = json.loads(
        (ROOT_DIR / "data" / "rag_knowledge" / "default_items.json").read_text(encoding="utf-8")
    )
    source_registry = json.loads(
        (ROOT_DIR / "data" / "attribution" / "source_registry" / "sources.json").read_text(
            encoding="utf-8"
        )
    )
    sources_by_id = {
        source["source_id"]: enrich_source_freshness(source, today=date(2026, 8, 4))
        for source in source_registry
    }

    assert len(default_items) == 26
    assert all(item.get("source_id") in sources_by_id for item in default_items)
    assert all(
        sources_by_id[item["source_id"]]["selectable_for_new_knowledge"] is True
        for item in default_items
    )


def test_rag_knowledge_store_refreshes_default_seed_without_overwriting_admin_edits(tmp_path) -> None:
    seed_path = tmp_path / "default_items.json"
    seed_path.write_text(
        """
        [
          {
            "knowledge_id": "global:demo:seed",
            "scope": "global",
            "content_kind": "coach_hint_note",
            "visibility": "pre_submit_safe",
            "allowed_agents": ["coach"],
            "source_id": "fareez_osce_2022",
            "title": "默认种子",
            "text": "旧版默认内容",
            "tags": ["demo"]
          }
        ]
        """,
        encoding="utf-8",
    )
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3", seed_defaults=True, seed_path=seed_path)

    assert store.get_item("global:demo:seed")["text"] == "旧版默认内容"

    seed_path.write_text(
        """
        [
          {
            "knowledge_id": "global:demo:seed",
            "scope": "global",
            "content_kind": "coach_hint_note",
            "visibility": "pre_submit_safe",
            "allowed_agents": ["coach"],
            "source_id": "fareez_osce_2022",
            "title": "默认种子",
            "text": "新版默认内容",
            "tags": ["demo"]
          }
        ]
        """,
        encoding="utf-8",
    )

    assert store.get_item("global:demo:seed")["text"] == "新版默认内容"

    store.upsert_item(
        {
            "knowledge_id": "global:demo:seed",
            "scope": "global",
            "content_kind": "coach_hint_note",
            "visibility": "pre_submit_safe",
            "allowed_agents": ["coach"],
            "source_id": "fareez_osce_2022",
            "title": "管理员编辑",
            "text": "管理员内容",
            "tags": ["demo"],
        },
        updated_by="admin@example.test",
    )
    seed_path.write_text(
        """
        [
          {
            "knowledge_id": "global:demo:seed",
            "scope": "global",
            "content_kind": "coach_hint_note",
            "visibility": "pre_submit_safe",
            "allowed_agents": ["coach"],
            "source_id": "fareez_osce_2022",
            "title": "默认种子",
            "text": "再次更新默认内容",
            "tags": ["demo"]
          }
        ]
        """,
        encoding="utf-8",
    )

    assert store.get_item("global:demo:seed")["text"] == "管理员内容"
