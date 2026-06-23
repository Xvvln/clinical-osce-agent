# Deep Report Diagnostic Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 1 of deep report analysis: a structured diagnostic contrast evidence packet plus prompt contract that explains why a submitted diagnosis is correct, plausible-but-wrong, contradicted, or unsupported.

**Architecture:** Backend deterministic code classifies the submitted diagnosis and prepares evidence buckets; TeacherAgent/prompt text may only explain those buckets in student-facing language. The first implementation is intentionally backend-only and exposes `deep_report_analysis.diagnostic_contrast_analysis` in reports while keeping legacy reports compatible.

**Tech Stack:** FastAPI service layer, Pydantic models/dataclasses where useful, pytest, existing case JSON under `data/cases`, existing report hydration in `services/api/app/services/osce_session_service.py`.

---

## File Structure

- Create `services/api/app/services/deep_report_analysis_service.py`
  - Owns `DEEP_REPORT_ANALYSIS_PROMPT_VERSION`, `DEEP_REPORT_ANALYSIS_PROMPT_CONTRACT`, `build_deep_report_analysis()`, and deterministic `build_diagnostic_contrast_analysis()`.
  - It does not call model providers in Phase 1. It prepares the structured packet and teacher-facing explanation text deterministically.
- Create `services/api/tests/test_deep_report_analysis_service.py`
  - Covers classification and evidence bucket behavior with real `appendicitis_001` case data.
- Modify `services/api/app/graph/osce_graph.py`
  - Adds `deep_report_analysis` to newly generated feedback reports after `clinical_reasoning_trace` is built.
- Modify `services/api/app/services/osce_session_service.py`
  - Normalizes old reports so missing `deep_report_analysis` becomes a legacy empty payload instead of crashing the frontend.
- Modify `apps/web/src/app/report/report-model.ts`
  - Adds TypeScript types and normalization for `deep_report_analysis`.
- Modify `apps/web/src/app/report/page.tsx`
  - Adds a first-pass “诊断对照分析” section after the existing teacher review section.
- Test files:
  - `services/api/tests/test_deep_report_analysis_service.py`
  - Existing focused API/report tests if report hydration changes require them.
  - Existing `apps/web/src/app/report/report-model.typecheck.ts` for frontend model compatibility.

---

### Task 1: Diagnostic Contrast Service Contract

**Files:**
- Create: `services/api/tests/test_deep_report_analysis_service.py`
- Create: `services/api/app/services/deep_report_analysis_service.py`

- [ ] **Step 1: Write the failing tests**

Add tests that use the real appendicitis case and minimal reports:

```python
from __future__ import annotations

from app.services.case_loader import load_case
from app.services.deep_report_analysis_service import build_diagnostic_contrast_analysis


def _base_report(diagnosis: str, reasoning: str = "") -> dict:
    return {
        "case_id": "appendicitis_001",
        "final_submission": {"diagnosis": diagnosis, "reasoning": reasoning},
        "evidence_graph_summary": {
            "covered_evidence_nodes": [
                {"source_id": "appendicitis_001.hf_02", "label": "转移并固定右下腹痛"},
                {"source_id": "appendicitis_001.hf_05", "label": "无明显腹泻"},
            ],
            "missing_evidence_nodes": [
                {"source_id": "lab.urinalysis", "label": "尿常规"},
            ],
        },
        "clinical_reasoning_trace": {
            "cognitive_patterns": [
                {"pattern_id": "thin_differential_reasoning", "label": "鉴别诊断过窄", "severity": "medium"}
            ]
        },
        "training_gaps": [
            {"gap_type": "differential_reasoning_missing", "label": "补充鉴别诊断证据"}
        ],
    }


def test_diagnostic_contrast_explains_plausible_but_wrong_gastroenteritis():
    case = load_case("appendicitis_001")

    analysis = build_diagnostic_contrast_analysis(
        report=_base_report("急性胃肠炎", "患者恶心，我考虑急性胃肠炎。"),
        case=case,
    )

    assert analysis["classification"] == "plausible_differential"
    assert analysis["submitted_diagnosis"] == "急性胃肠炎"
    assert analysis["target_diagnosis"] == "急性阑尾炎"
    assert analysis["matched_differential_name"] == "急性胃肠炎"
    assert any("恶心" in item for item in analysis["why_student_may_choose_it"])
    assert any("无明显腹泻" in item["label"] for item in analysis["evidence_against_submitted"])
    assert any("转移" in item["label"] for item in analysis["evidence_supporting_target"])
    assert any("尿常规" in item["label"] for item in analysis["missed_discriminating_evidence"])
    assert "先列支持依据" in analysis["next_training_action"]


def test_diagnostic_contrast_marks_main_diagnosis_correct_by_synonym():
    case = load_case("appendicitis_001")

    analysis = build_diagnostic_contrast_analysis(
        report=_base_report("阑尾炎", "转移性右下腹痛支持阑尾炎。"),
        case=case,
    )

    assert analysis["classification"] == "correct"
    assert analysis["matched_target_terms"] == ["阑尾炎"]
    assert analysis["matched_differential_name"] == ""
    assert analysis["evidence_against_submitted"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd services/api
uv run python -m pytest tests/test_deep_report_analysis_service.py -q
```

