from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

RRF_RANK_CONSTANT = 60
VECTOR_FUSION_WEIGHT = 0.65
LEXICAL_FUSION_WEIGHT = 0.35
MAX_EXPANDED_QUERY_CHARS = 600

MEDICAL_QUERY_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("憋气", "气短", "气促", "喘不上气", "呼吸困难"),
    ("心慌", "心悸", "心跳快"),
    ("浮肿", "水肿", "脚肿", "下肢肿胀"),
    ("发烧", "发热", "体温升高"),
    ("疼痛转移", "疼痛迁移", "迁移性疼痛"),
    ("反跳痛", "腹膜刺激征"),
    ("b超", "腹部超声", "超声检查"),
    ("心电图", "ecg", "ekg"),
    ("血常规", "cbc", "白细胞计数"),
    ("心梗", "心肌梗死", "急性冠脉综合征", "acs"),
    ("心衰", "心力衰竭"),
    ("甲亢", "甲状腺功能亢进"),
    ("肺部感染", "下呼吸道感染", "肺炎"),
    ("查体", "体格检查"),
    ("化验", "实验室检查", "辅助检查"),
    ("鉴别", "鉴别诊断", "排除依据"),
    ("复盘", "训练后反思", "反思总结"),
)


class SearchableDocument(Protocol):
    reference: str
    title: str
    snippet: str


@dataclass(frozen=True)
class RankedReference:
    reference: str
    score: float


@dataclass(frozen=True)
class FusedReference:
    reference: str
    score: float
    retrieval_methods: tuple[str, ...]
    vector_score: float | None = None
    lexical_score: float | None = None


def expand_retrieval_query(query: str) -> str:
    normalized_query = " ".join(str(query).split()).strip()
    if not normalized_query:
        return ""
    lowered_query = normalized_query.lower()
    expanded_terms: list[str] = [normalized_query]
    seen = {lowered_query}
    for synonym_group in MEDICAL_QUERY_SYNONYM_GROUPS:
        if not any(term.lower() in lowered_query for term in synonym_group):
            continue
        for term in synonym_group:
            normalized_term = term.strip()
            lowered_term = normalized_term.lower()
            if not normalized_term or lowered_term in seen:
                continue
            seen.add(lowered_term)
            expanded_terms.append(normalized_term)
    return " ".join(expanded_terms)[:MAX_EXPANDED_QUERY_CHARS].strip()


def rank_lexical_documents(
    query: str,
    documents: Sequence[SearchableDocument],
    *,
    limit: int,
) -> list[RankedReference]:
    if limit <= 0 or not documents:
        return []
    expanded_query = expand_retrieval_query(query)
    query_tokens = _tokenize(expanded_query)
    if not query_tokens:
        return []

    document_tokens = [
        _tokenize(f"{document.title} {document.title} {document.snippet}")
        for document in documents
    ]
    average_document_length = (
        sum(len(tokens) for tokens in document_tokens) / len(document_tokens)
        if document_tokens
        else 0.0
    )
    document_frequencies = Counter(
        token
        for tokens in document_tokens
        for token in set(tokens).intersection(query_tokens)
    )
    query_counter = Counter(query_tokens)
    compact_query = _compact_text(query)
    scored: list[RankedReference] = []
    for document, tokens in zip(documents, document_tokens):
        if not tokens:
            continue
        token_counts = Counter(tokens)
        score = 0.0
        for token, query_frequency in query_counter.items():
            term_frequency = token_counts.get(token, 0)
            if term_frequency <= 0:
                continue
            document_frequency = document_frequencies.get(token, 0)
            inverse_document_frequency = math.log(
                1 + (len(documents) - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            length_normalization = 1.2 * (
                0.25 + 0.75 * len(tokens) / max(average_document_length, 1.0)
            )
            score += (
                inverse_document_frequency
                * (term_frequency * 2.2)
                / (term_frequency + length_normalization)
                * min(query_frequency, 2)
            )
        compact_document = _compact_text(f"{document.title}{document.snippet}")
        if len(compact_query) >= 2 and compact_query in compact_document:
            score += 2.5
        if score > 0:
            scored.append(RankedReference(reference=document.reference, score=score))
    return sorted(scored, key=lambda item: (-item.score, item.reference))[:limit]


def fuse_ranked_references(
    *,
    vector_results: Sequence[RankedReference],
    lexical_results: Sequence[RankedReference],
    limit: int,
) -> list[FusedReference]:
    if limit <= 0:
        return []
    active_rankings = [
        ("vector", VECTOR_FUSION_WEIGHT, vector_results),
        ("lexical", LEXICAL_FUSION_WEIGHT, lexical_results),
    ]
    active_rankings = [entry for entry in active_rankings if entry[2]]
    if not active_rankings:
        return []

    available_weight = sum(weight for _, weight, _ in active_rankings)
    raw_scores: dict[str, float] = {}
    best_ranks: dict[str, int] = {}
    methods: dict[str, list[str]] = {}
    vector_scores = {item.reference: item.score for item in vector_results}
    lexical_scores = {item.reference: item.score for item in lexical_results}
    for method, weight, ranking in active_rankings:
        for rank, item in enumerate(ranking, start=1):
            raw_scores[item.reference] = raw_scores.get(item.reference, 0.0) + weight / (
                RRF_RANK_CONSTANT + rank
            )
            best_ranks[item.reference] = min(best_ranks.get(item.reference, rank), rank)
            methods.setdefault(item.reference, []).append(method)

    normalization = (RRF_RANK_CONSTANT + 1) / available_weight
    fused = [
        FusedReference(
            reference=reference,
            score=round(min(1.0, raw_score * normalization), 6),
            retrieval_methods=tuple(methods.get(reference, [])),
            vector_score=vector_scores.get(reference),
            lexical_score=lexical_scores.get(reference),
        )
        for reference, raw_score in raw_scores.items()
    ]
    return sorted(
        fused,
        key=lambda item: (-item.score, best_ranks.get(item.reference, 10_000), item.reference),
    )[:limit]


def _tokenize(text: str) -> list[str]:
    normalized = str(text).lower()
    tokens = re.findall(r"[a-z0-9_]+", normalized)
    for chinese_sequence in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", normalized):
        if len(chinese_sequence) <= 12:
            tokens.append(chinese_sequence)
        for size in (2, 3):
            if len(chinese_sequence) < size:
                continue
            tokens.extend(
                chinese_sequence[index : index + size]
                for index in range(len(chinese_sequence) - size + 1)
            )
    return tokens


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text)).lower()
