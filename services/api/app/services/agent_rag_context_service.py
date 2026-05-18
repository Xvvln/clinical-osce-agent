from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.services.rag_knowledge_store import RagKnowledgeStore, rag_knowledge_store


def retrieve_agent_context(
    *,
    agent_role: str,
    case_ids: list[str],
    query_terms: list[str],
    allowed_visibilities: set[str],
    forbidden_terms: list[str] | None = None,
    limit: int = 3,
    store: RagKnowledgeStore | None = None,
) -> list[dict[str, Any]]:
    knowledge_store = store or rag_knowledge_store
    database_path = getattr(knowledge_store, "database_path", None)
    if isinstance(database_path, Path) and not database_path.exists():
        return []

    normalized_case_ids = {str(case_id).strip() for case_id in case_ids if str(case_id).strip()}
    terms = _rag_terms(query_terms)
    scored_items: list[tuple[int, str, dict[str, Any]]] = []
    for item in knowledge_store.list_items():
        if not _agent_can_read_knowledge_item(
            item,
            agent_role=agent_role,
            case_ids=normalized_case_ids,
            allowed_visibilities=allowed_visibilities,
        ):
            continue
        score = _score_knowledge_item(item, terms)
        if score <= 0:
            continue
        knowledge_id = str(item.get("knowledge_id", "")).strip()
        scored_items.append((score, knowledge_id, item))

    return [
        _serialize_agent_knowledge_item(item, forbidden_terms=forbidden_terms or [])
        for _, _, item in sorted(scored_items, key=lambda entry: (-entry[0], entry[1]))[:limit]
    ]


def _agent_can_read_knowledge_item(
    item: dict[str, Any],
    *,
    agent_role: str,
    case_ids: set[str],
    allowed_visibilities: set[str],
) -> bool:
    visibility = str(item.get("visibility", "")).strip()
    if visibility not in allowed_visibilities:
        return False
    allowed_agents = [str(agent).strip() for agent in item.get("allowed_agents", []) if str(agent).strip()]
    if allowed_agents and agent_role not in allowed_agents:
        return False
    item_case_id = str(item.get("case_id", "")).strip()
    if item_case_id and item_case_id not in case_ids:
        return False
    if str(item.get("scope", "")).strip() == "case" and not item_case_id:
        return False
    return True


def _score_knowledge_item(item: dict[str, Any], terms: list[str]) -> int:
    haystack = " ".join(
        [
            str(item.get("knowledge_id", "")),
            str(item.get("title", "")),
            str(item.get("text", "")),
            " ".join(str(tag) for tag in item.get("tags", []) if str(tag)),
        ]
    ).lower()
    return sum(1 for term in terms if term.lower() in haystack)


def _rag_terms(query_terms: list[str]) -> list[str]:
    terms: set[str] = set()
    for raw_term in query_terms:
        normalized = str(raw_term).strip()
        if not normalized:
            continue
        terms.add(normalized)
        terms.update(token for token in re.split(r"[\s,，。；;:：、()（）]+", normalized) if token)
        terms.update(_cjk_ngrams(normalized, min_size=2, max_size=6))
    return sorted(terms, key=lambda term: (-len(term), term))


def _cjk_ngrams(text: str, *, min_size: int, max_size: int) -> set[str]:
    compact_text = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9_]+", "", text)
    if len(compact_text) < min_size:
        return set()
    return {
        compact_text[start : start + size]
        for size in range(min_size, min(max_size, len(compact_text)) + 1)
        for start in range(0, len(compact_text) - size + 1)
    }


def _serialize_agent_knowledge_item(item: dict[str, Any], *, forbidden_terms: list[str]) -> dict[str, Any]:
    knowledge_id = str(item.get("knowledge_id", "")).strip()
    return {
        "reference": f"rag_knowledge:{knowledge_id}",
        "knowledge_id": knowledge_id,
        "title": _sanitize_knowledge_context_text(str(item.get("title", "")).strip(), forbidden_terms),
        "snippet": _sanitize_knowledge_context_text(str(item.get("text", "")).strip(), forbidden_terms),
        "source_id": str(item.get("source_id", "")).strip(),
        "case_id": str(item.get("case_id", "")).strip(),
        "visibility": str(item.get("visibility", "")).strip(),
        "allowed_agents": [str(agent) for agent in item.get("allowed_agents", []) if str(agent)],
    }


def _sanitize_knowledge_context_text(text: str, forbidden_terms: list[str]) -> str:
    sanitized = text
    for term in forbidden_terms:
        if term:
            sanitized = sanitized.replace(term, "标准诊断")
    return sanitized
