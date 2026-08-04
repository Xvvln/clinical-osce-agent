from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import main
from app.services import retrieval_index as retrieval_index_module
from app.services.agent_rag_context_service import retrieve_agent_context
from app.services.rag_document_ingestion_service import assess_rag_text
from app.services.rag_knowledge_store import RagKnowledgeStore


@pytest.fixture
def local_lexical_knowledge_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[RagKnowledgeStore]:
    store = RagKnowledgeStore(
        tmp_path / "rag_knowledge.sqlite3",
        seed_defaults=True,
    )
    monkeypatch.setattr(retrieval_index_module, "rag_knowledge_store", store)
    monkeypatch.setattr(
        retrieval_index_module,
        "_build_embedding_clients_from_environment",
        lambda: [],
    )
    monkeypatch.setattr(
        retrieval_index_module,
        "_build_dashscope_reranker",
        lambda: None,
    )
    retrieval_index_module._retrieval_documents.cache_clear()
    yield store
    retrieval_index_module._retrieval_documents.cache_clear()


@pytest.mark.parametrize(
    ("case_id", "student_words", "expected_knowledge_id", "main_diagnosis"),
    [
        (
            "appendicitis_001",
            "肚脐周围痛后来跑到右下腹，还恶心，我接着该问什么？",
            "case:appendicitis_001:coach:abdominal_pain_history_sequence",
            "急性阑尾炎",
        ),
        (
            "acs_001",
            "胸口像石头压着还往左肩窜，出了一身汗，病史还要问什么？",
            "case:acs_001:coach:chest_pain_history_sequence",
            "急性冠脉综合征",
        ),
        (
            "heart_failure_001",
            "走路憋气，平躺更喘，半夜会憋醒，脚也肿了，该怎么追问？",
            "case:heart_failure_001:coach:dyspnea_volume_history_sequence",
            "心力衰竭",
        ),
        (
            "hyperthyroid_001",
            "最近心慌手抖、怕热还变瘦，问诊要补哪些？",
            "case:hyperthyroid_001:coach:palpitation_weight_history_sequence",
            "甲状腺功能亢进",
        ),
        (
            "pneumonia_001",
            "发烧咳黄痰，一咳嗽右胸就疼，我还应该追问什么？",
            "case:pneumonia_001:coach:cough_fever_history_sequence",
            "社区获得性肺炎",
        ),
    ],
)
def test_student_colloquial_history_help_stays_in_case_and_does_not_reveal_answer(
    local_lexical_knowledge_store: RagKnowledgeStore,
    case_id: str,
    student_words: str,
    expected_knowledge_id: str,
    main_diagnosis: str,
) -> None:
    context = retrieve_agent_context(
        agent_role="coach",
        case_ids=[case_id],
        query_terms=[student_words],
        allowed_visibilities={"pre_submit_safe"},
        stage_scope=["history_taking"],
        limit=3,
        store=local_lexical_knowledge_store,
    )

    assert expected_knowledge_id in {item["knowledge_id"] for item in context}
    assert all(item["case_id"] in {"", case_id} for item in context)
    assert all(item["visibility"] == "pre_submit_safe" for item in context)
    assert all("history_taking" in item["stage_scope"] or "any" in item["stage_scope"] for item in context)
    assert main_diagnosis not in " ".join(
        f"{item['title']} {item['snippet']}"
        for item in context
    )