Expected: fail because `app.services.deep_report_analysis_service` does not exist.

- [ ] **Step 3: Implement minimal service**

Create `services/api/app/services/deep_report_analysis_service.py` with:

```python
from __future__ import annotations

from typing import Any, Mapping

from app.models.case import Case

DEEP_REPORT_ANALYSIS_VERSION = "deep_report_analysis_v1"
DEEP_REPORT_ANALYSIS_PROMPT_VERSION = "deep_report_prompt_v1"

DEEP_REPORT_ANALYSIS_PROMPT_CONTRACT = """你是 OSCE 深度训练分析 Agent。

你不是评分器，也不是诊断裁判。classification、target_diagnosis、score、rubric_trace 均由后端结构化规则确定。
你只能把后端提供的证据包解释成学生能理解的教师讲评，不得新增病例事实、不得修改标准诊断、不得改分。

证据边界：
1. collected_evidence：本轮学生已经采集，可以评价学生是否使用了它。
2. missing_evidence：本轮学生没有采集，只能表述为下一轮需要补采的证据类型，不能泄露具体结果。
3. target_diagnosis_evidence：只用于解释为什么目标诊断更合理；若证据未采集，不能写成本轮已经看到。
4. distractor_clues：只能解释为什么容易误导，不能把患者猜测当成确诊依据。

输出必须围绕：学生为什么会这样想、哪些证据支持、哪些证据反对、还缺什么、目标诊断为什么更合理、下一轮怎么练。
"""


def build_deep_report_analysis(*, report: Mapping[str, Any], case: Case) -> dict[str, Any]:
    return {
        "version": DEEP_REPORT_ANALYSIS_VERSION,
        "status": "generated",
        "diagnostic_contrast_analysis": build_diagnostic_contrast_analysis(report=report, case=case),
    }


def build_legacy_deep_report_analysis() -> dict[str, Any]:
    return {
        "version": DEEP_REPORT_ANALYSIS_VERSION,
        "status": "legacy_report",
        "diagnostic_contrast_analysis": _empty_diagnostic_contrast_analysis(),
    }
```

Then add helper functions:

- Normalize diagnosis text with lowercase, whitespace removal, and simple Chinese punctuation removal.
- Match main diagnosis against `main_diagnosis` and `main_diagnosis_synonyms`.
- Match differential diagnosis against `differential_diagnoses[].disease_name`.
- Build `evidence_supporting_target` from covered evidence nodes whose `source_id` appears in support reasoning points.
- Build `evidence_against_submitted` from covered evidence nodes whose `source_id` appears in `negative_findings` for the matched differential.
- Build `missed_discriminating_evidence` from missing evidence nodes whose `source_id` appears in `negative_findings` or matched differential key distinction.
- Build `teacher_explanation` and `next_training_action` deterministically.

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
cd services/api
uv run python -m pytest tests/test_deep_report_analysis_service.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

