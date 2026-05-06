# RAG 逐条反馈来源覆盖设计

## 目标

把当前“整份报告有来源引用”的 RAG 审计能力，推进到“每条反馈解释都有明确来源引用”。系统应能证明每条优势反馈、推理问题反馈和 LLM reasoning feedback 都来自病例、rubric 或证据来源，而不是无依据文本。

## 当前事实

- `feedback_node()` 已生成 `strengths`、`reasoning_errors`、`llm_reasoning_feedback`、`source_references` 与 `source_reference_items`。
- `source_reference_items` 当前是整份报告级来源池，包含 `case:`、`source:`、`rubric:`、`evidence:` 等引用。
- `EvaluationResult` 当前已检查：报告必须有结构化来源，且 `missed_items` 中每个漏项必须有对应 `rubric:{case_id}_rubric.item.{item_id}` 来源。
- 管理端系统评测详情已展示 RAG 引用覆盖、rubric 覆盖率、来源条数、来源类型和缺失 rubric 引用。

## 问题

报告级来源池只能证明“这份报告总体有来源”，不能证明“这一句反馈为什么出现”。例如“你没有追问疼痛转移特点”应明确绑定到 `rubric:appendicitis_001_rubric.item.ht_migration`，否则教师无法逐条审计反馈依据，评测也无法拦截无来源解释。

## 范围

本小单元只做结构化归因与评测，不接入向量数据库，不改变评分规则，不改变医学事实生成逻辑。

纳入范围：

1. 后端报告新增结构化解释来源项。
2. 系统评测新增逐条解释来源覆盖指标。
3. 评测结果持久化兼容新增字段。
4. 管理端系统评测详情展示解释覆盖率和缺失解释来源。
5. 项目开发文档同步当前实现状态。

不纳入范围：

1. ChromaDB、pgvector 或 embedding 检索。
2. 用 LLM 改写反馈内容。
3. 对旧评测数据做数据库迁移。
4. 重构学生端报告 UI。

## 数据结构

报告新增字段：`explanation_source_items`。

每条解释来源项结构：

```json
{
  "kind": "strength",
  "text": "追问疼痛部位及转移特征：已完成。",
  "rubric_item_id": "ht_migration",
  "source_references": ["rubric:appendicitis_001_rubric.item.ht_migration"]
}
```

`kind` 取值：

- `strength`：来自已得分 rubric item 的优势反馈。
- `reasoning_error`：来自 `differential_diagnosis` 或 `reasoning` 维度未满分 item 的推理问题反馈。
- `llm_reasoning_feedback`：来自带 `rationale` 的 rubric item 结构化反馈。

`source_references` 第一阶段只要求包含对应 rubric 引用。若后续要细化证据级覆盖，可在同一数组追加 `evidence:` 引用。

## 生成规则

在 `feedback_node()` 中继续保留现有文本字段：

- `strengths`
- `reasoning_errors`
- `llm_reasoning_feedback`

同时生成 `explanation_source_items`：

1. 每个 `score > 0` 的 rubric item 生成一条 `strength` 解释项。
2. 每个 `dimension_id` 属于 `differential_diagnosis` 或 `reasoning` 且未满分的 rubric item 生成一条 `reasoning_error` 解释项。
3. 每个带 `rationale` 的 rubric item 生成一条 `llm_reasoning_feedback` 解释项。
4. 每条解释项必须带 `rubric_item_id`。
5. 每条解释项必须带 `rubric:{case_id}_rubric.item.{rubric_item_id}` 来源。

## 评测规则

`EvaluationResult` 新增字段：

- `rag_explanation_coverage_passed: bool`
- `rag_explanation_coverage_ratio: float`
- `missing_explanation_references: list[str]`

计算方式：

1. 如果报告没有 `explanation_source_items`，且存在 `strengths`、`reasoning_errors` 或 `llm_reasoning_feedback`，解释覆盖失败。
2. 如果 `explanation_source_items` 为空，且报告没有任何解释文本，则解释覆盖率为 `1.0`。
3. 对每条 `explanation_source_items`：
   - 必须是 dict；
   - `rubric_item_id` 必须是非空字符串；
   - `source_references` 必须包含 `rubric:{case_id}_rubric.item.{rubric_item_id}`；
   - 该 rubric 引用必须存在于报告级 `source_reference_items` 的 `reference` 集合中。
4. 缺失项写入 `missing_explanation_references`，格式为 `explanation:{kind}:{rubric_item_id}`。
5. `rag_explanation_coverage_ratio = 已通过解释项数量 / 解释项总数`。
6. 单病例 `passed` 必须同时满足现有 RAG 来源覆盖和解释来源覆盖。

## 管理端展示

系统评测详情中，在现有 RAG 行后追加解释覆盖信息：

```text
解释覆盖率 100% · 解释来源通过
```

若存在缺失项，展示：

```text
缺失解释来源：explanation:reasoning_error:rs_exclude
```

## 测试策略

按 TDD 执行：

1. 后端评测红灯：报告有解释文本但没有 `explanation_source_items` 时，评测失败。
2. 后端评测红灯：解释项有 `rubric_item_id`，但 `source_references` 缺对应 `rubric:` 时，评测失败。
3. 后端评测红灯：解释项引用的 `rubric:` 不在报告级 `source_reference_items` 中时，评测失败。
4. 后端绿灯：标准阑尾炎路径解释覆盖率为 `1.0`，缺失列表为空。
5. 持久化测试：新字段可保存、读取；旧评测 JSON 读取时补默认值。
6. 管理 API 测试：评测详情和运行评测响应包含新字段。
7. 管理端类型检查：`EvaluationCaseResult` 增加新字段，导出 JSON 保留新字段。

## 验收标准

- 标准评测路径通过，且显示解释覆盖率 `100%`。
- 构造无解释来源的假报告时，单病例评测失败。
- 构造解释来源与报告级来源池不一致的假报告时，单病例评测失败。
- 后端完整测试通过。
- 管理端 TypeScript 类型检查通过。
- 管理端系统评测详情能看到解释覆盖率和缺失解释来源。

## 后续扩展

后续可把 `source_references` 从仅 rubric 引用扩展到 evidence 引用，使系统进一步证明每条反馈不只是来自评分项，还能追溯到具体病例事实、查体或辅助检查证据。
