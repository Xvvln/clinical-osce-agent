import { strict as assert } from "node:assert";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

const pageUrl = new URL("./src/app/v2/page.tsx", import.meta.url);
const dashboardUrl = new URL("./src/app/v2/admin-v2-dashboard.tsx", import.meta.url);
const oldPageUrl = new URL("./src/app/page.tsx", import.meta.url);
const docsUrl = new URL("../../docs/admin-v2-dashboard.md", import.meta.url);

const pageSource = existsSync(pageUrl) ? readFileSync(pageUrl, "utf8") : "";
const dashboardSource = existsSync(dashboardUrl) ? readFileSync(dashboardUrl, "utf8") : "";
const oldPageSource = existsSync(oldPageUrl) ? readFileSync(oldPageUrl, "utf8") : "";
const docsSource = existsSync(docsUrl) ? readFileSync(docsUrl, "utf8") : "";

function sourceBetween(source, startToken, endToken) {
  const start = source.indexOf(startToken);
  const end = source.indexOf(endToken, start + startToken.length);
  assert.notEqual(start, -1, `${startToken} should exist`);
  assert.notEqual(end, -1, `${endToken} should exist after ${startToken}`);
  return source.slice(start, end);
}

test("admin v2 replaces the root admin entry while keeping the /v2 route available", () => {
  assert.ok(existsSync(pageUrl), "v2 page should exist");
  assert.ok(existsSync(dashboardUrl), "v2 dashboard client should exist");
  assert.match(pageSource, /AdminV2Dashboard/);
  assert.doesNotMatch(pageSource, /from "\.\.\/page"/);
  assert.doesNotMatch(dashboardSource, /from "\.\.\/page"/);
  assert.match(oldPageSource, /AdminV2Dashboard/);
  assert.match(oldPageSource, /from "\.\/v2\/admin-v2-dashboard"/);
  assert.doesNotMatch(dashboardSource, /旧版/);
  assert.doesNotMatch(dashboardSource, /href="\/"/);
});

test("admin v2 documents the Dashboard Blocks adaptation and migration boundary", () => {
  assert.ok(existsSync(docsUrl), "admin v2 design document should exist");
  assert.match(docsSource, /shadcn\/ui Dashboard Blocks/);
  assert.match(docsSource, /根路径 `\/` 已切换为 v2 工作台/);
  assert.match(docsSource, /`\/v2` 继续保留为兼容入口/);
  assert.match(docsSource, /技术 ID 和原始 JSON 不作为主界面阅读内容/);
  assert.match(docsSource, /http:\/\/127\.0\.0\.1:3001/);
});

test("admin v2 exposes the core management modules with clean Chinese labels", () => {
  for (const label of ["概览", "教学资源", "训练管理", "教学洞察", "Skill 进化", "系统评测", "调用日志"]) {
    assert.match(dashboardSource, new RegExp(label), `v2 dashboard should expose ${label}`);
  }

  for (const label of ["训练 Session", "评分报告", "候选 Skill", "模型成功率", "API 成功率和最近错误"]) {
    assert.match(dashboardSource, new RegExp(label), `v2 dashboard should show ${label}`);
  }

  assert.match(dashboardSource, /管理员登录/);
  assert.doesNotMatch(dashboardSource, /Dashboard Blocks Adaptation/);
  assert.doesNotMatch(dashboardSource, /shadcn\/ui Dashboard Blocks 布局模式的新工作台/);
  assert.doesNotMatch(dashboardSource, /把训练、资源、Skill、评测和模型日志重组为表格化管理视图/);
});

