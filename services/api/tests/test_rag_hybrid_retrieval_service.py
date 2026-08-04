from __future__ import annotations

from dataclasses import dataclass

from app.services.rag_hybrid_retrieval_service import (
    RankedReference,
    expand_retrieval_query,
    fuse_ranked_references,
    rank_lexical_documents,
)


@dataclass(frozen=True)
class FakeDocument:
    reference: str
    title: str
    snippet: str


def test_expand_retrieval_query_maps_colloquial_medical_terms() -> None:
    expanded = expand_retrieval_query("最近心慌、憋气，想做心电图")

    assert "心悸" in expanded
    assert "呼吸困难" in expanded
    assert "ecg" in expanded
    assert expanded.startswith("最近心慌、憋气，想做心电图")


def test_lexical_ranking_uses_expansion_for_colloquial_query() -> None:
    documents = [
        FakeDocument(
            reference="rag_knowledge:heart_failure",
            title="气短与水肿问诊",
            snippet="询问呼吸困难与下肢水肿的起病和演变。",
        ),
        FakeDocument(
            reference="rag_knowledge:abdominal_pain",
            title="腹痛问诊",
            snippet="询问疼痛迁移和恶心呕吐。",
        ),
    ]

    results = rank_lexical_documents("憋气又脚肿", documents, limit=2)

    assert results
    assert results[0].reference == "rag_knowledge:heart_failure"
    assert results[0].score > 0


def test_reciprocal_rank_fusion_records_both_retrieval_methods() -> None:
    results = fuse_ranked_references(
        vector_results=[
            RankedReference(reference="knowledge:a", score=0.99),
            RankedReference(reference="knowledge:b", score=0.9),
        ],
        lexical_results=[
            RankedReference(reference="knowledge:b", score=8.0),
            RankedReference(reference="knowledge:a", score=6.0),
        ],
        limit=2,
    )

    assert [result.reference for result in results] == ["knowledge:a", "knowledge:b"]
    assert results[0].retrieval_methods == ("vector", "lexical")
    assert results[0].vector_score == 0.99
    assert results[0].lexical_score == 6.0
    assert 0 < results[0].score <= 1
