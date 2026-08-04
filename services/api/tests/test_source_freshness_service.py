from __future__ import annotations

from datetime import date

from app.services.source_freshness_service import (
    enrich_source_freshness,
    summarize_source_freshness,
)


def test_source_freshness_computes_review_due_date_and_readable_fields() -> None:
    source = enrich_source_freshness(
        {
            "source_id": "official_guideline",
            "source_name": "Official Guideline",
            "data_type": "clinical_guideline_reference",
            "last_reviewed_at": "2026-08-04",
            "review_interval_days": 365,
            "source_status": "active",
        },
        today=date(2026, 8, 4),
    )

    assert source["title"] == "Official Guideline"
    assert source["source_type"] == "clinical_guideline_reference"
    assert source["review_due_at"] == "2027-08-04"
    assert source["freshness_status"] == "current"
    assert source["freshness_label"] == "复核有效"
    assert source["selectable_for_new_knowledge"] is True


def test_source_freshness_marks_expired_unverified_and_superseded_sources() -> None:
    evaluation_date = date(2026, 8, 4)

    expired = enrich_source_freshness(
        {"source_id": "expired", "last_reviewed_at": "2024-01-01", "review_interval_days": 365},
        today=evaluation_date,
    )
    unverified = enrich_source_freshness({"source_id": "unverified"}, today=evaluation_date)
    superseded = enrich_source_freshness(
        {
            "source_id": "old",
            "source_status": "superseded",
            "superseded_by": "new",
            "last_reviewed_at": "2026-08-04",
        },
        today=evaluation_date,
    )

    assert expired["freshness_status"] == "review_due"
    assert expired["selectable_for_new_knowledge"] is False
    assert unverified["freshness_status"] == "unverified"
    assert unverified["review_due_at"] == ""
    assert superseded["freshness_status"] == "superseded"
    assert superseded["selectable_for_new_knowledge"] is False


def test_source_freshness_summary_counts_every_status() -> None:
    summary = summarize_source_freshness(
        [
            {"freshness_status": "current"},
            {"freshness_status": "current"},
            {"freshness_status": "review_due"},
            {"freshness_status": "superseded"},
            {"freshness_status": "unverified"},
        ]
    )

    assert summary == {
        "total": 5,
        "current": 2,
        "review_due": 1,
        "superseded": 1,
        "unverified": 1,
    }