Stage only the new service and its tests:

```bash
git add services/api/app/services/deep_report_analysis_service.py services/api/tests/test_deep_report_analysis_service.py
git commit -m "feat: add diagnostic contrast analysis"
```

---

### Task 2: Report Generation Integration

**Files:**
- Modify: `services/api/app/graph/osce_graph.py`
- Modify: `services/api/app/services/osce_session_service.py`
- Test: existing report/session tests plus a new focused test if needed.

- [ ] **Step 1: Write failing integration test**

Add or extend a backend test so a generated completed report contains:

```python
analysis = report["deep_report_analysis"]
assert analysis["status"] == "generated"
assert analysis["diagnostic_contrast_analysis"]["target_diagnosis"]
assert analysis["diagnostic_contrast_analysis"]["classification"] in {
    "correct",
    "partially_correct",
    "plausible_differential",
    "contradicted_by_case",
    "unsupported",
}
```

For legacy normalization, add:

```python
normalized = _normalize_report_payload({"report_id": "old_report"})
assert normalized["deep_report_analysis"]["status"] == "legacy_report"
```

- [ ] **Step 2: Run tests to verify fail**

Run the focused tests chosen above. Expected failure: missing `deep_report_analysis`.

- [ ] **Step 3: Integrate service**

In `osce_graph.feedback_node`, after `clinical_reasoning_trace` is built and before `feedback_report` is returned:

```python
from app.services.deep_report_analysis_service import build_deep_report_analysis

deep_report_analysis = build_deep_report_analysis(
    report={**report, "clinical_reasoning_trace": clinical_reasoning_trace, "evidence_graph_summary": evidence_graph_summary},
    case=case,
)
```

Then include:

```python
"deep_report_analysis": deep_report_analysis,
```

In report normalization, default missing analysis to `build_legacy_deep_report_analysis()`.

- [ ] **Step 4: Run tests to verify pass**

Run focused backend tests and the new service tests:

```bash
cd services/api
uv run python -m pytest tests/test_deep_report_analysis_service.py tests/test_osce_sessions.py -q
```

