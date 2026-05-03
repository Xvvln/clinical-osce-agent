# LLM Skill 候选生成器接口先行设计

## 背景

当前 `TrainingSkillCandidateService` 已能从训练洞察中筛选高频漏项，并生成候选 Skill，后续会经过回归门禁和管理员审核后启用。现有实现仍是模板式生成：`reasoning_core` 使用固定标题和固定策略，其他漏项使用通用固定策略。这能支撑最小闭环，但不符合项目目标中“从日志中生成教学 Skill 候选，经审核后启用”的智能生成形态。

本设计聚焦一个小单元：不直接接真实外部模型，先把候选生成重构为可注入 generator（生成器）接口。测试中用 fake generator 模拟 LLM 输出，生产默认继续使用模板 generator，保证稳定性和可复现性。

## 目标

- 让 Skill 候选生成链路具备“由 LLM generator 生成候选”的代码结构。
- 保持当前默认模板输出不变，避免影响现有管理端候选审核、回归门禁和启用流程。
- 通过测试证明 `TrainingSkillCandidateService` 会把训练洞察上下文传给注入的 generator，并返回 generator 生成的候选。
- 为后续接入 Vertex Gemini 或 Claude API 生成结构化 Skill JSON 留出明确边界。

## 非目标

- 不在本小单元中调用真实 LLM API。
- 不新增环境变量、模型配置、代理配置或 SDK 依赖。
- 不修改管理端 API 路由、候选存储、审核启用和回归门禁流程。
- 不改变候选 Skill 当前字段结构。

## 方案

### 架构

将 `TrainingSkillCandidateService` 拆成两层职责：

1. `TrainingSkillCandidateService` 负责从 insights 中筛选满足 `support_count >= min_count` 的高频漏项，并构造生成上下文。
2. `TrainingSkillCandidateGenerator` 负责基于上下文生成候选 Skill。

默认实现为 `TemplateTrainingSkillCandidateGenerator`，复用当前 `_build_candidate()` 的模板逻辑。测试可注入 fake generator，后续真实 LLM generator 也使用同一接口。

### 数据流

输入仍是现有 `insights`：

- `report_count`
- `frequent_missed_items[]`
- `frequent_learning_recommendations[]`

`TrainingSkillCandidateService.propose_candidates()` 执行流程：

1. 从 `insights.frequent_learning_recommendations` 提取 `related_recommendations`。
2. 遍历 `insights.frequent_missed_items`。
3. 跳过 `count < min_count` 的漏项。
4. 为每个高频漏项构造上下文：
   - `item_id`
   - `support_count`
   - `case_ids`
   - `source_report_count`
   - `related_recommendations`
5. 调用 generator 生成候选。
6. 返回候选列表，继续交给现有 regression gate 和管理员审核。

### 接口契约

新增可注入接口，使用 Python Protocol 或等价 callable 契约：

```python
class TrainingSkillCandidateGenerator(Protocol):
    def generate_candidate(self, context: TrainingSkillCandidateContext) -> dict[str, Any]:
        ...
```

新增 `TrainingSkillCandidateContext`，可用 dataclass 表达：

```python
@dataclass(frozen=True)
class TrainingSkillCandidateContext:
    item_id: str
    support_count: int
    case_ids: list[str]
    source_report_count: int
    related_recommendations: list[str]
```

默认模板 generator 输出字段保持当前候选结构：

- `candidate_id`
- `trigger_item_id`
- `title`
- `description`
- `suggested_strategy`
- `status`
- `source_report_count`
- `support_count`
- `related_recommendations`

### 安全边界

本小单元不改变安全边界。候选生成后仍会经过现有 `TrainingSkillRegressionGate`：

- 拦截候选文本中的治疗方案、用药剂量、手术方案等禁用词。
- 依赖现有系统评测结果决定是否进入 `ready_for_review`。
- 管理员仍是最终审核者。

后续接真实 LLM 时，prompt 必须明确：只能生成教学策略，不得生成真实诊疗建议、用药剂量、治疗方案或病例标准答案。

## 测试计划

采用 TDD：

1. 在 `services/api/tests/test_training_skill_candidate_service.py` 先新增红灯测试：
   - 定义 fake generator；
   - 调用 `TrainingSkillCandidateService(generator=fake_generator).propose_candidates(insights, min_count=2)`；
   - 断言 fake generator 收到的上下文包含 `reasoning_core`、`support_count`、`case_ids`、`source_report_count`、`related_recommendations`；
   - 断言 service 返回 fake generator 生成的候选。
2. 保留并跑通现有模板测试：默认构造 `TrainingSkillCandidateService()` 时输出仍与当前一致。
3. 跑相关后端测试：
   - `pytest services/api/tests/test_training_skill_candidate_service.py -q`
   - 如影响 main 流程，再跑 `pytest services/api/tests/test_admin_api.py -q`

## 文档同步

实现后同步 `项目开发文档.md`：

- 将当前 Skill 候选生成状态从“模板生成”更新为“支持可注入 LLM generator，默认仍使用模板”。
- 明确真实 Vertex Gemini / Claude API generator 仍是后续小单元。
- 保留“候选必须经回归门禁和管理员审核后启用”的受控进化边界。
