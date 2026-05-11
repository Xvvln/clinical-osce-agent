"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, FormEvent, PointerEvent, ReactNode, UIEvent } from "react";
import { getCurrentUser, loginUser, logoutUser, registerUser } from "./auth-client";
import type { AuthUser } from "./auth-client";

type StageStatus = "done" | "active" | "locked";

type StageDefinition = {
  readonly key: string;
  readonly label: string;
};

type WorkflowStepDefinition = Readonly<{
  key: "case_intro" | "history_taking" | "physical_exam" | "auxiliary_test" | "hypothesis" | "diagnosis_submission" | "feedback";
  label: string;
}>;

type RightPanelKey = "focus" | "agent" | "evidence" | "hypotheses" | "report";

type OsceDockMenuGroup = "training" | "system";

type ProcedureActionGroup = "physical_exam" | "auxiliary_test";

type OsceDockSide = "left" | "right";

type ApiConfigProvider = "custom_backend" | "gemini" | "vertex_gemini_adc" | "vertex_gemini_api_key" | "openai_compatible" | "anthropic";

type StudentApiConfig = Readonly<{
  provider: ApiConfigProvider;
  apiKey: string;
  model: string;
  baseUrl: string;
  proxyUrl: string;
}>;

type StudentApiConfigTestResponse = Readonly<{
  ok: boolean;
  provider: ApiConfigProvider;
  message: string;
  checked_url?: string;
}>;

type StudentApiConfigRuntimeResponse = Readonly<{
  active: boolean;
  provider: ApiConfigProvider | "";
  model: string;
  base_url: string;
  proxy_url: string;
  api_key_saved?: boolean;
  integration_targets: readonly string[];
  message: string;
}>;

type ApiConfigProviderOption = Readonly<{
  id: ApiConfigProvider;
  label: string;
  defaultModel: string;
  defaultBaseUrl: string;
  defaultProxyUrl: string;
}>;

type OsceDockPosition = Readonly<{
  x: number;
  y: number;
  side: OsceDockSide;
  isReady: boolean;
}>;

type OsceDockDragState = Readonly<{
  pointerId: number;
  startPointerX: number;
  startPointerY: number;
  startX: number;
  startY: number;
  moved: boolean;
}>;

type CoverageMapItem = Readonly<{
  id: string;
  label: string;
  status: "covered" | "pending";
}>;

type CoverageMapPayload = Readonly<{
  history: readonly CoverageMapItem[];
  physical_exam: readonly CoverageMapItem[];
  auxiliary_test: readonly CoverageMapItem[];
  reasoning: readonly CoverageMapItem[];
}>;

type ApiMessage = {
  readonly role: "student" | "patient" | string;
  readonly content: string;
};

type FinalSubmission = Readonly<{
  diagnosis: string;
  reasoning: string;
}>;

type DiagnosisDraft = Readonly<{
  diagnosis: string;
  reasoning: string;
}>;

type StudentVisiblePatientProfile = Readonly<{
  age: string;
  gender: string;
  occupation: string;
  hospital_department: string;
}>;

type OpeningTaskCard = Readonly<{
  role: string;
  scenario: string;
  tasks: readonly string[];
}>;

type CaseTeachingErrorPattern = Readonly<{
  pattern_id: string;
  title: string;
  focus: string;
  related_rubric_items: readonly string[];
}>;

type CaseTeachingFocus = Readonly<{
  learning_objectives: readonly string[];
  common_error_patterns: readonly CaseTeachingErrorPattern[];
  recommended_training_path: readonly string[];
}>;

type DerivedTeachingFocusPattern = Readonly<{
  focus_id: string;
  scope: string;
  pattern: string;
  title: string;
  description: string;
  training_suggestion: string;
  trigger_item_ids: readonly string[];
  case_ids: readonly string[];
  support_count: number;
  source_report_count: number;
  source_reference_ids: readonly string[];
  severity: string;
  visibility_level: string;
  why_now: string;
}>;

type DerivedTeachingFocus = Readonly<{
  case_id: string;
  session_id?: string;
  scope: string;
  patterns: readonly DerivedTeachingFocusPattern[];
}>;

type InquiryGuidance = Readonly<{
  priority: string;
  suggested_questions: readonly string[];
  categories: readonly string[];
}>;

type PhysicalExamOption = Readonly<{
  exam_code: string;
  exam_name_cn: string;
  result: string;
  is_abnormal: boolean;
}>;

type AuxiliaryTestOption = Readonly<{
  test_code: string;
  test_name_cn: string;
  category: string;
  invasiveness: string;
  cost_hint: string;
  diagnostic_role: string;
  rules_out: readonly string[];
  recommended_stage: string;
  overuse_warning: string | null;
  result: string;
  is_abnormal: boolean;
}>;

type PhysicalExamQuickOption = Readonly<Pick<PhysicalExamOption, "exam_code" | "exam_name_cn">>;

type AuxiliaryTestQuickOption = Readonly<
  Pick<
    AuxiliaryTestOption,
    | "test_code"
    | "test_name_cn"
    | "category"
    | "invasiveness"
    | "cost_hint"
    | "diagnostic_role"
    | "rules_out"
    | "recommended_stage"
    | "overuse_warning"
  >
>;

type TrainingProgressSection = Readonly<{
  total: number;
}>;

type TrainingProgress = Readonly<{
  history: TrainingProgressSection &
    Readonly<{
      covered: number;
      covered_fact_ids: readonly string[];
      pending_fact_ids: readonly string[];
    }>;
  physical_exam: TrainingProgressSection &
    Readonly<{
      requested: number;
      requested_codes: readonly string[];
      pending_codes: readonly string[];
      must_total: number;
      must_requested: number;
      must_pending_codes: readonly string[];
    }>;
  auxiliary_test: TrainingProgressSection &
    Readonly<{
      requested: number;
      requested_codes: readonly string[];
      pending_codes: readonly string[];
      must_total: number;
      must_requested: number;
      must_pending_codes: readonly string[];
    }>;
  reasoning: Readonly<{
    total_evidence: number;
    collected_evidence_count: number;
    collected_evidence: readonly string[];
    pending_evidence: readonly string[];
    ready_for_hypothesis: boolean;
  }>;
  coverage_map: CoverageMapPayload;
  next_focus: string;
}>;

type TeachingPlan = Readonly<{
  plan_id: string;
  case_id: string;
  session_id?: string | null;
  stage: string;
  observed_gap_ids: readonly string[];
  active_focus_ids: readonly string[];
  selected_strategy: string;
  strategy_reason: string;
  learning_goal: string;
  next_best_action: string;
  allowed_actions: readonly string[];
  blocked_actions: readonly string[];
  source_references: readonly string[];
  skill_ids: readonly string[];
  safety_boundary: string;
}>;

type StageCheckpoint = Readonly<{
  checkpoint_id: string;
  case_id: string;
  session_id?: string | null;
  stage: string;
  status: string;
  readiness: string;
  covered_signal_ids: readonly string[];
  pending_signal_ids: readonly string[];
  safety_note: string;
}>;

type HintLadderStep = Readonly<{
  action_type: string;
  level: number;
  message_template: string;
  trigger_item_ids: readonly string[];
  disclosure_policy: string;
}>;

type PedagogyState = Readonly<{
  training_phase: string;
  active_learning_goal: string;
  missing_rubric_items: readonly string[];
  evidence_gap: string;
  differential_gap: string;
  next_best_action: string;
  skill_context_ids: readonly string[];
  coaching_mode: string;
  safety_mode: string;
  reflection_summary_id: string | null;
  teaching_plan: TeachingPlan;
  stage_checkpoint: StageCheckpoint;
  hint_ladder: readonly HintLadderStep[];
}>;

type AgentTraceObserve = Readonly<{
  stage: string;
  observed_gap_ids: readonly string[];
  checkpoint_status: string;
  covered_signal_ids: readonly string[];
  pending_signal_ids: readonly string[];
}>;

type AgentTraceDecide = Readonly<{
  active_learning_goal: string;
  selected_strategy: string;
  strategy_reason: string;
}>;

type AgentTraceAct = Readonly<{
  next_best_action: string;
  allowed_actions: readonly string[];
  blocked_actions: readonly string[];
  hint_ladder_levels: readonly number[];
}>;

type AgentTraceReflect = Readonly<{
  reflection_summary_id: string | null;
  safety_mode: string;
}>;

type AgentDecisionTraceItem = Readonly<{
  trace_id: string;
  node: string;
  stage: string;
  decision: string;
  next_best_action: string;
  skill_context_ids: readonly string[];
  coaching_mode: string;
  safety_mode: string;
  observe: AgentTraceObserve;
  decide: AgentTraceDecide;
  act: AgentTraceAct;
  reflect: AgentTraceReflect;
}>;

type AgentTurnMemoryItem = Readonly<{
  turn_id: string;
  student_message: string;
  reply: string;
  reply_role: "student" | "patient" | "coach" | string;
  current_intent: string;
  turn_policy: string;
  agent_path: readonly string[];
  revealed_fact_id: string | null;
  source_references: readonly string[];
  safety_flags: readonly string[];
}>;

type ReflectionPrompt = Readonly<{
  prompt_id: string;
  question: string;
  related_item_ids: readonly string[];
}>;

type ReflectionSummary = Readonly<{
  reflection_summary_id: string;
  missed_item_count: number;
  missed_item_ids: readonly string[];
  summary: string;
  next_focus: string;
  reflection_prompts: readonly ReflectionPrompt[];
  safety_note: string;
}>;

type OsceSession = Readonly<{
  session_id: string;
  student_id: string;
  case_id: string;
  stage: string;
  case_title: string;
  chief_complaint: string;
  patient_profile: StudentVisiblePatientProfile;
  opening_task_card: OpeningTaskCard;
  teaching_focus: CaseTeachingFocus;
  dynamic_teaching_focus: DerivedTeachingFocus;
  inquiry_guidance: InquiryGuidance;
  diagnosis_draft: DiagnosisDraft;
  physical_exam_options: readonly PhysicalExamOption[];
  auxiliary_test_options: readonly AuxiliaryTestOption[];
  training_progress: TrainingProgress;
  messages: readonly ApiMessage[];
  asked_questions: readonly string[];
  intent_history: readonly string[];
  revealed_facts: readonly string[];
  requested_exams: readonly string[];
  requested_tests: readonly string[];
  student_hypotheses: readonly string[];
  final_submission: FinalSubmission | null;
  rubric_scores: Readonly<Record<string, unknown>>;
  missed_items: readonly string[];
  retrieved_sources: readonly string[];
  feedback_report: Readonly<Record<string, unknown>> | null;
  safety_flags: readonly string[];
  evolution_candidates: readonly string[];
  agent_turn_memory: readonly AgentTurnMemoryItem[];
  pedagogy_state: PedagogyState;
  agent_decision_trace: readonly AgentDecisionTraceItem[];
  reflection_summary: ReflectionSummary | null;
  reply?: string;
  current_intent?: string;
}>;

type ChatMessage = {
  readonly id: string;
  readonly speaker: "student" | "patient" | "coach";
  readonly label: string;
  readonly text: string;
  readonly finalText?: string;
  readonly isPending?: boolean;
};

type EvidenceItem = {
  readonly label: string;
  readonly detail: string;
};

type PhysicalExamResponse = OsceSession &
  Readonly<{
    exam_code: string;
    exam_name_cn: string;
    result: string;
  }>;

type AuxiliaryTestResponse = OsceSession &
  Readonly<{
    test_code: string;
    test_name_cn: string;
    result: string;
  }>;

type HintResponse = OsceSession &
  Readonly<{
    hint: string;
  }>;

type ProcedureResult = Readonly<{
  id: string;
  label: string;
  result: string;
}>;

type SourceReferenceItem = Readonly<{
  reference: string;
  source_type: string;
  title: string;
  metadata: Readonly<Record<string, unknown>>;
}>;

type RubricScoreItem = Readonly<{
  score: number;
  max_score: number;
  dimension_id: string;
  description: string;
}>;

type FeedbackReport = Readonly<{
  session_id: string;
  case_id: string;
  total_score: number;
  dimension_scores: Readonly<Record<string, number>>;
  rubric_scores: Readonly<Record<string, unknown>>;
  missed_items: readonly string[];
  strengths: readonly string[];
  reasoning_errors: readonly string[];
  next_recommendations: readonly string[];
  source_references: readonly string[];
  source_reference_items?: readonly SourceReferenceItem[];
  feedback_summary: string;
}>;

type CaseOption = Readonly<{
  id: string;
  title: string;
  module: string;
  difficulty: string;
  chiefComplaint: string;
  enabled: boolean;
  patientProfile: StudentVisiblePatientProfile;
  openingTaskCard: OpeningTaskCard;
  teachingFocus: CaseTeachingFocus;
  physicalExamOptions: readonly PhysicalExamQuickOption[];
  auxiliaryTestOptions: readonly AuxiliaryTestQuickOption[];
}>;

type CaseSummary = Readonly<{
  case_id: string;
  case_title: string;
  course_module: string;
  difficulty: string;
  chief_complaint: string;
  enabled: boolean;
  patient_profile: StudentVisiblePatientProfile;
  opening_task_card: OpeningTaskCard;
  teaching_focus: CaseTeachingFocus;
  physical_exam_options: readonly PhysicalExamQuickOption[];
  auxiliary_test_options: readonly AuxiliaryTestQuickOption[];
}>;

type CaseListResponse = Readonly<{
  cases: readonly CaseSummary[];
}>;

type SourceReferenceDisplayItem = Readonly<{
  reference: string;
  sourceType: string;
  title: string;
  metadata: Readonly<Record<string, unknown>>;
}>;

type SourceReferenceGroup = Readonly<{
  key: string;
  title: string;
  description: string;
  references: readonly SourceReferenceDisplayItem[];
}>;

const DEFAULT_CASE_ID = "appendicitis_001";

const appendicitisPhysicalExamOptions: readonly PhysicalExamQuickOption[] = [
  { exam_code: "vital.temperature", exam_name_cn: "体温" },
  { exam_code: "abd.inspection", exam_name_cn: "腹部视诊" },
  { exam_code: "abd.palpation.tenderness", exam_name_cn: "McBurney 点压痛" },
  { exam_code: "abd.palpation.rebound", exam_name_cn: "反跳痛（Blumberg 征）" },
  { exam_code: "abd.palpation.guarding", exam_name_cn: "肌紧张" },
  { exam_code: "abd.special.rovsing", exam_name_cn: "Rovsing 征" },
  { exam_code: "abd.special.psoas", exam_name_cn: "腰大肌征" },
];

const appendicitisAuxiliaryTestOptions: readonly AuxiliaryTestQuickOption[] = [
  {
    test_code: "lab.cbc",
    test_name_cn: "血常规",
    category: "实验室",
    invasiveness: "微创",
    cost_hint: "基础",
    diagnostic_role: "supports_primary_diagnosis",
    rules_out: [],
    recommended_stage: "auxiliary_test",
    overuse_warning: null,
  },
  {
    test_code: "lab.crp",
    test_name_cn: "C 反应蛋白",
    category: "实验室",
    invasiveness: "微创",
    cost_hint: "基础",
    diagnostic_role: "supports_primary_diagnosis",
    rules_out: [],
    recommended_stage: "auxiliary_test",
    overuse_warning: null,
  },
  {
    test_code: "img.abd_us",
    test_name_cn: "腹部超声",
    category: "影像",
    invasiveness: "无创",
    cost_hint: "基础",
    diagnostic_role: "supports_primary_diagnosis",
    rules_out: [],
    recommended_stage: "auxiliary_test",
    overuse_warning: null,
  },
  {
    test_code: "lab.urinalysis",
    test_name_cn: "尿常规",
    category: "实验室",
    invasiveness: "无创",
    cost_hint: "基础",
    diagnostic_role: "rules_out_alternative",
    rules_out: ["右侧输尿管结石"],
    recommended_stage: "auxiliary_test",
    overuse_warning: null,
  },
  {
    test_code: "img.abd_ct",
    test_name_cn: "腹部 CT",
    category: "影像",
    invasiveness: "无创",
    cost_hint: "中等",
    diagnostic_role: "supports_primary_diagnosis",
    rules_out: [],
    recommended_stage: "auxiliary_test",
    overuse_warning: "基础证据已足够支持训练推理时，不应把 CT 作为第一步机械申请。",
  },
];

const appendicitisPatientProfile: StudentVisiblePatientProfile = {
  age: "22岁",
  gender: "男",
  occupation: "学生",
  hospital_department: "急诊外科",
};

const appendicitisOpeningTaskCard: OpeningTaskCard = {
  role: "你是急诊外科接诊医生。",
  scenario: "一名22岁男性学生因转移性右下腹痛 24 小时，伴恶心、低热来诊。",
  tasks: [
    "进行有重点的病史采集",
    "判断需要哪些查体",
    "选择必要辅助检查",
    "提出诊断假设和鉴别诊断",
    "最终提交诊断与推理依据",
  ],
};

const emptyTeachingFocus: CaseTeachingFocus = {
  learning_objectives: [],
  common_error_patterns: [],
  recommended_training_path: [],
};

