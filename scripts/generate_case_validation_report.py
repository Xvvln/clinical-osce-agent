from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
API_DIR = ROOT_DIR / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.models.case import Case
from app.models.rubric import Rubric
from app.validators.case_validator import validate_case, validate_case_rubric_pair, validate_rubric

CASES_DIR = ROOT_DIR / "data" / "cases"
RUBRICS_DIR = ROOT_DIR / "data" / "rubrics"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "docs" / "病例校验报告_首批.md"


@dataclass(frozen=True)
class CaseReportRow:
    case_id: str
    rubric_id: str
    total_score: int
    rule_score_ratio: float
    dimension_summary: str
    evidence_status: str
    validation_status: str


def _load_case_payload(case_path: Path) -> dict[str, Any]:
    return json.loads(case_path.read_text(encoding="utf-8"))


def _load_rubric_payload(rubric_path: Path) -> dict[str, Any]:
    return yaml.safe_load(rubric_path.read_text(encoding="utf-8"))


def _rule_score_ratio(rubric: Rubric) -> float:
    rule_score = sum(
        item.max_score
        for dimension in rubric.dimensions
        for item in dimension.items
        if item.match_rule.kind != "llm_rubric"
    )
    return rule_score / rubric.total_score


def _dimension_summary(rubric: Rubric) -> str:
    return "; ".join(
        f"{dimension.dimension_id}={dimension.weight}"
        for dimension in rubric.dimensions
    )


def _build_evidence_pool(case: Case) -> set[str]:
    evidence_pool = {hidden_fact.fact_id for hidden_fact in case.history.hidden_facts}
    evidence_pool.update(
        exam.exam_code
        for exam in [*case.physical_exam.must_items, *case.physical_exam.optional_items]
    )
    evidence_pool.update(
        test.test_code
        for test in [*case.auxiliary_tests.must_items, *case.auxiliary_tests.optional_items]
    )
    evidence_pool.update(point.point_id for point in case.diagnosis.reasoning_points)
    return evidence_pool


def _evidence_status(case: Case, rubric: Rubric) -> str:
    evidence_pool = _build_evidence_pool(case)
    unresolved = [
        evidence
        for dimension in rubric.dimensions
        for item in dimension.items
        for evidence in item.evidence_expected
        if evidence not in evidence_pool
    ]
    if unresolved:
        return "不完整"
    return "完整"


def build_report_rows() -> list[CaseReportRow]:
    rows: list[CaseReportRow] = []
    for case_path in sorted(CASES_DIR.glob("*.json")):
        case_payload = _load_case_payload(case_path)
        case = validate_case(case_payload)
        rubric_path = RUBRICS_DIR / f"{case.case_id}_rubric.yaml"
        rubric_payload = _load_rubric_payload(rubric_path)
        rubric = validate_rubric(rubric_payload)
        validate_case_rubric_pair(case, rubric)
        rows.append(
            CaseReportRow(
                case_id=case.case_id,
                rubric_id=rubric.rubric_id,
                total_score=rubric.total_score,
                rule_score_ratio=_rule_score_ratio(rubric),
                dimension_summary=_dimension_summary(rubric),
                evidence_status=_evidence_status(case, rubric),
                validation_status="通过",
            )
        )
    return rows


def render_report(rows: list[CaseReportRow]) -> str:
    lines = [
        "# 首批病例校验报告",
        "",
        "本报告由 `scripts/generate_case_validation_report.py` 读取 `data/cases/*.json` 与 `data/rubrics/*.yaml` 后生成。",
        "",
        "| case_id | rubric_id | 总分 | 规则评分占比 | 维度得分上限 | evidence 完整性 | 校验结果 |",
        "| --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            f"{row.case_id} | "
            f"{row.rubric_id} | "
            f"{row.total_score} | "
            f"{row.rule_score_ratio:.0%} | "
            f"{row.dimension_summary} | "
            f"{row.evidence_status} | "
            f"{row.validation_status} |"
        )
    lines.extend(
        [
            "",
            "## 结论",
            "",
            f"首批 {len(rows)} 个病例均已通过 `validate_case`、`validate_rubric` 与 `validate_case_rubric_pair` 三重校验。",
        ]
    )
    return "\n".join(lines) + "\n"


def generate_report(output_path: Path = DEFAULT_OUTPUT_PATH) -> Path:
    rows = build_report_rows()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_report(rows), encoding="utf-8")
    return output_path


def main() -> None:
    path = generate_report()
    print(f"generated: {path}")


if __name__ == "__main__":
    main()
