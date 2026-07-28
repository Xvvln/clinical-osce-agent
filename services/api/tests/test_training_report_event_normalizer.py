from app.services.training_report_event_normalizer import (
    latest_report_generated_event,
    normalize_report_generated_events,
    unique_session_ids,
)


def _report_event(
    marker: str,
    *,
    report_id: str | None,
    created_at: str,
    event_id: int | None = None,
    report_revision: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"marker": marker}
    if report_id is not None:
        payload["report_id"] = report_id
    if report_revision is not None:
        payload["report_revision"] = report_revision
    event: dict[str, object] = {
        "event_type": "report_generated",
        "payload": payload,
        "created_at": created_at,
    }
    if event_id is not None:
        event["event_id"] = event_id
    return event


def test_report_event_normalizer_prefers_highest_revision_and_keeps_distinct_and_legacy_reports() -> None:
    events = [
        _report_event(
            "revision_one",
            report_id="stable_report",
            report_revision=1,
            created_at="2026-05-03T00:00:00+00:00",
        ),
        _report_event(
            "revision_two_older_event",
            report_id="stable_report",
            report_revision=2,
            created_at="2026-05-01T00:00:00+00:00",
            event_id=1,
        ),
        _report_event(
            "revision_two_latest_event",
            report_id="stable_report",
            report_revision=2,
            created_at="2026-05-01T00:00:00+00:00",
            event_id=2,
        ),
        _report_event(
            "unversioned_later",
            report_id="stable_report",
            created_at="2026-05-04T00:00:00+00:00",
        ),
        _report_event(
            "other_report",
            report_id="other_report",
            created_at="2026-05-02T00:00:00+00:00",
        ),
        _report_event(
            "legacy_report",
            report_id=None,
            created_at="2026-05-02T00:00:00+00:00",
        ),
    ]

    normalized = normalize_report_generated_events(events)

    assert [event["payload"]["marker"] for event in normalized] == [
        "revision_two_latest_event",
        "other_report",
        "legacy_report",
    ]


def test_report_event_normalizer_uses_stable_event_order_for_unversioned_snapshots() -> None:
    events = [
        _report_event(
            "earlier",
            report_id="stable_report",
            created_at="2026-05-01T00:00:00+00:00",
            event_id=99,
        ),
        _report_event(
            "later_lower_event_id",
            report_id="stable_report",
            created_at="2026-05-02T00:00:00+00:00",
            event_id=1,
        ),
        _report_event(
            "later_higher_event_id",
            report_id="stable_report",
            created_at="2026-05-02T00:00:00+00:00",
            event_id=2,
        ),
    ]

    normalized = normalize_report_generated_events(events)

    assert [event["payload"]["marker"] for event in normalized] == ["later_higher_event_id"]


def test_latest_report_event_uses_event_order_across_distinct_reports() -> None:
    events = [
        _report_event(
            "first_report",
            report_id="first_report",
            created_at="2026-05-01T00:00:00+00:00",
        ),
        _report_event(
            "latest_report",
            report_id="latest_report",
            created_at="2026-05-02T00:00:00+00:00",
        ),
    ]

    selected = latest_report_generated_event(events)

    assert selected is not None
    assert selected["payload"]["marker"] == "latest_report"


def test_unique_session_ids_preserves_first_seen_order() -> None:
    assert unique_session_ids(["session_two", "session_one", "session_two"]) == [
        "session_two",
        "session_one",
    ]
