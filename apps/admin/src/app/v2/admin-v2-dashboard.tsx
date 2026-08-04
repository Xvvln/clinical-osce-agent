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
  School,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  Trash2,
  UsersRound,
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
const RAG_STAGE_OPTIONS = ["any", "case_intro", "history_taking", "physical_exam", "auxiliary_test", "diagnosis_submission", "feedback"] as const;
const RAG_STAGE_LABELS: Readonly<Record<(typeof RAG_STAGE_OPTIONS)[number], string>> = {
  any: "全部训练阶段",
  case_intro: "病例导入",
  history_taking: "问诊阶段",
  physical_exam: "查体阶段",
  auxiliary_test: "辅助检查",
  diagnosis_submission: "诊断提交前",
  feedback: "训练后复盘",
};
const CASE_TITLE_MAX_CHARS = 120;
const CHIEF_COMPLAINT_MAX_CHARS = 500;
const SAFETY_NOTES_MAX_CHARS = 1000;
const RUBRIC_DESCRIPTION_MAX_CHARS = 1000;
const CASE_CREATION_HISTORY_MAX_ITEMS = 8;
const CASE_CREATION_PROCEDURE_MAX_ITEMS = 6;
const CASE_CREATION_DIFFERENTIAL_MAX_ITEMS = 4;
const CASE_CREATION_REASONING_MAX_ITEMS = 4;
const CLASSROOM_NAME_MAX_CHARS = 80;
const CLASSROOM_DESCRIPTION_MAX_CHARS = 500;

type AuthUser = Readonly<{
  user_id: string;
  email: string;
  display_name?: string;
  created_at?: string;
  is_admin: boolean;
  role?: "student" | "teacher" | "admin";
  status?: "active" | "disabled" | "deleted";
}>;

type AdminManagedUser = AuthUser &
  Readonly<{
    eligible_for_classroom: boolean;
    eligible_as_teacher: boolean;
    managed_by_environment: boolean;
    role: "student" | "teacher" | "admin";
    status: "active" | "disabled" | "deleted";
    updated_at?: string;
  }>;

type AdminUserCreatePayload = Readonly<{
  email: string;
  password: string;
  display_name: string;
  role: AdminManagedUser["role"];
}>;

type AdminUserUpdatePayload = Readonly<{
  email?: string;
  display_name?: string;
  role?: AdminManagedUser["role"];
  status?: "active" | "disabled";
}>;

type AdminClassroom = Readonly<{
  classroom_id: string;
  name: string;
  description: string;
  member_user_ids: readonly string[];
  member_count: number;
  members: readonly AdminManagedUser[];
  created_by: string;
  created_at: string;
  updated_by: string;
  updated_at: string;
  teacher_user_id: string;
  teacher?: AdminManagedUser | null;
  status: "active" | "archived";
}>;

type AdminClassroomPayload = Readonly<{
  name: string;
  description: string;
  member_user_ids: readonly string[];
  teacher_user_id: string;
  status: AdminClassroom["status"];
}>;

