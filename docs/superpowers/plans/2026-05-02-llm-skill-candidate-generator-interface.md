# LLM Skill Candidate Generator Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将模板式 Skill 候选生成升级为可注入 LLM generator 的接口结构，同时保持默认模板输出和现有审核/回归门禁流程不变。

**Architecture:** `TrainingSkillCandidateService` 继续负责从 insights 中筛选高频漏项，并把每个高频漏项封装为 `TrainingSkillCandidateContext`。实际候选内容由可注入 `TrainingSkillCandidateGenerator` 生成；生产默认使用 `TemplateTrainingSkillCandidateGenerator` 复用现有模板，测试注入 fake generator 验证上下文传递与返回值。

**Tech Stack:** Python 3.11+、dataclasses、typing.Protocol、pytest、FastAPI 现有服务层。

---

## File Structure

- Modify: `services/api/tests/test_training_skill_candidate_service.py`
  - 新增 fake generator 红灯测试。
  - 保留现有默认模板输出测试，确保行为不变。
- Modify: `services/api/app/services/training_skill_candidate_service.py`
  - 新增 `TrainingSkillCandidateContext` dataclass。
  - 新增 `TrainingSkillCandidateGenerator` Protocol。
  - 新增 `TemplateTrainingSkillCandidateGenerator` 默认实现。
  - 修改 `TrainingSkillCandidateService` 支持注入 generator。
- Modify: `项目开发文档.md`
  - 同步 Step 8/受控进化状态：候选生成已具备可注入 LLM generator 接口，默认仍走模板。

## Implementation Notes

- 不新增真实 LLM API 调用。
- 不新增环境变量、模型配置、SDK 依赖或网络请求。
- 不修改 `main.py`、候选 store、regression gate、admin API。
- 不创建 git commit，除非用户明确要求。
- Python 命令使用 conda `agent` 环境。

---

### Task 1: Add failing fake-generator test

**Files:**
- Modify: `services/api/tests/test_training_skill_candidate_service.py`
- Test: `services/api/tests/test_training_skill_candidate_service.py`

- [ ] **Step 1: Update imports for the future context type**

Change the import at the top of `services/api/tests/test_training_skill_candidate_service.py` from:

```python
from app.services.training_skill_candidate_service import TrainingSkillCandidateService
```

to:

```python
from app.services.training_skill_candidate_service import (
    TrainingSkillCandidateContext,
    TrainingSkillCandidateService,
)
```

This will fail before implementation because `TrainingSkillCandidateContext` does not exist yet.

- [ ] **Step 2: Add a fake generator test before the existing template behavior test**

Insert this test above `test_training_skill_candidate_service_proposes_reasoning_candidate_from_frequent_missed_item`:

