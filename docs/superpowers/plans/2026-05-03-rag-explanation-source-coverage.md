# RAG Explanation Source Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-feedback explanation source attribution so every `strength`, `reasoning_error`, and `llm_reasoning_feedback` item can be audited against concrete `rubric:` references.

**Architecture:** Keep existing report text fields for UI compatibility, and add `explanation_source_items` as a structured attribution layer. Extend evaluation to fail reports that contain explanation text without matching explanation source items, and surface the new coverage metrics through persistence, admin API, admin UI, and project documentation.

**Tech Stack:** Python 3.11, FastAPI, LangGraph, SQLite, pytest, Next.js, React, TypeScript.

**Execution note:** Do not create git commits while executing this plan unless the user explicitly asks for a commit.

---

## File Structure

- Modify `services/api/app/services/source_retriever.py`
  - Expand report-level source pool so rubric references for explained scored items are available for per-feedback attribution.
- Modify `services/api/tests/test_source_retriever.py`
  - Lock the new source-pool contract with a failing test first.
- Modify `services/api/app/graph/osce_graph.py`
  - Generate `explanation_source_items` alongside existing `strengths`, `reasoning_errors`, and `llm_reasoning_feedback`.
- Modify `services/api/tests/test_osce_graph.py`
  - Assert generated reports contain structured explanation source items.
- Modify `services/api/app/services/evaluation_runner.py`
  - Add explanation coverage fields and helper functions.
- Modify `services/api/tests/test_evaluation_runner.py`
  - Add failure cases for missing explanation source items and inconsistent explanation references.
- Modify `services/api/app/services/evaluation_result_store.py`
  - Normalize new fields for old stored evaluation JSON.
- Modify `services/api/tests/test_evaluation_result_store.py`
  - Persist and legacy-normalization tests for the new fields.
- Modify `services/api/tests/test_admin_api.py`
  - Admin evaluation API contract includes the new fields.
- Modify `apps/admin/src/app/page.tsx`
  - Type, export, and render explanation coverage metrics.
- Modify `项目开发文档.md`
  - Sync Step 10 current implementation state and execution record.

---

### Task 1: Expand report-level rubric source coverage

**Files:**
- Modify: `services/api/tests/test_source_retriever.py:4-52`
- Modify: `services/api/app/services/source_retriever.py:35-57`

- [ ] **Step 1: Write the failing source retriever test**

Update `test_retrieve_feedback_source_items_returns_indexed_case_source_and_evidence` in `services/api/tests/test_source_retriever.py` so the expected references include `dx_main`, because `dx_main` is a scored rubric item that can generate a `strength` explanation.

```python
assert [item.reference for item in items] == [
    "case:appendicitis_001",
    "source:fareez_osce_2022",
    "rubric:appendicitis_001_rubric.item.ht_migration",
    "rubric:appendicitis_001_rubric.item.dx_main",
    "evidence:appendicitis_001.hf_01",
    "evidence:abd.palpation.rebound",
    "evidence:急性阑尾炎",
]
assert items[0].title == "右下腹痛教学病例"
assert items[0].source_type == "case"
assert items[1].title == "A dataset of simulated patient-physician medical interviews with a focus on respiratory cases"
assert items[1].source_type == "source"
assert items[1].metadata["license"] == "CC BY 4.0"
assert items[2].title == "追问疼痛部位及转移特征"
assert items[2].source_type == "rubric"
assert items[3].title == "主要诊断命中急性阑尾炎"
assert items[3].source_type == "rubric"
assert items[4].title == "24 小时前开始，最初是上腹部隐痛。"
assert items[4].source_type == "evidence"
assert items[5].title == "右下腹反跳痛阳性。"
assert items[5].source_type == "evidence"
assert items[6].title == "急性阑尾炎"
assert items[6].source_type == "evidence"
```

