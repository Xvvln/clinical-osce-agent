# 管理端系统评测失败复盘摘要设计

## 背景

`clinical-osce-agent` 管理端已能展示系统评测批次、通过率/失败率摘要、评测详情，并支持导出选中批次 JSON。`项目开发文档.md` Step 10 的验收标准还要求“有失败案例和改进记录”，当前页面只逐条展示评测用例的实际分与期望分，缺少教师视角可快速阅读的失败复盘摘要。

本设计聚焦一个最小可交付单元：在不新增后端接口、不引入新依赖的前提下，基于已加载的 `selectedEvaluation.results` 派生并展示失败复盘摘要。

## 目标

- 管理端选中系统评测批次后，能看到该批次失败复盘摘要。
- 失败复盘摘要能帮助教师或演示者快速回答：失败了几例、总分差多少、是否触发禁用词违规、哪条用例最慢。
- 每条失败用例要显示 `session_id`、实际/期望分、分差、耗时和禁用词违规。
- 全部通过时显示明确空态：“本批次暂无失败案例”。

## 非目标

- 不新增 `/api/admin/evaluations/{batch_id}` 的响应字段。
- 不新增数据库表、持久化改进建议或服务端分析任务。
- 不做趋势图、跨批次对比、PDF/CSV 报告或异步评测编排。
- 不改变现有系统评测运行逻辑。

## 方案

### 架构

采用前端派生方案。管理端页面已经持有 `selectedEvaluation: EvaluationBatchDetail | null`，其中 `results` 包含 `passed`、`actual_total_score`、`expected_total_score`、`forbidden_term_violations`、`duration_ms`、`session_id`。新增纯函数 `buildEvaluationFailureReview(selectedEvaluation)` 从这些字段派生展示模型，再由系统评测详情卡渲染。

该方案只修改管理端结构测试、管理端页面和项目开发文档，符合“超过 3 个文件需拆小单元”的限制。

### 数据模型

新增类型 `EvaluationFailureReview`：

- `failedCaseCount: number`
- `scoreGapTotal: number`
- `forbiddenViolationCount: number`
- `slowestDurationMs: number`
- `failedResults: readonly EvaluationFailureResult[]`

新增类型 `EvaluationFailureResult`：

- `session_id: string`
- `actual_total_score: number`
- `expected_total_score: number`
- `score_gap: number`
- `duration_ms: number`
- `forbidden_term_violations: readonly string[]`

`score_gap` 使用 `Math.max(expected_total_score - actual_total_score, 0)`，避免超额得分时出现负分差。

### UI

在系统评测详情卡中，现有批次标题、导出按钮和“通过 X/Y 例 · 耗时 Z ms”之后新增“失败复盘摘要”区块。

全通过时：

- 展示“本批次暂无失败案例”。

存在失败时：

- 展示四个小指标：失败用例、总分差、禁用词违规、最慢用例。
- 下方列出失败用例详情：`session_id`、实际/期望分、分差、耗时、禁用词违规。
- 禁用词为空时显示“无禁用词违规”。

### 错误处理

该功能不新增网络请求，因此不新增 API 错误状态。若 `selectedEvaluation` 为 `null`，不渲染详情卡和失败复盘摘要。若 `results` 为空，失败数为 0 并显示通过空态。

### 测试

采用 TDD：

1. 先在 `apps/admin/admin-skill-review.test.mjs` 新增结构测试红灯，锁定：
   - `type EvaluationFailureReview = Readonly<{`；
   - `type EvaluationFailureResult = Readonly<{`；
   - `function buildEvaluationFailureReview(`；
   - `const evaluationFailureReview = selectedEvaluation ? buildEvaluationFailureReview(selectedEvaluation) : null`；
   - 页面文本包含“失败复盘摘要”“失败用例”“总分差”“禁用词违规”“最慢用例”“本批次暂无失败案例”；
   - 失败条目显示 `score_gap` 和 `forbidden_term_violations`。
2. 实现最小前端逻辑。
3. 运行管理端结构测试、typecheck、build 和 diff check。
4. 做一次浏览器验证：运行系统评测后选中批次，确认失败复盘区块可见且控制台无 error。

## 文档同步

实现后同步 `项目开发文档.md`：

- Step 10 当前进展增加“系统评测失败复盘摘要已落地”。
- 将“失败案例和改进记录”标记为已具备最小复盘能力。
- 明确趋势分析、跨批次报告和持久化改进记录仍延后。