```python
def test_training_skill_candidate_service_uses_injected_generator_for_high_frequency_items() -> None:
    captured_contexts: list[TrainingSkillCandidateContext] = []

    class FakeTrainingSkillCandidateGenerator:
        def generate_candidate(self, context: TrainingSkillCandidateContext) -> dict[str, object]:
            captured_contexts.append(context)
            return {
                "candidate_id": f"llm_candidate_{context.item_id}",
                "trigger_item_id": context.item_id,
                "title": "LLM 生成的推理训练 Skill",
                "description": f"LLM 基于 {context.support_count} 次漏项生成。",
                "suggested_strategy": "提交诊断前，请先按证据链复核主要诊断和鉴别诊断。",
                "status": "draft",
                "source_report_count": context.source_report_count,
                "support_count": context.support_count,
                "related_recommendations": context.related_recommendations,
            }

    insights = {
        "session_count": 3,
        "report_count": 3,
        "frequent_missed_items": [
            {
                "item_id": "reasoning_core",
                "count": 2,
                "case_ids": ["appendicitis_001", "pneumonia_001"],
            },
            {
                "item_id": "ht_location",
                "count": 1,
                "case_ids": ["appendicitis_001"],
            },
        ],
        "frequent_learning_recommendations": [
            {
                "reference": "rubric:appendicitis_001_rubric.item.reasoning_core",
                "title": "推理链覆盖关键证据并能自圆其说",
                "count": 2,
            },
            {
                "reference": "knowledge:appendicitis_001.rp_03",
                "title": "急性阑尾炎诊断依据",
                "count": 1,
            },
        ],
    }

    candidates = TrainingSkillCandidateService(
        generator=FakeTrainingSkillCandidateGenerator(),
    ).propose_candidates(insights, min_count=2)

    assert captured_contexts == [
        TrainingSkillCandidateContext(
            item_id="reasoning_core",
            support_count=2,
            case_ids=["appendicitis_001", "pneumonia_001"],
            source_report_count=3,
            related_recommendations=[
                "rubric:appendicitis_001_rubric.item.reasoning_core",
                "knowledge:appendicitis_001.rp_03",
            ],
        )
    ]
    assert candidates == [
        {
            "candidate_id": "llm_candidate_reasoning_core",
            "trigger_item_id": "reasoning_core",
            "title": "LLM 生成的推理训练 Skill",
            "description": "LLM 基于 2 次漏项生成。",
            "suggested_strategy": "提交诊断前，请先按证据链复核主要诊断和鉴别诊断。",
            "status": "draft",
            "source_report_count": 3,
            "support_count": 2,
            "related_recommendations": [
                "rubric:appendicitis_001_rubric.item.reasoning_core",
                "knowledge:appendicitis_001.rp_03",
            ],
        }
    ]
```

- [ ] **Step 3: Run the new test to verify RED**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" pytest "clinical-osce-agent/services/api/tests/test_training_skill_candidate_service.py::test_training_skill_candidate_service_uses_injected_generator_for_high_frequency_items" -q
```

Expected: FAIL during import with an error equivalent to:

```text
ImportError: cannot import name 'TrainingSkillCandidateContext'
```

If the test fails for a syntax error, fix the test and re-run until it fails because the production interface is missing.

---

### Task 2: Implement injectable generator interface

**Files:**
- Modify: `services/api/app/services/training_skill_candidate_service.py`
- Test: `services/api/tests/test_training_skill_candidate_service.py`

- [ ] **Step 1: Replace the service module with the interface-based implementation**

Update `services/api/app/services/training_skill_candidate_service.py` to this content:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class TrainingSkillCandidateContext:
    item_id: str
    support_count: int
    case_ids: list[str]
    source_report_count: int
    related_recommendations: list[str]


class TrainingSkillCandidateGenerator(Protocol):
    def generate_candidate(self, context: TrainingSkillCandidateContext) -> dict[str, Any]:
        ...


class TemplateTrainingSkillCandidateGenerator:
    def generate_candidate(self, context: TrainingSkillCandidateContext) -> dict[str, Any]:
        return _build_candidate(
            item_id=context.item_id,
            support_count=context.support_count,
            case_ids=context.case_ids,
            source_report_count=context.source_report_count,
            related_recommendations=context.related_recommendations,
        )


class TrainingSkillCandidateService:
    def __init__(self, generator: TrainingSkillCandidateGenerator | None = None) -> None:
        self._generator = generator or TemplateTrainingSkillCandidateGenerator()

    def propose_candidates(self, insights: dict[str, Any], min_count: int = 2) -> list[dict[str, Any]]:
        source_report_count = insights.get("report_count", 0)
        related_recommendations = [
            recommendation["reference"]
            for recommendation in insights.get("frequent_learning_recommendations", [])
        ]
        candidates: list[dict[str, Any]] = []

        for missed_item in insights.get("frequent_missed_items", []):
            support_count = missed_item["count"]
            if support_count < min_count:
                continue
            context = TrainingSkillCandidateContext(
                item_id=missed_item["item_id"],
                support_count=support_count,
                case_ids=missed_item["case_ids"],
                source_report_count=source_report_count,
                related_recommendations=related_recommendations,
            )
            candidates.append(self._generator.generate_candidate(context))
        return candidates


def _build_candidate(
    item_id: str,
    support_count: int,
    case_ids: list[str],
    source_report_count: int,
    related_recommendations: list[str],
) -> dict[str, Any]:
    if item_id == "reasoning_core":
        return {
            "candidate_id": f"skill_candidate_{item_id}",
            "trigger_item_id": item_id,
            "title": "临床推理链纠偏提示",
            "description": _candidate_description(item_id, support_count, case_ids, source_report_count),
            "suggested_strategy": "在学生提交诊断前，提示其按症状、体征、辅助检查和鉴别诊断组织证据链，但不透露标准诊断或病例隐藏事实。",
            "status": "draft",
            "source_report_count": source_report_count,
            "support_count": support_count,
            "related_recommendations": related_recommendations,
        }
    return {
        "candidate_id": f"skill_candidate_{item_id}",
        "trigger_item_id": item_id,
        "title": "OSCE 漏项纠偏提示",
        "description": _candidate_description(item_id, support_count, case_ids, source_report_count),
        "suggested_strategy": "在不透露标准答案的前提下，提醒学生回顾本轮训练中反复遗漏的问诊、查体、检查或推理要点。",
        "status": "draft",
        "source_report_count": source_report_count,
        "support_count": support_count,
        "related_recommendations": related_recommendations,
    }


def _candidate_description(item_id: str, support_count: int, case_ids: list[str], source_report_count: int) -> str:
    return f"{source_report_count} 份报告中有 {support_count} 次漏掉 {item_id}，涉及病例：{'、'.join(case_ids)}。"


training_skill_candidate_service = TrainingSkillCandidateService()
```