- [ ] **Step 2: Run the source retriever test to verify it fails**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" python -m pytest "clinical-osce-agent/services/api/tests/test_source_retriever.py::test_retrieve_feedback_source_items_returns_indexed_case_source_and_evidence" -q
```

Expected: FAIL because `rubric:appendicitis_001_rubric.item.dx_main` is not yet returned.

- [ ] **Step 3: Implement rubric source expansion**

In `services/api/app/services/source_retriever.py`, update `_collect_references` so all rubric score keys are present after missed-item references and before evidence references.

```python
for item_id in report.get("missed_items", []):
    if item_id in rubric_scores:
        references.append(f"rubric:{case_id}_rubric.item.{item_id}")

for item_id in rubric_scores:
    if isinstance(item_id, str):
        references.append(f"rubric:{case_id}_rubric.item.{item_id}")

for fact_id in revealed_facts:
    references.append(f"evidence:{fact_id}")
```

Keep `_deduplicate()` unchanged so missed-item rubric references keep their current order and duplicate entries collapse.

- [ ] **Step 4: Run source retriever tests to verify green**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" python -m pytest "clinical-osce-agent/services/api/tests/test_source_retriever.py" -q
```

Expected: all tests in `test_source_retriever.py` pass.

---

### Task 2: Generate structured explanation source items in reports

**Files:**
- Modify: `services/api/tests/test_osce_graph.py`
- Modify: `services/api/app/graph/osce_graph.py:302-366`

- [ ] **Step 1: Write the failing graph report test**

In the existing feedback report test in `services/api/tests/test_osce_graph.py`, after the current `source_reference_items` assertions, add assertions for `explanation_source_items`.

```python
assert {
    "kind": "strength",
    "text": "主要诊断命中急性阑尾炎：已完成。",
    "rubric_item_id": "dx_main",
    "source_references": ["rubric:appendicitis_001_rubric.item.dx_main"],
} in feedback_report["explanation_source_items"]
assert {
    "kind": "reasoning_error",
    "text": "提出输尿管结石并说明排除依据：评分轨迹未找到足够证据。",
    "rubric_item_id": "dxd_urolith",
    "source_references": ["rubric:appendicitis_001_rubric.item.dxd_urolith"],
} in feedback_report["explanation_source_items"]
assert any(
    item["kind"] == "llm_reasoning_feedback"
    and item["rubric_item_id"] == "rs_support"
    and item["source_references"] == ["rubric:appendicitis_001_rubric.item.rs_support"]
    for item in feedback_report["explanation_source_items"]
)
```

- [ ] **Step 2: Run the graph test to verify it fails**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" python -m pytest "clinical-osce-agent/services/api/tests/test_osce_graph.py" -q
```

Expected: FAIL with `KeyError: 'explanation_source_items'` or assertion failure.

- [ ] **Step 3: Implement explanation source item generation**

In `services/api/app/graph/osce_graph.py`, compute `explanation_source_items` before building `feedback_report`.

```python
explanation_source_items = _build_explanation_source_items(report.get("case_id", ""), rubric_scores)
```

Add the field to `feedback_report`.

```python
"explanation_source_items": explanation_source_items,
```

Add these helper functions near `_build_llm_reasoning_feedback`.

```python
def _build_explanation_source_items(case_id: str, rubric_scores: dict[str, Any]) -> list[dict[str, Any]]:
    explanation_items: list[dict[str, Any]] = []
    for item_id, item_score in rubric_scores.items():
        if item_score["score"] > 0:
            explanation_items.append(
                _build_explanation_source_item(
                    case_id=case_id,
                    kind="strength",
                    text=f"{item_score['description']}：已完成。",
                    rubric_item_id=item_id,
                )
            )
        if (
            item_score["dimension_id"] in {"differential_diagnosis", "reasoning"}
            and item_score["score"] < item_score["max_score"]
        ):
            explanation_items.append(
                _build_explanation_source_item(
                    case_id=case_id,
                    kind="reasoning_error",
                    text=f"{item_score['description']}：评分轨迹未找到足够证据。",
                    rubric_item_id=item_id,
                )
            )
        if "rationale" in item_score:
            explanation_items.append(
                _build_explanation_source_item(
                    case_id=case_id,
                    kind="llm_reasoning_feedback",
                    text=str(item_score["rationale"]),
                    rubric_item_id=item_id,
                )
            )
    return explanation_items