const defaultCaseOption: CaseOption = {
  id: DEFAULT_CASE_ID,
  title: "右下腹痛教学病例",
  module: "腹痛",
  difficulty: "初级",
  chiefComplaint: "转移性右下腹痛 24 小时，伴恶心、低热",
  enabled: true,
  patientProfile: appendicitisPatientProfile,
  openingTaskCard: appendicitisOpeningTaskCard,
  teachingFocus: emptyTeachingFocus,
  physicalExamOptions: appendicitisPhysicalExamOptions,
  auxiliaryTestOptions: appendicitisAuxiliaryTestOptions,
};
const STUDENT_ID = "web_demo";
const DEFAULT_AUTH_EMAIL = "1@1.test";
const DEFAULT_AUTH_PASSWORD = "1";
const ADMIN_APP_URL = process.env.NEXT_PUBLIC_CLINICAL_OSCE_ADMIN_URL ?? "http://127.0.0.1:3001";
const ADMIN_MODEL_CONFIG_URL = `${ADMIN_APP_URL}#model-config`;
const DEPLOYMENT_MODE = process.env.NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE ?? "local-dev";
const PRODUCTION_DEPLOYMENT_MODES = new Set(["single-node-prod", "vertex-prod"]);
const isStudentRuntimeApiConfigEnabled = !PRODUCTION_DEPLOYMENT_MODES.has(DEPLOYMENT_MODE);
const TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE = "请先在 API 配置中应用可用模型，再开始训练。";
const OSCE_DOCK_POSITION_STORAGE_KEY = "clinical_osce_osce_dock_position";
const DIAGNOSIS_TEXTAREA_MAX_HEIGHT = 160;
const OSCE_DOCK_MARGIN = 20;
const OSCE_DOCK_BUTTON_SIZE = 56;
const OSCE_DOCK_DRAG_THRESHOLD = 4;
const PATIENT_REPLY_TYPEWRITER_DELAY_MS = 14;

const apiConfigProviderOptions: readonly ApiConfigProviderOption[] = [
  {
    id: "custom_backend",
    label: "自定义后端",
    defaultModel: "",
    defaultBaseUrl: "http://127.0.0.1:8000",
    defaultProxyUrl: "",
  },
  {
    id: "gemini",
    label: "Gemini Developer API",
    defaultModel: "gemini-3.1-pro-preview",
    defaultBaseUrl: "https://generativelanguage.googleapis.com",
    defaultProxyUrl: "http://127.0.0.1:7897",
  },
  {
    id: "vertex_gemini_adc",
    label: "Vertex Gemini ADC",
    defaultModel: "gemini-3.1-pro-preview",
    defaultBaseUrl: "",
    defaultProxyUrl: "http://127.0.0.1:7897",
  },
  {
    id: "vertex_gemini_api_key",
    label: "Vertex Gemini API Key",
    defaultModel: "gemini-2.5-flash",
    defaultBaseUrl: "",
    defaultProxyUrl: "http://127.0.0.1:7897",
  },
  {
    id: "openai_compatible",
    label: "OpenAI 兼容",
    defaultModel: "gpt-4.1-mini",
    defaultBaseUrl: "https://api.openai.com/v1",
    defaultProxyUrl: "http://127.0.0.1:7897",
  },
  {
    id: "anthropic",
    label: "Anthropic",
    defaultModel: "claude-3-5-sonnet-latest",
    defaultBaseUrl: "https://api.anthropic.com",
    defaultProxyUrl: "http://127.0.0.1:7897",
  },
];

const unavailablePatientProfile: StudentVisiblePatientProfile = {
  age: "未开放",
  gender: "未开放",
  occupation: "未开放",
  hospital_department: "未开放",
};

const unavailableOpeningTaskCard: OpeningTaskCard = {
  role: "病例暂未开放训练。",
  scenario: "该病例仍在整理中。",
  tasks: [],
};

const caseOptions: readonly CaseOption[] = [
  defaultCaseOption,
  {
    id: "pneumonia_001",
    title: "发热咳嗽伴胸痛教学病例",
    module: "发热",
    difficulty: "初级",
    chiefComplaint: "发热、咳嗽 3 天，右侧胸痛 1 天。",
    enabled: false,
    patientProfile: unavailablePatientProfile,
    openingTaskCard: unavailableOpeningTaskCard,
    teachingFocus: emptyTeachingFocus,
    physicalExamOptions: [],
    auxiliaryTestOptions: [],
  },
  {
    id: "hyperthyroid_001",
    title: "心慌、手抖与消瘦教学病例",
    module: "心悸",
    difficulty: "中级",
    chiefComplaint: "心慌、手抖 2 个月，消瘦 1 个月。",
    enabled: false,
    patientProfile: unavailablePatientProfile,
    openingTaskCard: unavailableOpeningTaskCard,
    teachingFocus: emptyTeachingFocus,
    physicalExamOptions: [],
    auxiliaryTestOptions: [],
  },
  {
    id: "acs_001",
    title: "胸痛伴出汗教学病例",
    module: "胸痛",
    difficulty: "中级",
    chiefComplaint: "胸骨后压榨性胸痛 2 小时，伴大汗。",
    enabled: false,
    patientProfile: unavailablePatientProfile,
    openingTaskCard: unavailableOpeningTaskCard,
    teachingFocus: emptyTeachingFocus,
    physicalExamOptions: [],
    auxiliaryTestOptions: [],
  },
  {
    id: "heart_failure_001",
    title: "活动后气短伴夜间憋醒教学病例",
    module: "呼吸困难",
    difficulty: "中级",
    chiefComplaint: "活动后气短 2 周，加重伴夜间憋醒 3 天。",
    enabled: false,
    patientProfile: unavailablePatientProfile,
    openingTaskCard: unavailableOpeningTaskCard,
    teachingFocus: emptyTeachingFocus,
    physicalExamOptions: [],
    auxiliaryTestOptions: [],
  },
];

const stageDefinitions: readonly StageDefinition[] = [
  { key: "case_intro", label: "阅读主诉" },
  { key: "history_taking", label: "问诊" },
  { key: "physical_exam", label: "查体" },
  { key: "auxiliary_test", label: "辅助检查" },
  { key: "diagnosis_submission", label: "诊断提交" },
  { key: "feedback", label: "复盘反馈" },
];

const workflowStepDefinitions: readonly WorkflowStepDefinition[] = [
  { key: "case_intro", label: "进入病例" },
  { key: "history_taking", label: "问诊" },
  { key: "physical_exam", label: "查体" },
  { key: "auxiliary_test", label: "辅助检查" },
  { key: "hypothesis", label: "诊断假设" },
  { key: "diagnosis_submission", label: "提交诊断" },
  { key: "feedback", label: "查看报告" },
];

const evidenceByFactId: Readonly<Record<string, EvidenceItem>> = {
  "appendicitis_001.hf_01": {
    label: "起病时间",
    detail: "24 小时前开始，最初是上腹部隐痛。",
  },
  "appendicitis_001.hf_02": {
    label: "疼痛部位",
    detail: "疼痛后来转移并固定到右下腹。",
  },
  "appendicitis_001.hf_03": {
    label: "伴随表现",
    detail: "伴有恶心，没有明显腹泻。",
  },
  "appendicitis_001.hf_04": {
    label: "既往史",
    detail: "既往体健，无腹部手术史。",
  },
};

const scoreDimensionLabels: Readonly<Record<string, string>> = {
  history_taking: "问诊",
  physical_exam: "查体",
  auxiliary_test: "辅助检查",
  main_diagnosis: "主诊断",
  differential_diagnosis: "鉴别诊断",
  reasoning: "推理链",
};

function getStageClass(status: StageStatus): string {
  if (status === "done") {
    return "border-brand/20 bg-brand/10 text-brand";
  }

  if (status === "active") {
    return "border-brand bg-brand text-white shadow-sm";
  }

  return "border-border bg-muted text-muted-foreground";
}

function getStageStatus(stageKey: string, currentStage: string | undefined): StageStatus {
  const normalizedStage = currentStage === "evaluation" ? "feedback" : currentStage;
  const currentIndex = Math.max(
    stageDefinitions.findIndex((stage) => stage.key === normalizedStage),
    0,
  );
  const targetIndex = stageDefinitions.findIndex((stage) => stage.key === stageKey);

  if (targetIndex < currentIndex) {
    return "done";
  }

  if (targetIndex === currentIndex) {
    return "active";
  }

  return "locked";
}

function getActiveWorkflowStepIndex(session: OsceSession | null, feedbackReport: FeedbackReport | null): number {
  if (!session) {
    return 0;
  }

  if (feedbackReport || session.feedback_report) {
    return 6;
  }

  if (session.final_submission) {
    return 6;
  }

  if (session.student_hypotheses.length > 0) {
    return 5;
  }

  if (session.requested_tests.length > 0) {
    return 4;
  }

  if (session.requested_exams.length > 0) {
    return 3;
  }

  if (session.asked_questions.length > 0 || session.revealed_facts.length > 0) {
    return 2;
  }

  return 1;
}

function getWorkflowStepStatus(stepKey: WorkflowStepDefinition["key"], session: OsceSession | null, feedbackReport: FeedbackReport | null): StageStatus {
  const activeIndex = getActiveWorkflowStepIndex(session, feedbackReport);
  const stepIndex = workflowStepDefinitions.findIndex((step) => step.key === stepKey);

  if (stepIndex < activeIndex) {
    return "done";
  }

  if (stepIndex === activeIndex) {
    return "active";
  }

  return "locked";
}

function getNextWorkflowSuggestion(session: OsceSession | null, feedbackReport: FeedbackReport | null): string {
  if (!session) {
    return "选择病例后，发送问诊或点击训练操作才会创建新会话。";
  }

  if (feedbackReport || session.feedback_report) {
    return "已生成评分报告，可前往训练记录页复盘。";
  }

  if (session.final_submission) {
    return "诊断已提交，请查看评分报告，也可前往训练记录页复盘。";
  }

  if (session.student_hypotheses.length > 0) {
    return "请整理已获得证据，提交最终诊断和诊断依据。";
  }

  if (session.requested_tests.length > 0) {
    return "先记录一个诊断假设，再用已获得证据检查它是否成立。";
  }

  if (session.requested_exams.length > 0) {
    return "你已获得部分查体结果，建议选择基础辅助检查验证当前假设。";
  }

  if (session.asked_questions.length > 0 || session.revealed_facts.length > 0) {
    return "已有问诊线索，建议申请关键查体并观察异常体征。";
  }

  return "请先询问起病、部位、性质、程度和伴随症状。";
}

function buildStructuredReasoning(
  differentialDiagnosis: string,
  supportingEvidence: string,
  exclusionEvidence: string,
  nextStep: string,
): string {
  return [
    `鉴别诊断：${differentialDiagnosis}`,
    `支持依据：${supportingEvidence}`,
    `排除依据：${exclusionEvidence}`,
    `下一步方向：${nextStep}`,
  ].join("\n");
}

function formatStage(stage: string | undefined): string {
  const stageLabel = stageDefinitions.find((definition) => definition.key === stage)?.label;
  return stageLabel ?? "等待会话";
}

function getCoachMessageLabel(content: string): "安全边界" | "答题边界" | "问诊引导" | "过程提示" {
  if (content.includes("本系统仅用于 OSCE 教学模拟训练")) {
    return "安全边界";
  }
  if (content.includes("不能直接告诉你标准答案")) {
    return "答题边界";
  }
  if (content.includes("病例脚本没有提供这方面信息")) {
    return "问诊引导";
  }
  return "过程提示";
}

function getDiagnosticRoleLabel(role: string): string {
  const labels: Readonly<Record<string, string>> = {
    supports_primary_diagnosis: "支持主诊断",
    rules_out_alternative: "排除鉴别",
    risk_stratification: "风险分层",
    contextual_baseline: "基础背景",
  };

  return labels[role] ?? "教学证据";
}

function mapApiMessage(message: ApiMessage, index: number): ChatMessage {
  const id = `${message.role}-${index}-${message.content}`;

  if (message.role === "student") {
    return {
      id,
      speaker: "student",
      label: "学生",
      text: message.content,
    };
  }

  if (message.role === "coach") {
    return {
      id,
      speaker: "coach",
      label: getCoachMessageLabel(message.content),
      text: message.content,
    };
  }

  return {
    id,
    speaker: "patient",
    label: "标准化病人",
    text: message.content,
  };
}

function getReplyMessageMetadata(session: OsceSession, replyText: string): Pick<ChatMessage, "speaker" | "label"> {
  const matchingReplyMessage = [...session.messages].reverse().find(
    (message) => message.content === replyText && (message.role === "coach" || message.role === "patient"),
  );

  if (matchingReplyMessage?.role === "coach") {
    return {
      speaker: "coach",
      label: getCoachMessageLabel(replyText),
    };
  }

  return {
    speaker: "patient",
    label: "标准化病人",
  };
}

function hasMessageWithSpeakerAndText(
  messages: readonly ChatMessage[],
  speaker: ChatMessage["speaker"],
  text: string,
): boolean {
  return messages.some((message) => message.speaker === speaker && message.text === text);
}

function getEvidenceItem(factId: string): EvidenceItem {
  return evidenceByFactId[factId] ?? { label: factId, detail: "后端已披露该结构化事实。" };
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

function getSourceReferenceGroupKey(reference: string): string {
  if (reference.startsWith("case:")) {
    return "case";
  }

  if (reference.startsWith("source:")) {
    return "source";
  }

  if (reference.startsWith("rubric:")) {
    return "rubric";
  }

  if (reference.startsWith("evidence:")) {
    return "evidence";
  }

  return "other";
}

function getSourceReferenceGroupMeta(key: string): Omit<SourceReferenceGroup, "references"> {
  const meta: Readonly<Record<string, Omit<SourceReferenceGroup, "references">>> = {
    case: {
      key: "case",
      title: "病例脚本",
      description: "指向当前训练使用的结构化病例。",
    },
    source: {
      key: "source",
      title: "公开来源",
      description: "指向病例加工时登记的公开数据或参考工程。",
    },
    rubric: {
      key: "rubric",
      title: "rubric 条目",
      description: "指向本次扣分、得分或反馈对应的 rubric 条目。",
    },
    evidence: {
      key: "evidence",
      title: "训练证据",
      description: "指向本轮训练实际命中的问诊事实、查体、检查或诊断证据。",
    },
    other: {
      key: "other",
      title: "其他引用",
      description: "暂未归入固定前缀的来源引用。",
    },
  };

  return meta[key] ?? meta.other;
}

function groupSourceReferences(
  items: readonly SourceReferenceItem[],
  fallbackReferences: readonly string[],
): readonly SourceReferenceGroup[] {
  const groupOrder = ["case", "rubric", "source", "evidence", "other"];
  const displayItems = items.length > 0
    ? items.map((item) => ({
        reference: item.reference,
        sourceType: item.source_type,
        title: item.title,
        metadata: item.metadata,
      }))
    : fallbackReferences.map((reference) => ({
        reference,
        sourceType: getSourceReferenceGroupKey(reference),
        title: getSourceReferenceLabel(reference),
        metadata: {},
      }));
  const groupedReferences = displayItems.reduce<Record<string, SourceReferenceDisplayItem[]>>((groups, item) => {
    const key = item.sourceType || getSourceReferenceGroupKey(item.reference);
    return {
      ...groups,
      [key]: [...(groups[key] ?? []), item],
    };
  }, {});

  return groupOrder
    .filter((key) => (groupedReferences[key]?.length ?? 0) > 0)
    .map((key) => ({
      ...getSourceReferenceGroupMeta(key),
      references: groupedReferences[key] ?? [],
    }));
}

function getScorePercent(score: number, maxScore: number): number {
  if (maxScore <= 0) {
    return 0;
  }

  return Math.min(Math.round((score / maxScore) * 100), 100);
}

function isRubricScoreItem(value: unknown): value is RubricScoreItem {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return typeof candidate.dimension_id === "string" && typeof candidate.max_score === "number";
}

function getDimensionMaxScoresFromRubricScores(rubricScores: Readonly<Record<string, unknown>> | undefined): Readonly<Record<string, number>> {
  const dimensionMaxScores: Record<string, number> = {};
  for (const rubricScore of Object.values(rubricScores ?? {})) {
    if (isRubricScoreItem(rubricScore)) {
      dimensionMaxScores[rubricScore.dimension_id] = (dimensionMaxScores[rubricScore.dimension_id] ?? 0) + rubricScore.max_score;
    }
  }
  return dimensionMaxScores;
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function getBoundedOsceDockPosition(x: number, y: number, side: OsceDockSide): OsceDockPosition {
  if (typeof window === "undefined") {
    return {
      x: OSCE_DOCK_MARGIN,
      y: OSCE_DOCK_MARGIN,
      side,
      isReady: false,
    };
  }

  const maxX = Math.max(OSCE_DOCK_MARGIN, window.innerWidth - OSCE_DOCK_BUTTON_SIZE - OSCE_DOCK_MARGIN);
  const maxY = Math.max(OSCE_DOCK_MARGIN, window.innerHeight - OSCE_DOCK_BUTTON_SIZE - OSCE_DOCK_MARGIN);

  return {
    x: clampNumber(x, OSCE_DOCK_MARGIN, maxX),
    y: clampNumber(y, OSCE_DOCK_MARGIN, maxY),
    side,
    isReady: true,
  };
}

function getSideSnappedOsceDockPosition(side: OsceDockSide, y: number): OsceDockPosition {
  if (typeof window === "undefined") {
    return getBoundedOsceDockPosition(OSCE_DOCK_MARGIN, y, side);
  }

  const snappedX = side === "left" ? OSCE_DOCK_MARGIN : window.innerWidth - OSCE_DOCK_BUTTON_SIZE - OSCE_DOCK_MARGIN;
  return getBoundedOsceDockPosition(snappedX, y, side);
}

function getSnappedOsceDockPosition(x: number, y: number): OsceDockPosition {
  if (typeof window === "undefined") {
    return getSideSnappedOsceDockPosition("right", y);
  }

  const side: OsceDockSide = x + OSCE_DOCK_BUTTON_SIZE / 2 < window.innerWidth / 2 ? "left" : "right";
  return getSideSnappedOsceDockPosition(side, y);
}

function createDefaultOsceDockPosition(): OsceDockPosition {
  if (typeof window === "undefined") {
    return {
      x: OSCE_DOCK_MARGIN,
      y: OSCE_DOCK_MARGIN,
      side: "right",
      isReady: false,
    };
  }

  return getSideSnappedOsceDockPosition("right", window.innerHeight - OSCE_DOCK_BUTTON_SIZE - OSCE_DOCK_MARGIN);
}

function loadOsceDockPosition(): OsceDockPosition {
  const defaultPosition = createDefaultOsceDockPosition();

  if (typeof window === "undefined") {
    return defaultPosition;
  }

  try {
    const storedValue = window.localStorage.getItem(OSCE_DOCK_POSITION_STORAGE_KEY);
    if (!storedValue) {
      return defaultPosition;
    }

    const storedPosition = JSON.parse(storedValue) as Partial<OsceDockPosition>;
    const side: OsceDockSide = storedPosition.side === "left" || storedPosition.side === "right" ? storedPosition.side : defaultPosition.side;
    const y = typeof storedPosition.y === "number" ? storedPosition.y : defaultPosition.y;
    return getSideSnappedOsceDockPosition(side, y);
  } catch {
    return defaultPosition;
  }
}

function saveOsceDockPosition(position: OsceDockPosition): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(OSCE_DOCK_POSITION_STORAGE_KEY, JSON.stringify({ side: position.side, y: position.y }));
}

function mapCaseSummary(caseSummary: CaseSummary): CaseOption {
  return {
    id: caseSummary.case_id,
    title: caseSummary.case_title,
    module: caseSummary.course_module,
    difficulty: caseSummary.difficulty,
    chiefComplaint: caseSummary.chief_complaint,
    enabled: caseSummary.enabled,
    patientProfile: caseSummary.patient_profile,
    openingTaskCard: caseSummary.opening_task_card,
    teachingFocus: caseSummary.teaching_focus,
    physicalExamOptions: caseSummary.physical_exam_options,
    auxiliaryTestOptions: caseSummary.auxiliary_test_options,
  };
}

async function getRequestErrorMessage(response: Response): Promise<string> {
  if (response.status === 401) {
    return "请先登录后再继续训练。";
  }

  const detail = await response.text();
  if (!detail) {
    return `请求失败：${response.status}`;
  }

  try {
    const payload = JSON.parse(detail) as Readonly<{ detail?: unknown }>;
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    return detail;
  }

  return detail;
}

async function requestJson<TResponse>(path: string, init: RequestInit): Promise<TResponse> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");

  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers,
  });

  if (!response.ok) {
    throw new Error(await getRequestErrorMessage(response));
  }

  return (await response.json()) as TResponse;
}