@pytest.mark.parametrize(
    ("case_id", "review_words", "expected_knowledge_id", "main_diagnosis"),
    [
        (
            "appendicitis_001",
            "复盘疼痛迁移、反跳痛、白细胞和超声怎样组成证据链",
            "case:appendicitis_001:reflection:appendicitis_reasoning_review",
            "急性阑尾炎",
        ),
        (
            "acs_001",
            "复盘压榨胸痛、放射、大汗、ST 段和肌钙蛋白",
            "case:acs_001:reflection:acs_reasoning_review",
            "急性冠脉综合征",
        ),
        (
            "heart_failure_001",
            "复盘夜间憋醒、水肿、颈静脉、BNP 和心脏超声",
            "case:heart_failure_001:reflection:heart_failure_reasoning_review",
            "心力衰竭",
        ),
        (
            "hyperthyroid_001",
            "复盘心慌手抖、多食消瘦、TSH 抑制和 FT4 升高",
            "case:hyperthyroid_001:reflection:hyperthyroid_reasoning_review",
            "甲状腺功能亢进",
        ),
        (
            "pneumonia_001",
            "复盘发热咳黄痰、局灶湿啰音和胸片浸润影",
            "case:pneumonia_001:reflection:pneumonia_reasoning_review",
            "社区获得性肺炎",
        ),
    ],
)
def test_submitted_case_reflection_can_use_diagnosis_content_but_not_other_cases(
    local_lexical_knowledge_store: RagKnowledgeStore,
    case_id: str,
    review_words: str,
    expected_knowledge_id: str,
    main_diagnosis: str,
) -> None:
    context = retrieve_agent_context(
        agent_role="reflection",
        case_ids=[case_id],
        query_terms=[review_words],
        allowed_visibilities={"post_submit_review"},
        stage_scope=["feedback"],
        limit=2,
        store=local_lexical_knowledge_store,
    )

    expected_item = next(
        item
        for item in context
        if item["knowledge_id"] == expected_knowledge_id
    )
    assert expected_item["case_id"] == case_id
    assert expected_item["visibility"] == "post_submit_review"
    assert main_diagnosis in f"{expected_item['title']} {expected_item['snippet']}"
    assert all(item["case_id"] == case_id for item in context)


def test_teacher_risky_note_is_invisible_until_moved_to_post_submit_and_approved(
    local_lexical_knowledge_store: RagKnowledgeStore,
) -> None:
    risky_text = "最终诊断为急性阑尾炎，建议立即给予抗生素治疗。本段只用于训练后复盘。"
    assessment = assess_rag_text(risky_text, section_title="诊断与治疗")
    knowledge_id = "case:appendicitis_001:document:teacher_risky_note"
    pending_item = local_lexical_knowledge_store.upsert_item(
        {
            "knowledge_id": knowledge_id,
            "scope": "case",
            "case_id": "appendicitis_001",
            "content_kind": "document_chunk",
            "visibility": "pre_submit_safe",
            "allowed_agents": ["coach"],
            "stage_scope": ["history_taking"],
            "source_id": "aafp_acute_abdominal_pain_2023",
            "title": "教师上传的诊断与治疗笔记",
            "text": risky_text,
            "tags": ["teacher_upload"],
            "risk_flags": assessment["risk_flags"],
            "quality_warnings": assessment["quality_warnings"],
            "review_status": "pending_review",
            "enabled": True,
        },
        updated_by="teacher@example.test",
    )
    retrieval_index_module._retrieval_documents.cache_clear()

    assert "diagnosis_answer_content" in pending_item["risk_flags"]
    assert "treatment_or_dose_content" in pending_item["risk_flags"]
    with pytest.raises(HTTPException) as approval_error:
        main._validate_rag_knowledge_approval(pending_item)
    assert getattr(approval_error.value, "status_code", None) == 409
    pre_submit_context = retrieve_agent_context(
        agent_role="coach",
        case_ids=["appendicitis_001"],
        query_terms=["最终诊断 抗生素"],
        allowed_visibilities={"pre_submit_safe"},
        stage_scope=["history_taking"],
        store=local_lexical_knowledge_store,
    )
    assert knowledge_id not in {item["knowledge_id"] for item in pre_submit_context}
    assert "急性阑尾炎" not in " ".join(item["snippet"] for item in pre_submit_context)
    assert "抗生素" not in " ".join(item["snippet"] for item in pre_submit_context)

    post_submit_item = local_lexical_knowledge_store.upsert_item(
        {
            **pending_item,
            "visibility": "post_submit_review",
            "allowed_agents": ["reflection"],
            "stage_scope": ["feedback"],
            "review_status": "pending_review",
        },
        updated_by="teacher@example.test",
    )
    main._validate_rag_knowledge_approval(post_submit_item)
    approved_item = local_lexical_knowledge_store.set_item_review_status(
        knowledge_id,
        review_status="approved",
        review_note="仅限提交后教学复盘",
        reviewed_by="reviewer@example.test",
    )
    retrieval_index_module._retrieval_documents.cache_clear()

    assert approved_item is not None
    approved_context = retrieve_agent_context(
        agent_role="reflection",
        case_ids=["appendicitis_001"],
        query_terms=["最终诊断 抗生素 训练后复盘"],
        allowed_visibilities={"post_submit_review"},
        stage_scope=["feedback"],
        store=local_lexical_knowledge_store,
    )
    assert knowledge_id in {item["knowledge_id"] for item in approved_context}