def _build_explanation_source_item(case_id: str, kind: str, text: str, rubric_item_id: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "text": text,
        "rubric_item_id": rubric_item_id,
        "source_references": [f"rubric:{case_id}_rubric.item.{rubric_item_id}"],
    }
```

- [ ] **Step 4: Run graph and source retriever tests**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" python -m pytest "clinical-osce-agent/services/api/tests/test_osce_graph.py" "clinical-osce-agent/services/api/tests/test_source_retriever.py" -q
```

Expected: both test files pass.

---

### Task 3: Add explanation coverage to evaluation results

**Files:**
- Modify: `services/api/tests/test_evaluation_runner.py:24-140`
- Modify: `services/api/app/services/evaluation_runner.py:28-145`

- [ ] **Step 1: Add fake services for explanation coverage failures**

In `services/api/tests/test_evaluation_runner.py`, add these fake services after `ReportWithPartialRubricSourcesService`.

```python
class ReportWithExplanationTextWithoutExplanationSourcesService(ReportWithoutRagSourcesService):
    def create_session(self, case_id: str, student_id: str) -> dict[str, str]:
        return {"session_id": "session_with_explanation_text_without_sources"}

    def get_report(self, session_id: str) -> dict[str, object]:
        return {
            "case_id": "appendicitis_001",
            "total_score": 32,
            "missed_items": [],
            "rubric_scores": {
                "dx_main": {
                    "dimension_id": "main_diagnosis",
                    "description": "主要诊断命中急性阑尾炎",
                    "score": 15,
                    "max_score": 15,
                }
            },
            "strengths": ["主要诊断命中急性阑尾炎：已完成。"],
            "reasoning_errors": [],
            "llm_reasoning_feedback": [],
            "source_reference_items": [
                {
                    "reference": "rubric:appendicitis_001_rubric.item.dx_main",
                    "source_type": "rubric",
                    "title": "主要诊断命中急性阑尾炎",
                    "metadata": {},
                }
            ],
        }


class ReportWithExplanationMissingRubricReferenceService(ReportWithExplanationTextWithoutExplanationSourcesService):
    def create_session(self, case_id: str, student_id: str) -> dict[str, str]:
        return {"session_id": "session_with_explanation_missing_rubric_reference"}

    def get_report(self, session_id: str) -> dict[str, object]:
        report = dict(super().get_report(session_id))
        report["explanation_source_items"] = [
            {
                "kind": "strength",
                "text": "主要诊断命中急性阑尾炎：已完成。",
                "rubric_item_id": "dx_main",
                "source_references": [],
            }
        ]
        return report


class ReportWithExplanationReferenceOutsideReportSourcesService(ReportWithExplanationTextWithoutExplanationSourcesService):
    def create_session(self, case_id: str, student_id: str) -> dict[str, str]:
        return {"session_id": "session_with_explanation_reference_outside_report_sources"}

    def get_report(self, session_id: str) -> dict[str, object]:
        report = dict(super().get_report(session_id))
        report["source_reference_items"] = [
            {
                "reference": "case:appendicitis_001",
                "source_type": "case",
                "title": "右下腹痛教学病例",
                "metadata": {},
            }
        ]
        report["explanation_source_items"] = [
            {
                "kind": "strength",
                "text": "主要诊断命中急性阑尾炎：已完成。",
                "rubric_item_id": "dx_main",
                "source_references": ["rubric:appendicitis_001_rubric.item.dx_main"],
            }
        ]
        return report
```

- [ ] **Step 2: Add failing evaluation tests**

