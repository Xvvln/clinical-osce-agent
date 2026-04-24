from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXPECTED_CASES = {
    "appendicitis_001",
    "hyperthyroid_001",
    "pneumonia_001",
    "acs_001",
    "heart_failure_001",
}


def _load_report_module() -> Any:
    try:
        return importlib.import_module("scripts.generate_case_validation_report")
    except ModuleNotFoundError as exc:
        pytest.fail(
            "红灯：缺少病例校验报告生成器 `scripts.generate_case_validation_report`。"
            f"缺少模块：{exc.name!r}。"
        )


def test_generate_case_validation_report_contains_all_first_batch_cases(tmp_path: Path) -> None:
    report_module = _load_report_module()
    generate_report = getattr(report_module, "generate_report", None)
    if generate_report is None:
        pytest.fail("红灯：`generate_report(output_path)` 尚未实现。")

    output_path = tmp_path / "病例校验报告_首批.md"
    result_path = generate_report(output_path=output_path)

    assert result_path == output_path
    assert output_path.exists()

    content = output_path.read_text(encoding="utf-8")
    assert "# 首批病例校验报告" in content
    assert "规则评分占比" in content
    assert "evidence 完整性" in content

    for case_id in EXPECTED_CASES:
        assert case_id in content
        assert f"{case_id}_rubric" in content

    assert "通过" in content
    assert "缺失" not in content