- [ ] **Step 2: Run the fake-generator test to verify GREEN for injected generation**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" pytest "clinical-osce-agent/services/api/tests/test_training_skill_candidate_service.py::test_training_skill_candidate_service_uses_injected_generator_for_high_frequency_items" -q
```

Expected:

```text
1 passed
```

- [ ] **Step 3: Run the full candidate service test file to verify default template behavior stayed green**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" pytest "clinical-osce-agent/services/api/tests/test_training_skill_candidate_service.py" -q
```

Expected:

```text
3 passed
```

---

### Task 3: Verify admin integration still uses the default service safely

**Files:**
- Modify: none unless a test fails and root cause points to a required compatibility fix.
- Test: `services/api/tests/test_admin_api.py`

- [ ] **Step 1: Run the admin API tests that cover candidate generation/review flow**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" pytest "clinical-osce-agent/services/api/tests/test_admin_api.py" -q
```

Expected: all tests in `test_admin_api.py` pass. At the time this plan was written, this file already covered candidate list/generate/approve/reject paths and should continue to pass because `TrainingSkillCandidateService()` still defaults to the template generator.

- [ ] **Step 2: If the admin API test fails, diagnose before changing code**

Use the failing assertion and stack trace to identify whether:

```text
- the service constructor signature broke a monkeypatch or import,
- the default generator output changed,
- candidate dict fields changed,
- or the test relies on exact ordering/content.
```

Only change production code if the root cause is a compatibility regression. Do not alter candidate field names, admin route behavior, regression gate behavior, or store schemas in this task.

---

### Task 4: Update project documentation

**Files:**
- Modify: `项目开发文档.md`

- [ ] **Step 1: Update Step 8 current status wording**

In `项目开发文档.md`, locate Step 8 around the section headed:

```markdown
## Step 8：实现 GA 式受控进化
```

Update the implementation/current-status wording in that area so it states these facts:

```markdown
当前 Skill 候选生成已从纯模板服务升级为可注入 `TrainingSkillCandidateGenerator` 的接口结构：服务层仍负责从训练洞察中筛选高频漏项，默认 `TemplateTrainingSkillCandidateGenerator` 保持既有模板输出；测试可注入 fake generator 模拟 LLM 输出。真实 Vertex Gemini / Claude API generator 仍作为后续小单元接入，候选仍必须经过回归门禁与管理员审核后才能启用。
```

If Step 8 does not already have a current-status paragraph, add the paragraph immediately after Step 8 outputs/验收标准附近的 current implementation notes, keeping the existing document style.

- [ ] **Step 2: Add an execution record near existing 2026-05-02 records**

In the execution records section near existing `2026-05-02` entries, add:

```markdown
### 2026-05-02 · Step 8 LLM Skill 候选生成器接口先行

