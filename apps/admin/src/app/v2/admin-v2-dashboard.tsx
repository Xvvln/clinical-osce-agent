"use client";

import { type FormEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  BookOpen,
  Brain,
  ClipboardCheck,
  FileText,
  Gauge,
  GraduationCap,
  LayoutDashboard,
  Loader2,
  LogOut,
  PlusCircle,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  Wrench,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const AUTH_EMAIL_MAX_CHARS = 254;
const AUTH_PASSWORD_MAX_CHARS = 256;
const DEPLOYMENT_MODE = process.env.NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE ?? "local-dev";
const LOCAL_AUTO_LOGIN_EMAIL = process.env.NEXT_PUBLIC_CLINICAL_OSCE_AUTO_LOGIN_EMAIL ?? "";
const LOCAL_AUTO_LOGIN_PASSWORD = process.env.NEXT_PUBLIC_CLINICAL_OSCE_AUTO_LOGIN_PASSWORD ?? "";
const isLocalAutoLoginConfigured =
  DEPLOYMENT_MODE === "local-dev" && Boolean(LOCAL_AUTO_LOGIN_EMAIL && LOCAL_AUTO_LOGIN_PASSWORD);
const ADMIN_CASE_REQUEST_MAX_BYTES = 256 * 1024;
const RAG_DOCUMENT_MAX_BYTES = 8 * 1024 * 1024;
const RAG_FILE_NAME_MAX_CHARS = 255;
const RAG_TAG_MAX_CHARS = 64;
const RAG_TAGS_MAX_ITEMS = 32;
const RAG_TITLE_MAX_CHARS = 200;
const RAG_TEXT_MAX_CHARS = 16_384;
const CASE_TITLE_MAX_CHARS = 120;
const CHIEF_COMPLAINT_MAX_CHARS = 500;
const SAFETY_NOTES_MAX_CHARS = 1000;
const RUBRIC_DESCRIPTION_MAX_CHARS = 1000;
const CASE_CREATION_HISTORY_MAX_ITEMS = 8;
const CASE_CREATION_PROCEDURE_MAX_ITEMS = 6;
const CASE_CREATION_DIFFERENTIAL_MAX_ITEMS = 4;
const CASE_CREATION_REASONING_MAX_ITEMS = 4;

type AuthUser = Readonly<{
  user_id: string;
  email: string;
  is_admin: boolean;
}>;

type Pagination = Readonly<{
  total: number;
  limit: number;
  offset: number;
}>;

type AdminSessionSummary = Readonly<{
  session_id: string;
  student_id: string;
  case_id: string;
  case_title?: string;
  stage: string;
  stage_label?: string;
  created_at: string;
  updated_at: string;
  active_skill_context?: Readonly<{
    skipped_reasons?: readonly Readonly<{
      skill_id: string;
      reason: string;
      reason_label?: string;
      reason_description?: string;
    }>[];
  }>;
}>;

type AdminReportSummary = Readonly<{
  report_id?: string;
  session_id: string;
  case_id: string;
  case_title?: string;
  student_id: string;
  total_score: number;
  missed_item_labels?: readonly string[];
  generation_warnings?: readonly string[];
}>;

type TrainingSkillCandidateSummary = Readonly<{
  candidate_id: string;
  title: string;
  description?: string;
  status: string;
  skill_type_label?: string;
  regression_passed: boolean;
  source_report_count: number;
  support_count: number;
  trigger_item_labels?: readonly string[];
  case_titles?: readonly string[];
}>;

type AdminSourceReferenceItem = Readonly<{
  reference: string;
  reference_label?: string;
  source_type?: string;
  title?: string;
}>;

type ReportRecommendation = Readonly<{
  title?: string;
  content?: string;
  source_references?: readonly string[];
}>;

type AdminSessionReport = Readonly<{
  report_id?: string;
  session_id: string;
  case_id: string;
  case_title?: string;
  student_id: string;
  total_score?: number;
  score_groups?: Record<string, Readonly<{ score: number; max_score: number }>>;
  dimension_scores?: Record<string, number>;
  missed_items?: readonly string[];
  missed_item_labels?: readonly string[];
  training_gaps?: readonly AdminTrainingGap[];
  missed_opportunities?: readonly AdminMissedOpportunity[];
  source_reference_items?: readonly AdminSourceReferenceItem[];
  explanation_source_items?: readonly AdminSourceReferenceItem[];
  knowledge_recommendations?: readonly ReportRecommendation[];
  generation_warnings?: readonly string[];
}>;

type AdminTrainingGap = Readonly<{
  dimension_id?: string;
  rubric_item_id?: string;
  gap_type?: string;
  label?: string;
  missing_score?: number;
  severity?: string;
  next_training_action?: string;
  skill_type?: string;
  gap_source?: string;
}>;

type AdminMissedOpportunity = Readonly<{
  opportunity_id?: string;
  gap_type?: string;
  trigger_evidence?: string;
  expected_response?: string;
}>;

type TrainingEventRecord = Readonly<{
  session_id?: string;
  case_id?: string;
  student_id?: string;
  event_type: string;
  payload?: Record<string, unknown>;
  created_at?: string;
}>;

type TrainingSkillAutoApprovalSettings = Readonly<{
  auto_apply_enabled: boolean;
  approval_agent_id?: string;
  updated_by?: string;
  updated_at?: string;
}>;

type TrainingSkillCandidateReview = Readonly<{
  status?: string;
  reviewed_by?: string;
  reviewed_at?: string;
  reason?: string;
}>;

type TrainingSkillApprovalAgentReview = Readonly<{
  decision?: string;
  revision_status?: string;
  changed_fields?: unknown;
  regression_status?: string;
  regression_passed?: boolean;
}>;

type TrainingSkillTeachingAction = Readonly<{
  action_type?: string;
  action_type_label?: string;
  level?: string;
  stage_scope_labels?: readonly string[];
  trigger_item_labels?: readonly string[];
  message_template?: string;
}>;

type TrainingSkillCandidateDetail = TrainingSkillCandidateSummary &
  Readonly<{
    skill_type?: string;
    stage_scope_labels?: unknown;
    applies_when?: unknown;
    effect_status?: string;
    effect_status_label?: string;
    suggested_strategy?: string;
    teaching_action_plan?: readonly TrainingSkillTeachingAction[];
    success_metrics?: unknown;
    related_recommendation_labels?: readonly string[];
    source_report_ids?: unknown;
    source_session_ids?: unknown;
    review?: TrainingSkillCandidateReview;
    approval_agent_review?: TrainingSkillApprovalAgentReview;
  }>;

type EvaluationBatchSummary = Readonly<{
  batch_id: string;
  batch_label?: string;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  passed: boolean;
}>;

type EvaluationCaseResult = Readonly<{
  session_id?: string;
  actual_total_score?: number;
  expected_total_score?: number;
  rag_source_coverage_passed?: boolean;
  rag_explanation_coverage_passed?: boolean;
  rag_explanation_coverage_ratio?: number;
  missing_explanation_references?: readonly string[];
  forbidden_term_violations?: readonly string[];
}>;

type EvaluationBatchDetail = EvaluationBatchSummary &
  Readonly<{
    total_duration_ms?: number;
    results?: readonly EvaluationCaseResult[];
  }>;

type AdminCaseSummary = Readonly<{
  case_id: string;
  title?: string;
  chief_complaint?: string;
  difficulty?: string;
}>;

type AdminCaseRaw = Record<string, unknown>;

type AdminSourceSummary = Readonly<{
  source_id: string;
  title?: string;
  source_type?: string;
}>;

type AdminRagDocument = Readonly<{
  document_id: string;
  title?: string;
  filename?: string;
  file_name?: string;
  scope: string;
  case_id?: string;
  case_title?: string;
  source_title?: string;
  chunk_count?: number;
  enabled?: boolean;
  visibility?: string;
  allowed_agents?: readonly string[];
  updated_at?: string;
}>;

type AdminRagKnowledgeItem = Readonly<{
  knowledge_id: string;
  document_id?: string;
  document_name?: string;
  title?: string;
  text?: string;
  scope?: string;
  case_id?: string;
  case_title?: string;
  source_id?: string;
  source_title?: string;
  content_kind?: string;
  visibility?: string;
  allowed_agents?: readonly string[] | string;
  tags?: readonly string[] | string;
  version?: number;
  chunk_index?: number | null;
  chunk_count?: number | null;
  section_title?: string;
  page_number?: number | null;
  source_location?: string;
  enabled?: boolean;
  updated_at?: string;
}>;

type AdminRagKnowledgeItemPayload = Readonly<{
  knowledge_id: string;
  scope: string;
  case_id: string;
  content_kind: string;
  visibility: string;
  allowed_agents: readonly string[];
  source_id: string;
  title: string;
  text: string;
  tags: readonly string[];
  version: number;
}>;

type AdminRagDocumentUploadPayload = Readonly<{
  allowed_agents: readonly string[];
  case_id: string;
  content_base64: string;
  enabled: boolean;
  file_name: string;
  scope: string;
  source_id: string;
  tags: readonly string[];
  visibility: string;
}>;

type AdminRagDocumentUploadResponse = Readonly<{
  document: AdminRagDocument;
  knowledge_items?: readonly AdminRagKnowledgeItem[];
}>;

type AdminCaseCreationPayload = Readonly<{
  case: Record<string, unknown>;
  rubric: Record<string, unknown>;
}>;

type AdminCaseImportStatus = Readonly<{
  valid?: boolean;
  imported?: boolean;
  case_id?: string | null;
  rubric_id?: string | null;
  errors?: readonly string[];
}>;

type CaseCreationTextRow = Readonly<{
  id: string;
  value: string;
}>;

type CaseCreationProcedureRow = Readonly<{
  code: string;
  id: string;
  name: string;
  result: string;
}>;

type CaseCreationDifferentialRow = Readonly<{
  description: string;
  id: string;
  name: string;
}>;

type CaseCreationDraft = Readonly<{
  ageValue: string;
  caseId: string;
  caseTitle: string;
  chiefComplaint: string;
  courseModule: string;
  differentialDiagnoses: readonly CaseCreationDifferentialRow[];
  difficulty: string;
  examItems: readonly CaseCreationProcedureRow[];
  gender: string;
  historyFacts: readonly CaseCreationTextRow[];
  hospitalDepartment: string;
  mainDiagnosis: string;
  occupation: string;
  patientConcern: string;
  patientExpectation: string;
  patientIdea: string;
  presentIllnessSummary: string;
  reasoningPoints: readonly CaseCreationTextRow[];
  safetyNotes: string;
  sourceId: string;
  testItems: readonly CaseCreationProcedureRow[];
}>;

type CaseCreationTextField = {
  [Key in keyof CaseCreationDraft]: CaseCreationDraft[Key] extends string ? Key : never;
}[keyof CaseCreationDraft];

type AdminModelProvider = Readonly<{
  provider_id: string;
  label: string;
  capability: string;
  enabled: boolean;
  configured: boolean;
  model?: string;
  integration_status?: string;
}>;

type AdminModelConfig = Readonly<{
  policy: Readonly<{
    deployment_mode: string;
    account_runtime_visible: boolean;
    runtime_write_supported: boolean;
  }>;
  providers: readonly AdminModelProvider[];
}>;

type AdminCaseFieldUpdatePayload = Readonly<{
  case_title?: string;
  chief_complaint?: string;
  course_module?: string;
  difficulty?: string;
  safety_notes?: string;
}>;

type AdminCaseUpdateResponse = Readonly<{
  case: AdminCaseRaw;
  updated_fields?: readonly string[];
}>;

type AdminRubricItem = Readonly<{
  item_id: string;
  description: string;
  max_score: number;
  match_rule?: Readonly<{ kind?: string; spec?: Record<string, unknown> }>;
  evidence_expected?: readonly string[];
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
  schema_version?: string;
  dimensions: readonly AdminRubricDimension[];
}>;

type AdminRubricItemUpdateResponse = Readonly<{
  item: AdminRubricItem;
  rubric: AdminRubricDetail;
}>;

type ApiCallLog = Readonly<{
  created_at: string;
  provider: string;
  operation: string;
  model: string;
  endpoint: string;
  caller?: string;
  user_id?: string;
  student_id?: string;
  session_id?: string;
  success: boolean;
  status_code?: number | null;
  duration_ms: number;
  error_type?: string;
  error_message?: string;
}>;

type ModelApiLogs = Readonly<{
  summary: Readonly<{
    total_calls: number;
    success_calls: number;
    failed_calls: number;
    success_rate: number;
    avg_duration_ms: number;
  }>;
  summary_by_provider: readonly Readonly<{
    provider: string;
    total_calls: number;
    success_calls: number;
    failed_calls: number;
    success_rate: number;
    avg_duration_ms: number;
  }>[];
  logs: readonly ApiCallLog[];
}>;

type ModelApiTrendPoint = Readonly<{
  label: string;
  total: number;
  success: number;
  failed: number;
  avgDuration: number;
}>;

type ModelApiDistributionPoint = Readonly<{
  name: string;
  value: number;
}>;

type ModelApiLatencyPoint = Readonly<{
  name: string;
  calls: number;
  avgDuration: number;
  failed: number;
}>;

type ModelApiChartData = Readonly<{
  trend: readonly ModelApiTrendPoint[];
  status: readonly ModelApiDistributionPoint[];
  operations: readonly ModelApiDistributionPoint[];
  providerCalls: readonly ModelApiDistributionPoint[];
  modelLatency: readonly ModelApiLatencyPoint[];
}>;

type TrainingInsights = Readonly<{
  session_count: number;
  report_count: number;
  frequent_missed_items?: readonly unknown[];
  frequent_turn_patterns?: readonly unknown[];
  humanistic_communication?: HumanisticCommunicationInsight;
}>;

type HumanisticCommunicationInsight = Readonly<{
  report_count: number;
  score_sample_count: number;
  average_score: number;
  max_score: number;
  average_percentage: number | null;
  dimension_averages: readonly Readonly<{
    dimension_id: string;
    dimension_label: string;
    sample_count: number;
    average_score: number;
    average_max_score: number;
    average_percentage: number | null;
  }>[];
  frequent_gaps: readonly Readonly<{
    gap_type: string;
    label: string;
    count: number;
    missing_score_total: number;
    skill_type: string;
  }>[];
  frequent_missed_opportunities: readonly Readonly<{
    gap_type: string;
    expected_response: string;
    count: number;
  }>[];
  anchor_candidate_count: number;
  anchor_candidates_by_status: readonly Readonly<{
    status: string;
    count: number;
  }>[];
  trend: Readonly<{
    previous_average_score: number;
    recent_average_score: number;
    delta: number;
  }>;
  percentage_trend: Readonly<{
    previous_average_score: number;
    recent_average_score: number;
    delta: number;
  }>;
}>;

type AdminNormalizedScoreMetric = Readonly<{
  sample_count: number;
  average_score: number;
  average_max_score: number;
  average_percentage: number | null;
}>;

type AdminLearningGap = Readonly<{
  gap_type?: string;
  item_id?: string;
  label?: string;
  count?: number;
  missing_score_total?: number;
  next_training_action?: string;
  expected_response?: string;
}>;

type AdminLearningAffectSignals = Readonly<{
  signal_count: number;
  repaired_count: number;
  ignored_count: number;
}>;

type AdminLearningTrainingDrill = Readonly<{
  drill_id: string;
  scope: "all_users" | "case" | "student" | string;
  scope_id?: string;
  source: "humanistic_gap" | "missed_opportunity" | "affect_response" | string;
  priority: number;
  title: string;
  target_gap_type: string;
  target_label: string;
  trigger_stage: string;
  trigger_signal: string;
  student_action: string;
  success_signal: string;
  source_count: number;
}>;

type AdminCaseLearningAnalytics = Readonly<{
  case_id: string;
  case_title?: string;
  session_count: number;
  report_count: number;
  average_total_score: number;
  average_clinical_score: number;
  average_humanistic_score: number;
  clinical_score: AdminNormalizedScoreMetric;
  humanistic_score: AdminNormalizedScoreMetric;
  frequent_missed_items: readonly AdminLearningGap[];
  frequent_humanistic_gaps: readonly AdminLearningGap[];
  frequent_missed_opportunities: readonly AdminLearningGap[];
  affect_signals: AdminLearningAffectSignals;
  teaching_actions: readonly string[];
  training_drills?: readonly AdminLearningTrainingDrill[];
}>;

type AdminStudentLearningAnalytics = Readonly<{
  student_id: string;
  session_count: number;
  report_count: number;
  average_total_score: number;
  average_clinical_score: number;
  average_humanistic_score: number;
  clinical_score: AdminNormalizedScoreMetric;
  humanistic_score: AdminNormalizedScoreMetric;
  case_titles: readonly string[];
  persistent_gaps: readonly AdminLearningGap[];
  current_humanistic_gaps: readonly AdminLearningGap[];
  affect_response: AdminLearningAffectSignals;
  recommended_next_actions: readonly string[];
  training_drills?: readonly AdminLearningTrainingDrill[];
}>;

type AdminCohortLearningAnalytics = Readonly<{
  scope: "all_users" | string;
  scope_label?: string;
  session_count: number;
  report_count: number;
  case_count: number;
  student_count: number;
  average_total_score: number;
  average_clinical_score: number;
  average_humanistic_score: number;
  clinical_score: AdminNormalizedScoreMetric;
  humanistic_score: AdminNormalizedScoreMetric;
  frequent_missed_items: readonly AdminLearningGap[];
  frequent_humanistic_gaps: readonly AdminLearningGap[];
  frequent_missed_opportunities: readonly AdminLearningGap[];
  affect_signals: AdminLearningAffectSignals;
  teaching_actions: readonly string[];
  training_drills?: readonly AdminLearningTrainingDrill[];
}>;

type AdminLearningAnalytics = Readonly<{
  summary: Readonly<{
    session_count: number;
    report_count: number;
    case_count: number;
    student_count: number;
  }>;
  cohort_analytics?: AdminCohortLearningAnalytics;
  case_analytics: readonly AdminCaseLearningAnalytics[];
  student_analytics: readonly AdminStudentLearningAnalytics[];
}>;

type ProcedureSimulationAuditItem = Readonly<{
  approval_decision?: string;
  approval_mode?: string;
  approval_rationale?: string;
  approval_status?: string;
  case_id?: string;
  case_title?: string;
  code?: string;
  kind?: string;
  label?: string;
  procedure_id?: string;
  result?: string;
  safety_boundary?: string;
  safety_issues?: readonly string[];
  scoring_eligible?: boolean;
  session_id?: string;
  source_context_references?: readonly string[];
  student_id?: string;
}>;

type ProcedureSimulationAuditSummary = Readonly<{
  by_approval_status?: Record<string, number>;
  by_case_title?: Record<string, number>;
  total?: number;
}>;

type AdminTeachingFocusPattern = Readonly<{
  case_titles?: readonly string[];
  description?: string;
  focus_id: string;
  pattern?: string;
  severity_label?: string;
  source_report_count?: number;
  support_count?: number;
  title?: string;
  training_suggestion?: string;
  trigger_item_labels?: readonly string[];
  visibility_level_label?: string;
  why_now?: string;
}>;

type InsightDisplayItem = Readonly<{
  title: string;
  description: string;
  meta: string;
  count: number;
}>;

type AdminRetrievalEval = Readonly<{
  boundary?: Readonly<{
    chroma_scope?: string;
    rag_usage?: string;
    scoring_boundary?: string;
  }>;
  gold_set?: Readonly<{
    path?: string;
    query_count?: number;
  }>;
  metrics?: Readonly<{
    mrr_at_5?: number;
    ndcg_at_5?: number;
    query_count?: number;
    recall_at_3?: number;
    recall_at_5?: number;
    source_coverage?: number;
  }>;
  results?: readonly Readonly<{
    expected_references?: readonly string[];
    hits_at_5?: readonly string[];
    query?: string;
    query_id?: string;
    retrieved_references?: readonly string[];
  }>[];
}>;

type TrainingSkillEffects = Readonly<{
  status: string;
  label?: string;
  min_sessions_per_group?: number;
  with_skill?: Readonly<{ session_count: number; average_total_score: number }>;
  without_skill?: Readonly<{ session_count: number; average_total_score: number }>;
}>;

type DashboardData = Readonly<{
  modelConfig: AdminModelConfig | null;
  apiLogs: ModelApiLogs | null;
  sessions: readonly AdminSessionSummary[];
  sessionPagination: Pagination | null;
  reports: readonly AdminReportSummary[];
  reportPagination: Pagination | null;
  candidates: readonly TrainingSkillCandidateSummary[];
  candidatePagination: Pagination | null;
  evaluations: readonly EvaluationBatchSummary[];
  evaluationPagination: Pagination | null;
  cases: readonly AdminCaseSummary[];
  sources: readonly AdminSourceSummary[];
  documents: readonly AdminRagDocument[];
  knowledgeItems: readonly AdminRagKnowledgeItem[];
  insights: TrainingInsights | null;
  learningAnalytics: AdminLearningAnalytics | null;
  procedureAudits: readonly ProcedureSimulationAuditItem[];
  procedureAuditSummary: ProcedureSimulationAuditSummary | null;
  teachingFocusPatterns: readonly AdminTeachingFocusPattern[];
  auditEvents: readonly TrainingEventRecord[];
  retrievalEval: AdminRetrievalEval | null;
  skillEffects: TrainingSkillEffects | null;
  autoApprovalSettings: TrainingSkillAutoApprovalSettings | null;
}>;

type AdminSectionId = "overview" | "resources" | "training" | "insights" | "skill" | "evaluation" | "logs";

const emptyDashboardData: DashboardData = {
  modelConfig: null,
  apiLogs: null,
  sessions: [],
  sessionPagination: null,
  reports: [],
  reportPagination: null,
  candidates: [],
  candidatePagination: null,
  evaluations: [],
  evaluationPagination: null,
  cases: [],
  sources: [],
  documents: [],
  knowledgeItems: [],
  insights: null,
  learningAnalytics: null,
  procedureAudits: [],
  procedureAuditSummary: null,
  teachingFocusPatterns: [],
  auditEvents: [],
  retrievalEval: null,
  skillEffects: null,
  autoApprovalSettings: null,
};

const sections: readonly Readonly<{ id: AdminSectionId; label: string; icon: typeof LayoutDashboard }>[] = [
  { id: "overview", label: "概览", icon: LayoutDashboard },
  { id: "resources", label: "教学资源", icon: BookOpen },
  { id: "training", label: "训练管理", icon: Stethoscope },
  { id: "insights", label: "教学洞察", icon: Brain },
  { id: "skill", label: "Skill 进化", icon: Sparkles },
  { id: "evaluation", label: "系统评测", icon: ClipboardCheck },
  { id: "logs", label: "调用日志", icon: Activity },
];

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      detail = payload.detail || detail;
    } catch {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

async function loadDashboardData(): Promise<DashboardData> {
  const [
    modelConfigPayload,
    apiLogPayload,
    sessionPayload,
    reportPayload,
    candidatePayload,
    evaluationPayload,
    casesPayload,
    sourcesPayload,
    documentsPayload,
    knowledgePayload,
    insightsPayload,
    learningAnalyticsPayload,
    procedureAuditPayload,
    teachingFocusPayload,
    auditEventsPayload,
    retrievalEvalPayload,
    skillEffectsPayload,
    autoApprovalSettingsPayload,
  ] = await Promise.all([
    fetchJson<{ providers: readonly AdminModelProvider[]; policy: AdminModelConfig["policy"] }>("/api/admin/model-config"),
    fetchJson<ModelApiLogs>("/api/admin/model-api-logs?limit=60"),
    fetchJson<{ sessions: readonly AdminSessionSummary[]; pagination?: Pagination }>("/api/admin/sessions?limit=20"),
    fetchJson<{ reports: readonly AdminReportSummary[]; pagination?: Pagination }>("/api/admin/reports?limit=20"),
    fetchJson<{ candidates: readonly TrainingSkillCandidateSummary[]; pagination?: Pagination }>("/api/admin/evolution/candidates?limit=20&review_status=all"),
    fetchJson<{ evaluations: readonly EvaluationBatchSummary[]; pagination?: Pagination }>("/api/admin/evaluations?limit=20"),
    fetchJson<{ cases: readonly AdminCaseSummary[] }>("/api/cases"),
    fetchJson<{ sources: readonly AdminSourceSummary[] }>("/api/admin/sources"),
    fetchJson<{ documents: readonly AdminRagDocument[] }>("/api/admin/rag/documents"),
    fetchJson<{ knowledge_items: readonly AdminRagKnowledgeItem[] }>("/api/admin/rag/knowledge"),
    fetchJson<{ insights: TrainingInsights }>("/api/admin/insights"),
    fetchJson<{ learning_analytics: AdminLearningAnalytics }>("/api/admin/learning-analytics"),
    fetchJson<{ procedure_simulation_audits: readonly ProcedureSimulationAuditItem[]; summary?: ProcedureSimulationAuditSummary }>("/api/admin/procedure-simulation-audits?limit=20"),
    fetchJson<{ patterns: readonly AdminTeachingFocusPattern[] }>("/api/admin/teaching-focus/patterns"),
    fetchJson<{ events: readonly TrainingEventRecord[] }>("/api/admin/evolution/events?limit=20"),
    fetchJson<{ retrieval_eval: AdminRetrievalEval }>("/api/admin/retrieval-eval"),
    fetchJson<{ skill_effects: TrainingSkillEffects }>("/api/admin/evolution/skill-effects"),
    fetchJson<{ settings: TrainingSkillAutoApprovalSettings }>("/api/admin/evolution/settings"),
  ]);
  return {
    modelConfig: modelConfigPayload,
    apiLogs: apiLogPayload,
    sessions: sessionPayload.sessions,
    sessionPagination: sessionPayload.pagination ?? null,
    reports: reportPayload.reports,
    reportPagination: reportPayload.pagination ?? null,
    candidates: candidatePayload.candidates,
    candidatePagination: candidatePayload.pagination ?? null,
    evaluations: evaluationPayload.evaluations,
    evaluationPagination: evaluationPayload.pagination ?? null,
    cases: casesPayload.cases,
    sources: sourcesPayload.sources,
    documents: documentsPayload.documents,
    knowledgeItems: knowledgePayload.knowledge_items,
    insights: insightsPayload.insights,
    learningAnalytics: learningAnalyticsPayload.learning_analytics,
    procedureAudits: procedureAuditPayload.procedure_simulation_audits,
    procedureAuditSummary: procedureAuditPayload.summary ?? null,
    teachingFocusPatterns: teachingFocusPayload.patterns,
    auditEvents: auditEventsPayload.events,
    retrievalEval: retrievalEvalPayload.retrieval_eval,
    skillEffects: skillEffectsPayload.skill_effects,
    autoApprovalSettings: autoApprovalSettingsPayload.settings,
  };
}

async function getSessionReport(sessionId: string): Promise<AdminSessionReport> {
  const payload = await fetchJson<{ report: AdminSessionReport }>(`/api/admin/sessions/${sessionId}/report`);
  return payload.report;
}

async function getSessionEvents(sessionId: string): Promise<readonly TrainingEventRecord[]> {
  const payload = await fetchJson<{ events: readonly TrainingEventRecord[] }>(`/api/admin/sessions/${sessionId}/events`);
  return payload.events;
}

async function getAdminCaseRaw(caseId: string): Promise<AdminCaseRaw> {
  const payload = await fetchJson<{ case: AdminCaseRaw }>(`/api/admin/cases/${encodeURIComponent(caseId)}/raw`);
  return payload.case;
}

async function updateAdminCaseFields(caseId: string, payload: AdminCaseFieldUpdatePayload): Promise<AdminCaseRaw> {
  const response = await fetchJson<AdminCaseUpdateResponse>(`/api/admin/cases/${encodeURIComponent(caseId)}/raw`, {
    body: JSON.stringify(payload),
    method: "PATCH",
  });
  return response.case;
}

async function getAdminRubric(rubricId: string): Promise<AdminRubricDetail> {
  const payload = await fetchJson<{ rubric: AdminRubricDetail }>(`/api/admin/rubrics/${rubricId}`);
  return payload.rubric;
}

async function updateAdminRubricItemDescription(rubricId: string, itemId: string, description: string): Promise<AdminRubricDetail> {
  const payload = await fetchJson<AdminRubricItemUpdateResponse>(`/api/admin/rubrics/${rubricId}/items/${itemId}`, {
    body: JSON.stringify({ description }),
    method: "PATCH",
  });
  return payload.rubric;
}

async function getEvaluationDetail(batchId: string): Promise<EvaluationBatchDetail> {
  const payload = await fetchJson<{ evaluation: EvaluationBatchDetail }>(`/api/admin/evaluations/${batchId}`);
  return payload.evaluation;
}

async function getCandidateDetail(candidateId: string): Promise<TrainingSkillCandidateDetail> {
  const payload = await fetchJson<{ candidate: TrainingSkillCandidateDetail }>(`/api/admin/evolution/candidates/${candidateId}`);
  return payload.candidate;
}

async function getCandidateEvents(candidateId: string): Promise<readonly TrainingEventRecord[]> {
  const payload = await fetchJson<{ events: readonly TrainingEventRecord[] }>(`/api/admin/evolution/candidates/${candidateId}/events`);
  return payload.events;
}

async function setRagDocumentEnabled(documentId: string, enabled: boolean): Promise<AdminRagDocument> {
  const payload = await fetchJson<{ document: AdminRagDocument }>(`/api/admin/rag/documents/${encodeURIComponent(documentId)}/enabled`, {
    body: JSON.stringify({ enabled }),
    method: "PATCH",
  });
  return payload.document;
}

async function upsertRagKnowledgeItem(payload: AdminRagKnowledgeItemPayload): Promise<AdminRagKnowledgeItem> {
  const response = await fetchJson<{ knowledge_item: AdminRagKnowledgeItem }>("/api/admin/rag/knowledge", {
    body: JSON.stringify(payload),
    method: "POST",
  });
  return response.knowledge_item;
}

async function uploadRagDocument(payload: AdminRagDocumentUploadPayload): Promise<AdminRagDocumentUploadResponse> {
  const response = await fetchJson<AdminRagDocumentUploadResponse>("/api/admin/rag/documents", {
    body: JSON.stringify(payload),
    method: "POST",
  });
  return response;
}

async function validateAdminCaseCreation(payload: AdminCaseCreationPayload): Promise<AdminCaseImportStatus> {
  return fetchJson<AdminCaseImportStatus>("/api/admin/cases/validate", {
    body: JSON.stringify(payload),
    method: "POST",
  });
}

async function importAdminCaseCreation(payload: AdminCaseCreationPayload): Promise<AdminCaseImportStatus> {
  return fetchJson<AdminCaseImportStatus>("/api/admin/cases/import", {
    body: JSON.stringify(payload),
    method: "POST",
  });
}

async function updateAutoApproval(autoApplyEnabled: boolean): Promise<TrainingSkillAutoApprovalSettings> {
  const payload = await fetchJson<{ settings: TrainingSkillAutoApprovalSettings }>("/api/admin/evolution/settings", {
    body: JSON.stringify({ auto_apply_enabled: autoApplyEnabled }),
    method: "PATCH",
  });
  return payload.settings;
}

async function reviewCandidate(candidateId: string, action: "approve" | "reject"): Promise<void> {
  await fetchJson(action === "approve" ? "/api/admin/evolution/approve" : "/api/admin/evolution/reject", {
    body: JSON.stringify({ candidate_id: candidateId }),
    method: "POST",
  });
}

export function AdminV2Dashboard() {
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [activeSectionId, setActiveSectionId] = useState<AdminSectionId>("overview");
  const [data, setData] = useState<DashboardData>(emptyDashboardData);
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [selectedReport, setSelectedReport] = useState<AdminSessionReport | null>(null);
  const [selectedEvents, setSelectedEvents] = useState<readonly TrainingEventRecord[]>([]);
  const [selectedEvaluation, setSelectedEvaluation] = useState<EvaluationBatchDetail | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<TrainingSkillCandidateDetail | null>(null);
  const [selectedCandidateEvents, setSelectedCandidateEvents] = useState<readonly TrainingEventRecord[]>([]);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isAuthLoading, setIsAuthLoading] = useState(true);
  const [isDataLoading, setIsDataLoading] = useState(false);
  const [isMutating, setIsMutating] = useState(false);
  const [isDetailBusy, setIsDetailBusy] = useState(false);
  const [isSkillBusy, setIsSkillBusy] = useState(false);
  const [isDocumentBusy, setIsDocumentBusy] = useState(false);
  const [isCaseCreationBusy, setIsCaseCreationBusy] = useState(false);
  const [isCaseCreationOpen, setIsCaseCreationOpen] = useState(false);
  const [errorText, setErrorText] = useState("");
  const [statusText, setStatusText] = useState("");
  const [loginErrorText, setLoginErrorText] = useState("");
  const hasAttemptedLocalAutoLoginRef = useRef(false);

  const selectedSession = useMemo(
    () => data.sessions.find((session) => session.session_id === selectedSessionId) ?? data.sessions[0] ?? null,
    [data.sessions, selectedSessionId],
  );

  useEffect(() => {
    let isMounted = true;

    async function loadAuthUser(): Promise<void> {
      let currentUser: AuthUser | null = null;
      try {
        currentUser = (await fetchJson<{ user: AuthUser }>("/api/auth/me")).user;
      } catch {
        currentUser = null;
      }

      if (currentUser === null && isLocalAutoLoginConfigured && !hasAttemptedLocalAutoLoginRef.current) {
        hasAttemptedLocalAutoLoginRef.current = true;
        setEmail(LOCAL_AUTO_LOGIN_EMAIL);
        setPassword(LOCAL_AUTO_LOGIN_PASSWORD);
        try {
          currentUser = (
            await fetchJson<{ user: AuthUser }>("/api/auth/login", {
              body: JSON.stringify({ email: LOCAL_AUTO_LOGIN_EMAIL, password: LOCAL_AUTO_LOGIN_PASSWORD }),
              method: "POST",
            })
          ).user;
        } catch (error) {
          if (isMounted) {
            setLoginErrorText(error instanceof Error ? error.message : "本地演示账号自动登录失败");
          }
        }
      }

      if (!isMounted) {
        return;
      }
      setAuthUser(currentUser);
      if (currentUser?.is_admin) {
        void refreshDashboard();
        setPassword("");
      }
      setIsAuthLoading(false);
    }

    void loadAuthUser();
    return () => {
      isMounted = false;
    };
  }, []);

  async function refreshDashboard(successMessage = "") {
    setIsDataLoading(true);
    setErrorText("");
    if (successMessage) {
      setStatusText("");
    }
    try {
      const nextData = await loadDashboardData();
      setData(nextData);
      setSelectedSessionId((current) => current || nextData.sessions[0]?.session_id || "");
      if (successMessage) {
        setStatusText(successMessage);
      }
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "读取管理端数据失败");
      setStatusText("");
    } finally {
      setIsDataLoading(false);
    }
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginErrorText("");
    try {
      const payload = await fetchJson<{ user: AuthUser }>("/api/auth/login", {
        body: JSON.stringify({ email, password }),
        method: "POST",
      });
      setAuthUser(payload.user);
      setPassword("");
      if (payload.user.is_admin) {
        await refreshDashboard();
      }
    } catch (error) {
      setLoginErrorText(error instanceof Error ? error.message : "登录失败");
    }
  }

  async function handleLogout() {
    await fetchJson("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    setAuthUser(null);
    setEmail("");
    setPassword("");
    setData(emptyDashboardData);
    setSelectedReport(null);
    setSelectedEvents([]);
    setSelectedEvaluation(null);
    setSelectedCandidate(null);
    setSelectedCandidateEvents([]);
  }

  async function runEvaluation() {
    setIsMutating(true);
    setErrorText("");
    try {
      await fetchJson("/api/admin/evals/run", {
        body: JSON.stringify({ batch_id: `admin_v2_manual_${Date.now()}` }),
        method: "POST",
      });
      await refreshDashboard();
      setActiveSectionId("evaluation");
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "运行评测失败");
    } finally {
      setIsMutating(false);
    }
  }

  async function generateSkillCandidates() {
    setIsMutating(true);
    setErrorText("");
    try {
      await fetchJson("/api/admin/evolution/candidates/generate", { method: "POST" });
      await refreshDashboard();
      setActiveSectionId("skill");
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "生成候选 Skill 失败");
    } finally {
      setIsMutating(false);
    }
  }

  async function readSessionReport(sessionId: string) {
    setIsDetailBusy(true);
    setErrorText("");
    try {
      const report = await getSessionReport(sessionId);
      setSelectedReport(report);
      setSelectedSessionId(sessionId);
    } catch (error) {
      const message = error instanceof Error ? error.message : "读取报告失败";
      if (message.toLowerCase().includes("report not found")) {
        setSelectedReport(null);
        setSelectedSessionId(sessionId);
        setStatusText("该 Session 还没有生成评分报告，可先读取日志或等待学生提交诊断。");
      } else {
        setErrorText(message);
      }
    } finally {
      setIsDetailBusy(false);
    }
  }

  async function readSessionEvents(sessionId: string) {
    setIsDetailBusy(true);
    setErrorText("");
    try {
      const events = await getSessionEvents(sessionId);
      setSelectedEvents(events);
      setSelectedSessionId(sessionId);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "读取日志失败");
    } finally {
      setIsDetailBusy(false);
    }
  }

  async function readEvaluationDetail(batchId: string) {
    setIsDetailBusy(true);
    setErrorText("");
    try {
      setSelectedEvaluation(await getEvaluationDetail(batchId));
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "读取评测详情失败");
    } finally {
      setIsDetailBusy(false);
    }
  }

  async function readCandidateDetail(candidateId: string) {
    setIsSkillBusy(true);
    setErrorText("");
    try {
      const [candidate, events] = await Promise.all([getCandidateDetail(candidateId), getCandidateEvents(candidateId)]);
      setSelectedCandidate(candidate);
      setSelectedCandidateEvents(events);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "读取候选 Skill 详情失败");
    } finally {
      setIsSkillBusy(false);
    }
  }

  async function handleCandidateReview(candidateId: string, action: "approve" | "reject") {
    setIsSkillBusy(true);
    setErrorText("");
    try {
      await reviewCandidate(candidateId, action);
      await refreshDashboard();
      await readCandidateDetail(candidateId);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : action === "approve" ? "批准候选 Skill 失败" : "拒绝候选 Skill 失败");
    } finally {
      setIsSkillBusy(false);
    }
  }

  async function handleToggleAutoApproval() {
    setIsSkillBusy(true);
    setErrorText("");
    try {
      const nextSettings = await updateAutoApproval(!(data.autoApprovalSettings?.auto_apply_enabled ?? false));
      setData((current) => ({ ...current, autoApprovalSettings: nextSettings }));
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "更新自动应用设置失败");
    } finally {
      setIsSkillBusy(false);
    }
  }

  async function handleSetDocumentEnabled(documentId: string, enabled: boolean) {
    setIsDocumentBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const nextDocument = await setRagDocumentEnabled(documentId, enabled);
      setData((current) => ({
        ...current,
        documents: current.documents.map((document) => (document.document_id === documentId ? nextDocument : document)),
      }));
      setStatusText(nextDocument.enabled ? "知识库文档已启用。" : "知识库文档已停用。");
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : enabled ? "启用文档失败" : "停用文档失败");
    } finally {
      setIsDocumentBusy(false);
    }
  }

  async function handleSaveKnowledgeItem(item: AdminRagKnowledgeItem): Promise<AdminRagKnowledgeItem> {
    setIsDocumentBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const savedItem = await upsertRagKnowledgeItem(buildRagKnowledgePayload(item));
      setData((current) => {
        const exists = current.knowledgeItems.some((currentItem) => currentItem.knowledge_id === savedItem.knowledge_id);
        return {
          ...current,
          knowledgeItems: exists
            ? current.knowledgeItems.map((currentItem) => (currentItem.knowledge_id === savedItem.knowledge_id ? savedItem : currentItem))
            : [savedItem, ...current.knowledgeItems],
        };
      });
      setStatusText(`已保存知识片段：${savedItem.title || savedItem.knowledge_id}`);
      return savedItem;
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "保存知识库内容失败");
      throw error;
    } finally {
      setIsDocumentBusy(false);
    }
  }

  async function handleUploadRagDocument(payload: AdminRagDocumentUploadPayload): Promise<AdminRagDocumentUploadResponse> {
    setIsDocumentBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const response = await uploadRagDocument(payload);
      setData((current) => {
        const exists = current.documents.some((document) => document.document_id === response.document.document_id);
        const nextKnowledgeItems = [
          ...(response.knowledge_items ?? []),
          ...current.knowledgeItems.filter(
            (item) => !item.document_id || item.document_id !== response.document.document_id,
          ),
        ];
        return {
          ...current,
          documents: exists
            ? current.documents.map((document) => (document.document_id === response.document.document_id ? response.document : document))
            : [response.document, ...current.documents],
          knowledgeItems: nextKnowledgeItems,
        };
      });
      setStatusText(`已上传文档：${response.document.title || response.document.file_name || response.document.filename || response.document.document_id}`);
      return response;
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "上传文档失败");
      throw error;
    } finally {
      setIsDocumentBusy(false);
    }
  }

  async function handleUpdateCaseFields(caseId: string, payload: AdminCaseFieldUpdatePayload): Promise<AdminCaseRaw> {
    setIsDocumentBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const updatedCase = await updateAdminCaseFields(caseId, payload);
      setData((current) => ({
        ...current,
        cases: current.cases.map((caseItem) =>
          caseItem.case_id === caseId
            ? {
                ...caseItem,
                chief_complaint: getStringField(updatedCase, "chief_complaint", caseItem.chief_complaint ?? ""),
                difficulty: getStringField(updatedCase, "difficulty", caseItem.difficulty ?? ""),
                title: getStringField(updatedCase, "case_title", caseItem.title ?? ""),
              }
            : caseItem,
        ),
      }));
      setStatusText(`已保存病例：${getStringField(updatedCase, "case_title", caseId)}`);
      return updatedCase;
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "保存病例失败");
      throw error;
    } finally {
      setIsDocumentBusy(false);
    }
  }

  async function handleUpdateRubricItem(rubricId: string, itemId: string, description: string): Promise<AdminRubricDetail> {
    setIsDocumentBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const updatedRubric = await updateAdminRubricItemDescription(rubricId, itemId, description);
      setStatusText("评分项说明已保存。");
      return updatedRubric;
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "保存评分项失败");
      throw error;
    } finally {
      setIsDocumentBusy(false);
    }
  }

  async function handleValidateCaseCreation(payload: AdminCaseCreationPayload): Promise<AdminCaseImportStatus> {
    setIsCaseCreationBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      return await validateAdminCaseCreation(payload);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "病例预检失败");
      throw error;
    } finally {
      setIsCaseCreationBusy(false);
    }
  }

  async function handleImportCaseCreation(payload: AdminCaseCreationPayload): Promise<AdminCaseImportStatus> {
    setIsCaseCreationBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const result = await importAdminCaseCreation(payload);
      if (result.imported) {
        await refreshDashboard();
        setIsCaseCreationOpen(false);
        setStatusText(`已发布病例：${result.case_id ?? "新病例"}`);
      }
      return result;
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "发布病例失败");
      throw error;
    } finally {
      setIsCaseCreationBusy(false);
    }
  }

  if (isAuthLoading) {
    return (
      <main className="min-h-screen bg-[#F6F4EE] p-6 text-[#141413]">
        <div className="flex min-h-[60vh] items-center justify-center">
          <div className="flex items-center gap-3 rounded-2xl border border-[#E7E0D4] bg-white px-5 py-4 shadow-sm">
            <Loader2 className="size-5 animate-spin text-[#AE5630]" />
            <span className="text-sm font-medium">正在读取管理员状态</span>
          </div>
        </div>
      </main>
    );
  }

  if (!authUser?.is_admin) {
    return (
      <main className="min-h-screen bg-[#F6F4EE] p-6 text-[#141413]">
        <section className="mx-auto mt-20 w-full max-w-md rounded-3xl border border-[#E7E0D4] bg-white p-8 shadow-sm">
          <h1 className="text-2xl font-semibold">管理员登录</h1>
          <form autoComplete="off" className="mt-6 grid gap-4" onSubmit={(event) => void handleLogin(event)}>
            <label className="grid gap-2 text-sm font-medium">
              邮箱
              <Input autoComplete="off" maxLength={AUTH_EMAIL_MAX_CHARS} onChange={(event) => setEmail(event.target.value)} placeholder="输入管理员邮箱" type="email" value={email} />
            </label>
            <label className="grid gap-2 text-sm font-medium">
              密码
              <Input autoComplete="new-password" maxLength={AUTH_PASSWORD_MAX_CHARS} onChange={(event) => setPassword(event.target.value)} placeholder="输入管理员账号密码" type="password" value={password} />
            </label>
            {loginErrorText ? <p className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{loginErrorText}</p> : null}
            {authUser && !authUser.is_admin ? <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">当前账号没有管理员权限。</p> : null}
            <Button disabled={!email.trim() || !password} type="submit">
              登录
            </Button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#F6F4EE] text-[#141413]">
      <div className="grid min-h-screen lg:grid-cols-[18rem_1fr]">
        <aside className="border-r border-[#E7E0D4] bg-white/92 p-4 lg:sticky lg:top-0 lg:h-screen">
          <div className="rounded-3xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-2xl bg-[#141413] text-white">
                <ShieldCheck className="size-5" />
              </div>
              <h1 className="text-base font-semibold">管理工作台</h1>
            </div>
          </div>
          <nav aria-label="新版管理后台导航" className="mt-4 grid gap-2">
            {sections.map((section) => {
              const Icon = section.icon;
              const isActive = activeSectionId === section.id;
              return (
                <button
                  className={cn(
                    "flex w-full items-center gap-3 rounded-2xl border px-3 py-3 text-left transition",
                    isActive ? "border-[#141413] bg-[#141413] text-white shadow-sm" : "border-transparent bg-transparent text-[#6F6257] hover:border-[#E7E0D4] hover:bg-[#FAF9F5] hover:text-[#141413]",
                  )}
                  key={section.id}
                  onClick={() => setActiveSectionId(section.id)}
                  type="button"
                >
                  <Icon className="size-4" />
                  <span className="text-sm font-semibold">{section.label}</span>
                </button>
              );
            })}
          </nav>
          <div className="mt-4 grid gap-2">
            <Button aria-label="刷新管理数据" disabled={isDataLoading} onClick={() => void refreshDashboard("已刷新管理数据")} variant="secondary">
              {isDataLoading ? <Loader2 className="animate-spin" /> : <RefreshCw />}
              刷新
            </Button>
            <Button onClick={() => void handleLogout()} variant="ghost">
              <LogOut />
              退出登录
            </Button>
          </div>
        </aside>
        <section className="min-w-0 p-4 sm:p-6">
          {errorText ? <p className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{errorText}</p> : null}
          {statusText ? <p className={cn("rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800", errorText ? "mt-3" : "")}>{statusText}</p> : null}

          <div className={cn(errorText || statusText ? "mt-4" : "")}>
            {activeSectionId === "overview" ? (
              <OverviewSection data={data} onGenerateSkillCandidates={() => void generateSkillCandidates()} onRunEvaluation={() => void runEvaluation()} isMutating={isMutating} />
            ) : null}
            {activeSectionId === "resources" ? (
              <ResourcesSection
                data={data}
                isDocumentBusy={isDocumentBusy}
                onOpenCaseCreation={() => setIsCaseCreationOpen(true)}
                onSaveCaseFields={(caseId, payload) => handleUpdateCaseFields(caseId, payload)}
                onSaveKnowledgeItem={(item) => handleSaveKnowledgeItem(item)}
                onSaveRubricItem={(rubricId, itemId, description) => handleUpdateRubricItem(rubricId, itemId, description)}
                onSetDocumentEnabled={(documentId, enabled) => void handleSetDocumentEnabled(documentId, enabled)}
                onUploadDocument={(payload) => handleUploadRagDocument(payload)}
              />
            ) : null}
            {activeSectionId === "training" ? (
              <TrainingSection
                data={data}
                isDetailBusy={isDetailBusy}
                onReadEvents={(sessionId) => void readSessionEvents(sessionId)}
                onReadReport={(sessionId) => void readSessionReport(sessionId)}
                onSelectSession={setSelectedSessionId}
                selectedEvents={selectedEvents}
                selectedReport={selectedReport}
                selectedSession={selectedSession}
              />
            ) : null}
            {activeSectionId === "insights" ? <InsightsSection data={data} /> : null}
            {activeSectionId === "skill" ? (
              <SkillSection
                data={data}
                isMutating={isMutating}
                isSkillBusy={isSkillBusy}
                onGenerateSkillCandidates={() => void generateSkillCandidates()}
                onReadCandidate={(candidateId) => void readCandidateDetail(candidateId)}
                onReviewCandidate={(candidateId, action) => void handleCandidateReview(candidateId, action)}
                onToggleAutoApproval={() => void handleToggleAutoApproval()}
                selectedCandidate={selectedCandidate}
                selectedCandidateEvents={selectedCandidateEvents}
              />
            ) : null}
            {activeSectionId === "evaluation" ? (
              <EvaluationSection data={data} isDetailBusy={isDetailBusy} isMutating={isMutating} onReadEvaluation={(batchId) => void readEvaluationDetail(batchId)} onRunEvaluation={() => void runEvaluation()} selectedEvaluation={selectedEvaluation} />
            ) : null}
            {activeSectionId === "logs" ? <LogsSection data={data} /> : null}
          </div>
          {isCaseCreationOpen ? (
            <CaseCreationModal
              cases={data.cases}
              isSaving={isCaseCreationBusy}
              onClose={() => setIsCaseCreationOpen(false)}
              onImport={(payload) => handleImportCaseCreation(payload)}
              onValidate={(payload) => handleValidateCaseCreation(payload)}
              sources={data.sources}
            />
          ) : null}
        </section>
      </div>
    </main>
  );
}

function OverviewSection({
  data,
  isMutating,
  onGenerateSkillCandidates,
  onRunEvaluation,
}: Readonly<{
  data: DashboardData;
  isMutating: boolean;
  onGenerateSkillCandidates: () => void;
  onRunEvaluation: () => void;
}>) {
  const enabledProviders = data.modelConfig?.providers.filter((provider) => provider.enabled && provider.configured).length ?? 0;
  const successRate = Math.round((data.apiLogs?.summary.success_rate ?? 0) * 100);
  return (
    <div className="grid gap-4">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard icon={<Stethoscope />} label="训练 Session" value={formatCount(data.sessionPagination?.total ?? data.sessions.length)} helper="最近训练证据" />
        <MetricCard icon={<FileText />} label="评分报告" value={formatCount(data.reportPagination?.total ?? data.reports.length)} helper="可追踪报告" />
        <MetricCard icon={<Sparkles />} label="候选 Skill" value={formatCount(data.candidatePagination?.total ?? data.candidates.length)} helper="待审核与已处理" />
        <MetricCard icon={<Gauge />} label="模型成功率" value={`${successRate}%`} helper={`${enabledProviders} 个能力可用`} />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <Card>
          <CardHeader className="flex-row items-start justify-between gap-4">
            <div>
              <CardTitle>近期训练</CardTitle>
              <CardDescription>按更新时间查看最近 Session，详情在训练管理中展开。</CardDescription>
            </div>
            <Badge variant="muted">{data.sessions.length} 条</Badge>
          </CardHeader>
          <CardContent>
            <SessionTable sessions={data.sessions.slice(0, 8)} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>快捷动作</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3">
            <Button disabled={isMutating} onClick={onGenerateSkillCandidates}>
              {isMutating ? <Loader2 className="animate-spin" /> : <Sparkles />}
              从训练日志生成候选 Skill
            </Button>
            <Button disabled={isMutating} onClick={onRunEvaluation} variant="secondary">
              {isMutating ? <Loader2 className="animate-spin" /> : <ClipboardCheck />}
              运行系统评测
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function ResourcesSection({
  data,
  isDocumentBusy,
  onOpenCaseCreation,
  onSaveCaseFields,
  onSaveKnowledgeItem,
  onSaveRubricItem,
  onSetDocumentEnabled,
  onUploadDocument,
}: Readonly<{
  data: DashboardData;
  isDocumentBusy: boolean;
  onOpenCaseCreation: () => void;
  onSaveCaseFields: (caseId: string, payload: AdminCaseFieldUpdatePayload) => Promise<AdminCaseRaw>;
  onSaveKnowledgeItem: (item: AdminRagKnowledgeItem) => Promise<AdminRagKnowledgeItem>;
  onSaveRubricItem: (rubricId: string, itemId: string, description: string) => Promise<AdminRubricDetail>;
  onSetDocumentEnabled: (documentId: string, enabled: boolean) => void;
  onUploadDocument: (payload: AdminRagDocumentUploadPayload) => Promise<AdminRagDocumentUploadResponse>;
}>) {
  const [openDocumentId, setOpenDocumentId] = useState("");
  const [openCaseDetail, setOpenCaseDetail] = useState<AdminCaseRaw | null>(null);
  const [editingCase, setEditingCase] = useState<AdminCaseRaw | null>(null);
  const [rubricDetail, setRubricDetail] = useState<AdminRubricDetail | null>(null);
  const [caseDetailErrorText, setCaseDetailErrorText] = useState("");
  const [loadingCaseId, setLoadingCaseId] = useState("");
  const [loadingRubricCaseId, setLoadingRubricCaseId] = useState("");
  const activeDocumentId = openDocumentId;
  const openDocument = data.documents.find((document) => document.document_id === openDocumentId) ?? null;
  const openDocumentItems = data.knowledgeItems
    .filter((item) => item.document_id === openDocumentId)
    .sort((left, right) => (left.chunk_index ?? 0) - (right.chunk_index ?? 0));

  function handleOpenDocument(documentId: string) {
    setOpenDocumentId(documentId);
  }

  async function handleOpenCaseDetail(caseId: string) {
    setLoadingCaseId(caseId);
    setCaseDetailErrorText("");
    try {
      setOpenCaseDetail(await getAdminCaseRaw(caseId));
    } catch (error) {
      setCaseDetailErrorText(error instanceof Error ? error.message : "读取病例详情失败");
    } finally {
      setLoadingCaseId("");
    }
  }

  async function handleOpenCaseEditor(caseId: string) {
    setLoadingCaseId(caseId);
    setCaseDetailErrorText("");
    try {
      setEditingCase(await getAdminCaseRaw(caseId));
    } catch (error) {
      setCaseDetailErrorText(error instanceof Error ? error.message : "读取病例失败");
    } finally {
      setLoadingCaseId("");
    }
  }

  async function handleOpenRubric(caseId: string) {
    setLoadingRubricCaseId(caseId);
    setCaseDetailErrorText("");
    try {
      const casePayload = await getAdminCaseRaw(caseId);
      const rubricId = getStringField(getRecordField(casePayload, "rubric_ref"), "rubric_id", "");
      if (!rubricId) {
        throw new Error("该病例未绑定 Rubric。");
      }
      setRubricDetail(await getAdminRubric(rubricId));
    } catch (error) {
      setCaseDetailErrorText(error instanceof Error ? error.message : "读取 Rubric 失败");
    } finally {
      setLoadingRubricCaseId("");
    }
  }

  return (
    <div className="grid gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <SectionIntro eyebrow="教学资源" title="病例、来源和知识库" description="管理训练病例、来源台账和教学知识库。" />
        <Button onClick={onOpenCaseCreation}>
          <PlusCircle />
          新建病例
        </Button>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard icon={<BookOpen />} label="病例" value={formatCount(data.cases.length)} helper="学生可训练病例" />
        <MetricCard icon={<FileText />} label="来源" value={formatCount(data.sources.length)} helper="来源台账" />
        <MetricCard icon={<Brain />} label="知识库文档" value={formatCount(data.documents.length)} helper={`${data.documents.filter((document) => document.enabled).length} 份已启用`} />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>病例台账</CardTitle>
          <CardDescription>展示当前可训练病例；新增病例会先通过结构校验，再写入病例与 Rubric 文件。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {data.cases.map((caseItem) => (
              <article className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4" key={caseItem.case_id}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="truncate text-base font-semibold">{caseItem.title || caseItem.case_id}</h3>
                    <p className="mt-2 line-clamp-2 text-sm leading-6 text-[#6F6257]">{caseItem.chief_complaint || "未填写主诉"}</p>
                  </div>
                  <Badge variant="muted">{caseItem.difficulty || "未分级"}</Badge>
                </div>
                <div className="mt-4 flex items-center justify-between gap-3">
                  <p className="truncate text-xs text-[#8A7D6F]">{caseItem.case_id}</p>
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button disabled={loadingCaseId === caseItem.case_id} onClick={() => void handleOpenCaseDetail(caseItem.case_id)} size="sm" type="button" variant="secondary">
                      {loadingCaseId === caseItem.case_id ? <Loader2 className="animate-spin" /> : <FileText />}
                      查看详情
                    </Button>
                    <Button disabled={loadingCaseId === caseItem.case_id} onClick={() => void handleOpenCaseEditor(caseItem.case_id)} size="sm" type="button" variant="secondary">
                      编辑病例
                    </Button>
                    <Button disabled={loadingRubricCaseId === caseItem.case_id} onClick={() => void handleOpenRubric(caseItem.case_id)} size="sm" type="button" variant="secondary">
                      {loadingRubricCaseId === caseItem.case_id ? <Loader2 className="animate-spin" /> : null}
                      查看 Rubric
                    </Button>
                  </div>
                </div>
              </article>
            ))}
          </div>
          {caseDetailErrorText ? <p className="mt-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{caseDetailErrorText}</p> : null}
          {data.cases.length === 0 ? <EmptyText>暂无病例。点击“新建病例”开始录入。</EmptyText> : null}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>知识库文档</CardTitle>
          <CardDescription>教师上传的全局或病例知识库，启用后进入所选 Agent 的 RAG 检索。</CardDescription>
        </CardHeader>
        <CardContent>
          <DocumentUploadPanel
            cases={data.cases}
            documents={data.documents}
            isSaving={isDocumentBusy}
            onUploadDocument={onUploadDocument}
            sources={data.sources}
          />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-[#8A7D6F]">
                <tr className="border-b border-[#E7E0D4]">
                  <th className="py-3 pr-4">文档</th>
                  <th className="py-3 pr-4">范围</th>
                  <th className="py-3 pr-4">关联病例</th>
                  <th className="py-3 pr-4">片段</th>
                  <th className="py-3 pr-4">状态</th>
                  <th className="py-3 pr-4">操作</th>
                </tr>
              </thead>
              <tbody>
                {data.documents.slice(0, 12).map((document) => (
                  <tr className="border-b border-[#F0E8DC]" key={document.document_id}>
                    <td className="py-3 pr-4 font-medium">{document.title || document.filename || document.document_id}</td>
                    <td className="py-3 pr-4 text-[#6F6257]">{document.scope === "case" ? "病例知识库" : "全局知识库"}</td>
                    <td className="py-3 pr-4 text-[#6F6257]">{document.case_title || "全部病例"}</td>
                    <td className="py-3 pr-4 text-[#6F6257]">{document.chunk_count ?? "-"}</td>
                    <td className="py-3 pr-4">
                      <Badge variant={document.enabled ? "success" : "muted"}>{document.enabled ? "已启用" : "未启用"}</Badge>
                    </td>
                    <td className="py-3 pr-4">
                      <div className="flex flex-wrap gap-2">
                        <Button onClick={() => handleOpenDocument(document.document_id)} size="sm" variant={activeDocumentId === document.document_id ? "default" : "secondary"}>
                          查看内容
                        </Button>
                        <Button disabled={isDocumentBusy} onClick={() => onSetDocumentEnabled(document.document_id, !document.enabled)} size="sm" variant={document.enabled ? "outline" : "secondary"}>
                          {document.enabled ? "停用文档" : "启用文档"}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.documents.length === 0 ? <EmptyText>暂无知识库文档。</EmptyText> : null}
        </CardContent>
      </Card>
      {openDocument ? (
        <KnowledgeContentModal
          document={openDocument}
          isSaving={isDocumentBusy}
          items={openDocumentItems}
          onClose={() => setOpenDocumentId("")}
          onSaveKnowledgeItem={onSaveKnowledgeItem}
        />
      ) : null}
      {openCaseDetail ? <CaseDetailModal casePayload={openCaseDetail} onClose={() => setOpenCaseDetail(null)} /> : null}
      {editingCase ? (
        <CaseEditModal
          casePayload={editingCase}
          isSaving={isDocumentBusy}
          onClose={() => setEditingCase(null)}
          onSave={async (caseId, payload) => {
            const updatedCase = await onSaveCaseFields(caseId, payload);
            setEditingCase(updatedCase);
          }}
        />
      ) : null}
      {rubricDetail ? (
        <RubricEditModal
          isSaving={isDocumentBusy}
          onClose={() => setRubricDetail(null)}
          onSaveItem={async (rubricId, itemId, description) => {
            const updatedRubric = await onSaveRubricItem(rubricId, itemId, description);
            setRubricDetail(updatedRubric);
          }}
          rubric={rubricDetail}
        />
      ) : null}
    </div>
  );
}

function DocumentUploadPanel({
  cases,
  documents,
  isSaving,
  onUploadDocument,
  sources,
}: Readonly<{
  cases: readonly AdminCaseSummary[];
  documents: readonly AdminRagDocument[];
  isSaving: boolean;
  onUploadDocument: (payload: AdminRagDocumentUploadPayload) => Promise<AdminRagDocumentUploadResponse>;
  sources: readonly AdminSourceSummary[];
}>) {
  const defaultCaseId = cases[0]?.case_id ?? "";
  const defaultSourceId = sources[0]?.source_id ?? "";
  const [scope, setScope] = useState("case");
  const [caseId, setCaseId] = useState(defaultCaseId);
  const [sourceId, setSourceId] = useState(defaultSourceId);
  const [visibility, setVisibility] = useState("pre_submit_safe");
  const [tags, setTags] = useState("teacher_document");
  const [allowedAgents, setAllowedAgents] = useState<readonly string[]>(["coach", "reflection", "skill_generation", "skill_approval"]);
  const [enabled, setEnabled] = useState(true);
  const [file, setFile] = useState<File | null>(null);
  const [localErrorText, setLocalErrorText] = useState("");
  const [localStatusText, setLocalStatusText] = useState("");

  useEffect(() => {
    setCaseId((current) => current || defaultCaseId);
  }, [defaultCaseId]);

  useEffect(() => {
    setSourceId((current) => current || defaultSourceId);
  }, [defaultSourceId]);

  async function handleUpload() {
    setLocalErrorText("");
    setLocalStatusText("");
    if (!file) {
      setLocalErrorText("请选择要上传的文档。");
      return;
    }
    if (file.size > RAG_DOCUMENT_MAX_BYTES) {
      setLocalErrorText("文档不能超过 8 MiB。");
      return;
    }
    if (file.name.length > RAG_FILE_NAME_MAX_CHARS) {
      setLocalErrorText(`文件名不能超过 ${RAG_FILE_NAME_MAX_CHARS} 个字符。`);
      return;
    }
    if (scope === "case" && !caseId) {
      setLocalErrorText("病例知识库需要先选择关联病例。");
      return;
    }
    const parsedTags = toTokenList(tags);
    if (parsedTags.length > RAG_TAGS_MAX_ITEMS || parsedTags.some((tag) => tag.length > RAG_TAG_MAX_CHARS)) {
      setLocalErrorText(`标签最多 ${RAG_TAGS_MAX_ITEMS} 个，每个不能超过 ${RAG_TAG_MAX_CHARS} 个字符。`);
      return;
    }
    try {
      const response = await onUploadDocument({
        allowed_agents: allowedAgents,
        case_id: scope === "case" ? caseId : "",
        content_base64: await readFileAsBase64(file),
        enabled,
        file_name: file.name,
        scope,
        source_id: sourceId,
        tags: parsedTags,
        visibility,
      });
      setLocalStatusText(`已切分 ${response.knowledge_items?.length ?? response.document.chunk_count ?? 0} 个知识片段。`);
      setFile(null);
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "上传文档失败");
    }
  }

  function toggleAgent(agentId: string) {
    setAllowedAgents((current) => (current.includes(agentId) ? current.filter((item) => item !== agentId) : [...current, agentId]));
  }

  return (
    <details className="mb-5 rounded-3xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
      <summary className="cursor-pointer select-none text-base font-semibold">上传文档</summary>
      <div className="mt-4 grid gap-4">
        <div className="grid gap-3 lg:grid-cols-3">
          <FormField label="知识库范围">
            <SelectInput optionLabels={{ case: "病例知识库", global: "全局知识库" }} options={["case", "global"]} value={scope} onChange={setScope} />
          </FormField>
          <FormField label="关联病例">
            <SelectInput
              optionLabels={Object.fromEntries(cases.map((caseItem) => [caseItem.case_id, caseItem.title || caseItem.case_id]))}
              options={scope === "case" ? cases.map((caseItem) => caseItem.case_id) : [""]}
              value={scope === "case" ? caseId : ""}
              onChange={setCaseId}
            />
          </FormField>
          <FormField label="可见范围">
            <SelectInput
              optionLabels={{
                admin_only: "仅管理员可见",
                post_submit_review: "提交后复盘可用",
                pre_submit_safe: "训练前可用于提示",
              }}
              options={["pre_submit_safe", "post_submit_review", "admin_only"]}
              value={visibility}
              onChange={setVisibility}
            />
          </FormField>
        </div>
        <div className="grid gap-3 lg:grid-cols-[1fr_1fr_1.2fr]">
          <FormField label="关联来源">
            <SelectInput
              optionLabels={{ "": "不绑定来源", ...Object.fromEntries(sources.map((source) => [source.source_id, source.title || source.source_id])) }}
              options={["", ...sources.map((source) => source.source_id)]}
              value={sourceId}
              onChange={setSourceId}
            />
          </FormField>
          <FormField label="标签">
            <Input onChange={(event) => setTags(event.target.value)} placeholder="例如 acute_abdomen,teaching" value={tags} />
          </FormField>
          <FormField label="文档文件">
            <Input
              accept=".md,.txt,.pdf,.docx,.html,.htm"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              type="file"
            />
          </FormField>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {["coach", "reflection", "skill_generation", "skill_approval"].map((agentId) => (
            <label className="flex items-center gap-2 rounded-2xl border border-[#E7E0D4] bg-white px-3 py-2 text-sm" key={agentId}>
              <input checked={allowedAgents.includes(agentId)} onChange={() => toggleAgent(agentId)} type="checkbox" />
              {getAgentLabel(agentId)}
            </label>
          ))}
          <label className="flex items-center gap-2 rounded-2xl border border-[#E7E0D4] bg-white px-3 py-2 text-sm">
            <input checked={enabled} onChange={(event) => setEnabled(event.target.checked)} type="checkbox" />
            上传后启用
          </label>
          <Button disabled={isSaving} onClick={() => void handleUpload()} type="button">
            {isSaving ? <Loader2 className="animate-spin" /> : <PlusCircle />}
            上传文档
          </Button>
          <p className="text-sm text-[#6F6257]">{file ? file.name : `${documents.length} 份文档已在库中`}</p>
        </div>
        {localErrorText ? <p className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{localErrorText}</p> : null}
        {localStatusText ? <p className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{localStatusText}</p> : null}
      </div>
    </details>
  );
}

function CaseEditModal({
  casePayload,
  isSaving,
  onClose,
  onSave,
}: Readonly<{
  casePayload: AdminCaseRaw;
  isSaving: boolean;
  onClose: () => void;
  onSave: (caseId: string, payload: AdminCaseFieldUpdatePayload) => Promise<void>;
}>) {
  const caseId = getStringField(casePayload, "case_id", "");
  const [caseTitle, setCaseTitle] = useState(getStringField(casePayload, "case_title", ""));
  const [chiefComplaint, setChiefComplaint] = useState(getStringField(casePayload, "chief_complaint", ""));
  const [courseModule, setCourseModule] = useState(getStringField(casePayload, "course_module", "腹痛"));
  const [difficulty, setDifficulty] = useState(getStringField(casePayload, "difficulty", "初级"));
  const [safetyNotes, setSafetyNotes] = useState(getStringField(casePayload, "safety_notes", ""));
  const [localErrorText, setLocalErrorText] = useState("");

  useEffect(() => {
    setCaseTitle(getStringField(casePayload, "case_title", ""));
    setChiefComplaint(getStringField(casePayload, "chief_complaint", ""));
    setCourseModule(getStringField(casePayload, "course_module", "腹痛"));
    setDifficulty(getStringField(casePayload, "difficulty", "初级"));
    setSafetyNotes(getStringField(casePayload, "safety_notes", ""));
    setLocalErrorText("");
  }, [casePayload]);

  async function handleSave() {
    setLocalErrorText("");
    if (!caseTitle.trim() || !chiefComplaint.trim()) {
      setLocalErrorText("病例标题和主诉不能为空。");
      return;
    }
    if (
      caseTitle.trim().length > CASE_TITLE_MAX_CHARS
      || chiefComplaint.trim().length > CHIEF_COMPLAINT_MAX_CHARS
      || safetyNotes.trim().length > SAFETY_NOTES_MAX_CHARS
    ) {
      setLocalErrorText(
        `病例标题不能超过 ${CASE_TITLE_MAX_CHARS} 个字符，主诉不能超过 ${CHIEF_COMPLAINT_MAX_CHARS} 个字符，边界说明不能超过 ${SAFETY_NOTES_MAX_CHARS} 个字符。`,
      );
      return;
    }
    try {
      await onSave(caseId, {
        case_title: caseTitle.trim(),
        chief_complaint: chiefComplaint.trim(),
        course_module: courseModule.trim(),
        difficulty: difficulty.trim(),
        safety_notes: safetyNotes.trim(),
      });
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "保存病例失败");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4" role="dialog" aria-modal="true" aria-label="编辑病例">
      <div className="grid max-h-[86vh] w-full max-w-3xl grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-3xl border border-[#E7E0D4] bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-[#E7E0D4] px-6 py-5">
          <div>
            <p className="text-xs font-semibold text-[#AE5630]">病例台账</p>
            <h3 className="mt-1 text-2xl font-semibold">编辑病例</h3>
            <p className="mt-2 text-sm text-[#6F6257]">{caseId || "未记录病例 ID"}</p>
          </div>
          <Button onClick={onClose} variant="secondary">关闭</Button>
        </div>
        <div className="min-h-0 overflow-y-auto p-6">
          <div className="grid gap-4">
            <FormField label="病例标题">
              <Input maxLength={CASE_TITLE_MAX_CHARS} onChange={(event) => setCaseTitle(event.target.value)} value={caseTitle} />
            </FormField>
            <FormField label="主诉">
              <Input maxLength={CHIEF_COMPLAINT_MAX_CHARS} onChange={(event) => setChiefComplaint(event.target.value)} value={chiefComplaint} />
            </FormField>
            <div className="grid gap-4 md:grid-cols-2">
              <FormField label="课程模块">
                <SelectInput options={courseModuleOptions} value={courseModule} onChange={setCourseModule} />
              </FormField>
              <FormField label="训练难度">
                <SelectInput options={["初级", "中级", "高级"]} value={difficulty} onChange={setDifficulty} />
              </FormField>
            </div>
            <FormField label="边界说明">
              <TextAreaInput maxLength={SAFETY_NOTES_MAX_CHARS} onChange={setSafetyNotes} value={safetyNotes} />
            </FormField>
            {localErrorText ? <p className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{localErrorText}</p> : null}
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-[#E7E0D4] px-6 py-4">
          <Button onClick={onClose} variant="secondary">取消</Button>
          <Button disabled={isSaving} onClick={() => void handleSave()}>
            {isSaving ? <Loader2 className="animate-spin" /> : <FileText />}
            保存基础信息
          </Button>
        </div>
      </div>
    </div>
  );
}

function RubricEditModal({
  isSaving,
  onClose,
  onSaveItem,
  rubric,
}: Readonly<{
  isSaving: boolean;
  onClose: () => void;
  onSaveItem: (rubricId: string, itemId: string, description: string) => Promise<void>;
  rubric: AdminRubricDetail;
}>) {
  const [drafts, setDrafts] = useState<Record<string, string>>(() => buildRubricDescriptionDrafts(rubric));
  const [localErrorText, setLocalErrorText] = useState("");

  useEffect(() => {
    setDrafts(buildRubricDescriptionDrafts(rubric));
    setLocalErrorText("");
  }, [rubric]);

  async function handleSaveItem(itemId: string) {
    const description = drafts[itemId]?.trim() ?? "";
    if (!description) {
      setLocalErrorText("评分项说明不能为空。");
      return;
    }
    if (description.length > RUBRIC_DESCRIPTION_MAX_CHARS) {
      setLocalErrorText(`评分项说明不能超过 ${RUBRIC_DESCRIPTION_MAX_CHARS} 个字符。`);
      return;
    }
    try {
      await onSaveItem(rubric.rubric_id, itemId, description);
      setLocalErrorText("");
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "保存评分项失败");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4" role="dialog" aria-modal="true" aria-label="查看 Rubric">
      <div className="grid max-h-[88vh] w-full max-w-6xl grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-3xl border border-[#E7E0D4] bg-white shadow-2xl">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-[#E7E0D4] px-6 py-5">
          <div>
            <p className="text-xs font-semibold text-[#AE5630]">评分 Rubric</p>
            <h3 className="mt-1 text-2xl font-semibold">查看 Rubric</h3>
            <p className="mt-2 text-sm text-[#6F6257]">总分 {rubric.total_score} · {rubric.dimensions.length} 个评分维度</p>
          </div>
          <Button onClick={onClose} variant="secondary">关闭</Button>
        </div>
        <div className="min-h-0 overflow-y-auto p-6">
          <div className="grid gap-4">
            {rubric.dimensions.map((dimension) => (
              <section className="rounded-3xl border border-[#E7E0D4] bg-[#FAF9F5] p-5" key={dimension.dimension_id}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h4 className="text-lg font-semibold">{getRubricDimensionLabel(dimension.dimension_id)}</h4>
                    <p className="mt-1 text-sm text-[#6F6257]">权重 {dimension.weight} · {dimension.items.length} 个评分项</p>
                  </div>
                  <Badge variant="muted">{dimension.scoring_mode}</Badge>
                </div>
                <div className="mt-4 grid gap-3">
                  {dimension.items.map((item) => (
                    <article className="rounded-2xl border border-[#E7E0D4] bg-white p-4" key={item.item_id}>
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold">{item.description || item.item_id}</p>
                          <p className="mt-1 text-xs text-[#8A7D6F]">最高 {item.max_score} 分 · {item.item_id}</p>
                        </div>
                        <Badge variant="muted">{joinText(item.evidence_expected, "无绑定证据")}</Badge>
                      </div>
                      <div className="mt-3 grid gap-2 md:grid-cols-[1fr_auto]">
                        <Input
                          maxLength={RUBRIC_DESCRIPTION_MAX_CHARS}
                          onChange={(event) => setDrafts((current) => ({ ...current, [item.item_id]: event.target.value }))}
                          value={drafts[item.item_id] ?? item.description}
                        />
                        <Button disabled={isSaving} onClick={() => void handleSaveItem(item.item_id)} type="button" variant="secondary">
                          {isSaving ? <Loader2 className="animate-spin" /> : null}
                          保存评分项
                        </Button>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            ))}
            {localErrorText ? <p className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{localErrorText}</p> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function CaseDetailModal({ casePayload, onClose }: Readonly<{ casePayload: AdminCaseRaw; onClose: () => void }>) {
  const patientProfile = getRecordField(casePayload, "patient_profile");
  const history = getRecordField(casePayload, "history");
  const physicalExam = getRecordField(casePayload, "physical_exam");
  const auxiliaryTests = getRecordField(casePayload, "auxiliary_tests");
  const diagnosis = getRecordField(casePayload, "diagnosis");
  const sourceAttribution = getRecordField(casePayload, "source_attribution");
  const teachingFocus = getRecordField(casePayload, "teaching_focus");
  const hiddenFacts = getRecordList(history?.hidden_facts);
  const examItems = [...getRecordList(physicalExam?.must_items), ...getRecordList(physicalExam?.optional_items)];
  const testItems = [...getRecordList(auxiliaryTests?.must_items), ...getRecordList(auxiliaryTests?.optional_items), ...getRecordList(auxiliaryTests?.forbidden_items)];
  const differentialDiagnoses = getRecordList(diagnosis?.differential_diagnoses);
  const reasoningPoints = getRecordList(diagnosis?.reasoning_points);

  const patientMeta = [
    getAgeGenderLabel(patientProfile),
    getStringField(patientProfile, "occupation", ""),
    getStringField(patientProfile, "hospital_department", ""),
  ].filter(Boolean);
  const iceItems = [
    getStringField(patientProfile, "idea", "") ? `想法：${getStringField(patientProfile, "idea", "")}` : "",
    getStringField(patientProfile, "concern", "") ? `担忧：${getStringField(patientProfile, "concern", "")}` : "",
    getStringField(patientProfile, "expectation", "") ? `期望：${getStringField(patientProfile, "expectation", "")}` : "",
  ].filter(Boolean);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4" role="dialog" aria-modal="true" aria-label="病例详情">
      <div className="grid max-h-[88vh] w-full max-w-6xl grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-3xl border border-[#E7E0D4] bg-white shadow-2xl">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-[#E7E0D4] px-6 py-5">
          <div className="min-w-0">
            <p className="text-xs font-semibold text-[#AE5630]">病例详情</p>
            <h3 className="mt-1 text-2xl font-semibold">{getStringField(casePayload, "case_title", getStringField(casePayload, "case_id", "未命名病例"))}</h3>
            <p className="mt-2 text-sm leading-6 text-[#6F6257]">
              {getStringField(casePayload, "case_id", "未记录")} · {getStringField(casePayload, "course_module", "未记录")} · {getStringField(casePayload, "difficulty", "未分级")}
            </p>
          </div>
          <Button onClick={onClose} variant="secondary">
            关闭
          </Button>
        </div>
        <div className="min-h-0 overflow-y-auto p-6">
          <div className="grid gap-4">
            <div className="grid gap-4 md:grid-cols-3">
              <InfoBlock title="主诉" value={getStringField(casePayload, "chief_complaint", "未记录")} />
              <InfoBlock title="来源" value={getStringField(sourceAttribution, "source_id", "未绑定来源")} />
              <InfoBlock title="Rubric" value={getStringField(getRecordField(casePayload, "rubric_ref"), "rubric_id", "未绑定 Rubric")} />
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <CaseDetailPanel title="病人信息">
                <CaseDetailLine label="基本信息" value={patientMeta.join(" · ") || "未记录"} />
                <CaseDetailLine label="现病史概要" value={getStringField(history, "present_illness_summary", "未记录")} />
                <CaseDetailList items={iceItems} emptyText="未记录 ICE 信息。" />
              </CaseDetailPanel>

              <CaseDetailPanel title="病史线索">
                <CaseDetailList
                  items={hiddenFacts.map((fact, index) => {
                    const topic = getStringField(fact, "topic", `线索 ${index + 1}`);
                    const answer = getStringField(fact, "canonical_answer", "未记录");
                    return `${topic}：${answer}`;
                  })}
                  emptyText="暂无结构化病史线索。"
                />
              </CaseDetailPanel>

              <CaseDetailPanel title="查体结果">
                <CaseDetailList
                  items={examItems.map((item) => {
                    const name = getStringField(item, "exam_name_cn", getStringField(item, "exam_code", "查体项目"));
                    return `${name}：${getStringField(item, "result", "未记录结果")}`;
                  })}
                  emptyText="暂无查体项目。"
                />
              </CaseDetailPanel>

              <CaseDetailPanel title="辅助检查结果">
                <CaseDetailList
                  items={testItems.map((item) => {
                    const name = getStringField(item, "test_name_cn", getStringField(item, "test_code", "辅助检查"));
                    const category = getStringField(item, "category", "");
                    const result = getStringField(item, "result", "未记录结果");
                    return `${category ? `${category} · ` : ""}${name}：${result}`;
                  })}
                  emptyText="暂无辅助检查。"
                />
              </CaseDetailPanel>

              <CaseDetailPanel className="lg:col-span-2" title="诊断与推理">
                <div className="grid gap-3 lg:grid-cols-2">
                  <CaseDetailLine label="主要诊断" value={getStringField(diagnosis, "main_diagnosis", "未记录")} />
                  <CaseDetailLine label="下一步建议" value={getStringField(diagnosis, "suggested_next_steps", "未记录")} />
                </div>
                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  <CaseDetailList
                    title="鉴别诊断"
                    items={differentialDiagnoses.map((item) => `${getStringField(item, "disease_name", "未命名鉴别诊断")}：${getStringField(item, "key_distinction", "未记录区别")}`)}
                    emptyText="暂无鉴别诊断。"
                  />
                  <CaseDetailList
                    title="推理要点"
                    items={reasoningPoints.map((item) => getStringField(item, "statement", "未记录推理要点"))}
                    emptyText="暂无推理要点。"
                  />
                </div>
              </CaseDetailPanel>

              <CaseDetailPanel className="lg:col-span-2" title="教学设置">
                <div className="grid gap-4 lg:grid-cols-2">
                  <CaseDetailList title="学习目标" items={toTextList(teachingFocus?.learning_objectives)} emptyText="暂无学习目标。" />
                  <CaseDetailList title="训练路径" items={toTextList(teachingFocus?.recommended_training_path)} emptyText="暂无训练路径。" />
                </div>
              </CaseDetailPanel>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function CaseDetailPanel({ children, className, title }: Readonly<{ children: ReactNode; className?: string; title: string }>) {
  return (
    <section className={cn("rounded-3xl border border-[#E7E0D4] bg-[#FAF9F5] p-5", className)}>
      <h4 className="text-lg font-semibold">{title}</h4>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function CaseDetailLine({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="rounded-2xl border border-[#E7E0D4] bg-white p-4">
      <p className="text-xs text-[#8A7D6F]">{label}</p>
      <p className="mt-2 text-sm leading-6 text-[#141413]">{value}</p>
    </div>
  );
}

function CaseDetailList({ emptyText, items, title }: Readonly<{ emptyText: string; items: readonly string[]; title?: string }>) {
  return (
    <div>
      {title ? <h5 className="mb-2 text-sm font-semibold">{title}</h5> : null}
      <div className="grid gap-2">
        {items.map((item, index) => (
          <p className="rounded-2xl border border-[#E7E0D4] bg-white px-4 py-3 text-sm leading-6 text-[#141413]" key={`${item}-${index}`}>
            {item}
          </p>
        ))}
        {items.length === 0 ? <p className="rounded-2xl border border-dashed border-[#E7E0D4] bg-white px-4 py-3 text-sm text-[#6F6257]">{emptyText}</p> : null}
      </div>
    </div>
  );
}

function KnowledgeContentModal({
  document,
  isSaving,
  items,
  onClose,
  onSaveKnowledgeItem,
}: Readonly<{
  document: AdminRagDocument;
  isSaving: boolean;
  items: readonly AdminRagKnowledgeItem[];
  onClose: () => void;
  onSaveKnowledgeItem: (item: AdminRagKnowledgeItem) => Promise<AdminRagKnowledgeItem>;
}>) {
  const [selectedKnowledgeId, setSelectedKnowledgeId] = useState(items[0]?.knowledge_id ?? "");
  const selectedItem = items.find((item) => item.knowledge_id === selectedKnowledgeId) ?? items[0] ?? null;
  const [draftTitle, setDraftTitle] = useState(selectedItem?.title || selectedItem?.section_title || "");
  const [draftText, setDraftText] = useState(selectedItem?.text || "");
  const [localErrorText, setLocalErrorText] = useState("");

  useEffect(() => {
    setSelectedKnowledgeId(items[0]?.knowledge_id ?? "");
  }, [document.document_id]);

  useEffect(() => {
    setDraftTitle(selectedItem?.title || selectedItem?.section_title || "");
    setDraftText(selectedItem?.text || "");
    setLocalErrorText("");
  }, [selectedItem?.knowledge_id, selectedItem?.section_title, selectedItem?.text, selectedItem?.title]);

  async function handleSave() {
    if (!selectedItem) {
      return;
    }
    const nextTitle = draftTitle.trim();
    const nextText = draftText.trim();
    if (!nextTitle || !nextText) {
      setLocalErrorText("标题和正文不能为空。");
      return;
    }
    if (nextTitle.length > RAG_TITLE_MAX_CHARS || nextText.length > RAG_TEXT_MAX_CHARS) {
      setLocalErrorText(`标题不能超过 ${RAG_TITLE_MAX_CHARS} 个字符，正文不能超过 ${RAG_TEXT_MAX_CHARS} 个字符。`);
      return;
    }
    try {
      const savedItem = await onSaveKnowledgeItem({
        ...selectedItem,
        title: nextTitle,
        text: nextText,
      });
      setSelectedKnowledgeId(savedItem.knowledge_id);
      setLocalErrorText("");
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "保存失败");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4" role="dialog" aria-modal="true" aria-label="编辑知识库内容">
      <div className="grid max-h-[88vh] w-full max-w-6xl overflow-hidden rounded-3xl border border-[#E7E0D4] bg-white shadow-2xl">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-[#E7E0D4] px-6 py-5">
          <div>
            <p className="text-xs font-semibold text-[#AE5630]">编辑知识库内容</p>
            <h3 className="mt-1 text-xl font-semibold">{document.title || document.file_name || document.filename || document.document_id}</h3>
            <p className="mt-2 text-sm text-[#6F6257]">
              文档内容 · {document.scope === "case" ? "病例知识库" : "全局知识库"} · {document.case_title || "全部病例"} · {items.length} 个知识片段
            </p>
          </div>
          <Button onClick={onClose} variant="secondary">
            关闭
          </Button>
        </div>
        <div className="grid min-h-0 gap-0 overflow-hidden lg:grid-cols-[18rem_1fr]">
          <aside className="min-h-0 overflow-y-auto border-b border-[#E7E0D4] bg-[#FAF9F5] p-4 lg:border-b-0 lg:border-r">
            <h4 className="text-sm font-semibold">知识片段</h4>
            <div className="mt-3 grid gap-2">
              {items.map((item, index) => {
                const isActive = selectedItem?.knowledge_id === item.knowledge_id;
                return (
                  <button
                    className={cn(
                      "rounded-2xl border px-3 py-3 text-left text-sm transition",
                      isActive ? "border-[#141413] bg-[#141413] text-white" : "border-[#E7E0D4] bg-white text-[#6F6257] hover:border-[#AE5630] hover:text-[#141413]",
                    )}
                    key={item.knowledge_id}
                    onClick={() => setSelectedKnowledgeId(item.knowledge_id)}
                    type="button"
                  >
                    <span className="block font-semibold">{item.section_title || item.title || `片段 ${index + 1}`}</span>
                    <span className={cn("mt-1 block text-xs", isActive ? "text-white/70" : "text-[#8A7D6F]")}>{item.chunk_index != null ? `第 ${item.chunk_index + 1} 段` : "知识条目"}</span>
                  </button>
                );
              })}
              {items.length === 0 ? <EmptyText>该文档暂无可编辑片段。</EmptyText> : null}
            </div>
          </aside>
          <section className="min-h-0 overflow-y-auto p-5">
            {selectedItem ? (
              <div className="grid gap-4">
                <div className="grid gap-3 md:grid-cols-3">
                  <MiniStat label="可见性" value={getKnowledgeVisibilityLabel(selectedItem.visibility)} />
                  <MiniStat label="可用模块" value={joinText(toTokenList(selectedItem.allowed_agents), "未配置")} />
                  <MiniStat label="更新时间" value={formatDateTime(selectedItem.updated_at ?? "")} />
                </div>
                <label className="grid gap-2 text-sm font-semibold">
                  标题
                  <Input maxLength={RAG_TITLE_MAX_CHARS} value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} />
                </label>
                <label className="grid gap-2 text-sm font-semibold">
                  正文
                  <textarea
                    className="min-h-[18rem] resize-y rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] px-4 py-3 text-sm leading-6 outline-none transition focus:border-[#AE5630] focus:bg-white"
                    maxLength={RAG_TEXT_MAX_CHARS}
                    value={draftText}
                    onChange={(event) => setDraftText(event.target.value)}
                  />
                </label>
                {localErrorText ? <p className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{localErrorText}</p> : null}
                <div className="flex flex-wrap justify-end gap-2">
                  <Button onClick={onClose} variant="secondary">
                    取消
                  </Button>
                  <Button disabled={isSaving} onClick={() => void handleSave()}>
                    {isSaving ? <Loader2 className="animate-spin" /> : <FileText />}
                    保存修改
                  </Button>
                </div>
              </div>
            ) : (
              <EmptyText>请选择一个知识片段。</EmptyText>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function CaseCreationModal({
  cases,
  isSaving,
  onClose,
  onImport,
  onValidate,
  sources,
}: Readonly<{
  cases: readonly AdminCaseSummary[];
  isSaving: boolean;
  onClose: () => void;
  onImport: (payload: AdminCaseCreationPayload) => Promise<AdminCaseImportStatus>;
  onValidate: (payload: AdminCaseCreationPayload) => Promise<AdminCaseImportStatus>;
  sources: readonly AdminSourceSummary[];
}>) {
  const [draft, setDraft] = useState<CaseCreationDraft>(() => buildDefaultCaseCreationDraft(sources, cases));
  const [result, setResult] = useState<AdminCaseImportStatus | null>(null);
  const [localErrorText, setLocalErrorText] = useState("");

  useEffect(() => {
    setDraft((current) => ({
      ...current,
      caseId: generateSequentialCaseId(cases),
      sourceId: current.sourceId || sources[0]?.source_id || "",
    }));
  }, [cases, sources]);

  const draftErrors = useMemo(() => getCaseCreationDraftErrors(draft, cases), [cases, draft]);
  const canSubmit = draftErrors.length === 0 && !isSaving;

  function clearCaseCreationResult() {
    setResult(null);
    setLocalErrorText("");
  }

  function updateDraft(field: CaseCreationTextField, value: string) {
    setDraft((current) => ({ ...current, [field]: value }));
    clearCaseCreationResult();
  }

  function addTextRow(field: "historyFacts" | "reasoningPoints") {
    const maxItems = field === "historyFacts" ? CASE_CREATION_HISTORY_MAX_ITEMS : CASE_CREATION_REASONING_MAX_ITEMS;
    setDraft((current) => (
      current[field].length >= maxItems
        ? current
        : { ...current, [field]: [...current[field], createTextRow()] }
    ));
    clearCaseCreationResult();
  }

  function updateTextRow(field: "historyFacts" | "reasoningPoints", rowId: string, value: string) {
    setDraft((current) => ({
      ...current,
      [field]: current[field].map((row) => (row.id === rowId ? { ...row, value } : row)),
    }));
    clearCaseCreationResult();
  }

  function removeTextRow(field: "historyFacts" | "reasoningPoints", rowId: string) {
    setDraft((current) => ({
      ...current,
      [field]: current[field].filter((row) => row.id !== rowId),
    }));
    clearCaseCreationResult();
  }

  function addProcedureRow(field: "examItems" | "testItems") {
    setDraft((current) => (
      current[field].length >= CASE_CREATION_PROCEDURE_MAX_ITEMS
        ? current
        : { ...current, [field]: [...current[field], createProcedureRow()] }
    ));
    clearCaseCreationResult();
  }

  function updateProcedureRow(field: "examItems" | "testItems", rowId: string, patch: Partial<Omit<CaseCreationProcedureRow, "id">>) {
    setDraft((current) => ({
      ...current,
      [field]: current[field].map((row) => (row.id === rowId ? { ...row, ...patch } : row)),
    }));
    clearCaseCreationResult();
  }

  function removeProcedureRow(field: "examItems" | "testItems", rowId: string) {
    setDraft((current) => ({
      ...current,
      [field]: current[field].filter((row) => row.id !== rowId),
    }));
    clearCaseCreationResult();
  }

  function addDifferentialRow() {
    setDraft((current) => (
      current.differentialDiagnoses.length >= CASE_CREATION_DIFFERENTIAL_MAX_ITEMS
        ? current
        : { ...current, differentialDiagnoses: [...current.differentialDiagnoses, createDifferentialRow()] }
    ));
    clearCaseCreationResult();
  }

  function updateDifferentialRow(rowId: string, patch: Partial<Omit<CaseCreationDifferentialRow, "id">>) {
    setDraft((current) => ({
      ...current,
      differentialDiagnoses: current.differentialDiagnoses.map((row) => (row.id === rowId ? { ...row, ...patch } : row)),
    }));
    clearCaseCreationResult();
  }

  function removeDifferentialRow(rowId: string) {
    setDraft((current) => ({
      ...current,
      differentialDiagnoses: current.differentialDiagnoses.filter((row) => row.id !== rowId),
    }));
    clearCaseCreationResult();
  }

  function buildPayloadOrReport(): AdminCaseCreationPayload | null {
    const errors = getCaseCreationDraftErrors(draft, cases);
    if (errors.length > 0) {
      setLocalErrorText(errors.join("；"));
      return null;
    }
    try {
      const payload = buildCaseCreationPayload(draft);
      if (getJsonUtf8ByteLength(payload) > ADMIN_CASE_REQUEST_MAX_BYTES) {
        setLocalErrorText("病例与评分表内容不能超过 256 KiB。");
        return null;
      }
      return payload;
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "病例结构生成失败");
      return null;
    }
  }

  async function handleValidate() {
    const payload = buildPayloadOrReport();
    if (!payload) {
      return;
    }
    try {
      const nextResult = await onValidate(payload);
      setResult(nextResult);
      setLocalErrorText(nextResult.valid ? "" : joinText(nextResult.errors, "预检未通过"));
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "导入前预检失败");
    }
  }

  async function handleImport() {
    const payload = buildPayloadOrReport();
    if (!payload) {
      return;
    }
    try {
      const nextResult = await onImport(payload);
      setResult(nextResult);
      if (!nextResult.imported) {
        setLocalErrorText(joinText(nextResult.errors, "发布失败"));
      }
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "发布病例失败");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4" role="dialog" aria-modal="true" aria-label="病例工坊">
      <div className="grid h-[calc(100dvh-2rem)] max-h-[calc(100dvh-2rem)] w-full max-w-6xl grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-3xl border border-[#E7E0D4] bg-white shadow-2xl">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-[#E7E0D4] px-6 py-5">
          <div>
            <p className="text-xs font-semibold text-[#AE5630]">病例工坊</p>
            <h3 className="mt-1 text-2xl font-semibold">新建病例</h3>
            <p className="mt-2 text-sm leading-6 text-[#6F6257]">用中文字段录入教学病例；系统会生成结构化病例和评分 Rubric，并在发布前执行后端校验。</p>
          </div>
          <Button onClick={onClose} variant="secondary">
            关闭
          </Button>
        </div>
        <div className="min-h-0 overflow-y-auto p-6">
          <div className="grid gap-5">
            <Card className="shadow-none">
              <CardHeader>
                <CardTitle>基础信息</CardTitle>
                <CardDescription>这些内容会出现在病例选择页和训练工作台。</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-2">
                <FormField label="病例 ID">
                  <Input readOnly value={draft.caseId} />
                  <p className="text-xs text-[#8A7D6F]">按当前病例数量自动递增生成，发布时后端仍会校验是否冲突。</p>
                </FormField>
                <FormField label="病例标题">
                  <Input value={draft.caseTitle} onChange={(event) => updateDraft("caseTitle", event.target.value)} placeholder="例如 右下腹痛教学病例" />
                </FormField>
                <FormField label="课程模块">
                  <SelectInput value={draft.courseModule} onChange={(value) => updateDraft("courseModule", value)} options={courseModuleOptions} />
                </FormField>
                <FormField label="训练难度">
                  <SelectInput value={draft.difficulty} onChange={(value) => updateDraft("difficulty", value)} options={["初级", "中级", "高级"]} />
                </FormField>
                <FormField className="md:col-span-2" label="主诉">
                  <Input value={draft.chiefComplaint} onChange={(event) => updateDraft("chiefComplaint", event.target.value)} placeholder="例如 转移性右下腹痛 24 小时，伴恶心、低热" />
                </FormField>
              </CardContent>
            </Card>

            <Card className="shadow-none">
              <CardHeader>
                <CardTitle>标准化病人</CardTitle>
                <CardDescription>用于病人开局、身份设定和 ICE 相关训练。</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-4">
                <FormField label="年龄">
                  <Input value={draft.ageValue} onChange={(event) => updateDraft("ageValue", event.target.value)} inputMode="numeric" />
                </FormField>
                <FormField label="性别">
                  <SelectInput value={draft.gender} onChange={(value) => updateDraft("gender", value)} options={["男", "女"]} />
                </FormField>
                <FormField label="职业">
                  <Input value={draft.occupation} onChange={(event) => updateDraft("occupation", event.target.value)} />
                </FormField>
                <FormField label="接诊科室">
                  <Input value={draft.hospitalDepartment} onChange={(event) => updateDraft("hospitalDepartment", event.target.value)} />
                </FormField>
                <FormField className="md:col-span-4" label="现病史概要">
                  <TextAreaInput value={draft.presentIllnessSummary} onChange={(value) => updateDraft("presentIllnessSummary", value)} placeholder="概括患者如何起病、症状如何演变、当前主要表现。" />
                </FormField>
                <FormField label="患者想法">
                  <Input value={draft.patientIdea} onChange={(event) => updateDraft("patientIdea", event.target.value)} />
                </FormField>
                <FormField label="患者担忧">
                  <Input value={draft.patientConcern} onChange={(event) => updateDraft("patientConcern", event.target.value)} />
                </FormField>
                <FormField className="md:col-span-2" label="患者期望">
                  <Input value={draft.patientExpectation} onChange={(event) => updateDraft("patientExpectation", event.target.value)} />
                </FormField>
              </CardContent>
            </Card>

            <Card className="shadow-none">
              <CardHeader>
                <CardTitle>线索与检查</CardTitle>
                <CardDescription>每个单元对应一个可追踪事实、查体或检查结果；需要更多项目时点击加号新增。</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-5">
                <CaseCreationTextRowList
                  addLabel="添加病史线索"
                  description="例如起病时间、疼痛部位、症状演变、伴随症状或重要阴性病史。"
                  fieldLabel="病史线索"
                  maxItems={CASE_CREATION_HISTORY_MAX_ITEMS}
                  onAdd={() => addTextRow("historyFacts")}
                  onRemove={(rowId) => removeTextRow("historyFacts", rowId)}
                  onUpdate={(rowId, value) => updateTextRow("historyFacts", rowId, value)}
                  placeholder="例如 起病 24 小时"
                  rows={draft.historyFacts}
                />
                <CaseCreationProcedureRowList
                  addLabel="添加查体项目"
                  description="查体名称和结果会进入查体申请结果。"
                  maxItems={CASE_CREATION_PROCEDURE_MAX_ITEMS}
                  namePlaceholder="例如 右下腹压痛"
                  onAdd={() => addProcedureRow("examItems")}
                  onRemove={(rowId) => removeProcedureRow("examItems", rowId)}
                  onUpdate={(rowId, patch) => updateProcedureRow("examItems", rowId, patch)}
                  resultPlaceholder="例如 McBurney 点明显压痛"
                  rows={draft.examItems}
                  title="查体项目"
                />
                <CaseCreationProcedureRowList
                  addLabel="添加辅助检查"
                  description="检查名称和结果会进入辅助检查申请结果。"
                  maxItems={CASE_CREATION_PROCEDURE_MAX_ITEMS}
                  namePlaceholder="例如 血常规"
                  onAdd={() => addProcedureRow("testItems")}
                  onRemove={(rowId) => removeProcedureRow("testItems", rowId)}
                  onUpdate={(rowId, patch) => updateProcedureRow("testItems", rowId, patch)}
                  resultPlaceholder="例如 白细胞升高"
                  rows={draft.testItems}
                  title="辅助检查"
                />
              </CardContent>
            </Card>

            <Card className="shadow-none">
              <CardHeader>
                <CardTitle>评分 Rubric</CardTitle>
                <CardDescription>填写诊断和推理要点后，系统自动生成 100 分结构化评分表。</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-2">
                <FormField label="主要诊断">
                  <Input value={draft.mainDiagnosis} onChange={(event) => updateDraft("mainDiagnosis", event.target.value)} placeholder="例如 急性阑尾炎" />
                </FormField>
                <FormField label="来源">
                  <SelectInput value={draft.sourceId} onChange={(value) => updateDraft("sourceId", value)} options={sources.map((source) => source.source_id)} optionLabels={Object.fromEntries(sources.map((source) => [source.source_id, source.title || source.source_id]))} />
                </FormField>
                <div className="md:col-span-2">
                  <CaseCreationDifferentialRowList
                    addLabel="添加鉴别诊断"
                    maxItems={CASE_CREATION_DIFFERENTIAL_MAX_ITEMS}
                    onAdd={addDifferentialRow}
                    onRemove={removeDifferentialRow}
                    onUpdate={updateDifferentialRow}
                    rows={draft.differentialDiagnoses}
                  />
                </div>
                <div className="md:col-span-2">
                  <CaseCreationTextRowList
                    addLabel="添加推理要点"
                    description="例如病史如何支持主要诊断、查体和检查如何补强证据、需要排除哪些危险诊断。"
                    fieldLabel="推理要点"
                    maxItems={CASE_CREATION_REASONING_MAX_ITEMS}
                    onAdd={() => addTextRow("reasoningPoints")}
                    onRemove={(rowId) => removeTextRow("reasoningPoints", rowId)}
                    onUpdate={(rowId, value) => updateTextRow("reasoningPoints", rowId, value)}
                    placeholder="例如 病史演变支持当前主要诊断"
                    rows={draft.reasoningPoints}
                  />
                </div>
              </CardContent>
            </Card>

            {localErrorText ? <p className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{localErrorText}</p> : null}
            {result ? (
              <p className={cn("rounded-2xl border px-4 py-3 text-sm", result.valid || result.imported ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800")}>
                {getCaseImportStatusText(result)}
              </p>
            ) : null}
            {draftErrors.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {draftErrors.map((error) => (
                  <Badge key={error} variant="warning">
                    {error}
                  </Badge>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#E7E0D4] px-6 py-4">
          <p className="text-sm text-[#6F6257]">发布后会进入病例台账，后续可继续为该病例上传知识库文档。</p>
          <div className="flex flex-wrap gap-2">
            <Button onClick={onClose} variant="secondary">
              取消
            </Button>
            <Button disabled={!canSubmit} onClick={() => void handleValidate()} variant="secondary">
              {isSaving ? <Loader2 className="animate-spin" /> : <ClipboardCheck />}
              导入前预检
            </Button>
            <Button disabled={!canSubmit || result?.valid !== true} onClick={() => void handleImport()}>
              {isSaving ? <Loader2 className="animate-spin" /> : <PlusCircle />}
              发布病例
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function TrainingSection({
  data,
  isDetailBusy,
  onReadEvents,
  onReadReport,
  selectedSession,
  selectedEvents,
  selectedReport,
  onSelectSession,
}: Readonly<{
  data: DashboardData;
  isDetailBusy: boolean;
  onReadEvents: (sessionId: string) => void;
  onReadReport: (sessionId: string) => void;
  selectedSession: AdminSessionSummary | null;
  selectedEvents: readonly TrainingEventRecord[];
  selectedReport: AdminSessionReport | null;
  onSelectSession: (sessionId: string) => void;
}>) {
  const hasSelectedReport = selectedSession
    ? selectedSession.stage === "feedback" || data.reports.some((report) => report.session_id === selectedSession.session_id)
    : false;
  const humanisticReportStats = selectedReport ? getHumanisticReportStats(selectedReport) : null;

  return (
    <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <Card>
        <CardHeader>
          <CardTitle>训练 Session</CardTitle>
          <CardDescription>表格化展示训练证据，点击一行查看详情。</CardDescription>
        </CardHeader>
        <CardContent>
          <SessionTable onSelectSession={onSelectSession} selectedSessionId={selectedSession?.session_id ?? ""} sessions={data.sessions} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Session 详情</CardTitle>
          <CardDescription>选择左侧 Session 后读取报告、日志和 Skill 应用证据。</CardDescription>
        </CardHeader>
        <CardContent>
          {selectedSession ? (
            <div className="grid gap-4">
              <div className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
                <p className="text-xs font-semibold text-[#AE5630]">{selectedSession.stage_label ?? selectedSession.stage}</p>
                <h3 className="mt-1 text-xl font-semibold">{selectedSession.case_title || selectedSession.case_id}</h3>
                <p className="mt-2 text-sm text-[#6F6257]">学员：{selectedSession.student_id}</p>
                <p className="mt-1 text-sm text-[#6F6257]">更新：{formatDateTime(selectedSession.updated_at)}</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button disabled={isDetailBusy || !hasSelectedReport} onClick={() => onReadReport(selectedSession.session_id)} size="sm">
                    {isDetailBusy ? <Loader2 className="animate-spin" /> : <FileText />}
                    {hasSelectedReport ? "读取报告" : "暂无报告"}
                  </Button>
                  <Button disabled={isDetailBusy} onClick={() => onReadEvents(selectedSession.session_id)} size="sm" variant="secondary">
                    {isDetailBusy ? <Loader2 className="animate-spin" /> : <Activity />}
                    读取日志
                  </Button>
                </div>
                {!hasSelectedReport ? <p className="mt-3 rounded-xl border border-[#E7E0D4] bg-white px-3 py-2 text-xs text-[#6F6257]">该 Session 还没有生成评分报告，通常表示学生尚未提交诊断。</p> : null}
              </div>
              {selectedReport ? (
                <div className="grid gap-3 rounded-2xl border border-[#E7E0D4] bg-white p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold text-[#AE5630]">评分报告</p>
                      <h4 className="mt-1 text-lg font-semibold">{selectedReport.case_title || selectedReport.case_id}</h4>
                    </div>
                    <Badge variant="success">{selectedReport.total_score ?? 0} 分</Badge>
                  </div>
                  <div className="grid gap-3 md:grid-cols-3">
                    <MiniStat label="未覆盖训练点" value={formatCount(selectedReport.missed_item_labels?.length ?? selectedReport.missed_items?.length ?? 0)} />
                    <MiniStat label="评分来源" value={formatCount(selectedReport.source_reference_items?.length ?? 0)} />
                    <MiniStat label="解释来源" value={formatCount(selectedReport.explanation_source_items?.length ?? 0)} />
                  </div>
                  {humanisticReportStats ? (
                    <div className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-3">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold">人文沟通统计</p>
                          <p className="mt-1 text-xs leading-5 text-[#6F6257]">叙事、沟通、伦理和关系建立的缺口与错失机会。</p>
                        </div>
                        <Badge variant="muted">{humanisticReportStats.scoreLabel}</Badge>
                      </div>
                      <div className="mt-3 grid gap-2 md:grid-cols-2">
                        <MiniStat label="人文沟通 gap" value={formatCount(humanisticReportStats.gaps.length)} />
                        <MiniStat label="错失机会" value={formatCount(selectedReport.missed_opportunities?.length ?? 0)} />
                      </div>
                      <CompactList items={humanisticReportStats.gaps.map((gap) => gap.label || gap.gap_type || "未命名缺口").slice(0, 4)} title="高频人文沟通缺口" />
                    </div>
                  ) : null}
                  <CompactList items={(selectedReport.missed_item_labels ?? selectedReport.missed_items ?? []).slice(0, 5)} title="主要未覆盖项" />
                </div>
              ) : null}
              {selectedEvents.length > 0 ? (
                <div className="rounded-2xl border border-[#E7E0D4] bg-white p-4">
                  <h4 className="text-sm font-semibold">最近日志事件</h4>
                  <div className="mt-3 grid gap-2">
                    {selectedEvents.slice(0, 8).map((event, index) => (
                      <div className="flex items-center justify-between gap-3 rounded-xl bg-[#FAF9F5] px-3 py-2 text-sm" key={`${event.created_at ?? ""}-${event.event_type}-${index}`}>
                        <span className="font-medium">{getEventTypeLabel(event.event_type)}</span>
                        <span className="text-xs text-[#8A7D6F]">{formatDateTime(event.created_at ?? "")}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              <div className="grid gap-2">
                <h4 className="text-sm font-semibold">Skill 跳过原因</h4>
                {(selectedSession.active_skill_context?.skipped_reasons ?? []).slice(0, 4).map((reason) => (
                  <div className="rounded-xl border border-[#E7E0D4] bg-white p-3 text-sm" key={`${reason.skill_id}-${reason.reason}`}>
                    <p className="font-medium">{reason.reason_label || reason.reason}</p>
                    <p className="mt-1 text-xs leading-5 text-[#6F6257]">{reason.reason_description || "暂无说明"}</p>
                  </div>
                ))}
                {(selectedSession.active_skill_context?.skipped_reasons ?? []).length === 0 ? <EmptyText>本轮暂无 Skill 跳过记录。</EmptyText> : null}
              </div>
            </div>
          ) : (
            <EmptyText>暂无可查看的训练 Session。</EmptyText>
          )}
        </CardContent>
      </Card>
      <ProcedureAuditList audits={data.procedureAudits} className="xl:col-span-2" summary={data.procedureAuditSummary} />
    </div>
  );
}

function ProcedureAuditList({
  audits,
  className,
  summary,
}: Readonly<{
  audits: readonly ProcedureSimulationAuditItem[];
  className?: string;
  summary: ProcedureSimulationAuditSummary | null;
}>) {
  return (
    <Card className={className}>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>历史模拟审计</CardTitle>
          <CardDescription>只读兼容历史报告中的模拟记录；当前活动训练不再新增。</CardDescription>
        </div>
        <Badge variant="muted">{formatCount(summary?.total ?? audits.length)} 条</Badge>
      </CardHeader>
      <CardContent>
        {audits.length > 0 ? (
          <div className="grid gap-3 md:grid-cols-2">
            {audits.slice(0, 8).map((audit, index) => (
              <article className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4" key={`${audit.session_id ?? ""}-${audit.procedure_id ?? ""}-${index}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h4 className="truncate text-sm font-semibold">{audit.label || audit.code || "未命名项目"}</h4>
                    <p className="mt-1 text-xs text-[#6F6257]">{audit.case_title || audit.case_id || "未绑定病例"}</p>
                  </div>
                  <Badge variant={audit.approval_status === "approved" || audit.approval_decision === "approved" ? "success" : "warning"}>
                    {getProcedureAuditStatusLabel(audit)}
                  </Badge>
                </div>
                <p className="mt-3 line-clamp-2 text-sm leading-6 text-[#141413]">{audit.result || "未记录模拟结果。"}</p>
                <p className="mt-2 line-clamp-2 text-xs leading-5 text-[#6F6257]">{audit.approval_rationale || audit.safety_boundary || "暂无审核说明。"}</p>
              </article>
            ))}
          </div>
        ) : (
          <EmptyText>暂无历史模拟审计记录。</EmptyText>
        )}
      </CardContent>
    </Card>
  );
}

function InsightsSection({ data }: Readonly<{ data: DashboardData }>) {
  const missedItems = toInsightDisplayItems(data.insights?.frequent_missed_items, "未覆盖训练点");
  const turnPatterns = toInsightDisplayItems(data.insights?.frequent_turn_patterns, "训练模式");
  const humanisticInsight = data.insights?.humanistic_communication;
  const learningAnalytics = data.learningAnalytics;

  return (
    <div className="grid gap-4">
      <SectionIntro eyebrow="教学洞察" title="错误模式与训练重点" description="聚合训练报告中的高频问题，供 Skill 生成和教师复盘参考。" />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard icon={<Stethoscope />} label="洞察 Session" value={formatCount(data.insights?.session_count ?? 0)} helper="进入统计的训练" />
        <MetricCard icon={<FileText />} label="洞察报告" value={formatCount(data.insights?.report_count ?? 0)} helper="进入统计的报告" />
        <MetricCard icon={<Brain />} label="错误模式" value={formatCount(data.insights?.frequent_turn_patterns?.length ?? 0)} helper="训练模式级聚合" />
        <MetricCard
          icon={<GraduationCap />}
          label="人文完成度"
          value={formatPercentage(humanisticInsight?.average_percentage)}
          helper={`趋势 ${formatPercentageTrend(humanisticInsight?.percentage_trend.delta ?? 0)}`}
        />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>当前训练问题</CardTitle>
          <CardDescription>按报告聚合的高频未覆盖项和按对话过程聚合的训练模式。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-2">
          <InsightList items={missedItems} title="近期漏项" />
          <InsightList items={turnPatterns} title="训练模式" />
        </CardContent>
      </Card>
      <HumanisticInsightsPanel insight={humanisticInsight} />
      <LearningAnalyticsPanel analytics={learningAnalytics} />
      <TeachingFocusList patterns={data.teachingFocusPatterns} />
    </div>
  );
}

function LearningAnalyticsPanel({ analytics }: Readonly<{ analytics: AdminLearningAnalytics | null }>) {
  const [view, setView] = useState<"cohort" | "case" | "student">("cohort");
  const summary = analytics?.summary;
  const cohort = analytics?.cohort_analytics ?? null;
  const caseItems = analytics?.case_analytics ?? [];
  const studentItems = analytics?.student_analytics ?? [];

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>全用户、病例与学生学情分析</CardTitle>
          <CardDescription>把报告、训练缺口、错失机会和患者情绪回应汇总到全用户、病例级与学生级，供教师安排下一轮训练。</CardDescription>
        </div>
        <Badge variant="muted">{formatCount(summary?.report_count ?? 0)} 份报告</Badge>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-3 md:grid-cols-4">
          <MiniStat label="统计 Session" value={formatCount(summary?.session_count ?? 0)} />
          <MiniStat label="覆盖病例" value={formatCount(summary?.case_count ?? 0)} />
          <MiniStat label="覆盖学生" value={formatCount(summary?.student_count ?? 0)} />
          <MiniStat label="分析报告" value={formatCount(summary?.report_count ?? 0)} />
        </div>
        <div className="inline-flex w-fit rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-1">
          <button
            className={cn(
              "rounded-xl px-4 py-2 text-sm font-semibold transition",
              view === "cohort" ? "bg-white text-[#141413] shadow-sm" : "text-[#6F6257] hover:text-[#141413]",
            )}
            onClick={() => setView("cohort")}
            type="button"
          >
            全用户总览
          </button>
          <button
            className={cn(
              "rounded-xl px-4 py-2 text-sm font-semibold transition",
              view === "case" ? "bg-white text-[#141413] shadow-sm" : "text-[#6F6257] hover:text-[#141413]",
            )}
            onClick={() => setView("case")}
            type="button"
          >
            病例视角
          </button>
          <button
            className={cn(
              "rounded-xl px-4 py-2 text-sm font-semibold transition",
              view === "student" ? "bg-white text-[#141413] shadow-sm" : "text-[#6F6257] hover:text-[#141413]",
            )}
            onClick={() => setView("student")}
            type="button"
          >
            学生视角
          </button>
        </div>
        {view === "cohort" ? <CohortLearningAnalyticsOverview item={cohort} /> : null}
        {view === "case" ? <CaseLearningAnalyticsList items={caseItems} /> : null}
        {view === "student" ? <StudentLearningAnalyticsList items={studentItems} /> : null}
      </CardContent>
    </Card>
  );
}

function CohortLearningAnalyticsOverview({ item }: Readonly<{ item: AdminCohortLearningAnalytics | null }>) {
  if (!item) {
    return <EmptyText>暂无全用户学情分析。</EmptyText>;
  }

  const topGap = item.frequent_humanistic_gaps[0] ?? item.frequent_missed_items[0];
  const missedOpportunity = item.frequent_missed_opportunities[0];

  return (
    <article className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">{item.scope_label || "全用户"}</h3>
          <p className="mt-1 text-xs text-[#6F6257]">
            {formatCount(item.student_count)} 名用户 · {formatCount(item.case_count)} 个病例 · {formatCount(item.report_count)} 份报告
          </p>
        </div>
        <Badge variant="warning">总体均分 {formatInsightNumber(item.average_total_score)}</Badge>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <LearningCompactMetric label="临床完成度" value={formatNormalizedScoreMetric(item.clinical_score)} />
        <LearningCompactMetric label="人文完成度" value={formatNormalizedScoreMetric(item.humanistic_score)} />
        <LearningCompactMetric label="情绪回应" value={formatAffectSignalText(item.affect_signals)} />
        <LearningCompactMetric label="Top 缺口" value={getLearningGapTitle(topGap)} />
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <LearningTextBlock title="全用户高频临床漏项" value={getLearningGapDetail(item.frequent_missed_items[0])} />
        <LearningTextBlock title="全用户人文沟通 gap" value={getLearningGapDetail(topGap)} />
        <LearningTextBlock title="全用户错失机会" value={getLearningGapDetail(missedOpportunity)} />
      </div>
      <CompactList items={item.teaching_actions.slice(0, 3)} title="全用户下一轮教学动作" />
      <TrainingDrillList items={item.training_drills ?? []} title="可执行训练任务" />
    </article>
  );
}

function CaseLearningAnalyticsList({ items }: Readonly<{ items: readonly AdminCaseLearningAnalytics[] }>) {
  if (items.length === 0) {
    return <EmptyText>暂无病例级学情分析。</EmptyText>;
  }

  return (
    <div className="grid gap-3">
      {items.slice(0, 6).map((item) => {
        const topGap = item.frequent_humanistic_gaps[0] ?? item.frequent_missed_items[0];
        const missedOpportunity = item.frequent_missed_opportunities[0];
        return (
          <article className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4" key={item.case_id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold">{item.case_title || item.case_id}</h3>
                <p className="mt-1 text-xs text-[#6F6257]">
                  {formatCount(item.session_count)} 次训练 · {formatCount(item.report_count)} 份报告
                </p>
              </div>
              <Badge variant="warning">均分 {formatInsightNumber(item.average_total_score)}</Badge>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-4">
              <LearningCompactMetric label="临床完成度" value={formatNormalizedScoreMetric(item.clinical_score)} />
              <LearningCompactMetric label="人文完成度" value={formatNormalizedScoreMetric(item.humanistic_score)} />
              <LearningCompactMetric label="情绪回应" value={formatAffectSignalText(item.affect_signals)} />
              <LearningCompactMetric label="Top 缺口" value={getLearningGapTitle(topGap)} />
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <LearningTextBlock title="高频人文沟通缺口" value={getLearningGapDetail(topGap)} />
              <LearningTextBlock title="错失机会" value={getLearningGapDetail(missedOpportunity)} />
            </div>
            <CompactList items={item.teaching_actions.slice(0, 3)} title="教师下一步动作" />
            <TrainingDrillList items={item.training_drills ?? []} title="可执行训练任务" />
          </article>
        );
      })}
    </div>
  );
}

function StudentLearningAnalyticsList({ items }: Readonly<{ items: readonly AdminStudentLearningAnalytics[] }>) {
  if (items.length === 0) {
    return <EmptyText>暂无学生级学情分析。</EmptyText>;
  }

  return (
    <div className="grid gap-3">
      {items.slice(0, 8).map((item) => {
        const currentGap = item.current_humanistic_gaps[0] ?? item.persistent_gaps[0];
        return (
          <article className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4" key={item.student_id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold">{item.student_id}</h3>
                <p className="mt-1 text-xs text-[#6F6257]">{joinText(item.case_titles, "未绑定病例")}</p>
              </div>
              <Badge variant="warning">均分 {formatInsightNumber(item.average_total_score)}</Badge>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-4">
              <LearningCompactMetric label="训练报告" value={`${formatCount(item.report_count)}/${formatCount(item.session_count)}`} />
              <LearningCompactMetric label="临床完成度" value={formatNormalizedScoreMetric(item.clinical_score)} />
              <LearningCompactMetric label="人文完成度" value={formatNormalizedScoreMetric(item.humanistic_score)} />
              <LearningCompactMetric label="情绪回应" value={formatAffectSignalText(item.affect_response)} />
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <LearningTextBlock title="当前人文沟通 gap" value={getLearningGapDetail(currentGap)} />
              <LearningTextBlock title="长期反复 gap" value={getLearningGapDetail(item.persistent_gaps[0])} />
            </div>
            <CompactList items={item.recommended_next_actions.slice(0, 3)} title="下一轮训练动作" />
            <TrainingDrillList items={item.training_drills ?? []} title="可执行训练任务" />
          </article>
        );
      })}
    </div>
  );
}

function LearningCompactMetric({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="rounded-2xl border border-[#F0E8DC] bg-white p-3">
      <p className="text-xs text-[#8A7D6F]">{label}</p>
      <p className="mt-2 line-clamp-2 text-sm font-semibold leading-5">{value}</p>
    </div>
  );
}

function LearningTextBlock({ title, value }: Readonly<{ title: string; value: string }>) {
  return (
    <div className="rounded-2xl border border-[#F0E8DC] bg-white p-3">
      <h4 className="text-sm font-semibold">{title}</h4>
      <p className="mt-2 line-clamp-3 text-sm leading-6 text-[#6F6257]">{value}</p>
    </div>
  );
}

function TrainingDrillList({ items, title }: Readonly<{ items: readonly AdminLearningTrainingDrill[]; title: string }>) {
  return (
    <div className="mt-4 rounded-2xl border border-[#E7E0D4] bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold">{title}</h4>
        <Badge variant="muted">{formatCount(items.length)} 项</Badge>
      </div>
      {items.length > 0 ? (
        <div className="mt-3 grid gap-3">
          {items.slice(0, 3).map((item) => (
            <div className="rounded-2xl border border-[#F0E8DC] bg-[#FAF9F5] p-3" key={item.drill_id}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold">{item.title || item.target_label}</p>
                  <p className="mt-1 text-xs text-[#8A7D6F]">
                    {getTrainingDrillSourceLabel(item.source)} · 来源 {formatCount(item.source_count)} 次 · 优先级 {formatCount(item.priority)}
                  </p>
                </div>
                <Badge variant="warning">{item.trigger_stage || "相关阶段"}</Badge>
              </div>
              <div className="mt-3 grid gap-2 text-xs leading-5 text-[#6F6257] md:grid-cols-3">
                <p>
                  <span className="font-semibold text-[#141413]">触发：</span>
                  {item.trigger_signal || "再次出现同类训练信号"}
                </p>
                <p>
                  <span className="font-semibold text-[#141413]">学生动作：</span>
                  {item.student_action || "补齐当前训练动作"}
                </p>
                <p>
                  <span className="font-semibold text-[#141413]">成功信号：</span>
                  {item.success_signal || "学生能在正确阶段完成动作"}
                </p>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-sm text-[#6F6257]">暂无稳定训练任务。</p>
      )}
    </div>
  );
}

function HumanisticInsightsPanel({ insight }: Readonly<{ insight?: HumanisticCommunicationInsight }>) {
  const dimensionItems = insight?.dimension_averages ?? [];
  const gapItems = insight?.frequent_gaps ?? [];
  const missedOpportunityItems = insight?.frequent_missed_opportunities ?? [];
  const candidateStatusItems = insight?.anchor_candidates_by_status ?? [];

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>人文沟通能力</CardTitle>
          <CardDescription>聚合叙事医学、沟通技巧、医学伦理和关系建立的班级训练信号。</CardDescription>
        </div>
        <Badge variant="muted">{formatCount(insight?.report_count ?? 0)} 份报告</Badge>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-3 md:grid-cols-3">
          <MiniStat label="人文沟通完成度" value={formatPercentage(insight?.average_percentage)} />
          <MiniStat label="近期变化" value={formatPercentageTrend(insight?.percentage_trend.delta ?? 0)} />
          <MiniStat label="锚点候选" value={formatCount(insight?.anchor_candidate_count ?? 0)} />
        </div>
        <div className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-2xl border border-[#E7E0D4] bg-white p-4">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-base font-semibold">维度均分</h3>
              <Badge variant="muted">{formatCount(dimensionItems.length)} 维</Badge>
            </div>
            {dimensionItems.length > 0 ? (
              <div className="mt-4 grid gap-3">
                {dimensionItems.map((item) => (
                  <div className="rounded-2xl border border-[#F0E8DC] bg-[#FAF9F5] p-3" key={item.dimension_id}>
                    <div className="flex items-center justify-between gap-3 text-sm">
                      <span className="font-medium">{item.dimension_label}</span>
                      <span className="text-[#AE5630]">
                        {formatPercentage(item.average_percentage)} · {formatInsightNumber(item.average_score)}/{formatInsightNumber(item.average_max_score)}
                      </span>
                    </div>
                    <div className="mt-2 h-2 rounded-full bg-[#EFE7DA]">
                      <div className="h-2 rounded-full bg-[#AE5630]" style={{ width: `${Math.min(100, Math.max(0, item.average_percentage ?? 0))}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyText>暂无人文沟通维度统计。</EmptyText>
            )}
          </div>
          <div className="grid gap-4">
            <HumanisticInsightList
              items={gapItems.map((item) => ({
                count: item.count,
                meta: `累计缺口 ${formatCount(item.missing_score_total)} 分`,
                title: item.label || item.gap_type,
              }))}
              title="常见人文沟通缺口"
            />
            <HumanisticInsightList
              items={missedOpportunityItems.map((item) => ({
                count: item.count,
                meta: item.expected_response,
                title: getHumanisticGapLabel(item.gap_type),
              }))}
              title="反复错失机会"
            />
          </div>
        </div>
        <CompactList
          items={candidateStatusItems.map((item) => `${getAnchorCandidateStatusLabel(item.status)} ${formatCount(item.count)}`)}
          title="锚点候选沉淀"
        />
      </CardContent>
    </Card>
  );
}

function HumanisticInsightList({ items, title }: Readonly<{ items: readonly Pick<InsightDisplayItem, "count" | "meta" | "title">[]; title: string }>) {
  return (
    <div className="rounded-2xl border border-[#E7E0D4] bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-base font-semibold">{title}</h3>
        <Badge variant="muted">{formatCount(items.length)} 项</Badge>
      </div>
      {items.length > 0 ? (
        <div className="mt-4 grid gap-3">
          {items.slice(0, 5).map((item, index) => (
            <article className="rounded-2xl border border-[#F0E8DC] bg-[#FAF9F5] p-4" key={`${item.title}-${index}`}>
              <div className="flex items-start justify-between gap-3">
                <h4 className="text-sm font-semibold leading-6">{item.title}</h4>
                <Badge variant="warning">{formatCount(item.count)} 次</Badge>
              </div>
              {item.meta ? <p className="mt-2 text-xs leading-5 text-[#6F6257]">{item.meta}</p> : null}
            </article>
          ))}
        </div>
      ) : (
        <EmptyText>暂无聚合记录。</EmptyText>
      )}
    </div>
  );
}

function TeachingFocusList({ patterns }: Readonly<{ patterns: readonly AdminTeachingFocusPattern[] }>) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>动态教学重点</CardTitle>
          <CardDescription>由病例结构、Rubric 和训练报告聚合生成，供教师复盘和后续 Skill 编排参考。</CardDescription>
        </div>
        <Badge variant="muted">{formatCount(patterns.length)} 项</Badge>
      </CardHeader>
      <CardContent>
        {patterns.length > 0 ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {patterns.slice(0, 8).map((pattern) => (
              <article className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4" key={pattern.focus_id}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold leading-6">{pattern.title || pattern.pattern || "未命名教学重点"}</h3>
                    <p className="mt-1 text-xs text-[#6F6257]">{joinText(pattern.case_titles, "未绑定病例")}</p>
                  </div>
                  <Badge variant="warning">{formatCount(pattern.support_count ?? pattern.source_report_count ?? 0)} 次</Badge>
                </div>
                <p className="mt-3 line-clamp-2 text-sm leading-6 text-[#141413]">{pattern.description || pattern.training_suggestion || "暂无说明。"}</p>
                <p className="mt-2 text-xs text-[#8A7D6F]">{pattern.severity_label || pattern.visibility_level_label || "教学观察"}</p>
              </article>
            ))}
          </div>
        ) : (
          <EmptyText>暂无动态教学重点。</EmptyText>
        )}
      </CardContent>
    </Card>
  );
}

function InsightList({ items, title }: Readonly<{ items: readonly InsightDisplayItem[]; title: string }>) {
  return (
    <div className="rounded-2xl border border-[#E7E0D4] bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-base font-semibold">{title}</h3>
        <Badge variant="muted">{formatCount(items.length)} 项</Badge>
      </div>
      {items.length > 0 ? (
        <div className="mt-4 grid gap-3">
          {items.slice(0, 8).map((item, index) => (
            <article className="rounded-2xl border border-[#F0E8DC] bg-[#FAF9F5] p-4" key={`${item.title}-${index}`}>
              <div className="flex items-start justify-between gap-3">
                <h4 className="text-sm font-semibold leading-6">{item.title}</h4>
                <Badge variant="warning">{formatCount(item.count)} 次</Badge>
              </div>
              {item.description ? <p className="mt-2 text-sm leading-6 text-[#6F6257]">{item.description}</p> : null}
              {item.meta ? <p className="mt-2 text-xs text-[#8A7D6F]">{item.meta}</p> : null}
            </article>
          ))}
        </div>
      ) : (
        <EmptyText>暂无可展示的聚合项。</EmptyText>
      )}
    </div>
  );
}

function SkillSection({
  data,
  isMutating,
  isSkillBusy,
  onGenerateSkillCandidates,
  onReadCandidate,
  onReviewCandidate,
  onToggleAutoApproval,
  selectedCandidate,
  selectedCandidateEvents,
}: Readonly<{
  data: DashboardData;
  isMutating: boolean;
  isSkillBusy: boolean;
  onGenerateSkillCandidates: () => void;
  onReadCandidate: (candidateId: string) => void;
  onReviewCandidate: (candidateId: string, action: "approve" | "reject") => void;
  onToggleAutoApproval: () => void;
  selectedCandidate: TrainingSkillCandidateDetail | null;
  selectedCandidateEvents: readonly TrainingEventRecord[];
}>) {
  const autoApplyEnabled = data.autoApprovalSettings?.auto_apply_enabled ?? false;
  return (
    <div className="grid gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <SectionIntro eyebrow="Skill 进化" title="候选、审核和效果统计" description="查看候选 Skill、审核状态和应用效果。" />
        <div className="flex flex-wrap gap-2">
          <Button disabled={isSkillBusy} onClick={onToggleAutoApproval} variant={autoApplyEnabled ? "outline" : "secondary"}>
            {autoApplyEnabled ? "关闭自动应用" : "开启自动应用"}
          </Button>
          <Button disabled={isMutating} onClick={onGenerateSkillCandidates}>
            {isMutating ? <Loader2 className="animate-spin" /> : <Sparkles />}
            生成候选 Skill
          </Button>
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard icon={<Sparkles />} label="候选 Skill" value={formatCount(data.candidatePagination?.total ?? data.candidates.length)} helper="来自训练日志" />
        <MetricCard icon={<GraduationCap />} label="效果状态" value={data.skillEffects?.label || getSkillEffectStatusLabel(data.skillEffects?.status)} helper="样本不足不伪造提升" />
        <MetricCard icon={<Brain />} label="支持样本要求" value={formatCount(data.skillEffects?.min_sessions_per_group ?? 0)} helper="每组最低样本数" />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>候选 Skill</CardTitle>
          <CardDescription>只显示审核判断需要的字段：标题、状态、来源报告、支持次数和回归结果。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-[#8A7D6F]">
                <tr className="border-b border-[#E7E0D4]">
                  <th className="py-3 pr-4">候选</th>
                  <th className="py-3 pr-4">病例</th>
                  <th className="py-3 pr-4">训练点</th>
                  <th className="py-3 pr-4">支持</th>
                  <th className="py-3 pr-4">状态</th>
                  <th className="py-3 pr-4">操作</th>
                </tr>
              </thead>
              <tbody>
                {data.candidates.map((candidate) => (
                  <tr className="border-b border-[#F0E8DC]" key={candidate.candidate_id}>
                    <td className="py-3 pr-4">
                      <p className="font-semibold">{candidate.title}</p>
                      <p className="mt-1 text-xs text-[#6F6257]">{candidate.skill_type_label || "未分类 Skill"}</p>
                    </td>
                    <td className="py-3 pr-4 text-[#6F6257]">{candidate.case_titles?.join("、") || "未绑定"}</td>
                    <td className="py-3 pr-4 text-[#6F6257]">{candidate.trigger_item_labels?.slice(0, 3).join("、") || "未记录"}</td>
                    <td className="py-3 pr-4 text-[#6F6257]">{candidate.support_count} 次 / {candidate.source_report_count} 报告</td>
                    <td className="py-3 pr-4">
                      <Badge variant={candidate.regression_passed ? "success" : "warning"}>{getCandidateStatusLabel(candidate.status)}</Badge>
                    </td>
                    <td className="py-3 pr-4">
                      <Button disabled={isSkillBusy} onClick={() => onReadCandidate(candidate.candidate_id)} size="sm" variant="secondary">
                        查看详情
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.candidates.length === 0 ? <EmptyText>暂无候选 Skill。</EmptyText> : null}
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>候选详情与审核</CardTitle>
            <CardDescription>选中候选后查看教学策略、审批 Agent 结论和审计事件。</CardDescription>
          </div>
          <Badge variant={autoApplyEnabled ? "success" : "muted"}>{autoApplyEnabled ? "自动应用开启" : "人工审核"}</Badge>
        </CardHeader>
        <CardContent>
          {selectedCandidate ? (
            <div className="grid gap-4">
              <div className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold text-[#AE5630]">{getCandidateStatusLabel(selectedCandidate.status)}</p>
                    <h3 className="mt-1 text-xl font-semibold">{selectedCandidate.title}</h3>
                    <p className="mt-2 text-sm leading-6 text-[#6F6257]">{selectedCandidate.description || "暂无描述。"}</p>
                  </div>
                  <Badge variant={selectedCandidate.regression_passed ? "success" : "warning"}>{selectedCandidate.regression_passed ? "回归通过" : "回归未通过"}</Badge>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button disabled={isSkillBusy || !canReviewCandidate(selectedCandidate)} onClick={() => onReviewCandidate(selectedCandidate.candidate_id, "approve")} size="sm">
                    批准并启用
                  </Button>
                  <Button disabled={isSkillBusy || !canReviewCandidate(selectedCandidate)} onClick={() => onReviewCandidate(selectedCandidate.candidate_id, "reject")} size="sm" variant="destructive">
                    拒绝候选
                  </Button>
                </div>
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                <InfoBlock title="适用范围" value={(selectedCandidate.case_titles ?? []).join("、") || "未绑定病例"} />
                <InfoBlock title="训练点" value={(selectedCandidate.trigger_item_labels ?? []).slice(0, 8).join("、") || "未记录"} />
                <InfoBlock className="lg:col-span-2" title="完整 Skill 内容" value={getSkillContentText(selectedCandidate)} />
                <InfoBlock className="lg:col-span-2" title="教学策略" value={getSkillStrategyText(selectedCandidate)} />
                <InfoBlock title="适用时机" value={joinText(toTextList(selectedCandidate.applies_when).length > 0 ? selectedCandidate.applies_when : selectedCandidate.stage_scope_labels, "由后端按病例、阶段和当前缺口匹配。")} />
                <InfoBlock title="成功指标" value={joinText(toTextList(selectedCandidate.success_metrics), "样本不足时只记录应用痕迹，不伪造提升。")} />
                <InfoBlock className="lg:col-span-2" title="来源报告" value={getCandidateSourceText(selectedCandidate)} />
                <InfoBlock className="lg:col-span-2" title="审批 Agent" value={getApprovalReviewText(selectedCandidate.approval_agent_review)} />
              </div>
              <CompactList items={(selectedCandidate.teaching_action_plan ?? []).map((action) => action.message_template || action.action_type_label || action.action_type || "教学动作").slice(0, 5)} title="Coach 注入动作" />
              <div className="rounded-2xl border border-[#E7E0D4] bg-white p-4">
                <h4 className="text-sm font-semibold">审批审计事件</h4>
                {selectedCandidateEvents.length > 0 ? (
                  <div className="mt-3 grid gap-2">
                    {selectedCandidateEvents.slice(0, 6).map((event, index) => (
                      <div className="flex items-center justify-between gap-3 rounded-xl bg-[#FAF9F5] px-3 py-2 text-sm" key={`${event.created_at ?? ""}-${event.event_type}-${index}`}>
                        <span className="font-medium">{getEventTypeLabel(event.event_type)}</span>
                        <span className="text-xs text-[#8A7D6F]">{formatDateTime(event.created_at ?? "")}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyText>暂无审批多轮记录。</EmptyText>
                )}
              </div>
            </div>
          ) : (
            <EmptyText>点击候选 Skill 的“查看详情”后，在这里审核或查看审批 Agent 记录。</EmptyText>
          )}
        </CardContent>
      </Card>
      <AuditEventList events={data.auditEvents} />
    </div>
  );
}

function AuditEventList({ events }: Readonly<{ events: readonly TrainingEventRecord[] }>) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>全局审核审计</CardTitle>
          <CardDescription>记录候选 Skill、自动应用和人工审核相关事件，便于答辩时追溯。</CardDescription>
        </div>
        <Badge variant="muted">{formatCount(events.length)} 条</Badge>
      </CardHeader>
      <CardContent>
        {events.length > 0 ? (
          <div className="grid gap-2">
            {events.slice(0, 10).map((event, index) => (
              <article className="flex flex-col gap-2 rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4 sm:flex-row sm:items-center sm:justify-between" key={`${event.created_at ?? ""}-${event.event_type}-${index}`}>
                <div>
                  <h4 className="text-sm font-semibold">{getEventTypeLabel(event.event_type)}</h4>
                  <p className="mt-1 text-xs text-[#6F6257]">{[event.case_id, event.session_id, event.student_id].filter(Boolean).join(" · ") || "系统事件"}</p>
                </div>
                <span className="text-xs text-[#8A7D6F]">{formatDateTime(event.created_at ?? "")}</span>
              </article>
            ))}
          </div>
        ) : (
          <EmptyText>暂无全局审核审计事件。</EmptyText>
        )}
      </CardContent>
    </Card>
  );
}

function EvaluationSection({
  data,
  isDetailBusy,
  isMutating,
  onReadEvaluation,
  onRunEvaluation,
  selectedEvaluation,
}: Readonly<{
  data: DashboardData;
  isDetailBusy: boolean;
  isMutating: boolean;
  onReadEvaluation: (batchId: string) => void;
  onRunEvaluation: () => void;
  selectedEvaluation: EvaluationBatchDetail | null;
}>) {
  const totalCases = data.evaluations.reduce((sum, evaluation) => sum + evaluation.total_cases, 0);
  const passedCases = data.evaluations.reduce((sum, evaluation) => sum + evaluation.passed_cases, 0);
  const passRate = totalCases > 0 ? Math.round((passedCases / totalCases) * 100) : 0;
  return (
    <div className="grid gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <SectionIntro eyebrow="系统评测" title="系统质检和用例结果" description="自动回归测试，用来确认关键链路没有被最近改动破坏。" />
        <Button disabled={isMutating} onClick={onRunEvaluation}>
          {isMutating ? <Loader2 className="animate-spin" /> : <ClipboardCheck />}
          运行系统评测
        </Button>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>系统质检说明</CardTitle>
          <CardDescription>这里不是学生成绩页，而是给管理员看的自动回归测试结果。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          <InfoBlock title="RAG 来源覆盖" value="自动回归测试会检查报告里的反馈解释、建议和来源引用是否还连得上。" />
          <InfoBlock title="报告兼容" value="自动回归测试会检查旧报告和新报告都能打开，避免字段升级后页面崩溃。" />
          <InfoBlock title="Skill 闭环" value="自动回归测试会检查候选生成、审核、启用和后续训练注入是否还能跑通。" />
        </CardContent>
      </Card>
      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard icon={<ClipboardCheck />} label="评测批次" value={formatCount(data.evaluationPagination?.total ?? data.evaluations.length)} helper="历史批次" />
        <MetricCard icon={<Gauge />} label="总通过率" value={`${passRate}%`} helper={`${passedCases}/${totalCases} 用例`} />
        <MetricCard icon={<Wrench />} label="失败用例" value={formatCount(data.evaluations.reduce((sum, evaluation) => sum + evaluation.failed_cases, 0))} helper="需要排查" />
      </div>
      <RetrievalEvalPanel retrievalEval={data.retrievalEval} />
      <Card>
        <CardHeader>
          <CardTitle>评测批次</CardTitle>
          <CardDescription>最新批次优先，点击批次查看用例结果。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2">
            {data.evaluations.map((evaluation) => (
              <article className="flex flex-col gap-3 rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4 sm:flex-row sm:items-center sm:justify-between" key={evaluation.batch_id}>
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-semibold">{evaluation.batch_label || evaluation.batch_id}</h3>
                  <p className="mt-1 text-xs text-[#6F6257]">通过 {evaluation.passed_cases}/{evaluation.total_cases}</p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={evaluation.passed ? "success" : "danger"}>{evaluation.passed ? "通过" : "失败"}</Badge>
                  <Button disabled={isDetailBusy} onClick={() => onReadEvaluation(evaluation.batch_id)} size="sm" variant="secondary">
                    查看评测详情
                  </Button>
                </div>
              </article>
            ))}
            {data.evaluations.length === 0 ? <EmptyText>暂无评测批次。</EmptyText> : null}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>评测详情</CardTitle>
          <CardDescription>用于核对 RAG 来源覆盖、解释覆盖和用例通过状态。</CardDescription>
        </CardHeader>
        <CardContent>
          {selectedEvaluation ? (
            <div className="grid gap-4">
              <div className="grid gap-3 md:grid-cols-4">
                <MiniStat label="总用例" value={formatCount(selectedEvaluation.total_cases)} />
                <MiniStat label="通过" value={formatCount(selectedEvaluation.passed_cases)} />
                <MiniStat label="失败" value={formatCount(selectedEvaluation.failed_cases)} />
                <MiniStat label="耗时" value={`${selectedEvaluation.total_duration_ms ?? 0} ms`} />
              </div>
              <div className="grid gap-2">
                {(selectedEvaluation.results ?? []).slice(0, 8).map((result, index) => (
                  <div className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4" key={`${result.session_id ?? ""}-${index}`}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h4 className="text-sm font-semibold">{result.session_id || `用例 ${index + 1}`}</h4>
                      <Badge variant={result.rag_source_coverage_passed === false || result.rag_explanation_coverage_passed === false ? "warning" : "success"}>RAG 覆盖</Badge>
                    </div>
                    <p className="mt-2 text-sm text-[#6F6257]">
                      分数 {result.actual_total_score ?? "-"} / 期望 {result.expected_total_score ?? "-"} · 解释覆盖 {Math.round((result.rag_explanation_coverage_ratio ?? 0) * 100)}%
                    </p>
                  </div>
                ))}
                {(selectedEvaluation.results ?? []).length === 0 ? <EmptyText>该批次暂无用例明细。</EmptyText> : null}
              </div>
            </div>
          ) : (
            <EmptyText>点击“查看评测详情”后展示批次明细。</EmptyText>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function RetrievalEvalPanel({ retrievalEval }: Readonly<{ retrievalEval: AdminRetrievalEval | null }>) {
  const metrics = retrievalEval?.metrics;
  const results = retrievalEval?.results ?? [];
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>RAG 检索评测</CardTitle>
          <CardDescription>用固定 gold query 检查知识库召回和来源覆盖；不参与标准诊断裁判。</CardDescription>
        </div>
        <Badge variant="muted">{formatCount(metrics?.query_count ?? retrievalEval?.gold_set?.query_count ?? results.length)} 条查询</Badge>
      </CardHeader>
      <CardContent>
        {retrievalEval ? (
          <div className="grid gap-4">
            <div className="grid gap-3 md:grid-cols-5">
              <MiniStat label="Recall@3" value={formatRatioMetric(metrics?.recall_at_3)} />
              <MiniStat label="Recall@5" value={formatRatioMetric(metrics?.recall_at_5)} />
              <MiniStat label="MRR@5" value={formatRatioMetric(metrics?.mrr_at_5)} />
              <MiniStat label="nDCG@5" value={formatRatioMetric(metrics?.ndcg_at_5)} />
              <MiniStat label="来源覆盖" value={formatRatioMetric(metrics?.source_coverage)} />
            </div>
            <div className="grid gap-3 lg:grid-cols-[1fr_0.8fr]">
              <div className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
                <h4 className="text-sm font-semibold">Top 查询命中</h4>
                <div className="mt-3 grid gap-2">
                  {results.slice(0, 5).map((result, index) => (
                    <div className="rounded-xl border border-[#E7E0D4] bg-white px-3 py-3 text-sm" key={`${result.query_id ?? ""}-${index}`}>
                      <p className="font-medium">{result.query || result.query_id || `查询 ${index + 1}`}</p>
                      <p className="mt-1 text-xs leading-5 text-[#6F6257]">命中：{joinText(result.retrieved_references ?? result.hits_at_5, "暂无")}</p>
                    </div>
                  ))}
                  {results.length === 0 ? <EmptyText>暂无检索评测明细。</EmptyText> : null}
                </div>
              </div>
              <div className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
                <h4 className="text-sm font-semibold">运行边界</h4>
                <p className="mt-3 text-sm leading-6 text-[#6F6257]">{retrievalEval.boundary?.rag_usage || "RAG 只服务反馈解释、教学提示、复盘和可追溯展示。"}</p>
                <p className="mt-2 text-sm leading-6 text-[#6F6257]">{retrievalEval.boundary?.scoring_boundary || "检索结果不得进入标准诊断裁判、rubric 评分或隐藏事实判定。"}</p>
              </div>
            </div>
          </div>
        ) : (
          <EmptyText>暂无 RAG 检索评测结果。</EmptyText>
        )}
      </CardContent>
    </Card>
  );
}

function LogsSection({ data }: Readonly<{ data: DashboardData }>) {
  const chartData = useMemo(
    () => buildModelApiChartData(data.apiLogs?.logs ?? [], data.apiLogs?.summary_by_provider ?? []),
    [data.apiLogs],
  );

  return (
    <div className="grid gap-4">
      <SectionIntro eyebrow="模型调用" title="API 成功率和最近错误" description="用于排查模型中转、embedding、TeacherAgent 和审批 Agent 的调用稳定性。" />
      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard icon={<Activity />} label="总调用" value={formatCount(data.apiLogs?.summary.total_calls ?? 0)} helper="最近日志窗口" />
        <MetricCard icon={<Gauge />} label="成功率" value={`${Math.round((data.apiLogs?.summary.success_rate ?? 0) * 100)}%`} helper={`平均 ${data.apiLogs?.summary.avg_duration_ms ?? 0} ms`} />
        <MetricCard icon={<Wrench />} label="失败调用" value={formatCount(data.apiLogs?.summary.failed_calls ?? 0)} helper="已脱敏展示" />
      </div>
      <ModelApiObservabilityPanel chartData={chartData} />
      <Card>
        <CardHeader>
          <CardTitle>最近模型 API 日志</CardTitle>
          <CardDescription>最近 60 条调用记录；不显示密钥或完整 URL，只显示脱敏后的调用结果。</CardDescription>
        </CardHeader>
        <CardContent>
          <ModelApiLogList logs={data.apiLogs?.logs ?? []} />
        </CardContent>
      </Card>
    </div>
  );
}

function ModelApiLogList({ logs }: Readonly<{ logs: readonly ApiCallLog[] }>) {
  const items = logs.slice(0, 18);
  if (items.length === 0) {
    return <EmptyText>暂无模型调用日志。</EmptyText>;
  }

  return (
    <div className="grid gap-3">
      {items.map((log, index) => (
        <article className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4" key={`${log.created_at}-${log.operation}-${index}`}>
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={log.success ? "success" : "danger"}>{log.success ? "成功" : `失败 ${log.status_code ?? ""}`}</Badge>
                <span className="text-sm font-semibold">{getOperationLabel(log.operation)}</span>
                <span className="text-xs text-[#8A7D6F]">{formatDateTime(log.created_at)}</span>
              </div>
              <p className="mt-2 truncate text-sm text-[#6F6257]">
                {log.model || "未记录模型"}
              </p>
            </div>
            <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-3 lg:w-auto">
              <LogMeta label="Provider" value={log.provider || "unknown"} />
              <LogMeta label="耗时" value={`${formatCount(Math.round(log.duration_ms || 0))} ms`} />
              <LogMeta label="调用人" value={getCallerLabel(log)} />
            </div>
          </div>
          <div className="mt-3 grid gap-2 rounded-xl border border-[#F0E8DC] bg-white p-3 text-sm md:grid-cols-[8rem_1fr]">
            <p className="font-semibold text-[#141413]">日志摘要</p>
            <p className="min-w-0 break-words text-[#6F6257]">
              {log.provider || "unknown"} · {getOperationLabel(log.operation)} · {log.endpoint || "未记录 endpoint"}
            </p>
          </div>
          {!log.success ? (
            <div className="mt-3 rounded-xl border border-red-100 bg-red-50 p-3 text-sm">
              <p className="font-semibold text-red-700">失败详情：{log.error_type || "错误"}</p>
              <p className="mt-1 break-words text-xs leading-5 text-red-700">{log.error_message || "后端未记录具体错误。"}</p>
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function LogMeta({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="rounded-xl border border-[#F0E8DC] bg-white px-3 py-2">
      <p className="text-[11px] text-[#8A7D6F]">{label}</p>
      <p className="mt-1 min-w-0 max-w-full truncate text-xs font-semibold text-[#141413] lg:max-w-[10rem]" title={value}>
        {value}
      </p>
    </div>
  );
}

function ModelApiObservabilityPanel({ chartData }: Readonly<{ chartData: ModelApiChartData }>) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>模型调用观测</CardTitle>
          <CardDescription>从最近调用日志派生趋势、成功失败、用途分布和耗时排行，用于定位模型链路稳定性问题。</CardDescription>
        </div>
        <Badge variant="muted">Recharts</Badge>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 lg:grid-cols-2">
          <ModelApiChartCard badge="最近日志窗口" empty={chartData.trend.length === 0} title="调用趋势">
            <ResponsiveContainer height="100%" width="100%">
              <LineChart data={chartData.trend} margin={{ bottom: 8, left: 8, right: 16, top: 8 }}>
                <CartesianGrid stroke="#E7E0D4" strokeDasharray="4 4" />
                <XAxis dataKey="label" minTickGap={18} tick={{ fill: "#6F6257", fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fill: "#6F6257", fontSize: 11 }} width={44} />
                <Tooltip contentStyle={MODEL_API_TOOLTIP_STYLE} />
                <Line dataKey="total" name="总调用" stroke="#AE5630" strokeWidth={2.4} type="monotone" />
                <Line dataKey="failed" name="失败" stroke="#DC2626" strokeWidth={2} type="monotone" />
                <Line dataKey="avgDuration" name="平均耗时 ms" stroke="#2563EB" strokeDasharray="5 5" strokeWidth={2} type="monotone" />
              </LineChart>
            </ResponsiveContainer>
          </ModelApiChartCard>
          <ModelApiChartCard empty={chartData.status.length === 0} title="成功失败分布">
            <ResponsiveContainer height="100%" width="100%">
              <PieChart>
                <Pie data={chartData.status} dataKey="value" innerRadius={48} nameKey="name" outerRadius={78} paddingAngle={3}>
                  {chartData.status.map((item, index) => (
                    <Cell fill={MODEL_API_STATUS_COLORS[item.name] ?? MODEL_API_CHART_COLORS[index % MODEL_API_CHART_COLORS.length]} key={item.name} />
                  ))}
                </Pie>
                <Tooltip contentStyle={MODEL_API_TOOLTIP_STYLE} />
              </PieChart>
            </ResponsiveContainer>
          </ModelApiChartCard>
          <ModelApiChartCard empty={chartData.operations.length === 0} heightClassName="h-[300px]" title="用途分布">
            <ResponsiveContainer height="100%" width="100%">
              <BarChart data={chartData.operations} layout="vertical" margin={{ bottom: 0, left: 0, right: 16, top: 4 }}>
                <CartesianGrid stroke="#E7E0D4" strokeDasharray="4 4" horizontal={false} />
                <XAxis allowDecimals={false} tick={{ fill: "#6F6257", fontSize: 11 }} type="number" />
                <YAxis dataKey="name" tick={{ fill: "#6F6257", fontSize: 11 }} type="category" width={150} />
                <Tooltip contentStyle={MODEL_API_TOOLTIP_STYLE} />
                <Bar dataKey="value" fill="#AE5630" name="调用次数" radius={[0, 6, 6, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ModelApiChartCard>
          <ModelApiChartCard empty={chartData.providerCalls.length === 0} heightClassName="h-[300px]" title="Provider 分布">
            <ResponsiveContainer height="100%" width="100%">
              <BarChart data={chartData.providerCalls} layout="vertical" margin={{ bottom: 0, left: 0, right: 16, top: 4 }}>
                <CartesianGrid stroke="#E7E0D4" strokeDasharray="4 4" horizontal={false} />
                <XAxis allowDecimals={false} tick={{ fill: "#6F6257", fontSize: 11 }} type="number" />
                <YAxis dataKey="name" tick={{ fill: "#6F6257", fontSize: 11 }} type="category" width={170} />
                <Tooltip contentStyle={MODEL_API_TOOLTIP_STYLE} />
                <Bar dataKey="value" fill="#059669" name="调用次数" radius={[0, 6, 6, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ModelApiChartCard>
          <ModelApiChartCard badge="平均耗时" className="lg:col-span-2" empty={chartData.modelLatency.length === 0} heightClassName="h-[320px]" title="模型耗时排行">
            <ResponsiveContainer height="100%" width="100%">
              <BarChart data={chartData.modelLatency} layout="vertical" margin={{ bottom: 0, left: 0, right: 16, top: 4 }}>
                <CartesianGrid stroke="#E7E0D4" strokeDasharray="4 4" horizontal={false} />
                <XAxis allowDecimals={false} tick={{ fill: "#6F6257", fontSize: 11 }} type="number" />
                <YAxis dataKey="name" tick={{ fill: "#6F6257", fontSize: 11 }} type="category" width={170} />
                <Tooltip contentStyle={MODEL_API_TOOLTIP_STYLE} />
                <Bar dataKey="avgDuration" fill="#2563EB" name="平均耗时 ms" radius={[0, 6, 6, 0]} />
                <Bar dataKey="failed" fill="#DC2626" name="失败次数" radius={[0, 6, 6, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ModelApiChartCard>
        </div>
      </CardContent>
    </Card>
  );
}

function ModelApiChartCard({
  badge,
  children,
  className,
  empty,
  heightClassName = "h-64",
  title,
}: Readonly<{
  badge?: string;
  children: ReactNode;
  className?: string;
  empty?: boolean;
  heightClassName?: string;
  title: string;
}>) {
  return (
    <div className={cn("rounded-2xl border border-[#E7E0D4] bg-white p-4", className)}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h4 className="text-sm font-semibold">{title}</h4>
        {badge ? <Badge variant={badge === "平均耗时" ? "warning" : "muted"}>{badge}</Badge> : null}
      </div>
      <div className={cn("mt-4", heightClassName)}>
        {empty ? <ChartEmptyState /> : children}
      </div>
    </div>
  );
}

function ChartEmptyState() {
  return (
    <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-[#E7E0D4] bg-[#FAF9F5] px-4 text-center text-sm text-[#6F6257]">
      暂无可绘制的模型调用日志。
    </div>
  );
}

function SessionTable({
  onSelectSession,
  selectedSessionId,
  sessions,
}: Readonly<{
  onSelectSession?: (sessionId: string) => void;
  selectedSessionId?: string;
  sessions: readonly AdminSessionSummary[];
}>) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-[#8A7D6F]">
          <tr className="border-b border-[#E7E0D4]">
            <th className="py-3 pr-4">病例</th>
            <th className="py-3 pr-4">学员</th>
            <th className="py-3 pr-4">阶段</th>
            <th className="py-3 pr-4">更新时间</th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((session) => (
            <tr
              className={cn("border-b border-[#F0E8DC]", onSelectSession ? "cursor-pointer hover:bg-[#FAF9F5]" : "", selectedSessionId === session.session_id ? "bg-[#F7F4ED]" : "")}
              key={session.session_id}
              onClick={() => onSelectSession?.(session.session_id)}
            >
              <td className="py-3 pr-4">
                <p className="font-semibold">{session.case_title || session.case_id}</p>
                <p className="mt-1 max-w-[16rem] truncate text-xs text-[#8A7D6F]">{session.session_id}</p>
              </td>
              <td className="py-3 pr-4 text-[#6F6257]">{session.student_id}</td>
              <td className="py-3 pr-4">
                <Badge variant={session.stage === "feedback" ? "success" : "muted"}>{session.stage_label ?? session.stage}</Badge>
              </td>
              <td className="py-3 pr-4 text-[#6F6257]">{formatDateTime(session.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {sessions.length === 0 ? <EmptyText>暂无训练 Session。</EmptyText> : null}
    </div>
  );
}

function MiniStat({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
      <p className="text-xs text-[#8A7D6F]">{label}</p>
      <p className="mt-2 text-xl font-semibold">{value}</p>
    </div>
  );
}

function CompactList({ items, title }: Readonly<{ items: readonly string[]; title: string }>) {
  return (
    <div className="rounded-2xl border border-[#E7E0D4] bg-white p-4">
      <h4 className="text-sm font-semibold">{title}</h4>
      {items.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {items.map((item, index) => (
            <Badge key={`${item}-${index}`} variant="muted">
              {item}
            </Badge>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-sm text-[#6F6257]">暂无记录。</p>
      )}
    </div>
  );
}

function InfoBlock({ className, title, value }: Readonly<{ className?: string; title: string; value: string }>) {
  return (
    <div className={cn("rounded-2xl border border-[#E7E0D4] bg-white p-4", className)}>
      <p className="text-xs text-[#8A7D6F]">{title}</p>
      <p className="mt-2 text-sm leading-6 text-[#141413]">{value}</p>
    </div>
  );
}

function MetricCard({ helper, icon, label, value }: Readonly<{ helper: string; icon: ReactNode; label: string; value: string }>) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardDescription>{label}</CardDescription>
          <CardTitle className="mt-2 text-3xl">{value}</CardTitle>
        </div>
        <div className="flex size-11 items-center justify-center rounded-2xl bg-[#F7F4ED] text-[#AE5630]">{icon}</div>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-[#6F6257]">{helper}</p>
      </CardContent>
    </Card>
  );
}

function SectionIntro({ description, eyebrow, title }: Readonly<{ description: string; eyebrow: string; title: string }>) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#AE5630]">{eyebrow}</p>
      <h2 className="mt-1 text-2xl font-semibold">{title}</h2>
      <p className="mt-2 text-sm leading-6 text-[#6F6257]">{description}</p>
    </div>
  );
}

function SimpleList({
  items,
}: Readonly<{
  items: readonly Readonly<{ badge: string; badgeVariant: "success" | "danger" | "warning" | "muted"; id: string; meta: string; title: string }>[];
}>) {
  return (
    <div className="grid gap-2">
      {items.map((item) => (
        <article className="flex items-center justify-between gap-4 rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4" key={item.id}>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold">{item.title}</h3>
            <p className="mt-1 text-xs text-[#6F6257]">{item.meta}</p>
          </div>
          <Badge variant={item.badgeVariant}>{item.badge}</Badge>
        </article>
      ))}
      {items.length === 0 ? <EmptyText>暂无数据。</EmptyText> : null}
    </div>
  );
}

function FormField({ children, className, label }: Readonly<{ children: ReactNode; className?: string; label: string }>) {
  return (
    <label className={cn("grid gap-2 text-sm font-semibold text-[#141413]", className)}>
      {label}
      {children}
    </label>
  );
}

function SelectInput({
  onChange,
  optionLabels,
  options,
  value,
}: Readonly<{
  onChange: (value: string) => void;
  optionLabels?: Record<string, string>;
  options: readonly string[];
  value: string;
}>) {
  return (
    <select
      className="h-10 w-full rounded-xl border border-[#E7E0D4] bg-white px-3 text-sm text-[#141413] outline-none transition focus:border-[#141413] focus:ring-2 focus:ring-[#141413]/10"
      onChange={(event) => onChange(event.target.value)}
      value={value}
    >
      {options.length === 0 ? <option value="">暂无可选项</option> : null}
      {options.map((option) => (
        <option key={option} value={option}>
          {optionLabels?.[option] ?? option}
        </option>
      ))}
    </select>
  );
}

function TextAreaInput({
  maxLength,
  onChange,
  placeholder,
  value,
}: Readonly<{
  maxLength?: number;
  onChange: (value: string) => void;
  placeholder?: string;
  value: string;
}>) {
  return (
    <textarea
      className="min-h-36 resize-y rounded-2xl border border-[#E7E0D4] bg-white px-4 py-3 text-sm leading-6 text-[#141413] outline-none transition placeholder:text-[#9A8B7D] focus:border-[#141413] focus:ring-2 focus:ring-[#141413]/10"
      maxLength={maxLength}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      value={value}
    />
  );
}

function CaseCreationTextRowList({
  addLabel,
  description,
  fieldLabel,
  maxItems,
  onAdd,
  onRemove,
  onUpdate,
  placeholder,
  rows,
}: Readonly<{
  addLabel: string;
  description: string;
  fieldLabel: string;
  maxItems: number;
  onAdd: () => void;
  onRemove: (rowId: string) => void;
  onUpdate: (rowId: string, value: string) => void;
  placeholder: string;
  rows: readonly CaseCreationTextRow[];
}>) {
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold">{fieldLabel}</h4>
          <p className="mt-1 text-xs leading-5 text-[#6F6257]">{description}</p>
        </div>
        <Button disabled={rows.length >= maxItems} onClick={onAdd} size="sm" type="button" variant="secondary">
          <PlusCircle />
          {addLabel}
        </Button>
      </div>
      <div className="grid gap-2">
        {rows.map((row, index) => (
          <div className="grid gap-2 rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-3" key={row.id}>
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs font-semibold text-[#AE5630]">
                {fieldLabel} {index + 1}
              </span>
              <Button disabled={rows.length <= 1} onClick={() => onRemove(row.id)} size="sm" type="button" variant="ghost">
                删除
              </Button>
            </div>
            <Input onChange={(event) => onUpdate(row.id, event.target.value)} placeholder={placeholder} value={row.value} />
          </div>
        ))}
      </div>
    </div>
  );
}

function CaseCreationProcedureRowList({
  addLabel,
  description,
  maxItems,
  namePlaceholder,
  onAdd,
  onRemove,
  onUpdate,
  resultPlaceholder,
  rows,
  title,
}: Readonly<{
  addLabel: string;
  description: string;
  maxItems: number;
  namePlaceholder: string;
  onAdd: () => void;
  onRemove: (rowId: string) => void;
  onUpdate: (rowId: string, patch: Partial<Omit<CaseCreationProcedureRow, "id">>) => void;
  resultPlaceholder: string;
  rows: readonly CaseCreationProcedureRow[];
  title: string;
}>) {
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold">{title}</h4>
          <p className="mt-1 text-xs leading-5 text-[#6F6257]">{description}</p>
        </div>
        <Button disabled={rows.length >= maxItems} onClick={onAdd} size="sm" type="button" variant="secondary">
          <PlusCircle />
          {addLabel}
        </Button>
      </div>
      <div className="grid gap-2">
        {rows.map((row, index) => (
          <div className="grid gap-3 rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-3" key={row.id}>
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs font-semibold text-[#AE5630]">
                {title} {index + 1}
              </span>
              <Button disabled={rows.length <= 1} onClick={() => onRemove(row.id)} size="sm" type="button" variant="ghost">
                删除
              </Button>
            </div>
            <div className="grid gap-2 md:grid-cols-[0.9fr_1.4fr]">
              <Input onChange={(event) => onUpdate(row.id, { name: event.target.value })} placeholder={namePlaceholder} value={row.name} />
              <Input onChange={(event) => onUpdate(row.id, { result: event.target.value })} placeholder={resultPlaceholder} value={row.result} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CaseCreationDifferentialRowList({
  addLabel,
  maxItems,
  onAdd,
  onRemove,
  onUpdate,
  rows,
}: Readonly<{
  addLabel: string;
  maxItems: number;
  onAdd: () => void;
  onRemove: (rowId: string) => void;
  onUpdate: (rowId: string, patch: Partial<Omit<CaseCreationDifferentialRow, "id">>) => void;
  rows: readonly CaseCreationDifferentialRow[];
}>) {
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold">鉴别诊断</h4>
          <p className="mt-1 text-xs leading-5 text-[#6F6257]">每个单元填写一个需要鉴别的疾病和关键区别。</p>
        </div>
        <Button disabled={rows.length >= maxItems} onClick={onAdd} size="sm" type="button" variant="secondary">
          <PlusCircle />
          {addLabel}
        </Button>
      </div>
      <div className="grid gap-2">
        {rows.map((row, index) => (
          <div className="grid gap-3 rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-3" key={row.id}>
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs font-semibold text-[#AE5630]">鉴别诊断 {index + 1}</span>
              <Button disabled={rows.length <= 1} onClick={() => onRemove(row.id)} size="sm" type="button" variant="ghost">
                删除
              </Button>
            </div>
            <div className="grid gap-2 md:grid-cols-[0.8fr_1.4fr]">
              <Input onChange={(event) => onUpdate(row.id, { name: event.target.value })} placeholder="例如 输尿管结石" value={row.name} />
              <Input onChange={(event) => onUpdate(row.id, { description: event.target.value })} placeholder="例如 多伴血尿或腰部绞痛" value={row.description} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EmptyText({ children }: Readonly<{ children: ReactNode }>) {
  return <p className="rounded-2xl border border-dashed border-[#E7E0D4] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">{children}</p>;
}

function getRecordField(value: unknown, fieldName: string): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const fieldValue = (value as Record<string, unknown>)[fieldName];
  return fieldValue && typeof fieldValue === "object" && !Array.isArray(fieldValue) ? (fieldValue as Record<string, unknown>) : null;
}

function getRecordList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

function getStringField(value: unknown, fieldName: string, fallback: string): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return fallback;
  }
  const fieldValue = (value as Record<string, unknown>)[fieldName];
  if (typeof fieldValue === "string") {
    return fieldValue.trim() || fallback;
  }
  if (typeof fieldValue === "number" || typeof fieldValue === "boolean") {
    return String(fieldValue);
  }
  return fallback;
}

function getAgeGenderLabel(patientProfile: Record<string, unknown> | null): string {
  if (!patientProfile) {
    return "";
  }
  const ageValue = getStringField(patientProfile, "age_value", "");
  const ageUnit = getStringField(patientProfile, "age_unit", "岁");
  const gender = getStringField(patientProfile, "gender", "");
  return [ageValue ? `${ageValue}${ageUnit}` : "", gender].filter(Boolean).join(" · ");
}

function toTextList(value: unknown): string[] {
  if (value == null) {
    return [];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => toTextList(item));
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed ? [trimmed] : [];
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return [String(value)];
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    const preferredFields = [
      "label",
      "title",
      "name",
      "item_label",
      "pattern_label",
      "description",
      "statement",
      "message_template",
      "item_id",
      "pattern_id",
      "id",
    ];
    return preferredFields.flatMap((fieldName) => toTextList(record[fieldName]));
  }
  return [];
}

function toInsightDisplayItems(value: unknown, fallbackTitle: string): InsightDisplayItem[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item, index) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        const title = toTextList(item)[0] || `${fallbackTitle} ${index + 1}`;
        return { count: 0, description: "", meta: "", title };
      }
      const record = item as Record<string, unknown>;
      const title =
        getStringField(record, "item_label", "") ||
        getStringField(record, "pattern_label", "") ||
        getStringField(record, "label", "") ||
        getStringField(record, "title", "") ||
        getStringField(record, "description", "") ||
        getStringField(record, "item_id", "") ||
        getStringField(record, "pattern_id", "") ||
        `${fallbackTitle} ${index + 1}`;
      const description =
        getStringField(record, "summary", "") ||
        getStringField(record, "description", "") ||
        getStringField(record, "explanation", "") ||
        getStringField(record, "suggested_focus", "");
      const countValue =
        Number(record.count ?? record.support_count ?? record.source_report_count ?? record.report_count ?? record.frequency ?? 0) || 0;
      const caseText = joinText(record.case_titles ?? record.case_ids, "");
      const sourceText = joinText(record.source_report_ids ?? record.report_ids, "");
      const meta = [caseText ? `病例：${caseText}` : "", sourceText ? `来源报告：${sourceText}` : ""].filter(Boolean).join(" · ");
      return {
        count: countValue,
        description,
        meta,
        title,
      };
    })
    .filter((item) => item.title.trim());
}

function toTokenList(value: unknown): string[] {
  return toTextList(value)
    .flatMap((item) => item.split(/[,，、\n]/))
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinText(value: unknown, fallback: string): string {
  const items = toTextList(value);
  return items.length > 0 ? items.join("、") : fallback;
}

function buildRagKnowledgePayload(item: AdminRagKnowledgeItem): AdminRagKnowledgeItemPayload {
  return {
    knowledge_id: item.knowledge_id,
    scope: item.scope || (item.case_id ? "case" : "global"),
    case_id: item.case_id || "",
    content_kind: item.content_kind || "teaching_note",
    visibility: item.visibility || "pre_submit_safe",
    allowed_agents: toTokenList(item.allowed_agents).length > 0 ? toTokenList(item.allowed_agents) : ["coach", "reflection", "skill_generation", "skill_approval"],
    source_id: item.source_id || "",
    title: item.title || item.section_title || "知识片段",
    text: item.text || "",
    tags: toTokenList(item.tags),
    version: item.version && item.version > 0 ? item.version : 1,
  };
}

const courseModuleOptions = ["腹痛", "胸痛", "发热", "头痛", "咳嗽", "呼吸困难", "心悸", "消瘦", "黄疸", "水肿"];

let caseCreationRowCounter = 0;

function createCaseCreationRowId(prefix: string): string {
  caseCreationRowCounter += 1;
  return `${prefix}_${caseCreationRowCounter}`;
}

function createTextRow(value = ""): CaseCreationTextRow {
  return {
    id: createCaseCreationRowId("text"),
    value,
  };
}

function createProcedureRow(values: Partial<Omit<CaseCreationProcedureRow, "id">> = {}): CaseCreationProcedureRow {
  return {
    code: values.code ?? "",
    id: createCaseCreationRowId("procedure"),
    name: values.name ?? "",
    result: values.result ?? "",
  };
}

function createDifferentialRow(values: Partial<Omit<CaseCreationDifferentialRow, "id">> = {}): CaseCreationDifferentialRow {
  return {
    description: values.description ?? "",
    id: createCaseCreationRowId("differential"),
    name: values.name ?? "",
  };
}

function generateSequentialCaseId(cases: readonly AdminCaseSummary[]): string {
  const existingCaseIds = new Set(cases.map((caseItem) => caseItem.case_id));
  let nextNumber = cases.length + 1;
  while (nextNumber <= 999) {
    const caseId = `teacher_case_${String(nextNumber).padStart(3, "0")}`;
    if (!existingCaseIds.has(caseId)) {
      return caseId;
    }
    nextNumber += 1;
  }
  return "teacher_case_999";
}

function buildDefaultCaseCreationDraft(sources: readonly AdminSourceSummary[], cases: readonly AdminCaseSummary[]): CaseCreationDraft {
  return {
    ageValue: "22",
    caseId: generateSequentialCaseId(cases),
    caseTitle: "",
    chiefComplaint: "",
    courseModule: "腹痛",
    differentialDiagnoses: [createDifferentialRow()],
    difficulty: "初级",
    examItems: [createProcedureRow()],
    gender: "男",
    historyFacts: [createTextRow()],
    hospitalDepartment: "急诊科",
    mainDiagnosis: "",
    occupation: "学生",
    patientConcern: "担心病情加重",
    patientExpectation: "希望明确原因",
    patientIdea: "不清楚具体原因",
    presentIllnessSummary: "",
    reasoningPoints: [createTextRow()],
    safetyNotes: "本病例仅用于 OSCE 教学模拟训练，不提供真实诊疗建议。",
    sourceId: sources[0]?.source_id ?? "",
    testItems: [createProcedureRow()],
  };
}

function getFilledTextRows(rows: readonly CaseCreationTextRow[]): string[] {
  return rows.map((row) => row.value.trim()).filter(Boolean);
}

function getFilledProcedureRows(rows: readonly CaseCreationProcedureRow[]): { code: string; name: string; result: string }[] {
  return rows
    .map((row) => ({
      code: row.code.trim(),
      name: row.name.trim(),
      result: row.result.trim(),
    }))
    .filter((row) => row.name || row.result);
}

function getFilledDifferentialRows(rows: readonly CaseCreationDifferentialRow[]): { description: string; name: string }[] {
  return rows
    .map((row) => ({
      description: row.description.trim(),
      name: row.name.trim(),
    }))
    .filter((row) => row.name || row.description);
}

function getCaseCreationDraftErrors(draft: CaseCreationDraft, cases: readonly AdminCaseSummary[]): string[] {
  const errors: string[] = [];
  const caseId = draft.caseId.trim();
  const ageValue = Number.parseInt(draft.ageValue, 10);
  if (!/^[a-z0-9_]+_\d{3}$/.test(caseId)) {
    errors.push("病例 ID 需形如 teacher_case_482");
  }
  if (cases.some((caseItem) => caseItem.case_id === caseId)) {
    errors.push("病例 ID 已存在");
  }
  if (!draft.caseTitle.trim()) {
    errors.push("请填写病例标题");
  }
  if (!draft.chiefComplaint.trim()) {
    errors.push("请填写主诉");
  }
  if (!draft.presentIllnessSummary.trim()) {
    errors.push("请填写现病史概要");
  }
  if (!Number.isInteger(ageValue) || ageValue < 0 || ageValue > 120) {
    errors.push("年龄需为 0-120 的整数");
  }
  if (!draft.sourceId.trim()) {
    errors.push("请选择来源");
  }
  if (getFilledTextRows(draft.historyFacts).length < 3) {
    errors.push("至少填写 3 条病史线索");
  }
  if (getFilledTextRows(draft.historyFacts).length > CASE_CREATION_HISTORY_MAX_ITEMS) {
    errors.push(`病史线索最多填写 ${CASE_CREATION_HISTORY_MAX_ITEMS} 条`);
  }
  if (getFilledProcedureRows(draft.examItems).length < 1) {
    errors.push("至少填写 1 个查体项目");
  }
  if (getFilledProcedureRows(draft.examItems).length > CASE_CREATION_PROCEDURE_MAX_ITEMS) {
    errors.push(`查体项目最多填写 ${CASE_CREATION_PROCEDURE_MAX_ITEMS} 个`);
  }
  if (getFilledProcedureRows(draft.testItems).length < 1) {
    errors.push("至少填写 1 个辅助检查");
  }
  if (getFilledProcedureRows(draft.testItems).length > CASE_CREATION_PROCEDURE_MAX_ITEMS) {
    errors.push(`辅助检查最多填写 ${CASE_CREATION_PROCEDURE_MAX_ITEMS} 个`);
  }
  if (!draft.mainDiagnosis.trim()) {
    errors.push("请填写主要诊断");
  }
  if (getFilledDifferentialRows(draft.differentialDiagnoses).length < 2) {
    errors.push("至少填写 2 个鉴别诊断");
  }
  if (getFilledDifferentialRows(draft.differentialDiagnoses).length > CASE_CREATION_DIFFERENTIAL_MAX_ITEMS) {
    errors.push(`鉴别诊断最多填写 ${CASE_CREATION_DIFFERENTIAL_MAX_ITEMS} 个`);
  }
  if (getFilledTextRows(draft.reasoningPoints).length < 1) {
    errors.push("至少填写 1 条推理要点");
  }
  if (getFilledTextRows(draft.reasoningPoints).length > CASE_CREATION_REASONING_MAX_ITEMS) {
    errors.push(`推理要点最多填写 ${CASE_CREATION_REASONING_MAX_ITEMS} 条`);
  }
  return errors;
}

function buildCaseCreationPayload(draft: CaseCreationDraft): AdminCaseCreationPayload {
  const caseId = draft.caseId.trim();
  const rubricId = `${caseId}_rubric`;
  const historyRows = getFilledTextRows(draft.historyFacts);
  const examRows = getFilledProcedureRows(draft.examItems);
  const testRows = getFilledProcedureRows(draft.testItems);
  const differentialRows = getFilledDifferentialRows(draft.differentialDiagnoses);
  const reasoningLines = getFilledTextRows(draft.reasoningPoints);
  const historyScores = distributeScores(25, historyRows.length);
  const examScores = distributeScores(15, examRows.length);
  const testScores = distributeScores(15, testRows.length);
  const differentialScores = distributeScores(15, differentialRows.length);

  const historyTopics = [
    { label: "起病与病程", slot: "onset", topic: "现病史", triggers: ["ask_onset", "ask_when_started"] },
    { label: "症状部位", slot: "location", topic: "现病史", triggers: ["ask_location"] },
    { label: "伴随症状", slot: "associated_symptom", topic: "现病史", triggers: ["ask_associated_symptom"] },
    { label: "既往背景", slot: null, topic: "既往史", triggers: ["ask_past_medical"] },
  ];

  const hiddenFacts = historyRows.map((line, index) => {
    const topicConfig = historyTopics[index] ?? { label: `病史线索 ${index + 1}`, slot: "context", topic: "现病史", triggers: [`ask_history_${index + 1}`] };
    const itemId = `ht_${String(index + 1).padStart(2, "0")}`;
    return {
      fact_id: `${caseId}.hf_${String(index + 1).padStart(2, "0")}`,
      topic: topicConfig.topic,
      slot: topicConfig.slot,
      canonical_answer: ensureSentence(line),
      variants: [line],
      trigger_intents: topicConfig.triggers,
      blocking_rule: "reveal_on_direct_question",
      linked_rubric_items: [itemId],
    };
  });

  const physicalExamItems = examRows.map((row, index) => ({
    exam_code: normalizeExamCode(row.code, row.name, index),
    exam_name_cn: row.name,
    result: ensureSentence(row.result),
    is_abnormal: true,
    linked_rubric_items: [`pe_${String(index + 1).padStart(2, "0")}`],
  }));

  const auxiliaryTestItems = testRows.map((row, index) => {
    const testCode = normalizeTestCode(row.code, row.name, index);
    return {
      test_code: testCode,
      test_name_cn: row.name,
      category: getTestCategory(testCode),
      invasiveness: testCode.startsWith("lab.") ? "微创" : "无创",
      cost_hint: testCode.startsWith("img.") ? "中等" : "基础",
      diagnostic_role: "supports_primary_diagnosis",
      rules_out: [],
      recommended_stage: "auxiliary_test",
      overuse_warning: null,
      result: ensureSentence(row.result),
      is_abnormal: true,
      linked_rubric_items: [`ax_${String(index + 1).padStart(2, "0")}`],
    };
  });

  const reasoningPoints = reasoningLines.map((line, index) => ({
    point_id: `${caseId}.rp_${String(index + 1).padStart(2, "0")}`,
    statement: ensureSentence(line),
    kind: index === reasoningLines.length - 1 && reasoningLines.length > 1 ? "鉴别" : "支持",
    required_evidence: [
      hiddenFacts[Math.min(index, hiddenFacts.length - 1)]?.fact_id,
      physicalExamItems[Math.min(index, physicalExamItems.length - 1)]?.exam_code,
      auxiliaryTestItems[Math.min(index, auxiliaryTestItems.length - 1)]?.test_code,
    ].filter((item): item is string => Boolean(item)),
    weight: Math.max(1, 10 - index),
  }));

  const mainDiagnosis = draft.mainDiagnosis.trim();
  const casePayload = {
    case_id: caseId,
    case_title: draft.caseTitle.trim(),
    course_module: draft.courseModule,
    difficulty: draft.difficulty,
    patient_profile: {
      name_placeholder: "×××",
      age_value: Number.parseInt(draft.ageValue, 10),
      age_unit: "岁",
      gender: draft.gender,
      occupation: draft.occupation.trim() || "未记录",
      marital_status: "未知",
      address_city: null,
      social_background: "管理员录入的教学模拟病人。",
      hospital_department: draft.hospitalDepartment.trim() || "门诊",
      idea: draft.patientIdea.trim() || null,
      concern: draft.patientConcern.trim() || null,
      expectation: draft.patientExpectation.trim() || null,
    },
    chief_complaint: draft.chiefComplaint.trim(),
    history: {
      present_illness_summary: ensureSentence(draft.presentIllnessSummary.trim()),
      hidden_facts: hiddenFacts,
      past_medical_history: "见病史线索。",
      surgery_injury_history: null,
      transfusion_history: null,
      infection_history: null,
      allergy_history: null,
      personal_history: null,
      menstrual_history: null,
      reproductive_history: null,
      family_history: null,
    },
    physical_exam: {
      must_items: physicalExamItems,
      optional_items: [],
    },
    auxiliary_tests: {
      must_items: auxiliaryTestItems,
      optional_items: [],
      forbidden_items: [],
    },
    diagnosis: {
      main_diagnosis: mainDiagnosis,
      main_diagnosis_synonyms: [mainDiagnosis],
      icd10_hint: null,
      differential_diagnoses: differentialRows.map((row) => ({
        disease_name: row.name,
        icd10_hint: null,
        expected_action: "排除",
        key_distinction: ensureSentence(row.description || `需要与${mainDiagnosis}鉴别。`),
      })),
      reasoning_points: reasoningPoints,
      suggested_next_steps: "教学模拟中建议围绕病史、查体、辅助检查和鉴别诊断继续完善证据链。",
    },
    distractor_clues: [],
    negative_findings: [],
    evidence_graph: {
      evidence_nodes: [],
      evidence_edges: [],
    },
    rubric_ref: {
      rubric_id: rubricId,
      version: "v1",
    },
    safety_notes: draft.safetyNotes.trim() || "本病例仅用于 OSCE 教学模拟训练。",
    source_attribution: {
      source_id: draft.sourceId,
      transformation: "admin_case_workshop",
      attribution_note: "管理员通过病例工坊录入并结构化为教学模拟病例。",
      modified: true,
    },
    teaching_focus: {
      learning_objectives: [`围绕${draft.courseModule}主诉完成系统问诊`, `用查体和检查验证${mainDiagnosis}相关诊断假设`],
      common_error_patterns: [],
      recommended_training_path: ["病史主线", "重点查体", "辅助检查", "诊断与鉴别诊断"],
    },
    schema_version: "1.1",
    tags: [draft.courseModule, draft.difficulty, mainDiagnosis],
  };

  const rubricPayload = {
    rubric_id: rubricId,
    case_id: caseId,
    version: "v1",
    total_score: 100,
    schema_version: "1.1",
    dimensions: [
      {
        dimension_id: "history_taking",
        weight: 25,
        scoring_mode: "rule",
        items: hiddenFacts.map((fact, index) => ({
          item_id: fact.linked_rubric_items[0],
          description: `追问${historyTopics[index]?.label ?? `病史线索 ${index + 1}`}`,
          max_score: historyScores[index],
          match_rule: {
            kind: "intent_keyword",
            spec: {
              topic: fact.topic,
              slot: fact.slot,
              any_of_keywords: buildKeywordsFromText(fact.canonical_answer),
            },
          },
          evidence_expected: [fact.fact_id],
        })),
      },
      {
        dimension_id: "physical_exam",
        weight: 15,
        scoring_mode: "rule",
        items: physicalExamItems.map((item, index) => ({
          item_id: item.linked_rubric_items[0],
          description: `选择查体：${item.exam_name_cn}`,
          max_score: examScores[index],
          match_rule: {
            kind: "exam_code",
            spec: {
              exam_code: item.exam_code,
              must: true,
            },
          },
          evidence_expected: [item.exam_code],
        })),
      },
      {
        dimension_id: "auxiliary_test",
        weight: 15,
        scoring_mode: "rule",
        items: auxiliaryTestItems.map((item, index) => ({
          item_id: item.linked_rubric_items[0],
          description: `申请检查：${item.test_name_cn}`,
          max_score: testScores[index],
          match_rule: {
            kind: "test_code",
            spec: {
              test_code: item.test_code,
              must: true,
              deduct_if_forbidden: 0,
            },
          },
          evidence_expected: [item.test_code],
        })),
      },
      {
        dimension_id: "main_diagnosis",
        weight: 15,
        scoring_mode: "rule",
        items: [
          {
            item_id: "dx_main",
            description: `主要诊断命中${mainDiagnosis}`,
            max_score: 15,
            match_rule: {
              kind: "diagnosis_concept",
              spec: {
                target: mainDiagnosis,
                synonyms: [mainDiagnosis],
                icd10_hint: "",
              },
            },
            evidence_expected: [],
          },
        ],
      },
      {
        dimension_id: "differential_diagnosis",
        weight: 15,
        scoring_mode: "rule",
        items: differentialRows.map((row, index) => ({
          item_id: `dxd_${String(index + 1).padStart(2, "0")}`,
          description: `提出并鉴别${row.name}`,
          max_score: differentialScores[index],
          match_rule: {
            kind: "diagnosis_concept",
            spec: {
              target: row.name,
              synonyms: [row.name],
              icd10_hint: "",
            },
          },
          evidence_expected: reasoningPoints[index]?.point_id ? [reasoningPoints[index].point_id] : [],
        })),
      },
      {
        dimension_id: "reasoning",
        weight: 15,
        scoring_mode: "rule",
        items: [
          {
            item_id: "rs_reasoning",
            description: "推理表达覆盖关键病史、查体、检查和鉴别诊断证据",
            max_score: 15,
            match_rule: {
              kind: "reasoning_coverage",
              spec: {
                required_evidence: reasoningPoints.flatMap((point) => point.required_evidence).slice(0, 6),
                min_coverage_ratio: 0.6,
              },
            },
            evidence_expected: reasoningPoints.map((point) => point.point_id),
          },
        ],
      },
    ],
  };

  return { case: casePayload, rubric: rubricPayload };
}

function splitLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function parseNamedLines(value: string): { description: string; name: string }[] {
  return splitLines(value).map((line, index) => {
    const parts = splitDelimitedLine(line);
    return {
      name: parts[0] || `鉴别诊断 ${index + 1}`,
      description: parts[1] || "",
    };
  });
}

function parseProcedureRows(value: string): { code: string; name: string; result: string }[] {
  return splitLines(value).map((line, index) => {
    const parts = splitDelimitedLine(line);
    const name = parts[0] || `项目 ${index + 1}`;
    return {
      code: parts[2] || "",
      name,
      result: parts[1] || `${name}结果见教学病例设置。`,
    };
  });
}

function splitDelimitedLine(line: string): string[] {
  return line
    .split(/[|｜]/)
    .map((part) => part.trim())
    .filter(Boolean);
}

function distributeScores(total: number, count: number): number[] {
  if (count <= 0) {
    return [];
  }
  const base = Math.floor(total / count);
  let remainder = total - base * count;
  return Array.from({ length: count }, () => {
    const score = base + (remainder > 0 ? 1 : 0);
    remainder -= 1;
    return Math.max(1, score);
  });
}

function sanitizeCodeToken(value: string, fallback: string): string {
  const token = value
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return /^[a-z][a-z0-9_]*$/.test(token) ? token : fallback;
}

function normalizeExamCode(code: string, name: string, index: number): string {
  if (/^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/.test(code)) {
    return code;
  }
  return `exam.${sanitizeCodeToken(name, `item_${index + 1}`)}`;
}

function normalizeTestCode(code: string, name: string, index: number): string {
  if (/^(lab|img|ecg|endo|path|other)\.[a-z][a-z0-9_]*$/.test(code)) {
    return code;
  }
  const prefix = name.includes("超声") || name.includes("CT") || name.includes("影像") || name.includes("X") ? "img" : name.includes("心电") ? "ecg" : "lab";
  return `${prefix}.${sanitizeCodeToken(name, `test_${index + 1}`)}`;
}

function getTestCategory(testCode: string): string {
  if (testCode.startsWith("img.")) {
    return "影像";
  }
  if (testCode.startsWith("ecg.")) {
    return "心电";
  }
  if (testCode.startsWith("endo.")) {
    return "内镜";
  }
  if (testCode.startsWith("path.")) {
    return "病理";
  }
  if (testCode.startsWith("other.")) {
    return "其他";
  }
  return "实验室";
}

function ensureSentence(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "未记录。";
  }
  return /[。！？.!?]$/.test(trimmed) ? trimmed : `${trimmed}。`;
}

function buildKeywordsFromText(value: string): string[] {
  const compact = value.replace(/[，。！？、,.!?]/g, " ").trim();
  const firstToken = compact.split(/\s+/)[0] || value.slice(0, 6);
  return Array.from(new Set([firstToken, value.slice(0, 6), "追问"].filter((item) => item.trim())));
}

function getCaseImportStatusText(result: AdminCaseImportStatus): string {
  const errors = joinText(result.errors, "");
  if (result.imported) {
    return `发布成功：${result.case_id ?? "新病例"}`;
  }
  if (result.valid) {
    return `预检通过：${result.case_id ?? "新病例"} / ${result.rubric_id ?? "Rubric"}`;
  }
  return errors ? `预检未通过：${errors}` : "预检未通过";
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      const value = typeof reader.result === "string" ? reader.result : "";
      resolve(value.includes(",") ? value.split(",").at(-1) ?? "" : value);
    });
    reader.addEventListener("error", () => reject(reader.error ?? new Error("读取文件失败")));
    reader.readAsDataURL(file);
  });
}

function getJsonUtf8ByteLength(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).byteLength;
}

function buildRubricDescriptionDrafts(rubric: AdminRubricDetail): Record<string, string> {
  return Object.fromEntries(
    rubric.dimensions.flatMap((dimension) => dimension.items.map((item) => [item.item_id, item.description] as const)),
  );
}

function formatRatioMetric(value: number | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return value <= 1 ? `${Math.round(value * 100)}%` : value.toFixed(3);
}

function formatInsightNumber(value: number): string {
  if (!Number.isFinite(value)) {
    return "0";
  }
  return Number.isInteger(value) ? formatCount(value) : value.toFixed(1);
}

function formatPercentage(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "--";
  }
  return `${formatInsightNumber(value)}%`;
}

function formatNormalizedScoreMetric(metric?: AdminNormalizedScoreMetric): string {
  if (!metric || metric.sample_count <= 0 || metric.average_percentage === null) {
    return "不适用";
  }
  return `${formatPercentage(metric.average_percentage)} · ${formatCount(metric.sample_count)} 份`;
}

function formatTrendDelta(value: number): string {
  if (!Number.isFinite(value) || value === 0) {
    return "持平";
  }
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${formatInsightNumber(value)} 分`;
}

function formatPercentageTrend(value: number): string {
  if (!Number.isFinite(value) || value === 0) {
    return "持平";
  }
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${formatInsightNumber(value)} 个百分点`;
}

function getHumanisticGapLabel(gapType: string): string {
  const labels: Record<string, string> = {
    narrative_patient_perspective_missing: "未询问患者视角",
    narrative_life_impact_missing: "未询问生活影响",
    communication_summary_missing: "缺少阶段性总结",
    ethics_consent_missing: "查体/检查前同意缺失",
    ethics_privacy_comfort_missing: "隐私和舒适度说明不足",
    relationship_empathy_missing: "患者担忧后缺少共情回应",
  };
  return labels[gapType] ?? (gapType || "人文沟通缺口");
}

function getLearningGapTitle(gap?: AdminLearningGap): string {
  if (!gap) {
    return "暂无缺口";
  }
  return gap.label || getHumanisticGapLabel(gap.gap_type ?? "") || gap.item_id || "未命名训练点";
}

function getLearningGapDetail(gap?: AdminLearningGap): string {
  if (!gap) {
    return "暂无记录。";
  }
  const title = getLearningGapTitle(gap);
  const metrics = [
    typeof gap.count === "number" ? `${formatCount(gap.count)} 次` : "",
    typeof gap.missing_score_total === "number" ? `累计缺口 ${formatCount(gap.missing_score_total)} 分` : "",
  ].filter(Boolean);
  const evidence = gap.next_training_action || gap.expected_response || "";
  return [title, metrics.join(" · "), evidence].filter(Boolean).join("。");
}

function formatAffectSignalText(signals?: AdminLearningAffectSignals): string {
  if (!signals) {
    return "暂无信号";
  }
  return `信号 ${formatCount(signals.signal_count)} · 缓解 ${formatCount(signals.repaired_count)} · 忽略 ${formatCount(signals.ignored_count)}`;
}

function getTrainingDrillSourceLabel(source: string): string {
  const labels: Record<string, string> = {
    humanistic_gap: "人文沟通缺口",
    missed_opportunity: "错失机会",
    affect_response: "情绪回应",
  };
  return labels[source] ?? "训练信号";
}

function getAnchorCandidateStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    candidate: "待整理",
    reviewed: "已复核",
  };
  return labels[status] ?? (status || "候选");
}

function getAgentLabel(agentId: string): string {
  const labels: Record<string, string> = {
    coach: "教学提示",
    reflection: "训练后复盘",
    skill_approval: "Skill 审批",
    skill_generation: "Skill 生成",
  };
  return labels[agentId] ?? agentId;
}

function getRubricDimensionLabel(dimensionId: string): string {
  const labels: Record<string, string> = {
    auxiliary_test: "辅助检查",
    differential_diagnosis: "鉴别诊断",
    history_taking: "问诊",
    main_diagnosis: "主要诊断",
    medical_ethics: "医学伦理",
    communication_skill: "沟通技巧",
    narrative_medicine: "叙事医学",
    physical_exam: "查体",
    relationship_building: "关系建立",
    reasoning: "推理表达",
  };
  return labels[dimensionId] ?? dimensionId;
}

function getHumanisticReportStats(report: AdminSessionReport): { scoreLabel: string; gaps: readonly AdminTrainingGap[] } | null {
  const scoreGroup = report.score_groups?.humanistic_communication;
  const gaps = (report.training_gaps ?? []).filter((gap) => isHumanisticGap(gap));
  const missedOpportunityCount = report.missed_opportunities?.length ?? 0;
  if (!scoreGroup && gaps.length === 0 && missedOpportunityCount === 0) {
    return null;
  }
  return {
    scoreLabel: scoreGroup ? `${scoreGroup.score}/${scoreGroup.max_score}` : "人文沟通",
    gaps,
  };
}

function isHumanisticGap(gap: AdminTrainingGap): boolean {
  const dimensionId = gap.dimension_id ?? "";
  const skillType = gap.skill_type ?? "";
  const gapType = gap.gap_type ?? "";
  return (
    ["narrative_medicine", "communication_skill", "medical_ethics", "relationship_building"].includes(dimensionId)
    || ["narrative_perspective", "communication_structure", "ethics_consent", "relationship_repair"].includes(skillType)
    || gapType.startsWith("narrative_")
    || gapType.startsWith("communication_")
    || gapType.startsWith("ethics_")
    || gapType.startsWith("relationship_")
  );
}

function getProcedureAuditStatusLabel(audit: ProcedureSimulationAuditItem): string {
  const statusText = audit.approval_status || audit.approval_decision || "";
  const labels: Record<string, string> = {
    approved: "已通过",
    rejected: "已拒绝",
    simulated: "已模拟",
  };
  return labels[statusText] ?? (statusText || "已记录");
}

const MODEL_API_CHART_COLORS = ["#AE5630", "#2563EB", "#059669", "#7C3AED", "#D97706", "#DC2626"];
const MODEL_API_STATUS_COLORS: Record<string, string> = {
  成功: "#059669",
  失败: "#DC2626",
};
const MODEL_API_TOOLTIP_STYLE = {
  background: "#FFFFFF",
  border: "1px solid #E7E0D4",
  borderRadius: "12px",
  color: "#141413",
  fontSize: "12px",
};

function buildModelApiChartData(
  logs: readonly ApiCallLog[],
  providerSummaries: ModelApiLogs["summary_by_provider"],
): ModelApiChartData {
  const normalizedLogs = [...logs]
    .map((log) => ({ ...log, createdTime: new Date(log.created_at).getTime() }))
    .filter((log) => Number.isFinite(log.createdTime))
    .sort((left, right) => left.createdTime - right.createdTime);

  const trendGroups = new Map<string, { total: number; success: number; failed: number; durationTotal: number }>();
  for (const log of normalizedLogs) {
    const label = getModelApiTimeBucketLabel(log.created_at);
    const current = trendGroups.get(label) ?? { total: 0, success: 0, failed: 0, durationTotal: 0 };
    current.total += 1;
    current.success += log.success ? 1 : 0;
    current.failed += log.success ? 0 : 1;
    current.durationTotal += Math.max(0, Number(log.duration_ms) || 0);
    trendGroups.set(label, current);
  }

  const trend = Array.from(trendGroups.entries())
    .map(([label, item]) => ({
      label,
      total: item.total,
      success: item.success,
      failed: item.failed,
      avgDuration: Math.round(item.durationTotal / Math.max(item.total, 1)),
    }))
    .slice(-10);

  const successCount = logs.filter((log) => log.success).length;
  const failedCount = logs.length - successCount;
  const operations = aggregateModelApiCounts(logs, (log) => getOperationLabel(log.operation), 6);
  const providerCalls = providerSummaries
    .map((item) => ({ name: getProviderLabel(item.provider), value: item.total_calls }))
    .filter((item) => item.value > 0)
    .slice(0, 6);
  const modelLatency = aggregateModelApiLatency(logs);

  return {
    trend,
    status: [
      { name: "成功", value: successCount },
      { name: "失败", value: failedCount },
    ].filter((item) => item.value > 0),
    operations,
    providerCalls,
    modelLatency,
  };
}

function aggregateModelApiCounts(
  logs: readonly ApiCallLog[],
  labelFactory: (log: ApiCallLog) => string,
  limit: number,
): ModelApiDistributionPoint[] {
  const counts = new Map<string, number>();
  for (const log of logs) {
    const label = labelFactory(log) || "未记录";
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([name, value]) => ({ name, value }))
    .sort((left, right) => right.value - left.value || left.name.localeCompare(right.name, "zh-CN"))
    .slice(0, limit);
}

function aggregateModelApiLatency(logs: readonly ApiCallLog[]): ModelApiLatencyPoint[] {
  const groups = new Map<string, { calls: number; failed: number; durationTotal: number }>();
  for (const log of logs) {
    const modelName = log.model || "未记录模型";
    const name = modelName.length > 18 ? `${modelName.slice(0, 18)}…` : modelName;
    const current = groups.get(name) ?? { calls: 0, failed: 0, durationTotal: 0 };
    current.calls += 1;
    current.failed += log.success ? 0 : 1;
    current.durationTotal += Math.max(0, Number(log.duration_ms) || 0);
    groups.set(name, current);
  }
  return Array.from(groups.entries())
    .map(([name, item]) => ({
      name,
      calls: item.calls,
      avgDuration: Math.round(item.durationTotal / Math.max(item.calls, 1)),
      failed: item.failed,
    }))
    .sort((left, right) => right.avgDuration - left.avgDuration || right.calls - left.calls)
    .slice(0, 6);
}

function getModelApiTimeBucketLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "未知";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    day: "2-digit",
    hour: "2-digit",
    month: "2-digit",
  }).format(date);
}

function formatCount(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatDateTime(value: string): string {
  if (!value) {
    return "未记录";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "2-digit",
  }).format(date);
}

function getCandidateStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    approved: "已批准",
    blocked_by_regression: "回归阻塞",
    ready_for_review: "待审核",
    rejected: "已拒绝",
  };
  return labels[status] ?? (status || "未记录");
}

function getSkillEffectStatusLabel(status: string | undefined): string {
  if (!status) {
    return "未记录";
  }
  if (status === "insufficient_samples") {
    return "样本不足";
  }
  return status;
}

function getKnowledgeVisibilityLabel(visibility: string | undefined): string {
  const labels: Record<string, string> = {
    admin_only: "仅管理员可见",
    post_submit_review: "提交后复盘可用",
    pre_submit_safe: "训练前可用于提示",
    secret_scoring_only: "仅评分结构使用",
  };
  return labels[visibility || ""] ?? (visibility || "未记录");
}

function getOperationLabel(operation: string): string {
  const labels: Record<string, string> = {
    "chat.completions": "OpenAI 对话",
    embed_content: "向量嵌入",
    embedding: "向量检索",
    generate_content: "Gemini 生成",
    messages: "Claude 对话",
    patient_response: "标准化病人",
    rerank: "召回重排",
    synthesize: "语音合成",
    chat_completion: "对话模型",
    skill_candidate: "Skill 生成",
    procedure_result: "检查模拟",
  };
  return labels[operation] ?? (operation || "未记录");
}

function getProviderLabel(provider: string): string {
  const labels: Record<string, string> = {
    anthropic: "Anthropic",
    dashscope_speech: "DashScope 语音",
    openai_compatible: "OpenAI 兼容",
    openai_compatible_fallback: "OpenAI 兜底",
    vertex_gemini_coach: "Coach Gemini",
    vertex_gemini_embedding: "Vertex Embedding",
    vertex_gemini_patient: "患者 Gemini",
    vertex_gemini_skill_candidate: "Skill Gemini",
    vertex_gemini_turn_intent: "意图 Gemini",
  };
  return labels[provider] ?? (provider || "unknown");
}

function getCallerLabel(log: ApiCallLog): string {
  return log.caller || log.student_id || log.user_id || log.session_id || "后端未记录";
}

function getEventTypeLabel(eventType: string): string {
  const labels: Record<string, string> = {
    case_intro: "病例导入",
    diagnosis_submitted: "提交诊断",
    report_generated: "报告生成",
    skill_candidate_generated: "候选 Skill 生成",
    skill_candidate_approved: "候选 Skill 批准",
    skill_candidate_rejected: "候选 Skill 拒绝",
    training_skill_applied: "Skill 已应用",
  };
  return labels[eventType] ?? (eventType || "未记录");
}

function canReviewCandidate(candidate: TrainingSkillCandidateDetail): boolean {
  return candidate.status === "ready_for_review" || candidate.review?.status === "ready_for_review";
}

function getSkillContentText(candidate: TrainingSkillCandidateDetail): string {
  const parts = [
    candidate.description,
    candidate.suggested_strategy,
    joinText(candidate.trigger_item_labels, ""),
    ...((candidate.teaching_action_plan ?? []).map((action) => action.message_template || action.action_type_label || action.action_type).filter(Boolean) as string[]),
  ].filter((part): part is string => Boolean(part?.trim()));
  return parts.length > 0 ? Array.from(new Set(parts)).join("；") : "暂无完整说明。";
}

function getSkillStrategyText(candidate: TrainingSkillCandidateDetail): string {
  const actionText = (candidate.teaching_action_plan ?? [])
    .map((action) => action.message_template || action.action_type_label || action.action_type)
    .filter(Boolean)
    .join("；");
  return candidate.suggested_strategy || actionText || "暂无策略。";
}

function getCandidateSourceText(candidate: TrainingSkillCandidateDetail): string {
  const reportIds = toTextList(candidate.source_report_ids).slice(0, 8);
  const sessionIds = toTextList(candidate.source_session_ids).slice(0, 8);
  const sourceParts = [
    reportIds.length > 0 ? `报告：${reportIds.join("、")}` : "",
    sessionIds.length > 0 ? `Session：${sessionIds.join("、")}` : "",
  ].filter(Boolean);
  return sourceParts.length > 0 ? sourceParts.join("；") : `${candidate.source_report_count} 份报告支持`;
}

function getApprovalReviewText(review: TrainingSkillApprovalAgentReview | undefined): string {
  if (!review) {
    return "暂无审批 Agent 记录。";
  }
  const parts = [
    review.decision ? `结论：${review.decision}` : "",
    review.revision_status ? `修改：${review.revision_status}` : "",
    review.regression_status ? `回归：${review.regression_status}` : "",
    toTextList(review.changed_fields).length ? `调整字段：${toTextList(review.changed_fields).join("、")}` : "",
  ].filter(Boolean);
  return parts.join("；") || "审批 Agent 已记录，但暂无摘要。";
}
