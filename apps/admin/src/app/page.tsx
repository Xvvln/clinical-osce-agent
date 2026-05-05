"use client";

import { type FormEvent, useEffect, useState } from "react";

type AdminSessionSummary = Readonly<{
  session_id: string;
  student_id: string;
  case_id: string;
  stage: string;
  created_at: string;
  updated_at: string;
}>;

type ReportRecommendation = Readonly<{
  title: string;
  reference: string;
}>;

type AdminSourceReferenceItem = Readonly<{
  reference: string;
  source_type: string;
  title: string;
  metadata: Readonly<Record<string, unknown>>;
}>;

type AdminSessionReport = Readonly<{
  report_id: string;
  session_id: string;
  case_id: string;
  student_id: string;
  total_score: number;
  dimension_scores: Record<string, number>;
  missed_items: readonly string[];
  source_references?: readonly string[];
  source_reference_items?: readonly AdminSourceReferenceItem[];
  knowledge_recommendations: readonly ReportRecommendation[];
}>;

type EvaluationBatchSummary = Readonly<{
  batch_id: string;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  passed: boolean;
}>;

type EvaluationCaseResult = Readonly<{
  session_id: string;
  actual_total_score: number;
  expected_total_score: number;
  forbidden_term_violations: readonly string[];
  source_reference_count: number;
  source_reference_types: readonly string[];
  rag_source_coverage_passed: boolean;
  rag_rubric_reference_coverage_ratio: number;
  missing_rubric_references: readonly string[];
  rag_explanation_coverage_passed: boolean;
  rag_explanation_coverage_ratio: number;
  missing_explanation_references: readonly string[];
  rag_evidence_coverage_passed: boolean;
  rag_evidence_coverage_ratio: number;
  missing_evidence_references: readonly string[];
  passed: boolean;
  duration_ms: number;
}>;

type EvaluationBatchDetail = Readonly<{
  batch_id: string;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  passed: boolean;
  total_duration_ms: number;
  results: readonly EvaluationCaseResult[];
}>;

type EvaluationExportPayload = Readonly<{
  batch_id: string;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  passed: boolean;
  total_duration_ms: number;
  results: readonly EvaluationCaseResult[];
}>;

type EvaluationChartSummary = Readonly<{
  batchCount: number;
  totalCases: number;
  passedCases: number;
  failedCases: number;
  passRatePercent: string;
  failureRatePercent: string;
  latestDurationMs: number;
}>;

type FrequentMissedItem = Readonly<{
  item_id: string;
  count: number;
  case_ids: readonly string[];
}>;

type FrequentLearningRecommendation = Readonly<{
  reference: string;
  title: string;
  count: number;
}>;

type FrequentSourceReference = AdminSourceReferenceItem &
  Readonly<{
    count: number;
    case_ids: readonly string[];
  }>;

type AdminTrainingInsights = Readonly<{
  session_count: number;
  report_count: number;
  frequent_missed_items: readonly FrequentMissedItem[];
  frequent_learning_recommendations: readonly FrequentLearningRecommendation[];
  frequent_source_references: readonly FrequentSourceReference[];
}>;

type TrainingSkillCandidateSummary = Readonly<{
  candidate_id: string;
  trigger_item_id: string;
  title: string;
  status: string;
  regression_passed: boolean;
  source_report_count: number;
  support_count: number;
}>;

type TrainingSkillCandidateReview = Readonly<{
  candidate_id: string;
  status: string;
  regression_passed: boolean;
  evaluation_total_cases: number;
  evaluation_passed_cases: number;
  evaluation_failed_cases: number;
  blocking_failures: readonly unknown[];
  reviewer_id?: string;
}>;

type TrainingSkillCandidateDetail = Readonly<{
  candidate_id: string;
  trigger_item_id: string;
  title: string;
  description: string;
  suggested_strategy: string;
  status: string;
  source_report_count: number;
  support_count: number;
  related_recommendations: readonly string[];
  review: TrainingSkillCandidateReview;
}>;

type TrainingSkillEffectGroup = Readonly<{
  session_count: number;
  average_total_score: number;
  missed_item_counts: Record<string, number>;
  skill_ids: readonly string[];
}>;

type TrainingSkillEffectSummary = Readonly<{
  status: "ready" | "insufficient_samples";
  label: string;
  min_sessions_per_group: number;
  score_delta: number | null;
  with_skill: TrainingSkillEffectGroup;
  without_skill: TrainingSkillEffectGroup;
}>;

type TrainingEventRecord = Readonly<{
  session_id: string;
  case_id: string;
  student_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}>;

type AdminCaseSummary = Readonly<{
  case_id: string;
  case_title: string;
  course_module: string;
  difficulty: string;
  chief_complaint: string;
}>;

type AdminCaseRaw = Readonly<{
  case_id: string;
  case_title: string;
  course_module: string;
  difficulty: string;
  chief_complaint: string;
  history: Readonly<{
    hidden_facts: readonly unknown[];
  }>;
  physical_exam: Readonly<{
    must_items: readonly unknown[];
    optional_items: readonly unknown[];
  }>;
  auxiliary_tests: Readonly<{
    must_items: readonly unknown[];
    optional_items: readonly unknown[];
  }>;
  diagnosis: Readonly<{
    main_diagnosis: string;
    differential_diagnoses: readonly unknown[];
    reasoning_points: readonly unknown[];
  }>;
  rubric_ref: Readonly<{
    rubric_id: string;
    version: string;
  }>;
  safety_notes: string;
  source_attribution: Readonly<{
    source_id: string;
    transformation: string;
    attribution_note: string;
    modified: boolean;
  }>;
}>;

type AdminRubricItem = Readonly<{
  item_id: string;
  description: string;
  max_score: number;
  match_rule: Readonly<{
    kind: string;
    spec: Record<string, unknown>;
  }>;
  evidence_expected: readonly string[];
}>;

type AdminRubricDimension = Readonly<{
  dimension_id: string;
  weight: number;
  scoring_mode: string;
  items: readonly AdminRubricItem[];
}>;

type AdminRubricDetail = Readonly<{
  rubric_id: string;
  case_id: string;
  version: string;
  total_score: number;
  schema_version: string;
  dimensions: readonly AdminRubricDimension[];
}>;

type AdminSourceRegistryEntry = Readonly<{
  source_id: string;
  source_name: string;
  source_url: string;
  license: string;
  data_type: string;
  allowed_usage: readonly string[];
  transformation: string;
  attribution_required: boolean;
  risk_note: string;
}>;

type AdminModelProviderConfig = Readonly<{
  provider_id: string;
  label: string;
  capability: string;
  enabled: boolean;
  configured: boolean;
  secret_configured: boolean;
  auth_mode: string;
  model: string;
  base_url: string;
  project: string;
  location: string;
  proxy_url: string;
  required_env: readonly string[];
  missing_env: readonly string[];
  integration_status: string;
  notes: string;
}>;

type AdminModelConfigPolicy = Readonly<{
  secrets_persisted: boolean;
  runtime_write_supported: boolean;
  configuration_source: string;
}>;

type AuthUser = Readonly<{
  user_id: string;
  email: string;
  display_name: string;
  created_at: string;
}>;

type AdminSessionsResponse = Readonly<{
  sessions: readonly AdminSessionSummary[];
}>;

type AdminCasesResponse = Readonly<{
  cases: readonly AdminCaseSummary[];
}>;

type AdminCaseRawResponse = Readonly<{
  case: AdminCaseRaw;
}>;

type AdminRubricResponse = Readonly<{
  rubric: AdminRubricDetail;
}>;

type AdminSourcesResponse = Readonly<{
  sources: readonly AdminSourceRegistryEntry[];
}>;

type AdminModelConfigResponse = Readonly<{
  providers: readonly AdminModelProviderConfig[];
  policy: AdminModelConfigPolicy;
}>;

type AdminCaseImportPayload = Readonly<{
  case: Record<string, unknown>;
  rubric: Record<string, unknown>;
}>;

type AdminCaseValidationResponse = Readonly<{
  valid: boolean;
  case_id: string | null;
  rubric_id: string | null;
  errors: readonly string[];
}>;

type AdminCaseImportResponse = Readonly<{
  imported: boolean;
  case_id: string | null;
  rubric_id: string | null;
  errors: readonly string[];
}>;

type AdminCaseImportStatus = AdminCaseValidationResponse | AdminCaseImportResponse;

type AdminCaseImportReadyState = Readonly<{
  payloadKey: string;
  result: AdminCaseValidationResponse;
}>;

type AuthLoginResponse = Readonly<{
  user: AuthUser;
}>;

type AdminSessionReportResponse = Readonly<{
  report: AdminSessionReport;
}>;

type AdminReportsResponse = Readonly<{
  reports: readonly AdminSessionReport[];
}>;

type EvaluationListResponse = Readonly<{
  evaluations: readonly EvaluationBatchSummary[];
}>;

type EvaluationDetailResponse = Readonly<{
  evaluation: EvaluationBatchDetail;
}>;

type EvaluationRunResponse = Readonly<{
  evaluation: EvaluationBatchDetail;
}>;

type AdminInsightsResponse = Readonly<{
  insights: AdminTrainingInsights;
}>;

type AdminSkillEffectsResponse = Readonly<{
  skill_effects: TrainingSkillEffectSummary;
}>;

type CandidateListResponse = Readonly<{
  candidates: readonly TrainingSkillCandidateSummary[];
}>;

type TrainingSkillCandidateGenerationResponse = Readonly<{
  generated_count: number;
  saved_count: number;
  ready_for_review_count: number;
  blocked_by_regression_count: number;
  candidates: readonly TrainingSkillCandidateSummary[];
}>;

type CandidateDetailResponse = Readonly<{
  candidate: TrainingSkillCandidateDetail;
}>;

type SessionEventsResponse = Readonly<{
  events: readonly TrainingEventRecord[];
}>;

type CandidateAuditEventsResponse = Readonly<{
  events: readonly TrainingEventRecord[];
}>;

type AdminAuditEventsResponse = Readonly<{
  events: readonly TrainingEventRecord[];
}>;

const ADMIN_LOGIN_REQUIRED_MESSAGE = "管理后台需要登录，请先完成登录后再刷新页面。";
const ADMIN_FORBIDDEN_MESSAGE = "当前账号没有管理后台权限，请使用管理员账号登录。";
const ADMIN_LOGIN_FAILED_MESSAGE = "管理员登录失败，请检查邮箱和密码。";
const DEMO_ADMIN_EMAIL = "admin-demo@example.test";
const DEMO_ADMIN_PASSWORD = "safe-admin-password";

class AdminApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "AdminApiError";
    this.status = status;
  }
}

async function assertAdminResponseOk(response: Response, action: string): Promise<void> {
  if (response.ok) {
    return;
  }
  if (response.status === 401) {
    throw new AdminApiError(ADMIN_LOGIN_REQUIRED_MESSAGE, response.status);
  }
  if (response.status === 403) {
    throw new AdminApiError(ADMIN_FORBIDDEN_MESSAGE, response.status);
  }
  throw new AdminApiError(`${action}失败：${response.status}`, response.status);
}