If `tests/test_osce_sessions.py` is too broad for local speed, run the smallest failing report normalization tests plus `tests/test_deep_report_analysis_service.py`.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/graph/osce_graph.py services/api/app/services/osce_session_service.py services/api/tests/test_deep_report_analysis_service.py
git commit -m "feat: attach deep report analysis to reports"
```

---

### Task 3: Frontend Model And First Display

**Files:**
- Modify: `apps/web/src/app/report/report-model.ts`
- Modify: `apps/web/src/app/report/report-model.typecheck.ts`
- Modify: `apps/web/src/app/report/page.tsx`

- [ ] **Step 1: Write failing frontend model/type test**

Extend `report-model.typecheck.ts` with a report containing:

```ts
deep_report_analysis: {
  version: "deep_report_analysis_v1",
  status: "generated",
  diagnostic_contrast_analysis: {
    submitted_diagnosis: "急性胃肠炎",
    target_diagnosis: "急性阑尾炎",
    classification: "plausible_differential",
    matched_target_terms: [],
    matched_differential_name: "急性胃肠炎",
    why_student_may_choose_it: ["恶心可能让学生想到胃肠炎。"],
    evidence_supporting_submitted: [],
    evidence_against_submitted: [{ source_id: "appendicitis_001.hf_05", label: "无明显腹泻" }],
    evidence_supporting_target: [{ source_id: "appendicitis_001.hf_02", label: "转移性右下腹痛" }],
    missed_discriminating_evidence: [{ source_id: "lab.urinalysis", label: "尿常规" }],
    reasoning_error_patterns: ["鉴别诊断过窄"],
    teacher_explanation: "这个诊断有一定诱因，但已有证据更支持阑尾炎。",
    next_training_action: "先列支持依据，再列反证 / 排除依据，最后提交诊断。",
  },
}
```

Assert normalized legacy reports still expose `deep_report_analysis.status === "legacy_report"`.

- [ ] **Step 2: Run frontend type test to verify fail**

Run:

```bash
corepack pnpm --dir apps/web exec tsc --noEmit
```

Expected: fail because `deep_report_analysis` types do not exist.

- [ ] **Step 3: Add types and first UI section**

Add `DeepReportAnalysis`, `DiagnosticContrastAnalysis`, and `DiagnosticEvidenceItem` types in `report-model.ts`.

Normalize missing payload to:

```ts
const DEFAULT_DEEP_REPORT_ANALYSIS = {
  version: "deep_report_analysis_v1",
  status: "legacy_report",
  diagnostic_contrast_analysis: {
    submitted_diagnosis: "",
    target_diagnosis: "",
    classification: "unsupported",
    matched_target_terms: [],
    matched_differential_name: "",
    why_student_may_choose_it: [],
    evidence_supporting_submitted: [],
    evidence_against_submitted: [],
    evidence_supporting_target: [],
    missed_discriminating_evidence: [],
    reasoning_error_patterns: [],
    teacher_explanation: "",
    next_training_action: "",
  },
} as const;
```

In `page.tsx`, add `DeepReportAnalysisSection` after `AiReflectionReviewSection`. It should render only when status is `generated` and show:

- 学生提交诊断
- 目标诊断
- 分类标签
- 为什么会想到这个
- 哪些证据反对
- 为什么目标诊断更合适
- 下一轮训练动作

- [ ] **Step 4: Run frontend verification**

Run:

```bash
corepack pnpm --dir apps/web exec tsc --noEmit
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/app/report/report-model.ts apps/web/src/app/report/report-model.typecheck.ts apps/web/src/app/report/page.tsx
git commit -m "feat: show diagnostic contrast analysis"
```

---

### Task 4: End-To-End Smoke And Documentation Update

**Files:**
- Modify: `项目开发文档.md`

- [ ] **Step 1: Run focused backend and frontend checks**

Run:

```bash
cd services/api
uv run python -m pytest tests/test_deep_report_analysis_service.py -q
cd ../..
corepack pnpm --dir apps/web exec tsc --noEmit
```

- [ ] **Step 2: Run or inspect one real generated report**

Use the local API or browser flow to generate a report where the final diagnosis is “急性胃肠炎” for `appendicitis_001`. Confirm the report JSON contains:

```text
deep_report_analysis.status = generated
diagnostic_contrast_analysis.classification = plausible_differential
diagnostic_contrast_analysis.evidence_against_submitted includes 无明显腹泻 when collected
diagnostic_contrast_analysis.missed_discriminating_evidence does not reveal uncollected result values
```

- [ ] **Step 3: Update project document**

In `项目开发文档.md`, append a short implementation record under `2026-06-23 · 深度训练分析报告 v2 设计`:

```text
- Phase 1 已实现：
  - deep_report_analysis_service 生成诊断对照分析；
  - 新报告会带 deep_report_analysis；
  - 旧报告按 legacy 空态兼容；
  - 报告页展示诊断对照分析。
- 验证命令：
  - ...
```

- [ ] **Step 4: Commit documentation**

```bash
git add 项目开发文档.md
git commit -m "docs: record diagnostic contrast analysis phase"
```

---

## Self-Review

- Spec coverage: This plan implements Phase 1 only: prompt contract, evidence packet, diagnostic contrast classification, report attachment, first frontend display, and documentation record.
- Out of scope: full `overall_evaluation`, clinical task analysis, humanistic communication analysis, next-round Coach integration, and browser visual polish. Those remain later phases from the project document.
- Placeholder scan: no unfinished placeholder markers or unspecified files.
- Type consistency: backend field name is consistently `deep_report_analysis.diagnostic_contrast_analysis`; frontend types mirror the same field names.