test("admin v2 reads the existing backend APIs without adding a new backend contract", () => {
  for (const endpoint of [
    "/api/admin/model-config",
    "/api/admin/model-api-logs?limit=60",
    "/api/admin/sessions?limit=20",
    "/api/admin/reports?limit=20",
    "/api/admin/sessions/${sessionId}/report",
    "/api/admin/sessions/${sessionId}/events",
    "/api/admin/evolution/candidates?limit=20&review_status=all",
    "/api/admin/evolution/candidates/${candidateId}",
    "/api/admin/evolution/candidates/${candidateId}/events",
    "/api/admin/evolution/approve",
    "/api/admin/evolution/reject",
    "/api/admin/evolution/settings",
    "/api/admin/evaluations?limit=20",
    "/api/admin/evaluations/${batchId}",
    "/api/cases",
    "/api/admin/cases/${encodeURIComponent(caseId)}/raw",
    "/api/admin/sources",
    "/api/admin/rag/documents",
    "/api/admin/rag/knowledge",
    "/api/admin/rag/documents",
    "/api/admin/retrieval-eval",
    "/api/admin/teaching-focus/patterns",
    "/api/admin/procedure-simulation-audits?limit=20",
    "/api/admin/evolution/events?limit=20",
    "/api/admin/rag/documents/${encodeURIComponent(documentId)}/enabled",
    "/api/admin/insights",
    "/api/admin/evolution/skill-effects",
    "/api/admin/evals/run",
    "/api/admin/evolution/candidates/generate",
    "/api/admin/rubrics/${rubricId}",
    "/api/admin/rubrics/${rubricId}/items/${itemId}",
  ]) {
    assert.match(dashboardSource, new RegExp(endpoint.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `v2 dashboard should use ${endpoint}`);
  }
});

test("admin v2 keeps necessary management actions but avoids raw debug surfaces", () => {
  for (const label of [
    "读取报告",
    "读取日志",
    "查看评测详情",
    "查看详情",
    "批准并启用",
    "拒绝候选",
    "开启自动应用",
    "关闭自动应用",
    "启用文档",
    "停用文档",
    "查看内容",
    "编辑病例",
    "查看 Rubric",
    "上传文档",
    "保存基础信息",
    "保存评分项",
  ]) {
    assert.match(dashboardSource, new RegExp(label), `v2 dashboard should provide ${label}`);
  }

  for (const forbidden of ["导出当前 Session 页 JSON", "导出当前候选页 JSON", "原始 JSON", "技术 ID 和原始 JSON"]) {
    assert.doesNotMatch(dashboardSource, new RegExp(forbidden.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});

test("admin v2 keeps the main workspace clean and moves refresh into the sidebar", () => {
  assert.doesNotMatch(dashboardSource, /<header className=/);
  assert.doesNotMatch(dashboardSource, /临境 OSCE 管理工作台/);
  assert.doesNotMatch(dashboardSource, /管理员已登录/);
  assert.match(dashboardSource, /aria-label="刷新管理数据"/);
});

test("admin v2 explains evaluation, skill details, knowledge content, and API failure details", () => {
  for (const label of [
    "系统质检说明",
    "RAG 来源覆盖",
    "报告兼容",
    "Skill 闭环",
    "自动回归测试",
    "完整 Skill 内容",
    "适用时机",
    "成功指标",
    "来源报告",
    "文档内容",
    "知识片段",
    "调用人",
    "失败详情",
    "最近 60 条",
    "RAG 检索评测",
    "历史模拟审计",
    "全局审核审计",
    "动态教学重点",
  ]) {
    assert.match(dashboardSource, new RegExp(label), `v2 dashboard should explain or show ${label}`);
  }
});

test("admin v2 keeps details in modal surfaces and normalizes unstable backend arrays", () => {
  assert.match(dashboardSource, /function toTextList/);
  assert.match(dashboardSource, /function toInsightDisplayItems/);
  assert.match(dashboardSource, /function getSkillContentText/);
  assert.match(dashboardSource, /toTextList\(selectedCandidate\.applies_when/);
  assert.match(dashboardSource, /toTextList\(selectedCandidate\.success_metrics/);
  assert.match(dashboardSource, /KnowledgeContentModal/);
  assert.match(dashboardSource, /CaseDetailModal/);
  assert.match(dashboardSource, /CaseEditModal/);
  assert.match(dashboardSource, /RubricEditModal/);
  assert.match(dashboardSource, /DocumentUploadPanel/);
  assert.match(dashboardSource, /ProcedureAuditList/);
  assert.match(dashboardSource, /TeachingFocusList/);
  assert.match(dashboardSource, /AuditEventList/);
  assert.match(dashboardSource, /RetrievalEvalPanel/);
  assert.match(dashboardSource, /编辑知识库内容/);
  assert.match(dashboardSource, /保存修改/);
  assert.match(dashboardSource, /onSaveKnowledgeItem/);
  assert.match(dashboardSource, /getAdminCaseRaw/);
  for (const label of ["病人信息", "病史线索", "查体结果", "辅助检查结果", "诊断与推理"]) {
    assert.match(dashboardSource, new RegExp(label), `case detail modal should expose ${label}`);
  }
  assert.doesNotMatch(dashboardSource, /<CardTitle>文档内容<\/CardTitle>/);
  assert.doesNotMatch(dashboardSource, /<CardTitle>病例内容<\/CardTitle>/);
});

test("admin v2 uses a chart component for model API observability", () => {
  for (const label of ["模型调用观测", "调用趋势", "成功失败分布", "用途分布", "Provider 分布", "模型耗时排行"]) {
    assert.match(dashboardSource, new RegExp(label), `model API observability should expose ${label}`);
  }

  for (const chartComponent of ["ResponsiveContainer", "LineChart", "BarChart", "PieChart", "Tooltip"]) {
    assert.match(dashboardSource, new RegExp(chartComponent), `model API charts should use ${chartComponent}`);
  }

  assert.match(dashboardSource, /from "recharts"/);
  assert.match(dashboardSource, /buildModelApiChartData/);
});

test("admin v2 lays out model API charts as balanced responsive cards", () => {
  const modelApiPanelSource = sourceBetween(dashboardSource, "function ModelApiObservabilityPanel", "function ModelApiChartCard");
  assert.match(modelApiPanelSource, /ModelApiChartCard/);
  assert.match(modelApiPanelSource, /grid gap-4 lg:grid-cols-2/);
  assert.match(modelApiPanelSource, /width=\{150\}/);
  assert.match(modelApiPanelSource, /width=\{170\}/);
  assert.doesNotMatch(modelApiPanelSource, /xl:grid-cols-\[1\.15fr_0\.85fr\]/);
  assert.doesNotMatch(modelApiPanelSource, /xl:grid-cols-1/);
  assert.doesNotMatch(modelApiPanelSource, /left: -20/);
  assert.doesNotMatch(modelApiPanelSource, /width=\{82\}/);
  assert.doesNotMatch(modelApiPanelSource, /width=\{96\}/);
});

test("admin v2 renders model API logs as responsive rows instead of a wide table", () => {
  assert.match(dashboardSource, /ModelApiLogList/);
  assert.match(dashboardSource, /日志摘要/);
  assert.match(dashboardSource, /失败详情/);
  assert.match(dashboardSource, /lg:grid-cols-\[minmax\(0,1fr\)_auto\]/);
  assert.match(dashboardSource, /w-full grid-cols-1 gap-2 sm:grid-cols-3 lg:w-auto/);
  assert.doesNotMatch(dashboardSource, /min-w-\[1080px\]/);
  assert.doesNotMatch(dashboardSource, /shrink-0 grid-cols-2/);
});

test("admin v2 only highlights opened knowledge documents and handles sessions without reports", () => {
  assert.match(dashboardSource, /const activeDocumentId = openDocumentId;/);
  assert.doesNotMatch(dashboardSource, /selectedDocumentId \|\| data\.documents\[0\]\?\.document_id/);
  assert.match(dashboardSource, /hasSelectedReport/);
  assert.match(dashboardSource, /暂无报告/);
  assert.match(dashboardSource, /该 Session 还没有生成评分报告/);
});

test("admin v2 renders insight aggregation lists instead of a placeholder-only insight page", () => {
  for (const label of ["近期漏项", "训练模式", "按报告聚合的高频未覆盖项", "按对话过程聚合的训练模式"]) {
    assert.match(dashboardSource, new RegExp(label), `insight page should render ${label}`);
  }
  assert.doesNotMatch(dashboardSource, /高频漏项、教学重点和来源热度已由后端聚合，用于生成候选 Skill 和教师复盘。/);
});

test("admin v2 exposes actionable learning drills for all-user, case, and student analytics", () => {
  for (const label of ["可执行训练任务", "触发", "学生动作", "成功信号"]) {
    assert.match(dashboardSource, new RegExp(label), `learning analytics should expose ${label}`);
  }

  assert.match(dashboardSource, /AdminLearningTrainingDrill/);
  assert.match(dashboardSource, /TrainingDrillList/);
  assert.match(dashboardSource, /training_drills/);
});

test("admin v2 provides a guided case creation flow instead of raw JSON import", () => {
  for (const endpoint of ["/api/admin/cases/validate", "/api/admin/cases/import"]) {
    assert.match(dashboardSource, new RegExp(endpoint.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `v2 dashboard should use ${endpoint}`);
  }

  for (const label of ["新建病例", "病例工坊", "基础信息", "标准化病人", "线索与检查", "评分 Rubric", "导入前预检", "发布病例"]) {
    assert.match(dashboardSource, new RegExp(label), `case creation flow should expose ${label}`);
  }

  assert.match(dashboardSource, /buildCaseCreationPayload/);
  assert.match(dashboardSource, /CaseCreationModal/);
  assert.match(dashboardSource, /generateSequentialCaseId/);
  assert.doesNotMatch(dashboardSource, /generateRandomCaseId/);
  assert.doesNotMatch(dashboardSource, /generateThreeDigitSuffix/);
  assert.match(dashboardSource, /grid-rows-\[auto_minmax\(0,1fr\)_auto\]/);
  assert.match(dashboardSource, /historyFacts:\s*\[createTextRow\(\)\]/);
  assert.match(dashboardSource, /examItems:\s*\[createProcedureRow\(\)\]/);
  assert.match(dashboardSource, /testItems:\s*\[createProcedureRow\(\)\]/);
  assert.match(dashboardSource, /differentialDiagnoses:\s*\[createDifferentialRow\(\)\]/);
  assert.match(dashboardSource, /reasoningPoints:\s*\[createTextRow\(\)\]/);
  assert.doesNotMatch(dashboardSource, /historyFacts:\s*\[createTextRow\(\),\s*createTextRow\(\),\s*createTextRow\(\)\]/);
  assert.doesNotMatch(dashboardSource, /differentialDiagnoses:\s*\[createDifferentialRow\(\),\s*createDifferentialRow\(\)\]/);
  for (const label of ["添加病史线索", "添加查体项目", "添加辅助检查", "添加鉴别诊断", "添加推理要点"]) {
    assert.match(dashboardSource, new RegExp(label), `case workshop should expose row add action ${label}`);
  }
  for (const componentName of ["CaseCreationTextRowList", "CaseCreationProcedureRowList", "CaseCreationDifferentialRowList"]) {
    assert.match(dashboardSource, new RegExp(componentName), `case workshop should use ${componentName}`);
  }
  assert.doesNotMatch(dashboardSource, /粘贴病例 JSON/);
  assert.doesNotMatch(dashboardSource, /粘贴 Rubric JSON/);
  assert.doesNotMatch(dashboardSource, /每行一条/);
  assert.doesNotMatch(dashboardSource, /代码可留空/);
  assert.doesNotMatch(dashboardSource, /安全说明/);
  assert.doesNotMatch(dashboardSource, /grid gap-5 xl:grid-cols-2/);
});

test("admin v2 gives explicit feedback after manual refresh", () => {
  assert.match(dashboardSource, /statusText/);
  assert.match(dashboardSource, /已刷新管理数据/);
  assert.match(dashboardSource, /refreshDashboard\("已刷新管理数据"\)/);
});

test("admin v2 does not leak demo account credentials in the new login surface", () => {
  for (const forbidden of ["admin@osce.test", "student@osce.test", "DEMO_ADMIN_PASSWORD", "admin / admin", "student / student"]) {
    assert.doesNotMatch(dashboardSource, new RegExp(forbidden.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
});