function isApiConfigProvider(value: unknown): value is ApiConfigProvider {
  return apiConfigProviderOptions.some((option) => option.id === value);
}

function normalizeApiConfigProvider(value: unknown, fallbackProvider: ApiConfigProvider): ApiConfigProvider {
  if (value === "local_backend") {
    return "custom_backend";
  }
  return isApiConfigProvider(value) ? value : fallbackProvider;
}

function getApiConfigProviderOption(provider: ApiConfigProvider): ApiConfigProviderOption {
  return apiConfigProviderOptions.find((option) => option.id === provider) ?? apiConfigProviderOptions[0];
}

function createDefaultStudentApiConfig(): StudentApiConfig {
  const defaultProvider = apiConfigProviderOptions[0];
  return {
    provider: defaultProvider.id,
    apiKey: "",
    model: "",
    baseUrl: "",
    proxyUrl: "",
  };
}

function createStudentApiConfigFromRuntime(runtimeConfig: StudentApiConfigRuntimeResponse): StudentApiConfig {
  if (!runtimeConfig.active || !isApiConfigProvider(runtimeConfig.provider)) {
    return createDefaultStudentApiConfig();
  }
  return {
    provider: runtimeConfig.provider,
    apiKey: "",
    model: runtimeConfig.model,
    baseUrl: runtimeConfig.base_url,
    proxyUrl: runtimeConfig.proxy_url,
  };
}

function testStudentApiConfigConnection(config: StudentApiConfig): Promise<StudentApiConfigTestResponse> {
  return requestJson<StudentApiConfigTestResponse>("/api/model-config/test", {
    method: "POST",
    body: JSON.stringify({
      provider: config.provider,
      api_key: config.apiKey,
      model: config.model,
      base_url: config.baseUrl,
      proxy_url: config.proxyUrl,
    }),
  });
}

function applyStudentApiConfigToRuntime(config: StudentApiConfig): Promise<StudentApiConfigRuntimeResponse> {
  return requestJson<StudentApiConfigRuntimeResponse>("/api/model-config/runtime", {
    method: "POST",
    body: JSON.stringify({
      provider: config.provider,
      api_key: config.apiKey,
      model: config.model,
      base_url: config.baseUrl,
      proxy_url: config.proxyUrl,
    }),
  });
}

function getStudentRuntimeApiConfig(): Promise<StudentApiConfigRuntimeResponse> {
  return requestJson<StudentApiConfigRuntimeResponse>("/api/model-config/runtime", {
    method: "GET",
  });
}

function isRuntimeStudentApiProvider(provider: ApiConfigProvider): boolean {
  return provider === "openai_compatible" || provider === "anthropic" || provider === "vertex_gemini_adc" || provider === "vertex_gemini_api_key";
}

function formatRuntimeApiConfigSummary(runtimeConfig: StudentApiConfigRuntimeResponse | null): string {
  if (!runtimeConfig) {
    return "未启用，使用本地确定性回退";
  }
  if (!runtimeConfig.active) {
    return runtimeConfig.message ?? "未启用，使用本地确定性回退";
  }
  const providerLabel = getApiConfigProviderOption(runtimeConfig.provider || "custom_backend").label;
  const details = [
    runtimeConfig.model ? `模型 ${runtimeConfig.model}` : "",
    runtimeConfig.base_url ? `地址 ${runtimeConfig.base_url}` : "",
    runtimeConfig.proxy_url ? `代理 ${runtimeConfig.proxy_url}` : "",
  ].filter(Boolean);
  return [providerLabel, ...details].join(" · ");
}

async function getCases(): Promise<readonly CaseOption[]> {
  const response = await requestJson<CaseListResponse>("/api/cases", {
    method: "GET",
  });
  return response.cases.map(mapCaseSummary);
}

function createSession(caseId: string): Promise<OsceSession> {
  return requestJson<OsceSession>("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ case_id: caseId, student_id: STUDENT_ID }),
  });
}

function sendHistoryMessage(sessionId: string, message: string): Promise<OsceSession> {
  return requestJson<OsceSession>(`/api/sessions/${sessionId}/message`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

function requestPhysicalExam(sessionId: string, examCode: string): Promise<PhysicalExamResponse> {
  return requestJson<PhysicalExamResponse>(`/api/sessions/${sessionId}/physical-exam`, {
    method: "POST",
    body: JSON.stringify({ exam_code: examCode }),
  });
}

function requestAuxiliaryTest(sessionId: string, testCode: string): Promise<AuxiliaryTestResponse> {
  return requestJson<AuxiliaryTestResponse>(`/api/sessions/${sessionId}/auxiliary-test`, {
    method: "POST",
    body: JSON.stringify({ test_code: testCode }),
  });
}

function recordHypothesis(sessionId: string, hypothesis: string): Promise<OsceSession> {
  return requestJson<OsceSession>(`/api/sessions/${sessionId}/hypotheses`, {
    method: "POST",
    body: JSON.stringify({ hypothesis }),
  });
}

function requestHint(sessionId: string): Promise<HintResponse> {
  return requestJson<HintResponse>(`/api/sessions/${sessionId}/hint`, {
    method: "POST",
  });
}

function submitDiagnosis(sessionId: string, diagnosis: string, reasoning: string): Promise<OsceSession> {
  return requestJson<OsceSession>(`/api/sessions/${sessionId}/submit-diagnosis`, {
    method: "POST",
    body: JSON.stringify({ diagnosis, reasoning }),
  });
}

function getSession(sessionId: string): Promise<OsceSession> {
  return requestJson<OsceSession>(`/api/me/sessions/${sessionId}`, {
    method: "GET",
  });
}

function getSessionReport(sessionId: string): Promise<FeedbackReport> {
  return requestJson<FeedbackReport>(`/api/me/sessions/${sessionId}/report`, {
    method: "GET",
  });
}

function Panel({
  title,
  description,
  action,
  children,
}: Readonly<{
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}>) {
  return (
    <section className="rounded-xl border border-border bg-card p-4 shadow-xs">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
          {description ? <p className="text-xs leading-5 text-muted-foreground">{description}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function ChevronIcon({ isOpen }: Readonly<{ isOpen: boolean }>) {
  return (
    <svg
      aria-hidden="true"
      className={`size-4 transition-transform ${isOpen ? "rotate-180" : ""}`}
      fill="none"
      viewBox="0 0 24 24"
    >
      <path d="M6 9l6 6 6-6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
    </svg>
  );
}

function CollapsiblePanel({
  title,
  description,
  isOpen,
  onToggle,
  maxContentHeightClass = "max-h-64",
  children,
}: Readonly<{
  title: string;
  description?: string;
  isOpen: boolean;
  onToggle: () => void;
  maxContentHeightClass?: string;
  children: ReactNode;
}>) {
  return (
    <Panel
      action={
        <button
          aria-expanded={isOpen}
          aria-label={`${isOpen ? "收起" : "展开"}${title}`}
          className="flex size-8 items-center justify-center rounded-md border border-border bg-background text-muted-foreground shadow-xs transition hover:bg-accent hover:text-foreground"
          onClick={onToggle}
          type="button"
        >
          <ChevronIcon isOpen={isOpen} />
        </button>
      }
      title={title}
      description={description}
    >
      {isOpen ? <div className={`${maxContentHeightClass} overflow-y-scroll pr-1 student-rail-scrollbar`} onScroll={handleStudentRailScroll}>{children}</div> : null}
    </Panel>
  );
}

function resizeTextareaToContent(textarea: HTMLTextAreaElement): void {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, DIAGNOSIS_TEXTAREA_MAX_HEIGHT)}px`;
  textarea.style.overflowY = textarea.scrollHeight > DIAGNOSIS_TEXTAREA_MAX_HEIGHT ? "auto" : "hidden";
}

const studentRailScrollbarTimers = new WeakMap<HTMLElement, number>();

function handleStudentRailScroll(event: UIEvent<HTMLElement>): void {
  const scrollElement = event.currentTarget;
  scrollElement.classList.add("is-student-scrollbar-active");
  const previousTimer = studentRailScrollbarTimers.get(scrollElement);
  if (previousTimer) {
    window.clearTimeout(previousTimer);
  }
  const nextTimer = window.setTimeout(() => {
    scrollElement.classList.remove("is-student-scrollbar-active");
    studentRailScrollbarTimers.delete(scrollElement);
  }, 900);
  studentRailScrollbarTimers.set(scrollElement, nextTimer);
}

function PendingThinkingIndicator() {
  return (
    <span aria-label="判断中" className="inline-flex items-center gap-1">
      <span>判断中</span>
      <span aria-hidden="true" className="inline-flex gap-0.5">
        {[0, 1, 2].map((dotIndex) => (
          <span className="clinical-osce-thinking-dot" key={dotIndex} style={{ animationDelay: `${dotIndex * 140}ms` }}>
            .
          </span>
        ))}
      </span>
    </span>
  );
}

function CoverageMapSection({ items, title }: Readonly<{ items: readonly CoverageMapItem[]; title: string }>) {
  const coveredCount = items.filter((item) => item.status === "covered").length;

  return (
    <section className="rounded-xl border border-border bg-muted/40 p-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">{title}</h3>
        <span className="rounded-full border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground">
          {coveredCount}/{items.length}
        </span>
      </div>
      <div className="mt-3 grid gap-2">
        {items.length > 0 ? (
          items.map((item) => {
            const visibleLabel = item.status === "covered" ? item.label : `未覆盖素材：${item.id}`;
            return (
              <div className="rounded-lg border border-border bg-background px-3 py-2 text-xs" key={item.id}>
                <div className="flex items-center justify-between gap-3">
                  <span className="min-w-0 truncate">{visibleLabel}</span>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${
                      item.status === "covered" ? "bg-[#EEF6EF] text-[#236146]" : "bg-muted text-muted-foreground"
                    }`}
                  >
                    {item.status === "covered" ? "已覆盖" : "待覆盖"}
                  </span>
                </div>
              </div>
            );
          })
        ) : (
          <p className="rounded-lg border border-dashed border-border bg-background px-3 py-2 text-xs text-muted-foreground">
            暂无素材项。
          </p>
        )}
      </div>
    </section>
  );
}

function CoverageMap({ trainingProgress }: Readonly<{ trainingProgress: TrainingProgress }>) {
  return (
    <div className="grid gap-3">
      <CoverageMapSection items={trainingProgress.coverage_map.history} title="问诊线索覆盖" />
      <CoverageMapSection items={trainingProgress.coverage_map.physical_exam} title="查体项目覆盖" />
      <CoverageMapSection items={trainingProgress.coverage_map.auxiliary_test} title="辅助检查覆盖" />
      <CoverageMapSection items={trainingProgress.coverage_map.reasoning} title="推理证据覆盖" />
    </div>
  );
}

function CaseSelectionPrompt({ onDismiss, selectedCase }: Readonly<{ onDismiss: () => void; selectedCase: CaseOption | null }>) {
  return (
    <div className="flex justify-center">
      <div className="relative w-full max-w-xl rounded-xl border border-brand/20 bg-brand/5 p-4 text-center shadow-xs">
        <button
          aria-label="关闭训练准备提示"
          className="absolute right-3 top-3 inline-flex size-7 items-center justify-center rounded-full border border-brand/20 bg-background text-sm font-medium whitespace-nowrap text-brand transition hover:bg-brand/10"
          onClick={onDismiss}
          type="button"
        >
          ×
        </button>
        <p className="text-xs font-medium text-brand">训练准备提示</p>
        <p className="mt-2 text-sm font-semibold text-foreground">
          {selectedCase ? `已选择${selectedCase.title}` : "请先选择一个病例"}
        </p>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {selectedCase
            ? "发送第一句问诊或点击训练操作后，系统才会创建新的 OSCE 训练会话。"
            : "进入病例后，系统会显示开局任务卡；在首次训练动作前不会创建训练记录。"}
        </p>
        <Link
          className="mt-3 inline-flex items-center justify-center rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover"
          href="/cases"
        >
          选择病例
        </Link>
      </div>
    </div>
  );
}

function OpeningTaskCardMessage({ openingTaskCard }: Readonly<{ openingTaskCard: OpeningTaskCard | null }>) {
  if (!openingTaskCard) {
    return null;
  }

  return (
    <div className="mx-auto w-full max-w-lg rounded-2xl border border-brand/30 bg-[#FFF8E8] p-4">
      <p className="text-xs font-semibold text-[#8A5A00]">开局任务卡</p>
      <p className="mt-2 text-sm font-semibold text-foreground">{openingTaskCard.role}</p>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">{openingTaskCard.scenario}</p>
      <ul className="mt-3 flex flex-wrap gap-2 text-xs leading-5">
        {openingTaskCard.tasks.map((task) => (
          <li className="rounded-full border border-brand/20 bg-background px-3 py-1.5" key={task}>
            {task}
          </li>
        ))}
      </ul>
    </div>
  );
}

