from app.services.report_score_metrics import (
    aggregate_score_metrics,
    dimension_score_metrics,
    score_group_metric,
)


def test_score_group_aggregation_normalizes_each_report_before_averaging() -> None:
    appendicitis_metric = score_group_metric(
        {
            "score_groups": {
                "clinical_osce": {"score": 35, "max_score": 70},
            }
        },
        "clinical_osce",
    )
    acs_metric = score_group_metric(
        {
            "score_groups": {
                "clinical_osce": {"score": 60, "max_score": 100},
            }
        },
        "clinical_osce",
    )

    assert appendicitis_metric is not None
    assert acs_metric is not None
    assert aggregate_score_metrics([appendicitis_metric, acs_metric]) == {
        "sample_count": 2,
        "average_score": 47.5,
        "average_max_score": 85,
        "average_percentage": 55,
    }


def test_zero_max_score_means_not_applicable_instead_of_zero_performance() -> None:
    metric = score_group_metric(
        {
            "score_groups": {
                "humanistic_communication": {"score": 0, "max_score": 0},
            }
        },
        "humanistic_communication",
    )

    assert metric is None
    assert aggregate_score_metrics([]) == {
        "sample_count": 0,
        "average_score": 0,
        "average_max_score": 0,
        "average_percentage": None,
    }


def test_dimension_metrics_use_each_rubric_dimension_maximum() -> None:
    metrics = dimension_score_metrics(
        {
            "dimension_scores": {
                "history_taking": 9,
                "relationship_building": 5,
            },
            "rubric_scores": {
                "history_one": {
                    "dimension_id": "history_taking",
                    "score": 4,
                    "max_score": 8,
                },
                "history_two": {
                    "dimension_id": "history_taking",
                    "score": 5,
                    "max_score": 10,
                },
                "relationship": {
                    "dimension_id": "relationship_building",
                    "score": 5,
                    "max_score": 5,
                },
            },
        }
    )

    assert metrics["history_taking"].score == 9
    assert metrics["history_taking"].max_score == 18
    assert metrics["history_taking"].percentage == 50
    assert metrics["relationship_building"].percentage == 100
