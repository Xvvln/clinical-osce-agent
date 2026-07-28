from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


REPORT_SNAPSHOT_EVENT_TYPES = frozenset({"report_generated", "report_enriched"})
REPORT_LIFECYCLE_EVENT_TYPES = frozenset(
    {*REPORT_SNAPSHOT_EVENT_TYPES, "report_enrichment_failed"}
)


def unique_session_ids(session_ids: Sequence[str]) -> list[str]:
    """Return session ids once, preserving the caller's first-seen order."""

    return list(dict.fromkeys(session_ids))


def normalize_report_events_by_session(
    session_ids: Sequence[str],
    events_by_session: Mapping[str, Sequence[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Collapse repeated snapshots of the same stable report id per session."""

    return {
        session_id: normalize_report_generated_events(events_by_session.get(session_id, ()))
        for session_id in session_ids
    }


def normalize_report_generated_events(
    events: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep one successful report snapshot per report id without reordering.

    A declared report revision wins over an unversioned snapshot, and the highest
    revision wins. Equal or absent revisions fall back to the stable event order.
    Legacy events without a report id are retained because they cannot be safely
    identified as duplicate snapshots. Failed enrichment events remain lifecycle
    events and never replace the last successful report snapshot.
    """

    selected_index_by_report_id: dict[str, int] = {}
    selected_key_by_report_id: dict[str, tuple[Any, ...]] = {}
    for index, event in enumerate(events):
        report_id = _stable_report_id(event)
        if report_id is None:
            continue
        selection_key = _report_selection_key(event, index)
        if (
            report_id not in selected_key_by_report_id
            or selection_key > selected_key_by_report_id[report_id]
        ):
            selected_index_by_report_id[report_id] = index
            selected_key_by_report_id[report_id] = selection_key

    normalized_events: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        report_id = _stable_report_id(event)
        if report_id is None or selected_index_by_report_id[report_id] == index:
            normalized_events.append(event)
    return normalized_events


def latest_report_generated_event(
    events: Sequence[dict[str, Any]],
) -> dict[str, Any] | None:
    """Select the chronologically latest successful normalized report snapshot."""

    candidates = [
        (event, index)
        for index, event in enumerate(events)
        if is_report_snapshot_event(event)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: _event_order_key(item[0], item[1]))[0]


def _stable_report_id(event: Mapping[str, Any]) -> str | None:
    if not is_report_snapshot_event(event):
        return None
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return None
    report_id = str(payload.get("report_id") or "").strip()
    return report_id or None


def is_report_snapshot_event(event: Mapping[str, Any]) -> bool:
    return event.get("event_type") in REPORT_SNAPSHOT_EVENT_TYPES


def report_snapshot_payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the complete report snapshot while keeping legacy events readable."""

    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return {}
    report = payload.get("report")
    return report if isinstance(report, Mapping) else payload


def _report_selection_key(event: Mapping[str, Any], input_index: int) -> tuple[Any, ...]:
    revision = _report_revision(event)
    return (
        revision is not None,
        revision if revision is not None else Decimal(0),
        *_event_order_key(event, input_index),
    )


def _report_revision(event: Mapping[str, Any]) -> Decimal | None:
    payload = event.get("payload")
    raw_revision = payload.get("report_revision") if isinstance(payload, Mapping) else None
    if raw_revision is None:
        raw_revision = event.get("report_revision")
    if raw_revision is None or isinstance(raw_revision, bool):
        return None
    try:
        revision = Decimal(str(raw_revision))
    except (InvalidOperation, ValueError):
        return None
    return revision if revision.is_finite() else None


def _event_order_key(event: Mapping[str, Any], input_index: int) -> tuple[Any, ...]:
    return (
        _created_at_key(event.get("created_at")),
        _event_id_key(event.get("event_id")),
        input_index,
    )


def _created_at_key(value: Any) -> tuple[int, float, str]:
    if isinstance(value, datetime):
        parsed = value
        raw_value = value.isoformat()
    else:
        raw_value = str(value or "").strip()
        if not raw_value:
            return (0, 0.0, "")
        try:
            parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except ValueError:
            return (1, 0.0, raw_value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (2, parsed.timestamp(), raw_value)


def _event_id_key(value: Any) -> tuple[int, int, str]:
    if value is None or isinstance(value, bool):
        return (0, 0, "")
    if isinstance(value, int):
        return (2, value, "")
    raw_value = str(value).strip()
    if not raw_value:
        return (0, 0, "")
    try:
        return (2, int(raw_value), "")
    except ValueError:
        return (1, 0, raw_value)