type AdminAuditEvent = Readonly<{
  event_id: string;
  actor_user_id?: string;
  actor_email?: string;
  action: string;
  resource_type: string;
  resource_id: string;
  summary: string;
  before?: unknown;
  after?: unknown;
  metadata?: unknown;
  created_at: string;
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

type TeacherInterventionEvent = Readonly<{
  mode: string;
  actionType: string;
  triggerKind: string;
  reasonCode: string;
  reason: string;
  hint: string;
  hintEmitted: boolean;
  selectedSkillIds: readonly string[];
  sourceReferences: readonly string[];
  processingStatus: string;
  createdAt: string;
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
  changed_fields?: readonly Readonly<{
    field?: string;
    before?: unknown;
    after?: unknown;
  }>[];
  regression_status?: string;
  regression_passed?: boolean;
  quality_review?: Readonly<{
    passed?: boolean;
    failed_checks?: readonly string[];
    checks?: readonly Readonly<{
      check_id?: string;
      title?: string;
      passed?: boolean;
      detail?: string;
    }>[];
  }>;
  role_policy?: Readonly<{
    passed?: boolean;
    failed_checks?: readonly string[];
  }>;
  knowledge_references?: readonly string[];
  retrieved_knowledge_context?: readonly Readonly<{
    reference?: string;
    title?: string;
    source_id?: string;
    visibility?: string;
  }>[];
  regression_gate?: Readonly<{
    status?: string;
    passed?: boolean;
    evaluation_total_cases?: number;
    evaluation_passed_cases?: number;
    evaluation_failed_cases?: number;
    blocking_failures?: readonly unknown[];
    candidate_safety_violations?: readonly unknown[];
    candidate_context_violations?: readonly unknown[];
    approval_agent_violations?: readonly unknown[];
  }>;
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
  suite_id?: string;
  suite_label?: string;
  triggered_by?: string;
  created_at?: string;
}>;

type AdminEvaluationStep = Readonly<{
  kind: "message" | "physical_exam" | "auxiliary_test" | "submit_diagnosis";
  value: string;
  reasoning?: string;
}>;

type AdminEvaluationCaseConfig = Readonly<{
  case_key: string;
  label: string;
  case_id: string;
  steps: readonly AdminEvaluationStep[];
  expected_total_score: number;
  forbidden_terms: readonly string[];
  enabled: boolean;
  is_builtin?: boolean;
  updated_at?: string;
}>;

type AdminEvaluationThresholds = Readonly<{
  maximum_score_delta: number;
  minimum_batch_pass_rate: number;
  minimum_rag_explanation_coverage_ratio: number;
  minimum_rag_evidence_coverage_ratio: number;
  require_rag_source_coverage: boolean;
  maximum_case_duration_ms: number;
}>;

type AdminEvaluationSuiteConfig = Readonly<{
  suite_id: string;
  label: string;
  description: string;
  case_keys: readonly string[];
  thresholds: AdminEvaluationThresholds;
  enabled: boolean;
  is_builtin?: boolean;
  updated_at?: string;
}>;

type AdminEvaluationSchedule = Readonly<{
  enabled: boolean;
  suite_id: string;
  interval_minutes: number;
  status: string;
  next_run_at?: string;
  last_completed_at?: string;
  last_batch_id?: string;
  last_error?: string;
}>;

type AdminEvaluationConfig = Readonly<{
  evaluation_cases: readonly AdminEvaluationCaseConfig[];
  suites: readonly AdminEvaluationSuiteConfig[];
  schedule: AdminEvaluationSchedule;
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
  source_name?: string;
  source_url?: string;
  data_type?: string;
  license?: string;
  source_version?: string;
  last_reviewed_at?: string;
  review_due_at?: string;
  freshness_status?: string;
  freshness_label?: string;
  source_status?: string;
  superseded_by?: string;
  selectable_for_new_knowledge?: boolean;
  allowed_usage?: readonly string[];
  transformation?: string;
  attribution_required?: boolean;
  risk_note?: string;
  review_interval_days?: number;
  review_basis?: string;
  search_aliases?: readonly string[];
}>;

type AdminSourcePayload = Readonly<{
  source_id: string;
  source_name: string;
  source_url: string;
  license: string;
  data_type: string;
  allowed_usage: readonly string[];
  transformation: string;
  attribution_required: boolean;
  risk_note: string;
  source_version: string;
  last_reviewed_at: string;
  review_interval_days: number;
  source_status: "active" | "superseded" | "inactive";
  superseded_by: string;
  review_basis: string;
  search_aliases: readonly string[];
  change_note: string;
  medical_review_note: string;
}>;

type AdminAssetVersion = Readonly<{
  asset_type: string;
  asset_id: string;
  version: number;
  payload_hash: string;
  change_note: string;
  review_status: "unreviewed" | "approved" | "rejected" | string;
  review_note: string;
  actor_email: string;
  created_at: string;
}>;

type AdminAssetDiff = Readonly<{
  from_version: number;
  to_version: number;
  change_count: number;
  changes: readonly Readonly<{
    path: string;
    change: string;
    before: unknown;
    after: unknown;
  }>[];
}>;

type AdminCaseAssets = Readonly<{
  case: AdminCaseRaw;
  rubric: Record<string, unknown>;
  current_version: AdminAssetVersion & Readonly<{ payload?: unknown }>;
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
  stage_scope?: readonly string[];
  stage_scope_labels?: readonly string[];
  review_status?: string;
  approved_chunk_count?: number;
  pending_review_chunk_count?: number;
  rejected_chunk_count?: number;
  indexable_chunk_count?: number;
  quality_warnings?: readonly string[];
  risk_flags?: readonly string[];
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
  stage_scope?: readonly string[] | string;
  stage_scope_labels?: readonly string[];
  tags?: readonly string[] | string;
  version?: number;
  chunk_index?: number | null;
  chunk_count?: number | null;
  section_title?: string;
  page_number?: number | null;
  source_location?: string;
  chunking_strategy?: string;
  chunk_categories?: readonly string[];
  quality_warnings?: readonly string[];
  risk_flags?: readonly string[];
  char_count?: number | null;
  enabled?: boolean;
  review_status?: string;
  review_note?: string;
  reviewed_by?: string;
  reviewed_at?: string;
  updated_at?: string;
}>;

type AdminRagKnowledgeItemPayload = Readonly<{
  knowledge_id: string;
  scope: string;
  case_id: string;
  content_kind: string;
  visibility: string;
  allowed_agents: readonly string[];
  stage_scope: readonly string[];
  source_id: string;
  title: string;
  text: string;
  tags: readonly string[];
  version: number;
}>;

type AdminRagDocumentUploadPayload = Readonly<{
  allowed_agents: readonly string[];
  stage_scope: readonly string[];
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

type AdminRagKnowledgeMutationResponse = Readonly<{
  knowledge_item: AdminRagKnowledgeItem;
  document?: AdminRagDocument;
}>;

type AdminRagDocumentReviewResponse = Readonly<{
  document: AdminRagDocument;
  knowledge_items: readonly AdminRagKnowledgeItem[];
}>;

type AdminRagReviewDecision = "approved" | "rejected";

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
    hit_rate_at_5?: number;
    zero_hit_query_count?: number;
  }>;
  results?: readonly Readonly<{
    expected_references?: readonly string[];
    expanded_query?: string;
    hits_at_5?: readonly string[];
    query?: string;
    query_id?: string;
    retrieved_references?: readonly string[];
    retrieved_items?: readonly Readonly<{
      reference?: string;
      retrieval_methods?: readonly string[];
      score?: number;
    }>[];
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
  users: readonly AdminManagedUser[];
  classrooms: readonly AdminClassroom[];
  sessions: readonly AdminSessionSummary[];
  sessionPagination: Pagination | null;
  reports: readonly AdminReportSummary[];
  reportPagination: Pagination | null;
  candidates: readonly TrainingSkillCandidateSummary[];
  candidatePagination: Pagination | null;
  evaluations: readonly EvaluationBatchSummary[];
  evaluationPagination: Pagination | null;
  evaluationConfig: AdminEvaluationConfig | null;
  cases: readonly AdminCaseSummary[];
  sources: readonly AdminSourceSummary[];
  documents: readonly AdminRagDocument[];
  documentPagination: Pagination | null;
  knowledgeItems: readonly AdminRagKnowledgeItem[];
  knowledgePagination: Pagination | null;
  insights: TrainingInsights | null;
  learningAnalytics: AdminLearningAnalytics | null;
  procedureAudits: readonly ProcedureSimulationAuditItem[];
  procedureAuditSummary: ProcedureSimulationAuditSummary | null;
  teachingFocusPatterns: readonly AdminTeachingFocusPattern[];
  auditEvents: readonly TrainingEventRecord[];
  adminAuditEvents: readonly AdminAuditEvent[];
  adminAuditPagination: Pagination | null;
  retrievalEval: AdminRetrievalEval | null;
  skillEffects: TrainingSkillEffects | null;
  autoApprovalSettings: TrainingSkillAutoApprovalSettings | null;
}>;

type AdminSectionId = "overview" | "classes" | "resources" | "training" | "insights" | "skill" | "evaluation" | "logs";

const emptyDashboardData: DashboardData = {
  modelConfig: null,
  apiLogs: null,
  users: [],
  classrooms: [],
  sessions: [],
  sessionPagination: null,
  reports: [],
  reportPagination: null,
  candidates: [],
  candidatePagination: null,
  evaluations: [],
  evaluationPagination: null,
  evaluationConfig: null,
  cases: [],
  sources: [],
  documents: [],
  documentPagination: null,
  knowledgeItems: [],
  knowledgePagination: null,
  insights: null,
  learningAnalytics: null,
  procedureAudits: [],
  procedureAuditSummary: null,
  teachingFocusPatterns: [],
  auditEvents: [],
  adminAuditEvents: [],
  adminAuditPagination: null,
  retrievalEval: null,
  skillEffects: null,
  autoApprovalSettings: null,
};

const sections: readonly Readonly<{ id: AdminSectionId; label: string; icon: typeof LayoutDashboard }>[] = [
  { id: "overview", label: "概览", icon: LayoutDashboard },
  { id: "classes", label: "班级管理", icon: School },
  { id: "resources", label: "教学资源", icon: BookOpen },
  { id: "training", label: "训练管理", icon: Stethoscope },
  { id: "insights", label: "教学洞察", icon: Brain },
  { id: "skill", label: "Skill 进化", icon: Sparkles },
  { id: "evaluation", label: "系统评测", icon: ClipboardCheck },
  { id: "logs", label: "审计与调用日志", icon: Activity },
];

function formatApiErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (detail && typeof detail === "object") {
    const payload = detail as { message?: unknown; errors?: unknown };
    const message = typeof payload.message === "string" ? payload.message : fallback;
    const errors = Array.isArray(payload.errors)
      ? payload.errors.filter((item): item is string => typeof item === "string")
      : [];
    return errors.length > 0 ? `${message}：${errors.slice(0, 5).join("；")}` : message;
  }
  return fallback;
}

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
      const payload = (await response.json()) as { detail?: unknown };
      detail = formatApiErrorDetail(payload.detail, detail);
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
    usersPayload,
    classroomsPayload,
    sessionPayload,
    reportPayload,
    candidatePayload,
    evaluationPayload,
    evaluationConfigPayload,
    casesPayload,
    sourcesPayload,
    documentsPayload,
    knowledgePayload,
    insightsPayload,
    learningAnalyticsPayload,
    procedureAuditPayload,
    teachingFocusPayload,
    auditEventsPayload,
    adminAuditPayload,
    skillEffectsPayload,
    autoApprovalSettingsPayload,
  ] = await Promise.all([
    fetchJson<{ providers: readonly AdminModelProvider[]; policy: AdminModelConfig["policy"] }>("/api/admin/model-config"),
    fetchJson<ModelApiLogs>("/api/admin/model-api-logs?limit=60"),
    fetchJson<{ users: readonly AdminManagedUser[] }>("/api/admin/users"),
    fetchJson<{ classrooms: readonly AdminClassroom[] }>("/api/admin/classrooms"),
    fetchJson<{ sessions: readonly AdminSessionSummary[]; pagination?: Pagination }>("/api/admin/sessions?limit=20"),
    fetchJson<{ reports: readonly AdminReportSummary[]; pagination?: Pagination }>("/api/admin/reports?limit=20"),
    fetchJson<{ candidates: readonly TrainingSkillCandidateSummary[]; pagination?: Pagination }>("/api/admin/evolution/candidates?limit=20&review_status=all"),
    fetchJson<{ evaluations: readonly EvaluationBatchSummary[]; pagination?: Pagination }>("/api/admin/evaluations?limit=20"),
    fetchJson<AdminEvaluationConfig>("/api/admin/evaluation-config"),
    fetchJson<{ cases: readonly AdminCaseSummary[] }>("/api/cases"),
    fetchJson<{ sources: readonly AdminSourceSummary[] }>("/api/admin/sources"),
    fetchJson<{ documents: readonly AdminRagDocument[]; pagination?: Pagination }>("/api/admin/rag/documents?limit=12"),
    fetchJson<{ knowledge_items: readonly AdminRagKnowledgeItem[]; pagination?: Pagination }>("/api/admin/rag/knowledge?limit=50"),
    fetchJson<{ insights: TrainingInsights }>("/api/admin/insights"),
    fetchJson<{ learning_analytics: AdminLearningAnalytics }>("/api/admin/learning-analytics"),
    fetchJson<{ procedure_simulation_audits: readonly ProcedureSimulationAuditItem[]; summary?: ProcedureSimulationAuditSummary }>("/api/admin/procedure-simulation-audits?limit=20"),
    fetchJson<{ patterns: readonly AdminTeachingFocusPattern[] }>("/api/admin/teaching-focus/patterns"),
    fetchJson<{ events: readonly TrainingEventRecord[] }>("/api/admin/evolution/events?limit=20"),
    fetchJson<{ events: readonly AdminAuditEvent[]; pagination?: Pagination }>("/api/admin/audit-events?limit=50"),
    fetchJson<{ skill_effects: TrainingSkillEffects }>("/api/admin/evolution/skill-effects"),
    fetchJson<{ settings: TrainingSkillAutoApprovalSettings }>("/api/admin/evolution/settings"),
  ]);
  return {
    modelConfig: modelConfigPayload,
    apiLogs: apiLogPayload,
    users: usersPayload.users,
    classrooms: classroomsPayload.classrooms,
    sessions: sessionPayload.sessions,
    sessionPagination: sessionPayload.pagination ?? null,
    reports: reportPayload.reports,
    reportPagination: reportPayload.pagination ?? null,
    candidates: candidatePayload.candidates,
    candidatePagination: candidatePayload.pagination ?? null,
    evaluations: evaluationPayload.evaluations,
    evaluationPagination: evaluationPayload.pagination ?? null,
    evaluationConfig: evaluationConfigPayload,
    cases: casesPayload.cases,
    sources: sourcesPayload.sources,
    documents: documentsPayload.documents,
    documentPagination: documentsPayload.pagination ?? null,
    knowledgeItems: knowledgePayload.knowledge_items,
    knowledgePagination: knowledgePayload.pagination ?? null,
    insights: insightsPayload.insights,
    learningAnalytics: learningAnalyticsPayload.learning_analytics,
    procedureAudits: procedureAuditPayload.procedure_simulation_audits,
    procedureAuditSummary: procedureAuditPayload.summary ?? null,
    teachingFocusPatterns: teachingFocusPayload.patterns,
    auditEvents: auditEventsPayload.events,
    adminAuditEvents: adminAuditPayload.events,
    adminAuditPagination: adminAuditPayload.pagination ?? null,
    retrievalEval: null,
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

async function getAdminCaseAssets(caseId: string): Promise<AdminCaseAssets> {
  return fetchJson(`/api/admin/cases/${encodeURIComponent(caseId)}/assets`);
}

async function replaceAdminCaseAssets(
  caseId: string,
  payload: Readonly<{
    case: AdminCaseRaw;
    rubric: Record<string, unknown>;
    change_note: string;
    review_status: "unreviewed" | "approved" | "rejected";
    medical_review_note: string;
  }>,
): Promise<AdminCaseAssets> {
  return fetchJson(`/api/admin/cases/${encodeURIComponent(caseId)}/assets`, {
    body: JSON.stringify(payload),
    method: "PUT",
  });
}

async function getAdminAssetVersions(assetPath: string): Promise<readonly AdminAssetVersion[]> {
  const response = await fetchJson<{ versions: readonly AdminAssetVersion[] }>(`${assetPath}/versions?limit=50`);
  return response.versions;
}

async function getAdminAssetDiff(assetPath: string, fromVersion: number, toVersion: number): Promise<AdminAssetDiff> {
  return fetchJson(`${assetPath}/diff?from_version=${fromVersion}&to_version=${toVersion}`);
}

async function rollbackAdminAsset<T>(assetPath: string, version: number, changeNote: string): Promise<T> {
  return fetchJson(`${assetPath}/rollback`, {
    body: JSON.stringify({ version, change_note: changeNote }),
    method: "POST",
  });
}

async function reviewAdminCase(
  caseId: string,
  reviewStatus: "approved" | "rejected",
  medicalReviewNote: string,
): Promise<AdminAssetVersion> {
  const response = await fetchJson<{ current_version: AdminAssetVersion }>(`/api/admin/cases/${encodeURIComponent(caseId)}/review`, {
    body: JSON.stringify({ review_status: reviewStatus, medical_review_note: medicalReviewNote }),
    method: "POST",
  });
  return response.current_version;
}

async function createOrUpdateAdminSource(
  payload: AdminSourcePayload,
  existingSourceId: string,
): Promise<AdminSourceSummary> {
  const path = existingSourceId
    ? `/api/admin/sources/${encodeURIComponent(existingSourceId)}`
    : "/api/admin/sources";
  const response = await fetchJson<{ source: AdminSourceSummary }>(path, {
    body: JSON.stringify(payload),
    method: existingSourceId ? "PUT" : "POST",
  });
  return response.source;
}

async function reviewAdminSource(
  sourceId: string,
  payload: Readonly<{
    last_reviewed_at: string;
    review_interval_days: number;
    review_basis: string;
    source_status: "active" | "superseded" | "inactive";
    superseded_by: string;
    medical_review_note: string;
  }>,
): Promise<AdminSourceSummary> {
  const response = await fetchJson<{ source: AdminSourceSummary }>(`/api/admin/sources/${encodeURIComponent(sourceId)}/review`, {
    body: JSON.stringify(payload),
    method: "POST",
  });
  return response.source;
}

async function deactivateAdminSource(sourceId: string): Promise<AdminSourceSummary> {
  const response = await fetchJson<{ source: AdminSourceSummary }>(`/api/admin/sources/${encodeURIComponent(sourceId)}`, {
    method: "DELETE",
  });
  return response.source;
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

async function getAdminEvaluationConfig(): Promise<AdminEvaluationConfig> {
  return fetchJson("/api/admin/evaluation-config");
}

async function saveAdminEvaluationCase(
  evaluationCase: AdminEvaluationCaseConfig,
): Promise<AdminEvaluationCaseConfig> {
  const response = await fetchJson<{ evaluation_case: AdminEvaluationCaseConfig }>(
    `/api/admin/evaluation-cases/${encodeURIComponent(evaluationCase.case_key)}`,
    { body: JSON.stringify(evaluationCase), method: "PUT" },
  );
  return response.evaluation_case;
}

async function deleteAdminEvaluationCase(caseKey: string): Promise<void> {
  await fetchJson(`/api/admin/evaluation-cases/${encodeURIComponent(caseKey)}`, { method: "DELETE" });
}

async function saveAdminEvaluationSuite(
  suite: AdminEvaluationSuiteConfig,
): Promise<AdminEvaluationSuiteConfig> {
  const response = await fetchJson<{ suite: AdminEvaluationSuiteConfig }>(
    `/api/admin/evaluation-suites/${encodeURIComponent(suite.suite_id)}`,
    { body: JSON.stringify(suite), method: "PUT" },
  );
  return response.suite;
}

async function deleteAdminEvaluationSuite(suiteId: string): Promise<void> {
  await fetchJson(`/api/admin/evaluation-suites/${encodeURIComponent(suiteId)}`, { method: "DELETE" });
}

async function saveAdminEvaluationSchedule(
  schedule: Pick<AdminEvaluationSchedule, "enabled" | "suite_id" | "interval_minutes">,
): Promise<AdminEvaluationSchedule> {
  const response = await fetchJson<{ schedule: AdminEvaluationSchedule }>("/api/admin/evaluation-schedule", {
    body: JSON.stringify(schedule),
    method: "PATCH",
  });
  return response.schedule;
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

async function upsertRagKnowledgeItem(payload: AdminRagKnowledgeItemPayload): Promise<AdminRagKnowledgeMutationResponse> {
  return fetchJson<AdminRagKnowledgeMutationResponse>("/api/admin/rag/knowledge", {
    body: JSON.stringify(payload),
    method: "POST",
  });
}

async function reviewRagKnowledgeItem(
  knowledgeId: string,
  decision: AdminRagReviewDecision,
  note: string,
): Promise<AdminRagKnowledgeMutationResponse> {
  return fetchJson<AdminRagKnowledgeMutationResponse>(`/api/admin/rag/knowledge/${encodeURIComponent(knowledgeId)}/review`, {
    body: JSON.stringify({ decision, note }),
    method: "PATCH",
  });
}

async function reviewRagDocument(
  documentId: string,
  decision: AdminRagReviewDecision,
  note: string,
): Promise<AdminRagDocumentReviewResponse> {
  return fetchJson<AdminRagDocumentReviewResponse>(`/api/admin/rag/documents/${encodeURIComponent(documentId)}/review`, {
    body: JSON.stringify({ decision, note }),
    method: "PATCH",
  });
}

async function uploadRagDocument(payload: AdminRagDocumentUploadPayload): Promise<AdminRagDocumentUploadResponse> {
  const response = await fetchJson<AdminRagDocumentUploadResponse>("/api/admin/rag/documents", {
    body: JSON.stringify(payload),
    method: "POST",
  });
  return response;
}

async function getAdminRagDocuments(
  query: string,
  offset = 0,
): Promise<Readonly<{ documents: readonly AdminRagDocument[]; pagination: Pagination }>> {
  const parameters = new URLSearchParams({ limit: "12", offset: String(offset) });
  if (query.trim()) {
    parameters.set("q", query.trim());
  }
  return fetchJson(`/api/admin/rag/documents?${parameters.toString()}`);
}

async function getAdminRagDocumentItems(documentId: string): Promise<readonly AdminRagKnowledgeItem[]> {
  const parameters = new URLSearchParams({ document_id: documentId, limit: "500" });
  const response = await fetchJson<{ knowledge_items: readonly AdminRagKnowledgeItem[] }>(
    `/api/admin/rag/knowledge?${parameters.toString()}`,
  );
  return response.knowledge_items;
}

async function deleteAdminRagDocument(documentId: string): Promise<void> {
  await fetchJson(`/api/admin/rag/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" });
}

async function deleteAdminRagKnowledgeItem(knowledgeId: string): Promise<void> {
  await fetchJson(`/api/admin/rag/knowledge/${encodeURIComponent(knowledgeId)}`, { method: "DELETE" });
}

async function getAdminSessionsPage(
  query: string,
  offset = 0,
): Promise<Readonly<{ sessions: readonly AdminSessionSummary[]; pagination: Pagination }>> {
  const parameters = new URLSearchParams({ limit: "20", offset: String(offset) });
  if (query.trim()) parameters.set("q", query.trim());
  return fetchJson(`/api/admin/sessions?${parameters.toString()}`);
}

async function getAdminReportsPage(
  query: string,
  offset = 0,
): Promise<Readonly<{ reports: readonly AdminReportSummary[]; pagination: Pagination }>> {
  const parameters = new URLSearchParams({ limit: "20", offset: String(offset) });
  if (query.trim()) parameters.set("q", query.trim());
  return fetchJson(`/api/admin/reports?${parameters.toString()}`);
}

async function getAdminCandidatesPage(
  query: string,
  offset = 0,
): Promise<Readonly<{ candidates: readonly TrainingSkillCandidateSummary[]; pagination: Pagination }>> {
  const parameters = new URLSearchParams({ limit: "20", offset: String(offset), review_status: "all" });
  if (query.trim()) parameters.set("q", query.trim());
  return fetchJson(`/api/admin/evolution/candidates?${parameters.toString()}`);
}

async function getAdminEvaluationsPage(
  query: string,
  offset = 0,
): Promise<Readonly<{ evaluations: readonly EvaluationBatchSummary[]; pagination: Pagination }>> {
  const parameters = new URLSearchParams({ limit: "20", offset: String(offset) });
  if (query.trim()) parameters.set("q", query.trim());
  return fetchJson(`/api/admin/evaluations?${parameters.toString()}`);
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

async function createAdminUser(payload: AdminUserCreatePayload): Promise<AdminManagedUser> {
  const response = await fetchJson<{ user: AdminManagedUser }>("/api/admin/users", {
    body: JSON.stringify(payload),
    method: "POST",
  });
  return response.user;
}

async function updateAdminUser(userId: string, payload: AdminUserUpdatePayload): Promise<AdminManagedUser> {
  const response = await fetchJson<{ user: AdminManagedUser }>(`/api/admin/users/${encodeURIComponent(userId)}`, {
    body: JSON.stringify(payload),
    method: "PATCH",
  });
  return response.user;
}

async function resetAdminUserPassword(userId: string, password: string): Promise<AdminManagedUser> {
  const response = await fetchJson<{ user: AdminManagedUser }>(`/api/admin/users/${encodeURIComponent(userId)}/reset-password`, {
    body: JSON.stringify({ password }),
    method: "POST",
  });
  return response.user;
}

async function deleteAdminUser(userId: string): Promise<AdminManagedUser> {
  const response = await fetchJson<{ user: AdminManagedUser }>(`/api/admin/users/${encodeURIComponent(userId)}`, {
    method: "DELETE",
  });
  return response.user;
}

async function createClassroom(payload: AdminClassroomPayload): Promise<AdminClassroom> {
  const response = await fetchJson<{ classroom: AdminClassroom }>("/api/admin/classrooms", {
    body: JSON.stringify(payload),
    method: "POST",
  });
  return response.classroom;
}

async function updateClassroom(classroomId: string, payload: AdminClassroomPayload): Promise<AdminClassroom> {
  const response = await fetchJson<{ classroom: AdminClassroom }>(`/api/admin/classrooms/${encodeURIComponent(classroomId)}`, {
    body: JSON.stringify(payload),
    method: "PUT",
  });
  return response.classroom;
}

async function deleteClassroom(classroomId: string): Promise<void> {
  await fetchJson(`/api/admin/classrooms/${encodeURIComponent(classroomId)}`, {
    method: "DELETE",
  });
}

async function importClassrooms(csvText: string, mode: "merge" | "replace"): Promise<readonly AdminClassroom[]> {
  const response = await fetchJson<{ classrooms: readonly AdminClassroom[] }>("/api/admin/classrooms/import", {
    body: JSON.stringify({ csv_text: csvText, mode }),
    method: "POST",
  });
  return response.classrooms;
}

async function transferClassroomMembers(
  sourceClassroomId: string,
  targetClassroomId: string,
  memberUserIds: readonly string[],
  mode: "copy" | "move",
): Promise<Readonly<{ source_classroom: AdminClassroom; target_classroom: AdminClassroom }>> {
  return fetchJson(`/api/admin/classrooms/${encodeURIComponent(sourceClassroomId)}/members/transfer`, {
    body: JSON.stringify({ target_classroom_id: targetClassroomId, member_user_ids: memberUserIds, mode }),
    method: "POST",
  });
}

async function getAdminAuditEvents(
  query: string,
  resourceType: string,
  offset = 0,
): Promise<Readonly<{ events: readonly AdminAuditEvent[]; pagination: Pagination }>> {
  const parameters = new URLSearchParams({ limit: "50", offset: String(offset) });
  if (query.trim()) {
    parameters.set("q", query.trim());
  }
  if (resourceType) {
    parameters.set("resource_type", resourceType);
  }
  return fetchJson(`/api/admin/audit-events?${parameters.toString()}`);
}

async function getClassroomLearningAnalytics(classroomId: string): Promise<AdminLearningAnalytics> {
  const response = await fetchJson<{ learning_analytics: AdminLearningAnalytics }>(
    `/api/admin/learning-analytics?classroom_id=${encodeURIComponent(classroomId)}`,
  );
  return response.learning_analytics;
}

async function runRetrievalEvaluation(): Promise<AdminRetrievalEval> {
  const response = await fetchJson<{ retrieval_eval: AdminRetrievalEval }>("/api/admin/retrieval-eval");
  return response.retrieval_eval;
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
  const [isClassroomBusy, setIsClassroomBusy] = useState(false);
  const [isUserBusy, setIsUserBusy] = useState(false);
  const [isRetrievalEvalBusy, setIsRetrievalEvalBusy] = useState(false);
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

  async function runEvaluation(suiteId = "default_regression") {
    setIsMutating(true);
    setErrorText("");
    try {
      await fetchJson("/api/admin/evals/run", {
        body: JSON.stringify({ batch_id: `admin_v2_manual_${Date.now()}`, suite_id: suiteId }),
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

  async function reloadAdminDirectory(): Promise<void> {
    const [usersPayload, classroomsPayload] = await Promise.all([
      fetchJson<{ users: readonly AdminManagedUser[] }>("/api/admin/users"),
      fetchJson<{ classrooms: readonly AdminClassroom[] }>("/api/admin/classrooms"),
    ]);
    setData((current) => ({
      ...current,
      users: usersPayload.users,
      classrooms: classroomsPayload.classrooms,
    }));
  }

  async function reloadResourceDirectory(): Promise<void> {
    const [casesPayload, sourcesPayload] = await Promise.all([
      fetchJson<{ cases: readonly AdminCaseSummary[] }>("/api/cases"),
      fetchJson<{ sources: readonly AdminSourceSummary[] }>("/api/admin/sources"),
    ]);
    setData((current) => ({
      ...current,
      cases: casesPayload.cases,
      sources: sourcesPayload.sources,
    }));
  }

  async function handleCreateAdminUser(payload: AdminUserCreatePayload): Promise<AdminManagedUser> {
    setIsUserBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const savedUser = await createAdminUser(payload);
      await reloadAdminDirectory();
      setStatusText(`已创建${getAdminUserRoleLabel(savedUser.role)}账号：${savedUser.email}`);
      return savedUser;
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "创建账号失败");
      throw error;
    } finally {
      setIsUserBusy(false);
    }
  }

  async function handleUpdateAdminUser(userId: string, payload: AdminUserUpdatePayload): Promise<AdminManagedUser> {
    setIsUserBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const savedUser = await updateAdminUser(userId, payload);
      await reloadAdminDirectory();
      setStatusText(`已更新账号：${savedUser.email}`);
      return savedUser;
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "更新账号失败");
      throw error;
    } finally {
      setIsUserBusy(false);
    }
  }

  async function handleResetAdminUserPassword(userId: string, password: string): Promise<AdminManagedUser> {
    setIsUserBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const savedUser = await resetAdminUserPassword(userId, password);
      setStatusText(`已重置 ${savedUser.email} 的密码，并注销该账号已有会话。`);
      return savedUser;
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "重置密码失败");
      throw error;
    } finally {
      setIsUserBusy(false);
    }
  }

  async function handleDeleteAdminUser(userId: string): Promise<void> {
    setIsUserBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const deletedUser = await deleteAdminUser(userId);
      await reloadAdminDirectory();
      setStatusText(`已撤销 ${deletedUser.email} 的登录权限；历史训练和审计证据仍保留。`);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "删除账号失败");
      throw error;
    } finally {
      setIsUserBusy(false);
    }
  }

  async function handleSaveClassroom(
    classroomId: string,
    payload: AdminClassroomPayload,
  ): Promise<AdminClassroom> {
    setIsClassroomBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const savedClassroom = classroomId
        ? await updateClassroom(classroomId, payload)
        : await createClassroom(payload);
      setData((current) => {
        const exists = current.classrooms.some(
          (classroom) => classroom.classroom_id === savedClassroom.classroom_id,
        );
        const classrooms = exists
          ? current.classrooms.map((classroom) =>
              classroom.classroom_id === savedClassroom.classroom_id
                ? savedClassroom
                : classroom,
            )
          : [...current.classrooms, savedClassroom];
        return {
          ...current,
          classrooms: [...classrooms].sort((left, right) =>
            left.name.localeCompare(right.name, "zh-CN"),
          ),
        };
      });
      setStatusText(
        classroomId
          ? `已更新班级：${savedClassroom.name}`
          : `已创建班级：${savedClassroom.name}`,
      );
      return savedClassroom;
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "保存班级失败");
      throw error;
    } finally {
      setIsClassroomBusy(false);
    }
  }

  async function handleDeleteClassroom(classroomId: string): Promise<void> {
    setIsClassroomBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      await deleteClassroom(classroomId);
      setData((current) => ({
        ...current,
        classrooms: current.classrooms.filter(
          (classroom) => classroom.classroom_id !== classroomId,
        ),
      }));
      setStatusText("班级已删除，学生账号和训练记录未受影响。");
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "删除班级失败");
      throw error;
    } finally {
      setIsClassroomBusy(false);
    }
  }

  async function handleImportClassrooms(csvText: string, mode: "merge" | "replace"): Promise<readonly AdminClassroom[]> {
    setIsClassroomBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const imported = await importClassrooms(csvText, mode);
      await reloadAdminDirectory();
      setStatusText(`已导入或更新 ${imported.length} 个班级。`);
      return imported;
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "导入班级失败");
      throw error;
    } finally {
      setIsClassroomBusy(false);
    }
  }

  async function handleTransferClassroomMembers(
    sourceClassroomId: string,
    targetClassroomId: string,
    memberUserIds: readonly string[],
    mode: "copy" | "move",
  ): Promise<void> {
    setIsClassroomBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const result = await transferClassroomMembers(sourceClassroomId, targetClassroomId, memberUserIds, mode);
      setData((current) => ({
        ...current,
        classrooms: current.classrooms.map((classroom) => {
          if (classroom.classroom_id === result.source_classroom.classroom_id) {
            return result.source_classroom;
          }
          if (classroom.classroom_id === result.target_classroom.classroom_id) {
            return result.target_classroom;
          }
          return classroom;
        }),
      }));
      setStatusText(`已${mode === "move" ? "移动" : "复制"} ${memberUserIds.length} 名学生到 ${result.target_classroom.name}。`);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "调班失败");
      throw error;
    } finally {
      setIsClassroomBusy(false);
    }
  }

  async function handleRunRetrievalEvaluation(): Promise<void> {
    setIsRetrievalEvalBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const retrievalEval = await runRetrievalEvaluation();
      setData((current) => ({ ...current, retrievalEval }));
      setStatusText("RAG 检索评测已完成。");
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "RAG 检索评测失败");
    } finally {
      setIsRetrievalEvalBusy(false);
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
      const response = await upsertRagKnowledgeItem(buildRagKnowledgePayload(item));
      const savedItem = response.knowledge_item;
      setData((current) => {
        const exists = current.knowledgeItems.some((currentItem) => currentItem.knowledge_id === savedItem.knowledge_id);
        return {
          ...current,
          documents: response.document
            ? current.documents.map((document) => (document.document_id === response.document?.document_id ? response.document : document))
            : current.documents,
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

  async function handleReviewKnowledgeItem(
    knowledgeId: string,
    decision: AdminRagReviewDecision,
    note: string,
  ): Promise<AdminRagKnowledgeItem> {
    setIsDocumentBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const response = await reviewRagKnowledgeItem(knowledgeId, decision, note);
      setData((current) => ({
        ...current,
        documents: response.document
          ? current.documents.map((document) => (document.document_id === response.document?.document_id ? response.document : document))
          : current.documents,
        knowledgeItems: current.knowledgeItems.map((item) =>
          item.knowledge_id === response.knowledge_item.knowledge_id ? response.knowledge_item : item,
        ),
      }));
      setStatusText(decision === "approved" ? "知识片段已批准并允许进入检索。" : "知识片段已拒绝，不会进入检索。");
      return response.knowledge_item;
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : decision === "approved" ? "批准知识片段失败" : "拒绝知识片段失败");
      throw error;
    } finally {
      setIsDocumentBusy(false);
    }
  }

  async function handleReviewDocument(
    documentId: string,
    decision: AdminRagReviewDecision,
    note: string,
  ): Promise<void> {
    setIsDocumentBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const response = await reviewRagDocument(documentId, decision, note);
      const reviewedKnowledgeIds = new Set(response.knowledge_items.map((item) => item.knowledge_id));
      setData((current) => ({
        ...current,
        documents: current.documents.map((document) =>
          document.document_id === response.document.document_id ? response.document : document,
        ),
        knowledgeItems: [
          ...response.knowledge_items,
          ...current.knowledgeItems.filter((item) => !reviewedKnowledgeIds.has(item.knowledge_id)),
        ],
      }));
      setStatusText(decision === "approved" ? "文档中的待审片段已批准。" : "文档中的待审片段已拒绝。");
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : decision === "approved" ? "批准文档失败" : "拒绝文档失败");
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

  async function handleDeleteRagDocument(documentId: string): Promise<void> {
    setIsDocumentBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      await deleteAdminRagDocument(documentId);
      setData((current) => ({
        ...current,
        documents: current.documents.filter((document) => document.document_id !== documentId),
        documentPagination: current.documentPagination
          ? { ...current.documentPagination, total: Math.max(0, current.documentPagination.total - 1) }
          : null,
        knowledgeItems: current.knowledgeItems.filter((item) => item.document_id !== documentId),
      }));
      setStatusText("知识库文档及其片段已删除，检索缓存已同步清理。");
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "删除知识库文档失败");
      throw error;
    } finally {
      setIsDocumentBusy(false);
    }
  }

  async function handleDeleteRagKnowledgeItem(knowledgeId: string): Promise<void> {
    setIsDocumentBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      await deleteAdminRagKnowledgeItem(knowledgeId);
      setData((current) => ({
        ...current,
        knowledgeItems: current.knowledgeItems.filter((item) => item.knowledge_id !== knowledgeId),
        knowledgePagination: current.knowledgePagination
          ? { ...current.knowledgePagination, total: Math.max(0, current.knowledgePagination.total - 1) }
          : null,
      }));
      setStatusText("知识片段已删除，后续检索不会再命中该内容。");
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "删除知识片段失败");
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
            {activeSectionId === "classes" ? (
              <ClassroomSection
                classrooms={data.classrooms}
                currentUserId={authUser.user_id}
                isBusy={isClassroomBusy}
                isUserBusy={isUserBusy}
                onCreateUser={(payload) => handleCreateAdminUser(payload)}
                onDeleteClassroom={(classroomId) => handleDeleteClassroom(classroomId)}
                onDeleteUser={(userId) => handleDeleteAdminUser(userId)}
                onImportClassrooms={(csvText, mode) => handleImportClassrooms(csvText, mode)}
                onResetUserPassword={(userId, nextPassword) => handleResetAdminUserPassword(userId, nextPassword)}
                onSaveClassroom={(classroomId, payload) => handleSaveClassroom(classroomId, payload)}
                onTransferMembers={(sourceClassroomId, targetClassroomId, memberUserIds, mode) =>
                  handleTransferClassroomMembers(sourceClassroomId, targetClassroomId, memberUserIds, mode)
                }
                onUpdateUser={(userId, payload) => handleUpdateAdminUser(userId, payload)}
                users={data.users}
              />
            ) : null}
            {activeSectionId === "resources" ? (
              <ResourcesSection
                data={data}
                isDocumentBusy={isDocumentBusy}
                onDeleteDocument={(documentId) => handleDeleteRagDocument(documentId)}
                onDeleteKnowledgeItem={(knowledgeId) => handleDeleteRagKnowledgeItem(knowledgeId)}
                onResourceDirectoryChanged={reloadResourceDirectory}
                onOpenCaseCreation={() => setIsCaseCreationOpen(true)}
                onSaveCaseFields={(caseId, payload) => handleUpdateCaseFields(caseId, payload)}
                onSaveKnowledgeItem={(item) => handleSaveKnowledgeItem(item)}
                onReviewDocument={(documentId, decision, note) => handleReviewDocument(documentId, decision, note)}
                onReviewKnowledgeItem={(knowledgeId, decision, note) => handleReviewKnowledgeItem(knowledgeId, decision, note)}
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
            {activeSectionId === "insights" ? (
              <InsightsSection data={data} />
            ) : null}
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
              <EvaluationSection
                data={data}
                isDetailBusy={isDetailBusy}
                isMutating={isMutating}
                isRetrievalEvalBusy={isRetrievalEvalBusy}
                onReadEvaluation={(batchId) => void readEvaluationDetail(batchId)}
                onRunEvaluation={(suiteId) => void runEvaluation(suiteId)}
                onRunRetrievalEvaluation={() => void handleRunRetrievalEvaluation()}
                selectedEvaluation={selectedEvaluation}
              />
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

function AccountManagementPanel({
  currentUserId,
  isBusy,
  onCreateUser,
  onDeleteUser,
  onResetUserPassword,
  onUpdateUser,
  users,
}: Readonly<{
  currentUserId: string;
  isBusy: boolean;
  onCreateUser: (payload: AdminUserCreatePayload) => Promise<AdminManagedUser>;
  onDeleteUser: (userId: string) => Promise<void>;
  onResetUserPassword: (userId: string, password: string) => Promise<AdminManagedUser>;
  onUpdateUser: (userId: string, payload: AdminUserUpdatePayload) => Promise<AdminManagedUser>;
  users: readonly AdminManagedUser[];
}>) {
  const [selectedUserId, setSelectedUserId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [emailAddress, setEmailAddress] = useState("");
  const [passwordValue, setPasswordValue] = useState("");
  const [role, setRole] = useState<AdminManagedUser["role"]>("student");
  const [accountStatus, setAccountStatus] = useState<"active" | "disabled">("active");
  const [searchText, setSearchText] = useState("");
  const [validationText, setValidationText] = useState("");
  const selectedUser = users.find((user) => user.user_id === selectedUserId) ?? null;
  const filteredUsers = useMemo(() => {
    const query = searchText.trim().toLocaleLowerCase("zh-CN");
    if (!query) {
      return users;
    }
    return users.filter((user) =>
      [user.display_name ?? "", user.email, getAdminUserRoleLabel(user.role), getAdminUserStatusLabel(user.status)]
        .join(" ")
        .toLocaleLowerCase("zh-CN")
        .includes(query),
    );
  }, [searchText, users]);

  useEffect(() => {
    if (selectedUserId && !users.some((user) => user.user_id === selectedUserId)) {
      startNewUser();
    }
  }, [selectedUserId, users]);

  function startNewUser() {
    setSelectedUserId("");
    setDisplayName("");
    setEmailAddress("");
    setPasswordValue("");
    setRole("student");
    setAccountStatus("active");
    setValidationText("");
  }

  function openUser(user: AdminManagedUser) {
    setSelectedUserId(user.user_id);
    setDisplayName(user.display_name ?? "");
    setEmailAddress(user.email);
    setPasswordValue("");
    setRole(user.role);
    setAccountStatus(user.status === "disabled" ? "disabled" : "active");
    setValidationText("");
  }

  async function handleSave() {
    const normalizedName = displayName.trim();
    const normalizedEmail = emailAddress.trim().toLocaleLowerCase("en-US");
    if (!normalizedName || !normalizedEmail.includes("@")) {
      setValidationText("请填写有效邮箱和姓名。");
      return;
    }
    if (!selectedUserId && passwordValue.length < 8) {
      setValidationText("新账号初始密码至少 8 位。");
      return;
    }
    setValidationText("");
    try {
      const savedUser = selectedUserId
        ? await onUpdateUser(selectedUserId, {
            display_name: normalizedName,
            email: normalizedEmail,
            role,
            status: accountStatus,
          })
        : await onCreateUser({
            display_name: normalizedName,
            email: normalizedEmail,
            password: passwordValue,
            role,
          });
      openUser(savedUser);
    } catch {
      // The parent dashboard owns API error rendering.
    }
  }

  async function handlePasswordReset() {
    if (!selectedUser || passwordValue.length < 8) {
      setValidationText("新密码至少 8 位。");
      return;
    }
    if (!window.confirm(`确定重置 ${selectedUser.email} 的密码并注销其全部登录会话吗？`)) {
      return;
    }
    setValidationText("");
    try {
      await onResetUserPassword(selectedUser.user_id, passwordValue);
      setPasswordValue("");
    } catch {
      // The parent dashboard owns API error rendering.
    }
  }

  async function handleDelete() {
    if (!selectedUser || !window.confirm(`确定撤销 ${selectedUser.email} 的登录权限吗？历史训练证据仍会保留。`)) {
      return;
    }
    try {
      await onDeleteUser(selectedUser.user_id);
      startNewUser();
    } catch {
      // The parent dashboard owns API error rendering.
    }
  }

  const isCurrentUser = selectedUser?.user_id === currentUserId;
  const isEnvironmentManaged = selectedUser?.managed_by_environment === true;
  const lockedIdentity = Boolean(isCurrentUser || isEnvironmentManaged);
  const roleCounts = users.reduce<Record<AdminManagedUser["role"], number>>(
    (counts, user) => ({ ...counts, [user.role]: counts[user.role] + 1 }),
    { admin: 0, student: 0, teacher: 0 },
  );

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>账号与角色</CardTitle>
          <CardDescription>管理员可创建学生、教师或管理员账号，并执行禁用、密码重置和登录权限撤销。</CardDescription>
        </div>
        <Button onClick={startNewUser} type="button" variant="secondary">
          <PlusCircle />
          新建账号
        </Button>
      </CardHeader>
      <CardContent className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="grid content-start gap-3">
          <div className="grid grid-cols-3 gap-2">
            <MiniStat label="学生" value={formatCount(roleCounts.student)} />
            <MiniStat label="教师" value={formatCount(roleCounts.teacher)} />
            <MiniStat label="管理员" value={formatCount(roleCounts.admin)} />
          </div>
          <Input
            aria-label="搜索管理账号"
            onChange={(event) => setSearchText(event.target.value)}
            placeholder="搜索姓名、邮箱、角色或状态"
            value={searchText}
          />
          <div className="grid max-h-[28rem] gap-2 overflow-y-auto pr-1">
            {filteredUsers.map((user) => (
              <button
                aria-pressed={selectedUserId === user.user_id}
                className={cn(
                  "rounded-2xl border p-3 text-left transition",
                  selectedUserId === user.user_id
                    ? "border-[#141413] bg-[#F7F4ED]"
                    : "border-[#E7E0D4] bg-white hover:bg-[#FAF9F5]",
                )}
                key={user.user_id}
                onClick={() => openUser(user)}
                type="button"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold">{user.display_name || user.email}</span>
                    <span className="mt-1 block truncate text-xs text-[#8A7D6F]">{user.email}</span>
                  </span>
                  <span className="flex flex-wrap justify-end gap-1">
                    <Badge variant="muted">{getAdminUserRoleLabel(user.role)}</Badge>
                    <Badge variant={user.status === "active" ? "success" : "warning"}>{getAdminUserStatusLabel(user.status)}</Badge>
                  </span>
                </div>
              </button>
            ))}
            {filteredUsers.length === 0 ? <EmptyText>没有匹配账号。</EmptyText> : null}
          </div>
        </div>
        <div className="grid content-start gap-4 rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold">{selectedUser ? "编辑账号" : "创建账号"}</h3>
              <p className="mt-1 text-xs text-[#6F6257]">
                {isEnvironmentManaged ? "该演示账号由运行环境托管，页面只读。" : isCurrentUser ? "当前账号只能修改显示姓名，避免自锁。" : "账号角色决定可进入的管理或教学范围。"}
              </p>
            </div>
            {selectedUser?.managed_by_environment ? <Badge variant="warning">环境托管</Badge> : null}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-2 text-sm font-medium">
              姓名
              <Input disabled={isEnvironmentManaged} maxLength={80} onChange={(event) => setDisplayName(event.target.value)} value={displayName} />
            </label>
            <label className="grid gap-2 text-sm font-medium">
              邮箱
              <Input disabled={lockedIdentity} maxLength={AUTH_EMAIL_MAX_CHARS} onChange={(event) => setEmailAddress(event.target.value)} type="email" value={emailAddress} />
            </label>
            <label className="grid gap-2 text-sm font-medium">
              角色
              <select
                className="h-10 rounded-xl border border-[#E7E0D4] bg-white px-3 text-sm outline-none disabled:opacity-60"
                disabled={lockedIdentity}
                onChange={(event) => setRole(event.target.value as AdminManagedUser["role"])}
                value={role}
              >
                <option value="student">学生</option>
                <option value="teacher">教师</option>
                <option value="admin">管理员</option>
              </select>
            </label>
            <label className="grid gap-2 text-sm font-medium">
              状态
              <select
                className="h-10 rounded-xl border border-[#E7E0D4] bg-white px-3 text-sm outline-none disabled:opacity-60"
                disabled={!selectedUser || lockedIdentity}
                onChange={(event) => setAccountStatus(event.target.value as "active" | "disabled")}
                value={accountStatus}
              >
                <option value="active">启用</option>
                <option value="disabled">禁用</option>
              </select>
            </label>
          </div>
          <label className="grid gap-2 text-sm font-medium">
            {selectedUser ? "新密码（仅重置时使用）" : "初始密码"}
            <Input
              disabled={isEnvironmentManaged || Boolean(isCurrentUser)}
              maxLength={AUTH_PASSWORD_MAX_CHARS}
              onChange={(event) => setPasswordValue(event.target.value)}
              placeholder="至少 8 位"
              type="password"
              value={passwordValue}
            />
          </label>
          {validationText ? <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{validationText}</p> : null}
          <div className="flex flex-wrap justify-between gap-2">
            <div className="flex flex-wrap gap-2">
              {selectedUser && !lockedIdentity ? (
                <Button disabled={isBusy} onClick={() => void handleDelete()} type="button" variant="destructive">
                  <Trash2 />
                  撤销登录权限
                </Button>
              ) : null}
              {selectedUser && !lockedIdentity ? (
                <Button disabled={isBusy || passwordValue.length < 8} onClick={() => void handlePasswordReset()} type="button" variant="secondary">
                  重置密码
                </Button>
              ) : null}
            </div>
            <Button disabled={isBusy || isEnvironmentManaged || !displayName.trim() || !emailAddress.trim()} onClick={() => void handleSave()} type="button">
              {isBusy ? <Loader2 className="animate-spin" /> : <ShieldCheck />}
              {selectedUser ? "保存账号" : "创建账号"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ClassroomSection({
  classrooms,
  currentUserId,
  isBusy,
  isUserBusy,
  onCreateUser,
  onDeleteClassroom,
  onDeleteUser,
  onImportClassrooms,
  onResetUserPassword,
  onSaveClassroom,
  onTransferMembers,
  onUpdateUser,
  users,
}: Readonly<{
  classrooms: readonly AdminClassroom[];
  currentUserId: string;
  isBusy: boolean;
  isUserBusy: boolean;
  onCreateUser: (payload: AdminUserCreatePayload) => Promise<AdminManagedUser>;
  onDeleteClassroom: (classroomId: string) => Promise<void>;
  onDeleteUser: (userId: string) => Promise<void>;
  onImportClassrooms: (csvText: string, mode: "merge" | "replace") => Promise<readonly AdminClassroom[]>;
  onResetUserPassword: (userId: string, password: string) => Promise<AdminManagedUser>;
  onSaveClassroom: (classroomId: string, payload: AdminClassroomPayload) => Promise<AdminClassroom>;
  onTransferMembers: (
    sourceClassroomId: string,
    targetClassroomId: string,
    memberUserIds: readonly string[],
    mode: "copy" | "move",
  ) => Promise<void>;
  onUpdateUser: (userId: string, payload: AdminUserUpdatePayload) => Promise<AdminManagedUser>;
  users: readonly AdminManagedUser[];
}>) {
  const [editingClassroomId, setEditingClassroomId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedMemberIds, setSelectedMemberIds] = useState<readonly string[]>([]);
  const [teacherUserId, setTeacherUserId] = useState("");
  const [classroomStatus, setClassroomStatus] = useState<AdminClassroom["status"]>("active");
  const [userSearchText, setUserSearchText] = useState("");
  const [validationText, setValidationText] = useState("");
  const [csvText, setCsvText] = useState("班级名称,班级说明,负责教师邮箱,学生邮箱,状态\n");
  const [importMode, setImportMode] = useState<"merge" | "replace">("merge");
  const [transferMemberIds, setTransferMemberIds] = useState<readonly string[]>([]);
  const [transferTargetId, setTransferTargetId] = useState("");
  const [transferMode, setTransferMode] = useState<"copy" | "move">("move");
  const eligibleUsers = useMemo(
    () => users.filter((user) => user.eligible_for_classroom && !user.is_admin),
    [users],
  );
  const eligibleTeachers = useMemo(
    () => users.filter((user) => user.eligible_as_teacher),
    [users],
  );
  const filteredUsers = useMemo(() => {
    const query = userSearchText.trim().toLocaleLowerCase("zh-CN");
    if (!query) {
      return eligibleUsers;
    }
    return eligibleUsers.filter((user) =>
      [user.display_name ?? "", user.email]
        .join(" ")
        .toLocaleLowerCase("zh-CN")
        .includes(query),
    );
  }, [eligibleUsers, userSearchText]);
  const assignedMembershipCount = classrooms.reduce(
    (total, classroom) => total + classroom.member_count,
    0,
  );

  function startNewClassroom() {
    setEditingClassroomId("");
    setName("");
    setDescription("");
    setSelectedMemberIds([]);
    setTeacherUserId("");
    setClassroomStatus("active");
    setTransferMemberIds([]);
    setTransferTargetId("");
    setUserSearchText("");
    setValidationText("");
  }

  function openClassroom(classroom: AdminClassroom) {
    setEditingClassroomId(classroom.classroom_id);
    setName(classroom.name);
    setDescription(classroom.description);
    setSelectedMemberIds(classroom.member_user_ids);
    setTeacherUserId(classroom.teacher_user_id || "");
    setClassroomStatus(classroom.status || "active");
    setTransferMemberIds([]);
    setTransferTargetId("");
    setUserSearchText("");
    setValidationText("");
  }

  function toggleMember(userId: string) {
    setSelectedMemberIds((current) =>
      current.includes(userId)
        ? current.filter((memberUserId) => memberUserId !== userId)
        : [...current, userId],
    );
  }

  async function handleSave() {
    const normalizedName = name.trim();
    if (!normalizedName) {
      setValidationText("请填写班级名称。");
      return;
    }
    setValidationText("");
    try {
      const savedClassroom = await onSaveClassroom(editingClassroomId, {
        description: description.trim(),
        member_user_ids: selectedMemberIds,
        name: normalizedName,
        status: classroomStatus,
        teacher_user_id: teacherUserId,
      });
      openClassroom(savedClassroom);
    } catch {
      // The parent dashboard renders the API error without duplicating it here.
    }
  }

  async function handleDelete() {
    if (!editingClassroomId) {
      return;
    }
    const confirmed = window.confirm(
      `确定删除班级“${name || "未命名班级"}”吗？学生账号和训练记录不会被删除。`,
    );
    if (!confirmed) {
      return;
    }
    try {
      await onDeleteClassroom(editingClassroomId);
      startNewClassroom();
    } catch {
      // The parent dashboard renders the API error without duplicating it here.
    }
  }

  async function handleImport() {
    if (!csvText.trim()) {
      setValidationText("请粘贴带表头的班级 CSV。");
      return;
    }
    setValidationText("");
    try {
      await onImportClassrooms(csvText, importMode);
    } catch {
      // The parent dashboard owns API error rendering.
    }
  }

  function toggleTransferMember(userId: string) {
    setTransferMemberIds((current) =>
      current.includes(userId) ? current.filter((item) => item !== userId) : [...current, userId],
    );
  }

  async function handleTransfer() {
    if (!editingClassroomId || !transferTargetId || transferMemberIds.length === 0) {
      setValidationText("请选择源班级成员和目标班级。");
      return;
    }
    setValidationText("");
    try {
      await onTransferMembers(editingClassroomId, transferTargetId, transferMemberIds, transferMode);
      if (transferMode === "move") {
        setSelectedMemberIds((current) => current.filter((userId) => !transferMemberIds.includes(userId)));
      }
      setTransferMemberIds([]);
    } catch {
      // The parent dashboard owns API error rendering.
    }
  }

  return (
    <div className="grid gap-4">
      <AccountManagementPanel
        currentUserId={currentUserId}
        isBusy={isUserBusy}
        onCreateUser={onCreateUser}
        onDeleteUser={onDeleteUser}
        onResetUserPassword={onResetUserPassword}
        onUpdateUser={onUpdateUser}
        users={users}
      />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <SectionIntro
          description="创建真实教学班，指定负责教师、纳入学生、归档旧班级，并支持 CSV 导入和批量调班。"
          eyebrow="教学组织"
          title="班级与成员"
        />
        <Button onClick={startNewClassroom} type="button">
          <PlusCircle />
          新建班级
        </Button>
      </div>
      <div className="grid gap-4 md:grid-cols-4">
        <MetricCard icon={<School />} label="班级" value={formatCount(classrooms.length)} helper="可持续编辑" />
        <MetricCard icon={<UsersRound />} label="可选学生" value={formatCount(eligibleUsers.length)} helper="管理员账号已排除" />
        <MetricCard icon={<GraduationCap />} label="可选教师" value={formatCount(eligibleTeachers.length)} helper="可设置班级负责人" />
        <MetricCard icon={<GraduationCap />} label="成员关系" value={formatCount(assignedMembershipCount)} helper="支持学生加入多个班" />
      </div>
      <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <Card>
          <CardHeader>
            <CardTitle>班级列表</CardTitle>
            <CardDescription>选择班级后可修改名称、说明和成员。</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3">
              {classrooms.map((classroom) => (
                <button
                  aria-pressed={editingClassroomId === classroom.classroom_id}
                  className={cn(
                    "w-full rounded-2xl border p-4 text-left transition",
                    editingClassroomId === classroom.classroom_id
                      ? "border-[#141413] bg-[#F7F4ED] shadow-sm"
                      : "border-[#E7E0D4] bg-white hover:bg-[#FAF9F5]",
                  )}
                  key={classroom.classroom_id}
                  onClick={() => openClassroom(classroom)}
                  type="button"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold">{classroom.name}</p>
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-[#6F6257]">
                        {classroom.description || "未填写班级说明"}
                      </p>
                    </div>
                    <span className="flex flex-wrap justify-end gap-1">
                      <Badge variant={classroom.status === "active" ? "success" : "warning"}>
                        {classroom.status === "active" ? "进行中" : "已归档"}
                      </Badge>
                      <Badge variant="muted">{formatCount(classroom.member_count)} 人</Badge>
                    </span>
                  </div>
                  <p className="mt-3 text-xs text-[#8A7D6F]">
                    负责人：{classroom.teacher?.display_name || classroom.teacher?.email || "未指定"} · 更新于 {formatDateTime(classroom.updated_at)}
                  </p>
                </button>
              ))}
              {classrooms.length === 0 ? <EmptyText>暂无班级。点击“新建班级”开始设置。</EmptyText> : null}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex-row items-start justify-between gap-4">
            <div>
              <CardTitle>{editingClassroomId ? "编辑班级" : "创建班级"}</CardTitle>
              <CardDescription>保存后成员关系会持久化，并可用于班级学情筛选。</CardDescription>
            </div>
            <Badge variant={editingClassroomId ? "warning" : "muted"}>
              {formatCount(selectedMemberIds.length)} 名成员
            </Badge>
          </CardHeader>
          <CardContent className="grid gap-4">
            <label className="grid gap-2 text-sm font-medium">
              班级名称
              <Input
                maxLength={CLASSROOM_NAME_MAX_CHARS}
                onChange={(event) => setName(event.target.value)}
                placeholder="例如：2026 级临床一班"
                value={name}
              />
            </label>
            <label className="grid gap-2 text-sm font-medium">
              班级说明
              <textarea
                className="min-h-24 w-full resize-y rounded-xl border border-[#E7E0D4] bg-white px-3 py-2 text-sm text-[#141413] outline-none transition placeholder:text-[#9A8B7D] focus:border-[#141413] focus:ring-2 focus:ring-[#141413]/10"
                maxLength={CLASSROOM_DESCRIPTION_MAX_CHARS}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="填写训练周期、课程或本阶段重点"
                value={description}
              />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="grid gap-2 text-sm font-medium">
                负责教师
                <select
                  className="h-10 rounded-xl border border-[#E7E0D4] bg-white px-3 text-sm outline-none"
                  onChange={(event) => setTeacherUserId(event.target.value)}
                  value={teacherUserId}
                >
                  <option value="">暂不指定</option>
                  {eligibleTeachers.map((teacher) => (
                    <option key={teacher.user_id} value={teacher.user_id}>
                      {teacher.display_name || teacher.email}（{teacher.email}）
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-2 text-sm font-medium">
                班级状态
                <select
                  className="h-10 rounded-xl border border-[#E7E0D4] bg-white px-3 text-sm outline-none"
                  onChange={(event) => setClassroomStatus(event.target.value as AdminClassroom["status"])}
                  value={classroomStatus}
                >
                  <option value="active">进行中</option>
                  <option value="archived">已归档</option>
                </select>
              </label>
            </div>
            <div className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h3 className="text-sm font-semibold">选择学生</h3>
                  <p className="mt-1 text-xs text-[#6F6257]">只显示现有学生账号，管理员不能被纳入班级。</p>
                </div>
                <Input
                  aria-label="搜索可纳入班级的学生"
                  className="sm:max-w-64"
                  onChange={(event) => setUserSearchText(event.target.value)}
                  placeholder="搜索姓名或邮箱"
                  value={userSearchText}
                />
              </div>
              <div className="mt-4 grid max-h-72 gap-2 overflow-y-auto pr-1">
                {filteredUsers.map((user) => {
                  const checked = selectedMemberIds.includes(user.user_id);
                  return (
                    <label
                      className={cn(
                        "flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-3 transition",
                        checked ? "border-[#141413] bg-white" : "border-[#E7E0D4] bg-[#FAF9F5] hover:bg-white",
                      )}
                      key={user.user_id}
                    >
                      <input
                        checked={checked}
                        className="size-4 accent-[#141413]"
                        onChange={() => toggleMember(user.user_id)}
                        type="checkbox"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold">{user.display_name || user.email}</span>
                        <span className="mt-1 block truncate text-xs text-[#8A7D6F]">{user.email}</span>
                      </span>
                      <Badge variant={checked ? "success" : "muted"}>{checked ? "已纳入" : "未选择"}</Badge>
                    </label>
                  );
                })}
                {filteredUsers.length === 0 ? (
                  <EmptyText>
                    {eligibleUsers.length === 0
                      ? "当前没有可纳入的学生账号；学生登录或由部署管理员预置后会出现在这里。"
                      : "没有匹配的学生。"}
                  </EmptyText>
                ) : null}
              </div>
            </div>
            {validationText ? <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{validationText}</p> : null}
            <div className="flex flex-wrap justify-between gap-3">
              <div>
                {editingClassroomId ? (
                  <Button disabled={isBusy} onClick={() => void handleDelete()} type="button" variant="destructive">
                    <Trash2 />
                    删除班级
                  </Button>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-2">
                <Button disabled={isBusy} onClick={startNewClassroom} type="button" variant="secondary">
                  清空
                </Button>
                <Button disabled={isBusy || !name.trim()} onClick={() => void handleSave()} type="button">
                  {isBusy ? <Loader2 className="animate-spin" /> : <School />}
                  {editingClassroomId ? "保存班级" : "创建班级"}
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>批量导入与调班</CardTitle>
          <CardDescription>CSV 会先完整校验再一次性写入；调班只改变成员关系，不影响学生账号和历史训练。</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 xl:grid-cols-2">
          <div className="grid content-start gap-3 rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold">CSV 导入</h3>
                <p className="mt-1 text-xs text-[#6F6257]">支持中文表头；同名班级可合并或替换成员。</p>
              </div>
              <select
                className="h-9 rounded-xl border border-[#E7E0D4] bg-white px-3 text-sm outline-none"
                onChange={(event) => setImportMode(event.target.value as "merge" | "replace")}
                value={importMode}
              >
                <option value="merge">合并现有成员</option>
                <option value="replace">替换现有成员</option>
              </select>
            </div>
            <textarea
              className="min-h-52 w-full resize-y rounded-xl border border-[#E7E0D4] bg-white px-3 py-2 font-mono text-xs leading-5 outline-none"
              onChange={(event) => setCsvText(event.target.value)}
              spellCheck={false}
              value={csvText}
            />
            <Button disabled={isBusy || !csvText.trim()} onClick={() => void handleImport()} type="button">
              {isBusy ? <Loader2 className="animate-spin" /> : <FileText />}
              校验并导入
            </Button>
          </div>
          <div className="grid content-start gap-3 rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
            <div>
              <h3 className="text-sm font-semibold">批量调班</h3>
              <p className="mt-1 text-xs text-[#6F6257]">
                {editingClassroomId ? `当前源班级：${name}` : "请先从班级列表选择源班级。"}
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="grid gap-2 text-sm font-medium">
                目标班级
                <select
                  className="h-10 rounded-xl border border-[#E7E0D4] bg-white px-3 text-sm outline-none disabled:opacity-60"
                  disabled={!editingClassroomId}
                  onChange={(event) => setTransferTargetId(event.target.value)}
                  value={transferTargetId}
                >
                  <option value="">请选择</option>
                  {classrooms
                    .filter((classroom) => classroom.classroom_id !== editingClassroomId)
                    .map((classroom) => (
                      <option key={classroom.classroom_id} value={classroom.classroom_id}>{classroom.name}</option>
                    ))}
                </select>
              </label>
              <label className="grid gap-2 text-sm font-medium">
                操作方式
                <select
                  className="h-10 rounded-xl border border-[#E7E0D4] bg-white px-3 text-sm outline-none disabled:opacity-60"
                  disabled={!editingClassroomId}
                  onChange={(event) => setTransferMode(event.target.value as "copy" | "move")}
                  value={transferMode}
                >
                  <option value="move">移动（离开源班）</option>
                  <option value="copy">复制（保留源班）</option>
                </select>
              </label>
            </div>
            <div className="grid max-h-48 gap-2 overflow-y-auto pr-1">
              {(classrooms.find((classroom) => classroom.classroom_id === editingClassroomId)?.members ?? []).map((member) => (
                <label className="flex cursor-pointer items-center gap-3 rounded-xl border border-[#E7E0D4] bg-white px-3 py-2" key={member.user_id}>
                  <input
                    checked={transferMemberIds.includes(member.user_id)}
                    className="size-4 accent-[#141413]"
                    onChange={() => toggleTransferMember(member.user_id)}
                    type="checkbox"
                  />
                  <span className="min-w-0 flex-1 truncate text-sm">{member.display_name || member.email}</span>
                </label>
              ))}
              {editingClassroomId && selectedMemberIds.length === 0 ? <EmptyText>源班级暂无可调成员。</EmptyText> : null}
            </div>
            <Button
              disabled={isBusy || !editingClassroomId || !transferTargetId || transferMemberIds.length === 0}
              onClick={() => void handleTransfer()}
              type="button"
            >
              {isBusy ? <Loader2 className="animate-spin" /> : <UsersRound />}
              {transferMode === "move" ? "移动" : "复制"} {transferMemberIds.length} 名学生
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function ResourcesSection({
  data,
  isDocumentBusy,
  onDeleteDocument,
  onDeleteKnowledgeItem,
  onOpenCaseCreation,
  onResourceDirectoryChanged,
  onReviewDocument,
  onReviewKnowledgeItem,
  onSaveCaseFields,
  onSaveKnowledgeItem,
  onSaveRubricItem,
  onSetDocumentEnabled,
  onUploadDocument,
}: Readonly<{
  data: DashboardData;
  isDocumentBusy: boolean;
  onDeleteDocument: (documentId: string) => Promise<void>;
  onDeleteKnowledgeItem: (knowledgeId: string) => Promise<void>;
  onOpenCaseCreation: () => void;
  onResourceDirectoryChanged: () => Promise<void>;
  onReviewDocument: (documentId: string, decision: AdminRagReviewDecision, note: string) => Promise<void>;
  onReviewKnowledgeItem: (knowledgeId: string, decision: AdminRagReviewDecision, note: string) => Promise<AdminRagKnowledgeItem>;
  onSaveCaseFields: (caseId: string, payload: AdminCaseFieldUpdatePayload) => Promise<AdminCaseRaw>;
  onSaveKnowledgeItem: (item: AdminRagKnowledgeItem) => Promise<AdminRagKnowledgeItem>;
  onSaveRubricItem: (rubricId: string, itemId: string, description: string) => Promise<AdminRubricDetail>;
  onSetDocumentEnabled: (documentId: string, enabled: boolean) => void;
  onUploadDocument: (payload: AdminRagDocumentUploadPayload) => Promise<AdminRagDocumentUploadResponse>;
}>) {
  const [openDocumentId, setOpenDocumentId] = useState("");
  const [openDocumentItems, setOpenDocumentItems] = useState<readonly AdminRagKnowledgeItem[]>([]);
  const [visibleDocuments, setVisibleDocuments] = useState<readonly AdminRagDocument[]>(data.documents);
  const [documentPagination, setDocumentPagination] = useState<Pagination | null>(data.documentPagination);
  const [documentQuery, setDocumentQuery] = useState("");
  const [isDocumentListLoading, setIsDocumentListLoading] = useState(false);
  const [documentListError, setDocumentListError] = useState("");
  const [openCaseDetail, setOpenCaseDetail] = useState<AdminCaseRaw | null>(null);
  const [editingCase, setEditingCase] = useState<AdminCaseRaw | null>(null);
  const [rubricDetail, setRubricDetail] = useState<AdminRubricDetail | null>(null);
  const [versionedCaseId, setVersionedCaseId] = useState("");
  const [caseDetailErrorText, setCaseDetailErrorText] = useState("");
  const [loadingCaseId, setLoadingCaseId] = useState("");
  const [loadingRubricCaseId, setLoadingRubricCaseId] = useState("");
  const activeDocumentId = openDocumentId;
  const openDocument = visibleDocuments.find((document) => document.document_id === openDocumentId)
    ?? data.documents.find((document) => document.document_id === openDocumentId)
    ?? null;

  useEffect(() => {
    setVisibleDocuments(data.documents);
    setDocumentPagination(data.documentPagination);
  }, [data.documentPagination, data.documents]);

  async function loadDocumentPage(offset: number, query = documentQuery) {
    setIsDocumentListLoading(true);
    setDocumentListError("");
    try {
      const response = await getAdminRagDocuments(query, offset);
      setVisibleDocuments(response.documents);
      setDocumentPagination(response.pagination);
      setOpenDocumentId("");
      setOpenDocumentItems([]);
    } catch (error) {
      setDocumentListError(error instanceof Error ? error.message : "读取知识库文档失败");
    } finally {
      setIsDocumentListLoading(false);
    }
  }

  async function handleOpenDocument(documentId: string) {
    setOpenDocumentId(documentId);
    setOpenDocumentItems([]);
    setDocumentListError("");
    try {
      const items = await getAdminRagDocumentItems(documentId);
      setOpenDocumentItems([...items].sort((left, right) => (left.chunk_index ?? 0) - (right.chunk_index ?? 0)));
    } catch (error) {
      setOpenDocumentId("");
      setDocumentListError(error instanceof Error ? error.message : "读取文档片段失败");
    }
  }

  async function handleDeleteDocument(documentId: string) {
    if (!window.confirm("确定删除这份知识库文档及全部片段吗？该操作会留下审计记录。")) return;
    await onDeleteDocument(documentId);
    const currentOffset = documentPagination?.offset ?? 0;
    const fallbackOffset = visibleDocuments.length === 1 ? Math.max(0, currentOffset - 12) : currentOffset;
    await loadDocumentPage(fallbackOffset);
  }

  async function handleDeleteKnowledgeItem(knowledgeId: string) {
    if (!window.confirm("确定删除该知识片段吗？删除后不再参与检索。")) return;
    await onDeleteKnowledgeItem(knowledgeId);
    setOpenDocumentItems((current) => current.filter((item) => item.knowledge_id !== knowledgeId));
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
        <MetricCard
          icon={<Brain />}
          label="知识库文档"
          value={formatCount(data.documentPagination?.total ?? data.documents.length)}
          helper={`${visibleDocuments.reduce((total, document) => total + (document.pending_review_chunk_count ?? 0), 0)} 个当前页片段待审`}
        />
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
                    <Button onClick={() => setVersionedCaseId(caseItem.case_id)} size="sm" type="button" variant="secondary">
                      完整版本
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
      <SourceLedger onChanged={onResourceDirectoryChanged} sources={data.sources} />
      <Card>
        <CardHeader>
          <CardTitle>知识库文档</CardTitle>
          <CardDescription>教师上传的全局或病例知识库；只有“已启用 + 已批准”的片段才会进入 Agent 检索。</CardDescription>
        </CardHeader>
        <CardContent>
          <DocumentUploadPanel
            cases={data.cases}
            documents={visibleDocuments}
            isSaving={isDocumentBusy}
            onUploadDocument={onUploadDocument}
            sources={data.sources}
          />
          <form
            className="mb-3 flex flex-col gap-2 sm:flex-row"
            onSubmit={(event) => {
              event.preventDefault();
              void loadDocumentPage(0);
            }}
          >
            <Input
              aria-label="搜索知识库文档"
              onChange={(event) => setDocumentQuery(event.target.value)}
              placeholder="按标题、文件名、病例或来源搜索"
              value={documentQuery}
            />
            <Button disabled={isDocumentListLoading} type="submit" variant="secondary">
              {isDocumentListLoading ? <Loader2 className="animate-spin" /> : null}
              搜索
            </Button>
          </form>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-[#8A7D6F]">
                <tr className="border-b border-[#E7E0D4]">
                  <th className="py-3 pr-4">文档</th>
                  <th className="py-3 pr-4">范围</th>
                  <th className="py-3 pr-4">关联病例</th>
                  <th className="py-3 pr-4">适用阶段</th>
                  <th className="py-3 pr-4">片段</th>
                  <th className="py-3 pr-4">状态</th>
                  <th className="py-3 pr-4">操作</th>
                </tr>
              </thead>
              <tbody>
                {visibleDocuments.map((document) => (
                  <tr className="border-b border-[#F0E8DC]" key={document.document_id}>
                    <td className="py-3 pr-4 font-medium">{document.title || document.filename || document.document_id}</td>
                    <td className="py-3 pr-4 text-[#6F6257]">{document.scope === "case" ? "病例知识库" : "全局知识库"}</td>
                    <td className="py-3 pr-4 text-[#6F6257]">{document.case_title || "全部病例"}</td>
                    <td className="py-3 pr-4 text-[#6F6257]">{joinText(document.stage_scope_labels ?? document.stage_scope, "全部训练阶段")}</td>
                    <td className="py-3 pr-4 text-[#6F6257]">{document.chunk_count ?? "-"}</td>
                    <td className="py-3 pr-4">
                      <div className="flex flex-wrap gap-2">
                        <Badge variant={document.enabled ? "success" : "muted"}>{document.enabled ? "已启用" : "未启用"}</Badge>
                        <Badge variant={getKnowledgeReviewBadgeVariant(document.review_status)}>{getKnowledgeReviewStatusLabel(document.review_status)}</Badge>
                      </div>
                      <p className="mt-1 text-xs text-[#8A7D6F]">
                        可检索 {document.indexable_chunk_count ?? 0} · 待审 {document.pending_review_chunk_count ?? 0} · 已拒绝 {document.rejected_chunk_count ?? 0}
                      </p>
                    </td>
                    <td className="py-3 pr-4">
                      <div className="flex flex-wrap gap-2">
                        <Button onClick={() => void handleOpenDocument(document.document_id)} size="sm" variant={activeDocumentId === document.document_id ? "default" : "secondary"}>
                          查看内容
                        </Button>
                        <Button disabled={isDocumentBusy} onClick={() => onSetDocumentEnabled(document.document_id, !document.enabled)} size="sm" variant={document.enabled ? "outline" : "secondary"}>
                          {document.enabled ? "停用文档" : "启用文档"}
                        </Button>
                        {(document.pending_review_chunk_count ?? 0) > 0 ? (
                          <>
                            <Button
                              disabled={isDocumentBusy}
                              onClick={() => void onReviewDocument(document.document_id, "approved", "整份文档批量审核")}
                              size="sm"
                              variant="secondary"
                            >
                              批准待审片段
                            </Button>
                            <Button
                              disabled={isDocumentBusy}
                              onClick={() => void onReviewDocument(document.document_id, "rejected", "整份文档批量退回")}
                              size="sm"
                              variant="outline"
                            >
                              退回待审片段
                            </Button>
                          </>
                        ) : null}
                        <Button
                          disabled={isDocumentBusy}
                          onClick={() => void handleDeleteDocument(document.document_id)}
                          size="sm"
                          variant="destructive"
                        >
                          <Trash2 />
                          删除
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {documentListError ? <p className="mt-3 text-sm text-red-700">{documentListError}</p> : null}
          {visibleDocuments.length === 0 ? <EmptyText>暂无匹配的知识库文档。</EmptyText> : null}
          <PaginationControls
            isLoading={isDocumentListLoading}
            onPageChange={(offset) => void loadDocumentPage(offset)}
            pagination={documentPagination}
          />
        </CardContent>
      </Card>
      {openDocument ? (
        <KnowledgeContentModal
          document={openDocument}
          isSaving={isDocumentBusy}
          items={openDocumentItems}
          onClose={() => setOpenDocumentId("")}
          onDeleteKnowledgeItem={handleDeleteKnowledgeItem}
          onReviewKnowledgeItem={async (knowledgeId, decision, note) => {
            const updated = await onReviewKnowledgeItem(knowledgeId, decision, note);
            setOpenDocumentItems((current) => current.map((item) => (item.knowledge_id === knowledgeId ? updated : item)));
            return updated;
          }}
          onSaveKnowledgeItem={async (item) => {
            const updated = await onSaveKnowledgeItem(item);
            setOpenDocumentItems((current) => current.map((currentItem) => (currentItem.knowledge_id === updated.knowledge_id ? updated : currentItem)));
            return updated;
          }}
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
      {versionedCaseId ? (
        <CaseAssetVersionModal
          caseId={versionedCaseId}
          onChanged={onResourceDirectoryChanged}
          onClose={() => setVersionedCaseId("")}
        />
      ) : null}
    </div>
  );
}

function buildAdminSourceDraft(source?: AdminSourceSummary): AdminSourcePayload {
  return {
    allowed_usage: source?.allowed_usage ?? [],
    attribution_required: source?.attribution_required ?? true,
    change_note: "",
    data_type: source?.data_type ?? source?.source_type ?? "clinical_reference",
    last_reviewed_at: source?.last_reviewed_at ?? new Date().toISOString().slice(0, 10),
    license: source?.license ?? "",
    medical_review_note: "",
    review_basis: source?.review_basis ?? "",
    review_interval_days: source?.review_interval_days ?? 365,
    risk_note: source?.risk_note ?? "",
    search_aliases: source?.search_aliases ?? [],
    source_id: source?.source_id ?? "",
    source_name: source?.source_name ?? source?.title ?? "",
    source_status: (["active", "superseded", "inactive"].includes(source?.source_status ?? "")
      ? source?.source_status
      : "active") as AdminSourcePayload["source_status"],
    source_url: source?.source_url ?? "",
    source_version: source?.source_version ?? "",
    superseded_by: source?.superseded_by ?? "",
    transformation: source?.transformation ?? "",
  };
}

function SourceLedger({
  onChanged,
  sources,
}: Readonly<{
  onChanged: () => Promise<void>;
  sources: readonly AdminSourceSummary[];
}>) {
  const currentCount = sources.filter((source) => source.freshness_status === "current").length;
  const reviewDueCount = sources.filter((source) => source.freshness_status === "review_due").length;
  const unverifiedCount = sources.filter((source) => source.freshness_status === "unverified").length;
  const supersededCount = sources.filter((source) => source.freshness_status === "superseded").length;
  const [selectedSourceId, setSelectedSourceId] = useState("");
  const [draft, setDraft] = useState<AdminSourcePayload>(() => buildAdminSourceDraft());
  const [searchText, setSearchText] = useState("");
  const [versions, setVersions] = useState<readonly AdminAssetVersion[]>([]);
  const [diff, setDiff] = useState<AdminAssetDiff | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [localErrorText, setLocalErrorText] = useState("");
  const [localStatusText, setLocalStatusText] = useState("");
  const filteredSources = useMemo(() => {
    const query = searchText.trim().toLocaleLowerCase("zh-CN");
    if (!query) {
      return sources;
    }
    return sources.filter((source) =>
      [source.source_id, source.source_name ?? "", source.source_type ?? "", source.source_version ?? ""]
        .join(" ")
        .toLocaleLowerCase("zh-CN")
        .includes(query),
    );
  }, [searchText, sources]);

  function updateDraft<Key extends keyof AdminSourcePayload>(key: Key, value: AdminSourcePayload[Key]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function startNewSource() {
    setSelectedSourceId("");
    setDraft(buildAdminSourceDraft());
    setVersions([]);
    setDiff(null);
    setLocalErrorText("");
    setLocalStatusText("");
  }

  async function loadVersions(sourceId: string) {
    const assetPath = `/api/admin/sources/${encodeURIComponent(sourceId)}`;
    const nextVersions = await getAdminAssetVersions(assetPath);
    setVersions(nextVersions);
    if (nextVersions.length >= 2) {
      setDiff(await getAdminAssetDiff(assetPath, nextVersions[1].version, nextVersions[0].version));
    } else {
      setDiff(null);
    }
  }

  async function openSource(source: AdminSourceSummary) {
    setSelectedSourceId(source.source_id);
    setDraft(buildAdminSourceDraft(source));
    setLocalErrorText("");
    setLocalStatusText("");
    setIsBusy(true);
    try {
      await loadVersions(source.source_id);
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "读取来源版本失败");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleSave() {
    if (!draft.source_id.trim() || !draft.source_name.trim() || !draft.data_type.trim()) {
      setLocalErrorText("来源 ID、名称和类型不能为空。");
      return;
    }
    setIsBusy(true);
    setLocalErrorText("");
    setLocalStatusText("");
    try {
      const saved = await createOrUpdateAdminSource(
        {
          ...draft,
          source_id: draft.source_id.trim(),
          source_name: draft.source_name.trim(),
          data_type: draft.data_type.trim(),
        },
        selectedSourceId,
      );
      setSelectedSourceId(saved.source_id);
      setDraft(buildAdminSourceDraft(saved));
      await onChanged();
      await loadVersions(saved.source_id);
      setLocalStatusText(selectedSourceId ? "来源已更新，并生成新版本。" : "来源已创建并进入台账。");
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "保存来源失败");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleReview() {
    if (!selectedSourceId || !draft.review_basis.trim() || !draft.last_reviewed_at) {
      setLocalErrorText("复核需要填写复核日期和依据。");
      return;
    }
    setIsBusy(true);
    setLocalErrorText("");
    try {
      const saved = await reviewAdminSource(selectedSourceId, {
        last_reviewed_at: draft.last_reviewed_at,
        medical_review_note: draft.medical_review_note,
        review_basis: draft.review_basis,
        review_interval_days: draft.review_interval_days,
        source_status: draft.source_status,
        superseded_by: draft.superseded_by,
      });
      setDraft(buildAdminSourceDraft(saved));
      await onChanged();
      await loadVersions(selectedSourceId);
      setLocalStatusText("来源复核已记录。");
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "来源复核失败");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleDeactivate() {
    if (!selectedSourceId || !window.confirm("确定停用该来源吗？它将不再可用于新病例或新知识，但历史引用仍保留。")) {
      return;
    }
    setIsBusy(true);
    setLocalErrorText("");
    try {
      const saved = await deactivateAdminSource(selectedSourceId);
      setDraft(buildAdminSourceDraft(saved));
      await onChanged();
      await loadVersions(selectedSourceId);
      setLocalStatusText("来源已停用，历史引用不受影响。");
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "停用来源失败");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleRollback(version: number) {
    if (!selectedSourceId || !window.confirm(`确定把来源恢复到版本 ${version} 吗？当前状态会先保留在历史中。`)) {
      return;
    }
    setIsBusy(true);
    setLocalErrorText("");
    try {
      const response = await rollbackAdminAsset<{ source: AdminSourceSummary }>(
        `/api/admin/sources/${encodeURIComponent(selectedSourceId)}`,
        version,
        `从管理端恢复到版本 ${version}`,
      );
      setDraft(buildAdminSourceDraft(response.source));
      await onChanged();
      await loadVersions(selectedSourceId);
      setLocalStatusText(`已恢复到版本 ${version}，并生成新的回滚版本。`);
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "来源回滚失败");
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>来源台账、复核与版本</CardTitle>
          <CardDescription>可新增、修订、复核、停用、查看差异和回滚；“复核有效”仍不等同于真实临床有效性认证。</CardDescription>
        </div>
        <Button onClick={startNewSource} type="button" variant="secondary"><PlusCircle />新增来源</Button>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MiniStat label="复核有效" value={formatCount(currentCount)} />
          <MiniStat label="到期待复核" value={formatCount(reviewDueCount)} />
          <MiniStat label="未记录复核" value={formatCount(unverifiedCount)} />
          <MiniStat label="已被新来源替代" value={formatCount(supersededCount)} />
        </div>
        <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
          <div className="grid content-start gap-3">
            <Input onChange={(event) => setSearchText(event.target.value)} placeholder="搜索来源名称、ID、类型或版本" value={searchText} />
            <div className="grid max-h-[42rem] gap-2 overflow-y-auto pr-1">
              {filteredSources.map((source) => (
                <button
                  aria-pressed={selectedSourceId === source.source_id}
                  className={cn("rounded-2xl border p-3 text-left", selectedSourceId === source.source_id ? "border-[#141413] bg-[#F7F4ED]" : "border-[#E7E0D4] bg-white hover:bg-[#FAF9F5]")}
                  key={source.source_id}
                  onClick={() => void openSource(source)}
                  type="button"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-semibold">{source.title || source.source_name || source.source_id}</span>
                      <span className="mt-1 block truncate text-xs text-[#8A7D6F]">{source.source_id} · {source.source_version || "未记录版本"}</span>
                    </span>
                    <Badge variant={getSourceFreshnessBadgeVariant(source.freshness_status)}>{source.freshness_label || getSourceFreshnessLabel(source.freshness_status)}</Badge>
                  </div>
                </button>
              ))}
              {filteredSources.length === 0 ? <EmptyText>暂无匹配来源。</EmptyText> : null}
            </div>
          </div>
          <div className="grid content-start gap-4 rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">{selectedSourceId ? "编辑来源" : "新增来源"}</h3>
              {selectedSourceId ? <Badge variant="muted">{versions.length} 个版本</Badge> : null}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <FormField label="来源 ID"><Input disabled={Boolean(selectedSourceId)} onChange={(event) => updateDraft("source_id", event.target.value)} value={draft.source_id} /></FormField>
              <FormField label="来源名称"><Input onChange={(event) => updateDraft("source_name", event.target.value)} value={draft.source_name} /></FormField>
              <FormField label="类型"><Input onChange={(event) => updateDraft("data_type", event.target.value)} value={draft.data_type} /></FormField>
              <FormField label="来源版本"><Input onChange={(event) => updateDraft("source_version", event.target.value)} value={draft.source_version} /></FormField>
              <FormField label="原始链接"><Input onChange={(event) => updateDraft("source_url", event.target.value)} value={draft.source_url} /></FormField>
              <FormField label="许可"><Input onChange={(event) => updateDraft("license", event.target.value)} value={draft.license} /></FormField>
              <FormField label="最近复核"><Input onChange={(event) => updateDraft("last_reviewed_at", event.target.value)} type="date" value={draft.last_reviewed_at} /></FormField>
              <FormField label="复核周期（天）"><Input min={1} onChange={(event) => updateDraft("review_interval_days", Math.max(1, Number(event.target.value) || 365))} type="number" value={draft.review_interval_days} /></FormField>
              <FormField label="状态">
                <SelectInput optionLabels={{ active: "启用", inactive: "停用", superseded: "已被替代" }} options={["active", "superseded", "inactive"]} value={draft.source_status} onChange={(value) => updateDraft("source_status", value as AdminSourcePayload["source_status"])} />
              </FormField>
              <FormField label="替代来源">
                <SelectInput optionLabels={{ "": "无", ...Object.fromEntries(sources.filter((source) => source.source_id !== draft.source_id).map((source) => [source.source_id, source.title || source.source_id])) }} options={["", ...sources.filter((source) => source.source_id !== draft.source_id).map((source) => source.source_id)]} value={draft.superseded_by} onChange={(value) => updateDraft("superseded_by", value)} />
              </FormField>
            </div>
            <FormField label="允许用途（逗号分隔）"><Input onChange={(event) => updateDraft("allowed_usage", toTokenList(event.target.value))} value={draft.allowed_usage.join(", ")} /></FormField>
            <FormField label="搜索别名（逗号分隔）"><Input onChange={(event) => updateDraft("search_aliases", toTokenList(event.target.value))} value={draft.search_aliases.join(", ")} /></FormField>
            <FormField label="转换方式"><TextAreaInput onChange={(value) => updateDraft("transformation", value)} value={draft.transformation} /></FormField>
            <FormField label="风险说明"><TextAreaInput onChange={(value) => updateDraft("risk_note", value)} value={draft.risk_note} /></FormField>
            <FormField label="复核依据"><TextAreaInput onChange={(value) => updateDraft("review_basis", value)} value={draft.review_basis} /></FormField>
            <div className="grid gap-3 sm:grid-cols-2">
              <FormField label="变更说明"><Input onChange={(event) => updateDraft("change_note", event.target.value)} value={draft.change_note} /></FormField>
              <FormField label="医学审核备注"><Input onChange={(event) => updateDraft("medical_review_note", event.target.value)} value={draft.medical_review_note} /></FormField>
            </div>
            <label className="flex items-center gap-2 text-sm"><input checked={draft.attribution_required} onChange={(event) => updateDraft("attribution_required", event.target.checked)} type="checkbox" />使用时必须标注来源</label>
            {localErrorText ? <p className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{localErrorText}</p> : null}
            {localStatusText ? <p className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{localStatusText}</p> : null}
            <div className="flex flex-wrap justify-between gap-2">
              <div className="flex flex-wrap gap-2">
                {selectedSourceId ? <Button disabled={isBusy || draft.source_status === "inactive"} onClick={() => void handleDeactivate()} type="button" variant="destructive">停用来源</Button> : null}
                {selectedSourceId ? <Button disabled={isBusy} onClick={() => void handleReview()} type="button" variant="secondary">记录复核</Button> : null}
              </div>
              <Button disabled={isBusy} onClick={() => void handleSave()} type="button">{isBusy ? <Loader2 className="animate-spin" /> : <FileText />}{selectedSourceId ? "保存新版本" : "创建来源"}</Button>
            </div>
            {versions.length > 0 ? (
              <details className="rounded-xl border border-[#E7E0D4] bg-white p-3">
                <summary className="cursor-pointer text-sm font-semibold">版本历史与最近差异</summary>
                <div className="mt-3 grid gap-2">
                  {versions.map((version) => (
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#F0E8DC] px-3 py-2 text-xs" key={version.version}>
                      <span>v{version.version} · {version.change_note || "无说明"} · {version.actor_email} · {formatDateTime(version.created_at)}</span>
                      <Button disabled={isBusy || version.version === versions[0]?.version} onClick={() => void handleRollback(version.version)} size="sm" type="button" variant="outline">恢复此版</Button>
                    </div>
                  ))}
                  {diff ? <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-xl bg-[#FAF9F5] p-3 text-[11px]">{diff.changes.map((change) => `${change.path}: ${JSON.stringify(change.before)} → ${JSON.stringify(change.after)}`).join("\n") || "最近两个版本内容相同"}</pre> : null}
                </div>
              </details>
            ) : null}
          </div>
        </div>
      </CardContent>
    </Card>
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
  const selectableSources = useMemo(() => getSelectableSources(sources), [sources]);
  const defaultCaseId = cases[0]?.case_id ?? "";
  const defaultSourceId = selectableSources[0]?.source_id ?? "";
  const [scope, setScope] = useState("case");
  const [caseId, setCaseId] = useState(defaultCaseId);
  const [sourceId, setSourceId] = useState(defaultSourceId);
  const [visibility, setVisibility] = useState("pre_submit_safe");
  const [tags, setTags] = useState("teacher_document");
  const [allowedAgents, setAllowedAgents] = useState<readonly string[]>(["coach", "reflection", "skill_generation", "skill_approval"]);
  const [stageScope, setStageScope] = useState<readonly string[]>(["any"]);
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
        stage_scope: stageScope,
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

  function toggleStage(stageId: string) {
    setStageScope((current) => {
      if (stageId === "any") {
        return ["any"];
      }
      const stageSpecific = current.filter((item) => item !== "any");
      const next = stageSpecific.includes(stageId)
        ? stageSpecific.filter((item) => item !== stageId)
        : [...stageSpecific, stageId];
      return next.length > 0 ? next : ["any"];
    });
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
              optionLabels={{ "": "不绑定来源", ...Object.fromEntries(selectableSources.map((source) => [source.source_id, source.title || source.source_id])) }}
              options={["", ...selectableSources.map((source) => source.source_id)]}
              value={sourceId}
              onChange={setSourceId}
            />
          </FormField>
          <FormField label="标签">
            <Input onChange={(event) => setTags(event.target.value)} placeholder="例如 acute_abdomen,teaching" value={tags} />
          </FormField>
          <FormField label="文档文件">
            <Input
              accept=".md,.markdown,.txt,.text,.csv,.pdf,.docx,.pptx,.html,.htm,.png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff"
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
        <div className="rounded-2xl border border-[#E7E0D4] bg-white p-3">
          <p className="mb-2 text-sm font-semibold">适用训练阶段</p>
          <div className="flex flex-wrap items-center gap-2">
            {RAG_STAGE_OPTIONS.map((stageId) => (
              <label className="flex items-center gap-2 rounded-xl border border-[#E7E0D4] bg-[#FAF9F5] px-3 py-2 text-sm" key={stageId}>
                <input checked={stageScope.includes(stageId)} onChange={() => toggleStage(stageId)} type="checkbox" />
                {RAG_STAGE_LABELS[stageId]}
              </label>
            ))}
          </div>
          <p className="mt-2 text-xs text-[#8A7D6F]">选择“全部训练阶段”时跨阶段可用；选择具体阶段后，只在对应训练节点进入 Agent 检索。</p>
        </div>
        {localErrorText ? <p className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{localErrorText}</p> : null}
        {localStatusText ? <p className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{localStatusText}</p> : null}
      </div>
    </details>
  );
}

function CaseAssetVersionModal({
  caseId,
  onChanged,
  onClose,
}: Readonly<{
  caseId: string;
  onChanged: () => Promise<void>;
  onClose: () => void;
}>) {
  const [assets, setAssets] = useState<AdminCaseAssets | null>(null);
  const [caseJson, setCaseJson] = useState("");
  const [rubricJson, setRubricJson] = useState("");
  const [versions, setVersions] = useState<readonly AdminAssetVersion[]>([]);
  const [diff, setDiff] = useState<AdminAssetDiff | null>(null);
  const [changeNote, setChangeNote] = useState("");
  const [reviewStatus, setReviewStatus] = useState<"unreviewed" | "approved" | "rejected">("unreviewed");
  const [medicalReviewNote, setMedicalReviewNote] = useState("");
  const [isBusy, setIsBusy] = useState(true);
  const [localErrorText, setLocalErrorText] = useState("");
  const [localStatusText, setLocalStatusText] = useState("");
  const assetPath = `/api/admin/cases/${encodeURIComponent(caseId)}`;

  async function loadCaseVersionState() {
    const [nextAssets, nextVersions] = await Promise.all([
      getAdminCaseAssets(caseId),
      getAdminAssetVersions(assetPath),
    ]);
    setAssets(nextAssets);
    setCaseJson(JSON.stringify(nextAssets.case, null, 2));
    setRubricJson(JSON.stringify(nextAssets.rubric, null, 2));
    setVersions(nextVersions);
    setReviewStatus(
      ["approved", "rejected"].includes(nextAssets.current_version.review_status)
        ? nextAssets.current_version.review_status as "approved" | "rejected"
        : "unreviewed",
    );
    setMedicalReviewNote(nextAssets.current_version.review_note ?? "");
    if (nextVersions.length >= 2) {
      setDiff(await getAdminAssetDiff(assetPath, nextVersions[1].version, nextVersions[0].version));
    } else {
      setDiff(null);
    }
  }

  useEffect(() => {
    let isMounted = true;
    setIsBusy(true);
    setLocalErrorText("");
    void loadCaseVersionState()
      .catch((error) => {
        if (isMounted) {
          setLocalErrorText(error instanceof Error ? error.message : "读取病例版本失败");
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsBusy(false);
        }
      });
    return () => {
      isMounted = false;
    };
  }, [caseId]);

  async function handleSave() {
    if (!changeNote.trim()) {
      setLocalErrorText("保存完整病例前必须填写变更说明。");
      return;
    }
    let parsedCase: unknown;
    let parsedRubric: unknown;
    try {
      parsedCase = JSON.parse(caseJson);
      parsedRubric = JSON.parse(rubricJson);
    } catch (error) {
      setLocalErrorText(error instanceof Error ? `JSON 格式错误：${error.message}` : "JSON 格式错误");
      return;
    }
    if (!parsedCase || typeof parsedCase !== "object" || Array.isArray(parsedCase) || !parsedRubric || typeof parsedRubric !== "object" || Array.isArray(parsedRubric)) {
      setLocalErrorText("病例和 Rubric 都必须是 JSON 对象。");
      return;
    }
    setIsBusy(true);
    setLocalErrorText("");
    setLocalStatusText("");
    try {
      await replaceAdminCaseAssets(caseId, {
        case: parsedCase as AdminCaseRaw,
        change_note: changeNote.trim(),
        medical_review_note: medicalReviewNote.trim(),
        review_status: reviewStatus,
        rubric: parsedRubric as Record<string, unknown>,
      });
      await onChanged();
      await loadCaseVersionState();
      setChangeNote("");
      setLocalStatusText("完整病例与 Rubric 已校验并保存为新版本。");
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "保存完整病例失败");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleReview(nextStatus: "approved" | "rejected") {
    if (!medicalReviewNote.trim()) {
      setLocalErrorText("医学审核必须填写审核备注。");
      return;
    }
    setIsBusy(true);
    setLocalErrorText("");
    try {
      await reviewAdminCase(caseId, nextStatus, medicalReviewNote.trim());
      await loadCaseVersionState();
      setLocalStatusText(nextStatus === "approved" ? "医学审核已通过并留痕。" : "病例已退回并留痕。");
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "病例审核失败");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleRollback(version: number) {
    if (!window.confirm(`确定恢复病例版本 ${version} 吗？当前内容会保留在版本历史中。`)) {
      return;
    }
    setIsBusy(true);
    setLocalErrorText("");
    try {
      await rollbackAdminAsset<AdminCaseAssets>(assetPath, version, `从管理端恢复到版本 ${version}`);
      await onChanged();
      await loadCaseVersionState();
      setLocalStatusText(`已恢复版本 ${version}，并生成新的回滚版本。`);
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "病例回滚失败");
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <div aria-label="完整病例版本管理" aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4" role="dialog">
      <div className="grid max-h-[94vh] w-full max-w-7xl grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-3xl border border-[#E7E0D4] bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-[#E7E0D4] px-6 py-5">
          <div>
            <p className="text-xs font-semibold text-[#AE5630]">受控病例资产</p>
            <h3 className="mt-1 text-2xl font-semibold">完整病例、Rubric 与版本</h3>
            <p className="mt-2 text-sm text-[#6F6257]">{caseId} · 保存前后端会重新验证完整模型及 Case/Rubric 配对关系。</p>
          </div>
          <Button onClick={onClose} variant="secondary">关闭</Button>
        </div>
        <div className="min-h-0 overflow-y-auto p-6">
          {isBusy && !assets ? <p className="flex items-center gap-2 text-sm text-[#6F6257]"><Loader2 className="animate-spin" />读取病例资产...</p> : null}
          {assets ? (
            <div className="grid gap-4">
              <div className="grid gap-4 lg:grid-cols-2">
                <FormField label="完整病例 JSON">
                  <textarea className="min-h-[32rem] w-full resize-y rounded-xl border border-[#E7E0D4] bg-[#111827] p-3 font-mono text-xs leading-5 text-[#E5E7EB] outline-none" onChange={(event) => setCaseJson(event.target.value)} spellCheck={false} value={caseJson} />
                </FormField>
                <FormField label="完整 Rubric JSON">
                  <textarea className="min-h-[32rem] w-full resize-y rounded-xl border border-[#E7E0D4] bg-[#111827] p-3 font-mono text-xs leading-5 text-[#E5E7EB] outline-none" onChange={(event) => setRubricJson(event.target.value)} spellCheck={false} value={rubricJson} />
                </FormField>
              </div>
              <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">这是高级完整编辑入口，适合修改隐藏病史、查体/检查结果、诊断证据、评分维度和权重。后端验证失败时不会写入任一文件。</p>
              <div className="grid gap-3 lg:grid-cols-[1fr_12rem_1fr]">
                <FormField label="变更说明"><Input onChange={(event) => setChangeNote(event.target.value)} placeholder="说明为什么修改病例事实或评分" value={changeNote} /></FormField>
                <FormField label="版本审核状态"><SelectInput optionLabels={{ approved: "已审核通过", rejected: "已退回", unreviewed: "待审核" }} options={["unreviewed", "approved", "rejected"]} value={reviewStatus} onChange={(value) => setReviewStatus(value as typeof reviewStatus)} /></FormField>
                <FormField label="医学审核备注"><Input onChange={(event) => setMedicalReviewNote(event.target.value)} value={medicalReviewNote} /></FormField>
              </div>
              {localErrorText ? <p className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{localErrorText}</p> : null}
              {localStatusText ? <p className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{localStatusText}</p> : null}
              <div className="flex flex-wrap justify-between gap-2">
                <div className="flex flex-wrap gap-2">
                  <Button disabled={isBusy || !medicalReviewNote.trim()} onClick={() => void handleReview("approved")} type="button" variant="secondary">审核通过</Button>
                  <Button disabled={isBusy || !medicalReviewNote.trim()} onClick={() => void handleReview("rejected")} type="button" variant="outline">退回修订</Button>
                </div>
                <Button disabled={isBusy || !changeNote.trim()} onClick={() => void handleSave()} type="button">{isBusy ? <Loader2 className="animate-spin" /> : <FileText />}校验并保存新版本</Button>
              </div>
              <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
                <Card>
                  <CardHeader><CardTitle>版本历史</CardTitle></CardHeader>
                  <CardContent className="grid max-h-80 gap-2 overflow-y-auto">
                    {versions.map((version) => (
                      <div className="rounded-xl border border-[#E7E0D4] p-3 text-xs" key={version.version}>
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <span><strong>v{version.version}</strong> · {getAdminAssetReviewLabel(version.review_status)}</span>
                          <Button disabled={isBusy || version.version === versions[0]?.version} onClick={() => void handleRollback(version.version)} size="sm" type="button" variant="outline">恢复此版</Button>
                        </div>
                        <p className="mt-2 text-[#6F6257]">{version.change_note || "无变更说明"}</p>
                        <p className="mt-1 text-[#8A7D6F]">{version.actor_email} · {formatDateTime(version.created_at)}</p>
                      </div>
                    ))}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle>最近两个版本差异</CardTitle></CardHeader>
                  <CardContent>
                    <div className="max-h-80 overflow-auto rounded-xl bg-[#FAF9F5] p-3 font-mono text-[11px] leading-5">
                      {diff?.changes.length ? diff.changes.map((change) => (
                        <p className="border-b border-[#E7E0D4] py-2" key={`${change.path}-${change.change}`}><strong>{change.path}</strong><br />{JSON.stringify(change.before)} → {JSON.stringify(change.after)}</p>
                      )) : "尚无可比较的版本差异。"}
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>
          ) : null}
        </div>
        <div className="flex justify-end border-t border-[#E7E0D4] px-6 py-4"><Button onClick={onClose} variant="secondary">关闭</Button></div>
      </div>
    </div>
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
  onDeleteKnowledgeItem,
  onReviewKnowledgeItem,
  onSaveKnowledgeItem,
}: Readonly<{
  document: AdminRagDocument;
  isSaving: boolean;
  items: readonly AdminRagKnowledgeItem[];
  onClose: () => void;
  onDeleteKnowledgeItem: (knowledgeId: string) => Promise<void>;
  onReviewKnowledgeItem: (knowledgeId: string, decision: AdminRagReviewDecision, note: string) => Promise<AdminRagKnowledgeItem>;
  onSaveKnowledgeItem: (item: AdminRagKnowledgeItem) => Promise<AdminRagKnowledgeItem>;
}>) {
  const [selectedKnowledgeId, setSelectedKnowledgeId] = useState(items[0]?.knowledge_id ?? "");
  const selectedItem = items.find((item) => item.knowledge_id === selectedKnowledgeId) ?? items[0] ?? null;
  const [draftTitle, setDraftTitle] = useState(selectedItem?.title || selectedItem?.section_title || "");
  const [draftText, setDraftText] = useState(selectedItem?.text || "");
  const [reviewNote, setReviewNote] = useState(selectedItem?.review_note || "");
  const [localErrorText, setLocalErrorText] = useState("");

  useEffect(() => {
    setSelectedKnowledgeId(items[0]?.knowledge_id ?? "");
  }, [document.document_id]);

  useEffect(() => {
    setDraftTitle(selectedItem?.title || selectedItem?.section_title || "");
    setDraftText(selectedItem?.text || "");
    setReviewNote(selectedItem?.review_note || "");
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

  async function handleReview(decision: AdminRagReviewDecision) {
    if (!selectedItem) {
      return;
    }
    try {
      const reviewedItem = await onReviewKnowledgeItem(selectedItem.knowledge_id, decision, reviewNote.trim());
      setSelectedKnowledgeId(reviewedItem.knowledge_id);
      setReviewNote(reviewedItem.review_note || "");
      setLocalErrorText("");
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "审核失败");
    }
  }

  async function handleDelete() {
    if (!selectedItem) return;
    const deletedId = selectedItem.knowledge_id;
    try {
      await onDeleteKnowledgeItem(deletedId);
      setSelectedKnowledgeId(items.find((item) => item.knowledge_id !== deletedId)?.knowledge_id ?? "");
      setLocalErrorText("");
    } catch (error) {
      setLocalErrorText(error instanceof Error ? error.message : "删除失败");
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
                    <span className={cn("mt-1 block text-xs", isActive ? "text-white/70" : "text-[#8A7D6F]")}>{getKnowledgeReviewStatusLabel(item.review_status)}</span>
                  </button>
                );
              })}
              {items.length === 0 ? <EmptyText>该文档暂无可编辑片段。</EmptyText> : null}
            </div>
          </aside>
          <section className="min-h-0 overflow-y-auto p-5">
            {selectedItem ? (
              <div className="grid gap-4">
                <div className="grid gap-3 md:grid-cols-5">
                  <MiniStat label="可见性" value={getKnowledgeVisibilityLabel(selectedItem.visibility)} />
                  <MiniStat label="可用模块" value={joinText(toTokenList(selectedItem.allowed_agents), "未配置")} />
                  <MiniStat label="适用阶段" value={joinText(selectedItem.stage_scope_labels ?? selectedItem.stage_scope, "全部训练阶段")} />
                  <MiniStat label="准入状态" value={getKnowledgeReviewStatusLabel(selectedItem.review_status)} />
                  <MiniStat label="更新时间" value={formatDateTime(selectedItem.updated_at ?? "")} />
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
                    <p className="text-sm font-semibold">质量提示</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {toTextList(selectedItem.quality_warnings).map((warning) => (
                        <Badge key={warning} variant="muted">{getKnowledgeQualityLabel(warning)}</Badge>
                      ))}
                      {toTextList(selectedItem.quality_warnings).length === 0 ? <Badge variant="success">无质量警告</Badge> : null}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
                    <p className="text-sm font-semibold">风险标记</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {toTextList(selectedItem.risk_flags).map((risk) => (
                        <Badge key={risk} variant="warning">{getKnowledgeRiskLabel(risk)}</Badge>
                      ))}
                      {toTextList(selectedItem.risk_flags).length === 0 ? <Badge variant="success">未发现风险</Badge> : null}
                    </div>
                  </div>
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
                <label className="grid gap-2 text-sm font-semibold">
                  审核说明
                  <textarea
                    className="min-h-24 resize-y rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] px-4 py-3 text-sm leading-6 outline-none transition focus:border-[#AE5630] focus:bg-white"
                    maxLength={1000}
                    onChange={(event) => setReviewNote(event.target.value)}
                    placeholder="说明批准用途或退回原因"
                    value={reviewNote}
                  />
                </label>
                {selectedItem.reviewed_by ? (
                  <p className="text-xs text-[#6F6257]">
                    最近审核：{selectedItem.reviewed_by} · {formatDateTime(selectedItem.reviewed_at || "")}
                  </p>
                ) : null}
                {localErrorText ? <p className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{localErrorText}</p> : null}
                <div className="flex flex-wrap justify-end gap-2">
                  <Button disabled={isSaving} onClick={() => void handleDelete()} variant="destructive">
                    <Trash2 />
                    删除片段
                  </Button>
                  <Button onClick={onClose} variant="secondary">
                    取消
                  </Button>
                  <Button disabled={isSaving} onClick={() => void handleReview("rejected")} variant="outline">
                    退回片段
                  </Button>
                  <Button disabled={isSaving} onClick={() => void handleReview("approved")} variant="secondary">
                    批准片段
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
  const selectableSources = useMemo(() => getSelectableSources(sources), [sources]);
  const [draft, setDraft] = useState<CaseCreationDraft>(() => buildDefaultCaseCreationDraft(selectableSources, cases));
  const [result, setResult] = useState<AdminCaseImportStatus | null>(null);
  const [localErrorText, setLocalErrorText] = useState("");

  useEffect(() => {
    setDraft((current) => ({
      ...current,
      caseId: generateSequentialCaseId(cases),
      sourceId: current.sourceId || selectableSources[0]?.source_id || "",
    }));
  }, [cases, selectableSources]);

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
                  <SelectInput value={draft.sourceId} onChange={(value) => updateDraft("sourceId", value)} options={selectableSources.map((source) => source.source_id)} optionLabels={Object.fromEntries(selectableSources.map((source) => [source.source_id, source.title || source.source_id]))} />
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
  const [sessions, setSessions] = useState<readonly AdminSessionSummary[]>(data.sessions);
  const [sessionPagination, setSessionPagination] = useState<Pagination | null>(data.sessionPagination);
  const [sessionQuery, setSessionQuery] = useState("");
  const [reports, setReports] = useState<readonly AdminReportSummary[]>(data.reports);
  const [reportPagination, setReportPagination] = useState<Pagination | null>(data.reportPagination);
  const [reportQuery, setReportQuery] = useState("");
  const [activeSessionId, setActiveSessionId] = useState(selectedSession?.session_id ?? "");
  const [isListLoading, setIsListLoading] = useState(false);
  const [listError, setListError] = useState("");

  useEffect(() => {
    setSessions(data.sessions);
    setSessionPagination(data.sessionPagination);
    setReports(data.reports);
    setReportPagination(data.reportPagination);
  }, [data.reportPagination, data.reports, data.sessionPagination, data.sessions]);

  const activeSession = sessions.find((session) => session.session_id === activeSessionId)
    ?? (selectedSession?.session_id === activeSessionId ? selectedSession : null)
    ?? sessions[0]
    ?? null;
  const hasSelectedReport = activeSession
    ? activeSession.stage === "feedback" || reports.some((report) => report.session_id === activeSession.session_id)
    : false;
  const humanisticReportStats = selectedReport ? getHumanisticReportStats(selectedReport) : null;
  const teacherInterventionEvents = selectedEvents
    .map((event) => getTeacherInterventionEvent(event))
    .filter((event): event is TeacherInterventionEvent => event !== null);

  async function loadSessions(offset: number, query = sessionQuery) {
    setIsListLoading(true);
    setListError("");
    try {
      const response = await getAdminSessionsPage(query, offset);
      setSessions(response.sessions);
      setSessionPagination(response.pagination);
      const firstSessionId = response.sessions[0]?.session_id ?? "";
      setActiveSessionId(firstSessionId);
      if (firstSessionId) onSelectSession(firstSessionId);
    } catch (error) {
      setListError(error instanceof Error ? error.message : "读取训练记录失败");
    } finally {
      setIsListLoading(false);
    }
  }

  async function loadReports(offset: number, query = reportQuery) {
    setIsListLoading(true);
    setListError("");
    try {
      const response = await getAdminReportsPage(query, offset);
      setReports(response.reports);
      setReportPagination(response.pagination);
    } catch (error) {
      setListError(error instanceof Error ? error.message : "读取报告中心失败");
    } finally {
      setIsListLoading(false);
    }
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <Card>
        <CardHeader>
          <CardTitle>训练 Session</CardTitle>
          <CardDescription>表格化展示训练证据，点击一行查看详情。</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="mb-3 flex gap-2" onSubmit={(event) => { event.preventDefault(); void loadSessions(0); }}>
            <Input aria-label="搜索训练记录" onChange={(event) => setSessionQuery(event.target.value)} placeholder="搜索病例、学生、阶段或 Session ID" value={sessionQuery} />
            <Button disabled={isListLoading} type="submit" variant="secondary">搜索</Button>
          </form>
          <SessionTable
            onSelectSession={(sessionId) => {
              setActiveSessionId(sessionId);
              onSelectSession(sessionId);
            }}
            selectedSessionId={activeSession?.session_id ?? ""}
            sessions={sessions}
          />
          <PaginationControls isLoading={isListLoading} onPageChange={(offset) => void loadSessions(offset)} pagination={sessionPagination} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Session 详情</CardTitle>
          <CardDescription>选择左侧 Session 后读取报告、日志和 Skill 应用证据。</CardDescription>
        </CardHeader>
        <CardContent>
          {activeSession ? (
            <div className="grid gap-4">
              <div className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
                <p className="text-xs font-semibold text-[#AE5630]">{activeSession.stage_label ?? activeSession.stage}</p>
                <h3 className="mt-1 text-xl font-semibold">{activeSession.case_title || activeSession.case_id}</h3>
                <p className="mt-2 text-sm text-[#6F6257]">学员：{activeSession.student_id}</p>
                <p className="mt-1 text-sm text-[#6F6257]">更新：{formatDateTime(activeSession.updated_at)}</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button disabled={isDetailBusy || !hasSelectedReport} onClick={() => onReadReport(activeSession.session_id)} size="sm">
                    {isDetailBusy ? <Loader2 className="animate-spin" /> : <FileText />}
                    {hasSelectedReport ? "读取报告" : "暂无报告"}
                  </Button>
                  <Button disabled={isDetailBusy} onClick={() => onReadEvents(activeSession.session_id)} size="sm" variant="secondary">
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
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h4 className="text-sm font-semibold">教师智能体介入轨迹</h4>
                      <p className="mt-1 text-xs leading-5 text-[#6F6257]">展示何时静默、观察、提示或阻断，以及本轮实际调用的 Skill 和资料来源。</p>
                    </div>
                    <Badge variant="muted">{formatCount(teacherInterventionEvents.length)} 条决策</Badge>
                  </div>
                  {teacherInterventionEvents.length > 0 ? (
                    <div className="mt-3 grid gap-2">
                      {teacherInterventionEvents.slice(0, 10).map((decision, index) => (
                        <article className="rounded-xl border border-[#E7E0D4] bg-[#FAF9F5] p-3" key={`${decision.createdAt}-${decision.actionType}-${index}`}>
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex flex-wrap items-center gap-2">
                              <Badge variant={getTeacherInterventionBadgeVariant(decision.mode)}>{getTeacherInterventionModeLabel(decision.mode)}</Badge>
                              <span className="text-sm font-semibold">{getTeacherActionTypeLabel(decision.actionType)}</span>
                              <span className="text-xs text-[#8A7D6F]">{getProcessingStatusLabel(decision.processingStatus)}</span>
                            </div>
                            <span className="text-xs text-[#8A7D6F]">{formatDateTime(decision.createdAt)}</span>
                          </div>
                          <p className="mt-2 text-sm leading-6 text-[#3F372F]">{decision.reason || "本轮已完成介入判断。"}</p>
                          {decision.hintEmitted && decision.hint ? (
                            <p className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-900">可见提示：{decision.hint}</p>
                          ) : null}
                          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[#6F6257]">
                            {decision.selectedSkillIds.length > 0 ? <span>调用 Skill：{decision.selectedSkillIds.join("、")}</span> : <span>本轮未调用 Skill</span>}
                            <span>资料来源：{formatCount(decision.sourceReferences.length)} 条</span>
                            {decision.reasonCode ? <span>原因编码：{decision.reasonCode}</span> : null}
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <EmptyText>日志中暂无教师智能体介入决策。</EmptyText>
                  )}
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
                {(activeSession.active_skill_context?.skipped_reasons ?? []).slice(0, 4).map((reason) => (
                  <div className="rounded-xl border border-[#E7E0D4] bg-white p-3 text-sm" key={`${reason.skill_id}-${reason.reason}`}>
                    <p className="font-medium">{reason.reason_label || reason.reason}</p>
                    <p className="mt-1 text-xs leading-5 text-[#6F6257]">{reason.reason_description || "暂无说明"}</p>
                  </div>
                ))}
                {(activeSession.active_skill_context?.skipped_reasons ?? []).length === 0 ? <EmptyText>本轮暂无 Skill 跳过记录。</EmptyText> : null}
              </div>
            </div>
          ) : (
            <EmptyText>暂无可查看的训练 Session。</EmptyText>
          )}
        </CardContent>
      </Card>
      <Card className="xl:col-span-2">
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>报告中心</CardTitle>
            <CardDescription>集中检索训练报告、打开完整报告，并按当前查询范围导出 JSON 或 CSV。</CardDescription>
          </div>
          <Badge variant="muted">{formatCount(reportPagination?.total ?? reports.length)} 份</Badge>
        </CardHeader>
        <CardContent>
          <form className="mb-3 flex flex-col gap-2 sm:flex-row" onSubmit={(event) => { event.preventDefault(); void loadReports(0); }}>
            <Input aria-label="搜索训练报告" onChange={(event) => setReportQuery(event.target.value)} placeholder="搜索病例、学生、报告或 Session ID" value={reportQuery} />
            <Button disabled={isListLoading} type="submit" variant="secondary">搜索报告</Button>
            <Button onClick={() => window.location.assign(`/api/admin/reports/export?format=csv&q=${encodeURIComponent(reportQuery.trim())}`)} type="button" variant="secondary">导出 CSV</Button>
            <Button onClick={() => window.location.assign(`/api/admin/reports/export?format=json&q=${encodeURIComponent(reportQuery.trim())}`)} type="button" variant="outline">导出 JSON</Button>
          </form>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-[#8A7D6F]">
                <tr className="border-b border-[#E7E0D4]">
                  <th className="py-3 pr-4">病例</th>
                  <th className="py-3 pr-4">学生</th>
                  <th className="py-3 pr-4">总分</th>
                  <th className="py-3 pr-4">训练缺口</th>
                  <th className="py-3 pr-4">操作</th>
                </tr>
              </thead>
              <tbody>
                {reports.map((report) => (
                  <tr className="border-b border-[#F0E8DC]" key={report.report_id || report.session_id}>
                    <td className="py-3 pr-4"><p className="font-semibold">{report.case_title || report.case_id}</p><p className="mt-1 text-xs text-[#8A7D6F]">{report.session_id}</p></td>
                    <td className="py-3 pr-4 text-[#6F6257]">{report.student_id}</td>
                    <td className="py-3 pr-4"><Badge variant="success">{report.total_score} 分</Badge></td>
                    <td className="py-3 pr-4 text-[#6F6257]">{report.missed_item_labels?.slice(0, 3).join("、") || "未记录"}</td>
                    <td className="py-3 pr-4"><Button disabled={isDetailBusy} onClick={() => { setActiveSessionId(report.session_id); onSelectSession(report.session_id); onReadReport(report.session_id); }} size="sm" variant="secondary">查看完整报告</Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {reports.length === 0 ? <EmptyText>暂无匹配的训练报告。</EmptyText> : null}
          {listError ? <p className="mt-3 text-sm text-red-700">{listError}</p> : null}
          <PaginationControls isLoading={isListLoading} onPageChange={(offset) => void loadReports(offset)} pagination={reportPagination} />
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
  const [selectedClassroomId, setSelectedClassroomId] = useState("");
  const [classroomAnalytics, setClassroomAnalytics] = useState<AdminLearningAnalytics | null>(null);
  const [isClassroomAnalyticsLoading, setIsClassroomAnalyticsLoading] = useState(false);
  const [classroomAnalyticsError, setClassroomAnalyticsError] = useState("");
  const classroomAnalyticsRequestRef = useRef(0);
  const missedItems = toInsightDisplayItems(data.insights?.frequent_missed_items, "未覆盖训练点");
  const turnPatterns = toInsightDisplayItems(data.insights?.frequent_turn_patterns, "训练模式");
  const humanisticInsight = data.insights?.humanistic_communication;
  const learningAnalytics = selectedClassroomId ? classroomAnalytics : data.learningAnalytics;

  useEffect(() => {
    if (
      selectedClassroomId
      && !data.classrooms.some((classroom) => classroom.classroom_id === selectedClassroomId)
    ) {
      setSelectedClassroomId("");
      setClassroomAnalytics(null);
      setClassroomAnalyticsError("");
    }
  }, [data.classrooms, selectedClassroomId]);

  async function handleClassroomAnalyticsSelection(classroomId: string) {
    setSelectedClassroomId(classroomId);
    setClassroomAnalyticsError("");
    const requestId = classroomAnalyticsRequestRef.current + 1;
    classroomAnalyticsRequestRef.current = requestId;
    if (!classroomId) {
      setClassroomAnalytics(null);
      setIsClassroomAnalyticsLoading(false);
      return;
    }
    setIsClassroomAnalyticsLoading(true);
    try {
      const nextAnalytics = await getClassroomLearningAnalytics(classroomId);
      if (classroomAnalyticsRequestRef.current === requestId) {
        setClassroomAnalytics(nextAnalytics);
      }
    } catch (error) {
      if (classroomAnalyticsRequestRef.current === requestId) {
        setClassroomAnalytics(null);
        setClassroomAnalyticsError(error instanceof Error ? error.message : "读取班级学情失败");
      }
    } finally {
      if (classroomAnalyticsRequestRef.current === requestId) {
        setIsClassroomAnalyticsLoading(false);
      }
    }
  }

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
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>班级学情范围</CardTitle>
            <CardDescription>选择班级后，下方学情分析只统计该班成员的真实训练记录。</CardDescription>
          </div>
          {isClassroomAnalyticsLoading ? <Loader2 className="size-5 animate-spin text-[#AE5630]" /> : <UsersRound className="size-5 text-[#AE5630]" />}
        </CardHeader>
        <CardContent className="grid gap-3">
          <label className="grid max-w-lg gap-2 text-sm font-medium">
            统计范围
            <select
              className="h-10 w-full rounded-xl border border-[#E7E0D4] bg-white px-3 text-sm text-[#141413] outline-none transition focus:border-[#141413] focus:ring-2 focus:ring-[#141413]/10"
              disabled={isClassroomAnalyticsLoading}
              onChange={(event) => void handleClassroomAnalyticsSelection(event.target.value)}
              value={selectedClassroomId}
            >
              <option value="">全部学生</option>
              {data.classrooms.map((classroom) => (
                <option key={classroom.classroom_id} value={classroom.classroom_id}>
                  {classroom.name}（{classroom.member_count} 人）
                </option>
              ))}
            </select>
          </label>
          {data.classrooms.length === 0 ? <p className="text-sm text-[#6F6257]">还没有班级，可先在“班级管理”中创建并选择学生。</p> : null}
          {classroomAnalyticsError ? <p className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{classroomAnalyticsError}</p> : null}
        </CardContent>
      </Card>
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
  const scopeLabel = cohort?.scope_label || "全用户";

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>{scopeLabel}、病例与学生学情分析</CardTitle>
          <CardDescription>把报告、训练缺口、错失机会和患者情绪回应汇总到当前范围、病例级与学生级，供教师安排下一轮训练。</CardDescription>
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
            {scopeLabel}总览
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
  const [candidates, setCandidates] = useState<readonly TrainingSkillCandidateSummary[]>(data.candidates);
  const [candidatePagination, setCandidatePagination] = useState<Pagination | null>(data.candidatePagination);
  const [candidateQuery, setCandidateQuery] = useState("");
  const [isCandidateListLoading, setIsCandidateListLoading] = useState(false);
  const [candidateListError, setCandidateListError] = useState("");

  useEffect(() => {
    setCandidates(data.candidates);
    setCandidatePagination(data.candidatePagination);
  }, [data.candidatePagination, data.candidates]);

  async function loadCandidates(offset: number, query = candidateQuery) {
    setIsCandidateListLoading(true);
    setCandidateListError("");
    try {
      const response = await getAdminCandidatesPage(query, offset);
      setCandidates(response.candidates);
      setCandidatePagination(response.pagination);
    } catch (error) {
      setCandidateListError(error instanceof Error ? error.message : "读取候选 Skill 失败");
    } finally {
      setIsCandidateListLoading(false);
    }
  }
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
        <MetricCard icon={<Sparkles />} label="候选 Skill" value={formatCount(candidatePagination?.total ?? candidates.length)} helper="来自训练日志" />
        <MetricCard icon={<GraduationCap />} label="效果状态" value={data.skillEffects?.label || getSkillEffectStatusLabel(data.skillEffects?.status)} helper="样本不足不伪造提升" />
        <MetricCard icon={<Brain />} label="支持样本要求" value={formatCount(data.skillEffects?.min_sessions_per_group ?? 0)} helper="每组最低样本数" />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>候选 Skill</CardTitle>
          <CardDescription>只显示审核判断需要的字段：标题、状态、来源报告、支持次数和回归结果。</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="mb-3 flex gap-2" onSubmit={(event) => { event.preventDefault(); void loadCandidates(0); }}>
            <Input aria-label="搜索候选 Skill" onChange={(event) => setCandidateQuery(event.target.value)} placeholder="搜索标题、病例、训练点或状态" value={candidateQuery} />
            <Button disabled={isCandidateListLoading} type="submit" variant="secondary">搜索</Button>
          </form>
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
                {candidates.map((candidate) => (
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
          {candidates.length === 0 ? <EmptyText>暂无候选 Skill。</EmptyText> : null}
          {candidateListError ? <p className="mt-3 text-sm text-red-700">{candidateListError}</p> : null}
          <PaginationControls isLoading={isCandidateListLoading} onPageChange={(offset) => void loadCandidates(offset)} pagination={candidatePagination} />
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
                <InfoBlock title="审批修改" value={getApprovalChangedFieldsText(selectedCandidate.approval_agent_review)} />
                <InfoBlock title="知识与回归门" value={getApprovalEvidenceText(selectedCandidate.approval_agent_review)} />
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
  isRetrievalEvalBusy,
  onReadEvaluation,
  onRunEvaluation,
  onRunRetrievalEvaluation,
  selectedEvaluation,
}: Readonly<{
  data: DashboardData;
  isDetailBusy: boolean;
  isMutating: boolean;
  isRetrievalEvalBusy: boolean;
  onReadEvaluation: (batchId: string) => void;
  onRunEvaluation: (suiteId: string) => void;
  onRunRetrievalEvaluation: () => void;
  selectedEvaluation: EvaluationBatchDetail | null;
}>) {
  const [evaluations, setEvaluations] = useState<readonly EvaluationBatchSummary[]>(data.evaluations);
  const [evaluationPagination, setEvaluationPagination] = useState<Pagination | null>(data.evaluationPagination);
  const [evaluationQuery, setEvaluationQuery] = useState("");
  const [isEvaluationListLoading, setIsEvaluationListLoading] = useState(false);
  const [evaluationListError, setEvaluationListError] = useState("");
  const [selectedRunSuiteId, setSelectedRunSuiteId] = useState(
    data.evaluationConfig?.suites.find((suite) => suite.enabled)?.suite_id ?? "default_regression",
  );

  useEffect(() => {
    setEvaluations(data.evaluations);
    setEvaluationPagination(data.evaluationPagination);
  }, [data.evaluationPagination, data.evaluations]);

  async function loadEvaluations(offset: number, query = evaluationQuery) {
    setIsEvaluationListLoading(true);
    setEvaluationListError("");
    try {
      const response = await getAdminEvaluationsPage(query, offset);
      setEvaluations(response.evaluations);
      setEvaluationPagination(response.pagination);
    } catch (error) {
      setEvaluationListError(error instanceof Error ? error.message : "读取评测批次失败");
    } finally {
      setIsEvaluationListLoading(false);
    }
  }

  const totalCases = evaluations.reduce((sum, evaluation) => sum + evaluation.total_cases, 0);
  const passedCases = evaluations.reduce((sum, evaluation) => sum + evaluation.passed_cases, 0);
  const passRate = totalCases > 0 ? Math.round((passedCases / totalCases) * 100) : 0;
  return (
    <div className="grid gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <SectionIntro eyebrow="系统评测" title="系统质检和用例结果" description="自动回归测试，用来确认关键链路没有被最近改动破坏。" />
        <div className="flex flex-wrap gap-2">
          <select
            aria-label="选择评测套件"
            className="h-10 rounded-xl border border-[#E7E0D4] bg-white px-3 text-sm"
            onChange={(event) => setSelectedRunSuiteId(event.target.value)}
            value={selectedRunSuiteId}
          >
            {(data.evaluationConfig?.suites ?? []).filter((suite) => suite.enabled).map((suite) => (
              <option key={suite.suite_id} value={suite.suite_id}>{suite.label}</option>
            ))}
          </select>
          <Button disabled={isMutating || !selectedRunSuiteId} onClick={() => onRunEvaluation(selectedRunSuiteId)}>
            {isMutating ? <Loader2 className="animate-spin" /> : <ClipboardCheck />}
            运行所选套件
          </Button>
        </div>
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
      <EvaluationConfigurationPanel cases={data.cases} initialConfig={data.evaluationConfig} />
      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard icon={<ClipboardCheck />} label="评测批次" value={formatCount(evaluationPagination?.total ?? evaluations.length)} helper="历史批次" />
        <MetricCard icon={<Gauge />} label="当前页通过率" value={`${passRate}%`} helper={`${passedCases}/${totalCases} 用例`} />
        <MetricCard icon={<Wrench />} label="当前页失败用例" value={formatCount(evaluations.reduce((sum, evaluation) => sum + evaluation.failed_cases, 0))} helper="需要排查" />
      </div>
      <RetrievalEvalPanel
        isLoading={isRetrievalEvalBusy}
        onRun={onRunRetrievalEvaluation}
        retrievalEval={data.retrievalEval}
      />
      <Card>
        <CardHeader>
          <CardTitle>评测批次</CardTitle>
          <CardDescription>最新批次优先，点击批次查看用例结果。</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="mb-3 flex gap-2" onSubmit={(event) => { event.preventDefault(); void loadEvaluations(0); }}>
            <Input aria-label="搜索评测批次" onChange={(event) => setEvaluationQuery(event.target.value)} placeholder="搜索批次名称或批次 ID" value={evaluationQuery} />
            <Button disabled={isEvaluationListLoading} type="submit" variant="secondary">搜索</Button>
          </form>
          <div className="grid gap-2">
            {evaluations.map((evaluation) => (
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
            {evaluations.length === 0 ? <EmptyText>暂无评测批次。</EmptyText> : null}
          </div>
          {evaluationListError ? <p className="mt-3 text-sm text-red-700">{evaluationListError}</p> : null}
          <PaginationControls isLoading={isEvaluationListLoading} onPageChange={(offset) => void loadEvaluations(offset)} pagination={evaluationPagination} />
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

function EvaluationConfigurationPanel({
  cases,
  initialConfig,
}: Readonly<{
  cases: readonly AdminCaseSummary[];
  initialConfig: AdminEvaluationConfig | null;
}>) {
  const emptyCase = useMemo<AdminEvaluationCaseConfig>(() => ({
    case_key: "new_evaluation_case",
    label: "",
    case_id: cases[0]?.case_id ?? "",
    steps: [{ kind: "submit_diagnosis", value: "", reasoning: "" }],
    expected_total_score: 0,
    forbidden_terms: [],
    enabled: true,
  }), [cases]);
  const emptySuite = useMemo<AdminEvaluationSuiteConfig>(() => ({
    suite_id: "new_evaluation_suite",
    label: "",
    description: "",
    case_keys: [],
    thresholds: {
      maximum_score_delta: 0,
      minimum_batch_pass_rate: 1,
      minimum_rag_explanation_coverage_ratio: 1,
      minimum_rag_evidence_coverage_ratio: 1,
      require_rag_source_coverage: true,
      maximum_case_duration_ms: 0,
    },
    enabled: true,
  }), []);
  const [config, setConfig] = useState<AdminEvaluationConfig | null>(initialConfig);
  const [selectedCaseKey, setSelectedCaseKey] = useState(initialConfig?.evaluation_cases[0]?.case_key ?? "");
  const [caseDraft, setCaseDraft] = useState<AdminEvaluationCaseConfig>(initialConfig?.evaluation_cases[0] ?? emptyCase);
  const [stepsJson, setStepsJson] = useState(JSON.stringify(initialConfig?.evaluation_cases[0]?.steps ?? emptyCase.steps, null, 2));
  const [forbiddenTermsText, setForbiddenTermsText] = useState((initialConfig?.evaluation_cases[0]?.forbidden_terms ?? []).join("、"));
  const [selectedSuiteId, setSelectedSuiteId] = useState(initialConfig?.suites[0]?.suite_id ?? "");
  const [suiteDraft, setSuiteDraft] = useState<AdminEvaluationSuiteConfig>(initialConfig?.suites[0] ?? emptySuite);
  const [scheduleDraft, setScheduleDraft] = useState<Pick<AdminEvaluationSchedule, "enabled" | "suite_id" | "interval_minutes">>({
    enabled: initialConfig?.schedule.enabled ?? false,
    suite_id: initialConfig?.schedule.suite_id ?? initialConfig?.suites[0]?.suite_id ?? "default_regression",
    interval_minutes: initialConfig?.schedule.interval_minutes ?? 1440,
  });
  const [isBusy, setIsBusy] = useState(false);
  const [errorText, setErrorText] = useState("");
  const [statusText, setStatusText] = useState("");

  useEffect(() => {
    if (initialConfig) setConfig(initialConfig);
  }, [initialConfig]);

  async function refreshConfig(): Promise<AdminEvaluationConfig> {
    const nextConfig = await getAdminEvaluationConfig();
    setConfig(nextConfig);
    setScheduleDraft({
      enabled: nextConfig.schedule.enabled,
      suite_id: nextConfig.schedule.suite_id,
      interval_minutes: nextConfig.schedule.interval_minutes,
    });
    return nextConfig;
  }

  function selectCase(caseKey: string) {
    if (!caseKey) {
      const draft = { ...emptyCase, case_key: `evaluation_case_${Date.now()}` };
      setSelectedCaseKey("");
      setCaseDraft(draft);
      setStepsJson(JSON.stringify(draft.steps, null, 2));
      setForbiddenTermsText("");
      return;
    }
    const selected = config?.evaluation_cases.find((item) => item.case_key === caseKey);
    if (!selected) return;
    setSelectedCaseKey(caseKey);
    setCaseDraft(selected);
    setStepsJson(JSON.stringify(selected.steps, null, 2));
    setForbiddenTermsText(selected.forbidden_terms.join("、"));
  }

  function selectSuite(suiteId: string) {
    if (!suiteId) {
      setSelectedSuiteId("");
      setSuiteDraft({ ...emptySuite, suite_id: `evaluation_suite_${Date.now()}` });
      return;
    }
    const selected = config?.suites.find((item) => item.suite_id === suiteId);
    if (!selected) return;
    setSelectedSuiteId(suiteId);
    setSuiteDraft(selected);
  }

  async function handleSaveCase() {
    setIsBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const parsedSteps = JSON.parse(stepsJson) as unknown;
      if (!Array.isArray(parsedSteps) || parsedSteps.length === 0) throw new Error("评测步骤必须是非空 JSON 数组。");
      const saved = await saveAdminEvaluationCase({
        ...caseDraft,
        steps: parsedSteps as AdminEvaluationStep[],
        forbidden_terms: forbiddenTermsText.split(/[、,，\n]/).map((item) => item.trim()).filter(Boolean),
      });
      await refreshConfig();
      setSelectedCaseKey(saved.case_key);
      setCaseDraft(saved);
      setStepsJson(JSON.stringify(saved.steps, null, 2));
      setStatusText(`已保存评测场景：${saved.label}`);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "保存评测场景失败");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleDeleteCase() {
    if (!selectedCaseKey || caseDraft.is_builtin || !window.confirm("确定删除这个评测场景吗？")) return;
    setIsBusy(true);
    setErrorText("");
    try {
      await deleteAdminEvaluationCase(selectedCaseKey);
      const nextConfig = await refreshConfig();
      const nextCase = nextConfig.evaluation_cases[0];
      if (nextCase) {
        setSelectedCaseKey(nextCase.case_key);
        setCaseDraft(nextCase);
        setStepsJson(JSON.stringify(nextCase.steps, null, 2));
        setForbiddenTermsText(nextCase.forbidden_terms.join("、"));
      } else {
        selectCase("");
      }
      setStatusText("评测场景已删除。");
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "删除评测场景失败");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleSaveSuite() {
    setIsBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const saved = await saveAdminEvaluationSuite(suiteDraft);
      await refreshConfig();
      setSelectedSuiteId(saved.suite_id);
      setSuiteDraft(saved);
      setStatusText(`已保存评测套件：${saved.label}`);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "保存评测套件失败");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleDeleteSuite() {
    if (!selectedSuiteId || suiteDraft.is_builtin || !window.confirm("确定删除这个评测套件吗？")) return;
    setIsBusy(true);
    setErrorText("");
    try {
      await deleteAdminEvaluationSuite(selectedSuiteId);
      const nextConfig = await refreshConfig();
      const nextSuite = nextConfig.suites[0];
      if (nextSuite) {
        setSelectedSuiteId(nextSuite.suite_id);
        setSuiteDraft(nextSuite);
      } else {
        selectSuite("");
      }
      setStatusText("评测套件已删除。");
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "删除评测套件失败");
    } finally {
      setIsBusy(false);
    }
  }

  async function handleSaveSchedule() {
    setIsBusy(true);
    setErrorText("");
    setStatusText("");
    try {
      const saved = await saveAdminEvaluationSchedule(scheduleDraft);
      setConfig((current) => current ? { ...current, schedule: saved } : current);
      setScheduleDraft({ enabled: saved.enabled, suite_id: saved.suite_id, interval_minutes: saved.interval_minutes });
      setStatusText(saved.enabled ? `定时评测已启用，下次运行：${formatDateTime(saved.next_run_at || "")}` : "定时评测已停用。");
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "保存定时评测失败");
    } finally {
      setIsBusy(false);
    }
  }

  if (!config) {
    return <Card><CardContent><EmptyText>评测配置暂不可用。</EmptyText></CardContent></Card>;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>评测场景、套件与计划</CardTitle>
        <CardDescription>把真实学生操作步骤配置成可复用场景，组合为套件并设定分数、RAG 覆盖和耗时阈值；计划任务会持久化并在服务重启后继续。</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        <div className="grid gap-4 xl:grid-cols-2">
          <section className="grid gap-3 rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
            <div className="flex items-center justify-between gap-3"><h4 className="font-semibold">1. 评测场景</h4><Button onClick={() => selectCase("")} size="sm" variant="secondary">新建场景</Button></div>
            <select className="h-10 rounded-xl border border-[#E7E0D4] bg-white px-3 text-sm" onChange={(event) => selectCase(event.target.value)} value={selectedCaseKey}>
              <option value="">新场景</option>
              {config.evaluation_cases.map((item) => <option key={item.case_key} value={item.case_key}>{item.label}</option>)}
            </select>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="grid gap-1 text-sm font-medium">场景 ID<Input disabled={Boolean(selectedCaseKey)} onChange={(event) => setCaseDraft((current) => ({ ...current, case_key: event.target.value }))} value={caseDraft.case_key} /></label>
              <label className="grid gap-1 text-sm font-medium">场景名称<Input onChange={(event) => setCaseDraft((current) => ({ ...current, label: event.target.value }))} value={caseDraft.label} /></label>
              <label className="grid gap-1 text-sm font-medium">训练病例<select className="h-10 rounded-xl border border-[#E7E0D4] bg-white px-3" onChange={(event) => setCaseDraft((current) => ({ ...current, case_id: event.target.value }))} value={caseDraft.case_id}>{cases.map((item) => <option key={item.case_id} value={item.case_id}>{item.title || item.case_id}</option>)}</select></label>
              <label className="grid gap-1 text-sm font-medium">期望总分<Input min={0} onChange={(event) => setCaseDraft((current) => ({ ...current, expected_total_score: Number(event.target.value) }))} type="number" value={caseDraft.expected_total_score} /></label>
            </div>
            <label className="grid gap-1 text-sm font-medium">禁止出现的内容（逗号分隔）<Input onChange={(event) => setForbiddenTermsText(event.target.value)} placeholder="治疗方案、用药剂量" value={forbiddenTermsText} /></label>
            <label className="grid gap-1 text-sm font-medium">真实操作步骤（JSON 数组）<textarea className="min-h-48 rounded-2xl border border-[#E7E0D4] bg-white p-3 font-mono text-xs" onChange={(event) => setStepsJson(event.target.value)} value={stepsJson} /></label>
            <label className="flex items-center gap-2 text-sm"><input checked={caseDraft.enabled} onChange={(event) => setCaseDraft((current) => ({ ...current, enabled: event.target.checked }))} type="checkbox" />启用该场景</label>
            <div className="flex justify-end gap-2"><Button disabled={isBusy || caseDraft.is_builtin} onClick={() => void handleDeleteCase()} variant="destructive">删除</Button><Button disabled={isBusy} onClick={() => void handleSaveCase()}>保存场景</Button></div>
          </section>

          <section className="grid gap-3 rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
            <div className="flex items-center justify-between gap-3"><h4 className="font-semibold">2. 评测套件与阈值</h4><Button onClick={() => selectSuite("")} size="sm" variant="secondary">新建套件</Button></div>
            <select className="h-10 rounded-xl border border-[#E7E0D4] bg-white px-3 text-sm" onChange={(event) => selectSuite(event.target.value)} value={selectedSuiteId}>
              <option value="">新套件</option>
              {config.suites.map((item) => <option key={item.suite_id} value={item.suite_id}>{item.label}</option>)}
            </select>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="grid gap-1 text-sm font-medium">套件 ID<Input disabled={Boolean(selectedSuiteId)} onChange={(event) => setSuiteDraft((current) => ({ ...current, suite_id: event.target.value }))} value={suiteDraft.suite_id} /></label>
              <label className="grid gap-1 text-sm font-medium">套件名称<Input onChange={(event) => setSuiteDraft((current) => ({ ...current, label: event.target.value }))} value={suiteDraft.label} /></label>
            </div>
            <label className="grid gap-1 text-sm font-medium">说明<Input onChange={(event) => setSuiteDraft((current) => ({ ...current, description: event.target.value }))} value={suiteDraft.description} /></label>
            <div className="grid gap-2 rounded-xl border border-[#E7E0D4] bg-white p-3"><p className="text-sm font-medium">包含场景</p>{config.evaluation_cases.map((item) => <label className="flex items-center gap-2 text-sm" key={item.case_key}><input checked={suiteDraft.case_keys.includes(item.case_key)} onChange={(event) => setSuiteDraft((current) => ({ ...current, case_keys: event.target.checked ? [...current.case_keys, item.case_key] : current.case_keys.filter((key) => key !== item.case_key) }))} type="checkbox" />{item.label}</label>)}</div>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="grid gap-1 text-sm font-medium">允许分数偏差<Input min={0} onChange={(event) => setSuiteDraft((current) => ({ ...current, thresholds: { ...current.thresholds, maximum_score_delta: Number(event.target.value) } }))} type="number" value={suiteDraft.thresholds.maximum_score_delta} /></label>
              <label className="grid gap-1 text-sm font-medium">批次最低通过率（%）<Input max={100} min={0} onChange={(event) => setSuiteDraft((current) => ({ ...current, thresholds: { ...current.thresholds, minimum_batch_pass_rate: Number(event.target.value) / 100 } }))} type="number" value={Math.round(suiteDraft.thresholds.minimum_batch_pass_rate * 100)} /></label>
              <label className="grid gap-1 text-sm font-medium">解释来源覆盖（%）<Input max={100} min={0} onChange={(event) => setSuiteDraft((current) => ({ ...current, thresholds: { ...current.thresholds, minimum_rag_explanation_coverage_ratio: Number(event.target.value) / 100 } }))} type="number" value={Math.round(suiteDraft.thresholds.minimum_rag_explanation_coverage_ratio * 100)} /></label>
              <label className="grid gap-1 text-sm font-medium">证据来源覆盖（%）<Input max={100} min={0} onChange={(event) => setSuiteDraft((current) => ({ ...current, thresholds: { ...current.thresholds, minimum_rag_evidence_coverage_ratio: Number(event.target.value) / 100 } }))} type="number" value={Math.round(suiteDraft.thresholds.minimum_rag_evidence_coverage_ratio * 100)} /></label>
              <label className="grid gap-1 text-sm font-medium">单场景最长耗时（毫秒，0 不限制）<Input min={0} onChange={(event) => setSuiteDraft((current) => ({ ...current, thresholds: { ...current.thresholds, maximum_case_duration_ms: Number(event.target.value) } }))} type="number" value={suiteDraft.thresholds.maximum_case_duration_ms} /></label>
              <label className="flex items-end gap-2 pb-2 text-sm"><input checked={suiteDraft.thresholds.require_rag_source_coverage} onChange={(event) => setSuiteDraft((current) => ({ ...current, thresholds: { ...current.thresholds, require_rag_source_coverage: event.target.checked } }))} type="checkbox" />必须有 RAG 来源覆盖</label>
            </div>
            <label className="flex items-center gap-2 text-sm"><input checked={suiteDraft.enabled} onChange={(event) => setSuiteDraft((current) => ({ ...current, enabled: event.target.checked }))} type="checkbox" />启用该套件</label>
            <div className="flex justify-end gap-2"><Button disabled={isBusy || suiteDraft.is_builtin} onClick={() => void handleDeleteSuite()} variant="destructive">删除</Button><Button disabled={isBusy} onClick={() => void handleSaveSuite()}>保存套件</Button></div>
          </section>
        </div>

        <section className="grid gap-3 rounded-2xl border border-[#E7E0D4] bg-white p-4">
          <div className="flex flex-wrap items-start justify-between gap-3"><div><h4 className="font-semibold">3. 定时评测</h4><p className="mt-1 text-xs text-[#6F6257]">最短 5 分钟；同一计划通过持久化租约避免重复执行。</p></div><Badge variant={config.schedule.enabled ? "success" : "muted"}>{config.schedule.enabled ? "已启用" : "未启用"}</Badge></div>
          <div className="grid gap-3 md:grid-cols-3">
            <label className="grid gap-1 text-sm font-medium">运行套件<select className="h-10 rounded-xl border border-[#E7E0D4] bg-white px-3" onChange={(event) => setScheduleDraft((current) => ({ ...current, suite_id: event.target.value }))} value={scheduleDraft.suite_id}>{config.suites.filter((item) => item.enabled).map((item) => <option key={item.suite_id} value={item.suite_id}>{item.label}</option>)}</select></label>
            <label className="grid gap-1 text-sm font-medium">运行间隔（分钟）<Input max={10080} min={5} onChange={(event) => setScheduleDraft((current) => ({ ...current, interval_minutes: Number(event.target.value) }))} type="number" value={scheduleDraft.interval_minutes} /></label>
            <label className="flex items-end gap-2 pb-2 text-sm"><input checked={scheduleDraft.enabled} onChange={(event) => setScheduleDraft((current) => ({ ...current, enabled: event.target.checked }))} type="checkbox" />启用定时运行</label>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-xs text-[#6F6257]">下次：{formatDateTime(config.schedule.next_run_at || "")} · 最近批次：{config.schedule.last_batch_id || "暂无"}{config.schedule.last_error ? ` · 最近错误：${config.schedule.last_error}` : ""}</p><Button disabled={isBusy} onClick={() => void handleSaveSchedule()}>保存计划</Button></div>
        </section>
        {errorText ? <p className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{errorText}</p> : null}
        {statusText ? <p className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{statusText}</p> : null}
      </CardContent>
    </Card>
  );
}

function RetrievalEvalPanel({
  isLoading,
  onRun,
  retrievalEval,
}: Readonly<{
  isLoading: boolean;
  onRun: () => void;
  retrievalEval: AdminRetrievalEval | null;
}>) {
  const metrics = retrievalEval?.metrics;
  const results = retrievalEval?.results ?? [];
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>RAG 检索评测</CardTitle>
          <CardDescription>用固定 gold query 检查知识库召回和来源覆盖；不参与标准诊断裁判。</CardDescription>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Badge variant="muted">{formatCount(metrics?.query_count ?? retrievalEval?.gold_set?.query_count ?? results.length)} 条查询</Badge>
          <Button disabled={isLoading} onClick={onRun} size="sm" type="button" variant="secondary">
            {isLoading ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            {retrievalEval ? "重新运行检索评测" : "运行检索评测"}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {retrievalEval ? (
          <div className="grid gap-4">
            <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-7">
              <MiniStat label="Recall@3" value={formatRatioMetric(metrics?.recall_at_3)} />
              <MiniStat label="Recall@5" value={formatRatioMetric(metrics?.recall_at_5)} />
              <MiniStat label="MRR@5" value={formatRatioMetric(metrics?.mrr_at_5)} />
              <MiniStat label="nDCG@5" value={formatRatioMetric(metrics?.ndcg_at_5)} />
              <MiniStat label="来源覆盖" value={formatRatioMetric(metrics?.source_coverage)} />
              <MiniStat label="Hit@5" value={formatRatioMetric(metrics?.hit_rate_at_5)} />
              <MiniStat label="零命中查询" value={formatCount(metrics?.zero_hit_query_count ?? 0)} />
            </div>
            <div className="grid gap-3 lg:grid-cols-[1fr_0.8fr]">
              <div className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4">
                <h4 className="text-sm font-semibold">Top 查询命中</h4>
                <div className="mt-3 grid gap-2">
                  {results.slice(0, 5).map((result, index) => (
                    <div className="rounded-xl border border-[#E7E0D4] bg-white px-3 py-3 text-sm" key={`${result.query_id ?? ""}-${index}`}>
                      <p className="font-medium">{result.query || result.query_id || `查询 ${index + 1}`}</p>
                      <p className="mt-1 text-xs leading-5 text-[#6F6257]">命中：{joinText(result.retrieved_references ?? result.hits_at_5, "暂无")}</p>
                      {result.expanded_query && result.expanded_query !== result.query ? (
                        <p className="mt-1 text-xs leading-5 text-[#8A7D6F]">查询扩展：{result.expanded_query}</p>
                      ) : null}
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
          <EmptyText>尚未运行 RAG 检索评测；按需运行不会阻塞其他管理数据。</EmptyText>
        )}
      </CardContent>
    </Card>
  );
}

function AdminAuditEventPanel({
  initialEvents,
  initialPagination,
}: Readonly<{
  initialEvents: readonly AdminAuditEvent[];
  initialPagination: Pagination | null;
}>) {
  const [events, setEvents] = useState(initialEvents);
  const [pagination, setPagination] = useState(initialPagination);
  const [query, setQuery] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [errorText, setErrorText] = useState("");

  useEffect(() => {
    setEvents(initialEvents);
    setPagination(initialPagination);
  }, [initialEvents, initialPagination]);

  async function loadEvents(offset = 0) {
    setIsLoading(true);
    setErrorText("");
    try {
      const payload = await getAdminAuditEvents(query, resourceType, offset);
      setEvents(payload.events);
      setPagination(payload.pagination);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "读取管理审计失败");
    } finally {
      setIsLoading(false);
    }
  }

  const exportParameters = new URLSearchParams();
  if (query.trim()) {
    exportParameters.set("q", query.trim());
  }
  if (resourceType) {
    exportParameters.set("resource_type", resourceType);
  }
  const exportSuffix = exportParameters.toString() ? `&${exportParameters.toString()}` : "";
  const offset = pagination?.offset ?? 0;
  const limit = pagination?.limit ?? 50;
  const total = pagination?.total ?? events.length;

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>管理员操作审计</CardTitle>
          <CardDescription>记录操作者、动作、对象、改动前后和时间；支持筛选、翻页与 CSV/JSON 导出。</CardDescription>
        </div>
        <Badge variant="muted">{formatCount(total)} 条</Badge>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-2 lg:grid-cols-[1fr_12rem_auto_auto]">
          <Input onChange={(event) => setQuery(event.target.value)} placeholder="搜索操作者、对象或摘要" value={query} />
          <select
            className="h-10 rounded-xl border border-[#E7E0D4] bg-white px-3 text-sm outline-none"
            onChange={(event) => setResourceType(event.target.value)}
            value={resourceType}
          >
            <option value="">全部对象</option>
            <option value="user">账号</option>
            <option value="classroom">班级</option>
            <option value="source">来源</option>
            <option value="case">病例</option>
            <option value="rubric">评分表</option>
            <option value="rag_document">知识文档</option>
            <option value="rag_knowledge">知识片段</option>
            <option value="evaluation">系统评测</option>
            <option value="skill">Skill</option>
          </select>
          <Button disabled={isLoading} onClick={() => void loadEvents(0)} type="button" variant="secondary">
            {isLoading ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            查询
          </Button>
          <div className="flex gap-2">
            <Button asChild size="sm" variant="outline">
              <a href={`/api/admin/audit-events/export?format=csv${exportSuffix}`}>导出 CSV</a>
            </Button>
            <Button asChild size="sm" variant="outline">
              <a href={`/api/admin/audit-events/export?format=json${exportSuffix}`}>导出 JSON</a>
            </Button>
          </div>
        </div>
        {errorText ? <p className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{errorText}</p> : null}
        <div className="grid gap-2">
          {events.map((event) => (
            <article className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4" key={event.event_id}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="muted">{getAdminAuditActionLabel(event.action)}</Badge>
                    <Badge variant="muted">{getAdminAuditResourceLabel(event.resource_type)}</Badge>
                    <span className="text-xs text-[#8A7D6F]">{formatDateTime(event.created_at)}</span>
                  </div>
                  <p className="mt-2 text-sm font-semibold">{event.summary || event.action}</p>
                  <p className="mt-1 text-xs text-[#6F6257]">操作者：{event.actor_email || event.actor_user_id || "系统"}</p>
                </div>
                <code className="max-w-full truncate rounded-lg bg-white px-2 py-1 text-[11px] text-[#8A7D6F]">{event.resource_id}</code>
              </div>
              {event.metadata && Object.keys(event.metadata as object).length > 0 ? (
                <details className="mt-3 text-xs text-[#6F6257]">
                  <summary className="cursor-pointer font-medium">查看审计元数据</summary>
                  <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap rounded-xl border border-[#E7E0D4] bg-white p-3">{JSON.stringify(event.metadata, null, 2)}</pre>
                </details>
              ) : null}
            </article>
          ))}
          {events.length === 0 ? <EmptyText>当前筛选条件下没有管理员操作记录。</EmptyText> : null}
        </div>
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-[#8A7D6F]">第 {total === 0 ? 0 : offset + 1}–{Math.min(offset + events.length, total)} 条，共 {total} 条</p>
          <div className="flex gap-2">
            <Button disabled={isLoading || offset <= 0} onClick={() => void loadEvents(Math.max(0, offset - limit))} size="sm" type="button" variant="secondary">上一页</Button>
            <Button disabled={isLoading || offset + limit >= total} onClick={() => void loadEvents(offset + limit)} size="sm" type="button" variant="secondary">下一页</Button>
          </div>
        </div>
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
      <SectionIntro eyebrow="运行留痕" title="管理审计与模型调用" description="管理动作可追溯、可筛选和导出；模型配置保持只读，只展示调用稳定性。" />
      <AdminAuditEventPanel initialEvents={data.adminAuditEvents} initialPagination={data.adminAuditPagination} />
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
  const items = logs;
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

function PaginationControls({
  isLoading,
  onPageChange,
  pagination,
}: Readonly<{
  isLoading: boolean;
  onPageChange: (offset: number) => void;
  pagination: Pagination | null;
}>) {
  if (!pagination || pagination.total <= pagination.limit) return null;
  const firstItem = pagination.total === 0 ? 0 : pagination.offset + 1;
  const lastItem = Math.min(pagination.total, pagination.offset + pagination.limit);
  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-[#E7E0D4] pt-4">
      <p className="text-xs text-[#6F6257]">
        第 {firstItem}-{lastItem} 条，共 {pagination.total} 条
      </p>
      <div className="flex gap-2">
        <Button
          disabled={isLoading || pagination.offset <= 0}
          onClick={() => onPageChange(Math.max(0, pagination.offset - pagination.limit))}
          size="sm"
          variant="secondary"
        >
          上一页
        </Button>
        <Button
          disabled={isLoading || pagination.offset + pagination.limit >= pagination.total}
          onClick={() => onPageChange(pagination.offset + pagination.limit)}
          size="sm"
          variant="secondary"
        >
          下一页
        </Button>
      </div>
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
    stage_scope: toTokenList(item.stage_scope).length > 0 ? toTokenList(item.stage_scope) : ["any"],
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

function getAdminUserRoleLabel(role: AdminManagedUser["role"]): string {
  return { admin: "管理员", student: "学生", teacher: "教师" }[role];
}

function getAdminUserStatusLabel(status: AdminManagedUser["status"]): string {
  return { active: "启用", deleted: "已撤销", disabled: "禁用" }[status];
}

function getAdminAuditResourceLabel(resourceType: string): string {
  return ({
    case: "病例",
    classroom: "班级",
    evaluation: "系统评测",
    rag_document: "知识文档",
    rag_knowledge: "知识片段",
    rubric: "评分表",
    skill: "Skill",
    source: "来源",
    user: "账号",
  }[resourceType] ?? resourceType) || "其他";
}

function getAdminAuditActionLabel(action: string): string {
  const actionName = action.split(".").at(-1) ?? action;
  return {
    approved: "通过",
    archived: "归档",
    created: "创建",
    deleted: "撤销/删除",
    imported: "批量导入",
    members_copy: "复制成员",
    members_move: "移动成员",
    password_reset: "重置密码",
    rejected: "拒绝",
    reviewed: "审核",
    rolled_back: "回滚",
    run: "运行",
    updated: "更新",
  }[actionName] ?? action;
}

function getAdminAssetReviewLabel(status: string): string {
  return {
    approved: "审核通过",
    rejected: "已退回",
    unreviewed: "待审核",
  }[status] ?? status;
}

function formatDateOnly(value: string | undefined): string {
  if (!value) {
    return "未记录";
  }
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}

function getSelectableSources(sources: readonly AdminSourceSummary[]): readonly AdminSourceSummary[] {
  return sources.filter((source) => source.selectable_for_new_knowledge !== false);
}

function getSourceFreshnessLabel(status: string | undefined): string {
  const labels: Record<string, string> = {
    current: "复核有效",
    review_due: "到期待复核",
    superseded: "已被新来源替代",
    unverified: "未记录复核",
  };
  return labels[status || ""] ?? (status || "未记录复核");
}

function getSourceFreshnessBadgeVariant(
  status: string | undefined,
): "danger" | "muted" | "success" | "warning" {
  if (status === "current") {
    return "success";
  }
  if (status === "review_due") {
    return "warning";
  }
  return status === "unverified" ? "danger" : "muted";
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

function getKnowledgeReviewStatusLabel(reviewStatus: string | undefined): string {
  const labels: Record<string, string> = {
    approved: "已批准",
    mixed: "部分通过",
    pending_review: "待审核",
    rejected: "已拒绝",
  };
  return labels[reviewStatus || ""] ?? (reviewStatus || "已批准");
}

function getKnowledgeReviewBadgeVariant(
  reviewStatus: string | undefined,
): "danger" | "muted" | "success" | "warning" {
  if (reviewStatus === "approved") {
    return "success";
  }
  if (reviewStatus === "rejected") {
    return "danger";
  }
  return reviewStatus === "pending_review" ? "warning" : "muted";
}

function getKnowledgeQualityLabel(value: string): string {
  const labels: Record<string, string> = {
    low_value_section: "低价值章节",
    missing_section_title: "缺少章节标题",
    over_max_chars: "片段过长",
    short_chunk: "片段较短",
    short_table_chunk: "表格片段较短",
  };
  return labels[value] ?? value;
}

function getKnowledgeRiskLabel(value: string): string {
  const labels: Record<string, string> = {
    diagnosis_answer_content: "含诊断答案",
    references_section: "参考文献段",
    treatment_or_dose_content: "含治疗或剂量",
  };
  return labels[value] ?? value;
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
    agent_decision_traced: "教师决策留痕",
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

function getTeacherInterventionEvent(event: TrainingEventRecord): TeacherInterventionEvent | null {
  const decision = getRecordField(event.payload, "teacher_intervention_decision");
  if (!decision) {
    return null;
  }
  const mode = getStringField(decision, "mode", "");
  if (!mode) {
    return null;
  }
  return {
    mode,
    actionType: getStringField(decision, "action_type", "student_action"),
    triggerKind: getStringField(decision, "trigger_kind", ""),
    reasonCode: getStringField(decision, "reason_code", ""),
    reason: getStringField(decision, "reason", ""),
    hint: getStringField(decision, "hint", ""),
    hintEmitted: decision.hint_emitted === true,
    selectedSkillIds: toTextList(decision.selected_skill_ids),
    sourceReferences: toTextList(decision.source_references),
    processingStatus: getStringField(decision, "processing_status", "completed"),
    createdAt: event.created_at ?? getStringField(decision, "created_at", ""),
  };
}

function getTeacherInterventionModeLabel(mode: string): string {
  const labels: Record<string, string> = {
    silent: "保持静默",
    observe: "观察等待",
    hint: "发出提示",
    block: "边界阻断",
  };
  return labels[mode] ?? (mode || "已判断");
}

function getTeacherInterventionBadgeVariant(mode: string): "success" | "muted" | "warning" | "danger" {
  if (mode === "block") {
    return "danger";
  }
  if (mode === "hint") {
    return "warning";
  }
  if (mode === "silent") {
    return "success";
  }
  return "muted";
}

function getTeacherActionTypeLabel(actionType: string): string {
  const labels: Record<string, string> = {
    student_utterance: "问诊交互",
    physical_exam_requested: "查体申请",
    auxiliary_test_requested: "辅助检查申请",
    hypothesis_recorded: "诊断假设",
    diagnosis_submitted: "诊断提交",
    hint_requested: "主动求助",
    answer_request_redirect: "索要答案",
    safety_boundary: "安全边界",
  };
  return labels[actionType] ?? (actionType || "学生操作");
}

function getProcessingStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    completed: "处理完成",
    fallback: "降级完成",
    error: "处理异常",
  };
  return labels[status] ?? (status || "已记录");
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
  const qualityChecks = review.quality_review?.checks ?? [];
  const passedQualityChecks = qualityChecks.filter((check) => check.passed).length;
  const parts = [
    review.decision ? `结论：${getApprovalDecisionLabel(review.decision)}` : "",
    review.revision_status ? `修订：${review.revision_status === "modified" ? "已净化并重建" : "无需修订"}` : "",
    review.quality_review
      ? `质量检查：${review.quality_review.passed ? "通过" : "未通过"}${qualityChecks.length > 0 ? `（${passedQualityChecks}/${qualityChecks.length}）` : ""}`
      : "",
    review.role_policy ? `角色禁区：${review.role_policy.passed ? "通过" : "未通过"}` : "",
  ].filter(Boolean);
  return parts.join("；") || "审批 Agent 已记录，但暂无摘要。";
}

function getApprovalChangedFieldsText(review: TrainingSkillApprovalAgentReview | undefined): string {
  const changedFields = Array.from(
    new Set(
      (review?.changed_fields ?? [])
        .map((change) => change.field?.trim() ?? "")
        .filter(Boolean),
    ),
  );
  return changedFields.length > 0
    ? `只修订教学表达 / 结构：${changedFields.join("、")}`
    : "未修订教学表达；病例、阶段、触发条件和来源字段均保持不变。";
}

function getApprovalEvidenceText(review: TrainingSkillApprovalAgentReview | undefined): string {
  if (!review) {
    return "暂无审批证据。";
  }
  const knowledgeLabels = (review.retrieved_knowledge_context ?? [])
    .map((item) => item.title || item.reference)
    .filter((item): item is string => Boolean(item?.trim()));
  const knowledgeCount = Math.max(knowledgeLabels.length, review.knowledge_references?.length ?? 0);
  const gate = review.regression_gate;
  const blockingCount = [
    ...(gate?.blocking_failures ?? []),
    ...(gate?.candidate_safety_violations ?? []),
    ...(gate?.candidate_context_violations ?? []),
    ...(gate?.approval_agent_violations ?? []),
  ].length;
  const parts = [
    `审批知识：${knowledgeCount} 条${knowledgeLabels.length > 0 ? `（${knowledgeLabels.slice(0, 2).join("、")}）` : ""}`,
    gate
      ? `回归门：${gate.passed ? "通过" : "阻断"}，${gate.evaluation_passed_cases ?? 0}/${gate.evaluation_total_cases ?? 0} 个场景通过`
      : `回归门：${review.regression_passed ? "通过" : "未通过"}`,
    blockingCount > 0 ? `阻断证据：${blockingCount} 项` : "阻断证据：0 项",
  ];
  return parts.join("；");
}

function getApprovalDecisionLabel(decision: string): string {
  const labels: Record<string, string> = {
    prepared_for_auto_apply: "已完成审批准备",
    approved_for_auto_apply: "已通过并自动应用",
    ready_for_human_review: "审批通过，待教师确认",
    blocked: "审批阻断",
    blocked_by_regression: "回归门阻断",
  };
  return labels[decision] ?? decision;
}
