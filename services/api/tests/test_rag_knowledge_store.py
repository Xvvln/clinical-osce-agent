from app.services.rag_knowledge_store import RagKnowledgeStore


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

    expected_case_ids = {
        "appendicitis_001",
        "acs_001",
        "heart_failure_001",
        "hyperthyroid_001",
        "pneumonia_001",
    }
    seeded_case_ids = {
        item["case_id"]
        for item in store.list_items(visibility="pre_submit_safe")
        if item["scope"] == "case" and "coach" in item["allowed_agents"]
    }

    assert expected_case_ids <= seeded_case_ids


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