- 已完成：
  - `services/api/tests/test_training_skill_candidate_service.py` 新增 fake generator 测试，锁定 `TrainingSkillCandidateService` 会把高频漏项、病例列表、来源报告数和学习建议引用传给可注入生成器；
  - `services/api/app/services/training_skill_candidate_service.py` 新增 `TrainingSkillCandidateContext`、`TrainingSkillCandidateGenerator` 与 `TemplateTrainingSkillCandidateGenerator`，生产默认仍保持既有模板候选输出；
  - Skill 候选生成链路已具备后续接入真实 LLM generator 的接口边界，但本小单元不调用外部模型。
- 与开发文档对齐情况：
  - 对齐 Step 8 “从训练日志中生成教学 Skill 候选，经审核后启用”的受控进化方向；
  - 保持“LLM 生成候选、回归门禁拦截、管理员最终审核”的安全边界。
- 当前边界：
  - 当前默认仍使用模板 generator，不新增 Vertex Gemini、Claude API、环境变量或网络请求；
  - 真实大模型生成、prompt 契约、模型错误处理和成本控制仍延后到下一小单元。
- 验证方式：
  - `source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" pytest "clinical-osce-agent/services/api/tests/test_training_skill_candidate_service.py" -q` → 通过；
  - `source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" pytest "clinical-osce-agent/services/api/tests/test_admin_api.py" -q` → 通过。
- 是否已同步本文档：已同步。
```

After running verification, update “通过” to the exact observed pass count if desired, for example `3 passed`.

---

### Task 5: Final verification and diff check

**Files:**
- Verify: `services/api/tests/test_training_skill_candidate_service.py`
- Verify: `services/api/tests/test_admin_api.py`
- Verify: `services/api/app/services/training_skill_candidate_service.py`
- Verify: `项目开发文档.md`

- [ ] **Step 1: Run backend candidate-service and admin API tests together**

Run:

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="clinical-osce-agent/services/api" pytest "clinical-osce-agent/services/api/tests/test_training_skill_candidate_service.py" "clinical-osce-agent/services/api/tests/test_admin_api.py" -q
```

Expected:

```text
all selected tests pass with 0 failures
```

Record the exact pass count from pytest output in the final report.

- [ ] **Step 2: Run whitespace diff check for touched files**

Run:

```bash
git -C "clinical-osce-agent" diff --check -- "services/api/app/services/training_skill_candidate_service.py" "services/api/tests/test_training_skill_candidate_service.py" "项目开发文档.md"
```

Expected:

```text
no whitespace errors
```

Git may print LF/CRLF warnings on Windows; those are not whitespace errors.

- [ ] **Step 3: Inspect the diff for scope control**

Run:

```bash
git -C "clinical-osce-agent" diff -- "services/api/app/services/training_skill_candidate_service.py" "services/api/tests/test_training_skill_candidate_service.py" "项目开发文档.md"
```

Confirm the diff only contains:

```text
- fake generator test and import update,
- service generator interface/context/template refactor,
- project documentation status/execution record.
```

Do not include unrelated frontend, admin route, store schema, regression gate, or external model configuration changes.

- [ ] **Step 4: Final report**

Report:

```text
- What changed in each touched file.
- RED result: the fake generator test failed before implementation because TrainingSkillCandidateContext was missing.
- GREEN result: exact pytest pass count for candidate service tests.
- Integration result: exact pytest pass count for admin API tests.
- diff --check result.
- Potential issues: production still uses template generator; real LLM provider/prompt/cost/error handling remains future work.
- Suggested next tests: fake generator returning unsafe terms should still be blocked by regression gate; real Vertex/Claude generator should validate JSON schema before saving candidates.
```

Do not say “complete” unless the verification commands in this task have been run in the current implementation session and passed.
