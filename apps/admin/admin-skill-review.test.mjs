import { strict as assert } from "node:assert";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

const adminPageUrl = new URL("./src/app/page.tsx", import.meta.url);
const adminPackageUrl = new URL("./package.json", import.meta.url);
const adminTsconfigUrl = new URL("./tsconfig.json", import.meta.url);
const adminLayoutUrl = new URL("./src/app/layout.tsx", import.meta.url);
const adminGlobalsUrl = new URL("./src/app/globals.css", import.meta.url);
const adminNextConfigUrl = new URL("./next.config.mjs", import.meta.url);
const adminPostcssConfigUrl = new URL("./postcss.config.mjs", import.meta.url);
const adminPageSource = existsSync(adminPageUrl) ? readFileSync(adminPageUrl, "utf8") : "";
const adminPackageSource = existsSync(adminPackageUrl) ? readFileSync(adminPackageUrl, "utf8") : "";
const adminTsconfigSource = existsSync(adminTsconfigUrl) ? readFileSync(adminTsconfigUrl, "utf8") : "";
const adminLayoutSource = existsSync(adminLayoutUrl) ? readFileSync(adminLayoutUrl, "utf8") : "";
const adminGlobalsSource = existsSync(adminGlobalsUrl) ? readFileSync(adminGlobalsUrl, "utf8") : "";
const adminNextConfigSource = existsSync(adminNextConfigUrl) ? readFileSync(adminNextConfigUrl, "utf8") : "";
const adminPostcssConfigSource = existsSync(adminPostcssConfigUrl) ? readFileSync(adminPostcssConfigUrl, "utf8") : "";

function getInteractiveElementsWithLabel(source, label) {
  return (source.match(/<(?:button|Link|a)\b[\s\S]*?<\/(?:button|Link|a)>/g) ?? []).filter((element) => element.includes(label));
}

function assertInteractiveLabelsDoNotWrap(sourceName, source, labels) {
  for (const label of labels) {
    const matchingElements = getInteractiveElementsWithLabel(source, label);
    assert.ok(matchingElements.length > 0, `${sourceName} should render an interactive action labelled ${label}`);

    for (const element of matchingElements) {
      assert.match(element, /whitespace-nowrap/, `${sourceName} action ${label} should prevent multi-line button text`);
    }
  }
}

