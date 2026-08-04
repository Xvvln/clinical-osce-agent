from app.services import agent_rag_context_service as agent_rag_context_module
from app.services.agent_rag_context_service import retrieve_agent_context
from app.services.rag_knowledge_store import RagKnowledgeStore
from app.services.retrieval_index import RetrievalDocument


def test_retrieve_agent_context_filters_visibility_agent_case_and_sanitizes_forbidden_terms(tmp_path, monkeypatch) -> None:
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

    def fake_search_retrieval_documents(
        query: str,
        limit: int,
        *,
        allowed_references: set[str],
    ) -> list[RetrievalDocument]:
        assert allowed_references == {
            "rag_knowledge:case:appendicitis_001:coach:pain_migration"
        }
        return [
            RetrievalDocument(
                reference="rag_knowledge:case:appendicitis_001:coach:pain_migration",
                source_type="rag_knowledge",
                title="vector hit",
                snippet="vector hit",
                score=0.99,
            ),
            RetrievalDocument(
                reference="rag_knowledge:case:appendicitis_001:reflection:pain_migration",
                source_type="rag_knowledge",
                title="filtered by agent",
                snippet="filtered by agent",
                score=0.98,
            ),
            RetrievalDocument(
                reference="rag_knowledge:case:acs_001:coach:pain_migration",
                source_type="rag_knowledge",
                title="filtered by case",
                snippet="filtered by case",
                score=0.97,
            ),
        ]

    monkeypatch.setattr(
        agent_rag_context_module,
        "search_retrieval_documents",
        fake_search_retrieval_documents,
        raising=False,
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
    assert results[0]["stage_scope"] == ["any"]
    assert "急性阑尾炎" not in str(results[0])
    assert "标准诊断" in results[0]["snippet"]


def test_retrieve_agent_context_excludes_pending_and_rejected_items_before_search(tmp_path, monkeypatch) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    for review_status in ["pending_review", "rejected"]:
        store.upsert_item(
            {
                "knowledge_id": f"case:appendicitis_001:coach:{review_status}",
                "scope": "case",
                "case_id": "appendicitis_001",
                "content_kind": "coach_hint_note",
                "visibility": "pre_submit_safe",
                "allowed_agents": ["coach"],
                "source_id": "",
                "title": review_status,
                "text": "未审核内容不应进入 Coach 上下文。",
                "tags": ["review"],
                "review_status": review_status,
            },
            updated_by="admin@example.test",
        )

    def fail_search(*args, **kwargs):
        raise AssertionError("search must not run without approved eligible references")

    monkeypatch.setattr(agent_rag_context_module, "search_retrieval_documents", fail_search)

    assert (
        retrieve_agent_context(
            agent_role="coach",
            case_ids=["appendicitis_001"],
            query_terms=["未审核内容"],
            allowed_visibilities={"pre_submit_safe"},
            store=store,
        )
        == []
    )


def test_retrieve_agent_context_filters_by_training_stage_and_normalizes_aliases(
    tmp_path,
    monkeypatch,
) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    for knowledge_id, stage_scope, title in [
        ("case:appendicitis_001:coach:history", ["history_taking"], "问诊阶段资料"),
        ("case:appendicitis_001:coach:exam", ["physical_exam"], "查体阶段资料"),
        ("case:appendicitis_001:coach:test", ["auxiliary_test"], "检查阶段资料"),
        ("case:appendicitis_001:coach:any", ["any"], "全阶段安全资料"),
    ]:
        store.upsert_item(
            {
                "knowledge_id": knowledge_id,
                "scope": "case",
                "case_id": "appendicitis_001",
                "content_kind": "coach_hint_note",
                "visibility": "pre_submit_safe",
                "allowed_agents": ["coach"],
                "stage_scope": stage_scope,
                "source_id": "",
                "title": title,
                "text": f"{title}正文。",
                "tags": ["stage_test"],
                "version": 1,
            },
            updated_by="admin@example.test",
        )

    vector_hits = [
        RetrievalDocument(
            reference=f"rag_knowledge:{knowledge_id}",
            source_type="rag_knowledge",
            title=title,
            snippet=title,
            score=1.0 - index * 0.01,
        )
        for index, (knowledge_id, _, title) in enumerate(
            [
                ("case:appendicitis_001:coach:history", [], "问诊阶段资料"),
                ("case:appendicitis_001:coach:exam", [], "查体阶段资料"),
                ("case:appendicitis_001:coach:test", [], "检查阶段资料"),
                ("case:appendicitis_001:coach:any", [], "全阶段安全资料"),
            ]
        )
    ]
    captured_queries: list[str] = []

    def fake_search(
        query: str,
        limit: int,
        *,
        allowed_references: set[str],
    ) -> list[RetrievalDocument]:
        captured_queries.append(query)
        return [
            item
            for item in vector_hits
            if item.reference in allowed_references
        ][:limit]

    monkeypatch.setattr(agent_rag_context_module, "search_retrieval_documents", fake_search)

    history_results = retrieve_agent_context(
        agent_role="coach",
        case_ids=["appendicitis_001"],
        query_terms=["腹痛训练"],
        allowed_visibilities={"pre_submit_safe"},
        stage_scope=["history_taking"],
        limit=4,
        store=store,
    )
    test_results = retrieve_agent_context(
        agent_role="coach",
        case_ids=["appendicitis_001"],
        query_terms=["腹痛训练"],
        allowed_visibilities={"pre_submit_safe"},
        stage_scope=["auxiliary_testing"],
        limit=4,
        store=store,
    )

    assert [item["knowledge_id"] for item in history_results] == [
        "case:appendicitis_001:coach:history",
        "case:appendicitis_001:coach:any",
    ]
    assert [item["knowledge_id"] for item in test_results] == [
        "case:appendicitis_001:coach:test",
        "case:appendicitis_001:coach:any",
    ]
    assert "history_taking" in captured_queries[0]
    assert "auxiliary_test" in captured_queries[1]


def test_retrieve_agent_context_does_not_keyword_scan_when_vector_retrieval_misses(
    tmp_path,
    monkeypatch,
) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    store.upsert_item(
        {
            "knowledge_id": "case:appendicitis_001:coach:keyword_only",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "coach_hint_note",
            "visibility": "pre_submit_safe",
            "allowed_agents": ["coach"],
            "source_id": "rubric_appendicitis_001",
            "title": "关键词命中但不应返回",
            "text": "疼痛迁移训练应追问是否从上腹或脐周转移到右下腹。",
            "tags": ["疼痛迁移训练"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )

    monkeypatch.setattr(
        agent_rag_context_module,
        "search_retrieval_documents",
        lambda query, limit, *, allowed_references: [],
        raising=False,
    )

    results = retrieve_agent_context(
        agent_role="coach",
        case_ids=["appendicitis_001"],
        query_terms=["疼痛迁移训练"],
        allowed_visibilities={"pre_submit_safe"},
        store=store,
    )

    assert results == []


def test_retrieve_agent_context_uses_vector_retrieval_results_without_keyword_overlap(
    tmp_path,
    monkeypatch,
) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    store.upsert_item(
        {
            "knowledge_id": "case:appendicitis_001:coach:sequence_bridge",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "coach_hint_note",
            "visibility": "pre_submit_safe",
            "allowed_agents": ["coach"],
            "source_id": "rubric_appendicitis_001",
            "title": "腹痛问诊顺序提示",
            "text": "先补齐病史结构，再进入体格检查。",
            "tags": ["workflow"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )
    captured_queries: list[str] = []

    def fake_search_retrieval_documents(
        query: str,
        limit: int,
        *,
        allowed_references: set[str],
    ) -> list[RetrievalDocument]:
        captured_queries.append(query)
        assert allowed_references == {
            "rag_knowledge:case:appendicitis_001:coach:sequence_bridge"
        }
        return [
            RetrievalDocument(
                reference="rag_knowledge:case:appendicitis_001:coach:sequence_bridge",
                source_type="rag_knowledge",
                title="semantic hit",
                snippet="semantic hit",
                score=0.98,
            )
        ]

    monkeypatch.setattr(
        agent_rag_context_module,
        "search_retrieval_documents",
        fake_search_retrieval_documents,
        raising=False,
    )

    results = retrieve_agent_context(
        agent_role="coach",
        case_ids=["appendicitis_001"],
        query_terms=["clinical sequencing without lexical overlap"],
        allowed_visibilities={"pre_submit_safe"},
        store=store,
    )

    assert captured_queries == ["clinical sequencing without lexical overlap"]
    assert [item["reference"] for item in results] == [
        "rag_knowledge:case:appendicitis_001:coach:sequence_bridge"
    ]


def test_retrieve_agent_context_keeps_teacher_document_when_non_rag_hits_are_ahead(
    tmp_path,
    monkeypatch,
) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3")
    store.upsert_item(
        {
            "knowledge_id": "kbdoc:appendicitis_001:teacher_note:chunk:0000",
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "document_chunk",
            "visibility": "pre_submit_safe",
            "allowed_agents": ["coach"],
            "source_id": "teacher_uploaded_note",
            "title": "腹痛问诊教学补充",
            "text": "腹痛问诊应先厘清起病部位、转移过程、伴随恶心发热以及腹泻等阴性信息。",
            "tags": ["teacher_note", "abdominal_pain"],
            "version": 1,
        },
        updated_by="admin@example.test",
    )
    captured_limits: list[int] = []
    captured_allowed_references: list[set[str]] = []

    def fake_search_retrieval_documents(
        query: str,
        limit: int,
        *,
        allowed_references: set[str],
    ) -> list[RetrievalDocument]:
        captured_limits.append(limit)
        captured_allowed_references.append(allowed_references)
        all_hits = [
            RetrievalDocument(
                reference=f"rubric:appendicitis_001_rubric.item.ht_{index}",
                source_type="rubric",
                title=f"rubric hit {index}",
                snippet="rubric content",
                score=1.0 - index * 0.01,
            )
            for index in range(30)
        ]
        all_hits.append(
            RetrievalDocument(
                reference="rag_knowledge:kbdoc:appendicitis_001:teacher_note:chunk:0000",
                source_type="rag_knowledge",
                title="teacher note",
                snippet="semantic teacher note",
                score=0.7,
            )
        )
        return [
            item
            for item in all_hits
            if item.reference in allowed_references
        ][:limit]

    monkeypatch.setattr(
        agent_rag_context_module,
        "search_retrieval_documents",
        fake_search_retrieval_documents,
        raising=False,
    )

    results = retrieve_agent_context(
        agent_role="coach",
        case_ids=["appendicitis_001"],
        query_terms=["腹痛问诊 起病 转移 恶心 发热"],
        allowed_visibilities={"pre_submit_safe"},
        store=store,
    )

    assert captured_limits == [3]
    assert captured_allowed_references == [
        {"rag_knowledge:kbdoc:appendicitis_001:teacher_note:chunk:0000"}
    ]
    assert [item["reference"] for item in results] == [
        "rag_knowledge:kbdoc:appendicitis_001:teacher_note:chunk:0000"
    ]


def test_retrieve_agent_context_reads_seeded_public_knowledge_without_revealing_diagnosis(tmp_path, monkeypatch) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3", seed_defaults=True)
    monkeypatch.setattr(
        agent_rag_context_module,
        "search_retrieval_documents",
        lambda query, limit, *, allowed_references: [
            RetrievalDocument(
                reference="rag_knowledge:case:appendicitis_001:coach:abdominal_pain_history_sequence",
                source_type="rag_knowledge",
                title="vector hit",
                snippet="vector hit",
                score=0.99,
            )
        ],
        raising=False,
    )

    results = retrieve_agent_context(
        agent_role="coach",
        case_ids=["appendicitis_001"],
        query_terms=["腹痛问诊 起病 部位 迁移 伴随症状"],
        allowed_visibilities={"pre_submit_safe"},
        forbidden_terms=["急性阑尾炎"],
        store=store,
    )

    assert results
    assert results[0]["reference"] == (
        "rag_knowledge:case:appendicitis_001:coach:abdominal_pain_history_sequence"
    )
    assert results[0]["source_id"] == "aafp_acute_abdominal_pain_2023"
    assert "急性阑尾炎" not in str(results)


def test_retrieve_agent_context_reads_seeded_recommended_case_knowledge(tmp_path, monkeypatch) -> None:
    store = RagKnowledgeStore(tmp_path / "rag_knowledge.sqlite3", seed_defaults=True)
    monkeypatch.setattr(
        agent_rag_context_module,
        "search_retrieval_documents",
        lambda query, limit, *, allowed_references: [
            RetrievalDocument(
                reference="rag_knowledge:case:acs_001:coach:chest_pain_history_sequence",
                source_type="rag_knowledge",
                title="vector hit",
                snippet="vector hit",
                score=0.99,
            )
        ],
        raising=False,
    )

    results = retrieve_agent_context(
        agent_role="coach",
        case_ids=["acs_001"],
        query_terms=["胸痛 放射 大汗 呼吸困难 心电图"],
        allowed_visibilities={"pre_submit_safe"},
        forbidden_terms=["急性冠脉综合征"],
        store=store,
    )

    assert results
    assert results[0]["reference"] == "rag_knowledge:case:acs_001:coach:chest_pain_history_sequence"
    assert "胸痛" in results[0]["title"]
    assert "急性冠脉综合征" not in str(results)