Add these tests before `test_run_evaluation_case_fails_when_forbidden_terms_appear`.

```python
def test_run_evaluation_case_fails_when_explanation_text_lacks_source_items() -> None:
    evaluation_case = EvaluationCase(
        case_id="appendicitis_001",
        student_id="eval_student",
        steps=[EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="转移性右下腹痛支持诊断。")],
        expected_total_score=32,
        forbidden_terms=[],
    )

    result = run_evaluation_case(evaluation_case, ReportWithExplanationTextWithoutExplanationSourcesService())

    assert result.passed is False
    assert result.rag_explanation_coverage_passed is False
    assert result.rag_explanation_coverage_ratio == 0.0
    assert result.missing_explanation_references == ["explanation:strength:dx_main"]


def test_run_evaluation_case_fails_when_explanation_item_lacks_its_rubric_reference() -> None:
    evaluation_case = EvaluationCase(
        case_id="appendicitis_001",
        student_id="eval_student",
        steps=[EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="转移性右下腹痛支持诊断。")],
        expected_total_score=32,
        forbidden_terms=[],
    )

    result = run_evaluation_case(evaluation_case, ReportWithExplanationMissingRubricReferenceService())

    assert result.passed is False
    assert result.rag_explanation_coverage_passed is False
    assert result.rag_explanation_coverage_ratio == 0.0
    assert result.missing_explanation_references == ["explanation:strength:dx_main"]


def test_run_evaluation_case_fails_when_explanation_reference_is_missing_from_report_sources() -> None:
    evaluation_case = EvaluationCase(
        case_id="appendicitis_001",
        student_id="eval_student",
        steps=[EvaluationStep(kind="submit_diagnosis", value="急性阑尾炎", reasoning="转移性右下腹痛支持诊断。")],
        expected_total_score=32,
        forbidden_terms=[],
    )

    result = run_evaluation_case(evaluation_case, ReportWithExplanationReferenceOutsideReportSourcesService())

    assert result.passed is False
    assert result.rag_source_coverage_passed is True
    assert result.rag_explanation_coverage_passed is False
    assert result.rag_explanation_coverage_ratio == 0.0
    assert result.missing_explanation_references == ["explanation:strength:dx_main"]
```

Also extend `test_run_evaluation_case_passes_standard_appendicitis_path`.

```python
assert result.rag_explanation_coverage_passed is True
assert result.rag_explanation_coverage_ratio == 1.0
assert result.missing_explanation_references == []
```