function getAdminErrorMessage(error: unknown): string {
  if (error instanceof AdminApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "读取管理后台数据失败。";
}

function shouldOpenAdminLoginDialog(error: unknown): boolean {
  return error instanceof AdminApiError && (error.status === 401 || error.status === 403);
}

async function loginAdminUser(email: string, password: string): Promise<AuthUser> {
  const response = await fetch("/api/auth/login", {
    body: JSON.stringify({ email, password }),
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });
  if (!response.ok) {
    throw new AdminApiError(ADMIN_LOGIN_FAILED_MESSAGE, response.status);
  }
  const payload = (await response.json()) as AuthLoginResponse;
  return payload.user;
}

async function getAdminCases(): Promise<readonly AdminCaseSummary[]> {
  const response = await fetch("/api/cases", { method: "GET" });
  await assertAdminResponseOk(response, "读取病例台账");
  const payload = (await response.json()) as AdminCasesResponse;
  return payload.cases;
}

async function getAdminCaseRaw(caseId: string): Promise<AdminCaseRaw> {
  const response = await fetch(`/api/admin/cases/${caseId}/raw`, { method: "GET" });
  await assertAdminResponseOk(response, "读取病例详情");
  const payload = (await response.json()) as AdminCaseRawResponse;
  return payload.case;
}

async function getAdminRubric(rubricId: string): Promise<AdminRubricDetail> {
  const response = await fetch(`/api/admin/rubrics/${rubricId}`, { method: "GET" });
  await assertAdminResponseOk(response, "读取 Rubric 详情");
  const payload = (await response.json()) as AdminRubricResponse;
  return payload.rubric;
}

async function getAdminSources(): Promise<readonly AdminSourceRegistryEntry[]> {
  const response = await fetch("/api/admin/sources", { method: "GET" });
  await assertAdminResponseOk(response, "读取数据来源登记表");
  const payload = (await response.json()) as AdminSourcesResponse;
  return payload.sources;
}

async function getAdminModelConfig(): Promise<AdminModelConfigResponse> {
  const response = await fetch("/api/admin/model-config", { method: "GET" });
  await assertAdminResponseOk(response, "读取模型 API 配置");
  return (await response.json()) as AdminModelConfigResponse;
}

function getAdminCaseImportPayloadKey(caseText: string, rubricText: string): string {
  return `${caseText}\n---rubric---\n${rubricText}`;
}

function parseAdminImportJson(text: string, label: string): Record<string, unknown> {
  const trimmedText = text.trim();
  if (!trimmedText) {
    throw new Error(`${label} 不能为空。`);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmedText) as unknown;
  } catch {
    throw new Error(`${label} 不是合法 JSON。`);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON object。`);
  }
  return parsed as Record<string, unknown>;
}

async function validateAdminCaseImport(payload: AdminCaseImportPayload): Promise<AdminCaseValidationResponse> {
  const response = await fetch("/api/admin/cases/validate", {
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });
  await assertAdminResponseOk(response, "校验病例与 Rubric");
  return (await response.json()) as AdminCaseValidationResponse;
}

async function importAdminCasePayload(payload: AdminCaseImportPayload): Promise<AdminCaseImportResponse> {
  const response = await fetch("/api/admin/cases/import", {
    body: JSON.stringify(payload),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });
  await assertAdminResponseOk(response, "导入病例与 Rubric");
  return (await response.json()) as AdminCaseImportResponse;
}

async function getAdminSessions(): Promise<readonly AdminSessionSummary[]> {
  const response = await fetch("/api/admin/sessions", { method: "GET" });
  await assertAdminResponseOk(response, "读取训练 Session");
  const payload = (await response.json()) as AdminSessionsResponse;
  return payload.sessions;
}

async function getAdminSessionReport(sessionId: string): Promise<AdminSessionReport> {
  const response = await fetch(`/api/admin/sessions/${sessionId}/report`, { method: "GET" });
  await assertAdminResponseOk(response, "读取评分报告");
  const payload = (await response.json()) as AdminSessionReportResponse;
  return payload.report;
}

async function getAdminReports(): Promise<readonly AdminSessionReport[]> {
  const response = await fetch("/api/admin/reports", { method: "GET" });
  await assertAdminResponseOk(response, "读取跨 Session 报告列表");
  const payload = (await response.json()) as AdminReportsResponse;
  return payload.reports;
}

async function getAdminSessionEvents(sessionId: string): Promise<readonly TrainingEventRecord[]> {
  const response = await fetch(`/api/admin/sessions/${sessionId}/events`, { method: "GET" });
  await assertAdminResponseOk(response, "读取训练日志");
  const payload = (await response.json()) as SessionEventsResponse;
  return payload.events;
}

async function getAdminInsights(): Promise<AdminTrainingInsights> {
  const response = await fetch("/api/admin/insights", { method: "GET" });
  await assertAdminResponseOk(response, "读取错误模式统计");
  const payload = (await response.json()) as AdminInsightsResponse;
  return payload.insights;
}

async function getTrainingSkillEffects(): Promise<TrainingSkillEffectSummary> {
  const response = await fetch("/api/admin/evolution/skill-effects", { method: "GET" });
  await assertAdminResponseOk(response, "读取 Skill 效果统计");
  const payload = (await response.json()) as AdminSkillEffectsResponse;
  return payload.skill_effects;
}

async function getAdminEvaluations(): Promise<readonly EvaluationBatchSummary[]> {
  const response = await fetch("/api/admin/evaluations", { method: "GET" });
  await assertAdminResponseOk(response, "读取系统评测");
  const payload = (await response.json()) as EvaluationListResponse;
  return payload.evaluations;
}

async function getAdminEvaluation(batchId: string): Promise<EvaluationBatchDetail> {
  const response = await fetch(`/api/admin/evaluations/${batchId}`, { method: "GET" });
  await assertAdminResponseOk(response, "读取评测详情");
  const payload = (await response.json()) as EvaluationDetailResponse;
  return payload.evaluation;
}

async function runAdminEvaluation(batchId: string): Promise<EvaluationBatchDetail> {
  const response = await fetch("/api/admin/evals/run", {
    body: JSON.stringify({ batch_id: batchId }),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });
  await assertAdminResponseOk(response, "运行系统评测");
  const payload = (await response.json()) as EvaluationRunResponse;
  return payload.evaluation;
}

async function getTrainingSkillCandidates(): Promise<readonly TrainingSkillCandidateSummary[]> {
  const response = await fetch("/api/admin/evolution/candidates", { method: "GET" });
  await assertAdminResponseOk(response, "读取候选 Skill");
  const payload = (await response.json()) as CandidateListResponse;
  return payload.candidates;
}

async function generateTrainingSkillCandidates(): Promise<TrainingSkillCandidateGenerationResponse> {
  const response = await fetch("/api/admin/evolution/candidates/generate", { method: "POST" });
  await assertAdminResponseOk(response, "从训练日志生成候选 Skill");
  return (await response.json()) as TrainingSkillCandidateGenerationResponse;
}

async function getTrainingSkillCandidate(candidateId: string): Promise<TrainingSkillCandidateDetail> {
  const response = await fetch(`/api/admin/evolution/candidates/${candidateId}`, { method: "GET" });
  await assertAdminResponseOk(response, "读取候选 Skill 详情");
  const payload = (await response.json()) as CandidateDetailResponse;
  return payload.candidate;
}

async function getTrainingSkillCandidateEvents(candidateId: string): Promise<readonly TrainingEventRecord[]> {
  const response = await fetch(`/api/admin/evolution/candidates/${candidateId}/events`, { method: "GET" });
  await assertAdminResponseOk(response, "读取候选 Skill 审核审计事件");
  const payload = (await response.json()) as CandidateAuditEventsResponse;
  return payload.events;
}

async function getAdminAuditEvents(): Promise<readonly TrainingEventRecord[]> {
  const response = await fetch("/api/admin/evolution/events", { method: "GET" });
  await assertAdminResponseOk(response, "读取独立审核审计日志");
  const payload = (await response.json()) as AdminAuditEventsResponse;
  return payload.events;
}

async function approveTrainingSkillCandidate(candidateId: string): Promise<void> {
  const response = await fetch("/api/admin/evolution/approve", {
    body: JSON.stringify({ candidate_id: candidateId }),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });
  await assertAdminResponseOk(response, "批准候选 Skill");
}

async function rejectTrainingSkillCandidate(candidateId: string): Promise<void> {
  const response = await fetch("/api/admin/evolution/reject", {
    body: JSON.stringify({ candidate_id: candidateId }),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });
  await assertAdminResponseOk(response, "拒绝候选 Skill");
}

function getPassLabel(passed: boolean): string {
  return passed ? "通过" : "未通过";
}

function getPercent(part: number, total: number): string {
  if (total === 0) {
    return "0%";
  }
  return `${Math.round((part / total) * 100)}%`;
}

function buildEvaluationChartSummary(
  evaluations: readonly EvaluationBatchSummary[],
  selectedEvaluation: EvaluationBatchDetail | null,
): EvaluationChartSummary {
  const totalCases = evaluations.reduce((sum, evaluation) => sum + evaluation.total_cases, 0);
  const passedCases = evaluations.reduce((sum, evaluation) => sum + evaluation.passed_cases, 0);
  const failedCases = evaluations.reduce((sum, evaluation) => sum + evaluation.failed_cases, 0);

  return {
    batchCount: evaluations.length,
    totalCases,
    passedCases,
    failedCases,
    passRatePercent: getPercent(passedCases, totalCases),
    failureRatePercent: getPercent(failedCases, totalCases),
    latestDurationMs: selectedEvaluation?.total_duration_ms ?? 0,
  };
}

function getSourceReferenceLabel(reference: string): string {
  const separatorIndex = reference.indexOf(":");
  if (separatorIndex === -1) {
    return reference;
  }
  return reference.slice(separatorIndex + 1);
}

function getSourceReferenceMetadataText(metadata: Readonly<Record<string, unknown>>): string {
  const license = typeof metadata.license === "string" ? `许可：${metadata.license}` : "";
  const sourceUrl = typeof metadata.source_url === "string" ? `来源：${metadata.source_url}` : "";
  return [license, sourceUrl].filter(Boolean).join(" · ");
}

function getReportSourceReferenceItems(report: AdminSessionReport): readonly AdminSourceReferenceItem[] {
  if ((report.source_reference_items?.length ?? 0) > 0) {
    return report.source_reference_items ?? [];
  }
  return (report.source_references ?? []).map((reference) => ({
    reference,
    source_type: reference.split(":", 1)[0] || "other",
    title: getSourceReferenceLabel(reference),
    metadata: {},
  }));
}

function getAdminCaseImportStatusLabel(result: AdminCaseImportStatus): string {
  if ("valid" in result) {
    return result.valid ? "预检通过" : "valid=false";
  }
  return result.imported ? "导入成功" : "imported=false";
}

function getAdminCaseImportStatusText(result: AdminCaseImportStatus): string {
  const label = getAdminCaseImportStatusLabel(result);
  const errors = result.errors.length > 0 ? ` · ${result.errors.join("；")}` : "";
  return `${label} · case_id=${result.case_id ?? "—"} · rubric_id=${result.rubric_id ?? "—"}${errors}`;
}

function buildEvaluationExportPayload(evaluation: EvaluationBatchDetail): EvaluationExportPayload {
  return {
    batch_id: evaluation.batch_id,
    failed_cases: evaluation.failed_cases,
    passed: evaluation.passed,
    passed_cases: evaluation.passed_cases,
    results: evaluation.results.map((result) => ({
      actual_total_score: result.actual_total_score,
      duration_ms: result.duration_ms,
      expected_total_score: result.expected_total_score,
      forbidden_term_violations: result.forbidden_term_violations,
      passed: result.passed,
      rag_rubric_reference_coverage_ratio: result.rag_rubric_reference_coverage_ratio,
      rag_source_coverage_passed: result.rag_source_coverage_passed,
      missing_rubric_references: result.missing_rubric_references,
      rag_explanation_coverage_passed: result.rag_explanation_coverage_passed,
      rag_explanation_coverage_ratio: result.rag_explanation_coverage_ratio,
      missing_explanation_references: result.missing_explanation_references,
      rag_evidence_coverage_passed: result.rag_evidence_coverage_passed,
      rag_evidence_coverage_ratio: result.rag_evidence_coverage_ratio,
      missing_evidence_references: result.missing_evidence_references,
      session_id: result.session_id,
      source_reference_count: result.source_reference_count,
      source_reference_types: result.source_reference_types,
    })),
    total_cases: evaluation.total_cases,
    total_duration_ms: evaluation.total_duration_ms,
  };
}

function downloadEvaluationBatchJson(evaluation: EvaluationBatchDetail): void {
  const payload = buildEvaluationExportPayload(evaluation);
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `clinical-osce-evaluation-${evaluation.batch_id}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

function includesSearchText(searchSource: string, searchText: string): boolean {
  const normalizedSearchText = searchText.trim().toLowerCase();
  return !normalizedSearchText || searchSource.toLowerCase().includes(normalizedSearchText);
}

export default function AdminDashboardPage() {
  const [cases, setCases] = useState<readonly AdminCaseSummary[]>([]);
  const [selectedCaseRaw, setSelectedCaseRaw] = useState<AdminCaseRaw | null>(null);
  const [selectedRubric, setSelectedRubric] = useState<AdminRubricDetail | null>(null);
  const [sources, setSources] = useState<readonly AdminSourceRegistryEntry[]>([]);
  const [modelConfig, setModelConfig] = useState<AdminModelConfigResponse | null>(null);
  const [sessions, setSessions] = useState<readonly AdminSessionSummary[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [selectedReport, setSelectedReport] = useState<AdminSessionReport | null>(null);
  const [reports, setReports] = useState<readonly AdminSessionReport[]>([]);
  const [insights, setInsights] = useState<AdminTrainingInsights | null>(null);
  const [skillEffects, setSkillEffects] = useState<TrainingSkillEffectSummary | null>(null);
  const [evaluations, setEvaluations] = useState<readonly EvaluationBatchSummary[]>([]);
  const [selectedEvaluation, setSelectedEvaluation] = useState<EvaluationBatchDetail | null>(null);
  const [isRunningEvaluation, setIsRunningEvaluation] = useState(false);
  const [isGeneratingCandidates, setIsGeneratingCandidates] = useState(false);
  const [candidates, setCandidates] = useState<readonly TrainingSkillCandidateSummary[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<TrainingSkillCandidateDetail | null>(null);
  const [caseSearchText, setCaseSearchText] = useState("");
  const [caseImportJsonText, setCaseImportJsonText] = useState("");
  const [rubricImportJsonText, setRubricImportJsonText] = useState("");
  const [caseImportResult, setCaseImportResult] = useState<AdminCaseImportStatus | null>(null);
  const [validatedCaseImport, setValidatedCaseImport] = useState<AdminCaseImportReadyState | null>(null);
  const [isCaseImportBusy, setIsCaseImportBusy] = useState(false);
  const [sessionSearchText, setSessionSearchText] = useState("");
  const [reportSearchText, setReportSearchText] = useState("");
  const [candidateSearchText, setCandidateSearchText] = useState("");
  const [candidateAuditEvents, setCandidateAuditEvents] = useState<readonly TrainingEventRecord[]>([]);
  const [auditEvents, setAuditEvents] = useState<readonly TrainingEventRecord[]>([]);
  const [sessionIdInput, setSessionIdInput] = useState("");
  const [trainingEvents, setTrainingEvents] = useState<readonly TrainingEventRecord[]>([]);
  const [statusText, setStatusText] = useState("正在读取管理后台数据...");
  const [adminEmail, setAdminEmail] = useState(DEMO_ADMIN_EMAIL);
  const [adminPassword, setAdminPassword] = useState(DEMO_ADMIN_PASSWORD);
  const [adminLoginErrorText, setAdminLoginErrorText] = useState<string | null>(null);
  const [isAdminLoginDialogOpen, setIsAdminLoginDialogOpen] = useState(false);
  const [isLoggingIn, setIsLoggingIn] = useState(false);

  const filteredCases = cases.filter((caseItem) =>
    includesSearchText(
      [
        caseItem.case_id,
        caseItem.case_title,
        caseItem.course_module,
        caseItem.difficulty,
        caseItem.chief_complaint,
        selectedCaseRaw?.case_id === caseItem.case_id ? selectedCaseRaw.rubric_ref.rubric_id : "",
      ].join(" "),
      caseSearchText,
    ),
  );
  const filteredSessions = sessions.filter((session) =>
    includesSearchText(
      [session.session_id, session.student_id, session.case_id, session.stage, session.updated_at].join(" "),
      sessionSearchText,
    ),
  );
  const filteredReports = reports.filter((report) =>
    includesSearchText(
      [
        report.report_id,
        report.session_id,
        report.case_id,
        report.student_id,
        String(report.total_score),
        ...report.missed_items,
        ...report.knowledge_recommendations.map((recommendation) => recommendation.title),
        ...getReportSourceReferenceItems(report).flatMap((item) => [item.title, item.reference]),
      ].join(" "),
      reportSearchText,
    ),
  );
  const filteredCandidates = candidates.filter((candidate) =>
    includesSearchText(
      [
        candidate.candidate_id,
        candidate.trigger_item_id,
        candidate.title,
        candidate.status,
        candidate.regression_passed ? "回归通过" : "回归阻塞",
      ].join(" "),
      candidateSearchText,
    ),
  );
  const currentCaseImportPayloadKey = getAdminCaseImportPayloadKey(caseImportJsonText, rubricImportJsonText);
  const canImportCasePayload = validatedCaseImport?.payloadKey === currentCaseImportPayloadKey && validatedCaseImport.result.valid && !isCaseImportBusy;
  const evaluationChartSummary = buildEvaluationChartSummary(evaluations, selectedEvaluation);

  async function loadDashboard() {
    const [nextCases, nextSources, nextModelConfig, nextSessions, nextReports, nextInsights, nextSkillEffects, nextEvaluations, nextCandidates, nextAuditEvents] = await Promise.all([
      getAdminCases(),
      getAdminSources(),
      getAdminModelConfig(),
      getAdminSessions(),
      getAdminReports(),
      getAdminInsights(),
      getTrainingSkillEffects(),
      getAdminEvaluations(),
      getTrainingSkillCandidates(),
      getAdminAuditEvents(),
    ]);
    setCases(nextCases);
    setSources(nextSources);
    setModelConfig(nextModelConfig);
    setSessions(nextSessions);
    setReports(nextReports);
    setInsights(nextInsights);
    setSkillEffects(nextSkillEffects);
    setEvaluations(nextEvaluations);
    setCandidates(nextCandidates);
    setAuditEvents(nextAuditEvents);
    setStatusText("已读取管理后台数据。");
    if (nextCases[0]) {
      const firstCaseRaw = await getAdminCaseRaw(nextCases[0].case_id);
      setSelectedCaseRaw(firstCaseRaw);
      setSelectedRubric(await getAdminRubric(firstCaseRaw.rubric_ref.rubric_id));
    }
    if (nextReports[0]) {
      setSelectedReport(nextReports[0]);
      setSelectedSessionId(nextReports[0].session_id);
      setSessionIdInput(nextReports[0].session_id);
    } else if (nextSessions[0]) {
      setSelectedSessionId(nextSessions[0].session_id);
      setSessionIdInput(nextSessions[0].session_id);
    }
    if (nextEvaluations[0]) {
      setSelectedEvaluation(await getAdminEvaluation(nextEvaluations[0].batch_id));
    }
    if (nextCandidates[0]) {
      const candidateId = nextCandidates[0].candidate_id;
      setSelectedCandidate(await getTrainingSkillCandidate(candidateId));
      setCandidateAuditEvents(await getTrainingSkillCandidateEvents(candidateId));
    }
  }

  useEffect(() => {
    loadDashboard().catch((error: unknown) => {
      const message = getAdminErrorMessage(error);
      setStatusText(message);
      setAdminLoginErrorText(message);
      if (shouldOpenAdminLoginDialog(error)) {
        setIsAdminLoginDialogOpen(true);
      }
    });
  }, []);

  async function handleAdminLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = adminEmail.trim();
    if (!email || !adminPassword) {
      const message = "请输入管理员邮箱和密码。";
      setAdminLoginErrorText(message);
      setStatusText(message);
      return;
    }
    setIsLoggingIn(true);
    try {
      const user = await loginAdminUser(email, adminPassword);
      setAdminLoginErrorText(null);
      setIsAdminLoginDialogOpen(false);
      setStatusText(`已登录管理员账号：${user.email}，正在读取管理后台数据...`);
      await loadDashboard();
    } catch (error: unknown) {
      const message = getAdminErrorMessage(error);
      setAdminLoginErrorText(message);
      setStatusText(message);
    } finally {
      setIsLoggingIn(false);
    }
  }

  function buildAdminCaseImportPayload(): AdminCaseImportPayload {
    return {
      case: parseAdminImportJson(caseImportJsonText, "病例 JSON"),
      rubric: parseAdminImportJson(rubricImportJsonText, "Rubric JSON"),
    };
  }

  function clearCaseImportResult() {
    setCaseImportResult(null);
    setValidatedCaseImport(null);
  }

  async function handleValidateCaseImport() {
    setIsCaseImportBusy(true);
    try {
      const result = await validateAdminCaseImport(buildAdminCaseImportPayload());
      setCaseImportResult(result);
      setValidatedCaseImport(result.valid ? { payloadKey: currentCaseImportPayloadKey, result } : null);
      setStatusText(getAdminCaseImportStatusText(result));
    } catch (error: unknown) {
      setCaseImportResult(null);
      setValidatedCaseImport(null);
      const message = getAdminErrorMessage(error);
      setStatusText(message);
      if (shouldOpenAdminLoginDialog(error)) {
        setAdminLoginErrorText(message);
        setIsAdminLoginDialogOpen(true);
      }
    } finally {
      setIsCaseImportBusy(false);
    }
  }

  async function handleImportCasePayload() {
    if (!canImportCasePayload) {
      setStatusText("请先对当前病例与 Rubric JSON 执行导入前预检。");
      return;
    }
    setIsCaseImportBusy(true);
    try {
      const result = await importAdminCasePayload(buildAdminCaseImportPayload());
      setCaseImportResult(result);
      setValidatedCaseImport(null);
      setStatusText(getAdminCaseImportStatusText(result));
      if (result.imported) {
        setCases(await getAdminCases());
        if (result.case_id) {
          const nextCaseRaw = await getAdminCaseRaw(result.case_id);
          setSelectedCaseRaw(nextCaseRaw);
          setSelectedRubric(await getAdminRubric(nextCaseRaw.rubric_ref.rubric_id));
        }
      }
    } catch (error: unknown) {
      setCaseImportResult(null);
      setValidatedCaseImport(null);
      const message = getAdminErrorMessage(error);
      setStatusText(message);
      if (shouldOpenAdminLoginDialog(error)) {
        setAdminLoginErrorText(message);
        setIsAdminLoginDialogOpen(true);
      }
    } finally {
      setIsCaseImportBusy(false);
    }
  }

  async function handleSelectCase(caseId: string) {
    const nextCaseRaw = await getAdminCaseRaw(caseId);
    setSelectedCaseRaw(nextCaseRaw);
    setSelectedRubric(await getAdminRubric(nextCaseRaw.rubric_ref.rubric_id));
    setStatusText("已选择病例来源台账。");
  }

  async function handleSelectSession(sessionId: string) {
    setSelectedSessionId(sessionId);
    setSessionIdInput(sessionId);
    setTrainingEvents(await getAdminSessionEvents(sessionId));
    try {
      setSelectedReport(await getAdminSessionReport(sessionId));
    } catch {
      setSelectedReport(null);
    }
  }

  function handleSelectReport(report: AdminSessionReport) {
    setSelectedReport(report);
    setSelectedSessionId(report.session_id);
    setSessionIdInput(report.session_id);
    setStatusText("已选择跨 Session 评分报告。");
  }

  async function handleLoadSessionEvents() {
    const sessionId = sessionIdInput.trim();
    if (!sessionId) {
      setStatusText("请输入 session_id 后读取训练日志。");
      return;
    }
    setSelectedSessionId(sessionId);
    setTrainingEvents(await getAdminSessionEvents(sessionId));
    setStatusText("已读取训练日志。");
  }

  async function handleLoadSessionReport() {
    const sessionId = sessionIdInput.trim();
    if (!sessionId) {
      setStatusText("请输入 session_id 后读取评分报告。");
      return;
    }
    setSelectedSessionId(sessionId);
    setSelectedReport(await getAdminSessionReport(sessionId));
    setStatusText("已读取评分报告。");
  }

  async function handleSelectEvaluation(batchId: string) {
    setSelectedEvaluation(await getAdminEvaluation(batchId));
  }

  async function handleRunEvaluation() {
    const batchId = `admin_manual_${Date.now()}`;
    setIsRunningEvaluation(true);
    setStatusText("正在运行系统评测...");
    try {
      const evaluation = await runAdminEvaluation(batchId);
      setEvaluations(await getAdminEvaluations());
      setSelectedEvaluation(evaluation);
      setStatusText(`系统评测已完成：${evaluation.passed_cases}/${evaluation.total_cases} 通过。`);
    } catch (error: unknown) {
      const message = getAdminErrorMessage(error);
      setStatusText(message);
      if (shouldOpenAdminLoginDialog(error)) {
        setAdminLoginErrorText(message);
        setIsAdminLoginDialogOpen(true);
      }
    } finally {
      setIsRunningEvaluation(false);
    }
  }

  async function handleGenerateTrainingSkillCandidates() {
    setIsGeneratingCandidates(true);
    setStatusText("正在从训练日志生成候选 Skill...");
    try {
      const result = await generateTrainingSkillCandidates();
      const [nextInsights, nextSkillEffects, nextCandidates, nextEvaluations, nextAuditEvents] = await Promise.all([
        getAdminInsights(),
        getTrainingSkillEffects(),
        getTrainingSkillCandidates(),
        getAdminEvaluations(),
        getAdminAuditEvents(),
      ]);
      setInsights(nextInsights);
      setSkillEffects(nextSkillEffects);
      setCandidates(nextCandidates);
      setEvaluations(nextEvaluations);
      setAuditEvents(nextAuditEvents);
      if (nextCandidates[0]) {
        const candidateId = nextCandidates[0].candidate_id;
        setSelectedCandidate(await getTrainingSkillCandidate(candidateId));
        setCandidateAuditEvents(await getTrainingSkillCandidateEvents(candidateId));
      } else {
        setSelectedCandidate(null);
        setCandidateAuditEvents([]);
      }
      setStatusText(`已从训练日志生成 ${result.generated_count} 个候选 Skill，${result.ready_for_review_count} 个进入审核，${result.blocked_by_regression_count} 个被回归阻塞。`);
    } catch (error: unknown) {
      const message = getAdminErrorMessage(error);
      setStatusText(message);
      if (shouldOpenAdminLoginDialog(error)) {
        setAdminLoginErrorText(message);
        setIsAdminLoginDialogOpen(true);
      }
    } finally {
      setIsGeneratingCandidates(false);
    }
  }

  async function handleSelectCandidate(candidateId: string) {
    setSelectedCandidate(await getTrainingSkillCandidate(candidateId));
    setCandidateAuditEvents(await getTrainingSkillCandidateEvents(candidateId));
  }

  async function handleReview(action: "approve" | "reject") {
    if (!selectedCandidate) {
      return;
    }
    if (selectedCandidate.review.status !== "ready_for_review") {
      setStatusText(`候选已审核，当前状态为 ${selectedCandidate.review.status}，不能重复审核。`);
      return;
    }
    if (action === "approve") {
      await approveTrainingSkillCandidate(selectedCandidate.candidate_id);
    } else {
      await rejectTrainingSkillCandidate(selectedCandidate.candidate_id);
    }
    const [nextCandidates, nextAuditEvents, nextSkillEffects] = await Promise.all([
      getTrainingSkillCandidates(),
      getAdminAuditEvents(),
      getTrainingSkillEffects(),
    ]);
    setCandidates(nextCandidates);
    setAuditEvents(nextAuditEvents);
    setSkillEffects(nextSkillEffects);
    setSelectedCandidate(await getTrainingSkillCandidate(selectedCandidate.candidate_id));
    setCandidateAuditEvents(await getTrainingSkillCandidateEvents(selectedCandidate.candidate_id));
    setStatusText(action === "approve" ? "已批准并启用候选 Skill。" : "已拒绝候选 Skill。");
  }

  const canReviewSelectedCandidate = selectedCandidate?.review.status === "ready_for_review";

  return (
    <main className="min-h-screen bg-[#FAF9F5] px-6 py-8 text-[#141413]">
      <div className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(circle_at_20%_20%,rgba(174,86,48,0.10),transparent_30%),linear-gradient(135deg,rgba(255,255,255,0.75),rgba(250,249,245,0.35))]" />
      <div className={isAdminLoginDialogOpen ? "pointer-events-none blur-sm" : ""}>
        <div className="mx-auto max-w-7xl">
        <header className="rounded-[2rem] border border-[#E6DFD2] bg-white/75 p-6 shadow-sm backdrop-blur">
          <p className="text-xs font-medium uppercase tracking-[0.28em] text-[#8A7D6F]">Clinical OSCE Agent Admin</p>
          <div className="mt-3 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h1 className="text-3xl font-semibold tracking-tight">Clinical OSCE 管理后台</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-[#6F6257]">
                教师视角查看训练 Session、评分报告、系统评测、训练日志，并审核受控进化产生的候选 Skill。
              </p>
            </div>
            <div className="flex flex-col gap-2 sm:items-end">
              <p className="rounded-full border border-[#AE5630]/20 bg-[#AE5630]/10 px-4 py-2 text-xs font-medium text-[#AE5630]">{statusText}</p>
              <button
                className="rounded-md border border-[#AE5630] bg-white px-4 py-2 text-sm font-semibold whitespace-nowrap text-[#AE5630] transition hover:bg-[#AE5630]/10"
                onClick={() => setIsAdminLoginDialogOpen(true)}
                type="button"
              >
                管理员登录
              </button>
            </div>
          </div>
        </header>

        <section className="mt-5 grid gap-3 md:grid-cols-5">
          <article className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-4 shadow-sm">
            <p className="text-xs text-[#8A7D6F]">总览 · 训练 Session</p>
            <p className="mt-2 text-3xl font-semibold">{sessions.length}</p>
          </article>
          <article className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-4 shadow-sm">
            <p className="text-xs text-[#8A7D6F]">总览 · 错误模式</p>
            <p className="mt-2 text-3xl font-semibold">{insights ? insights.frequent_missed_items.length : "—"}</p>
          </article>
          <article className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-4 shadow-sm">
            <p className="text-xs text-[#8A7D6F]">总览 · 候选 Skill</p>
            <p className="mt-2 text-3xl font-semibold">{candidates.length}</p>
          </article>
          <article className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-4 shadow-sm">
            <p className="text-xs text-[#8A7D6F]">总览 · 系统评测</p>
            <p className="mt-2 text-3xl font-semibold">{evaluations.length}</p>
          </article>
          <article className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-4 shadow-sm">
            <p className="text-xs text-[#8A7D6F]">总览 · 当前报告</p>
            <p className="mt-2 text-3xl font-semibold">{selectedReport ? selectedReport.total_score : "—"}</p>
          </article>
        </section>

        <section className="mt-5 rounded-2xl border border-[#E6DFD2] bg-white/70 p-5 shadow-sm" id="model-config">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.22em] text-[#8A7D6F]">Model Configuration</p>
              <h2 className="mt-1 text-xl font-semibold">模型 / API 配置</h2>
              <p className="mt-2 text-sm leading-6 text-[#6F6257]">统一查看 Gemini、Vertex 和 OpenAI 兼容模型的启用状态；密钥不落库，可来自环境变量、本地 .env 或本次运行时内存配置。</p>
            </div>
            <p className="rounded-full border border-[#AE5630]/20 bg-[#AE5630]/10 px-3 py-1 text-xs text-[#AE5630]">
              {modelConfig ? `配置来源：${modelConfig.policy.configuration_source}` : "读取中"}
            </p>
          </div>
          {modelConfig ? (
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              {modelConfig.providers.map((provider) => (
                <article className="rounded-xl border border-[#E6DFD2] bg-[#FAF9F5] p-4" key={provider.provider_id}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="text-sm font-semibold">{provider.label}</p>
                      <p className="mt-1 text-xs leading-5 text-[#6F6257]">{provider.capability}</p>
                    </div>
                    <span className={`rounded-full border px-2 py-1 text-[11px] ${provider.configured ? "border-green-200 bg-green-50 text-green-700" : "border-[#E6DFD2] bg-white text-[#6F6257]"}`}>
                      {provider.configured ? "已配置" : provider.enabled ? "缺少配置" : "未启用"}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-2 text-xs text-[#6F6257] sm:grid-cols-2">
                    <p>模型：{provider.model || "未设置"}</p>
                    <p>认证：{provider.auth_mode}</p>
                    <p>密钥：{provider.secret_configured ? "已配置" : "未配置 / 使用 ADC"}</p>
                    <p>状态：{provider.integration_status}</p>
                    {provider.base_url ? <p className="break-words">Base URL：{provider.base_url}</p> : null}
                    {provider.project ? <p className="break-words">Project：{provider.project}</p> : null}
                    {provider.location ? <p>Location：{provider.location}</p> : null}
                    {provider.proxy_url ? <p className="break-words">Proxy：{provider.proxy_url}</p> : null}
                  </div>
                  <p className="mt-3 text-xs leading-5 text-[#6F6257]">{provider.notes}</p>
                  {provider.missing_env.length > 0 ? (
                    <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">缺少：{provider.missing_env.join("、")}</p>
                  ) : null}
                  <p className="mt-2 text-[11px] leading-5 text-[#8A7D6F]">环境变量：{provider.required_env.join("、")}</p>
                </article>
              ))}
            </div>
          ) : (
            <p className="mt-4 rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">正在读取模型 / API 配置。</p>
          )}
        </section>

        <section className="mt-5 rounded-2xl border border-[#E6DFD2] bg-white/70 p-5 shadow-sm">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.22em] text-[#8A7D6F]">Case Ledger</p>
              <h2 className="mt-1 text-xl font-semibold">病例与来源台账</h2>
              <p className="mt-2 text-sm leading-6 text-[#6F6257]">只读核对病例、Rubric 引用、来源追踪与医学安全边界，不在管理端直接修改医学事实。</p>
            </div>
            <p className="rounded-full border border-[#AE5630]/20 bg-[#AE5630]/10 px-3 py-1 text-xs text-[#AE5630]">{filteredCases.length}/{cases.length} 个病例</p>
          </div>
          <input
            aria-label="筛选病例"
            className="mt-4 w-full rounded-md border border-[#E6DFD2] bg-white px-3 py-2 text-sm outline-none transition focus:border-[#AE5630]"
            onChange={(event) => setCaseSearchText(event.target.value)}
            placeholder="筛选病例 / 主诉"
            type="search"
            value={caseSearchText}
          />
          <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
            <div className="grid max-h-80 gap-2 overflow-y-auto pr-1">
              {filteredCases.length > 0 ? (
                filteredCases.map((caseItem) => (
                  <button
                    className={`rounded-xl border p-3 text-left transition ${
                      selectedCaseRaw?.case_id === caseItem.case_id
                        ? "border-[#AE5630] bg-[#AE5630]/10"
                        : "border-[#E6DFD2] bg-[#FAF9F5] hover:border-[#AE5630]"
                    }`}
                    key={caseItem.case_id}
                    onClick={() => void handleSelectCase(caseItem.case_id)}
                    type="button"
                  >
                    <span className="text-sm font-semibold">{caseItem.case_title}</span>
                    <span className="mt-1 block text-xs text-[#6F6257]">{caseItem.course_module} · {caseItem.difficulty}</span>
                    <span className="mt-1 block text-[11px] text-[#8A7D6F]">{caseItem.chief_complaint}</span>
                  </button>
                ))
              ) : (
                <p className="rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">{cases.length > 0 ? "没有匹配的病例台账。" : "暂无病例台账。"}</p>
              )}
            </div>
            {selectedCaseRaw ? (
              <article className="rounded-2xl border border-[#E6DFD2] bg-[#FAF9F5] p-4">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="font-mono text-[11px] text-[#AE5630]">{selectedCaseRaw.case_id}</p>
                    <h3 className="mt-1 text-lg font-semibold">{selectedCaseRaw.case_title}</h3>
                    <p className="mt-1 text-sm leading-6 text-[#6F6257]">{selectedCaseRaw.chief_complaint}</p>
                  </div>
                  <span className="rounded-full border border-[#E6DFD2] bg-white px-3 py-1 text-xs text-[#6F6257]">{selectedCaseRaw.course_module} · {selectedCaseRaw.difficulty}</span>
                </div>
                <div className="mt-4 grid gap-3 md:grid-cols-4">
                  <div className="rounded-xl border border-[#E6DFD2] bg-white p-3">
                    <p className="text-xs text-[#8A7D6F]">hidden_facts</p>
                    <p className="mt-1 text-2xl font-semibold">{selectedCaseRaw.history.hidden_facts.length}</p>
                  </div>
                  <div className="rounded-xl border border-[#E6DFD2] bg-white p-3">
                    <p className="text-xs text-[#8A7D6F]">查体项</p>
                    <p className="mt-1 text-2xl font-semibold">{selectedCaseRaw.physical_exam.must_items.length + selectedCaseRaw.physical_exam.optional_items.length}</p>
                  </div>
                  <div className="rounded-xl border border-[#E6DFD2] bg-white p-3">
                    <p className="text-xs text-[#8A7D6F]">辅助检查</p>
                    <p className="mt-1 text-2xl font-semibold">{selectedCaseRaw.auxiliary_tests.must_items.length + selectedCaseRaw.auxiliary_tests.optional_items.length}</p>
                  </div>
                  <div className="rounded-xl border border-[#E6DFD2] bg-white p-3">
                    <p className="text-xs text-[#8A7D6F]">reasoning_points</p>
                    <p className="mt-1 text-2xl font-semibold">{selectedCaseRaw.diagnosis.reasoning_points.length}</p>
                  </div>
                </div>
                <dl className="mt-4 grid gap-3 text-sm md:grid-cols-3">
                  <div className="rounded-xl border border-[#E6DFD2] bg-white p-3">
                    <dt className="text-xs font-semibold text-[#141413]">Rubric 引用</dt>
                    <dd className="mt-2 text-[#6F6257]">{selectedCaseRaw.rubric_ref.rubric_id} · {selectedCaseRaw.rubric_ref.version}</dd>
                  </div>
                  <div className="rounded-xl border border-[#E6DFD2] bg-white p-3">
                    <dt className="text-xs font-semibold text-[#141413]">来源追踪</dt>
                    <dd className="mt-2 text-[#6F6257]">{selectedCaseRaw.source_attribution.source_id} · {selectedCaseRaw.source_attribution.modified ? "已教学改写" : "原始登记"}</dd>
                    <dd className="mt-2 text-xs leading-5 text-[#8A7D6F]">source_attribution：{selectedCaseRaw.source_attribution.attribution_note}</dd>
                  </div>
                  <div className="rounded-xl border border-[#E6DFD2] bg-white p-3">
                    <dt className="text-xs font-semibold text-[#141413]">医学安全边界</dt>
                    <dd className="mt-2 text-[#6F6257]">{selectedCaseRaw.safety_notes}</dd>
                  </div>
                </dl>
                {selectedRubric ? (
                  <section className="mt-4 rounded-xl border border-[#E6DFD2] bg-white p-4">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <p className="text-xs font-semibold text-[#AE5630]">Rubric 评分表详情</p>
                        <h4 className="mt-1 text-sm font-semibold">{selectedRubric.rubric_id}</h4>
                        <p className="mt-1 text-xs text-[#8A7D6F]">schema_version：{selectedRubric.schema_version}</p>
                      </div>
                      <p className="rounded-full border border-[#AE5630]/20 bg-[#AE5630]/10 px-3 py-1 text-xs text-[#AE5630]">total_score：{selectedRubric.total_score}</p>
                    </div>
                    <div className="mt-3 grid gap-3">
                      {selectedRubric.dimensions.map((dimension) => (
                        <article className="rounded-lg border border-[#E6DFD2] bg-[#FAF9F5] p-3" key={dimension.dimension_id}>
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="text-xs font-semibold text-[#141413]">评分维度：{dimension.dimension_id}</p>
                            <p className="text-[11px] text-[#8A7D6F]">{dimension.scoring_mode} · 权重 {dimension.weight}</p>
                          </div>
                          <div className="mt-2 grid gap-2">
                            {dimension.items.map((item) => (
                              <div className="rounded-md border border-[#E6DFD2] bg-white p-3 text-xs leading-5 text-[#6F6257]" key={item.item_id}>
                                <p className="font-semibold text-[#141413]">评分项：{item.item_id} · {item.max_score} 分</p>
                                <p className="mt-1">{item.description}</p>
                                <p className="mt-1">match_rule：{item.match_rule.kind}</p>
                                <p className="mt-1">evidence_expected：{item.evidence_expected.length > 0 ? item.evidence_expected.join("、") : "无"}</p>
                              </div>
                            ))}
                          </div>
                        </article>
                      ))}
                    </div>
                  </section>
                ) : (
                  <p className="mt-4 rounded-xl border border-dashed border-[#E6DFD2] bg-white p-4 text-sm text-[#6F6257]">Rubric 详情待读取。</p>
                )}
              </article>
            ) : (
              <p className="rounded-2xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">请选择一个病例查看 Rubric 与来源台账。</p>
            )}
          </div>
          <section className="mt-4 rounded-2xl border border-[#E6DFD2] bg-[#FAF9F5] p-4">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <p className="text-xs font-semibold text-[#AE5630]">病例 / Rubric 导入</p>
                <h3 className="mt-1 text-sm font-semibold">受控新增正式教学资产</h3>
                <p className="mt-1 text-xs leading-5 text-[#8A7D6F]">粘贴已解析为 JSON object 的病例与 Rubric，先导入前预检，再正式导入；后端会拒绝覆盖已有 case_id 或 rubric_id。</p>
              </div>
              <p className="rounded-full border border-[#AE5630]/20 bg-[#AE5630]/10 px-3 py-1 text-xs text-[#AE5630]">valid=false / imported=false 会保留错误列表</p>
            </div>
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              <label className="grid gap-2 text-xs font-semibold text-[#141413]">
                粘贴病例 JSON
                <textarea
                  className="min-h-52 rounded-xl border border-[#E6DFD2] bg-white p-3 font-mono text-xs leading-5 text-[#6F6257] outline-none transition focus:border-[#AE5630]"
                  onChange={(event) => {
                    setCaseImportJsonText(event.target.value);
                    clearCaseImportResult();
                  }}
                  placeholder="{\n  &quot;case_id&quot;: &quot;new_case_001&quot;\n}"
                  value={caseImportJsonText}
                />
              </label>
              <label className="grid gap-2 text-xs font-semibold text-[#141413]">
                粘贴 Rubric JSON
                <textarea
                  className="min-h-52 rounded-xl border border-[#E6DFD2] bg-white p-3 font-mono text-xs leading-5 text-[#6F6257] outline-none transition focus:border-[#AE5630]"
                  onChange={(event) => {
                    setRubricImportJsonText(event.target.value);
                    clearCaseImportResult();
                  }}
                  placeholder="{\n  &quot;rubric_id&quot;: &quot;new_case_001_rubric&quot;\n}"
                  value={rubricImportJsonText}
                />
              </label>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                className="rounded-md border border-[#AE5630] bg-white px-3 py-2 text-sm font-medium whitespace-nowrap text-[#AE5630] transition hover:bg-[#AE5630]/10 disabled:cursor-not-allowed disabled:opacity-60"
                disabled={isCaseImportBusy}
                onClick={() => void handleValidateCaseImport()}
                type="button"
              >
                导入前预检
              </button>
              <button
                className="rounded-md border border-[#AE5630] bg-[#AE5630] px-3 py-2 text-sm font-medium whitespace-nowrap text-white transition hover:bg-[#C4633A] disabled:cursor-not-allowed disabled:opacity-60"
                disabled={!canImportCasePayload}
                onClick={() => void handleImportCasePayload()}
                type="button"
              >
                正式导入
              </button>
              {caseImportResult ? (
                <p className="rounded-full border border-[#E6DFD2] bg-white px-3 py-2 text-xs text-[#6F6257]">{getAdminCaseImportStatusText(caseImportResult)}</p>
              ) : (
                <p className="text-xs text-[#8A7D6F]">导入成功后会刷新病例台账并选中新病例。</p>
              )}
            </div>
          </section>

          <section className="mt-4 rounded-2xl border border-[#E6DFD2] bg-[#FAF9F5] p-4">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <p className="text-xs font-semibold text-[#AE5630]">数据来源登记表</p>
                <h3 className="mt-1 text-sm font-semibold">公开来源与许可核对</h3>
                <p className="mt-1 text-xs leading-5 text-[#8A7D6F]">核对 source_id、source_url、allowed_usage、attribution_required 和 risk_note，确保病例来源链路可追踪。</p>
              </div>
              <p className="rounded-full border border-[#AE5630]/20 bg-[#AE5630]/10 px-3 py-1 text-xs text-[#AE5630]">{sources.length} 条来源</p>
            </div>
            <div className="mt-3 grid max-h-80 gap-3 overflow-y-auto pr-1 md:grid-cols-2">
              {sources.length > 0 ? (
                sources.map((source) => (
                  <article className="rounded-xl border border-[#E6DFD2] bg-white p-3 text-xs leading-5 text-[#6F6257]" key={source.source_id}>
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p className="font-mono text-[11px] text-[#AE5630]">{source.source_id}</p>
                        <h4 className="mt-1 text-sm font-semibold text-[#141413]">{source.source_name}</h4>
                      </div>
                      <span className="rounded-full border border-[#E6DFD2] bg-[#FAF9F5] px-2 py-1 text-[11px] text-[#6F6257]">{source.license}</span>
                    </div>
                    <p className="mt-2">source_url：{source.source_url}</p>
                    <p className="mt-1">allowed_usage：{source.allowed_usage.join("、")}</p>
                    <p className="mt-1">attribution_required：{source.attribution_required ? "需要署名" : "无需署名"}</p>
                    <p className="mt-1">转换方式：{source.transformation}</p>
                    <p className="mt-1">risk_note：{source.risk_note}</p>
                  </article>
                ))
              ) : (
                <p className="rounded-xl border border-dashed border-[#E6DFD2] bg-white p-4 text-sm text-[#6F6257]">暂无数据来源登记。</p>
              )}
            </div>
          </section>
        </section>

        <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
          <div className="grid gap-5">
            <section className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-5 shadow-sm">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.22em] text-[#8A7D6F]">Training Sessions</p>
                  <h2 className="mt-1 text-xl font-semibold">训练 Session</h2>
                </div>
                <div className="flex gap-2">
                  <input
                    className="min-w-0 rounded-md border border-[#E6DFD2] bg-white px-3 py-2 text-sm outline-none transition focus:border-[#AE5630]"
                    onChange={(event) => setSessionIdInput(event.target.value)}
                    placeholder="输入 session_id"
                    type="text"
                    value={sessionIdInput}
                  />
                  <button
                    className="rounded-md border border-[#AE5630] bg-[#AE5630] px-3 py-2 text-sm font-medium whitespace-nowrap text-white transition hover:bg-[#C4633A]"
                    onClick={() => void handleLoadSessionReport()}
                    type="button"
                  >
                    读报告
                  </button>
                  <button
                    className="rounded-md border border-[#E6DFD2] bg-white px-3 py-2 text-sm font-medium whitespace-nowrap text-[#6F6257] transition hover:bg-[#F1ECE2]"
                    onClick={() => void handleLoadSessionEvents()}
                    type="button"
                  >
                    读日志
                  </button>
                </div>
              </div>
              <input
                aria-label="筛选训练 Session"
                className="mt-4 w-full rounded-md border border-[#E6DFD2] bg-white px-3 py-2 text-sm outline-none transition focus:border-[#AE5630]"
                onChange={(event) => setSessionSearchText(event.target.value)}
                placeholder="筛选 session / 用户 / 状态"
                type="search"
                value={sessionSearchText}
              />
              <div className="mt-4 grid max-h-80 gap-2 overflow-y-auto pr-1">
                {filteredSessions.length > 0 ? (
                  filteredSessions.map((session) => (
                    <button
                      className={`rounded-xl border p-3 text-left transition ${
                        selectedSessionId === session.session_id
                          ? "border-[#AE5630] bg-[#AE5630]/10"
                          : "border-[#E6DFD2] bg-[#FAF9F5] hover:border-[#AE5630]"
                      }`}
                      key={session.session_id}
                      onClick={() => void handleSelectSession(session.session_id)}
                      type="button"
                    >
                      <span className="text-sm font-semibold">{session.case_id}</span>
                      <span className="mt-1 block text-xs text-[#6F6257]">
                        {session.session_id} · {session.student_id} · {session.stage}
                      </span>
                      <span className="mt-1 block text-[11px] text-[#8A7D6F]">更新：{session.updated_at}</span>
                    </button>
                  ))
                ) : (
                  <p className="rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">{sessions.length > 0 ? "没有匹配的训练 Session。" : "暂无训练 Session。"}</p>
                )}
              </div>
            </section>

            <section className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.22em] text-[#8A7D6F]">Reports</p>
                  <h2 className="mt-1 text-xl font-semibold">跨 Session 报告列表</h2>
                </div>
                <p className="rounded-full border border-[#AE5630]/20 bg-[#AE5630]/10 px-3 py-1 text-xs text-[#AE5630]">
                  {filteredReports.length}/{reports.length} 份报告
                </p>
              </div>
              <input
                aria-label="筛选评分报告"
                className="mt-4 w-full rounded-md border border-[#E6DFD2] bg-white px-3 py-2 text-sm outline-none transition focus:border-[#AE5630]"
                onChange={(event) => setReportSearchText(event.target.value)}
                placeholder="筛选报告 / 病例 / 学员"
                type="search"
                value={reportSearchText}
              />
              <div className="mt-4 grid max-h-80 gap-2 overflow-y-auto pr-1">
                {filteredReports.length > 0 ? (
                  filteredReports.map((report) => (
                    <button
                      className={`rounded-xl border p-3 text-left transition ${
                        selectedReport?.report_id === report.report_id
                          ? "border-[#AE5630] bg-[#AE5630]/10"
                          : "border-[#E6DFD2] bg-[#FAF9F5] hover:border-[#AE5630]"
                      }`}
                      key={report.report_id}
                      onClick={() => handleSelectReport(report)}
                      type="button"
                    >
                      <span className="text-sm font-semibold">{report.report_id}</span>
                      <span className="mt-1 block text-xs text-[#6F6257]">
                        {report.case_id} · {report.student_id} · {report.total_score} 分
                      </span>
                      <span className="mt-1 block text-[11px] text-[#8A7D6F]">Session：{report.session_id}</span>
                    </button>
                  ))
                ) : (
                  <p className="rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">{reports.length > 0 ? "没有匹配的评分报告。" : "暂无评分报告。"}</p>
                )}
              </div>
            </section>

            <section className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-5 shadow-sm">
              <h2 className="text-xl font-semibold">评分报告</h2>
              {selectedReport ? (
                <div className="mt-4 grid gap-4">
                  <div className="rounded-xl border border-[#E6DFD2] bg-[#FAF9F5] p-4">
                    <p className="text-xs text-[#8A7D6F]">{selectedReport.report_id}</p>
                    <p className="mt-2 text-3xl font-semibold">{selectedReport.total_score} 分</p>
                    <p className="mt-1 text-sm text-[#6F6257]">
                      {selectedReport.case_id} · {selectedReport.student_id}
                    </p>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {Object.entries(selectedReport.dimension_scores).map(([key, score]) => (
                      <p className="rounded-lg border border-[#E6DFD2] bg-white p-3 text-sm" key={key}>
                        {key}：<span className="font-semibold text-[#AE5630]">{score}</span>
                      </p>
                    ))}
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold">常见漏项</h3>
                    <p className="mt-2 text-sm leading-6 text-[#6F6257]">
                      {selectedReport.missed_items.length > 0 ? selectedReport.missed_items.join("、") : "暂无漏项。"}
                    </p>
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold">学习建议</h3>
                    <div className="mt-2 grid gap-2">
                      {selectedReport.knowledge_recommendations.map((recommendation) => (
                        <p className="rounded-lg border border-[#E6DFD2] bg-white p-3 text-sm text-[#6F6257]" key={recommendation.reference}>
                          {recommendation.title} · {recommendation.reference}
                        </p>
                      ))}
                    </div>
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold">RAG 来源引用</h3>
                    <div className="mt-2 grid gap-2">
                      {getReportSourceReferenceItems(selectedReport).length > 0 ? (
                        getReportSourceReferenceItems(selectedReport).map((item) => {
                          const metadataText = getSourceReferenceMetadataText(item.metadata);
                          return (
                            <div className="rounded-lg border border-[#E6DFD2] bg-white p-3 text-sm text-[#6F6257]" key={item.reference}>
                              <p className="font-semibold text-[#141413]">{item.title}</p>
                              <p className="mt-1 break-all font-mono text-xs">{item.reference}</p>
                              <p className="mt-1 text-xs text-[#8A7D6F]">类型：{item.source_type}</p>
                              {metadataText ? <p className="mt-1 break-all text-xs text-[#8A7D6F]">{metadataText}</p> : null}
                            </div>
                          );
                        })
                      ) : (
                        <p className="rounded-lg border border-dashed border-[#E6DFD2] bg-white p-3 text-sm text-[#6F6257]">
                          当前报告暂无结构化来源引用。
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <p className="mt-4 rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">
                  选择训练 Session 或输入 session_id 后读取评分报告。
                </p>
              )}
            </section>

            <section className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-5 shadow-sm">
              <h2 className="text-xl font-semibold">训练日志</h2>
              <div className="mt-3 grid max-h-80 gap-2 overflow-y-auto pr-1">
                {trainingEvents.length > 0 ? (
                  trainingEvents.map((event) => (
                    <div className="rounded-lg border border-[#E6DFD2] bg-[#FAF9F5] p-3" key={`${event.created_at}-${event.event_type}`}>
                      <p className="text-[11px] text-[#8A7D6F]">{event.created_at}</p>
                      <p className="mt-1 text-xs font-semibold text-[#141413]">事件类型：{event.event_type}</p>
                      <p className="mt-1 text-xs text-[#6F6257]">病例：{event.case_id} · 学生：{event.student_id}</p>
                      <pre className="mt-2 whitespace-pre-wrap break-words rounded-md bg-white p-2 text-[11px] leading-5 text-[#6F6257]">
                        事件内容：{JSON.stringify(event.payload, null, 2)}
                      </pre>
                    </div>
                  ))
                ) : (
                  <p className="rounded-lg border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-3 text-sm text-[#6F6257]">选择训练 Session 或输入 session_id 后读取训练日志。</p>
                )}
              </div>
            </section>
          </div>

          <div className="grid gap-5">
            <section className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.22em] text-[#8A7D6F]">Error Patterns</p>
                  <h2 className="mt-1 text-xl font-semibold">错误模式统计</h2>
                </div>
                <p className="rounded-full border border-[#AE5630]/20 bg-[#AE5630]/10 px-3 py-1 text-xs text-[#AE5630]">
                  {insights ? `${insights.report_count} 份报告` : "待读取"}
                </p>
              </div>
              {insights ? (
                <div className="mt-4 grid gap-4">
                  <div>
                    <h3 className="text-sm font-semibold">常见漏项</h3>
                    <div className="mt-2 grid gap-2">
                      {insights.frequent_missed_items.length > 0 ? (
                        insights.frequent_missed_items.map((item) => (
                          <div className="rounded-xl border border-[#E6DFD2] bg-[#FAF9F5] p-3" key={item.item_id}>
                            <div className="flex items-center justify-between gap-3">
                              <p className="text-sm font-semibold">{item.item_id}</p>
                              <span className="rounded-full bg-[#AE5630]/10 px-2 py-1 text-xs text-[#AE5630]">{item.count} 次</span>
                            </div>
                            <p className="mt-2 text-xs leading-5 text-[#6F6257]">涉及病例：{item.case_ids.join("、")}</p>
                          </div>
                        ))
                      ) : (
                        <p className="rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-3 text-sm text-[#6F6257]">暂无常见漏项。</p>
                      )}
                    </div>
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold">学习建议</h3>
                    <div className="mt-2 grid gap-2">
                      {insights.frequent_learning_recommendations.length > 0 ? (
                        insights.frequent_learning_recommendations.map((recommendation) => (
                          <p className="rounded-xl border border-[#E6DFD2] bg-white p-3 text-sm leading-6 text-[#6F6257]" key={recommendation.reference}>
                            {recommendation.title} · {recommendation.count} 次 · {recommendation.reference}
                          </p>
                        ))
                      ) : (
                        <p className="rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-3 text-sm text-[#6F6257]">暂无高频学习建议。</p>
                      )}
                    </div>
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold">高频 RAG 来源</h3>
                    <div className="mt-2 grid gap-2">
                      {insights.frequent_source_references.length > 0 ? (
                        insights.frequent_source_references.map((sourceReference) => {
                          const metadataText = getSourceReferenceMetadataText(sourceReference.metadata);
                          return (
                            <article className="rounded-xl border border-[#E6DFD2] bg-white p-3 text-sm leading-6 text-[#6F6257]" key={sourceReference.reference}>
                              <div className="flex flex-wrap items-start justify-between gap-2">
                                <div>
                                  <p className="font-semibold text-[#141413]">{sourceReference.title}</p>
                                  <p className="font-mono text-[11px] text-[#AE5630]">{sourceReference.reference}</p>
                                </div>
                                <span className="rounded-full bg-[#AE5630]/10 px-2 py-1 text-xs text-[#AE5630]">{sourceReference.count} 次</span>
                              </div>
                              <p className="mt-2 text-xs text-[#8A7D6F]">类型：{getSourceReferenceLabel(sourceReference.reference)} · 涉及病例：{sourceReference.case_ids.join("、")}</p>
                              {metadataText ? <p className="mt-1 text-xs text-[#8A7D6F]">{metadataText}</p> : null}
                            </article>
                          );
                        })
                      ) : (
                        <p className="rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-3 text-sm text-[#6F6257]">暂无高频 RAG 来源。</p>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <p className="mt-4 rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">正在读取错误模式统计。</p>
              )}
            </section>

            <section className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-5 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-xl font-semibold">系统评测</h2>
                <button
                  className="rounded-md border border-[#AE5630] bg-[#AE5630] px-3 py-2 text-sm font-medium whitespace-nowrap text-white transition hover:bg-[#C4633A] disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={isRunningEvaluation}
                  onClick={() => void handleRunEvaluation()}
                  type="button"
                >
                  {isRunningEvaluation ? "运行中" : "运行系统评测"}
                </button>
              </div>
              <article className="mt-4 rounded-xl border border-[#E6DFD2] bg-[#FAF9F5] p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-[0.22em] text-[#8A7D6F]">Evaluation Metrics</p>
                    <h3 className="mt-1 text-sm font-semibold">系统评测图表摘要</h3>
                  </div>
                  <p className="rounded-full border border-[#AE5630]/20 bg-[#AE5630]/10 px-3 py-1 text-xs text-[#AE5630]">
                    最近耗时 {evaluationChartSummary.latestDurationMs} ms
                  </p>
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-4">
                  <div className="rounded-lg border border-[#E6DFD2] bg-white p-3">
                    <p className="text-xs text-[#8A7D6F]">批次数</p>
                    <p className="mt-1 text-2xl font-semibold">{evaluationChartSummary.batchCount}</p>
                  </div>
                  <div className="rounded-lg border border-[#E6DFD2] bg-white p-3">
                    <p className="text-xs text-[#8A7D6F]">总用例</p>
                    <p className="mt-1 text-2xl font-semibold">{evaluationChartSummary.totalCases}</p>
                  </div>
                  <div className="rounded-lg border border-[#E6DFD2] bg-white p-3">
                    <p className="text-xs text-[#8A7D6F]">通过率</p>
                    <p className="mt-1 text-2xl font-semibold">{evaluationChartSummary.passRatePercent}</p>
                  </div>
                  <div className="rounded-lg border border-[#E6DFD2] bg-white p-3">
                    <p className="text-xs text-[#8A7D6F]">失败用例</p>
                    <p className="mt-1 text-2xl font-semibold">{evaluationChartSummary.failedCases}</p>
                  </div>
                </div>
                <div className="mt-4 grid gap-3">
                  <div>
                    <div className="flex items-center justify-between text-xs text-[#6F6257]">
                      <span>通过率</span>
                      <span>{evaluationChartSummary.passedCases}/{evaluationChartSummary.totalCases}</span>
                    </div>
                    <div className="mt-1 h-2 overflow-hidden rounded-full bg-[#E6DFD2]">
                      <div className="h-full rounded-full bg-[#2F6868]" style={{ width: evaluationChartSummary.passRatePercent }} />
                    </div>
                  </div>
                  <div>
                    <div className="flex items-center justify-between text-xs text-[#6F6257]">
                      <span>失败率</span>
                      <span>{evaluationChartSummary.failedCases}/{evaluationChartSummary.totalCases}</span>
                    </div>
                    <div className="mt-1 h-2 overflow-hidden rounded-full bg-[#E6DFD2]">
                      <div className="h-full rounded-full bg-[#AE5630]" style={{ width: evaluationChartSummary.failureRatePercent }} />
                    </div>
                  </div>
                </div>
              </article>
              <div className="mt-4 grid gap-2">
                {evaluations.length > 0 ? (
                  evaluations.map((evaluation) => (
                    <button
                      className="rounded-xl border border-[#E6DFD2] bg-[#FAF9F5] p-3 text-left transition hover:border-[#AE5630]"
                      key={evaluation.batch_id}
                      onClick={() => void handleSelectEvaluation(evaluation.batch_id)}
                      type="button"
                    >
                      <span className="text-sm font-semibold">{evaluation.batch_id}</span>
                      <span className="mt-1 block text-xs text-[#6F6257]">
                        {getPassLabel(evaluation.passed)} · 通过 {evaluation.passed_cases}/{evaluation.total_cases} · 通过率 {getPercent(evaluation.passed_cases, evaluation.total_cases)}
                      </span>
                    </button>
                  ))
                ) : (
                  <p className="rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">暂无系统评测批次。</p>
                )}
              </div>
              {selectedEvaluation ? (
                <article className="mt-4 rounded-xl border border-[#E6DFD2] bg-[#FAF9F5] p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-medium text-[#AE5630]">{getPassLabel(selectedEvaluation.passed)}</p>
                      <h3 className="mt-1 text-sm font-semibold">{selectedEvaluation.batch_id}</h3>
                    </div>
                    <button
                      className="rounded-md border border-[#2F6868] bg-white px-3 py-2 text-xs font-medium whitespace-nowrap text-[#2F6868] transition hover:bg-[#E7F0EC]"
                      onClick={() => downloadEvaluationBatchJson(selectedEvaluation)}
                      type="button"
                    >
                      导出评测 JSON
                    </button>
                  </div>
                  <p className="mt-2 text-sm text-[#6F6257]">
                    通过 {selectedEvaluation.passed_cases}/{selectedEvaluation.total_cases} 例 · 耗时 {selectedEvaluation.total_duration_ms} ms
                  </p>
                  <div className="mt-3 grid gap-2">
                    {selectedEvaluation.results.map((result) => (
                      <article className="rounded-lg border border-[#E6DFD2] bg-white p-3 text-xs text-[#6F6257]" key={result.session_id}>
                        <p>
                          {result.session_id} · {getPassLabel(result.passed)} · 实际 {result.actual_total_score} / 期望 {result.expected_total_score}
                        </p>
                        <p className="mt-2 text-[#8A7D6F]">
                          RAG 引用覆盖：{result.rag_source_coverage_passed ? "通过" : "未通过"} · rubric 覆盖率 {Math.round(result.rag_rubric_reference_coverage_ratio * 100)}% · 来源 {result.source_reference_count} 条 · 类型 {result.source_reference_types.length > 0 ? result.source_reference_types.join("、") : "无"}
                        </p>
                        {result.missing_rubric_references.length > 0 ? (
                          <p className="mt-1 font-mono text-[11px] text-[#AE5630]">缺失引用：{result.missing_rubric_references.join("、")}</p>
                        ) : null}
                        <p className="mt-1 text-[#8A7D6F]">
                          解释覆盖率 {Math.round(result.rag_explanation_coverage_ratio * 100)}% · 解释来源{result.rag_explanation_coverage_passed ? "通过" : "未通过"}
                        </p>
                        {result.missing_explanation_references.length > 0 ? (
                          <p className="mt-1 font-mono text-[11px] text-[#AE5630]">缺失解释来源：{result.missing_explanation_references.join("、")}</p>
                        ) : null}
                        <p className="mt-1 text-[#8A7D6F]">
                          证据覆盖率 {Math.round(result.rag_evidence_coverage_ratio * 100)}% · 证据来源{result.rag_evidence_coverage_passed ? "通过" : "未通过"}
                        </p>
                        {result.missing_evidence_references.length > 0 ? (
                          <p className="mt-1 font-mono text-[11px] text-[#AE5630]">缺失证据来源：{result.missing_evidence_references.join("、")}</p>
                        ) : null}
                      </article>
                    ))}
                  </div>
                </article>
              ) : null}
            </section>

            <section className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.22em] text-[#8A7D6F]">Audit Log</p>
                  <h2 className="mt-1 text-xl font-semibold">独立审核审计日志</h2>
                </div>
                <p className="rounded-full border border-[#AE5630]/20 bg-[#AE5630]/10 px-3 py-1 text-xs text-[#AE5630]">
                  {auditEvents.length} 条事件
                </p>
              </div>
              <div className="mt-4 grid max-h-80 gap-2 overflow-y-auto pr-1">
                {auditEvents.length > 0 ? (
                  auditEvents.map((event) => (
                    <article className="rounded-xl border border-[#E6DFD2] bg-[#FAF9F5] p-3" key={`${event.session_id}-${event.event_type}-${event.created_at}`}>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-xs font-semibold text-[#AE5630]">{event.event_type}</p>
                        <p className="text-[11px] text-[#8A7D6F]">{event.created_at}</p>
                      </div>
                      <p className="mt-2 text-xs text-[#6F6257]">候选：{event.session_id} · 审核人：{event.student_id}</p>
                      <pre className="mt-2 whitespace-pre-wrap break-words rounded-md bg-white p-2 text-[11px] leading-5 text-[#6F6257]">
                        {JSON.stringify(event.payload, null, 2)}
                      </pre>
                    </article>
                  ))
                ) : (
                  <p className="rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">暂无独立审核审计日志。</p>
                )}
              </div>
            </section>

            <section className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-medium uppercase tracking-[0.22em] text-[#8A7D6F]">Skill Effects</p>
                  <h2 className="mt-1 text-xl font-semibold">Skill 效果统计</h2>
                </div>
                <p className="rounded-full border border-[#AE5630]/20 bg-[#AE5630]/10 px-3 py-1 text-xs text-[#AE5630]">
                  {skillEffects?.label ?? "待读取"}
                </p>
              </div>
              {skillEffects ? (
                <div className="mt-4 grid gap-3">
                  {skillEffects.status === "insufficient_samples" ? (
                    <p className="rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-3 text-sm leading-6 text-[#6F6257]">
                      样本不足：使用 Skill 与未使用 Skill 的训练报告各至少需要 {skillEffects.min_sessions_per_group} 份，当前只展示描述性计数，不计算提升。
                    </p>
                  ) : (
                    <p className="rounded-xl border border-[#E6DFD2] bg-[#FAF9F5] p-3 text-sm leading-6 text-[#6F6257]">
                      描述性对比：使用 Skill 组平均分较未使用组 {skillEffects.score_delta !== null && skillEffects.score_delta >= 0 ? "+" : ""}{skillEffects.score_delta} 分，仅用于教学复盘，不作为因果结论。
                    </p>
                  )}
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="rounded-xl border border-[#E6DFD2] bg-white p-3">
                      <p className="text-xs text-[#8A7D6F]">使用 Skill 组</p>
                      <p className="mt-1 text-2xl font-semibold">{skillEffects.with_skill.session_count}</p>
                      <p className="mt-1 text-xs text-[#6F6257]">平均分 {skillEffects.with_skill.average_total_score.toFixed(1)}</p>
                      <p className="mt-2 break-words text-xs text-[#8A7D6F]">Skill：{skillEffects.with_skill.skill_ids.length > 0 ? skillEffects.with_skill.skill_ids.join("、") : "无"}</p>
                    </div>
                    <div className="rounded-xl border border-[#E6DFD2] bg-white p-3">
                      <p className="text-xs text-[#8A7D6F]">未使用 Skill 组</p>
                      <p className="mt-1 text-2xl font-semibold">{skillEffects.without_skill.session_count}</p>
                      <p className="mt-1 text-xs text-[#6F6257]">平均分 {skillEffects.without_skill.average_total_score.toFixed(1)}</p>
                      <p className="mt-2 text-xs text-[#8A7D6F]">漏项种类 {Object.keys(skillEffects.without_skill.missed_item_counts).length}</p>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="mt-4 rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">正在读取 Skill 效果统计。</p>
              )}
            </section>

            <section className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <h2 className="text-xl font-semibold">候选 Skill 审核</h2>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <button
                    className="rounded-md border border-[#AE5630] bg-[#AE5630] px-3 py-2 text-sm font-medium whitespace-nowrap text-white transition hover:bg-[#C4633A] disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={isGeneratingCandidates}
                    onClick={() => void handleGenerateTrainingSkillCandidates()}
                    type="button"
                  >
                    {isGeneratingCandidates ? "生成中" : "从训练日志生成候选 Skill"}
                  </button>
                  <p className="rounded-full border border-[#AE5630]/20 bg-[#AE5630]/10 px-3 py-1 text-xs text-[#AE5630]">
                    {filteredCandidates.length}/{candidates.length} 个候选
                  </p>
                </div>
              </div>
              <input
                aria-label="筛选候选 Skill"
                className="mt-4 w-full rounded-md border border-[#E6DFD2] bg-white px-3 py-2 text-sm outline-none transition focus:border-[#AE5630]"
                onChange={(event) => setCandidateSearchText(event.target.value)}
                placeholder="筛选候选 Skill"
                type="search"
                value={candidateSearchText}
              />
              <div className="mt-4 grid gap-2">
                {filteredCandidates.length > 0 ? (
                  filteredCandidates.map((candidate) => (
                    <button
                      className="rounded-xl border border-[#E6DFD2] bg-[#FAF9F5] p-3 text-left transition hover:border-[#AE5630]"
                      key={candidate.candidate_id}
                      onClick={() => void handleSelectCandidate(candidate.candidate_id)}
                      type="button"
                    >
                      <span className="text-sm font-semibold">{candidate.title}</span>
                      <span className="mt-1 block text-xs text-[#6F6257]">
                        {candidate.trigger_item_id} · 支持 {candidate.support_count}/{candidate.source_report_count}
                      </span>
                      <span className="mt-2 inline-flex rounded-full border border-[#AE5630]/20 bg-[#AE5630]/10 px-2 py-1 text-[11px] text-[#AE5630]">
                        {candidate.regression_passed ? "回归通过" : "回归阻塞"}
                      </span>
                    </button>
                  ))
                ) : (
                  <p className="rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">{candidates.length > 0 ? "没有匹配的候选 Skill。" : "暂无候选 Skill。"}</p>
                )}
              </div>
              {selectedCandidate ? (
                <article className="mt-4 rounded-xl border border-[#E6DFD2] bg-[#FAF9F5] p-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div>
                      <p className="text-xs font-medium text-[#AE5630]">{selectedCandidate.review.status}</p>
                      <h3 className="mt-1 text-lg font-semibold">{selectedCandidate.title}</h3>
                    </div>
                    {canReviewSelectedCandidate ? (
                      <div className="flex flex-wrap gap-2">
                        <button
                          className="rounded-md border border-[#AE5630] bg-[#AE5630] px-3 py-2 text-sm font-medium whitespace-nowrap text-white transition hover:bg-[#C4633A]"
                          onClick={() => void handleReview("approve")}
                          type="button"
                        >
                          批准并启用
                        </button>
                        <button
                          className="rounded-md border border-[#E6DFD2] bg-white px-3 py-2 text-sm font-medium whitespace-nowrap text-[#6F6257] transition hover:bg-[#F1ECE2]"
                          onClick={() => void handleReview("reject")}
                          type="button"
                        >
                          拒绝候选
                        </button>
                      </div>
                    ) : (
                      <p className="rounded-md border border-[#E6DFD2] bg-white px-3 py-2 text-sm font-medium text-[#6F6257]">
                        候选已审核，当前状态为 {selectedCandidate.review.status}。
                      </p>
                    )}
                  </div>
                  <div className="mt-4 grid gap-3">
                    <div>
                      <h4 className="text-sm font-semibold">候选说明</h4>
                      <p className="mt-2 text-sm leading-6 text-[#6F6257]">{selectedCandidate.description}</p>
                    </div>
                    <div>
                      <h4 className="text-sm font-semibold">教学策略</h4>
                      <p className="mt-2 text-sm leading-6 text-[#6F6257]">{selectedCandidate.suggested_strategy}</p>
                    </div>
                    <div>
                      <h4 className="text-sm font-semibold">回归结果</h4>
                      <p className="mt-2 text-sm leading-6 text-[#6F6257]">
                        {selectedCandidate.review.regression_passed ? "回归通过" : "回归阻塞"} · 通过 {selectedCandidate.review.evaluation_passed_cases}/{selectedCandidate.review.evaluation_total_cases} 例
                      </p>
                    </div>
                    <div>
                      <h4 className="text-sm font-semibold">审核审计事件</h4>
                      <div className="mt-2 grid max-h-64 gap-2 overflow-auto pr-1">
                        {candidateAuditEvents.length > 0 ? (
                          candidateAuditEvents.map((event) => (
                            <div className="rounded-lg border border-[#E6DFD2] bg-white p-3" key={`${event.event_type}-${event.created_at}`}>
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <p className="text-xs font-semibold text-[#AE5630]">{event.event_type}</p>
                                <p className="text-[11px] text-[#8A7D6F]">{event.created_at}</p>
                              </div>
                              <p className="mt-1 text-xs text-[#6F6257]">审核人：{event.student_id} · 触发项：{event.case_id}</p>
                              <pre className="mt-2 whitespace-pre-wrap rounded-md bg-[#FAF9F5] p-2 text-[11px] leading-5 text-[#6F6257]">
                                {JSON.stringify(event.payload, null, 2)}
                              </pre>
                            </div>
                          ))
                        ) : (
                          <p className="rounded-lg border border-dashed border-[#E6DFD2] bg-white p-3 text-sm text-[#6F6257]">暂无审核审计事件。</p>
                        )}
                      </div>
                    </div>
                  </div>
                </article>
              ) : (
                <p className="mt-4 rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">请选择一个候选 Skill。</p>
              )}
            </section>
          </div>
        </div>
        </div>
      </div>
      {isAdminLoginDialogOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#141413]/35 p-4 backdrop-blur">
          <section className="w-full max-w-md rounded-2xl border border-[#E6DFD2] bg-white p-6 shadow-xl">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-[#8A7D6F]">Clinical OSCE Agent Admin</p>
              <h2 className="mt-2 text-xl font-semibold">管理员登录</h2>
              <p className="mt-2 text-sm leading-6 text-[#6F6257]">登录管理员账号后读取训练 Session、评分报告、系统评测和候选 Skill 审核数据。</p>
              <p className="mt-2 rounded-lg border border-[#AE5630]/20 bg-[#AE5630]/10 px-3 py-2 text-xs leading-5 text-[#AE5630]">演示账号已预填：{DEMO_ADMIN_EMAIL} / {DEMO_ADMIN_PASSWORD}</p>
            </div>
            <form className="mt-5 space-y-4" onSubmit={(event) => void handleAdminLogin(event)}>
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="admin-email-input">
                  邮箱
                </label>
                <input
                  autoComplete="email"
                  className="w-full rounded-lg border border-[#E6DFD2] bg-[#FAF9F5] px-3 py-2 text-sm outline-none transition placeholder:text-[#8A7D6F] focus:border-[#AE5630] focus:ring-2 focus:ring-[#AE5630]/15"
                  id="admin-email-input"
                  onChange={(event) => setAdminEmail(event.target.value)}
                  placeholder={DEMO_ADMIN_EMAIL}
                  type="email"
                  value={adminEmail}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="admin-password-input">
                  密码
                </label>
                <input
                  autoComplete="current-password"
                  className="w-full rounded-lg border border-[#E6DFD2] bg-[#FAF9F5] px-3 py-2 text-sm outline-none transition placeholder:text-[#8A7D6F] focus:border-[#AE5630] focus:ring-2 focus:ring-[#AE5630]/15"
                  id="admin-password-input"
                  onChange={(event) => setAdminPassword(event.target.value)}
                  placeholder="输入管理员账号密码"
                  type="password"
                  value={adminPassword}
                />
              </div>
              {adminLoginErrorText ? <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">{adminLoginErrorText}</p> : null}
              <button
                className="w-full rounded-lg border border-[#AE5630] bg-[#AE5630] px-4 py-2 text-sm font-semibold whitespace-nowrap text-white transition hover:bg-[#C4633A] disabled:cursor-not-allowed disabled:opacity-60"
                disabled={isLoggingIn || !adminEmail.trim() || !adminPassword}
                type="submit"
              >
                {isLoggingIn ? "登录中" : "登录"}
              </button>
            </form>
          </section>
        </div>
      ) : null}
    </main>
  );
}
