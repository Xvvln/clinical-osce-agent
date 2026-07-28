from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class NormalizedScoreMetric:
    score: float
    max_score: float
    percentage: float


def score_group_metric(
    report: Mapping[str, Any],
    group_id: str,
) -> NormalizedScoreMetric | None:
    score_groups = _mapping(report.get("score_groups"))
    group = _mapping(score_groups.get(group_id))
    score = _number(group.get("score"))
    max_score = _number(group.get("max_score"))
    if score is None or max_score is None or max_score <= 0:
        return None
    return _normalized_metric(score, max_score)


def dimension_score_metrics(
    report: Mapping[str, Any],
) -> dict[str, NormalizedScoreMetric]:
    max_scores: defaultdict[str, float] = defaultdict(float)
    for item in _mapping(report.get("rubric_scores")).values():
        item_payload = _mapping(item)
        dimension_id = str(item_payload.get("dimension_id") or "")
        max_score = _number(item_payload.get("max_score"))
        if dimension_id and max_score is not None and max_score > 0:
            max_scores[dimension_id] += max_score

    metrics: dict[str, NormalizedScoreMetric] = {}
    for dimension_id, value in _mapping(report.get("dimension_scores")).items():
        score = _number(value)
        max_score = max_scores.get(str(dimension_id), 0)
        if score is None or max_score <= 0:
            continue
        metrics[str(dimension_id)] = _normalized_metric(score, max_score)
    return metrics


def aggregate_score_metrics(
    metrics: Iterable[NormalizedScoreMetric],
) -> dict[str, int | float | None]:
    values = list(metrics)
    if not values:
        return {
            "sample_count": 0,
            "average_score": 0,
            "average_max_score": 0,
            "average_percentage": None,
        }
    return {
        "sample_count": len(values),
        "average_score": _rounded_average(metric.score for metric in values),
        "average_max_score": _rounded_average(metric.max_score for metric in values),
        "average_percentage": _rounded_average(metric.percentage for metric in values),
    }


def _normalized_metric(score: float, max_score: float) -> NormalizedScoreMetric:
    percentage = max(0.0, min(100.0, score / max_score * 100))
    return NormalizedScoreMetric(
        score=score,
        max_score=max_score,
        percentage=percentage,
    )


def _rounded_average(values: Iterable[float]) -> int | float:
    normalized = list(values)
    average = sum(normalized) / len(normalized)
    rounded = round(average, 2)
    return int(rounded) if rounded.is_integer() else rounded


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


__all__ = [
    "NormalizedScoreMetric",
    "aggregate_score_metrics",
    "dimension_score_metrics",
    "score_group_metric",
]
