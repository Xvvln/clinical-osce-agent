from app.services.agent_rag_context_service import retrieve_agent_context
from app.services.rag_knowledge_store import RagKnowledgeStore


def test_retrieve_agent_context_filters_visibility_agent_case_and_sanitizes_forbidden_terms(tmp_path) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    store.upsert_item(
        {
            "knowledge_id": "case:appendicitis_001:coach:pain_migration",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "coach_hint_note",
            "visibility": "pre_submit_safe",
            "allowed_agents": ["coach"],
            "source_id": "rubric_appendicitis_001",
            "title": "疼痛迁移提示",
            "text": "提示学生追问疼痛迁移，但不要说出急性阑尾炎。",
            "tags": ["疼痛迁移"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )
    store.upsert_item(
        {
            "knowledge_id": "case:appendicitis_001:secret:hidden_answer",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "internal_answer",
            "visibility": "secret_scoring_only",
            "allowed_agents": ["scoring"],
            "source_id": "",
            "title": "隐藏答案",
            "text": "隐藏答案：急性阑尾炎。",
            "tags": ["internal"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )
    store.upsert_item(
        {
            "knowledge_id": "case:appendicitis_001:reflection:pain_migration",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "reflection_note",
            "visibility": "pre_submit_safe",
            "allowed_agents": ["reflection"],
            "source_id": "",
            "title": "复盘提示",
            "text": "复盘疼痛迁移。",
            "tags": ["疼痛迁移"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )
    store.upsert_item(
        {
            "knowledge_id": "case:acs_001:coach:pain_migration",
            "scope": "case",
            "case_id": "acs_001",
            "content_kind": "coach_hint_note",
            "visibility": "pre_submit_safe",
            "allowed_agents": ["coach"],
            "source_id": "",
            "title": "胸痛迁移提示",
            "text": "胸痛病例提示。",
            "tags": ["疼痛迁移"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )

    results = retrieve_agent_context(
        agent_role="coach",
        case_ids=["appendicitis_001"],
        query_terms=["疼痛迁移"],
        allowed_visibilities={"pre_submit_safe"},
        forbidden_terms=["急性阑尾炎"],
        store=store,
    )

    assert [item["reference"] for item in results] == [
        "rag_knowledge:case:appendicitis_001:coach:pain_migration"
    ]
    assert results[0]["visibility"] == "pre_submit_safe"
    assert results[0]["allowed_agents"] == ["coach"]
    assert "急性阑尾炎" not in str(results[0])
    assert "标准诊断" in results[0]["snippet"]
