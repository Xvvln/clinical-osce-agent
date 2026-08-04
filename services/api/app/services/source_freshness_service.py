from __future__ import annotations

from datetime import date, timedelta
from typing import Any

DEFAULT_SOURCE_REVIEW_INTERVAL_DAYS = 365
SOURCE_FRESHNESS_LABELS = {
    "current": "复核有效",
    "review_due": "到期待复核",
    "superseded": "已被新来源替代",
    "unverified": "未记录复核",
}


def enrich_source_freshness(
    source: dict[str, Any],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    evaluation_date = today or date.today()
    source_status = str(source.get("source_status") or "active").strip().lower()
    last_reviewed_at = _parse_iso_date(source.get("last_reviewed_at"))
    review_interval_days = _positive_int(
        source.get("review_interval_days"),
        default=DEFAULT_SOURCE_REVIEW_INTERVAL_DAYS,
    )
    explicit_review_due_at = _parse_iso_date(source.get("review_due_at"))
    review_due_at = explicit_review_due_at or (
        last_reviewed_at + timedelta(days=review_interval_days)
        if last_reviewed_at is not None
        else None
    )

    if source_status == "superseded":
        freshness_status = "superseded"
    elif last_reviewed_at is None or review_due_at is None:
        freshness_status = "unverified"
    elif review_due_at < evaluation_date:
        freshness_status = "review_due"
    else:
        freshness_status = "current"

    return {
        **source,
        "title": str(source.get("source_name") or source.get("source_id") or "").strip(),
        "source_type": str(source.get("data_type") or "").strip(),
        "source_status": source_status,
        "last_reviewed_at": last_reviewed_at.isoformat() if last_reviewed_at else "",
        "review_interval_days": review_interval_days,
        "review_due_at": review_due_at.isoformat() if review_due_at else "",
        "freshness_status": freshness_status,
        "freshness_label": SOURCE_FRESHNESS_LABELS[freshness_status],
        "selectable_for_new_knowledge": freshness_status == "current" and source_status == "active",
    }


def summarize_source_freshness(sources: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in SOURCE_FRESHNESS_LABELS}
    for source in sources:
        status = str(source.get("freshness_status") or "unverified")
        if status not in counts:
            status = "unverified"
        counts[status] += 1
    return {"total": len(sources), **counts}


def _parse_iso_date(value: object) -> date | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _positive_int(value: object, *, default: int) -> int:
    try:
        normalized = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return normalized if normalized > 0 else default