function HomeContent() {
  const searchParams = useSearchParams();
  const requestedSessionId = searchParams.get("session_id");
  const initialCaseId = searchParams.get("case_id");
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(initialCaseId);
  const [caseOptionsState, setCaseOptionsState] = useState<readonly CaseOption[]>(caseOptions);
  const [isOsceDockOpen, setIsOsceDockOpen] = useState(false);
  const [osceDockMenuGroup, setOsceDockMenuGroup] = useState<OsceDockMenuGroup | null>(null);
  const [isApiConfigHelpOpen, setIsApiConfigHelpOpen] = useState(false);
  const [studentApiConfig, setStudentApiConfig] = useState<StudentApiConfig>(createDefaultStudentApiConfig());
  const [runtimeApiConfig, setRuntimeApiConfig] = useState<StudentApiConfigRuntimeResponse | null>(null);
  const [apiConfigStatusText, setApiConfigStatusText] = useState("配置按当前登录账号保存在后端；密钥不会回显。");
  const [apiConfigTestResult, setApiConfigTestResult] = useState<StudentApiConfigTestResponse | null>(null);
  const [isTestingStudentApiConfig, setIsTestingStudentApiConfig] = useState(false);
  const [isApplyingStudentApiConfig, setIsApplyingStudentApiConfig] = useState(false);
  const isTrainingModelConfigReady = Boolean(runtimeApiConfig?.active);
  const [rightPanelOpenStates, setRightPanelOpenStates] = useState<Record<RightPanelKey, boolean>>({
    focus: false,
    agent: false,
    evidence: true,
    hypotheses: true,
    report: true,
  });
  const [session, setSession] = useState<OsceSession | null>(null);
  const [inputValue, setInputValue] = useState("");
  const [statusText, setStatusText] = useState("选择病例后，发送问诊或点击训练操作才会创建新会话。");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [optimisticHistoryMessage, setOptimisticHistoryMessage] = useState<ChatMessage | null>(null);
  const [pendingPatientMessage, setPendingPatientMessage] = useState<ChatMessage | null>(null);
  const [isCasePreparationPromptDismissed, setIsCasePreparationPromptDismissed] = useState(false);
  const [openProcedureActionGroup, setOpenProcedureActionGroup] = useState<ProcedureActionGroup | null>(null);
  const [isRequestingExam, setIsRequestingExam] = useState(false);
  const [isRequestingTest, setIsRequestingTest] = useState(false);
  const [hypothesisValue, setHypothesisValue] = useState("");
  const [isRecordingHypothesis, setIsRecordingHypothesis] = useState(false);
  const [isRequestingHint, setIsRequestingHint] = useState(false);
  const [diagnosisValue, setDiagnosisValue] = useState("");
  const [differentialDiagnosisValue, setDifferentialDiagnosisValue] = useState("");
  const [supportingEvidenceValue, setSupportingEvidenceValue] = useState("");
  const [exclusionEvidenceValue, setExclusionEvidenceValue] = useState("");
  const [nextStepValue, setNextStepValue] = useState("");
  const [isDiagnosisComposerOpen, setIsDiagnosisComposerOpen] = useState(false);
  const [isSubmittingDiagnosis, setIsSubmittingDiagnosis] = useState(false);
  const [feedbackReport, setFeedbackReport] = useState<FeedbackReport | null>(null);
  const [procedureResults, setProcedureResults] = useState<readonly ProcedureResult[]>([]);
  const [selectedProcedureResult, setSelectedProcedureResult] = useState<ProcedureResult | null>(null);
  const [isCoverageMapOpen, setIsCoverageMapOpen] = useState(false);
  const [isPatientProfileOpen, setIsPatientProfileOpen] = useState(false);
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [isAuthDialogOpen, setIsAuthDialogOpen] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authEmail, setAuthEmail] = useState(DEFAULT_AUTH_EMAIL);
  const [authPassword, setAuthPassword] = useState(DEFAULT_AUTH_PASSWORD);
  const [authDisplayName, setAuthDisplayName] = useState("");
  const [authErrorText, setAuthErrorText] = useState<string | null>(null);
  const [isAccountMenuOpen, setIsAccountMenuOpen] = useState(false);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [isSubmittingAuth, setIsSubmittingAuth] = useState(false);
  const [osceDockPosition, setOsceDockPosition] = useState<OsceDockPosition>({
    x: OSCE_DOCK_MARGIN,
    y: OSCE_DOCK_MARGIN,
    side: "right",
    isReady: false,
  });
  const osceDockDragRef = useRef<OsceDockDragState | null>(null);
  const suppressOsceDockClickRef = useRef(false);
  const osceDockContainerRef = useRef<HTMLDivElement | null>(null);
  const procedureActionContainerRef = useRef<HTMLDivElement | null>(null);
  const chatScrollContainerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!isStudentRuntimeApiConfigEnabled || isCheckingAuth) {
      return;
    }

    if (!authUser) {
      setRuntimeApiConfig(null);
      setStudentApiConfig(createDefaultStudentApiConfig());
      return;
    }

    let isMounted = true;
    async function loadRuntimeApiConfig() {
      try {
        const runtimeConfig = await getStudentRuntimeApiConfig();
        if (isMounted) {
          setRuntimeApiConfig(runtimeConfig);
          setStudentApiConfig(createStudentApiConfigFromRuntime(runtimeConfig));
        }
      } catch {
        if (isMounted) {
          setRuntimeApiConfig(null);
          setStudentApiConfig(createDefaultStudentApiConfig());
        }
      }
    }

    void loadRuntimeApiConfig();
    return () => {
      isMounted = false;
    };
  }, [authUser, isCheckingAuth]);

  useEffect(() => {
    if (!isApiConfigHelpOpen || !isStudentRuntimeApiConfigEnabled || !authUser) {
      return;
    }

    let isMounted = true;
    async function loadRuntimeApiConfig() {
      try {
        const runtimeConfig = await getStudentRuntimeApiConfig();
        if (isMounted) {
          setRuntimeApiConfig(runtimeConfig);
          setStudentApiConfig(createStudentApiConfigFromRuntime(runtimeConfig));
        }
      } catch {
        if (isMounted) {
          setRuntimeApiConfig(null);
        }
      }
    }

    void loadRuntimeApiConfig();
    return () => {
      isMounted = false;
    };
  }, [authUser, isApiConfigHelpOpen]);

  useEffect(() => {
    let isMounted = true;

    async function loadAuthUser() {
      try {
        const currentUser = await getCurrentUser();
        if (!isMounted) {
          return;
        }

        setAuthUser(currentUser);
        setIsAuthDialogOpen(currentUser === null);
      } catch (error) {
        if (!isMounted) {
          return;
        }

        setAuthErrorText(error instanceof Error ? error.message : "读取登录状态失败。");
        setIsAuthDialogOpen(true);
      } finally {
        if (isMounted) {
          setIsCheckingAuth(false);
        }
      }
    }

    loadAuthUser();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    let isMounted = true;

    async function loadCases() {
      try {
        const nextCaseOptions = await getCases();
        if (!isMounted || nextCaseOptions.length === 0) {
          return;
        }

        setCaseOptionsState(nextCaseOptions);
        setSelectedCaseId((currentSelectedCaseId) =>
          currentSelectedCaseId && nextCaseOptions.some((caseOption) => caseOption.id === currentSelectedCaseId)
            ? currentSelectedCaseId
            : null,
        );
      } catch (error) {
        if (!isMounted) {
          return;
        }

        setErrorText(error instanceof Error ? error.message : "读取病例列表失败。");
      }
    }

    loadCases();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    setIsCasePreparationPromptDismissed(false);
  }, [selectedCaseId]);

  useEffect(() => {
    if (isCheckingAuth) {
      return;
    }

    if (!authUser) {
      setIsCreating(false);
      setSession(null);
      setStatusText("请先登录后再开始或恢复训练。");
      return;
    }

    if (!requestedSessionId) {
      setIsCreating(false);
      setSession(null);
      setFeedbackReport(null);
      setProcedureResults([]);
      setSelectedProcedureResult(null);
      setIsPatientProfileOpen(false);
      setStatusText(
        selectedCaseId
          ? isTrainingModelConfigReady
            ? "已选择病例，发送问诊或点击训练操作后开始新会话。"
            : TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE
          : "请选择病例后再开始训练。",
      );
      setErrorText(null);
      return;
    }

    const sessionIdToRestore = requestedSessionId;
    let isMounted = true;

    async function loadRequestedSession() {
      setIsCreating(true);
      setSession(null);
      setInputValue("");
      setHypothesisValue("");
      setDiagnosisValue("");
      setDifferentialDiagnosisValue("");
      setSupportingEvidenceValue("");
      setExclusionEvidenceValue("");
      setNextStepValue("");
      setFeedbackReport(null);
      setProcedureResults([]);
      setSelectedProcedureResult(null);
      setIsPatientProfileOpen(false);
      setStatusText("正在恢复后端训练会话...");
      setErrorText(null);

      try {
        const nextSession = await getSession(sessionIdToRestore);
        if (!isMounted) {
          return;
        }

        setSession(nextSession);
        setSelectedCaseId(nextSession.case_id);
        setStatusText("已恢复后端训练会话，可以继续训练。");
        setErrorText(null);
      } catch (error) {
        if (!isMounted) {
          return;
        }

        const message = error instanceof Error ? error.message : "恢复训练会话失败。";
        if (message === "请先登录后再继续训练。") {
          setAuthUser(null);
          setIsAuthDialogOpen(true);
        }
        setStatusText(message === "请先登录后再继续训练。" ? message : "后端未连接，页面暂时只显示工作台框架。");
        setErrorText(message);
      } finally {
        if (isMounted) {
          setIsCreating(false);
        }
      }
    }

    loadRequestedSession();

    return () => {
      isMounted = false;
    };
  }, [authUser, isCheckingAuth, isTrainingModelConfigReady, requestedSessionId, selectedCaseId]);

  useEffect(() => {
    function snapDockToCurrentEdge() {
      setOsceDockPosition((currentPosition) => {
        if (!currentPosition.isReady) {
          return loadOsceDockPosition();
        }

        const snappedPosition = getSideSnappedOsceDockPosition(currentPosition.side, currentPosition.y);
        saveOsceDockPosition(snappedPosition);
        return snappedPosition;
      });
    }

    snapDockToCurrentEdge();
    window.addEventListener("resize", snapDockToCurrentEdge);

    return () => {
      window.removeEventListener("resize", snapDockToCurrentEdge);
    };
  }, []);

  useEffect(() => {
    function closeSecondaryMenusOnOutsidePointerDown(event: globalThis.PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }

      if (isOsceDockOpen && osceDockContainerRef.current && !osceDockContainerRef.current.contains(target)) {
        closeOsceDock();
      }

      if (osceDockMenuGroup && osceDockContainerRef.current && !osceDockContainerRef.current.contains(target)) {
        setOsceDockMenuGroup(null);
      }

      if (openProcedureActionGroup && procedureActionContainerRef.current && !procedureActionContainerRef.current.contains(target)) {
        setOpenProcedureActionGroup(null);
      }
    }

    document.addEventListener("pointerdown", closeSecondaryMenusOnOutsidePointerDown);
    return () => {
      document.removeEventListener("pointerdown", closeSecondaryMenusOnOutsidePointerDown);
    };
  }, [isOsceDockOpen, openProcedureActionGroup, osceDockMenuGroup]);

  useEffect(() => {
    if (!feedbackReport && !session?.feedback_report) {
      return;
    }

    setRightPanelOpenStates((currentStates) =>
      currentStates.report ? currentStates : { ...currentStates, report: true },
    );
  }, [feedbackReport, session?.feedback_report]);

  function toggleRightPanel(panelKey: RightPanelKey) {
    setRightPanelOpenStates((currentStates) => ({
      ...currentStates,
      [panelKey]: !currentStates[panelKey],
    }));
  }

  function getOsceDockSideFromX(x: number): OsceDockSide {
    if (typeof window === "undefined") {
      return "left";
    }

    return x + OSCE_DOCK_BUTTON_SIZE / 2 < window.innerWidth / 2 ? "left" : "right";
  }

  function handleOsceDockPointerDown(event: PointerEvent<HTMLButtonElement>) {
    const buttonRect = event.currentTarget.getBoundingClientRect();
    event.currentTarget.setPointerCapture(event.pointerId);
    osceDockDragRef.current = {
      pointerId: event.pointerId,
      startPointerX: event.clientX,
      startPointerY: event.clientY,
      startX: buttonRect.left,
      startY: buttonRect.top,
      moved: false,
    };
    setOsceDockPosition(getBoundedOsceDockPosition(buttonRect.left, buttonRect.top, getOsceDockSideFromX(buttonRect.left)));
  }

  function handleOsceDockPointerMove(event: PointerEvent<HTMLButtonElement>) {
    const dragState = osceDockDragRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return;
    }

    const deltaX = event.clientX - dragState.startPointerX;
    const deltaY = event.clientY - dragState.startPointerY;
    const hasMoved = dragState.moved || Math.abs(deltaX) > OSCE_DOCK_DRAG_THRESHOLD || Math.abs(deltaY) > OSCE_DOCK_DRAG_THRESHOLD;
    const nextX = dragState.startX + deltaX;
    const nextY = dragState.startY + deltaY;

    osceDockDragRef.current = {
      ...dragState,
      moved: hasMoved,
    };

    if (!hasMoved) {
      return;
    }

    event.preventDefault();
    suppressOsceDockClickRef.current = true;
    setOsceDockPosition(getBoundedOsceDockPosition(nextX, nextY, getOsceDockSideFromX(nextX)));
  }

  function handleOsceDockPointerUp(event: PointerEvent<HTMLButtonElement>) {
    const dragState = osceDockDragRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return;
    }

    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }

    osceDockDragRef.current = null;

    if (!dragState.moved) {
      return;
    }

    event.preventDefault();
    const nextX = dragState.startX + event.clientX - dragState.startPointerX;
    const nextY = dragState.startY + event.clientY - dragState.startPointerY;
    const snappedPosition = getSnappedOsceDockPosition(nextX, nextY);
    saveOsceDockPosition(snappedPosition);
    setOsceDockPosition(snappedPosition);
    window.setTimeout(() => {
      suppressOsceDockClickRef.current = false;
    }, 0);
  }

  function handleOsceDockPointerCancel(event: PointerEvent<HTMLButtonElement>) {
    const dragState = osceDockDragRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return;
    }

    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }

    osceDockDragRef.current = null;
    setOsceDockPosition((currentPosition) => {
      const snappedPosition = getSnappedOsceDockPosition(currentPosition.x, currentPosition.y);
      saveOsceDockPosition(snappedPosition);
      return snappedPosition;
    });
    window.setTimeout(() => {
      suppressOsceDockClickRef.current = false;
    }, 0);
  }

  function selectOsceDockMenuGroup(nextGroup: OsceDockMenuGroup): void {
    setOsceDockMenuGroup((currentGroup) => (currentGroup === nextGroup ? null : nextGroup));
  }

  function closeOsceDock(): void {
    setOsceDockMenuGroup(null);
    setIsOsceDockOpen(false);
  }

  function handleStudentApiProviderChange(provider: ApiConfigProvider): void {
    setStudentApiConfig((currentConfig) => ({
      ...currentConfig,
      provider,
      apiKey: "",
      model: "",
      baseUrl: "",
      proxyUrl: "",
    }));
    setApiConfigTestResult(null);
    setApiConfigStatusText(
      isRuntimeStudentApiProvider(provider)
        ? "已切换服务端，保存后会按当前登录账号持久化并应用到训练智能体。"
        : "已切换服务端，可测试连通性；训练智能体请使用 OpenAI 兼容、Anthropic 或 Vertex Gemini。",
    );
  }

  async function handleSaveStudentApiConfig(): Promise<void> {
    setApiConfigTestResult(null);
    if (!authUser) {
      setApiConfigStatusText("请先登录后再保存 API 配置。");
      setIsAuthDialogOpen(true);
      return;
    }
    if (!isRuntimeStudentApiProvider(studentApiConfig.provider)) {
      setApiConfigStatusText("当前服务端仅用于连通性测试；训练智能体请使用 OpenAI 兼容、Anthropic 或 Vertex Gemini。");
      return;
    }

    setIsApplyingStudentApiConfig(true);
    setApiConfigStatusText("正在保存到当前账号并应用到后端运行时...");
    try {
      const result = await applyStudentApiConfigToRuntime(studentApiConfig);
      setRuntimeApiConfig(result);
      setStudentApiConfig(createStudentApiConfigFromRuntime(result));
      setApiConfigStatusText(result.message);
    } catch (error) {
      setApiConfigStatusText(error instanceof Error ? error.message : "应用到后端运行时失败。");
    } finally {
      setIsApplyingStudentApiConfig(false);
    }
  }

  async function handleTestStudentApiConfig(): Promise<void> {
    setIsTestingStudentApiConfig(true);
    setApiConfigStatusText("正在测试连通性...");
    setApiConfigTestResult(null);
    try {
      const result = await testStudentApiConfigConnection(studentApiConfig);
      setApiConfigTestResult(result);
      setApiConfigStatusText(result.message);
    } catch (error) {
      setApiConfigStatusText(error instanceof Error ? error.message : "连通性测试失败。");
      setApiConfigTestResult(null);
    } finally {
      setIsTestingStudentApiConfig(false);
    }
  }

  function handleOsceDockButtonClick() {
    if (suppressOsceDockClickRef.current) {
      suppressOsceDockClickRef.current = false;
      return;
    }

    if (!isOsceDockOpen) {
      setOsceDockMenuGroup(null);
    }
    setIsOsceDockOpen((isOpen) => !isOpen);
  }

  const selectedCase = useMemo(
    () => selectedCaseId ? caseOptionsState.find((caseOption) => caseOption.id === selectedCaseId) ?? null : null,
    [caseOptionsState, selectedCaseId],
  );
  const physicalExamOptions = session?.physical_exam_options ?? selectedCase?.physicalExamOptions ?? [];
  const auxiliaryTestOptions = session?.auxiliary_test_options ?? selectedCase?.auxiliaryTestOptions ?? [];
  const requestedExamCodeSet = useMemo(() => new Set(session?.requested_exams ?? []), [session?.requested_exams]);
  const requestedTestCodeSet = useMemo(() => new Set(session?.requested_tests ?? []), [session?.requested_tests]);
  const pendingPhysicalExamOptions = physicalExamOptions.filter((examOption) => !requestedExamCodeSet.has(examOption.exam_code));
  const completedPhysicalExamOptions = physicalExamOptions.filter((examOption) => requestedExamCodeSet.has(examOption.exam_code));
  const pendingAuxiliaryTestOptions = auxiliaryTestOptions.filter((testOption) => !requestedTestCodeSet.has(testOption.test_code));
  const completedAuxiliaryTestOptions = auxiliaryTestOptions.filter((testOption) => requestedTestCodeSet.has(testOption.test_code));
  const preparedOpeningTaskCard = session?.opening_task_card ?? selectedCase?.openingTaskCard ?? null;
  const preparedPatientProfile = session?.patient_profile ?? selectedCase?.patientProfile ?? null;
  const preparedTeachingFocus = session?.teaching_focus ?? selectedCase?.teachingFocus ?? null;
  const preparedDynamicTeachingFocus = session?.dynamic_teaching_focus ?? null;
  const selectedApiConfigProviderOption = getApiConfigProviderOption(studentApiConfig.provider);
  const isVertexGeminiAdcConfig = studentApiConfig.provider === "vertex_gemini_adc";
  const isVertexGeminiApiKeyConfig = studentApiConfig.provider === "vertex_gemini_api_key";
  const hasSavedApiKeyForSelectedProvider = Boolean(
    runtimeApiConfig?.active
    && runtimeApiConfig.provider === studentApiConfig.provider
    && runtimeApiConfig.api_key_saved,
  );
  const apiConfigBaseUrlLabel = isVertexGeminiAdcConfig ? "Project ID" : isVertexGeminiApiKeyConfig ? "Base URL（可留空）" : "Base URL";
  const apiConfigBaseUrlPlaceholder = isVertexGeminiAdcConfig
    ? "例如：my-gcp-project"
    : isVertexGeminiApiKeyConfig
      ? "Vertex API Key 模式无需填写"
      : selectedApiConfigProviderOption.defaultBaseUrl;

  const chatMessages = useMemo<readonly ChatMessage[]>(() => {
    let baseMessages: ChatMessage[] = [];
    if (!session) {
      baseMessages = [];
    } else {
      baseMessages = [
        {
          id: "chief-complaint",
          speaker: "patient",
          label: "标准化病人",
          text: `医生您好，我这次主要是${session.chief_complaint}。`,
        },
        ...session.messages.map(mapApiMessage),
      ];
    }

    if (pendingPatientMessage?.finalText) {
      baseMessages = baseMessages.filter(
        (message) => !(message.speaker === pendingPatientMessage.speaker && message.text === pendingPatientMessage.finalText),
      );
    }

    const nextMessages = [...baseMessages];
    if (
      optimisticHistoryMessage &&
      !hasMessageWithSpeakerAndText(nextMessages, optimisticHistoryMessage.speaker, optimisticHistoryMessage.text)
    ) {
      nextMessages.push(optimisticHistoryMessage);
    }
    if (pendingPatientMessage) {
      nextMessages.push(pendingPatientMessage);
    }

    return nextMessages;
  }, [optimisticHistoryMessage, pendingPatientMessage, session]);

  useEffect(() => {
    const chatScrollContainer = chatScrollContainerRef.current;
    if (!chatScrollContainer) {
      return;
    }
    chatScrollContainer.scrollTo({
      top: chatScrollContainer.scrollHeight,
      behavior: "smooth",
    });
  }, [chatMessages.length, optimisticHistoryMessage?.text, pendingPatientMessage?.text, statusText, errorText]);

  const evidenceItems = useMemo(
    () => session?.revealed_facts.map(getEvidenceItem) ?? [],
    [session?.revealed_facts],
  );

  const requestedItems = useMemo(
    () => [
      ...(session?.requested_exams.map((exam) => ({
        id: `exam:${exam}`,
        label: `查体：${physicalExamOptions.find((examOption) => examOption.exam_code === exam)?.exam_name_cn ?? exam}`,
      })) ?? []),
      ...(session?.requested_tests.map((test) => ({
        id: `test:${test}`,
        label: `检查：${auxiliaryTestOptions.find((testOption) => testOption.test_code === test)?.test_name_cn ?? test}`,
      })) ?? []),
    ],
    [auxiliaryTestOptions, physicalExamOptions, session?.requested_exams, session?.requested_tests],
  );

  const procedureItems = useMemo(
    () => [
      ...procedureResults,
      ...requestedItems
        .filter((request) => !procedureResults.some((result) => result.id === request.id))
        .map((request) => ({ ...request, result: "后端已记录该申请。" })),
    ],
    [procedureResults, requestedItems],
  );

  function getProcedureResultById(procedureId: string): ProcedureResult | null {
    return procedureItems.find((item) => item.id === procedureId) ?? null;
  }

  const sourceReferenceGroups = useMemo(
    () => groupSourceReferences(feedbackReport?.source_reference_items ?? [], feedbackReport?.source_references ?? []),
    [feedbackReport?.source_reference_items, feedbackReport?.source_references],
  );
  const reportDimensionMaxScores = useMemo(() => getDimensionMaxScoresFromRubricScores(feedbackReport?.rubric_scores), [feedbackReport?.rubric_scores]);

  const workflowSuggestion = useMemo(
    () => getNextWorkflowSuggestion(session, feedbackReport),
    [feedbackReport, session],
  );
  const trainingSuggestion = session?.training_progress.next_focus ?? workflowSuggestion;
  const osceDockStyle: CSSProperties = osceDockPosition.isReady
    ? {
        left: `${osceDockPosition.x}px`,
        top: `${osceDockPosition.y}px`,
      }
    : {
        bottom: `${OSCE_DOCK_MARGIN}px`,
        right: `${OSCE_DOCK_MARGIN}px`,
      };
  const osceDockPanelAlignmentClass = osceDockPosition.side === "right" ? "right-0" : "left-0";
  const osceDockPanelVerticalClass = osceDockPosition.isReady && osceDockPosition.y < 260 ? "top-16" : "bottom-16";
  const osceDockSubmenuAlignmentClass = osceDockPosition.side === "right" ? "right-full mr-2" : "left-full ml-2";
  const osceDockActionClass = "rounded-lg border border-border bg-background px-3 py-2 text-center text-sm font-medium whitespace-nowrap transition hover:border-brand/30 hover:bg-accent";
  const osceDockButtonActionClass = "rounded-lg border border-border bg-background px-3 py-2 text-center text-sm font-medium whitespace-nowrap transition hover:border-brand/30 hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50";
  const osceDockMenuButtonClass = "rounded-lg border border-border px-3 py-2 text-center text-sm font-medium whitespace-nowrap transition hover:border-brand/30 hover:bg-accent";

  const scoringPreview = useMemo(
    () => [
      `当前阶段：${formatStage(session?.stage)}`,
      `已问问题：${session?.asked_questions.length ?? 0} 个`,
      `已披露线索：${session?.revealed_facts.length ?? 0} 条`,
      `最终诊断：${session?.final_submission?.diagnosis ?? "尚未提交"}`,
      `安全边界：${session?.safety_flags.length ?? 0} 次`,
    ],
    [
      session?.asked_questions.length,
      session?.final_submission?.diagnosis,
      session?.revealed_facts.length,
      session?.safety_flags.length,
      session?.stage,
    ],
  );

  const reportDimensions = useMemo(
    () => Object.entries(feedbackReport?.dimension_scores ?? {}),
    [feedbackReport?.dimension_scores],
  );

  async function handleAuthSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = authEmail.trim();

    if (!email || !authPassword || isSubmittingAuth) {
      return;
    }

    setIsSubmittingAuth(true);
    setAuthErrorText(null);

    try {
      const nextUser =
        authMode === "login"
          ? await loginUser(email, authPassword)
          : await registerUser(email, authPassword, authDisplayName.trim());
      setAuthUser(nextUser);
      setAuthPassword("");
      setAuthDisplayName("");
      setIsAuthDialogOpen(false);
      setIsAccountMenuOpen(false);
      setStatusText(`已登录：${nextUser.display_name}`);
    } catch (error) {
      setAuthErrorText(error instanceof Error ? error.message : "登录或注册失败。");
    } finally {
      setIsSubmittingAuth(false);
    }
  }

  async function handleLogout() {
    if (isSubmittingAuth) {
      return;
    }

    setIsSubmittingAuth(true);
    setAuthErrorText(null);
    setIsAccountMenuOpen(false);

    try {
      await logoutUser();
      setAuthUser(null);
      setAuthEmail(DEFAULT_AUTH_EMAIL);
      setAuthPassword(DEFAULT_AUTH_PASSWORD);
      setIsAuthDialogOpen(true);
      setStatusText("已退出登录，请重新登录后继续保存训练。");
    } catch (error) {
      setAuthErrorText(error instanceof Error ? error.message : "退出登录失败。");
      setIsAuthDialogOpen(true);
    } finally {
      setIsSubmittingAuth(false);
    }
  }

  function promptTrainingModelConfigRequired(): void {
    setStatusText(TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE);
    setErrorText(TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE);
    setIsApiConfigHelpOpen(true);
  }

  async function ensureActiveSession(): Promise<OsceSession | null> {
    if (session) {
      if (!isTrainingModelConfigReady) {
        promptTrainingModelConfigRequired();
        return null;
      }
      return session;
    }

    if (!authUser) {
      setStatusText("请先登录后再开始或恢复训练。");
      setIsAuthDialogOpen(true);
      return null;
    }

    if (!selectedCaseId) {
      setStatusText("请先选择病例，再开始训练。");
      return null;
    }

    if (!isTrainingModelConfigReady) {
      promptTrainingModelConfigRequired();
      return null;
    }

    setIsCreating(true);
    setErrorText(null);
    setStatusText("正在创建训练会话...");

    try {
      const nextSession = await createSession(selectedCaseId);
      setSession(nextSession);
      setSelectedCaseId(nextSession.case_id);
      setStatusText("已创建训练会话，可以继续训练。");
      return nextSession;
    } catch (error) {
      const message = error instanceof Error ? error.message : "创建训练会话失败。";
      if (message === "请先登录后再继续训练。") {
        setAuthUser(null);
        setIsAuthDialogOpen(true);
      }
      setStatusText(message === "请先登录后再继续训练。" ? message : "训练会话创建失败，请确认后端仍在运行。");
      setErrorText(message);
      return null;
    } finally {
      setIsCreating(false);
    }
  }

  async function animatePendingPatientReply(messageId: string, replyText: string): Promise<void> {
    if (!replyText) {
      setPendingPatientMessage((currentMessage) => currentMessage?.id === messageId ? null : currentMessage);
      return;
    }

    for (let index = 1; index <= replyText.length; index += 1) {
      await new Promise<void>((resolve) => {
        window.setTimeout(resolve, PATIENT_REPLY_TYPEWRITER_DELAY_MS);
      });
      setPendingPatientMessage((currentMessage) =>
        currentMessage?.id === messageId
          ? {
              ...currentMessage,
              finalText: replyText,
              isPending: index < replyText.length,
              text: replyText.slice(0, index),
            }
          : currentMessage,
      );
    }

    setPendingPatientMessage((currentMessage) => currentMessage?.id === messageId ? null : currentMessage);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = inputValue.trim();

    if (!authUser || !selectedCaseId || !message || isCreating || isSending) {
      return;
    }

    if (!isTrainingModelConfigReady) {
      promptTrainingModelConfigRequired();
      return;
    }

    const requestTimestamp = Date.now();
    const optimisticQuestionId = `optimistic-student-${requestTimestamp}`;
    const pendingPatientReplyId = `pending-patient-${requestTimestamp}`;
    setIsSending(true);
    setErrorText(null);
    setInputValue("");
    setOptimisticHistoryMessage({
      id: optimisticQuestionId,
      speaker: "student",
      label: "学生",
      text: message,
    });
    setPendingPatientMessage({
      id: pendingPatientReplyId,
      speaker: "coach",
      label: "判断中",
      text: "判断中",
      isPending: true,
    });
    setStatusText("正在处理问诊");

    try {
      const activeSession = await ensureActiveSession();
      if (!activeSession) {
        setPendingPatientMessage((currentMessage) => currentMessage?.id === pendingPatientReplyId ? null : currentMessage);
        return;
      }

      const updatedSession = await sendHistoryMessage(activeSession.session_id, message);
      const replyText = updatedSession.reply ?? "";
      const replyMessageMetadata = getReplyMessageMetadata(updatedSession, replyText);
      const replyStatusLabel = replyMessageMetadata.speaker === "coach" ? replyMessageMetadata.label : "标准化病人回复";
      setPendingPatientMessage((currentMessage) =>
        currentMessage?.id === pendingPatientReplyId
          ? {
              ...currentMessage,
              ...replyMessageMetadata,
              finalText: replyText,
            }
          : currentMessage,
      );
      setSession(updatedSession);
      setOptimisticHistoryMessage((currentMessage) => currentMessage?.id === optimisticQuestionId ? null : currentMessage);
      setStatusText(`正在显示${replyStatusLabel}...`);
      await animatePendingPatientReply(pendingPatientReplyId, updatedSession.reply ?? "");
      setStatusText(`已收到${replyStatusLabel}：${updatedSession.current_intent ?? "未识别意图"}`);
    } catch (error) {
      setPendingPatientMessage((currentMessage) => currentMessage?.id === pendingPatientReplyId ? null : currentMessage);
      setErrorText(error instanceof Error ? error.message : "发送问诊失败。");
      setStatusText("问诊发送失败，请确认后端仍在运行。");
    } finally {
      setIsSending(false);
    }
  }

  async function handlePhysicalExamRequest(examCode: string) {
    if (isCreating || isRequestingExam) {
      return;
    }

    setIsRequestingExam(true);
    setErrorText(null);

    try {
      const activeSession = await ensureActiveSession();
      if (!activeSession) {
        return;
      }
      const shouldShowPhysicalExamSequenceReminder = activeSession.training_progress.history.covered === 0;
      const updatedSession = await requestPhysicalExam(activeSession.session_id, examCode);
      const nextProcedureResult = {
        id: `exam:${updatedSession.exam_code}`,
        label: `查体：${updatedSession.exam_name_cn}`,
        result: updatedSession.result,
      };
      setSession(updatedSession);
      setProcedureResults((currentResults) => [
        ...currentResults.filter((result) => result.id !== `exam:${updatedSession.exam_code}`),
        nextProcedureResult,
      ]);
      setSelectedProcedureResult(nextProcedureResult);
      const sequenceReminder = shouldShowPhysicalExamSequenceReminder
        ? " OSCE 通常建议先完成核心病史采集，再进入查体。"
        : "";
      setStatusText(`已返回查体结果：${updatedSession.exam_name_cn}${sequenceReminder}`);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "请求查体失败。");
      setStatusText("查体请求失败，请确认后端仍在运行。");
    } finally {
      setIsRequestingExam(false);
    }
  }

  async function handleAuxiliaryTestRequest(testCode: string) {
    if (isCreating || isRequestingTest) {
      return;
    }

    setIsRequestingTest(true);
    setErrorText(null);

    try {
      const activeSession = await ensureActiveSession();
      if (!activeSession) {
        return;
      }
      const shouldShowAuxiliaryTestSequenceReminder = activeSession.training_progress.physical_exam.requested === 0;
      const updatedSession = await requestAuxiliaryTest(activeSession.session_id, testCode);
      const nextProcedureResult = {
        id: `test:${updatedSession.test_code}`,
        label: `检查：${updatedSession.test_name_cn}`,
        result: updatedSession.result,
      };
      setSession(updatedSession);
      setProcedureResults((currentResults) => [
        ...currentResults.filter((result) => result.id !== `test:${updatedSession.test_code}`),
        nextProcedureResult,
      ]);
      setSelectedProcedureResult(nextProcedureResult);
      const sequenceReminder = shouldShowAuxiliaryTestSequenceReminder
        ? " 现实 OSCE 中通常应先基于病史和查体形成初步判断，再选择辅助检查。"
        : "";
      setStatusText(`已返回辅助检查结果：${updatedSession.test_name_cn}${sequenceReminder}`);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "申请辅助检查失败。");
      setStatusText("辅助检查申请失败，请确认后端仍在运行。");
    } finally {
      setIsRequestingTest(false);
    }
  }

  async function handleHypothesisSubmit() {
    const hypothesis = hypothesisValue.trim();

    if (!authUser || !selectedCaseId || !hypothesis || isCreating || isRecordingHypothesis) {
      return;
    }

    setIsRecordingHypothesis(true);
    setErrorText(null);

    try {
      const activeSession = await ensureActiveSession();
      if (!activeSession) {
        return;
      }

      const updatedSession = await recordHypothesis(activeSession.session_id, hypothesis);
      setSession(updatedSession);
      setHypothesisValue("");
      setStatusText(`已记录诊断假设：${hypothesis}`);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "记录诊断假设失败。");
      setStatusText("诊断假设记录失败，请确认后端仍在运行。");
    } finally {
      setIsRecordingHypothesis(false);
    }
  }

  async function handleHintRequest() {
    if (!authUser || !selectedCaseId || isCreating || isRequestingHint) {
      return;
    }

    setIsRequestingHint(true);
    setErrorText(null);

    try {
      const activeSession = await ensureActiveSession();
      if (!activeSession) {
        return;
      }

      const updatedSession = await requestHint(activeSession.session_id);
      setSession(updatedSession);
      setStatusText(`已生成过程提示：${updatedSession.hint}`);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "请求过程提示失败。");
      setStatusText("过程提示请求失败，请确认后端仍在运行。");
    } finally {
      setIsRequestingHint(false);
    }
  }

  async function handleDiagnosisSubmit() {
    const diagnosis = diagnosisValue.trim();
    const differentialDiagnosis = differentialDiagnosisValue.trim();
    const supportingEvidence = supportingEvidenceValue.trim();
    const exclusionEvidence = exclusionEvidenceValue.trim();
    const nextStep = nextStepValue.trim();

    if (!authUser || !selectedCaseId || !diagnosis || !differentialDiagnosis || !supportingEvidence || !exclusionEvidence || !nextStep || isCreating || isSubmittingDiagnosis) {
      return;
    }

    const reasoning = buildStructuredReasoning(differentialDiagnosis, supportingEvidence, exclusionEvidence, nextStep);

    setIsSubmittingDiagnosis(true);
    setErrorText(null);

    try {
      const activeSession = await ensureActiveSession();
      if (!activeSession) {
        return;
      }

      const submittedSession = await submitDiagnosis(activeSession.session_id, diagnosis, reasoning);
      const report = await getSessionReport(submittedSession.session_id);
      const updatedSession = await getSession(submittedSession.session_id);
      setSession(updatedSession);
      setFeedbackReport(report);
      setStatusText(`已提交诊断并生成评分报告：${report.total_score} 分。`);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "提交诊断或获取报告失败。");
      setStatusText("诊断提交失败，请确认后端仍在运行。");
    } finally {
      setIsSubmittingDiagnosis(false);
    }
  }

  return (
    <main className="relative h-screen overflow-hidden bg-muted/40 text-foreground">
      <div className={isAuthDialogOpen ? "h-full pointer-events-none blur-sm" : "h-full"}>
        <div className="flex h-full min-h-0">
      <aside className="hidden w-72 shrink-0 border-r border-border bg-background p-4 shadow-inner-right lg:flex lg:flex-col">
        <div className="min-h-0 flex-1 overflow-y-scroll student-rail-scrollbar" onScroll={handleStudentRailScroll}>
        <div className="mb-6">
          <h1 className="text-xl font-semibold tracking-tight">临境 OSCE 智能体</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            基于公开 OSCE 病例数据的诊断学临床思维训练
          </p>
        </div>

        <Panel title="训练导航" description="当前病例、阶段和下一步。">
          <div className="space-y-4">
            <div className="rounded-lg border border-border bg-muted/60 p-3 text-xs leading-5">
              <p className="text-muted-foreground">当前选择</p>
              {selectedCase ? (
                <>
                  <p className="mt-1 font-medium">{session?.case_title ?? selectedCase.title}</p>
                  <p className="mt-1 text-muted-foreground">{session?.chief_complaint ?? selectedCase.chiefComplaint}</p>
                  {session ? (
                    <p className="mt-2 rounded-md bg-background px-2 py-1 font-mono text-[11px] text-muted-foreground">
                      会话 ID：{session.session_id}
                    </p>
                  ) : null}
                </>
              ) : (
                <p className="mt-1 text-muted-foreground">尚未选择病例，请先进入病例库选择训练场景。</p>
              )}
              <button
                className="mt-3 w-full rounded-md border border-border bg-background px-3 py-2 text-center text-xs font-medium whitespace-nowrap shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                disabled={!preparedPatientProfile}
                onClick={() => setIsPatientProfileOpen(true)}
                type="button"
              >
                患者信息
              </button>
            </div>

            <Link
              className="mx-auto flex w-fit items-center justify-center rounded-md border border-[#141413] bg-[#141413] px-4 py-2 text-center text-xs font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-[#2A2926]"
              href="/cases"
            >
              选择病例
            </Link>

            <div className="space-y-2">
              {workflowStepDefinitions.map((step, index) => (
                <div
                  className={`rounded-md border px-3 py-2 text-sm font-medium ${getStageClass(
                    getWorkflowStepStatus(step.key, session, feedbackReport),
                  )}`}
                  key={step.key}
                >
                  <span className="mr-2 font-mono text-xs opacity-70">{index + 1}</span>
                  {step.label}
                </div>
              ))}
            </div>

            <div className="rounded-lg border border-brand/20 bg-brand/5 p-3">
              <p className="text-sm font-semibold text-brand">下一步建议</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">{trainingSuggestion}</p>
            </div>
          </div>
        </Panel>
        </div>
        <div className="mt-4 border-t border-border pt-4">
          <p className="text-xs font-medium text-muted-foreground">个人中心</p>
          {authUser ? (
            <div className="relative mt-2">
              <button
                aria-expanded={isAccountMenuOpen}
                aria-haspopup="menu"
                aria-label="打开个人中心菜单"
                className="flex w-full items-center justify-between gap-2 rounded-xl border border-border bg-background px-3 py-2 text-sm font-medium text-foreground shadow-xs transition hover:border-brand/30 hover:bg-accent"
                onClick={() => setIsAccountMenuOpen((isOpen) => !isOpen)}
                type="button"
              >
                <span className="whitespace-nowrap">测试账号</span>
                <span className="max-w-28 truncate text-xs text-muted-foreground">{authUser.display_name}</span>
              </button>
              {isAccountMenuOpen ? (
                <div className="absolute bottom-12 left-0 z-50 w-full rounded-xl border border-border bg-white p-2 shadow-[0_18px_40px_rgba(20,20,19,0.14)]">
                  <p className="px-3 py-2 text-xs leading-5 text-muted-foreground">
                    当前登录：<span className="font-medium text-foreground">{authUser.display_name}</span>
                  </p>
                  <Link
                    className="block rounded-lg border border-border bg-background px-3 py-2 text-center text-sm font-medium whitespace-nowrap transition hover:border-brand/30 hover:bg-accent"
                    href="/history"
                  >
                    训练记录
                  </Link>
                  <Link
                    className="mt-2 block rounded-lg border border-border bg-background px-3 py-2 text-center text-sm font-medium whitespace-nowrap transition hover:border-brand/30 hover:bg-accent"
                    href="/profile"
                  >
                    学习画像
                  </Link>
                  <button
                    className="mt-2 inline-flex w-full items-center justify-center rounded-lg border border-[#B42318]/30 bg-[#FEF3F2] text-[#B42318] px-3 py-2 text-sm font-medium whitespace-nowrap transition hover:bg-[#FEE4E2] disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={isSubmittingAuth}
                    onClick={handleLogout}
                    type="button"
                  >
                    退出登录
                  </button>
                </div>
              ) : null}
            </div>
          ) : (
            <button
              className="mt-2 w-full rounded-xl border border-border bg-background px-3 py-2 text-sm font-medium whitespace-nowrap shadow-xs transition hover:bg-accent"
              onClick={() => setIsAuthDialogOpen(true)}
              type="button"
            >
              登录 / 注册
            </button>
          )}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-hidden p-3 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="relative flex min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-background shadow-xs">
            <div className="border-b border-border p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold">医患对话</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {session?.case_title ?? selectedCase?.title ?? "请先选择病例"}
                  </p>
                </div>
                <div className="max-w-sm rounded-lg border border-brand/20 bg-brand/5 px-3 py-2 text-xs leading-5 text-brand">
                  <p>{statusText}</p>
                  {errorText ? <p className="mt-1 text-red-600">{errorText}</p> : null}
                </div>
              </div>
            </div>

            <div className="flex-1 space-y-4 overflow-y-scroll p-5 pb-40 student-chat-scrollbar" ref={chatScrollContainerRef}>
              {!session && !isCasePreparationPromptDismissed ? (
                <CaseSelectionPrompt selectedCase={selectedCase} onDismiss={() => setIsCasePreparationPromptDismissed(true)} />
              ) : null}
              <OpeningTaskCardMessage openingTaskCard={preparedOpeningTaskCard} />
              {chatMessages.map((message) => {
                const isStudent = message.speaker === "student";
                const isCoach = message.speaker === "coach";
                const messageRowClass = isStudent ? "justify-end" : isCoach ? "justify-center" : "justify-start";
                const messageBubbleClass = isStudent
                  ? "max-w-[76%] rounded-xl border border-brand bg-brand px-4 py-3 text-sm leading-6 text-white shadow-xs"
                  : isCoach
                    ? "w-full max-w-lg border-[#B5812A]/30 bg-[#FFF8E8] rounded-xl border px-4 py-3 text-sm leading-6 text-foreground shadow-xs"
                    : "max-w-[76%] rounded-xl border border-border bg-muted px-4 py-3 text-sm leading-6 text-foreground shadow-xs";
                return (
                  <div className={`flex ${messageRowClass}`} key={message.id}>
                    <div className={messageBubbleClass}>
                      <p className={isStudent ? "text-white/80" : isCoach ? "text-[#8A5A00]" : "text-muted-foreground"}>
                        {message.label}
                      </p>
                      <p className="mt-1">{message.isPending && !message.finalText ? <PendingThinkingIndicator /> : message.text}</p>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 px-3 pb-4 pt-10">
              <div className="pointer-events-auto relative mx-auto mb-2 flex max-w-3xl flex-wrap items-center gap-2" ref={procedureActionContainerRef}>
                <button
                  className="rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium whitespace-nowrap shadow-xs transition hover:bg-accent"
                  onClick={() => setInputValue("什么时候开始疼的？")}
                  type="button"
                >
                  问现病史
                </button>
                <button
                  className="rounded-full border border-[#B5812A]/30 bg-[#FFF8E8] px-3 py-1.5 text-xs font-medium whitespace-nowrap text-[#8A5A00] shadow-xs transition hover:bg-[#FFF1CC] disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCreating || isRequestingHint}
                  onClick={handleHintRequest}
                  type="button"
                >{isRequestingHint ? "提示生成中" : "请求提示"}</button>
                <button
                  aria-expanded={openProcedureActionGroup === "physical_exam"}
                  className="inline-flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium whitespace-nowrap shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || physicalExamOptions.length === 0}
                  onClick={() => setOpenProcedureActionGroup((currentGroup) => currentGroup === "physical_exam" ? null : "physical_exam")}
                  type="button"
                >
                  查体项目
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                    {completedPhysicalExamOptions.length}/{physicalExamOptions.length}
                  </span>
                </button>
                <button
                  aria-expanded={openProcedureActionGroup === "auxiliary_test"}
                  className="inline-flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium whitespace-nowrap shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || auxiliaryTestOptions.length === 0}
                  onClick={() => setOpenProcedureActionGroup((currentGroup) => currentGroup === "auxiliary_test" ? null : "auxiliary_test")}
                  type="button"
                >
                  辅助检查
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                    {completedAuxiliaryTestOptions.length}/{auxiliaryTestOptions.length}
                  </span>
                </button>
                <button
                  className="rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium whitespace-nowrap shadow-xs transition hover:bg-accent"
                  onClick={() => setIsDiagnosisComposerOpen((isOpen) => !isOpen)}
                  type="button"
                >{isDiagnosisComposerOpen ? "收起诊断" : "填写诊断"}</button>
                {openProcedureActionGroup === "physical_exam" ? (
                  <div className="absolute bottom-11 left-0 z-30 w-80 rounded-2xl border border-border bg-background p-3 shadow-[0_18px_45px_rgba(20,20,19,0.16)]" data-procedure-action-menu="true">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold">查体项目</p>
                      <span className="rounded-full border border-border bg-muted px-2 py-1 text-[11px] text-muted-foreground">
                        {completedPhysicalExamOptions.length} 已查看
                      </span>
                    </div>
                    <div className="mt-3 grid max-h-72 gap-2 overflow-y-scroll pr-1 student-rail-scrollbar" onScroll={handleStudentRailScroll}>
                      {pendingPhysicalExamOptions.length > 0 ? (
                        pendingPhysicalExamOptions.map((examOption) => (
                          <button
                            className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-left text-xs font-medium shadow-xs transition hover:border-brand/30 hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                            disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCreating || isRequestingExam}
                            key={examOption.exam_code}
                            onClick={() => {
                              setOpenProcedureActionGroup(null);
                              void handlePhysicalExamRequest(examOption.exam_code);
                            }}
                            type="button"
                          >
                            <span className="block whitespace-nowrap">{isRequestingExam ? "查体中" : examOption.exam_name_cn}</span>
                          </button>
                        ))
                      ) : (
                        <p className="rounded-lg border border-dashed border-border bg-muted/40 p-3 text-xs text-muted-foreground">
                          当前查体项目都已查看。
                        </p>
                      )}
                      {completedPhysicalExamOptions.length > 0 ? (
                        <div className="border-t border-border pt-3">
                          <p className="text-xs font-medium text-muted-foreground">已查看</p>
                          <div className="mt-2 grid gap-2">
                            {completedPhysicalExamOptions.map((examOption) => (
                              <button
                                className="rounded-lg border border-[#86B993]/40 bg-[#EEF6EF] px-3 py-2 text-left text-xs font-medium whitespace-nowrap text-[#236146] shadow-xs transition hover:bg-[#E2F0E4]"
                                key={examOption.exam_code}
                                onClick={() => {
                                  setSelectedProcedureResult(getProcedureResultById(`exam:${examOption.exam_code}`));
                                  setOpenProcedureActionGroup(null);
                                }}
                                type="button"
                              >
                                查体：{examOption.exam_name_cn}
                              </button>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </div>
                ) : null}
                {openProcedureActionGroup === "auxiliary_test" ? (
                  <div className="absolute bottom-11 left-32 z-30 w-80 rounded-2xl border border-border bg-background p-3 shadow-[0_18px_45px_rgba(20,20,19,0.16)]" data-procedure-action-menu="true">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold">辅助检查</p>
                      <span className="rounded-full border border-border bg-muted px-2 py-1 text-[11px] text-muted-foreground">
                        {completedAuxiliaryTestOptions.length} 已查看
                      </span>
                    </div>
                    <div className="mt-3 grid max-h-72 gap-2 overflow-y-scroll pr-1 student-rail-scrollbar" onScroll={handleStudentRailScroll}>
                      {pendingAuxiliaryTestOptions.length > 0 ? (
                        pendingAuxiliaryTestOptions.map((testOption) => (
                          <button
                            className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-left text-xs font-medium shadow-xs transition hover:border-brand/30 hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                            disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCreating || isRequestingTest}
                            key={testOption.test_code}
                            onClick={() => {
                              setOpenProcedureActionGroup(null);
                              void handleAuxiliaryTestRequest(testOption.test_code);
                            }}
                            title={
                              testOption.rules_out.length > 0
                                ? `用于排除：${testOption.rules_out.join("、")}`
                                : testOption.overuse_warning ?? undefined
                            }
                            type="button"
                          >
                            <span className="block whitespace-nowrap">{isRequestingTest ? "检查中" : `${testOption.category}：${testOption.test_name_cn}`}</span>
                            <span className="mt-1 block whitespace-nowrap text-[11px] font-normal text-muted-foreground">
                              {testOption.cost_hint} · {testOption.invasiveness} · {getDiagnosticRoleLabel(testOption.diagnostic_role)}
                            </span>
                          </button>
                        ))
                      ) : (
                        <p className="rounded-lg border border-dashed border-border bg-muted/40 p-3 text-xs text-muted-foreground">
                          当前辅助检查都已查看。
                        </p>
                      )}
                      {completedAuxiliaryTestOptions.length > 0 ? (
                        <div className="border-t border-border pt-3">
                          <p className="text-xs font-medium text-muted-foreground">已查看</p>
                          <div className="mt-2 grid gap-2">
                            {completedAuxiliaryTestOptions.map((testOption) => (
                              <button
                                className="rounded-lg border border-[#86B993]/40 bg-[#EEF6EF] px-3 py-2 text-left text-xs font-medium whitespace-nowrap text-[#236146] shadow-xs transition hover:bg-[#E2F0E4]"
                                key={testOption.test_code}
                                onClick={() => {
                                  setSelectedProcedureResult(getProcedureResultById(`test:${testOption.test_code}`));
                                  setOpenProcedureActionGroup(null);
                                }}
                                type="button"
                              >
                                {testOption.category}：{testOption.test_name_cn}
                              </button>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </div>
                ) : null}
              </div>
              <form className="pointer-events-auto mx-auto max-w-3xl rounded-full border border-border bg-background px-3 py-2 shadow-[0_10px_30px_rgba(20,20,19,0.12)]" onSubmit={handleSubmit}>
                <label className="sr-only" htmlFor="history-question">
                  输入下一句问诊问题
                </label>
                <div className="flex items-center gap-2">
                  <input
                    className="h-10 min-w-0 flex-1 rounded-full border-0 bg-transparent px-3 text-sm outline-none transition placeholder:text-muted-foreground focus:ring-0"
                    disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCreating || isSending}
                    id="history-question"
                    onChange={(event) => setInputValue(event.target.value)}
                    placeholder="例如：什么时候开始疼的？疼痛在哪里？有没有恶心或腹泻？"
                    value={inputValue}
                  />
                  <button
                    className="rounded-full border border-brand bg-brand px-4 py-2 text-sm font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCreating || !inputValue.trim() || isSending}
                    type="submit"
                  >
                    {isSending ? "发送中" : "发送问诊"}
                  </button>
                </div>
              </form>
              {isDiagnosisComposerOpen ? (
                  <div className="pointer-events-auto mx-auto mt-3 max-w-3xl rounded-lg border border-border bg-background p-3 shadow-[0_10px_30px_rgba(20,20,19,0.12)]">
                    <div className="grid gap-2">
                    <div className="grid gap-2 sm:grid-cols-2">
                      <label className="sr-only" htmlFor="diagnosis-input">
                        输入最终诊断
                      </label>
                      <input
                        className="min-w-0 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                        disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCreating || isSubmittingDiagnosis}
                        id="diagnosis-input"
                        onChange={(event) => setDiagnosisValue(event.target.value)}
                        placeholder="最终诊断"
                        value={diagnosisValue}
                      />
                      <label className="sr-only" htmlFor="differential-diagnosis-input">
                        输入鉴别诊断
                      </label>
                      <input
                        className="min-w-0 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                        disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCreating || isSubmittingDiagnosis}
                        id="differential-diagnosis-input"
                        onChange={(event) => setDifferentialDiagnosisValue(event.target.value)}
                        placeholder="至少 2 个合理鉴别诊断"
                        value={differentialDiagnosisValue}
                      />
                    </div>
                    <label className="sr-only" htmlFor="supporting-evidence-input">
                      输入支持依据
                    </label>
                    <textarea
                      className="min-w-0 resize-y max-h-40 overflow-y-auto rounded-md border border-border bg-muted/40 px-3 py-2 text-xs outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                      disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCreating || isSubmittingDiagnosis}
                      id="supporting-evidence-input"
                      onChange={(event) => setSupportingEvidenceValue(event.target.value)}
                      onInput={(event) => resizeTextareaToContent(event.currentTarget)}
                      placeholder="支持主诊断的关键阳性证据"
                      rows={2}
                      value={supportingEvidenceValue}
                    />
                    <label className="sr-only" htmlFor="exclusion-evidence-input">
                      输入排除依据
                    </label>
                    <textarea
                      className="min-w-0 resize-y max-h-40 overflow-y-auto rounded-md border border-border bg-muted/40 px-3 py-2 text-xs outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                      disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCreating || isSubmittingDiagnosis}
                      id="exclusion-evidence-input"
                      onChange={(event) => setExclusionEvidenceValue(event.target.value)}
                      onInput={(event) => resizeTextareaToContent(event.currentTarget)}
                      placeholder="排除或暂不能支持其他诊断的依据"
                      rows={2}
                      value={exclusionEvidenceValue}
                    />
                    <label className="sr-only" htmlFor="next-step-input">
                      输入下一步方向
                    </label>
                    <textarea
                      className="min-w-0 resize-y max-h-40 overflow-y-auto rounded-md border border-border bg-muted/40 px-3 py-2 text-xs outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                      disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCreating || isSubmittingDiagnosis}
                      id="next-step-input"
                      onChange={(event) => setNextStepValue(event.target.value)}
                      onInput={(event) => resizeTextareaToContent(event.currentTarget)}
                      placeholder="若继续训练，下一步最需要验证什么"
                      rows={2}
                      value={nextStepValue}
                    />
                    <button
                      className="rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50 sm:w-fit"
                      disabled={
                        !authUser ||
                        !isTrainingModelConfigReady ||
                        isCreating ||
                        !diagnosisValue.trim() ||
                        !differentialDiagnosisValue.trim() ||
                        !supportingEvidenceValue.trim() ||
                        !exclusionEvidenceValue.trim() ||
                        !nextStepValue.trim() ||
                        isSubmittingDiagnosis
                      }
                      onClick={handleDiagnosisSubmit}
                      type="button"
                    >
                      {isSubmittingDiagnosis ? "生成中" : "提交诊断"}
                    </button>
                    </div>
                  </div>
                ) : null}
            </div>
          </div>

          <aside className="flex min-h-0 flex-col gap-4 overflow-y-scroll student-rail-scrollbar" onScroll={handleStudentRailScroll}>
            <CollapsiblePanel
              title="教学重点与问诊提示"
              description="展开查看训练重点、误区和推荐问诊。"
              isOpen={rightPanelOpenStates.focus}
              maxContentHeightClass="max-h-80"
              onToggle={() => toggleRightPanel("focus")}
            >
              <div className="space-y-3 text-xs leading-5">
                {session?.inquiry_guidance.priority ? (
                  <p className="rounded-lg border border-[#B5812A]/30 bg-[#FFF8E8] p-3 text-[#8A5A00]">
                    {session?.inquiry_guidance.priority}
                  </p>
                ) : (
                  <p className="rounded-lg border border-dashed border-border bg-muted/40 p-3 text-muted-foreground">
                    创建训练会话后，这里会展示推荐问诊顺序和示例问题。
                  </p>
                )}
                {session ? (
                  <>
                    <div className="flex flex-wrap gap-2">
                      {session.inquiry_guidance.suggested_questions.map((question) => (
                        <button
                          className="rounded-md border border-border bg-background px-3 py-1.5 text-left text-xs font-medium shadow-xs transition hover:bg-accent"
                          key={question}
                          onClick={() => setInputValue(question)}
                          type="button"
                        >
                          {question}
                        </button>
                      ))}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {session.inquiry_guidance.categories.map((category) => (
                        <span className="rounded-full bg-muted px-2 py-1 text-[11px] text-muted-foreground" key={category}>
                          {category}
                        </span>
                      ))}
                    </div>
                  </>
                ) : null}

                {preparedDynamicTeachingFocus && preparedDynamicTeachingFocus.patterns.length > 0 ? (
                  <div className="space-y-2">
                    {preparedDynamicTeachingFocus.patterns.map((pattern) => (
                      <div className="rounded-lg border border-brand/20 bg-brand/5 p-3" key={pattern.focus_id}>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="font-semibold text-foreground">{pattern.title}</p>
                          <span className="rounded-full border border-brand/20 bg-background px-2 py-0.5 text-[11px] text-brand">
                            {pattern.severity}
                          </span>
                        </div>
                        <p className="mt-1 text-muted-foreground">{pattern.description}</p>
                        <p className="mt-2 text-brand">{pattern.training_suggestion}</p>
                        <p className="mt-2 text-[11px] text-muted-foreground">生成依据：{pattern.why_now}</p>
                      </div>
                    ))}
                  </div>
                ) : null}

                {preparedTeachingFocus && (
                  preparedTeachingFocus.learning_objectives.length > 0
                  || preparedTeachingFocus.common_error_patterns.length > 0
                  || preparedTeachingFocus.recommended_training_path.length > 0
                ) ? (
                  <div className="space-y-3 rounded-lg border border-border bg-background p-3">
                    {preparedTeachingFocus.learning_objectives.length > 0 ? (
                      <div>
                        <p className="font-semibold text-brand">学习目标</p>
                        <ul className="mt-1 space-y-1 text-muted-foreground">
                          {preparedTeachingFocus.learning_objectives.map((objective) => (
                            <li key={objective}>· {objective}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                    {preparedTeachingFocus.common_error_patterns.length > 0 ? (
                      <div>
                        <p className="font-semibold text-brand">常见误区</p>
                        <div className="mt-2 space-y-2">
                          {preparedTeachingFocus.common_error_patterns.map((pattern) => (
                            <div className="rounded-lg border border-dashed border-brand/20 bg-brand/5 p-2" key={pattern.pattern_id}>
                              <p className="font-medium text-foreground">{pattern.title}</p>
                              <p className="mt-1 text-muted-foreground">{pattern.focus}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {preparedTeachingFocus.recommended_training_path.length > 0 ? (
                      <div>
                        <p className="font-semibold text-brand">训练路径</p>
                        <ol className="mt-1 space-y-1 text-muted-foreground">
                          {preparedTeachingFocus.recommended_training_path.map((step, index) => (
                            <li key={step}>{index + 1}. {step}</li>
                          ))}
                        </ol>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </CollapsiblePanel>

            <CollapsiblePanel
              title="智能体教学详情"
              description="展开查看教学策略、阶段检查点和决策轨迹。"
              isOpen={rightPanelOpenStates.agent}
              maxContentHeightClass="max-h-96"
              onToggle={() => toggleRightPanel("agent")}
            >
              {session?.pedagogy_state ? (
                <div className="space-y-3 text-xs leading-5">
                  <div className="rounded-lg border border-brand/20 bg-brand/5 p-3">
                    <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">Active Goal</p>
                    <p className="mt-1 font-semibold text-foreground">{session.pedagogy_state.active_learning_goal}</p>
                    <p className="mt-2 text-muted-foreground">{session.pedagogy_state.next_best_action}</p>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="rounded-lg border border-border bg-background p-3">
                      <p className="text-muted-foreground">教学模式</p>
                      <p className="mt-1 font-mono text-[11px] text-foreground">{session.pedagogy_state.coaching_mode}</p>
                    </div>
                    <div className="rounded-lg border border-border bg-background p-3">
                      <p className="text-muted-foreground">教学安全边界</p>
                      <p className="mt-1 font-mono text-[11px] text-foreground">{session.pedagogy_state.safety_mode}</p>
                    </div>
                  </div>
                  <div className="rounded-lg border border-border bg-background p-3">
                    <p className="font-semibold text-foreground">阶段检查点</p>
                    <div className="mt-2 grid gap-2 sm:grid-cols-2">
                      <div>
                        <p className="text-muted-foreground">状态</p>
                        <p className="mt-1 font-mono text-[11px] text-foreground">{session.pedagogy_state.stage_checkpoint.status}</p>
                      </div>
                      <div>
                        <p className="text-muted-foreground">准备度</p>
                        <p className="mt-1 font-mono text-[11px] text-foreground">{session.pedagogy_state.stage_checkpoint.readiness}</p>
                      </div>
                    </div>
                    <p className="mt-2 break-words text-[11px] text-muted-foreground">
                      待补证据：{session.pedagogy_state.stage_checkpoint.pending_signal_ids.join("、") || "暂无"}
                    </p>
                  </div>
                  <div className="rounded-lg border border-border bg-background p-3">
                    <p className="font-semibold text-foreground">教学计划</p>
                    <p className="mt-1 font-mono text-[11px] text-foreground">{session.pedagogy_state.teaching_plan.selected_strategy}</p>
                    <p className="mt-2 text-muted-foreground">{session.pedagogy_state.teaching_plan.strategy_reason}</p>
                    <p className="mt-2 break-words text-[11px] text-muted-foreground">
                      来源：{session.pedagogy_state.teaching_plan.source_references.join("、") || "当前阶段规则"}
                    </p>
                  </div>
                  <div className="rounded-lg border border-border bg-background p-3">
                    <p className="font-semibold text-foreground">Hint Ladder</p>
                    <div className="mt-2 space-y-2">
                      {session.pedagogy_state.hint_ladder.map((hint) => (
                        <div className="rounded-md bg-muted px-2 py-1" key={`${hint.action_type}-${hint.level}`}>
                          <p className="font-mono text-[11px] text-muted-foreground">Level {hint.level} · {hint.disclosure_policy}</p>
                          <p className="mt-1 text-foreground">{hint.message_template}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="rounded-lg border border-border bg-background p-3">
                    <p className="font-semibold text-foreground">最近决策轨迹</p>
                    <div className="mt-2 space-y-2">
                      {session.agent_decision_trace.slice(-3).map((trace) => (
                        <div className="rounded-md bg-muted px-2 py-1" key={trace.trace_id}>
                          <p className="font-mono text-[11px] text-muted-foreground">{trace.node} · {trace.stage}</p>
                          <p className="mt-1 text-foreground">{trace.decision}</p>
                          <p className="mt-1 text-[11px] text-muted-foreground">
                            observe: {trace.observe.checkpoint_status} · decide: {trace.decide.selected_strategy}
                          </p>
                          <p className="mt-1 text-[11px] text-muted-foreground">
                            act: Level {trace.act.hint_ladder_levels.join("/")} · reflect: {trace.reflect.safety_mode}
                          </p>
                        </div>
                      ))}
                      {session.agent_decision_trace.length === 0 ? (
                        <p className="text-muted-foreground">暂无决策轨迹。</p>
                      ) : null}
                    </div>
                  </div>
                </div>
              ) : (
                <p className="rounded-lg border border-dashed border-border bg-muted/40 p-3 text-xs leading-5 text-muted-foreground">
                  智能体还未形成可展示的教学状态。
                </p>
              )}
            </CollapsiblePanel>

            <CollapsiblePanel
              title="已收集线索"
              description="来自问诊节点的结构化事实。"
              isOpen={rightPanelOpenStates.evidence}
              maxContentHeightClass="max-h-64"
              onToggle={() => toggleRightPanel("evidence")}
            >
              {evidenceItems.length > 0 ? (
                <div className="space-y-2">
                  {evidenceItems.map((item) => (
                    <div className="rounded-lg border border-border bg-muted/60 p-3" key={item.label}>
                      <p className="text-sm font-medium">{item.label}</p>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">{item.detail}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="rounded-lg border border-dashed border-border bg-muted/40 p-3 text-xs leading-5 text-muted-foreground">
                  发送能命中病例意图的问诊问题后，这里会展示后端披露的结构化线索。
                </p>
              )}
            </CollapsiblePanel>

            <CollapsiblePanel
              title="诊断假设"
              isOpen={rightPanelOpenStates.hypotheses}
              maxContentHeightClass="max-h-48"
              onToggle={() => toggleRightPanel("hypotheses")}
            >
              <div className="space-y-3">
                <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                  <label className="sr-only" htmlFor="hypothesis-input">
                    输入训练中的诊断假设
                  </label>
                  <input
                    className="min-w-0 rounded-md border border-border bg-background px-3 py-2 text-xs outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                    disabled={!session || isRecordingHypothesis}
                    id="hypothesis-input"
                    onChange={(event) => setHypothesisValue(event.target.value)}
                    placeholder="例如：急性阑尾炎"
                    value={hypothesisValue}
                  />
                  <button
                    className="rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={!session || !hypothesisValue.trim() || isRecordingHypothesis}
                    onClick={handleHypothesisSubmit}
                    type="button"
                  >{isRecordingHypothesis ? "记录中" : "记录假设"}</button>
                </div>
                {session?.student_hypotheses.length ? (
                  <div className="flex flex-wrap gap-2">
                    {session.student_hypotheses.map((hypothesis, index) => (
                      <span className="rounded-full border border-border bg-background px-3 py-1 text-xs" key={`${hypothesis}-${index}`}>
                        {hypothesis}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs leading-5 text-muted-foreground">
                    训练中可先记录诊断假设，最终诊断仍在下方提交。
                  </p>
                )}
              </div>
            </CollapsiblePanel>

            <CollapsiblePanel
              title="评分报告"
              description="提交诊断后展示结构化复盘报告。"
              isOpen={rightPanelOpenStates.report}
              maxContentHeightClass="max-h-96"
              onToggle={() => toggleRightPanel("report")}
            >
              <div className="space-y-2">
                {scoringPreview.map((item) => (
                  <p className="rounded-md border border-border bg-background px-3 py-2 text-xs" key={item}>
                    {item}
                  </p>
                ))}
                <p className="rounded-md border border-brand/20 bg-brand/5 px-3 py-2 text-xs leading-5 text-brand">
                  本报告仅用于教学复盘，评分依据来自病例、rubric 与来源引用。
                </p>
              </div>
              {feedbackReport ? (
                <div className="mt-3 space-y-4 rounded-xl border border-brand/20 bg-brand/5 p-3">
                  <div className="rounded-xl border border-brand/20 bg-background p-4 shadow-xs">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="text-xs text-muted-foreground">OSCE 训练总分</p>
                        <div className="mt-1 flex items-end gap-1 text-brand">
                          <span className="text-4xl font-semibold leading-none">{feedbackReport.total_score}</span>
                          <span className="pb-1 text-sm font-medium">/ 100</span>
                        </div>
                      </div>
                      <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
                        {feedbackReport.total_score >= 60 ? "基本达标" : "继续训练"}
                      </span>
                    </div>
                    <div className="mt-4 h-2 overflow-hidden rounded-full bg-muted">
                      <div className="h-full rounded-full bg-brand" style={{ width: `${feedbackReport.total_score}%` }} />
                    </div>
                    <p className="mt-3 text-xs leading-5 text-muted-foreground">{feedbackReport.feedback_summary}</p>
                    <Link
                      className="mt-4 inline-flex items-center justify-center rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover"
                      href={`/report?session_id=${feedbackReport.session_id}`}
                    >
                      打开独立报告页
                    </Link>
                  </div>

                  {reportDimensions.length > 0 ? (
                    <div className="space-y-2 rounded-xl border border-border bg-background p-3">
                      <p className="text-xs font-medium">维度得分</p>
                      {reportDimensions.map(([key, score]) => {
                        const maxScore = reportDimensionMaxScores[key] ?? 100;
                        const percent = getScorePercent(score, maxScore);
                        return (
                          <div className="space-y-1" key={key}>
                            <div className="flex items-center justify-between gap-2 text-xs">
                              <span className="font-medium">{scoreDimensionLabels[key] ?? key}</span>
                              <span className="text-muted-foreground">
                                {score} / {maxScore} 分
                              </span>
                            </div>
                            <div className="h-2 overflow-hidden rounded-full bg-muted">
                              <div className="h-full rounded-full bg-brand" style={{ width: `${percent}%` }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}

                  <div className="space-y-3 text-xs leading-5">
                    <div className="rounded-xl border border-border bg-background p-3">
                      <p className="font-medium">已完成亮点</p>
                      <ul className="mt-2 space-y-1 text-muted-foreground">
                        {feedbackReport.strengths.map((item) => (
                          <li className="rounded-md bg-muted/60 px-2 py-1" key={item}>
                            {item}
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div className="rounded-xl border border-border bg-background p-3">
                      <p className="font-medium">推理问题</p>
                      <ul className="mt-2 space-y-1 text-muted-foreground">
                        {feedbackReport.reasoning_errors.map((item) => (
                          <li className="rounded-md bg-muted/60 px-2 py-1" key={item}>
                            {item}
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div className="rounded-xl border border-border bg-background p-3">
                      <p className="font-medium">下一轮训练重点</p>
                      <ul className="mt-2 space-y-1 text-muted-foreground">
                        {feedbackReport.next_recommendations.map((item) => (
                          <li className="rounded-md bg-muted/60 px-2 py-1" key={item}>
                            {item}
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div className="rounded-xl border border-border bg-background p-3">
                      <div className="flex items-center justify-between gap-3">
                        <p className="font-medium">来源引用</p>
                        <Link className="text-[11px] font-medium text-brand hover:underline" href="/sources">
                          查看说明
                        </Link>
                      </div>
                      <div className="mt-2 space-y-2 text-muted-foreground">
                        {sourceReferenceGroups.map((group) => (
                          <section className="rounded-lg bg-muted/60 p-2" key={group.key}>
                            <p className="text-xs font-medium text-foreground">{group.title}</p>
                            <p className="mt-1 text-[11px] leading-4">{group.description}</p>
                            <ul className="mt-2 space-y-1">
                              {group.references.map((item) => {
                                const metadataText = getSourceReferenceMetadataText(item.metadata);
                                return (
                                  <li className="rounded-md bg-background/80 px-2 py-1 text-[11px]" key={item.reference}>
                                    <p className="font-medium text-foreground">{item.title}</p>
                                    <p className="mt-1 break-all font-mono text-muted-foreground">{item.reference}</p>
                                    {metadataText ? <p className="mt-1 break-all text-muted-foreground">{metadataText}</p> : null}
                                  </li>
                                );
                              })}
                            </ul>
                          </section>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              ) : null}
            </CollapsiblePanel>
            <div className="rounded-xl border border-dashed border-border bg-background/80 p-3 text-xs leading-5">
              <p className="font-medium text-foreground">管理员图谱</p>
              <p className="mt-1 text-muted-foreground">
                查看本次训练素材覆盖状态；未覆盖项只显示素材 ID，避免提前泄露隐藏结果。
              </p>
              <button
                className="mt-3 inline-flex w-fit items-center justify-center rounded-md border border-[#141413] bg-[#141413] px-3 py-2 text-xs font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-[#2A2926] disabled:cursor-not-allowed disabled:opacity-50"
                disabled={!session}
                onClick={() => setIsCoverageMapOpen(true)}
                type="button"
              >
                查看素材覆盖图谱
              </button>
            </div>
          </aside>
        </div>
      </section>
      <div className="fixed z-40" ref={osceDockContainerRef} style={osceDockStyle}>
        {isOsceDockOpen ? (
          <section className={`absolute ${osceDockPanelVerticalClass} ${osceDockPanelAlignmentClass} rounded-2xl border border-border bg-white/95 p-3 shadow-[0_18px_45px_rgba(20,20,19,0.16)] backdrop-blur`}>
            <div className="grid w-36 gap-2">
              <button
                className={`${osceDockMenuButtonClass} ${osceDockMenuGroup === "training" ? "border-brand bg-brand text-white" : "bg-background text-foreground"}`}
                onClick={() => selectOsceDockMenuGroup("training")}
                type="button"
              >
                训练入口
              </button>
              {isStudentRuntimeApiConfigEnabled ? (
                <button
                  className={osceDockButtonActionClass}
                  onClick={() => {
                    closeOsceDock();
                    setIsApiConfigHelpOpen(true);
                  }}
                  type="button"
                >
                  API 配置
                </button>
              ) : null}
              <Link className={osceDockActionClass} href="/safety" onClick={closeOsceDock}>
                安全声明
              </Link>
              <Link className={osceDockActionClass} href="/sources" onClick={closeOsceDock}>
                数据来源
              </Link>
              <button
                className={`${osceDockMenuButtonClass} ${osceDockMenuGroup === "system" ? "border-brand bg-brand text-white" : "bg-background text-foreground"}`}
                onClick={() => selectOsceDockMenuGroup("system")}
                type="button"
              >
                系统状态
              </button>
              <button
                aria-label="关闭 OSCE 快捷入口"
                className="rounded-lg border border-border bg-background px-3 py-2 text-center text-sm font-medium whitespace-nowrap transition hover:bg-accent"
                onClick={closeOsceDock}
                type="button"
              >
                关闭菜单
              </button>
            </div>
            {osceDockMenuGroup ? (
              <div className={`absolute top-0 ${osceDockSubmenuAlignmentClass} w-48 rounded-2xl border border-border bg-white/95 p-2 shadow-[0_18px_45px_rgba(20,20,19,0.14)] backdrop-blur`}>
                {osceDockMenuGroup === "training" ? (
                  <div className="grid gap-2">
                    <Link className={osceDockActionClass} href="/cases" onClick={closeOsceDock}>
                      病例库
                    </Link>
                    {feedbackReport ? (
                      <Link className="rounded-lg border border-brand bg-brand px-3 py-2 text-center text-sm font-medium whitespace-nowrap text-white transition hover:bg-brand-hover" href={`/report?session_id=${feedbackReport.session_id}`} onClick={closeOsceDock}>
                        评分报告
                      </Link>
                    ) : (
                      <span className="rounded-lg border border-border bg-muted px-3 py-2 text-center text-sm font-medium whitespace-nowrap text-muted-foreground">评分报告</span>
                    )}
                    <button
                      className={osceDockButtonActionClass}
                      disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCreating || isRequestingHint}
                      onClick={() => {
                        closeOsceDock();
                        void handleHintRequest();
                      }}
                      type="button"
                    >
                      过程提示
                    </button>
                    <button
                      className={osceDockButtonActionClass}
                      disabled={!preparedPatientProfile}
                      onClick={() => {
                        closeOsceDock();
                        setIsPatientProfileOpen(true);
                      }}
                      type="button"
                    >
                      患者信息
                    </button>
                  </div>
                ) : null}
                {osceDockMenuGroup === "system" ? (
                  <div className="grid gap-2">
                    <span className="rounded-lg border border-border bg-muted px-3 py-2 text-center text-sm font-medium whitespace-nowrap text-muted-foreground">
                      {authUser ? "账号已登录" : "等待登录"}
                    </span>
                    <span className="rounded-lg border border-border bg-muted px-3 py-2 text-center text-sm font-medium whitespace-nowrap text-muted-foreground">
                      {selectedCase ? "病例已选择" : "未选择病例"}
                    </span>
                  </div>
                ) : null}
              </div>
            ) : null}
          </section>
        ) : null}
        <button
          aria-label="打开 OSCE 快捷入口"
          aria-pressed={isOsceDockOpen}
          className="relative flex size-14 touch-none cursor-grab items-center justify-center rounded-full border border-brand/35 bg-[#FFF8E8] text-brand shadow-[0_14px_32px_rgba(174,86,48,0.22)] transition hover:border-brand hover:bg-[#FFEED8] active:cursor-grabbing focus:ring-2 focus:ring-brand/20"
          onClick={handleOsceDockButtonClick}
          onPointerCancel={handleOsceDockPointerCancel}
          onPointerDown={handleOsceDockPointerDown}
          onPointerMove={handleOsceDockPointerMove}
          onPointerUp={handleOsceDockPointerUp}
          type="button"
        >
          <span className="pointer-events-none absolute inset-1.5 rounded-full border border-brand/20 bg-background/80" />
          <span className="relative z-10 flex size-8 items-center justify-center rounded-full bg-brand text-base font-semibold text-white">临</span>
          <span className="pointer-events-none absolute right-2 top-2 size-2 rounded-full bg-[#86B993]" />
        </button>
      </div>
      {selectedProcedureResult ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="w-full max-w-lg rounded-2xl border border-border bg-background p-5 shadow-xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-medium text-brand">已查看结果</p>
                <h2 className="mt-1 text-base font-semibold">{selectedProcedureResult.label}</h2>
              </div>
              <button
                aria-label="关闭查体检查结果"
                className="inline-flex shrink-0 items-center justify-center rounded-md border border-border bg-background px-2 py-1 text-xs font-medium whitespace-nowrap shadow-xs transition hover:bg-accent"
                onClick={() => setSelectedProcedureResult(null)}
                type="button"
              >
                关闭
              </button>
            </div>
            <p className="mt-4 rounded-xl border border-border bg-muted/50 p-4 text-sm leading-7 text-foreground">
              {selectedProcedureResult.result}
            </p>
          </div>
        </div>
      ) : null}
      {isCoverageMapOpen && session ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="max-h-[82vh] w-full max-w-3xl overflow-y-scroll rounded-2xl border border-border bg-background p-5 shadow-xl student-chat-scrollbar">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-medium text-brand">管理员图谱</p>
                <h2 className="mt-1 text-base font-semibold">管理员图谱 · 素材覆盖</h2>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  用于答辩和调试训练路径覆盖，不参与评分决策；未覆盖项不会展示隐藏结果文本。
                </p>
              </div>
              <button
                aria-label="关闭素材覆盖图谱"
                className="inline-flex shrink-0 items-center justify-center rounded-md border border-border bg-background px-2 py-1 text-xs font-medium whitespace-nowrap shadow-xs transition hover:bg-accent"
                onClick={() => setIsCoverageMapOpen(false)}
                type="button"
              >
                关闭
              </button>
            </div>
            <div className="mt-4">
              <CoverageMap trainingProgress={session.training_progress} />
            </div>
          </div>
        </div>
      ) : null}
      {isPatientProfileOpen && preparedPatientProfile ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="w-full max-w-sm rounded-2xl border border-border bg-background p-5 shadow-xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-base font-semibold">患者信息</p>
                <p className="mt-1 text-xs text-muted-foreground">OSCE 教学模拟开局信息</p>
              </div>
              <button
                aria-label="关闭患者信息弹窗"
                className="inline-flex shrink-0 items-center justify-center rounded-md border border-border bg-background px-2 py-1 text-xs font-medium whitespace-nowrap shadow-xs transition hover:bg-accent"
                onClick={() => setIsPatientProfileOpen(false)}
                type="button"
              >
                关闭
              </button>
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg bg-muted p-3">
                <dt className="text-xs text-muted-foreground">年龄</dt>
                <dd className="mt-1 font-medium">{preparedPatientProfile.age}</dd>
              </div>
              <div className="rounded-lg bg-muted p-3">
                <dt className="text-xs text-muted-foreground">性别</dt>
                <dd className="mt-1 font-medium">{preparedPatientProfile.gender}</dd>
              </div>
              <div className="rounded-lg bg-muted p-3">
                <dt className="text-xs text-muted-foreground">职业</dt>
                <dd className="mt-1 font-medium">{preparedPatientProfile.occupation}</dd>
              </div>
              <div className="rounded-lg bg-muted p-3">
                <dt className="text-xs text-muted-foreground">就诊科室</dt>
                <dd className="mt-1 font-medium">{preparedPatientProfile.hospital_department}</dd>
              </div>
            </dl>
            <p className="mt-4 rounded-lg border border-[#B5812A]/30 bg-[#FFF8E8] p-3 text-xs leading-5 text-[#8A5A00]">
              以上为 OSCE 教学模拟开局信息，不包含隐藏病史、查体、检查或标准诊断。
            </p>
          </div>
        </div>
      ) : null}
      {isApiConfigHelpOpen && isStudentRuntimeApiConfigEnabled ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="max-h-[86vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-border bg-white p-5 shadow-xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-medium text-brand">系统与配置</p>
                <h2 className="mt-1 text-base font-semibold">API 配置</h2>
              </div>
              <button
                aria-label="关闭 API 配置说明"
                className="inline-flex shrink-0 items-center justify-center rounded-md border border-border bg-background px-2 py-1 text-xs font-medium whitespace-nowrap shadow-xs transition hover:bg-accent"
                onClick={() => setIsApiConfigHelpOpen(false)}
                type="button"
              >
                关闭
              </button>
            </div>
            <div className="mt-5 space-y-4">
              <section className="space-y-2">
                <p className="text-sm font-medium">服务端</p>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {apiConfigProviderOptions.map((providerOption) => {
                    const isSelectedProvider = studentApiConfig.provider === providerOption.id;
                    const isCurrentProvider = Boolean(runtimeApiConfig?.active && runtimeApiConfig.provider === providerOption.id);
                    return (
                      <button
                        className={`rounded-lg border px-3 py-2 text-center text-sm font-medium whitespace-nowrap transition ${
                          isSelectedProvider ? "border-brand bg-brand text-white" : "border-border bg-muted text-foreground hover:bg-accent"
                        }`}
                        key={providerOption.id}
                        onClick={() => handleStudentApiProviderChange(providerOption.id)}
                        type="button"
                      >
                        <span>{providerOption.label}</span>
                        {isCurrentProvider ? <span className="ml-2 rounded-full bg-background/85 px-2 py-0.5 text-[11px] text-brand">当前</span> : null}
                      </button>
                    );
                  })}
                </div>
                <p className="rounded-lg border border-border bg-muted px-3 py-2 text-xs leading-5 text-muted-foreground">
                  当前渠道：{formatRuntimeApiConfigSummary(runtimeApiConfig)}
                </p>
              </section>
              <div className="grid gap-3">
                <label className="space-y-1 text-sm font-medium" htmlFor="student-api-key-input">
                  <span>API Key</span>
                  <input
                    autoComplete="off"
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                    disabled={studentApiConfig.provider === "vertex_gemini_adc"}
                    id="student-api-key-input"
                    onChange={(event) => {
                      setStudentApiConfig((currentConfig) => ({ ...currentConfig, apiKey: event.target.value }));
                      setApiConfigTestResult(null);
                    }}
                    placeholder={
                      isVertexGeminiAdcConfig
                        ? "使用本机 ADC，无需 API Key"
                        : studentApiConfig.provider === "custom_backend"
                          ? "自定义后端可选"
                          : hasSavedApiKeyForSelectedProvider
                            ? "已保存，可留空沿用"
                            : studentApiConfig.provider !== "vertex_gemini_api_key"
                              ? "输入服务商密钥"
                              : "输入 Vertex API Key"
                    }
                    type="password"
                    value={studentApiConfig.apiKey}
                  />
                  {hasSavedApiKeyForSelectedProvider ? <span className="block text-xs font-normal text-muted-foreground">密钥已保存，留空会沿用当前账号的已保存密钥。</span> : null}
                </label>
                <label className="space-y-1 text-sm font-medium" htmlFor="student-api-model-input">
                  <span>模型</span>
                  <input
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                    id="student-api-model-input"
                    onChange={(event) => {
                      setStudentApiConfig((currentConfig) => ({ ...currentConfig, model: event.target.value }));
                      setApiConfigTestResult(null);
                    }}
                    placeholder={selectedApiConfigProviderOption.defaultModel || "自定义后端可选"}
                    value={studentApiConfig.model}
                  />
                </label>
                <label className="space-y-1 text-sm font-medium" htmlFor="student-api-base-url-input">
                  <span>{apiConfigBaseUrlLabel}</span>
                  <input
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                    id="student-api-base-url-input"
                    onChange={(event) => {
                      setStudentApiConfig((currentConfig) => ({ ...currentConfig, baseUrl: event.target.value }));
                      setApiConfigTestResult(null);
                    }}
                    placeholder={apiConfigBaseUrlPlaceholder}
                    value={studentApiConfig.baseUrl}
                  />
                </label>
                <label className="space-y-1 text-sm font-medium" htmlFor="student-api-proxy-url-input">
                  <span>代理</span>
                  <input
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                    id="student-api-proxy-url-input"
                    onChange={(event) => {
                      setStudentApiConfig((currentConfig) => ({ ...currentConfig, proxyUrl: event.target.value }));
                      setApiConfigTestResult(null);
                    }}
                    placeholder="http://127.0.0.1:7897"
                    value={studentApiConfig.proxyUrl}
                  />
                </label>
              </div>
              <p className="rounded-lg border border-border bg-muted px-3 py-2 text-xs leading-5 text-muted-foreground">
                {apiConfigStatusText}
                {apiConfigTestResult?.checked_url ? <span className="block break-all">检查地址：{apiConfigTestResult.checked_url}</span> : null}
              </p>
              <div className="grid grid-cols-2 gap-2">
                <button
                  className="rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium whitespace-nowrap transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={isApplyingStudentApiConfig}
                  onClick={handleSaveStudentApiConfig}
                  type="button"
                >
                  保存配置
                </button>
                <button className="rounded-lg border border-brand bg-brand px-4 py-2 text-sm font-medium whitespace-nowrap text-white transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-60" disabled={isTestingStudentApiConfig} onClick={() => void handleTestStudentApiConfig()} type="button">{isTestingStudentApiConfig ? "测试中" : "测试连通性"}</button>
              </div>
              <p className="text-xs leading-5 text-muted-foreground">OpenAI 兼容、Anthropic、Vertex Gemini ADC 或 Vertex Gemini API Key 配置按当前登录账号保存在后端，可用于标准化病人、llm_rubric 和 Skill 候选文案；规则评分和病例标准答案仍由后端确定性执行。</p>
            </div>
          </div>
        </div>
      ) : null}
      </div>
      </div>
      {!isCheckingAuth && isAuthDialogOpen ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-background/75 p-4 backdrop-blur">
          <section className="w-full max-w-md rounded-2xl border border-border bg-background p-6 shadow-xl">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">临境 OSCE 智能体（TraceOSCE）</p>
              <h2 className="mt-2 text-xl font-semibold">登录 / 注册</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {isCheckingAuth ? "正在读取登录状态..." : "登录后训练记录、报告和后续会话管理会逐步绑定到当前账号。"}
              </p>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-2 rounded-xl bg-muted p-1">
              <button
                className={`rounded-lg px-3 py-2 text-sm font-medium whitespace-nowrap transition ${
                  authMode === "login" ? "bg-background text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground"
                }`}
                onClick={() => setAuthMode("login")}
                type="button"
              >
                登录
              </button>
              <button
                className={`rounded-lg px-3 py-2 text-sm font-medium whitespace-nowrap transition ${
                  authMode === "register" ? "bg-background text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground"
                }`}
                onClick={() => setAuthMode("register")}
                type="button"
              >
                注册
              </button>
            </div>
            <form className="mt-5 space-y-4" onSubmit={handleAuthSubmit}>
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="auth-email-input">
                  邮箱
                </label>
                <input
                  autoComplete="email"
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                  id="auth-email-input"
                  onChange={(event) => setAuthEmail(event.target.value)}
                  placeholder="student@example.com"
                  type="email"
                  value={authEmail}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="auth-password-input">
                  密码
                </label>
                <input
                  autoComplete={authMode === "login" ? "current-password" : "new-password"}
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                  id="auth-password-input"
                  onChange={(event) => setAuthPassword(event.target.value)}
                  placeholder="至少输入一个可记住的密码"
                  type="password"
                  value={authPassword}
                />
              </div>
              {authMode === "register" ? (
                <div className="space-y-2">
                  <label className="text-sm font-medium" htmlFor="auth-display-name-input">
                    显示名称
                  </label>
                  <input
                    autoComplete="name"
                    className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                    id="auth-display-name-input"
                    onChange={(event) => setAuthDisplayName(event.target.value)}
                    placeholder="可选，例如：学生甲"
                    type="text"
                    value={authDisplayName}
                  />
                </div>
              ) : null}
              {authErrorText ? <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">{authErrorText}</p> : null}
              <button
                className="w-full rounded-lg border border-brand bg-brand px-4 py-2 text-sm font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
                disabled={isCheckingAuth || isSubmittingAuth || !authEmail.trim() || !authPassword}
                type="submit"
              >{isSubmittingAuth ? "处理中" : authMode === "login" ? "登录" : "注册"}</button>
            </form>
          </section>
        </div>
      ) : null}
    </main>
  );
}

export default function Home() {
  return (
    <Suspense fallback={null}>
      <HomeContent />
    </Suspense>
  );
}