test("admin dashboard reads management data and exposes review actions", () => {
  assert.ok(existsSync(adminPageUrl), "admin dashboard page should exist");
  assert.match(adminPageSource, /type AdminSessionSummary = Readonly<\{/);
  assert.match(adminPageSource, /type AdminSessionReport = Readonly<\{/);
  assert.match(adminPageSource, /type AdminReportsResponse = Readonly<\{/);
  assert.match(adminPageSource, /type EvaluationBatchSummary = Readonly<\{/);
  assert.match(adminPageSource, /type EvaluationBatchDetail = Readonly<\{/);
  assert.match(adminPageSource, /type AdminTrainingInsights = Readonly<\{/);
  assert.match(adminPageSource, /type FrequentMissedItem = Readonly<\{/);
  assert.match(adminPageSource, /type FrequentLearningRecommendation = Readonly<\{/);
  assert.match(adminPageSource, /type TrainingSkillCandidateSummary = Readonly<\{/);
  assert.match(adminPageSource, /type TrainingSkillCandidateDetail = Readonly<\{/);
  assert.match(adminPageSource, /type TrainingSkillEffectSummary = Readonly<\{/);
  assert.match(adminPageSource, /type AdminModelProviderConfig = Readonly<\{/);
  assert.match(adminPageSource, /type AdminModelConfigResponse = Readonly<\{/);
  assert.match(adminPageSource, /type CandidateAuditEventsResponse = Readonly<\{/);
  assert.match(adminPageSource, /type AdminAuditEventsResponse = Readonly<\{/);
  assert.match(adminPageSource, /type TrainingEventRecord = Readonly<\{/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/sessions"/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/reports"/);
  assert.match(adminPageSource, /fetch\(`\/api\/admin\/sessions\/\$\{sessionId\}\/report`/);
  assert.match(adminPageSource, /fetch\(`\/api\/admin\/sessions\/\$\{sessionId\}\/events`/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/insights"/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/evaluations"/);
  assert.match(adminPageSource, /fetch\(`\/api\/admin\/evaluations\/\$\{batchId\}`/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/evolution\/candidates"/);
  assert.match(adminPageSource, /fetch\(`\/api\/admin\/evolution\/candidates\/\$\{candidateId\}`/);
  assert.match(adminPageSource, /fetch\(`\/api\/admin\/evolution\/candidates\/\$\{candidateId\}\/events`/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/evolution\/events"/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/evolution\/skill-effects"/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/model-config"/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/evolution\/approve"/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/evolution\/reject"/);
  assert.match(adminPageSource, /Clinical OSCE 管理后台/);
  assert.match(adminPageSource, /总览/);
  assert.match(adminPageSource, /训练 Session/);
  assert.match(adminPageSource, /评分报告/);
  assert.match(adminPageSource, /跨 Session 报告列表/);
  assert.match(adminPageSource, /reports\.length > 0/);
  assert.match(adminPageSource, /setReports\(nextReports\)/);
  assert.match(adminPageSource, /错误模式统计/);
  assert.match(adminPageSource, /常见漏项/);
  assert.match(adminPageSource, /学习建议/);
  assert.match(adminPageSource, /系统评测/);
  assert.match(adminPageSource, /训练日志/);
  assert.match(adminPageSource, /候选 Skill 审核/);
  assert.match(adminPageSource, /Skill 效果统计/);
  assert.match(adminPageSource, /id="model-config"/);
  assert.match(adminPageSource, /模型 \/ API 配置/);
  assert.match(adminPageSource, /Gemini、Vertex 和 OpenAI 兼容模型/);
  assert.match(adminPageSource, /provider\.label/);
  assert.match(adminPageSource, /provider\.integration_status/);
  assert.match(adminPageSource, /密钥不落库/);
  assert.match(adminPageSource, /样本不足/);
  assert.match(adminPageSource, /skillEffects\.status === "insufficient_samples"/);
  assert.match(adminPageSource, /事件类型/);
  assert.match(adminPageSource, /事件内容/);
  assert.match(adminPageSource, /回归通过/);
  assert.match(adminPageSource, /批准并启用/);
  assert.match(adminPageSource, /拒绝候选/);
  assert.match(adminPageSource, /教学策略/);
  assert.match(adminPageSource, /独立审核审计日志/);
  assert.match(adminPageSource, /审核审计事件/);
  assert.match(adminPageSource, /auditEvents\.length > 0/);
  assert.match(adminPageSource, /candidateAuditEvents\.length > 0/);
  assert.match(adminPageSource, /setAuditEvents\(nextAuditEvents\)/);
  assert.match(adminPageSource, /setCandidateAuditEvents\(await getTrainingSkillCandidateEvents\(candidateId\)\)/);
});

test("admin action buttons keep Chinese labels on one line", () => {
  assertInteractiveLabelsDoNotWrap("admin dashboard", adminPageSource, [
    "管理员登录",
    "从训练日志生成候选 Skill",
    "批准并启用",
    "拒绝候选",
    "登录中",
  ]);
});

test("admin review actions are only available for ready candidates", () => {
  assert.match(adminPageSource, /const canReviewSelectedCandidate = selectedCandidate\?\.review\.status === "ready_for_review"/);
  assert.match(adminPageSource, /if \(selectedCandidate\.review\.status !== "ready_for_review"\) \{/);
  assert.match(adminPageSource, /\{canReviewSelectedCandidate \? \(/);
  assert.match(adminPageSource, /候选已审核，当前状态为 \{selectedCandidate\.review\.status\}/);
});

test("admin dashboard shows dedicated prompts for authentication and authorization API responses", () => {
  assert.match(adminPageSource, /const ADMIN_LOGIN_REQUIRED_MESSAGE = "管理后台需要登录，请先完成登录后再刷新页面。"/);
  assert.match(adminPageSource, /const ADMIN_FORBIDDEN_MESSAGE = "当前账号没有管理后台权限，请使用管理员账号登录。"/);
  assert.match(adminPageSource, /class AdminApiError extends Error/);
  assert.match(adminPageSource, /if \(response\.status === 401\)/);
  assert.match(adminPageSource, /if \(response\.status === 403\)/);
  assert.match(adminPageSource, /function getAdminErrorMessage\(error: unknown\): string/);
  assert.match(adminPageSource, /function shouldOpenAdminLoginDialog\(error: unknown\): boolean/);
  assert.match(adminPageSource, /const message = getAdminErrorMessage\(error\)/);
  assert.match(adminPageSource, /setStatusText\(message\)/);
  assert.match(adminPageSource, /setAdminLoginErrorText\(message\)/);
});

test("admin dashboard provides a modal login dialog for admin users", () => {
  assert.match(adminPageSource, /type AuthUser = Readonly<\{/);
  assert.match(adminPageSource, /type AuthLoginResponse = Readonly<\{/);
  assert.match(adminPageSource, /async function loginAdminUser\(email: string, password: string\): Promise<AuthUser>/);
  assert.match(adminPageSource, /fetch\("\/api\/auth\/login"/);
  assert.match(adminPageSource, /credentials: "same-origin"/);
  assert.match(adminPageSource, /const DEMO_ADMIN_EMAIL = "admin-demo@example.test"/);
  assert.match(adminPageSource, /const DEMO_ADMIN_PASSWORD = "safe-admin-password"/);
  assert.match(adminPageSource, /const \[adminEmail, setAdminEmail\] = useState\(DEMO_ADMIN_EMAIL\)/);
  assert.match(adminPageSource, /const \[adminPassword, setAdminPassword\] = useState\(DEMO_ADMIN_PASSWORD\)/);
  assert.match(adminPageSource, /const \[isAdminLoginDialogOpen, setIsAdminLoginDialogOpen\] = useState\(false\)/);
  assert.match(adminPageSource, /async function handleAdminLogin\(event: FormEvent<HTMLFormElement>\)/);
  assert.match(adminPageSource, /setIsAdminLoginDialogOpen\(true\)/);
  assert.match(adminPageSource, /setIsAdminLoginDialogOpen\(false\)/);
  assert.match(adminPageSource, /<div className=\{isAdminLoginDialogOpen \? "pointer-events-none blur-sm" : ""\}>/);
  assert.match(adminPageSource, /\{isAdminLoginDialogOpen \? \(/);
  assert.match(adminPageSource, /fixed inset-0 z-50 flex items-center justify-center/);
  assert.match(adminPageSource, /backdrop-blur/);
  assert.match(adminPageSource, /onSubmit=\{\(event\) => void handleAdminLogin\(event\)\}/);
  assert.match(adminPageSource, /管理员登录/);
  assert.match(adminPageSource, /id="admin-email-input"/);
  assert.match(adminPageSource, /id="admin-password-input"/);
  assert.match(adminPageSource, /type="password"/);
  assert.match(adminPageSource, /演示账号已预填/);
  assert.match(adminPageSource, /await loadDashboard\(\)/);
});

test("admin dashboard shows a read-only case rubric and source ledger", () => {
  assert.match(adminPageSource, /type AdminCaseSummary = Readonly<\{/);
  assert.match(adminPageSource, /type AdminCaseRaw = Readonly<\{/);
  assert.match(adminPageSource, /type AdminRubricItem = Readonly<\{/);
  assert.match(adminPageSource, /type AdminRubricDimension = Readonly<\{/);
  assert.match(adminPageSource, /type AdminRubricDetail = Readonly<\{/);
  assert.match(adminPageSource, /type AdminSourceRegistryEntry = Readonly<\{/);
  assert.match(adminPageSource, /type AdminCasesResponse = Readonly<\{/);
  assert.match(adminPageSource, /type AdminCaseRawResponse = Readonly<\{/);
  assert.match(adminPageSource, /type AdminRubricResponse = Readonly<\{/);
  assert.match(adminPageSource, /type AdminSourcesResponse = Readonly<\{/);
  assert.match(adminPageSource, /fetch\("\/api\/cases"/);
  assert.match(adminPageSource, /fetch\(`\/api\/admin\/cases\/\$\{caseId\}\/raw`/);
  assert.doesNotMatch(adminPageSource, /fetch\(`\/api\/cases\/\$\{caseId\}\/raw`/);
  assert.match(adminPageSource, /fetch\(`\/api\/admin\/rubrics\/\$\{rubricId\}`/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/sources"/);
  assert.match(adminPageSource, /getAdminCases\(\)/);
  assert.match(adminPageSource, /getAdminCaseRaw\(caseId\)/);
  assert.match(adminPageSource, /async function getAdminRubric\(rubricId: string\): Promise<AdminRubricDetail>/);
  assert.match(adminPageSource, /async function getAdminSources\(\): Promise<readonly AdminSourceRegistryEntry\[\]>/);
  assert.match(adminPageSource, /const \[cases, setCases\] = useState<readonly AdminCaseSummary\[\]>\(\[\]\)/);
  assert.match(adminPageSource, /const \[selectedCaseRaw, setSelectedCaseRaw\] = useState<AdminCaseRaw \| null>\(null\)/);
  assert.match(adminPageSource, /const \[selectedRubric, setSelectedRubric\] = useState<AdminRubricDetail \| null>\(null\)/);
  assert.match(adminPageSource, /const \[sources, setSources\] = useState<readonly AdminSourceRegistryEntry\[\]>\(\[\]\)/);
  assert.match(adminPageSource, /getAdminSources\(\)/);
  assert.match(adminPageSource, /setCases\(nextCases\)/);
  assert.match(adminPageSource, /setSources\(nextSources\)/);
  assert.match(adminPageSource, /const firstCaseRaw = await getAdminCaseRaw\(nextCases\[0\]\.case_id\)/);
  assert.match(adminPageSource, /setSelectedCaseRaw\(firstCaseRaw\)/);
  assert.match(adminPageSource, /setSelectedRubric\(await getAdminRubric\(firstCaseRaw\.rubric_ref\.rubric_id\)\)/);
  assert.match(adminPageSource, /const nextCaseRaw = await getAdminCaseRaw\(caseId\)/);
  assert.match(adminPageSource, /setSelectedCaseRaw\(nextCaseRaw\)/);
  assert.match(adminPageSource, /setSelectedRubric\(await getAdminRubric\(nextCaseRaw\.rubric_ref\.rubric_id\)\)/);
  assert.match(adminPageSource, /病例与来源台账/);
  assert.match(adminPageSource, /Rubric 引用/);
  assert.match(adminPageSource, /Rubric 评分表详情/);
  assert.match(adminPageSource, /评分维度/);
  assert.match(adminPageSource, /评分项/);
  assert.match(adminPageSource, /total_score/);
  assert.match(adminPageSource, /schema_version/);
  assert.match(adminPageSource, /match_rule/);
  assert.match(adminPageSource, /evidence_expected/);
  assert.match(adminPageSource, /来源追踪/);
  assert.match(adminPageSource, /数据来源登记表/);
  assert.match(adminPageSource, /allowed_usage/);
  assert.match(adminPageSource, /source_url/);
  assert.match(adminPageSource, /attribution_required/);
  assert.match(adminPageSource, /risk_note/);
  assert.match(adminPageSource, /医学安全边界/);
  assert.match(adminPageSource, /hidden_facts/);
  assert.match(adminPageSource, /reasoning_points/);
  assert.match(adminPageSource, /source_attribution/);
});

test("admin dashboard can validate and import case rubric payloads", () => {
  assert.match(adminPageSource, /type AdminCaseImportPayload = Readonly<\{/);
  assert.match(adminPageSource, /type AdminCaseValidationResponse = Readonly<\{/);
  assert.match(adminPageSource, /type AdminCaseImportResponse = Readonly<\{/);
  assert.match(adminPageSource, /type AdminCaseImportReadyState = Readonly<\{/);
  assert.match(adminPageSource, /function parseAdminImportJson\(text: string, label: string\): Record<string, unknown>/);
  assert.match(adminPageSource, /function getAdminCaseImportPayloadKey\(caseText: string, rubricText: string\): string/);
  assert.match(adminPageSource, /function buildAdminCaseImportPayload\(/);
  assert.match(adminPageSource, /async function validateAdminCaseImport\(payload: AdminCaseImportPayload\): Promise<AdminCaseValidationResponse>/);
  assert.match(adminPageSource, /async function importAdminCasePayload\(payload: AdminCaseImportPayload\): Promise<AdminCaseImportResponse>/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/cases\/validate"/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/cases\/import"/);
  assert.match(adminPageSource, /body: JSON\.stringify\(payload\)/);
  assert.match(adminPageSource, /const \[caseImportJsonText, setCaseImportJsonText\] = useState\(""\)/);
  assert.match(adminPageSource, /const \[rubricImportJsonText, setRubricImportJsonText\] = useState\(""\)/);
  assert.match(adminPageSource, /const \[caseImportResult, setCaseImportResult\] = useState<AdminCaseImportStatus \| null>\(null\)/);
  assert.match(adminPageSource, /const \[validatedCaseImport, setValidatedCaseImport\] = useState<AdminCaseImportReadyState \| null>\(null\)/);
  assert.match(adminPageSource, /const \[isCaseImportBusy, setIsCaseImportBusy\] = useState\(false\)/);
  assert.match(adminPageSource, /const currentCaseImportPayloadKey = getAdminCaseImportPayloadKey\(caseImportJsonText, rubricImportJsonText\)/);
  assert.match(adminPageSource, /const canImportCasePayload =/);
  assert.match(adminPageSource, /async function handleValidateCaseImport\(\)/);
  assert.match(adminPageSource, /setValidatedCaseImport\(result\.valid \? \{ payloadKey: currentCaseImportPayloadKey, result \} : null\)/);
  assert.match(adminPageSource, /async function handleImportCasePayload\(\)/);
  assert.match(adminPageSource, /disabled=\{!canImportCasePayload\}/);
  assert.match(adminPageSource, /setCaseImportResult\(null\)/);
  assert.match(adminPageSource, /setValidatedCaseImport\(null\)/);
  assert.match(adminPageSource, /setCases\(await getAdminCases\(\)\)/);
  assert.match(adminPageSource, /病例 \/ Rubric 导入/);
  assert.match(adminPageSource, /粘贴病例 JSON/);
  assert.match(adminPageSource, /粘贴 Rubric JSON/);
  assert.match(adminPageSource, /导入前预检/);
  assert.match(adminPageSource, /正式导入/);
  assert.match(adminPageSource, /imported=false/);
  assert.match(adminPageSource, /valid=false/);
});

test("admin dashboard filters long management lists locally", () => {
  assert.match(adminPageSource, /const \[caseSearchText, setCaseSearchText\] = useState\(""\)/);
  assert.match(adminPageSource, /const \[sessionSearchText, setSessionSearchText\] = useState\(""\)/);
  assert.match(adminPageSource, /const \[reportSearchText, setReportSearchText\] = useState\(""\)/);
  assert.match(adminPageSource, /const \[candidateSearchText, setCandidateSearchText\] = useState\(""\)/);
  assert.match(adminPageSource, /const filteredCases = cases\.filter/);
  assert.match(adminPageSource, /const filteredSessions = sessions\.filter/);
  assert.match(adminPageSource, /const filteredReports = reports\.filter/);
  assert.match(adminPageSource, /const filteredCandidates = candidates\.filter/);
  assert.match(adminPageSource, /placeholder="筛选病例 \/ 主诉"/);
  assert.match(adminPageSource, /placeholder="筛选 session \/ 用户 \/ 状态"/);
  assert.match(adminPageSource, /placeholder="筛选报告 \/ 病例 \/ 学员"/);
  assert.match(adminPageSource, /placeholder="筛选候选 Skill"/);
  assert.match(adminPageSource, /filteredCases\.length > 0/);
  assert.match(adminPageSource, /filteredSessions\.length > 0/);
  assert.match(adminPageSource, /filteredReports\.length > 0/);
  assert.match(adminPageSource, /filteredCandidates\.length > 0/);
  assert.match(adminPageSource, /filteredCases\.map\(\(caseItem\) =>/);
  assert.match(adminPageSource, /filteredSessions\.map\(\(session\) =>/);
  assert.match(adminPageSource, /filteredReports\.map\(\(report\) =>/);
  assert.match(adminPageSource, /filteredCandidates\.map\(\(candidate\) =>/);
  assert.match(adminPageSource, /没有匹配的病例台账。/);
  assert.match(adminPageSource, /没有匹配的训练 Session。/);
  assert.match(adminPageSource, /没有匹配的评分报告。/);
  assert.match(adminPageSource, /没有匹配的候选 Skill。/);
});

test("admin dashboard can trigger system evaluation runs", () => {
  assert.match(adminPageSource, /type EvaluationRunResponse = Readonly<\{/);
  assert.match(adminPageSource, /async function runAdminEvaluation\(batchId: string\): Promise<EvaluationBatchDetail>/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/evals\/run"/);
  assert.match(adminPageSource, /body: JSON\.stringify\(\{ batch_id: batchId \}\)/);
  assert.match(adminPageSource, /const \[isRunningEvaluation, setIsRunningEvaluation\] = useState\(false\)/);
  assert.match(adminPageSource, /async function handleRunEvaluation\(\)/);
  assert.match(adminPageSource, /const evaluation = await runAdminEvaluation\(batchId\)/);
  assert.match(adminPageSource, /setEvaluations\(await getAdminEvaluations\(\)\)/);
  assert.match(adminPageSource, /setSelectedEvaluation\(evaluation\)/);
  assert.match(adminPageSource, /setIsRunningEvaluation\(false\)/);
  assert.match(adminPageSource, /onClick=\{\(\) => void handleRunEvaluation\(\)\}/);
  assert.match(adminPageSource, /运行系统评测/);
  assert.match(adminPageSource, /运行中/);
});

test("admin dashboard renders a system evaluation chart summary", () => {
  assert.match(adminPageSource, /type EvaluationChartSummary = Readonly<\{/);
  assert.match(adminPageSource, /function buildEvaluationChartSummary\(/);
  assert.match(adminPageSource, /const evaluationChartSummary = buildEvaluationChartSummary\(evaluations, selectedEvaluation\)/);
  assert.match(adminPageSource, /系统评测图表摘要/);
  assert.match(adminPageSource, /批次数/);
  assert.match(adminPageSource, /总用例/);
  assert.match(adminPageSource, /通过率/);
  assert.match(adminPageSource, /失败用例/);
  assert.match(adminPageSource, /最近耗时/);
  assert.match(adminPageSource, /evaluationChartSummary\.passRatePercent/);
  assert.match(adminPageSource, /evaluationChartSummary\.failureRatePercent/);
  assert.match(adminPageSource, /style=\{\{ width: evaluationChartSummary\.passRatePercent \}\}/);
  assert.match(adminPageSource, /style=\{\{ width: evaluationChartSummary\.failureRatePercent \}\}/);
});

test("admin dashboard can export selected system evaluation batch as JSON", () => {
  assert.match(adminPageSource, /type EvaluationExportPayload = Readonly<\{/);
  assert.match(adminPageSource, /function buildEvaluationExportPayload\(evaluation: EvaluationBatchDetail\): EvaluationExportPayload/);
  assert.match(adminPageSource, /function downloadEvaluationBatchJson\(evaluation: EvaluationBatchDetail\): void/);
  assert.match(adminPageSource, /const payload = buildEvaluationExportPayload\(evaluation\)/);
  assert.match(adminPageSource, /new Blob\(\[JSON\.stringify\(payload, null, 2\)\], \{ type: "application\/json" \}\)/);
  assert.match(adminPageSource, /link\.download = `clinical-osce-evaluation-\$\{evaluation\.batch_id\}\.json`/);
  assert.match(adminPageSource, /onClick=\{\(\) => downloadEvaluationBatchJson\(selectedEvaluation\)\}/);
  assert.match(adminPageSource, /导出评测 JSON/);
  assert.match(adminPageSource, /selectedEvaluation \? \(/);
});

test("admin dashboard can generate candidate skills from training logs", () => {
  assert.match(adminPageSource, /type TrainingSkillCandidateGenerationResponse = Readonly<\{/);
  assert.match(adminPageSource, /async function generateTrainingSkillCandidates\(\): Promise<TrainingSkillCandidateGenerationResponse>/);
  assert.match(adminPageSource, /fetch\("\/api\/admin\/evolution\/candidates\/generate"/);
  assert.match(adminPageSource, /const \[isGeneratingCandidates, setIsGeneratingCandidates\] = useState\(false\)/);
  assert.match(adminPageSource, /async function handleGenerateTrainingSkillCandidates\(\)/);
  assert.match(adminPageSource, /const result = await generateTrainingSkillCandidates\(\)/);
  assert.match(adminPageSource, /const \[nextInsights, nextSkillEffects, nextCandidates, nextEvaluations, nextAuditEvents\] = await Promise\.all/);
  assert.match(adminPageSource, /getAdminInsights\(\)/);
  assert.match(adminPageSource, /getTrainingSkillEffects\(\)/);
  assert.match(adminPageSource, /getTrainingSkillCandidates\(\)/);
  assert.match(adminPageSource, /getAdminEvaluations\(\)/);
  assert.match(adminPageSource, /getAdminAuditEvents\(\)/);
  assert.match(adminPageSource, /setInsights\(nextInsights\)/);
  assert.match(adminPageSource, /setSkillEffects\(nextSkillEffects\)/);
  assert.match(adminPageSource, /setCandidates\(nextCandidates\)/);
  assert.match(adminPageSource, /setEvaluations\(nextEvaluations\)/);
  assert.match(adminPageSource, /setAuditEvents\(nextAuditEvents\)/);
  assert.match(adminPageSource, /setIsGeneratingCandidates\(false\)/);
  assert.match(adminPageSource, /onClick=\{\(\) => void handleGenerateTrainingSkillCandidates\(\)\}/);
  assert.match(adminPageSource, /从训练日志生成候选 Skill/);
  assert.match(adminPageSource, /生成中/);
  assert.match(adminPageSource, /已从训练日志生成/);
});

test("admin review actions only send candidate id", () => {
  assert.match(adminPageSource, /body: JSON\.stringify\(\{ candidate_id: candidateId \}\)/);
  assert.doesNotMatch(adminPageSource, /reviewer_id: "local-admin"/);
});

test("admin app has standalone Next.js package and TypeScript config", () => {
  assert.ok(existsSync(adminPackageUrl), "admin package.json should exist");
  assert.ok(existsSync(adminTsconfigUrl), "admin tsconfig.json should exist");
  assert.match(adminPackageSource, /"name": "clinical-osce-admin"/);
  assert.match(adminPackageSource, /"dev": "next dev"/);
  assert.match(adminPackageSource, /"build": "next build"/);
  assert.match(adminPackageSource, /"typecheck": "tsc --noEmit"/);
  assert.match(adminPackageSource, /"next": "\^15\.5\.14"/);
  assert.match(adminPackageSource, /"react": "\^19\.1\.0"/);
  assert.match(adminTsconfigSource, /"strict": true/);
  assert.match(adminTsconfigSource, /"plugins": \[\{ "name": "next" \}\]/);
  assert.match(adminTsconfigSource, /"include": \["next-env\.d\.ts", "\*\*\/\*\.ts", "\*\*\/\*\.tsx", "\.next\/types\/\*\*\/\*\.ts"\]/);
});

test("admin app has Next.js root layout and global styles", () => {
  assert.ok(existsSync(adminLayoutUrl), "admin root layout should exist");
  assert.ok(existsSync(adminGlobalsUrl), "admin globals stylesheet should exist");
  assert.match(adminLayoutSource, /import type \{ Metadata \} from "next"/);
  assert.match(adminLayoutSource, /import "\.\/globals\.css"/);
  assert.match(adminLayoutSource, /title: "Clinical OSCE 管理后台"/);
  assert.match(adminLayoutSource, /<html lang="zh-CN">/);
  assert.match(adminGlobalsSource, /@import "tailwindcss";/);
  assert.match(adminGlobalsSource, /--admin-paper: #faf9f5;/);
});

test("admin app proxies API requests and compiles Tailwind styles", () => {
  assert.ok(existsSync(adminNextConfigUrl), "admin next.config.mjs should exist");
  assert.ok(existsSync(adminPostcssConfigUrl), "admin postcss.config.mjs should exist");
  assert.match(adminNextConfigSource, /const adminApiUrl = process\.env\.CLINICAL_OSCE_ADMIN_API_URL \?\? "http:\/\/127\.0\.0\.1:8000"/);
  assert.match(adminNextConfigSource, /async rewrites\(\)/);
  assert.match(adminNextConfigSource, /source: "\/api\/:path\*"/);
  assert.match(adminNextConfigSource, /destination: `\$\{adminApiUrl\}\/api\/:path\*`/);
  assert.match(adminPostcssConfigSource, /plugins: \["@tailwindcss\/postcss"\]/);
});
