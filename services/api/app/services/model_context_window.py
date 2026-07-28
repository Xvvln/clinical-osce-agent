from __future__ import annotations

from typing import Any

MAX_PROVIDER_PRIOR_MESSAGES = 8
MAX_PROVIDER_PRIOR_MESSAGE_BYTES = 4_000
# Backward-compatible alias for callers that imported the old, inaccurately
# named constant. The budget has always applied to message content; it is now
# enforced as UTF-8 bytes instead of Python code points.
MAX_PROVIDER_PRIOR_MESSAGE_CHARS = MAX_PROVIDER_PRIOR_MESSAGE_BYTES
PROVIDER_DIALOGUE_ROLES = frozenset({"student", "patient", "coach"})
PROVIDER_CONTEXT_ROLES = frozenset({*PROVIDER_DIALOGUE_ROLES, "tool"})


def bounded_provider_messages(
    messages: Any,
    *,
    max_messages: int = MAX_PROVIDER_PRIOR_MESSAGES,
    max_chars: int | None = None,
    allowed_roles: frozenset[str] = PROVIDER_CONTEXT_ROLES,
    max_bytes: int | None = None,
) -> list[dict[str, str]]:
    """Keep the newest allowed messages within a UTF-8 content-byte budget.

    The budget covers the sum of encoded ``content`` values. JSON field names,
    role values, and envelope overhead are bounded separately by provider
    payload builders.
    """
    # ``max_chars`` remains a supported keyword for compatibility, but its
    # value is interpreted as the content byte budget just like ``max_bytes``.
    content_byte_budget = (
        max_bytes
        if max_bytes is not None
        else (
            max_chars
            if max_chars is not None
            else MAX_PROVIDER_PRIOR_MESSAGE_BYTES
        )
    )
    if (
        not isinstance(messages, list)
        or max_messages <= 0
        or content_byte_budget <= 0
    ):
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

    remaining_bytes = content_byte_budget
    newest_first: list[dict[str, str]] = []
    for message in reversed(valid_messages[-max_messages:]):
        if remaining_bytes <= 0:
            break
        content = _truncate_utf8_prefix(
            message["content"],
            max_bytes=remaining_bytes,
        )
        if not content:
            break
        newest_first.append(
            {
                "role": message["role"],
                "content": content,
            }
        )
        remaining_bytes -= len(content.encode("utf-8"))
    return list(reversed(newest_first))


def _truncate_utf8_prefix(value: str, *, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")