- [ ] **Step 3: Run evaluation tests to verify red**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" python -m pytest "clinical-osce-agent/services/api/tests/test_evaluation_runner.py" -q
```

Expected: FAIL with missing `EvaluationResult` attributes or failing explanation coverage assertions.

- [ ] **Step 4: Add EvaluationResult fields**

In `services/api/app/services/evaluation_runner.py`, extend `EvaluationResult`.

```python
rag_explanation_coverage_passed: bool = False
rag_explanation_coverage_ratio: float = 0.0
missing_explanation_references: list[str] = field(default_factory=list)
```

Place these after `missing_rubric_references` and before `duration_ms`.

- [ ] **Step 5: Calculate explanation coverage in `run_evaluation_case`**

Add these lines after `rag_source_coverage_passed` is calculated.

```python
missing_explanation_references = _missing_explanation_references(
    evaluation_case.case_id,
    report,
    source_reference_items,
)
rag_explanation_coverage_ratio = _explanation_reference_coverage_ratio(report, missing_explanation_references)
rag_explanation_coverage_passed = not missing_explanation_references
```

Update `passed`.

```python
passed = (
    actual_total_score == evaluation_case.expected_total_score
    and not forbidden_term_violations
    and rag_source_coverage_passed
    and rag_explanation_coverage_passed
)
```

Pass the new fields to `EvaluationResult`.

```python
rag_explanation_coverage_passed=rag_explanation_coverage_passed,
rag_explanation_coverage_ratio=rag_explanation_coverage_ratio,
missing_explanation_references=missing_explanation_references,
```

- [ ] **Step 6: Add explanation coverage helpers**

Add these helpers below `_rubric_reference_coverage_ratio`.

```python
def _missing_explanation_references(case_id: str, report: dict[str, Any], source_reference_items: Any) -> list[str]:
    covered_references = {
        item["reference"]
        for item in source_reference_items
        if isinstance(item, dict) and isinstance(item.get("reference"), str)
    }
    explanation_source_items = report.get("explanation_source_items", [])
    if not isinstance(explanation_source_items, list) or not explanation_source_items:
        if _report_has_explanation_text(report):
            return _expected_missing_explanation_references(report)
        return []

    missing_references: list[str] = []
    for item in explanation_source_items:
        if not isinstance(item, dict):
            missing_references.append("explanation:invalid:item")
            continue
        kind = item.get("kind") if isinstance(item.get("kind"), str) else "unknown"
        rubric_item_id = item.get("rubric_item_id")
        if not isinstance(rubric_item_id, str) or not rubric_item_id:
            missing_references.append(f"explanation:{kind}:missing_rubric_item_id")
            continue
        expected_reference = f"rubric:{case_id}_rubric.item.{rubric_item_id}"
        source_references = item.get("source_references", [])
        if not isinstance(source_references, list):
            source_references = []
        if expected_reference not in source_references or expected_reference not in covered_references:
            missing_references.append(f"explanation:{kind}:{rubric_item_id}")
    return missing_references


def _explanation_reference_coverage_ratio(report: dict[str, Any], missing_explanation_references: list[str]) -> float:
    explanation_source_items = report.get("explanation_source_items", [])
    if isinstance(explanation_source_items, list) and explanation_source_items:
        total_count = len(explanation_source_items)
    elif _report_has_explanation_text(report):
        total_count = len(_expected_missing_explanation_references(report))
    else:
        return 1.0
    if total_count == 0:
        return 0.0
    covered_count = total_count - len(missing_explanation_references)
    return covered_count / total_count


def _report_has_explanation_text(report: dict[str, Any]) -> bool:
    return bool(
        report.get("strengths")
        or report.get("reasoning_errors")
        or report.get("llm_reasoning_feedback")
    )


def _expected_missing_explanation_references(report: dict[str, Any]) -> list[str]:
    expected_references: list[str] = []
    rubric_scores = report.get("rubric_scores", {})
    if not isinstance(rubric_scores, dict):
        return expected_references
    for item_id, item_score in rubric_scores.items():
        if not isinstance(item_id, str) or not isinstance(item_score, dict):
            continue
        if item_score.get("score", 0) > 0:
            expected_references.append(f"explanation:strength:{item_id}")
        if (
            item_score.get("dimension_id") in {"differential_diagnosis", "reasoning"}
            and item_score.get("score", 0) < item_score.get("max_score", 0)
        ):
            expected_references.append(f"explanation:reasoning_error:{item_id}")
        if "rationale" in item_score:
            expected_references.append(f"explanation:llm_reasoning_feedback:{item_id}")
    return expected_references
```

- [ ] **Step 7: Run evaluation tests to verify green**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" python -m pytest "clinical-osce-agent/services/api/tests/test_evaluation_runner.py" -q
```

Expected: all tests in `test_evaluation_runner.py` pass.

---

### Task 4: Persist and normalize explanation coverage fields

**Files:**
- Modify: `services/api/tests/test_evaluation_result_store.py:8-129`
- Modify: `services/api/app/services/evaluation_result_store.py:78-87`

- [ ] **Step 1: Write failing persistence expectations**

In `test_evaluation_result_store_persists_batch_result_across_instances`, add new fields to both `EvaluationResult(...)` objects and expected dictionaries.

Passing result constructor fields:

```python
rag_explanation_coverage_passed=True,
rag_explanation_coverage_ratio=1.0,
missing_explanation_references=[],
```

