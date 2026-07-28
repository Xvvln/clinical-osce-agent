from __future__ import annotations

from typing import Any

MAX_PROVIDER_PRIOR_MESSAGES = 8
MAX_PROVIDER_PRIOR_MESSAGE_CHARS = 4_000
PROVIDER_DIALOGUE_ROLES = frozenset({"student", "patient", "coach"})
PROVIDER_CONTEXT_ROLES = frozenset({*PROVIDER_DIALOGUE_ROLES, "tool"})


def bounded_provider_messages(
    messages: Any,
    *,
    max_messages: int = MAX_PROVIDER_PRIOR_MESSAGES,
    max_chars: int = MAX_PROVIDER_PRIOR_MESSAGE_CHARS,
    allowed_roles: frozenset[str] = PROVIDER_CONTEXT_ROLES,
) -> list[dict[str, str]]:
    if not isinstance(messages, list) or max_messages <= 0 or max_chars <= 0:
        return []

    valid_messages: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        content = str(message.get("content") or "")
        if role not in allowed_roles or not content.strip():
            continue
        valid_messages.append({"role": role, "content": content})

    remaining_chars = max_chars
    newest_first: list[dict[str, str]] = []
    for message in reversed(valid_messages[-max_messages:]):
        if remaining_chars <= 0:
            break
        content = message["content"][:remaining_chars]
        if not content:
            continue
        newest_first.append(
            {
                "role": message["role"],
                "content": content,
            }
        )
        remaining_chars -= len(content)
    return list(reversed(newest_first))
