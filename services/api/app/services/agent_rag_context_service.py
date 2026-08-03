from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.rag_knowledge_store import (
    RagKnowledgeStore,
    normalize_rag_stage_scope,
    rag_knowledge_store,
)
from app.services.retrieval_index import search_retrieval_documents

MAX_AGENT_KNOWLEDGE_SNIPPET_CHARS = 1_200


def retrieve_agent_context(
    *,
    agent_role: str,
    case_ids: list[str],
    query_terms: list[str],
    allowed_visibilities: set[str],
    stage_scope: list[str] | None = None,
    forbidden_terms: list[str] | None = None,
    limit: int = 3,
    store: RagKnowledgeStore | None = None,
) -> list[dict[str, Any]]:
    knowledge_store = store or rag_knowledge_store
    database_path = getattr(knowledge_store, "database_path", None)
    if (
        isinstance(database_path, Path)
        and not database_path.exists()
        and not getattr(knowledge_store, "seed_defaults", False)
    ):
        return []

    normalized_case_ids = {str(case_id).strip() for case_id in case_ids if str(case_id).strip()}
    requested_stage_scope = (
        normalize_rag_stage_scope(stage_scope)
        if stage_scope
        else []
    )
    query_text = " ".join(
        [
            *[str(term).strip() for term in query_terms if str(term).strip()],
            *[stage for stage in requested_stage_scope if stage != "any"],
        ]
    )
    selected_items: list[dict[str, Any]] = []
    if query_text:
        retrieval_limit = max(limit * 20, 40)
        for result in search_retrieval_documents(query_text, limit=retrieval_limit):
            if result.source_type != "rag_knowledge" or not result.reference.startswith("rag_knowledge:"):
                continue
            knowledge_id = result.reference.removeprefix("rag_knowledge:")
            item = knowledge_store.get_item(knowledge_id)
            if item is None:
                continue
            if not _agent_can_read_knowledge_item(
                item,
                agent_role=agent_role,
                case_ids=normalized_case_ids,
                allowed_visibilities=allowed_visibilities,
                requested_stage_scope=set(requested_stage_scope),
            ):
                continue
            selected_items.append(item)
            if len(selected_items) >= limit:
                break

    return [
        _serialize_agent_knowledge_item(item, forbidden_terms=forbidden_terms or [])
        for item in selected_items[:limit]
    ]


def _agent_can_read_knowledge_item(
    item: dict[str, Any],
    *,
    agent_role: str,
    case_ids: set[str],
    allowed_visibilities: set[str],
    requested_stage_scope: set[str],
) -> bool:
    if item.get("enabled") is False:
        return False
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
    item_stage_scope = set(normalize_rag_stage_scope(item.get("stage_scope")))
    if (
        requested_stage_scope
        and "any" not in requested_stage_scope
        and "any" not in item_stage_scope
        and not requested_stage_scope.intersection(item_stage_scope)
    ):
        return False
    return True


def _serialize_agent_knowledge_item(item: dict[str, Any], *, forbidden_terms: list[str]) -> dict[str, Any]:
    knowledge_id = str(item.get("knowledge_id", "")).strip()
    snippet = _sanitize_knowledge_context_text(
        str(item.get("text", "")).strip(),
        forbidden_terms,
    )
    return {
        "reference": f"rag_knowledge:{knowledge_id}",
        "knowledge_id": knowledge_id,
        "title": _sanitize_knowledge_context_text(str(item.get("title", "")).strip(), forbidden_terms),
        "snippet": snippet[:MAX_AGENT_KNOWLEDGE_SNIPPET_CHARS],
        "source_id": str(item.get("source_id", "")).strip(),
        "case_id": str(item.get("case_id", "")).strip(),
        "visibility": str(item.get("visibility", "")).strip(),
        "allowed_agents": [str(agent) for agent in item.get("allowed_agents", []) if str(agent)],
        "stage_scope": normalize_rag_stage_scope(item.get("stage_scope")),
    }


def _sanitize_knowledge_context_text(text: str, forbidden_terms: list[str]) -> str:
    sanitized = text
    for term in forbidden_terms:
        if term:
            sanitized = sanitized.replace(term, "标准诊断")
    return sanitized