Failing result constructor fields:

```python
rag_explanation_coverage_passed=False,
rag_explanation_coverage_ratio=0.0,
missing_explanation_references=["explanation:reasoning_error:rs_exclude"],
```

Passing expected dictionary fields:

```python
"rag_explanation_coverage_passed": True,
"rag_explanation_coverage_ratio": 1.0,
"missing_explanation_references": [],
```

Failing expected dictionary fields:

```python
"rag_explanation_coverage_passed": False,
"rag_explanation_coverage_ratio": 0.0,
"missing_explanation_references": ["explanation:reasoning_error:rs_exclude"],
```

- [ ] **Step 2: Write failing legacy normalization expectations**

In `test_evaluation_result_store_normalizes_legacy_results_without_rag_fields`, add expected defaults.

```python
"rag_explanation_coverage_passed": False,
"rag_explanation_coverage_ratio": 0.0,
"missing_explanation_references": [],
```

- [ ] **Step 3: Run store tests to verify red**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" python -m pytest "clinical-osce-agent/services/api/tests/test_evaluation_result_store.py" -q
```

Expected: FAIL until `EvaluationResult` serialization and normalization include new fields.

- [ ] **Step 4: Normalize legacy stored results**

In `services/api/app/services/evaluation_result_store.py`, extend `_normalize_batch_result`.

```python
result.setdefault("rag_explanation_coverage_passed", False)
result.setdefault("rag_explanation_coverage_ratio", 0.0)
result.setdefault("missing_explanation_references", [])
```

- [ ] **Step 5: Run store tests to verify green**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" python -m pytest "clinical-osce-agent/services/api/tests/test_evaluation_result_store.py" -q
```

Expected: all tests in `test_evaluation_result_store.py` pass.

---

### Task 5: Update admin API contract tests

**Files:**
- Modify: `services/api/tests/test_admin_api.py`

- [ ] **Step 1: Write failing admin API expectations**

In `test_admin_can_read_evaluation_batch_detail`, add new fields to the expected result dictionary.

```python
"rag_explanation_coverage_passed": False,
"rag_explanation_coverage_ratio": 0.0,
"missing_explanation_references": [],
```

In `test_admin_can_run_evaluation_batch`, add the same fields to the expected result dictionary.

```python
"rag_explanation_coverage_passed": False,
"rag_explanation_coverage_ratio": 0.0,
"missing_explanation_references": [],
```

- [ ] **Step 2: Run admin API tests to verify red or contract mismatch**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" python -m pytest "clinical-osce-agent/services/api/tests/test_admin_api.py::test_admin_can_read_evaluation_batch_detail" "clinical-osce-agent/services/api/tests/test_admin_api.py::test_admin_can_run_evaluation_batch" -q
```

Expected: fail before all upstream fields and normalization are implemented; pass after Tasks 3 and 4.

- [ ] **Step 3: Run full admin API tests**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" python -m pytest "clinical-osce-agent/services/api/tests/test_admin_api.py" -q
```

Expected: all tests in `test_admin_api.py` pass.

---

### Task 6: Update admin UI types, export, and display

**Files:**
- Modify: `apps/admin/src/app/page.tsx:47-59`
- Modify: `apps/admin/src/app/page.tsx:576-597`
- Modify: `apps/admin/src/app/page.tsx:1484-1492`

- [ ] **Step 1: Add TypeScript fields**

In `EvaluationCaseResult`, add:

```typescript
rag_explanation_coverage_passed: boolean;
rag_explanation_coverage_ratio: number;
missing_explanation_references: readonly string[];
```

- [ ] **Step 2: Preserve fields in evaluation JSON export**

In `buildEvaluationExportPayload`, add these properties inside each mapped result:

```typescript
rag_explanation_coverage_passed: result.rag_explanation_coverage_passed,
rag_explanation_coverage_ratio: result.rag_explanation_coverage_ratio,
missing_explanation_references: result.missing_explanation_references,
```

