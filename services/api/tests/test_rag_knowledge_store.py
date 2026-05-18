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

    assert store.delete_item("case:appendicitis_001:teaching:history_migration")
    assert store.get_item("case:appendicitis_001:teaching:history_migration") is None
    assert not store.delete_item("case:appendicitis_001:teaching:history_migration")