- [ ] **Step 3: Display explanation coverage in evaluation details**

After the existing RAG coverage paragraph, add:

```tsx
<p className="mt-1 text-[#8A7D6F]">
  解释覆盖率 {Math.round(result.rag_explanation_coverage_ratio * 100)}% · 解释来源{result.rag_explanation_coverage_passed ? "通过" : "未通过"}
</p>
{result.missing_explanation_references.length > 0 ? (
  <p className="mt-1 font-mono text-[11px] text-[#AE5630]">缺失解释来源：{result.missing_explanation_references.join("、")}</p>
) : null}
```

- [ ] **Step 4: Run admin typecheck**

Run:

```bash
corepack pnpm --dir "/f/杂物/个人开发/clinical-osce-agent/apps/admin" typecheck
```

Expected: TypeScript typecheck passes.

---

### Task 7: Sync project development document

**Files:**
- Modify: `项目开发文档.md:2505-2510`

- [ ] **Step 1: Update Step 10 current implementation state**

Replace the second paragraph under `### 当前实现状态（2026-05-03）` with text that includes explanation coverage.

```markdown
管理端系统评测详情已展示每个评测 session 的 RAG 引用覆盖状态、rubric 覆盖率、来源条数、来源类型、解释覆盖率和缺失解释来源；评测 JSON 导出也会保留这些字段。当前覆盖检查已覆盖“漏项 → rubric 来源”和“每条 strengths / reasoning_errors / LLM reasoning feedback → rubric 来源”的解释依据链路；更细的“每条解释是否进一步绑定到具体 evidence 来源”仍留给后续证据级覆盖率统计。
```

- [ ] **Step 2: Add execution record to `24.6 执行记录`**

Find the existing `2026-05-03` execution records and add a short record.

```markdown
- 2026-05-03：Step 10 RAG 逐条反馈来源覆盖。报告新增 `explanation_source_items`，评测新增 `rag_explanation_coverage_passed`、`rag_explanation_coverage_ratio` 与 `missing_explanation_references`，管理端展示解释覆盖率和缺失解释来源。验证：`pytest services/api/tests -q` 通过，`pnpm --dir apps/admin typecheck` 通过。
```

- [ ] **Step 3: Read updated doc section**

Run a targeted read of the updated section and verify it mentions:

- `explanation_source_items`
- `rag_explanation_coverage_passed`
- `rag_explanation_coverage_ratio`
- `missing_explanation_references`

---

### Task 8: Final verification

**Files:**
- No file edits.

- [ ] **Step 1: Run backend full test suite**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" python -m pytest "clinical-osce-agent/services/api/tests" -q
```

Expected: all backend tests pass.

- [ ] **Step 2: Run admin typecheck**

Run:

```bash
corepack pnpm --dir "/f/杂物/个人开发/clinical-osce-agent/apps/admin" typecheck
```

Expected: TypeScript typecheck passes.

- [ ] **Step 3: Optional MCP browser validation after tests pass**

If the user wants browser-level validation, run local backend and admin services on unused ports, log in with a test admin, run one system evaluation from the admin page, and verify visible text contains:

```text
解释覆盖率 100% · 解释来源通过
```

Clean up any services started for this validation and confirm their ports are closed.

---

## Self-Review Checklist

- Spec coverage: covered report generation, report-level source pool, evaluation metrics, storage normalization, admin API contract, admin UI display, project documentation, and verification.
- Placeholder scan: no unresolved placeholder steps are present.
- Type consistency: field names are consistent across Python and TypeScript: `rag_explanation_coverage_passed`, `rag_explanation_coverage_ratio`, `missing_explanation_references`, `explanation_source_items`.
- Scope control: this plan does not add vector retrieval, LLM rewriting, database migrations, or student UI redesign.
- User instruction: commit steps are omitted because the user has not explicitly asked for a git commit.
