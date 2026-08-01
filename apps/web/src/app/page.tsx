"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, FormEvent, PointerEvent, ReactNode, UIEvent } from "react";
import { getCurrentUser, loginUser, logoutUser } from "./auth-client";
import type { AuthUser } from "./auth-client";
import {
  clearLocalAutoLoginSuppression,
  isLocalAutoLoginSuppressed,
  suppressLocalAutoLogin,
} from "./local-auto-login";

type StageStatus = "done" | "active" | "locked";

type StageDefinition = {
  readonly key: string;
  readonly label: string;
};

type WorkflowStepDefinition = Readonly<{
  key: "case_intro" | "history_taking" | "physical_exam" | "auxiliary_test" | "hypothesis" | "diagnosis_submission" | "feedback";
  label: string;
}>;

type RightPanelKey = "evidence" | "report";

type OsceDockMenuGroup = "training" | "system";

type ProcedureActionGroup = "physical_exam" | "auxiliary_test";

type TrainingDifficultyMode = "beginner" | "intermediate" | "advanced";

type SearchParamReader = Readonly<{
  get: (name: string) => string | null;
}>;

type OsceDockSide = "left" | "right";

type BackendConnectionStatus = "checking" | "online" | "offline";

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
  runtime_write_supported?: boolean;
  deployment_mode?: string;
  integration_targets: readonly string[];
  message: string;
}>;

type SpeechTranscriptionResponse = Readonly<{
  text: string;
  provider: string;
  model: string;
  language?: string | null;
  emotion?: string | null;
  duration_seconds?: number | null;
}>;

type PatientSpeechContext = Readonly<{
  sessionId?: string;
  messageIndex?: number;
  emotion?: string | null;
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

type StudentRevealedItem = Readonly<{
  id: string;
  label: string;
  topic?: string | null;
  slot?: string | null;
}>;

type StudentRevealedItems = Readonly<{
  history: readonly StudentRevealedItem[];
  physical_exam: readonly StudentRevealedItem[];
  auxiliary_test: readonly StudentRevealedItem[];
  reasoning: readonly StudentRevealedItem[];
}>;

type ApiMessage = {
  readonly role: "student" | "patient" | string;
  readonly content: string;
  readonly emotion?: string | null;
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

type PhysicalExamOption = Readonly<{
  exam_code: string;
  exam_name_cn: string;
}>;

type AuxiliaryTestOption = Readonly<{
  test_code: string;
  test_name_cn: string;
  category: string;
  invasiveness: string;
  cost_hint: string;
}>;

type PhysicalExamQuickOption = Readonly<Pick<PhysicalExamOption, "exam_code" | "exam_name_cn">>;

type AuxiliaryTestQuickOption = Readonly<
  Pick<
    AuxiliaryTestOption,
    "test_code" | "test_name_cn" | "category" | "invasiveness" | "cost_hint"
  >
>;

type ProcedureAvailabilityStatus = "case_configured" | "not_available_for_case" | "ai_simulated_for_training";

type ProcedureCatalogPhysicalExam = Readonly<{
  exam_code: string;
  exam_name_cn: string;
  category: string;
}>;

type ProcedureCatalogAuxiliaryTest = Readonly<{
  test_code: string;
  test_name_cn: string;
  category: string;
  invasiveness: string;
  cost_hint: string;
}>;

type ProcedureCatalog = Readonly<{
  mode: string;
  physical_exams: readonly ProcedureCatalogPhysicalExam[];
  auxiliary_tests: readonly ProcedureCatalogAuxiliaryTest[];
  safety_boundary: string;
}>;

type TrainingProgressSection = Readonly<{
  total: number;
}>;

type TrainingProgress = Readonly<{
  history: TrainingProgressSection &
    Readonly<{
      covered: number;
    }>;
  physical_exam: TrainingProgressSection &
    Readonly<{
      requested: number;
    }>;
  auxiliary_test: TrainingProgressSection &
    Readonly<{
      requested: number;
    }>;
  reasoning: Readonly<{
    collected_evidence_count: number;
    ready_for_hypothesis: boolean;
  }>;
  revealed_items: StudentRevealedItems;
  next_focus: string;
}>;

type ClinicalReasoningNextBestAction = Readonly<{
  action_type: string;
  target_category: string;
  message: string;
  why: string;
}>;

type ClinicalReasoningState = Readonly<{
  last_action_stage: string;
  pedagogical_phase: string;
  readiness: Readonly<Record<string, string>>;
  sequence_flags: readonly string[];
  next_best_action: ClinicalReasoningNextBestAction;
  socratic_question: string;
  reasoning_rationale: string;
  safety_note: string;
}>;

type PedagogyState = Readonly<{
  clinical_reasoning_state?: ClinicalReasoningState;
}>;

type BackendProcessingTraceItem = Readonly<{
  step_id: string;
  label: string;
  status: "completed" | "skipped" | "error" | string;
  started_at: string;
  completed_at: string;
  duration_ms: number;
  metadata?: Readonly<Record<string, unknown>>;
}>;

type SessionProcessingStatusStep = Readonly<{
  step_id: string;
  label: string;
  status: "completed" | "skipped" | "error" | "active" | string;
}>;

type SessionProcessingStatus = Readonly<{
  state: "idle" | "running" | "completed" | "error" | string;
  current_step_id: string;
  current_label: string;
  summary: string;
  steps: readonly SessionProcessingStatusStep[];
}>;

type AgentTurnMemoryItem = Readonly<{
  turn_id: string;
  student_message: string;
  reply: string;
  reply_role: "student" | "patient" | "coach" | string;
  current_intents: readonly string[];
  turn_policy: string;
  revealed_fact_count: number;
  selected_skill_count: number;
  knowledge_reference_count: number;
  processing_trace?: readonly BackendProcessingTraceItem[];
  processing_duration_ms?: number;
  safety_flags: readonly string[];
}>;

type CollectedPhysicalExamResult = Readonly<{
  exam_code: string;
  exam_name_cn: string;
  result: string;
}>;

type CollectedAuxiliaryTestResult = Readonly<{
  test_code: string;
  test_name_cn: string;
  result: string;
}>;

type CollectedProcedureResults = Readonly<{
  physical_exams: readonly CollectedPhysicalExamResult[];
  auxiliary_tests: readonly CollectedAuxiliaryTestResult[];
}>;

type OsceSession = Readonly<{
  payload_schema_version: "student_session.v2";
  session_id: string;
  student_id: string;
  case_id: string;
  stage: string;
  training_difficulty: TrainingDifficultyMode;
  case_title: string;
  chief_complaint: string;
  patient_opening_utterance: string;
  patient_profile: StudentVisiblePatientProfile;
  opening_task_card: OpeningTaskCard;
  diagnosis_draft: DiagnosisDraft;
  physical_exam_options: readonly PhysicalExamOption[];
  auxiliary_test_options: readonly AuxiliaryTestOption[];
  collected_procedure_results: CollectedProcedureResults;
  training_progress: TrainingProgress;
  messages: readonly ApiMessage[];
  asked_questions: readonly string[];
  revealed_facts: readonly string[];
  requested_exams: readonly string[];
  requested_tests: readonly string[];
  student_hypotheses: readonly string[];
  final_submission: FinalSubmission | null;
  feedback_report: Readonly<Record<string, unknown>> | null;
  safety_flags: readonly string[];
  agent_turn_memory: readonly AgentTurnMemoryItem[];
  pedagogy_state: PedagogyState;
  reply?: string;
  current_intents?: readonly string[];
}>;

type AgentProcessingStepStatus = "pending" | "active" | "completed" | "skipped" | "error";

type AgentProcessingStep = Readonly<{
  id: string;
  label: string;
  status: AgentProcessingStepStatus;
  durationMs?: number;
  metadata?: Readonly<Record<string, unknown>>;
}>;

type AgentProcessingTimeline = Readonly<{
  state: "pending" | "completed";
  isOpen: boolean;
  title: string;
  summary: string;
  elapsedMs?: number;
  startedAtMs?: number;
  steps: readonly AgentProcessingStep[];
}>;

type ChatMessage = {
  readonly id: string;
  readonly speaker: "student" | "patient" | "coach";
  readonly label: string;
  readonly text: string;
  readonly emotion?: string | null;
  readonly apiMessageIndex?: number;
  readonly finalText?: string;
  readonly isPending?: boolean;
  readonly deliveryState?: "uncertain";
  readonly processingTimeline?: AgentProcessingTimeline;
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

type PhysicalExamBatchResult = Readonly<{
  exam_code: string;
  exam_name_cn: string;
  result: string;
  availability_status: ProcedureAvailabilityStatus;
}>;

type PhysicalExamBatchResponse = OsceSession &
  Readonly<{
    exam_results: readonly PhysicalExamBatchResult[];
  }>;

type AuxiliaryTestResponse = OsceSession &
  Readonly<{
    test_code: string;
    test_name_cn: string;
    result: string;
  }>;

type AuxiliaryTestBatchResult = Readonly<{
  test_code: string;
  test_name_cn: string;
  result: string;
  availability_status: ProcedureAvailabilityStatus;
}>;

type AuxiliaryTestBatchResponse = OsceSession &
  Readonly<{
    test_results: readonly AuxiliaryTestBatchResult[];
  }>;

type StandardizedProcedureRequest = Readonly<{
  mode: "advanced_free_text_catalog" | string;
  raw_request: string;
  matched_exam_codes: readonly string[];
  matched_test_codes: readonly string[];
  unmatched_requests: readonly string[];
  routed_unmatched_requests?: readonly RoutedUnmatchedProcedureRequest[];
  generated_result_policy: string;
  safety_boundary: string;
}>;

type RoutedUnmatchedProcedureRequest = Readonly<{
  raw_text: string;
  decision: "generate" | "clarify" | "block" | string;
  kind: "physical_exam" | "auxiliary_test" | "patient_profile" | "vital_sign" | "other" | string;
  name_cn: string;
  rationale: string;
  safety_issues: readonly string[];
}>;

type MatchedProcedureResult = Readonly<{
  id: string;
  kind: "physical_exam" | "auxiliary_test" | string;
  code: string;
  name_cn: string;
  label: string;
  result: string;
  availability_status: ProcedureAvailabilityStatus;
  generated_by_ai: boolean;
  approval_status: string;
  source_context_references: readonly string[];
  scoring_eligible: boolean;
}>;

type ProcedureFreeTextResponse = OsceSession &
  Readonly<{
    standardized_request: StandardizedProcedureRequest;
    matched_procedure_results: readonly MatchedProcedureResult[];
  }>;

type HintResponse = OsceSession &
  Readonly<{
    hint: string;
  }>;

type ProcedureResult = Readonly<{
  id: string;
  label: string;
  result: string;
  availabilityStatus?: ProcedureAvailabilityStatus;
  generatedByAi?: boolean;
  approvalStatus?: string;
  sourceContextReferences?: readonly string[];
  scoringEligible?: boolean;
}>;

type AdvancedProcedureRequestSummary = Readonly<{
  rawRequest: string;
  matchedLabels: readonly string[];
  unmatchedRequests: readonly string[];
  returnedResultCount: number;
  simulatedResultCount: number;
  unavailableResultCount: number;
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
  patientOpeningUtterance: string;
  enabled: boolean;
  patientProfile: StudentVisiblePatientProfile;
  openingTaskCard: OpeningTaskCard;
  physicalExamOptions: readonly PhysicalExamQuickOption[];
  auxiliaryTestOptions: readonly AuxiliaryTestQuickOption[];
}>;

type CaseSummary = Readonly<{
  case_id: string;
  case_title: string;
  course_module: string;
  difficulty: string;
  chief_complaint: string;
  patient_opening_utterance: string;
  enabled: boolean;
  patient_profile: StudentVisiblePatientProfile;
  opening_task_card: OpeningTaskCard;
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
  },
  {
    test_code: "lab.crp",
    test_name_cn: "C 反应蛋白",
    category: "实验室",
    invasiveness: "微创",
    cost_hint: "基础",
  },
  {
    test_code: "img.abd_us",
    test_name_cn: "腹部超声",
    category: "影像",
    invasiveness: "无创",
    cost_hint: "基础",
  },
  {
    test_code: "lab.urinalysis",
    test_name_cn: "尿常规",
    category: "实验室",
    invasiveness: "无创",
    cost_hint: "基础",
  },
  {
    test_code: "img.abd_ct",
    test_name_cn: "腹部 CT",
    category: "影像",
    invasiveness: "无创",
    cost_hint: "中等",
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

const appendicitisPatientOpeningUtterance = "医生您好，我这次主要是肚子疼，后来右下腹更明显，有点想吐，也有点发热。";

const defaultCaseOption: CaseOption = {
  id: DEFAULT_CASE_ID,
  title: "右下腹痛教学病例",
  module: "腹痛",
  difficulty: "初级",
  chiefComplaint: "转移性右下腹痛 24 小时，伴恶心、低热",
  patientOpeningUtterance: appendicitisPatientOpeningUtterance,
  enabled: true,
  patientProfile: appendicitisPatientProfile,
  openingTaskCard: appendicitisOpeningTaskCard,
  physicalExamOptions: appendicitisPhysicalExamOptions,
  auxiliaryTestOptions: appendicitisAuxiliaryTestOptions,
};
const STUDENT_ID = "web_demo";
const ADMIN_APP_URL = process.env.NEXT_PUBLIC_CLINICAL_OSCE_ADMIN_URL ?? "http://127.0.0.1:3001";
const ADMIN_MODEL_CONFIG_URL = `${ADMIN_APP_URL}#model-config`;
const DEPLOYMENT_MODE = process.env.NEXT_PUBLIC_CLINICAL_OSCE_DEPLOYMENT_MODE ?? "local-dev";
const LOCAL_AUTO_LOGIN_EMAIL = process.env.NEXT_PUBLIC_CLINICAL_OSCE_AUTO_LOGIN_EMAIL ?? "";
const LOCAL_AUTO_LOGIN_PASSWORD = process.env.NEXT_PUBLIC_CLINICAL_OSCE_AUTO_LOGIN_PASSWORD ?? "";
const isLocalAutoLoginConfigured =
  DEPLOYMENT_MODE === "local-dev" && Boolean(LOCAL_AUTO_LOGIN_EMAIL && LOCAL_AUTO_LOGIN_PASSWORD);
const PRODUCTION_DEPLOYMENT_MODES = new Set(["single-node-prod", "vertex-prod"]);
const isStudentRuntimeApiConfigEnabled = !PRODUCTION_DEPLOYMENT_MODES.has(DEPLOYMENT_MODE);
const isStudentApiConfigEditable = false;
const isAccountRegistrationEnabled = false;
const TEST_STAGE_API_CONFIG_MESSAGE = "测试阶段，统一使用我们提供的模型。";
const SERVER_MANAGED_API_CONFIG_MESSAGE = `${TEST_STAGE_API_CONFIG_MESSAGE}主对话模型为 Gemini 3.5 Flash，备用对话模型为 MiMo V2.5 Pro；向量检索优先使用 Gemini Embedding，失败时回落到本地向量模型。请不要高并发连续请求，上游 API 有速率限制。`;
const TRAINING_MODEL_CONFIG_REQUIRED_MESSAGE = "请先在 API 配置中应用可用模型，再开始训练。";
const OSCE_DOCK_POSITION_STORAGE_KEY = "clinical_osce_osce_dock_position";
const DIAGNOSIS_TEXTAREA_MAX_HEIGHT = 160;
const AUTH_EMAIL_MAX_CHARS = 254;
const AUTH_PASSWORD_MAX_CHARS = 256;
const QUESTION_MAX_CHARS = 500;
const PROCEDURE_REQUEST_MAX_CHARS = 500;
const DIAGNOSIS_MAX_CHARS = 128;
const DIAGNOSIS_DETAIL_MAX_CHARS = 700;
const DIFFERENTIAL_DIAGNOSIS_MAX_CHARS = 300;
const DIAGNOSIS_REASONING_MAX_CHARS = 4096;
const SPEECH_INPUT_MAX_CHARS = 2000;
const AUDIO_TRANSCRIPTION_MAX_BYTES = 10 * 1024 * 1024;
const OSCE_DOCK_MARGIN = 20;
const OSCE_DOCK_BUTTON_SIZE = 56;
const OSCE_DOCK_DRAG_THRESHOLD = 4;
const PATIENT_REPLY_TYPEWRITER_DELAY_MS = 14;
const BACKEND_HEALTH_CHECK_INTERVAL_MS = 30000;
const AGENT_PROCESSING_STATUS_POLL_INTERVAL_MS = 600;
const SPEECH_INPUT_DEFAULT_MIME_TYPE = "audio/webm";
const TEACHER_CONTEXT_EVALUATION_STEP_ID = "dialogue_context";
const TEACHER_CONTEXT_EVALUATION_STEP_LABEL = "正在评估当前对话上下文";

const AGENT_PROCESSING_STEP_DEFINITIONS: readonly Readonly<{ id: string; label: string }>[] = [
  { id: "intent", label: "正在解析问诊意图" },
  { id: TEACHER_CONTEXT_EVALUATION_STEP_ID, label: TEACHER_CONTEXT_EVALUATION_STEP_LABEL },
  { id: "case_context", label: "正在匹配病例事实" },
  { id: "skill", label: "正在评估是否调用 Skill" },
  { id: "rag", label: "正在检索教学知识库" },
  { id: "patient_reply", label: "正在组织标准化病人回复" },
  { id: "coach", label: "教师智能体正在复核边界" },
  { id: "response", label: "正在生成可见回复" },
];
const PATIENT_REPLY_PROCESSING_STEP_IDS = new Set(["intent", "case_context", "patient_reply", "response"]);

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
    patientOpeningUtterance: "",
    enabled: false,
    patientProfile: unavailablePatientProfile,
    openingTaskCard: unavailableOpeningTaskCard,
    physicalExamOptions: [],
    auxiliaryTestOptions: [],
  },
  {
    id: "hyperthyroid_001",
    title: "心慌、手抖与消瘦教学病例",
    module: "心悸",
    difficulty: "中级",
    chiefComplaint: "心慌、手抖 2 个月，消瘦 1 个月。",
    patientOpeningUtterance: "",
    enabled: false,
    patientProfile: unavailablePatientProfile,
    openingTaskCard: unavailableOpeningTaskCard,
    physicalExamOptions: [],
    auxiliaryTestOptions: [],
  },
  {
    id: "acs_001",
    title: "胸痛伴出汗教学病例",
    module: "胸痛",
    difficulty: "中级",
    chiefComplaint: "胸骨后压榨性胸痛 2 小时，伴大汗。",
    patientOpeningUtterance: "",
    enabled: false,
    patientProfile: unavailablePatientProfile,
    openingTaskCard: unavailableOpeningTaskCard,
    physicalExamOptions: [],
    auxiliaryTestOptions: [],
  },
  {
    id: "heart_failure_001",
    title: "活动后气短伴夜间憋醒教学病例",
    module: "呼吸困难",
    difficulty: "中级",
    chiefComplaint: "活动后气短 2 周，加重伴夜间憋醒 3 天。",
    patientOpeningUtterance: "",
    enabled: false,
    patientProfile: unavailablePatientProfile,
    openingTaskCard: unavailableOpeningTaskCard,
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

function isCompletedOsceSession(session: OsceSession | null): boolean {
  return Boolean(session?.final_submission || session?.feedback_report || session?.stage === "diagnosis_submission" || session?.stage === "feedback");
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

  const pedagogicalPhase = session.pedagogy_state?.clinical_reasoning_state?.pedagogical_phase;
  if (pedagogicalPhase === "needs_history") {
    return 1;
  }
  if (pedagogicalPhase === "needs_physical_exam") {
    return 2;
  }
  if (pedagogicalPhase === "needs_auxiliary_test") {
    return 3;
  }
  if (pedagogicalPhase === "needs_reasoning") {
    return 4;
  }
  if (pedagogicalPhase === "ready_for_submission") {
    return 5;
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
    return "选择病例后，发送问诊或点击训练操作会自动创建训练会话。";
  }

  if (feedbackReport || session.feedback_report) {
    return "已生成评分报告，可前往训练记录页复盘。";
  }

  if (session.final_submission) {
    return "诊断已提交，请查看评分报告，也可前往训练记录页复盘。";
  }

  const clinicalReasoningState = session.pedagogy_state?.clinical_reasoning_state;
  if (clinicalReasoningState?.next_best_action?.message) {
    const sequenceNote = clinicalReasoningState.sequence_flags.length > 0 ? "已识别训练顺序缺口：" : "";
    return `${sequenceNote}${clinicalReasoningState.next_best_action.message}`;
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
  primaryDiagnosis: string,
  otherPossibleDiagnoses: string,
  supportingEvidence: string,
  differentialReasoning: string,
  nextStep: string,
  uncertainty: string,
): string {
  return [
    `当前诊断假设：${primaryDiagnosis}`,
    otherPossibleDiagnoses ? `鉴别诊断：${otherPossibleDiagnoses}` : "",
    `支持依据：${supportingEvidence}`,
    `鉴别与排除：${differentialReasoning}`,
    nextStep ? `下一步验证计划：${nextStep}` : "",
    uncertainty ? `证据不足或不确定点：${uncertainty}` : "",
  ].filter(Boolean).join("\n");
}

function formatStage(stage: string | undefined): string {
  const stageLabel = stageDefinitions.find((definition) => definition.key === stage)?.label;
  return stageLabel ?? "等待会话";
}

function formatIntentList(currentIntents: readonly string[] | undefined): string {
  return currentIntents && currentIntents.length > 0 ? currentIntents.join("、") : "未识别意图";
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

function normalizePatientEmotion(emotion: string | null | undefined): string | null {
  const normalizedEmotion = emotion?.trim();
  if (!normalizedEmotion || normalizedEmotion === "平静" || normalizedEmotion === "neutral") {
    return null;
  }
  return normalizedEmotion;
}

function mapApiMessage(
  message: ApiMessage,
  index: number,
  session?: OsceSession,
): ChatMessage {
  const id = `${message.role}-${index}-${message.content}`;

  if (message.role === "student") {
    return {
      id,
      speaker: "student",
      label: "学生",
      text: message.content,
      apiMessageIndex: index,
    };
  }

  if (message.role === "coach") {
    const coachLabel = getCoachMessageLabel(message.content);
    return {
      id,
      speaker: "coach",
      label: coachLabel,
      text: message.content,
      apiMessageIndex: index,
      processingTimeline: coachLabel === "安全边界" ? undefined : session ? buildCompletedCoachProcessingTimeline(session, message.content) : undefined,
    };
  }

  return {
    id,
    speaker: "patient",
    label: "标准化病人",
    text: message.content,
    emotion: normalizePatientEmotion(message.emotion),
    apiMessageIndex: index,
    processingTimeline: session ? buildCompletedAgentProcessingTimeline(session, message.content) : undefined,
  };
}

function formatAgentProcessingElapsed(elapsedMs: number | undefined): string {
  if (elapsedMs === undefined) {
    return "流程记录";
  }
  const safeElapsedMs = Math.max(0, Math.round(elapsedMs));
  if (safeElapsedMs === 0) {
    return "瞬时";
  }
  if (safeElapsedMs < 1000) {
    return `${safeElapsedMs} ms`;
  }
  const elapsedSeconds = safeElapsedMs / 1000;
  return elapsedSeconds < 10 ? `${elapsedSeconds.toFixed(1)} 秒` : `${Math.round(elapsedSeconds)} 秒`;
}

function formatAgentProcessingTimerElapsed(elapsedMs: number): string {
  const elapsedSeconds = Math.max(0, Math.floor(elapsedMs / 1000));
  return `${elapsedSeconds} 秒`;
}

function getPatientReplyProcessingSteps<TStep extends Readonly<{ id: string }>>(steps: readonly TStep[]): readonly TStep[] {
  return steps.filter((step) => PATIENT_REPLY_PROCESSING_STEP_IDS.has(step.id));
}

function stripTerminalChinesePunctuation(text: string): string {
  return text.trim().replace(/[。.!！?？]+$/u, "");
}

function getPendingPatientProcessingSummary(
  processingStatus: SessionProcessingStatus | null | undefined,
  visibleSteps: readonly AgentProcessingStep[],
): string {
  if (!processingStatus) {
    return "当前：正在建立后端流程连接";
  }
  const latestVisibleStep = [...visibleSteps].reverse().find((step) => step.status === "completed" || step.status === "active");
  return latestVisibleStep ? `当前：${stripTerminalChinesePunctuation(getAgentProcessingStepLabel(latestVisibleStep))}` : "当前：正在组织标准化病人回复";
}

function buildPendingAgentProcessingTimeline(processingStatus?: SessionProcessingStatus | null): AgentProcessingTimeline {
  const statusSteps = processingStatus?.steps.map((step) => ({
    id: step.step_id,
    label: step.label,
    status: normalizeAgentProcessingStepStatus(step.status),
  })) ?? [];
  const patientSteps = getPatientReplyProcessingSteps(statusSteps);
  const hasActiveVisibleStep = patientSteps.some((step) => step.status === "active");
  const timelineSteps = processingStatus?.state === "running" && patientSteps.length > 0 && !hasActiveVisibleStep
    ? [
        ...patientSteps,
        {
          id: "response_wait",
          label: "正在等待可见回复返回",
          status: "active" as const,
        },
      ]
    : patientSteps;
  const currentStepId = processingStatus?.current_step_id ?? "backend_connect";
  const isPatientFallbackStep = PATIENT_REPLY_PROCESSING_STEP_IDS.has(currentStepId);
  const fallbackStepId = isPatientFallbackStep ? currentStepId : "response_wait";
  const fallbackStepLabel = isPatientFallbackStep
    ? processingStatus?.current_label || "正在组织标准化病人回复"
    : "正在等待标准化病人回复";
  return {
    state: "pending",
    isOpen: false,
    title: "智能体处理中",
    summary: getPendingPatientProcessingSummary(processingStatus, timelineSteps),
    steps: timelineSteps.length > 0 ? timelineSteps : [
      {
        id: fallbackStepId,
        label: fallbackStepLabel,
        status: "active",
      },
    ],
  };
}

function buildPendingHintProcessingTimeline(processingStatus?: SessionProcessingStatus | null): AgentProcessingTimeline {
  const statusSteps = processingStatus?.steps.map((step) => ({
    id: step.step_id,
    label: step.step_id === "response" ? "正在生成过程提示" : step.label,
    status: normalizeAgentProcessingStepStatus(step.status),
  })) ?? [];
  const hasActiveStep = statusSteps.some((step) => step.status === "active");
  const currentStepId = processingStatus?.current_step_id ?? "backend_connect";
  const hasCurrentStep = statusSteps.some((step) => step.id === currentStepId);
  const fallbackStep = {
    id: currentStepId || "hint_response_wait",
    label: currentStepId === "response" ? "正在生成过程提示" : processingStatus?.current_label || "正在生成过程提示",
    status: "active" as const,
  };
  const timelineSteps = processingStatus?.state === "running" && !hasActiveStep && !hasCurrentStep
    ? [...statusSteps, fallbackStep]
    : statusSteps;
  const displaySteps = withTeacherContextEvaluationStep(timelineSteps);
  return {
    state: "pending",
    isOpen: true,
    title: "教师智能体处理中",
    summary: stripTerminalChinesePunctuation(processingStatus?.summary ?? "当前：正在评估当前对话上下文。"),
    steps: displaySteps,
  };
}

function withTeacherContextEvaluationStep(steps: readonly AgentProcessingStep[]): readonly AgentProcessingStep[] {
  if (steps.some((step) => step.id === TEACHER_CONTEXT_EVALUATION_STEP_ID)) {
    return steps;
  }
  const contextStepStatus: AgentProcessingStepStatus = steps.length > 0 ? "completed" : "active";
  return [
    {
      id: TEACHER_CONTEXT_EVALUATION_STEP_ID,
      label: TEACHER_CONTEXT_EVALUATION_STEP_LABEL,
      status: contextStepStatus,
    },
    ...steps,
  ];
}

function getBackendProcessingTraceElapsedMs(turn: AgentTurnMemoryItem | undefined): number | undefined {
  if (!turn) {
    return undefined;
  }
  if (typeof turn.processing_duration_ms === "number") {
    return turn.processing_duration_ms;
  }
  const trace = turn.processing_trace ?? [];
  if (trace.length === 0) {
    return undefined;
  }
  return trace.reduce((totalDuration, step) => totalDuration + Math.max(0, step.duration_ms || 0), 0);
}

function getTimelineStepsFromBackendProcessingTrace(trace: readonly BackendProcessingTraceItem[] | undefined): readonly AgentProcessingStep[] {
  if (!trace || trace.length === 0) {
    return [];
  }
  return trace.map((step) => ({
    id: step.step_id,
    label: step.label || AGENT_PROCESSING_STEP_DEFINITIONS.find((definition) => definition.id === step.step_id)?.label || step.step_id,
    status: normalizeAgentProcessingStepStatus(step.status),
    durationMs: step.duration_ms,
    metadata: step.metadata,
  }));
}

function normalizeAgentProcessingStepStatus(status: string): AgentProcessingStepStatus {
  if (status === "completed" || status === "skipped" || status === "error" || status === "active") {
    return status;
  }
  return "completed";
}

function getAgentProcessingStepRetrievedCount(step: AgentProcessingStep): number | undefined {
  const retrievedCount = step.metadata?.retrieved_count ?? step.metadata?.retrievedCount;
  if (typeof retrievedCount !== "number" || !Number.isFinite(retrievedCount)) {
    return undefined;
  }
  return Math.max(0, Math.trunc(retrievedCount));
}

function getKnowledgeReferenceCountFromProcessingSteps(steps: readonly AgentProcessingStep[]): number {
  return steps.reduce((totalCount, step) => {
    if (step.id !== "rag") {
      return totalCount;
    }
    return totalCount + (getAgentProcessingStepRetrievedCount(step) ?? 0);
  }, 0);
}

function buildCompletedAgentProcessingTimeline(session: OsceSession, replyText: string): AgentProcessingTimeline {
  const patientTurn = getLatestAgentTurnForReply(session, replyText, "patient");
  const backendTraceSteps = getTimelineStepsFromBackendProcessingTrace(patientTurn?.processing_trace);
  const patientTraceSteps = getPatientReplyProcessingSteps(backendTraceSteps);
  const elapsedMs = getBackendProcessingTraceElapsedMs(patientTurn);
  const hasCurrentIntents = Boolean(session.current_intents?.length || (patientTurn?.current_intents?.length ?? 0) > 0);
  const hasCaseReferences = (patientTurn?.revealed_fact_count ?? 0) > 0;
  const completedParts = [
    hasCurrentIntents ? "意图解析" : "",
    hasCaseReferences ? "病例事实" : "",
    replyText ? "标准化病人回复" : "",
  ].filter(Boolean);

  return {
    state: "completed",
    isOpen: false,
    title: "智能体处理了",
    summary: completedParts.length > 0 ? `已完成：${completedParts.join(" · ")}` : "已完成本轮安全生成流程",
    elapsedMs,
    steps: patientTraceSteps.length > 0 ? patientTraceSteps : AGENT_PROCESSING_STEP_DEFINITIONS
      .filter((stepDefinition) => PATIENT_REPLY_PROCESSING_STEP_IDS.has(stepDefinition.id))
      .map((stepDefinition) => {
      const statusByStepId: Readonly<Record<string, AgentProcessingStepStatus>> = {
        intent: hasCurrentIntents ? "completed" : "skipped",
        case_context: hasCaseReferences ? "completed" : "skipped",
        patient_reply: replyText ? "completed" : "error",
        response: "completed",
      };
      return {
        ...stepDefinition,
        status: statusByStepId[stepDefinition.id] ?? "skipped",
      };
    }),
  };
}

function buildCompletedCoachProcessingTimeline(session: OsceSession, replyText: string): AgentProcessingTimeline | undefined {
  const coachTurn = getLatestAgentTurnForReply(session, replyText, "coach");
  if (!coachTurn) {
    return undefined;
  }
  const backendTraceSteps = getTimelineStepsFromBackendProcessingTrace(coachTurn.processing_trace);
  const elapsedMs = getBackendProcessingTraceElapsedMs(coachTurn);
  const selectedSkillCount = coachTurn.selected_skill_count;
  const knowledgeReferenceCount = Math.max(
    getKnowledgeReferenceCountFromProcessingSteps(backendTraceSteps),
    coachTurn.knowledge_reference_count,
  );
  const completedParts = [
    "教师复核",
    selectedSkillCount > 0 ? `Skill ${selectedSkillCount} 条` : "",
    knowledgeReferenceCount > 0 ? `知识库 ${knowledgeReferenceCount} 条` : "",
  ].filter(Boolean);

  return {
    state: "completed",
    isOpen: false,
    title: "教师智能体处理了",
    summary: completedParts.length > 0 ? `已完成：${completedParts.join(" · ")}` : "已完成过程提示生成",
    elapsedMs,
    steps: withTeacherContextEvaluationStep(backendTraceSteps.length > 0 ? backendTraceSteps : AGENT_PROCESSING_STEP_DEFINITIONS
      .filter((stepDefinition) => stepDefinition.id !== "patient_reply")
      .map((stepDefinition) => ({
        ...stepDefinition,
        status: "completed",
      }))),
  };
}

function getLatestAgentTurnForReply(
  session: OsceSession | undefined,
  replyText: string,
  replyRole: "patient" | "coach",
): AgentTurnMemoryItem | undefined {
  if (!session || !replyText) {
    return undefined;
  }
  return [...session.agent_turn_memory].reverse().find(
    (turn) => turn.reply === replyText && turn.reply_role === replyRole,
  );
}

function getLatestPassiveCoachReviewTurn(
  session: OsceSession | undefined,
  studentMessage: string,
): AgentTurnMemoryItem | undefined {
  if (!session) {
    return undefined;
  }
  return [...session.agent_turn_memory].reverse().find((turn) => {
    const isPassiveCoachTurn = turn.reply_role === "coach" && turn.turn_policy.startsWith("passive_review");
    if (!studentMessage) {
      return isPassiveCoachTurn;
    }
    return isPassiveCoachTurn && turn.student_message === studentMessage;
  });
}

function getAgentProcessingStepLabel(step: AgentProcessingStep): string {
  const isCoachResponseStep = step.id === "response" && (
    step.metadata?.reply_role === "coach" || step.label.includes("过程提示")
  );
  if (isCoachResponseStep) {
    if (step.status === "completed") {
      return "已生成过程提示";
    }
    if (step.status === "skipped") {
      return "本轮无过程提示";
    }
    if (step.status === "error") {
      return "过程提示生成失败";
    }
  }
  const completedLabels: Readonly<Record<string, string>> = {
    intent: "已解析问诊意图",
    [TEACHER_CONTEXT_EVALUATION_STEP_ID]: "已评估当前对话上下文",
    case_context: "已匹配病例事实",
    skill: "已评估 Skill 调用",
    rag: "已检索教学知识库",
    patient_reply: "已组织标准化病人回复",
    coach: "教师智能体已复核边界",
    response: "已生成可见回复",
  };
  const skippedLabels: Readonly<Record<string, string>> = {
    intent: "未识别具体问诊意图",
    [TEACHER_CONTEXT_EVALUATION_STEP_ID]: "本轮未评估当前对话上下文",
    case_context: "未命中新增病例事实",
    skill: "本轮未调用 Skill",
    rag: "本轮未使用知识库",
    patient_reply: "本轮未生成病人回复",
    coach: "本轮未触发教师智能体复核",
    response: "本轮无可见回复",
  };
  const errorLabels: Readonly<Record<string, string>> = {
    patient_reply: "标准化病人回复生成失败",
    response: "可见回复生成失败",
  };

  if (step.status === "completed") {
    if (step.id === "rag") {
      const retrievedCount = getAgentProcessingStepRetrievedCount(step);
      if (retrievedCount !== undefined) {
        return `已检索教学知识库：命中 ${retrievedCount} 条`;
      }
    }
    return completedLabels[step.id] ?? step.label;
  }
  if (step.status === "skipped") {
    return skippedLabels[step.id] ?? `本轮未触发：${step.label.replace(/^正在/, "")}`;
  }
  if (step.status === "error") {
    return errorLabels[step.id] ?? `流程异常：${step.label.replace(/^正在/, "")}`;
  }
  return step.label;
}

function getReplyMessageMetadata(session: OsceSession, replyText: string): Pick<ChatMessage, "speaker" | "label" | "apiMessageIndex"> {
  const matchingReplyMessage = session.messages
    .map((message, index) => ({ message, index }))
    .reverse()
    .find(({ message }) => message.content === replyText && (message.role === "coach" || message.role === "patient"));

  if (matchingReplyMessage?.message.role === "coach") {
    return {
      speaker: "coach",
      label: getCoachMessageLabel(replyText),
      apiMessageIndex: matchingReplyMessage.index,
    };
  }

  return {
    speaker: "patient",
    label: "标准化病人",
    apiMessageIndex: matchingReplyMessage?.index,
  };
}

function getVisibleApiMessagesDuringPendingReply(
  messages: readonly ApiMessage[],
  pendingPatientMessage: ChatMessage | null,
): readonly ApiMessage[] {
  if (!pendingPatientMessage?.finalText || pendingPatientMessage.apiMessageIndex === undefined) {
    return messages;
  }

  if (pendingPatientMessage.apiMessageIndex < 0 || pendingPatientMessage.apiMessageIndex >= messages.length) {
    return messages.filter((message) => message.role !== "coach");
  }

  return messages.slice(0, pendingPatientMessage.apiMessageIndex + 1);
}

function getPatientSpeechText(message: ChatMessage): string {
  return (message.finalText ?? message.text).trim();
}

function canShowPatientSpeechPlayback(message: ChatMessage): boolean {
  return message.speaker === "patient" && !message.isPending && getPatientSpeechText(message).length > 0;
}

function getShortEvidenceId(factId: string): string {
  const separatorIndex = factId.lastIndexOf(".");
  return separatorIndex === -1 ? factId : factId.slice(separatorIndex + 1);
}

const evidenceSlotLabels: Readonly<Record<string, string>> = {
  onset: "起病时间",
  location: "症状部位",
  migration: "部位变化",
  character: "症状性质",
  severity: "症状程度",
  associated_symptom: "伴随表现",
  past_medical: "既往史",
  allergy: "过敏史",
  personal: "个人史",
  family: "家族史",
  menstrual: "月经史",
  medication: "用药史",
  social: "社会史",
  ice: "就诊想法",
};

function getEvidenceTopicLabel(topic?: string | null): string | null {
  const normalizedTopic = topic?.trim();
  return normalizedTopic ? normalizedTopic : null;
}

function getEvidenceSlotLabel(slot?: string | null): string | null {
  const normalizedSlot = slot?.trim();
  if (!normalizedSlot) {
    return null;
  }

  return evidenceSlotLabels[normalizedSlot] ?? normalizedSlot.replaceAll("_", " ");
}

function getEvidenceLabelFromRevealedItem(item: StudentRevealedItem, fallbackIndex: number): string {
  const topicLabel = getEvidenceTopicLabel(item.topic);
  const slotLabel = getEvidenceSlotLabel(item.slot);
  if (slotLabel) {
    return slotLabel;
  }
  if (topicLabel) {
    return topicLabel;
  }

  return `问诊线索 ${fallbackIndex + 1}`;
}

function getEvidenceItem(factId: string, trainingProgress: TrainingProgress | null, fallbackIndex: number): EvidenceItem {
  const shortFactId = getShortEvidenceId(factId);
  const revealedHistoryItem = trainingProgress?.revealed_items.history.find(
    (item) => item.id === factId || item.id === shortFactId,
  );
  if (revealedHistoryItem) {
    return {
      label: getEvidenceLabelFromRevealedItem(revealedHistoryItem, fallbackIndex),
      detail: revealedHistoryItem.label,
    };
  }

  return {
    label: `问诊线索 ${fallbackIndex + 1}`,
    detail: "已收集该结构化问诊事实。",
  };
}

function mapCollectedProcedureResults(
  collectedProcedureResults: CollectedProcedureResults,
): readonly ProcedureResult[] {
  return [
    ...collectedProcedureResults.physical_exams.map((exam) => ({
      id: `exam:${exam.exam_code}`,
      label: `查体：${exam.exam_name_cn}`,
      result: exam.result,
    })),
    ...collectedProcedureResults.auxiliary_tests.map((test) => ({
      id: `test:${test.test_code}`,
      label: `检查：${test.test_name_cn}`,
      result: test.result,
    })),
  ];
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
    patientOpeningUtterance: caseSummary.patient_opening_utterance,
    enabled: caseSummary.enabled,
    patientProfile: caseSummary.patient_profile,
    openingTaskCard: caseSummary.opening_task_card,
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

type ApiRequestOutcome = "rejected" | "uncertain";

class ApiRequestError extends Error {
  readonly outcome: ApiRequestOutcome;
  readonly status: number | null;

  constructor(message: string, outcome: ApiRequestOutcome, status: number | null = null) {
    super(message);
    this.name = "ApiRequestError";
    this.outcome = outcome;
    this.status = status;
  }
}

async function requestJson<TResponse>(path: string, init: RequestInit): Promise<TResponse> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      credentials: "same-origin",
      headers,
    });
  } catch {
    throw new ApiRequestError(
      "网络连接中断，服务器处理结果暂时无法确认。",
      "uncertain",
    );
  }

  if (!response.ok) {
    throw new ApiRequestError(
      await getRequestErrorMessage(response),
      response.status >= 500 || response.status === 408
        ? "uncertain"
        : "rejected",
      response.status,
    );
  }

  try {
    return (await response.json()) as TResponse;
  } catch {
    throw new ApiRequestError(
      "服务器已处理请求，但响应无法解析，结果暂时无法确认。",
      "uncertain",
      response.status,
    );
  }
}

async function transcribeSpeechAudio(file: File): Promise<SpeechTranscriptionResponse> {
  const body = new FormData();
  body.append("file", file);
  body.append("language", "zh");

  const response = await fetch("/api/audio/transcriptions", {
    method: "POST",
    body,
    credentials: "same-origin",
  });

  if (!response.ok) {
    throw new Error(await getRequestErrorMessage(response));
  }

  return (await response.json()) as SpeechTranscriptionResponse;
}

async function synthesizePatientSpeech(text: string, context: PatientSpeechContext): Promise<Blob> {
  const response = await fetch("/api/audio/speech", {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      input: text,
      session_id: context.sessionId,
      message_index: context.messageIndex,
      emotion: context.emotion,
    }),
  });

  if (!response.ok) {
    throw new Error(await getRequestErrorMessage(response));
  }

  return response.blob();
}

async function checkBackendConnection(): Promise<boolean> {
  const response = await fetch("/api/health", {
    cache: "no-store",
    credentials: "same-origin",
  });
  return response.ok;
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

function getBackendConnectionStatusLabel(status: BackendConnectionStatus): string {
  if (status === "online") {
    return "后端状态：在线";
  }
  if (status === "offline") {
    return "后端状态：离线";
  }
  return "后端状态：检测中";
}

function getBackendStatusHaloClass(status: BackendConnectionStatus): string {
  if (status === "online") {
    return "bg-[#65B87B]";
  }
  if (status === "offline") {
    return "bg-red-500";
  }
  return "bg-[#D7A64F]";
}

function getBackendStatusLightClass(status: BackendConnectionStatus): string {
  if (status === "online") {
    return "bg-[#4F9F68] shadow-[0_0_12px_rgba(79,159,104,0.78)]";
  }
  if (status === "offline") {
    return "bg-red-500 shadow-[0_0_12px_rgba(239,68,68,0.65)]";
  }
  return "bg-[#D7A64F] shadow-[0_0_12px_rgba(215,166,79,0.65)]";
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

function normalizeTrainingDifficultyMode(rawMode: string | null | undefined): TrainingDifficultyMode {
  if (rawMode === "intermediate" || rawMode === "advanced") {
    return rawMode;
  }
  return "beginner";
}

function getTrainingDifficultyModeFromSearchParams(searchParams: SearchParamReader): TrainingDifficultyMode {
  return normalizeTrainingDifficultyMode(searchParams.get("difficulty"));
}

function getTrainingDifficultyLabel(trainingDifficultyMode: TrainingDifficultyMode): string {
  if (trainingDifficultyMode === "intermediate") {
    return "中级";
  }
  if (trainingDifficultyMode === "advanced") {
    return "高级";
  }
  return "初级";
}

function buildHintContextSignature(
  session: OsceSession | null | undefined,
  selectedCaseId: string | null,
  trainingDifficultyMode: TrainingDifficultyMode,
): string {
  const nonCoachMessages = session?.messages
    .filter((message) => message.role !== "coach")
    .map((message) => `${message.role}:${message.content}`) ?? [];

  return JSON.stringify({
    session_id: session?.session_id ?? null,
    case_id: session?.case_id ?? selectedCaseId,
    difficulty: session?.training_difficulty ?? trainingDifficultyMode,
    stage: session?.stage ?? null,
    non_coach_messages: nonCoachMessages,
    asked_questions: session?.asked_questions ?? [],
    revealed_facts: session?.revealed_facts ?? [],
    requested_exams: session?.requested_exams ?? [],
    requested_tests: session?.requested_tests ?? [],
    student_hypotheses: session?.student_hypotheses ?? [],
  });
}

function createSession(caseId: string, trainingDifficultyMode: TrainingDifficultyMode): Promise<OsceSession> {
  return requestJson<OsceSession>("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ case_id: caseId, student_id: STUDENT_ID, training_difficulty: trainingDifficultyMode }),
  });
}

function sendHistoryMessage(sessionId: string, message: string): Promise<OsceSession> {
  return requestJson<OsceSession>(`/api/sessions/${sessionId}/message`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

function fetchProcedureCatalog(): Promise<ProcedureCatalog> {
  return requestJson<ProcedureCatalog>("/api/procedure-catalog", {
    method: "GET",
  });
}

function fetchSessionProcessingStatus(sessionId: string): Promise<SessionProcessingStatus> {
  return requestJson<SessionProcessingStatus>(`/api/sessions/${sessionId}/processing-status`, {
    method: "GET",
  });
}

function requestPhysicalExam(sessionId: string, examCode: string): Promise<PhysicalExamResponse> {
  return requestJson<PhysicalExamResponse>(`/api/sessions/${sessionId}/physical-exam`, {
    method: "POST",
    body: JSON.stringify({ exam_code: examCode }),
  });
}

function requestPhysicalExamBatch(sessionId: string, examCodes: readonly string[]): Promise<PhysicalExamBatchResponse> {
  return requestJson<PhysicalExamBatchResponse>(`/api/sessions/${sessionId}/physical-exams`, {
    method: "POST",
    body: JSON.stringify({ exam_codes: examCodes }),
  });
}

function requestAuxiliaryTest(sessionId: string, testCode: string): Promise<AuxiliaryTestResponse> {
  return requestJson<AuxiliaryTestResponse>(`/api/sessions/${sessionId}/auxiliary-test`, {
    method: "POST",
    body: JSON.stringify({ test_code: testCode }),
  });
}

function requestAuxiliaryTestBatch(sessionId: string, testCodes: readonly string[]): Promise<AuxiliaryTestBatchResponse> {
  return requestJson<AuxiliaryTestBatchResponse>(`/api/sessions/${sessionId}/auxiliary-tests`, {
    method: "POST",
    body: JSON.stringify({ test_codes: testCodes }),
  });
}

function requestProcedureText(sessionId: string, requestText: string): Promise<ProcedureFreeTextResponse> {
  return requestJson<ProcedureFreeTextResponse>(`/api/sessions/${sessionId}/procedure-request`, {
    method: "POST",
    body: JSON.stringify({ request_text: requestText }),
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

function generateSessionReport(sessionId: string): Promise<FeedbackReport> {
  return requestJson<FeedbackReport>(`/api/sessions/${sessionId}/report/generate`, {
    method: "POST",
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

function MicrophoneIcon() {
  return (
    <svg aria-hidden="true" className="size-4" fill="none" viewBox="0 0 24 24">
      <path
        d="M12 4a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V7a3 3 0 0 0-3-3Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
      />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg aria-hidden="true" className="size-4" fill="none" viewBox="0 0 24 24">
      <path d="M8 8h8v8H8z" fill="currentColor" />
    </svg>
  );
}

function LoadingSpinnerIcon() {
  return (
    <svg aria-hidden="true" className="size-4 animate-spin" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" />
      <path className="opacity-80" d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeLinecap="round" strokeWidth="3" />
    </svg>
  );
}

function SpeakerIcon() {
  return (
    <svg aria-hidden="true" className="size-4" fill="none" viewBox="0 0 24 24">
      <path
        d="M4 10v4h4l5 4V6L8 10H4Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
      />
      <path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
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

function AgentProcessingTimelineView({ timeline }: Readonly<{ timeline: AgentProcessingTimeline }>) {
  const activeStepStartedAtRef = useRef<Map<string, number>>(new Map());
  const [timerNowMs, setTimerNowMs] = useState(() => Date.now());
  const pendingStartedAtMs = timeline.state === "pending" ? timeline.startedAtMs : undefined;
  const activeStepSignature = timeline.state === "pending"
    ? timeline.steps
      .filter((step) => step.status === "active")
      .map((step) => step.id)
      .join("|")
    : "";
  const activeStepIds = activeStepSignature ? activeStepSignature.split("|") : [];

  useEffect(() => {
    if (timeline.state !== "pending" || !activeStepSignature) {
      activeStepStartedAtRef.current.clear();
      return;
    }
    const nowMs = Date.now();
    const nextActiveStepIds = activeStepSignature.split("|");
    for (const stepId of nextActiveStepIds) {
      if (!activeStepStartedAtRef.current.has(stepId)) {
        activeStepStartedAtRef.current.set(stepId, nowMs);
      }
    }
    for (const stepId of Array.from(activeStepStartedAtRef.current.keys())) {
      if (!nextActiveStepIds.includes(stepId)) {
        activeStepStartedAtRef.current.delete(stepId);
      }
    }
    setTimerNowMs(nowMs);
  }, [activeStepSignature, timeline.state]);

  useEffect(() => {
    if (timeline.state !== "pending" || (!activeStepSignature && pendingStartedAtMs === undefined)) {
      return;
    }
    const intervalId = window.setInterval(() => {
      setTimerNowMs(Date.now());
    }, 1000);
    return () => window.clearInterval(intervalId);
  }, [activeStepSignature, pendingStartedAtMs, timeline.state]);

  const getActiveStepElapsedMs = (stepId: string) => {
    const startedAtMs = activeStepStartedAtRef.current.get(stepId) ?? timerNowMs;
    return Math.max(0, timerNowMs - startedAtMs);
  };
  const activeStepElapsedMs = timeline.state === "pending" && activeStepIds.length > 0
    ? Math.max(...activeStepIds.map((stepId) => getActiveStepElapsedMs(stepId)))
    : undefined;
  const pendingElapsedMs = timeline.state === "pending" && pendingStartedAtMs !== undefined
    ? Math.max(0, timerNowMs - pendingStartedAtMs)
    : activeStepElapsedMs;
  const thoughtLine = timeline.state === "pending"
    ? `${timeline.title} · ${timeline.summary}${pendingElapsedMs === undefined ? "" : ` · ${formatAgentProcessingTimerElapsed(pendingElapsedMs)}`}`
    : timeline.elapsedMs === undefined
      ? "智能体流程"
      : `智能体处理了 ${formatAgentProcessingElapsed(timeline.elapsedMs)}`;
  return (
    <details
      className="group mt-3 text-sm"
      key={`${timeline.state}-${timeline.elapsedMs ?? "no-duration"}`}
      open={timeline.isOpen}
    >
      <summary className="inline-flex cursor-pointer list-none items-center gap-2 text-muted-foreground transition hover:text-foreground">
        <span
          aria-hidden="true"
          className={`size-1.5 rounded-full ${timeline.state === "pending" ? "clinical-osce-agent-process-dot-active bg-[#B85A32]" : "bg-[#9A9186]"}`}
        />
        <span>{thoughtLine}</span>
        <span aria-hidden="true" className="text-lg leading-none transition-transform group-open:rotate-90">
          ›
        </span>
      </summary>
      <p className="mt-2 text-xs leading-5 text-[#8A7E72]">{timeline.summary}</p>
      <ol className="ml-1 mt-2 border-l border-[#DDD4C6] pl-4 text-xs leading-5 text-[#6F6257]">
        {timeline.steps.map((step, stepIndex) => {
          const isLastStep = stepIndex === timeline.steps.length - 1;
          const displayDurationMs = step.durationMs ?? (
            timeline.state === "pending" && step.status === "active"
              ? getActiveStepElapsedMs(step.id)
              : undefined
          );
          const dotClassName = [
            "absolute -left-[1.42rem] top-0.5 z-10 flex size-4 items-center justify-center rounded-full border text-[10px] font-bold leading-none transition-colors",
            step.status === "completed"
              ? "border-brand bg-brand text-white"
              : step.status === "active"
                ? "clinical-osce-agent-process-dot-active border-[#D6A54F] bg-[#FFF8E8] text-[#8A5A00]"
              : step.status === "error"
                  ? "border-red-300 bg-red-50 text-red-600"
                  : step.status === "skipped"
                    ? "border-[#DDD4C6] bg-white text-[#B0A497]"
                    : "border-[#D8D1C5] bg-[#FAF9F5] text-transparent",
          ].join(" ");
          return (
            <li className={`relative ${isLastStep ? "" : "pb-2"}`} key={step.id}>
              <span className={dotClassName} aria-hidden="true">
                {step.status === "completed" ? "✓" : step.status === "error" ? "!" : step.status === "skipped" ? "·" : ""}
              </span>
              <span
                className={
                  step.status === "completed"
                    ? "text-[#4F463D]"
                    : step.status === "active"
                      ? "font-medium text-[#8A5A00]"
                      : step.status === "error"
                        ? "text-red-600"
                        : "text-muted-foreground"
                }
              >
                {getAgentProcessingStepLabel(step)}
                {displayDurationMs !== undefined ? (
                  <span className="ml-1 text-[11px] text-[#9A9186]">
                    · {step.status === "active" ? formatAgentProcessingTimerElapsed(displayDurationMs) : formatAgentProcessingElapsed(displayDurationMs)}
                  </span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ol>
    </details>
  );
}

function CaseSelectionPrompt({ onDismiss }: Readonly<{ onDismiss: () => void }>) {
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
        <p className="mt-2 text-sm font-semibold text-foreground">请先选择一个病例</p>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          进入病例后，系统会显示开局任务卡；在首次训练动作前不会创建训练记录。
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
  const router = useRouter();
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
  const [apiConfigStatusText, setApiConfigStatusText] = useState(
    isStudentApiConfigEditable ? "配置按当前登录账号保存在后端；密钥不会回显。" : SERVER_MANAGED_API_CONFIG_MESSAGE,
  );
  const [apiConfigTestResult, setApiConfigTestResult] = useState<StudentApiConfigTestResponse | null>(null);
  const [isTestingStudentApiConfig, setIsTestingStudentApiConfig] = useState(false);
  const [isApplyingStudentApiConfig, setIsApplyingStudentApiConfig] = useState(false);
  const [backendConnectionStatus, setBackendConnectionStatus] = useState<BackendConnectionStatus>("checking");
  const isTrainingModelConfigReady = Boolean(runtimeApiConfig?.active) || (!isStudentApiConfigEditable && backendConnectionStatus === "online");
  const [rightPanelOpenStates, setRightPanelOpenStates] = useState<Record<RightPanelKey, boolean>>({
    evidence: true,
    report: true,
  });
  const [session, setSession] = useState<OsceSession | null>(null);
  const [inputValue, setInputValue] = useState("");
  const [speechInputState, setSpeechInputState] = useState<"idle" | "recording" | "transcribing">("idle");
  const [speechStatusText, setSpeechStatusText] = useState<string | null>(null);
  const [speechPlaybackState, setSpeechPlaybackState] = useState<Readonly<{ messageId: string; status: "loading" | "playing" }> | null>(null);
  const [statusText, setStatusText] = useState("选择病例后，发送问诊或点击训练操作会自动创建训练会话。");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [optimisticHistoryMessage, setOptimisticHistoryMessage] = useState<ChatMessage | null>(null);
  const [pendingPatientMessage, setPendingPatientMessage] = useState<ChatMessage | null>(null);
  const [pendingCoachHintMessage, setPendingCoachHintMessage] = useState<ChatMessage | null>(null);
  const [isCasePreparationPromptDismissed, setIsCasePreparationPromptDismissed] = useState(false);
  const [openProcedureActionGroup, setOpenProcedureActionGroup] = useState<ProcedureActionGroup | null>(null);
  const [trainingDifficultyMode, setTrainingDifficultyMode] = useState<TrainingDifficultyMode>(() => getTrainingDifficultyModeFromSearchParams(searchParams));
  const [procedureCatalog, setProcedureCatalog] = useState<ProcedureCatalog | null>(null);
  const [isLoadingProcedureCatalog, setIsLoadingProcedureCatalog] = useState(false);
  const [selectedIntermediateExamCodes, setSelectedIntermediateExamCodes] = useState<readonly string[]>([]);
  const [selectedIntermediateTestCodes, setSelectedIntermediateTestCodes] = useState<readonly string[]>([]);
  const [advancedProcedureRequestText, setAdvancedProcedureRequestText] = useState("");
  const [advancedProcedureUnmatchedRequests, setAdvancedProcedureUnmatchedRequests] = useState<readonly string[]>([]);
  const [isRequestingAdvancedProcedure, setIsRequestingAdvancedProcedure] = useState(false);
  const [isRequestingExam, setIsRequestingExam] = useState(false);
  const [isRequestingTest, setIsRequestingTest] = useState(false);
  const [isRequestingHint, setIsRequestingHint] = useState(false);
  const [lastHintContextSignature, setLastHintContextSignature] = useState<string | null>(null);
  const [diagnosisValue, setDiagnosisValue] = useState("");
  const [differentialDiagnosisValue, setDifferentialDiagnosisValue] = useState("");
  const [supportingEvidenceValue, setSupportingEvidenceValue] = useState("");
  const [exclusionEvidenceValue, setExclusionEvidenceValue] = useState("");
  const [nextStepValue, setNextStepValue] = useState("");
  const [uncertaintyValue, setUncertaintyValue] = useState("");
  const [isDiagnosisComposerOpen, setIsDiagnosisComposerOpen] = useState(false);
  const [isSubmittingDiagnosis, setIsSubmittingDiagnosis] = useState(false);
  const [feedbackReport, setFeedbackReport] = useState<FeedbackReport | null>(null);
  const [procedureResults, setProcedureResults] = useState<readonly ProcedureResult[]>([]);
  const [selectedProcedureResult, setSelectedProcedureResult] = useState<ProcedureResult | null>(null);
  const [selectedProcedureResults, setSelectedProcedureResults] = useState<readonly ProcedureResult[]>([]);
  const [isAdvancedProcedureRequestSummaryOpen, setIsAdvancedProcedureRequestSummaryOpen] = useState(false);
  const [advancedProcedureRequestSummary, setAdvancedProcedureRequestSummary] = useState<AdvancedProcedureRequestSummary | null>(null);
  const [latestRevealedFactId, setLatestRevealedFactId] = useState<string | null>(null);
  const [isPatientProfileOpen, setIsPatientProfileOpen] = useState(false);
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [isAuthDialogOpen, setIsAuthDialogOpen] = useState(false);
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
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
  const questionInputRef = useRef<HTMLInputElement | null>(null);
  const latestEvidenceItemRef = useRef<HTMLDivElement | null>(null);
  const hasAttemptedLocalAutoLoginRef = useRef(false);
  const previousRevealedFactIdsRef = useRef<readonly string[] | null>(null);
  const previousRevealedFactsSessionIdRef = useRef<string | null>(null);
  const clientChatMessageSequenceRef = useRef(0);
  const trainingContextEpochRef = useRef(0);
  const speechInputMediaRecorderRef = useRef<MediaRecorder | null>(null);
  const speechInputStreamRef = useRef<MediaStream | null>(null);
  const speechInputChunksRef = useRef<Blob[]>([]);
  const patientSpeechAudioRef = useRef<HTMLAudioElement | null>(null);
  const patientSpeechObjectUrlRef = useRef<string | null>(null);
  const isNextStepRequired = trainingDifficultyMode !== "beginner";

  useEffect(() => {
    trainingContextEpochRef.current += 1;
  }, [authUser?.user_id, requestedSessionId]);

  function createClientChatMessageId(prefix: string): string {
    clientChatMessageSequenceRef.current += 1;
    return `${prefix}-${clientChatMessageSequenceRef.current}`;
  }

  function stopSpeechInputStream(): void {
    speechInputStreamRef.current?.getTracks().forEach((track) => track.stop());
    speechInputStreamRef.current = null;
    speechInputMediaRecorderRef.current = null;
  }

  function stopPatientSpeechPlayback(options: { updateState?: boolean } = {}): void {
    patientSpeechAudioRef.current?.pause();
    patientSpeechAudioRef.current = null;
    if (patientSpeechObjectUrlRef.current) {
      URL.revokeObjectURL(patientSpeechObjectUrlRef.current);
      patientSpeechObjectUrlRef.current = null;
    }
    if (options.updateState !== false) {
      setSpeechPlaybackState(null);
    }
  }

  function getSpeechInputRecorderOptions(): MediaRecorderOptions | undefined {
    if (typeof MediaRecorder === "undefined") {
      return undefined;
    }
    const opusMimeType = "audio/webm;codecs=opus";
    if (MediaRecorder.isTypeSupported(opusMimeType)) {
      return { mimeType: opusMimeType };
    }
    if (MediaRecorder.isTypeSupported(SPEECH_INPUT_DEFAULT_MIME_TYPE)) {
      return { mimeType: SPEECH_INPUT_DEFAULT_MIME_TYPE };
    }
    return undefined;
  }

  async function handleSpeechRecordingStopped(recordedMimeType: string): Promise<void> {
    const chunks = speechInputChunksRef.current;
    speechInputChunksRef.current = [];
    stopSpeechInputStream();
    if (chunks.length === 0) {
      setSpeechInputState("idle");
      setSpeechStatusText(null);
      setErrorText("没有录到有效语音，请检查麦克风后重试。");
      return;
    }

    setSpeechInputState("transcribing");
    setSpeechStatusText("正在转写语音...");
    setErrorText(null);

    try {
      const mimeType = recordedMimeType || SPEECH_INPUT_DEFAULT_MIME_TYPE;
      const audioBlob = new Blob(chunks, { type: mimeType });
      const extension = mimeType.includes("wav") ? "wav" : "webm";
      const audioFile = new File([audioBlob], `osce-question-${Date.now()}.${extension}`, { type: mimeType });
      if (audioFile.size > AUDIO_TRANSCRIPTION_MAX_BYTES) {
        setSpeechStatusText(null);
        setErrorText("录音超过 10 MiB，请缩短后重试。");
        return;
      }
      const result = await transcribeSpeechAudio(audioFile);
      const transcript = result.text.trim();
      if (!transcript) {
        setSpeechStatusText(null);
        setErrorText("语音已处理，但没有识别到可用文字。");
        return;
      }
      setInputValue((currentValue) => {
        const cleanCurrentValue = currentValue.trim();
        const combinedTranscript = cleanCurrentValue ? `${cleanCurrentValue} ${transcript}` : transcript;
        return combinedTranscript;
      });
      setSpeechStatusText(`转写内容已完整保留到输入框；单次问诊最多发送 ${QUESTION_MAX_CHARS} 个字符，请按需删减。`);
      questionInputRef.current?.focus();
    } catch (error) {
      setSpeechStatusText(null);
      setErrorText(error instanceof Error ? error.message : "语音转写失败。");
    } finally {
      setSpeechInputState("idle");
    }
  }

  async function handleSpeechInputButtonClick(): Promise<void> {
    if (speechInputState === "recording") {
      const recorder = speechInputMediaRecorderRef.current;
      setSpeechStatusText("正在结束录音并转写...");
      if (recorder && recorder.state !== "inactive") {
        recorder.stop();
      } else {
        await handleSpeechRecordingStopped(SPEECH_INPUT_DEFAULT_MIME_TYPE);
      }
      return;
    }

    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setErrorText("当前浏览器不支持录音输入。");
      return;
    }

    try {
      setErrorText(null);
      setSpeechStatusText("正在请求麦克风权限...");
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const recorderOptions = getSpeechInputRecorderOptions();
      const recorder = recorderOptions ? new MediaRecorder(stream, recorderOptions) : new MediaRecorder(stream);
      speechInputStreamRef.current = stream;
      speechInputMediaRecorderRef.current = recorder;
      speechInputChunksRef.current = [];
      const recordedMimeType = recorder.mimeType || recorderOptions?.mimeType || SPEECH_INPUT_DEFAULT_MIME_TYPE;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          speechInputChunksRef.current.push(event.data);
        }
      };
      recorder.onstop = () => {
        void handleSpeechRecordingStopped(recordedMimeType);
      };
      recorder.onerror = () => {
        stopSpeechInputStream();
        setSpeechInputState("idle");
        setSpeechStatusText(null);
        setErrorText("录音过程中出现错误，请重新尝试。");
      };
      recorder.start();
      setSpeechInputState("recording");
      setSpeechStatusText("正在录音，点击结束后转写到输入框。");
    } catch (error) {
      stopSpeechInputStream();
      setSpeechInputState("idle");
      setSpeechStatusText(null);
      setErrorText(error instanceof Error ? error.message : "无法访问麦克风。");
    }
  }

  async function handlePatientSpeechButtonClick(message: ChatMessage): Promise<void> {
    const speechText = getPatientSpeechText(message);
    if (!speechText) {
      return;
    }
    if (speechPlaybackState?.messageId === message.id) {
      stopPatientSpeechPlayback();
      return;
    }
    if (speechText.length > SPEECH_INPUT_MAX_CHARS) {
      stopPatientSpeechPlayback();
      setErrorText(`患者回复超过 ${SPEECH_INPUT_MAX_CHARS} 个字符，暂时无法生成语音。`);
      return;
    }

    stopPatientSpeechPlayback({ updateState: false });
    setSpeechPlaybackState({ messageId: message.id, status: "loading" });
    setErrorText(null);

    try {
      const audioBlob = await synthesizePatientSpeech(speechText, {
        sessionId: session?.session_id,
        messageIndex: message.apiMessageIndex,
        emotion: message.emotion,
      });
      const audioUrl = URL.createObjectURL(audioBlob);
      patientSpeechObjectUrlRef.current = audioUrl;
      const audio = new Audio(audioUrl);
      patientSpeechAudioRef.current = audio;
      audio.onended = () => stopPatientSpeechPlayback();
      audio.onerror = () => {
        stopPatientSpeechPlayback();
        setErrorText("患者语音播放失败。");
      };
      await audio.play();
      setSpeechPlaybackState({ messageId: message.id, status: "playing" });
    } catch (error) {
      stopPatientSpeechPlayback({ updateState: false });
      setSpeechPlaybackState(null);
      setErrorText(error instanceof Error ? error.message : "患者语音生成失败。");
    }
  }

  useEffect(() => {
    return () => {
      const recorder = speechInputMediaRecorderRef.current;
      if (recorder?.state === "recording") {
        recorder.onstop = null;
        recorder.stop();
      }
      stopSpeechInputStream();
      stopPatientSpeechPlayback({ updateState: false });
    };
  }, []);

  useEffect(() => {
    let isMounted = true;

    async function refreshBackendConnectionStatus(): Promise<void> {
      try {
        const isOnline = await checkBackendConnection();
        if (isMounted) {
          setBackendConnectionStatus(isOnline ? "online" : "offline");
        }
      } catch {
        if (isMounted) {
          setBackendConnectionStatus("offline");
        }
      }
    }

    void refreshBackendConnectionStatus();
    const intervalId = window.setInterval(() => {
      void refreshBackendConnectionStatus();
    }, BACKEND_HEALTH_CHECK_INTERVAL_MS);

    return () => {
      isMounted = false;
      window.clearInterval(intervalId);
    };
  }, []);

  useEffect(() => {
    if (isCheckingAuth) {
      return;
    }

    if (!authUser) {
      setRuntimeApiConfig(null);
      setStudentApiConfig(createDefaultStudentApiConfig());
      if (!isStudentApiConfigEditable) {
        setApiConfigStatusText(SERVER_MANAGED_API_CONFIG_MESSAGE);
      }
      return;
    }

    let isMounted = true;
    async function loadRuntimeApiConfig() {
      try {
        const runtimeConfig = await getStudentRuntimeApiConfig();
        if (isMounted) {
          setRuntimeApiConfig(runtimeConfig);
          setStudentApiConfig(createStudentApiConfigFromRuntime(runtimeConfig));
          if (!isStudentApiConfigEditable) {
            setApiConfigStatusText(SERVER_MANAGED_API_CONFIG_MESSAGE);
          }
        }
      } catch {
        if (isMounted) {
          setRuntimeApiConfig(null);
          setStudentApiConfig(createDefaultStudentApiConfig());
          if (!isStudentApiConfigEditable) {
            setApiConfigStatusText(SERVER_MANAGED_API_CONFIG_MESSAGE);
          }
        }
      }
    }

    void loadRuntimeApiConfig();
    return () => {
      isMounted = false;
    };
  }, [authUser, isCheckingAuth]);

  useEffect(() => {
    if (!isApiConfigHelpOpen || !authUser) {
      return;
    }

    let isMounted = true;
    async function loadRuntimeApiConfig() {
      try {
        const runtimeConfig = await getStudentRuntimeApiConfig();
        if (isMounted) {
          setRuntimeApiConfig(runtimeConfig);
          setStudentApiConfig(createStudentApiConfigFromRuntime(runtimeConfig));
          if (!isStudentApiConfigEditable) {
            setApiConfigStatusText(SERVER_MANAGED_API_CONFIG_MESSAGE);
          }
        }
      } catch {
        if (isMounted) {
          setRuntimeApiConfig(null);
          if (!isStudentApiConfigEditable) {
            setApiConfigStatusText(SERVER_MANAGED_API_CONFIG_MESSAGE);
          }
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
        let currentUser = await getCurrentUser();
        if (
          currentUser === null
          && isLocalAutoLoginConfigured
          && !isLocalAutoLoginSuppressed(window.sessionStorage)
          && !hasAttemptedLocalAutoLoginRef.current
        ) {
          hasAttemptedLocalAutoLoginRef.current = true;
          setAuthEmail(LOCAL_AUTO_LOGIN_EMAIL);
          setAuthPassword(LOCAL_AUTO_LOGIN_PASSWORD);
          currentUser = await loginUser(LOCAL_AUTO_LOGIN_EMAIL, LOCAL_AUTO_LOGIN_PASSWORD);
        }
        if (!isMounted) {
          return;
        }

        setAuthUser(currentUser);
        setIsAuthDialogOpen(currentUser === null);
        if (currentUser !== null) {
          setAuthEmail("");
          setAuthPassword("");
        }
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
    if (!requestedSessionId) {
      setTrainingDifficultyMode(getTrainingDifficultyModeFromSearchParams(searchParams));
    }
  }, [requestedSessionId, searchParams]);

  useEffect(() => {
    if (isCheckingAuth) {
      return;
    }

    if (!authUser) {
      setIsCreating(false);
      setSession(null);
      setOptimisticHistoryMessage(null);
      setPendingPatientMessage(null);
      setPendingCoachHintMessage(null);
      setStatusText("请先登录后再开始或恢复训练。");
      return;
    }

    if (!requestedSessionId) {
      setIsCreating(false);
      setSession(null);
      setOptimisticHistoryMessage(null);
      setPendingPatientMessage(null);
      setPendingCoachHintMessage(null);
      setFeedbackReport(null);
      setProcedureResults([]);
      setSelectedProcedureResult(null);
      setSelectedProcedureResults([]);
      setIsAdvancedProcedureRequestSummaryOpen(false);
      setAdvancedProcedureRequestSummary(null);
      setSelectedIntermediateExamCodes([]);
      setSelectedIntermediateTestCodes([]);
      setAdvancedProcedureRequestText("");
      setAdvancedProcedureUnmatchedRequests([]);
      setIsPatientProfileOpen(false);
      setDiagnosisValue("");
      setDifferentialDiagnosisValue("");
      setSupportingEvidenceValue("");
      setExclusionEvidenceValue("");
      setNextStepValue("");
      setUncertaintyValue("");
      setIsDiagnosisComposerOpen(false);
      setStatusText(
        selectedCaseId
          ? isTrainingModelConfigReady
            ? "已选择病例，发送问诊或点击训练操作会自动创建训练会话。"
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
      setOptimisticHistoryMessage(null);
      setPendingPatientMessage(null);
      setPendingCoachHintMessage(null);
      setInputValue("");
      setDiagnosisValue("");
      setDifferentialDiagnosisValue("");
      setSupportingEvidenceValue("");
      setExclusionEvidenceValue("");
      setNextStepValue("");
      setUncertaintyValue("");
      setIsDiagnosisComposerOpen(false);
      setFeedbackReport(null);
      setProcedureResults([]);
      setSelectedProcedureResult(null);
      setSelectedProcedureResults([]);
      setIsAdvancedProcedureRequestSummaryOpen(false);
      setAdvancedProcedureRequestSummary(null);
      setSelectedIntermediateExamCodes([]);
      setSelectedIntermediateTestCodes([]);
      setAdvancedProcedureRequestText("");
      setAdvancedProcedureUnmatchedRequests([]);
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
        setTrainingDifficultyMode(nextSession.training_difficulty);
        setProcedureResults(mapCollectedProcedureResults(nextSession.collected_procedure_results));
        setStatusText(isCompletedOsceSession(nextSession) ? "该训练已提交诊断，训练已结束。可以查看评分报告或重新选择病例开始新训练。" : "已恢复后端训练会话，可以继续训练。");
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

  useEffect(() => {
    const currentSessionId = session?.session_id ?? null;
    const currentRevealedFactIds = session?.revealed_facts ?? [];

    if (!currentSessionId) {
      previousRevealedFactsSessionIdRef.current = null;
      previousRevealedFactIdsRef.current = null;
      setLatestRevealedFactId(null);
      return;
    }

    if (previousRevealedFactsSessionIdRef.current !== currentSessionId) {
      previousRevealedFactsSessionIdRef.current = currentSessionId;
      previousRevealedFactIdsRef.current = currentRevealedFactIds;
      setLatestRevealedFactId(null);
      return;
    }

    const previousRevealedFactIds = previousRevealedFactIdsRef.current ?? [];
    previousRevealedFactIdsRef.current = currentRevealedFactIds;
    const previousRevealedFactIdSet = new Set(previousRevealedFactIds);
    const newestRevealedFactId = [...currentRevealedFactIds].reverse().find((factId) => !previousRevealedFactIdSet.has(factId));

    if (!newestRevealedFactId) {
      return;
    }

    setLatestRevealedFactId(newestRevealedFactId);
    setRightPanelOpenStates((currentStates) => currentStates.evidence ? currentStates : { ...currentStates, evidence: true });
  }, [session?.revealed_facts, session?.session_id]);

  useEffect(() => {
    if (!latestRevealedFactId || !rightPanelOpenStates.evidence) {
      return;
    }

    const scrollTimer = window.setTimeout(() => {
      latestEvidenceItemRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 100);

    return () => {
      window.clearTimeout(scrollTimer);
    };
  }, [latestRevealedFactId, rightPanelOpenStates.evidence]);

  useEffect(() => {
    if (!latestRevealedFactId) {
      return;
    }

    const glowTimer = window.setTimeout(() => {
      setLatestRevealedFactId((currentFactId) => currentFactId === latestRevealedFactId ? null : currentFactId);
    }, 2600);

    return () => {
      window.clearTimeout(glowTimer);
    };
  }, [latestRevealedFactId]);

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
    if (!isStudentApiConfigEditable) {
      setApiConfigStatusText(SERVER_MANAGED_API_CONFIG_MESSAGE);
      return;
    }
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
    if (!isStudentApiConfigEditable) {
      setApiConfigStatusText(SERVER_MANAGED_API_CONFIG_MESSAGE);
      return;
    }
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
    if (!isStudentApiConfigEditable) {
      setApiConfigStatusText(SERVER_MANAGED_API_CONFIG_MESSAGE);
      setApiConfigTestResult(null);
      return;
    }
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
  const currentHintContextSignature = useMemo(
    () => buildHintContextSignature(session, selectedCaseId, trainingDifficultyMode),
    [selectedCaseId, session, trainingDifficultyMode],
  );
  const isHintRequestLocked = Boolean(
    selectedCaseId
    && lastHintContextSignature
    && lastHintContextSignature === currentHintContextSignature
  );
  const hintButtonLabel = isRequestingHint
    ? "提示生成中"
    : isHintRequestLocked
      ? "开始问诊"
      : "请求提示";
  const physicalExamOptions = session?.physical_exam_options ?? selectedCase?.physicalExamOptions ?? [];
  const auxiliaryTestOptions = session?.auxiliary_test_options ?? selectedCase?.auxiliaryTestOptions ?? [];
  const intermediatePhysicalExamOptions = procedureCatalog?.physical_exams ?? [];
  const intermediateAuxiliaryTestOptions = procedureCatalog?.auxiliary_tests ?? [];
  const isCurrentSessionCompleted = isCompletedOsceSession(session);
  const isSpeechInputRecording = speechInputState === "recording";
  const isSpeechInputTranscribing = speechInputState === "transcribing";
  const isSpeechInputBusy = isSpeechInputRecording || isSpeechInputTranscribing;
  const hasUncertainHistoryMessage = (
    optimisticHistoryMessage?.deliveryState === "uncertain"
  );
  const isSpeechInputButtonDisabled =
    !authUser
    || !selectedCaseId
    || !isTrainingModelConfigReady
    || isCurrentSessionCompleted
    || isCreating
    || isSending
    || hasUncertainHistoryMessage
    || isSpeechInputTranscribing;
  const speechInputButtonAriaLabel = isSpeechInputRecording ? "结束录音" : isSpeechInputTranscribing ? "正在转写语音" : "开始语音输入";
  const speechInputButtonTitle = isSpeechInputRecording ? "结束录音" : isSpeechInputTranscribing ? "正在转写语音" : "语音输入";
  const requestedExamCodeSet = useMemo(() => new Set(session?.requested_exams ?? []), [session?.requested_exams]);
  const requestedTestCodeSet = useMemo(() => new Set(session?.requested_tests ?? []), [session?.requested_tests]);
  const pendingPhysicalExamOptions = physicalExamOptions.filter((examOption) => !requestedExamCodeSet.has(examOption.exam_code));
  const completedPhysicalExamOptions = physicalExamOptions.filter((examOption) => requestedExamCodeSet.has(examOption.exam_code));
  const pendingAuxiliaryTestOptions = auxiliaryTestOptions.filter((testOption) => !requestedTestCodeSet.has(testOption.test_code));
  const completedAuxiliaryTestOptions = auxiliaryTestOptions.filter((testOption) => requestedTestCodeSet.has(testOption.test_code));
  const pendingIntermediatePhysicalExamOptions = intermediatePhysicalExamOptions.filter((examOption) => !requestedExamCodeSet.has(examOption.exam_code));
  const completedIntermediatePhysicalExamOptions = intermediatePhysicalExamOptions.filter((examOption) => requestedExamCodeSet.has(examOption.exam_code));
  const pendingIntermediateAuxiliaryTestOptions = intermediateAuxiliaryTestOptions.filter((testOption) => !requestedTestCodeSet.has(testOption.test_code));
  const completedIntermediateAuxiliaryTestOptions = intermediateAuxiliaryTestOptions.filter((testOption) => requestedTestCodeSet.has(testOption.test_code));
  const isIntermediateTrainingMode = trainingDifficultyMode === "intermediate";
  const isAdvancedTrainingMode = trainingDifficultyMode === "advanced";
  const isPhysicalExamActionDisabled = !authUser
    || !selectedCaseId
    || !isTrainingModelConfigReady
    || isCurrentSessionCompleted
    || isAdvancedTrainingMode
    || (trainingDifficultyMode === "beginner" && physicalExamOptions.length === 0);
  const isAuxiliaryTestActionDisabled = !authUser
    || !selectedCaseId
    || !isTrainingModelConfigReady
    || isCurrentSessionCompleted
    || isAdvancedTrainingMode
    || (trainingDifficultyMode === "beginner" && auxiliaryTestOptions.length === 0);
  const catalogPhysicalExamLabelMap = useMemo(
    () => new Map(intermediatePhysicalExamOptions.map((examOption) => [examOption.exam_code, examOption.exam_name_cn] as const)),
    [intermediatePhysicalExamOptions],
  );
  const catalogAuxiliaryTestLabelMap = useMemo(
    () => new Map(intermediateAuxiliaryTestOptions.map((testOption) => [testOption.test_code, testOption.test_name_cn] as const)),
    [intermediateAuxiliaryTestOptions],
  );
  const preparedOpeningTaskCard = session?.opening_task_card ?? selectedCase?.openingTaskCard ?? null;
  const preparedPatientProfile = session?.patient_profile ?? selectedCase?.patientProfile ?? null;
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
  const backendConnectionStatusLabel = getBackendConnectionStatusLabel(backendConnectionStatus);
  const backendStatusLightClass = getBackendStatusLightClass(backendConnectionStatus);
  const backendStatusHaloClass = getBackendStatusHaloClass(backendConnectionStatus);

  const chatMessages = useMemo<readonly ChatMessage[]>(() => {
    let baseMessages: ChatMessage[] = [];
    if (session) {
      baseMessages = [
        ...baseMessages,
        ...getVisibleApiMessagesDuringPendingReply(session.messages, pendingPatientMessage).map((message, index) =>
          mapApiMessage(message, index, session),
        ),
      ];
    }

    let didReplacePendingPatientMessage = false;
    if (pendingPatientMessage?.finalText) {
      baseMessages = baseMessages.map((message) => {
        if (
          !didReplacePendingPatientMessage
          && message.apiMessageIndex !== undefined
          && message.apiMessageIndex === pendingPatientMessage.apiMessageIndex
        ) {
          didReplacePendingPatientMessage = true;
          return pendingPatientMessage;
        }
        return message;
      });
    }

    const nextMessages = [...baseMessages];
    if (optimisticHistoryMessage) {
      nextMessages.push(optimisticHistoryMessage);
    }
    if (pendingPatientMessage && !didReplacePendingPatientMessage) {
      nextMessages.push(pendingPatientMessage);
    }
    if (pendingCoachHintMessage) {
      nextMessages.push(pendingCoachHintMessage);
    }

    return nextMessages;
  }, [optimisticHistoryMessage, pendingCoachHintMessage, pendingPatientMessage, session]);

  useEffect(() => {
    const chatScrollContainer = chatScrollContainerRef.current;
    if (!chatScrollContainer) {
      return;
    }
    chatScrollContainer.scrollTo({
      top: chatScrollContainer.scrollHeight,
      behavior: "smooth",
    });
  }, [chatMessages.length, optimisticHistoryMessage?.text, pendingCoachHintMessage?.text, pendingPatientMessage?.text, statusText, errorText]);

  const evidenceItems = useMemo(() => {
    if (!session) {
      return [];
    }

    return session.revealed_facts.map((factId, itemIndex) => ({
      id: factId,
      ...getEvidenceItem(factId, session.training_progress, itemIndex),
    }));
  }, [session]);

  const requestedItems = useMemo(
    () => [
      ...(session?.requested_exams.map((exam) => ({
        id: `exam:${exam}`,
        label: `查体：${physicalExamOptions.find((examOption) => examOption.exam_code === exam)?.exam_name_cn ?? catalogPhysicalExamLabelMap.get(exam) ?? exam}`,
      })) ?? []),
      ...(session?.requested_tests.map((test) => ({
        id: `test:${test}`,
        label: `检查：${auxiliaryTestOptions.find((testOption) => testOption.test_code === test)?.test_name_cn ?? catalogAuxiliaryTestLabelMap.get(test) ?? test}`,
      })) ?? []),
    ],
    [auxiliaryTestOptions, catalogAuxiliaryTestLabelMap, catalogPhysicalExamLabelMap, physicalExamOptions, session?.requested_exams, session?.requested_tests],
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

  const advancedProcedureRequestItemsToShow = useMemo<readonly ProcedureResult[]>(
    () => isAdvancedTrainingMode ? procedureItems : [],
    [isAdvancedTrainingMode, procedureItems],
  );

  const advancedProcedureRequestSummaryToShow = useMemo<AdvancedProcedureRequestSummary | null>(() => {
    if (!isAdvancedTrainingMode) {
      return null;
    }
    const draftRequest = advancedProcedureRequestText.trim();
    if (!draftRequest && advancedProcedureUnmatchedRequests.length === 0 && advancedProcedureRequestItemsToShow.length === 0) {
      return null;
    }
    const simulatedResultCount = advancedProcedureRequestItemsToShow.filter((procedureItem) => procedureItem.generatedByAi).length;
    const unavailableResultCount = advancedProcedureRequestItemsToShow.filter((procedureItem) => procedureItem.availabilityStatus === "not_available_for_case").length;
    return {
      rawRequest: advancedProcedureRequestSummary?.rawRequest || draftRequest || "全部已申请项目",
      matchedLabels: advancedProcedureRequestItemsToShow.map((procedureItem) => procedureItem.label),
      unmatchedRequests: advancedProcedureRequestSummary?.unmatchedRequests ?? advancedProcedureUnmatchedRequests,
      returnedResultCount: advancedProcedureRequestItemsToShow.length,
      simulatedResultCount,
      unavailableResultCount,
    };
  }, [advancedProcedureRequestItemsToShow, advancedProcedureRequestSummary, advancedProcedureRequestText, advancedProcedureUnmatchedRequests, isAdvancedTrainingMode]);

  function getProcedureResultById(procedureId: string): ProcedureResult | null {
    return procedureItems.find((item) => item.id === procedureId) ?? null;
  }

  function openProcedureResultGroup(nextProcedureResults: readonly ProcedureResult[]) {
    const firstProcedureResult = nextProcedureResults[0] ?? null;
    setSelectedProcedureResult(firstProcedureResult);
    setSelectedProcedureResults(firstProcedureResult ? nextProcedureResults : []);
  }

  function openProcedureResult(nextProcedureResult: ProcedureResult | null) {
    openProcedureResultGroup(nextProcedureResult ? [nextProcedureResult] : []);
  }

  function closeProcedureResultModal() {
    setSelectedProcedureResult(null);
    setSelectedProcedureResults([]);
  }

  function openAdvancedProcedureRequestSummary() {
    setIsAdvancedProcedureRequestSummaryOpen(true);
  }

  function closeAdvancedProcedureRequestSummary() {
    setIsAdvancedProcedureRequestSummaryOpen(false);
  }

  function formatProcedureResultText(procedureResult: ProcedureResult): string {
    if (!procedureResult.generatedByAi) {
      return procedureResult.result;
    }
    return procedureResult.result
      .replace(/^AI 模拟[：:]\s*/, "")
      .replace(/（训练参考，不进入评分。）$/, "")
      .trim();
  }

  const sourceReferenceGroups = useMemo(
    () => groupSourceReferences(feedbackReport?.source_reference_items ?? [], feedbackReport?.source_references ?? []),
    [feedbackReport?.source_reference_items, feedbackReport?.source_references],
  );
  const reportDimensionMaxScores = useMemo(() => getDimensionMaxScoresFromRubricScores(feedbackReport?.rubric_scores), [feedbackReport?.rubric_scores]);

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
      `已披露线索：${session?.revealed_facts.length ?? 0} / ${session?.training_progress.history.total ?? 0} 条`,
      `最终诊断：${session?.final_submission?.diagnosis ?? "尚未提交"}`,
      `安全边界：${session?.safety_flags.length ?? 0} 次`,
    ],
    [
      session?.asked_questions.length,
      session?.final_submission?.diagnosis,
      session?.revealed_facts.length,
      session?.training_progress.history.total,
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
      const nextUser = await loginUser(email, authPassword);
      clearLocalAutoLoginSuppression(window.sessionStorage);
      setAuthUser(nextUser);
      setAuthPassword("");
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
    if (isSubmittingAuth || isSending) {
      return;
    }

    setIsSubmittingAuth(true);
    setAuthErrorText(null);
    setIsAccountMenuOpen(false);

    try {
      await logoutUser();
      suppressLocalAutoLogin(window.sessionStorage);
      setAuthUser(null);
      setAuthEmail("");
      setAuthPassword("");
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

  async function handleStartNewSession(): Promise<void> {
    if (isCreating || isSending) {
      return;
    }

    if (!authUser) {
      setStatusText("请先登录后再开始或恢复训练。");
      setIsAuthDialogOpen(true);
      return;
    }

    if (!selectedCaseId) {
      setStatusText("请先选择病例，再开启新会话。");
      setErrorText("请先选择病例，再开启新会话。");
      return;
    }

    if (!isTrainingModelConfigReady) {
      promptTrainingModelConfigRequired();
      return;
    }

    setIsCreating(true);
    setErrorText(null);
    setInputValue("");
    setDiagnosisValue("");
    setDifferentialDiagnosisValue("");
    setSupportingEvidenceValue("");
    setExclusionEvidenceValue("");
    setNextStepValue("");
    setUncertaintyValue("");
    setIsDiagnosisComposerOpen(false);
    setFeedbackReport(null);
    setProcedureResults([]);
    setSelectedProcedureResult(null);
    setSelectedProcedureResults([]);
    setIsAdvancedProcedureRequestSummaryOpen(false);
    setAdvancedProcedureRequestSummary(null);
    setSelectedIntermediateExamCodes([]);
    setSelectedIntermediateTestCodes([]);
    setAdvancedProcedureRequestText("");
    setAdvancedProcedureUnmatchedRequests([]);
    setPendingPatientMessage(null);
    setPendingCoachHintMessage(null);
    setOptimisticHistoryMessage(null);
    setIsPatientProfileOpen(false);
    setStatusText("正在创建训练会话...");

    try {
      const nextSession = await createSession(selectedCaseId, trainingDifficultyMode);
      setSession(nextSession);
      setSelectedCaseId(nextSession.case_id);
      setTrainingDifficultyMode(nextSession.training_difficulty);
      setStatusText("已创建训练会话，可以继续训练。");
    } catch (error) {
      const message = error instanceof Error ? error.message : "创建训练会话失败。";
      if (message === "请先登录后再继续训练。") {
        setAuthUser(null);
        setIsAuthDialogOpen(true);
      }
      setStatusText(message === "请先登录后再继续训练。" ? message : "训练会话创建失败，请确认后端仍在运行。");
      setErrorText(message);
    } finally {
      setIsCreating(false);
    }
  }

  async function ensureActiveSession(
    expectedContextEpoch: number = trainingContextEpochRef.current,
  ): Promise<OsceSession | null> {
    if (expectedContextEpoch !== trainingContextEpochRef.current) {
      return null;
    }
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
      const nextSession = await createSession(selectedCaseId, trainingDifficultyMode);
      if (expectedContextEpoch !== trainingContextEpochRef.current) {
        return null;
      }
      setSession(nextSession);
      setSelectedCaseId(nextSession.case_id);
      setTrainingDifficultyMode(nextSession.training_difficulty);
      setStatusText("已创建训练会话，可以继续训练。");
      return nextSession;
    } catch (error) {
      if (expectedContextEpoch !== trainingContextEpochRef.current) {
        return null;
      }
      const message = error instanceof Error ? error.message : "创建训练会话失败。";
      if (message === "请先登录后再继续训练。") {
        setAuthUser(null);
        setIsAuthDialogOpen(true);
      }
      setStatusText(message === "请先登录后再继续训练。" ? message : "训练会话创建失败，请确认后端仍在运行。");
      setErrorText(message);
      return null;
    } finally {
      if (expectedContextEpoch === trainingContextEpochRef.current) {
        setIsCreating(false);
      }
    }
  }

  async function ensureProcedureCatalog(): Promise<ProcedureCatalog | null> {
    if (procedureCatalog) {
      return procedureCatalog;
    }

    setIsLoadingProcedureCatalog(true);
    setErrorText(null);

    try {
      const nextProcedureCatalog = await fetchProcedureCatalog();
      setProcedureCatalog(nextProcedureCatalog);
      return nextProcedureCatalog;
    } catch (error) {
      const message = error instanceof Error ? error.message : "读取查体检查目录失败。";
      setErrorText(message);
      setStatusText("读取查体检查目录失败，请确认后端仍在运行。");
      return null;
    } finally {
      setIsLoadingProcedureCatalog(false);
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

  function refreshPendingProcessingTimeline(sessionId: string, messageId: string): () => void {
    let isStopped = false;
    const pollProcessingStatus = async () => {
      try {
        const processingStatus = await fetchSessionProcessingStatus(sessionId);
        if (processingStatus.state !== "running") {
          return;
        }
        if (isStopped) {
          return;
        }
        setPendingPatientMessage((currentMessage) =>
          currentMessage?.id === messageId && currentMessage.isPending
            ? {
                ...currentMessage,
                processingTimeline: {
                  ...buildPendingAgentProcessingTimeline(processingStatus),
                  startedAtMs: currentMessage.processingTimeline?.startedAtMs ?? Date.now(),
                },
              }
            : currentMessage,
        );
        setPendingCoachHintMessage((currentMessage) =>
          currentMessage?.id === messageId && currentMessage.isPending
            ? {
                ...currentMessage,
                processingTimeline: {
                  ...buildPendingHintProcessingTimeline(processingStatus),
                  startedAtMs: currentMessage.processingTimeline?.startedAtMs ?? Date.now(),
                },
              }
            : currentMessage,
        );
      } catch {
        // Keep the current pending message if the transient polling request fails.
      }
    };

    void pollProcessingStatus();
    const intervalId = window.setInterval(pollProcessingStatus, AGENT_PROCESSING_STATUS_POLL_INTERVAL_MS);
    return () => {
      isStopped = true;
      window.clearInterval(intervalId);
    };
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = inputValue.trim();

    if (hasUncertainHistoryMessage) {
      setErrorText("上一轮问诊仍待确认，请先刷新训练记录或开启新会话。");
      setStatusText("待确认问诊未解决前不会继续发送，避免产生重复记录。");
      return;
    }

    if (!authUser || !selectedCaseId || !message || isCreating || isSending || isSpeechInputBusy) {
      return;
    }
    if (message.length > QUESTION_MAX_CHARS) {
      setErrorText(`问诊内容不能超过 ${QUESTION_MAX_CHARS} 个字符。`);
      return;
    }

    if (!isTrainingModelConfigReady) {
      promptTrainingModelConfigRequired();
      return;
    }

    setIsSending(true);
    setErrorText(null);
    let optimisticQuestionId: string | null = null;
    let pendingPatientReplyId: string | null = null;
    let stopProcessingTimelinePolling: (() => void) | null = null;
    let requestContextEpoch: number | null = null;

    try {
      requestContextEpoch = trainingContextEpochRef.current;
      const activeSession = await ensureActiveSession(requestContextEpoch);
      if (requestContextEpoch !== trainingContextEpochRef.current) {
        return;
      }
      if (!activeSession) {
        return;
      }
      if (isCompletedOsceSession(activeSession)) {
        setErrorText("训练已结束，请查看报告。");
        setStatusText("该训练已结束，请打开报告复盘或重新选择病例开始新训练。");
        return;
      }
      optimisticQuestionId = createClientChatMessageId("optimistic-student");
      pendingPatientReplyId = createClientChatMessageId("pending-patient");
      const patientReplyProcessingStartedAtMs = Date.now();
      setInputValue("");
      setSpeechStatusText(null);
      setPendingCoachHintMessage(null);
      setOptimisticHistoryMessage({
        id: optimisticQuestionId,
        speaker: "student",
        label: "学生",
        text: message,
      });
      setPendingPatientMessage({
        id: pendingPatientReplyId,
        speaker: "patient",
        label: "标准化病人",
        text: "",
        isPending: true,
        processingTimeline: {
          ...buildPendingAgentProcessingTimeline(),
          startedAtMs: patientReplyProcessingStartedAtMs,
        },
      });
      setStatusText("正在处理问诊");

      const pendingHistoryMessage = sendHistoryMessage(activeSession.session_id, message);
      stopProcessingTimelinePolling = refreshPendingProcessingTimeline(activeSession.session_id, pendingPatientReplyId);
      const updatedSession = await pendingHistoryMessage;
      stopProcessingTimelinePolling();
      stopProcessingTimelinePolling = null;
      if (requestContextEpoch !== trainingContextEpochRef.current) {
        return;
      }
      const replyText = updatedSession.reply ?? "";
      const replyMessageMetadata = getReplyMessageMetadata(updatedSession, replyText);
      const replyStatusLabel = replyMessageMetadata.speaker === "coach" ? replyMessageMetadata.label : "标准化病人回复";
      if (replyMessageMetadata.speaker === "coach") {
        setPendingPatientMessage((currentMessage) => currentMessage?.id === pendingPatientReplyId ? null : currentMessage);
        setSession(updatedSession);
        setOptimisticHistoryMessage((currentMessage) => currentMessage?.id === optimisticQuestionId ? null : currentMessage);
        setStatusText(`已收到${replyStatusLabel}：${formatIntentList(updatedSession.current_intents)}`);
        return;
      }
      const completedTimeline = buildCompletedAgentProcessingTimeline(updatedSession, replyText);
      const patientReplyProcessingElapsedMs = Math.max(0, Date.now() - patientReplyProcessingStartedAtMs);
      setPendingPatientMessage((currentMessage) =>
        currentMessage?.id === pendingPatientReplyId
          ? {
              ...currentMessage,
              ...replyMessageMetadata,
              finalText: replyText,
              processingTimeline: {
                ...completedTimeline,
                elapsedMs: Math.max(completedTimeline.elapsedMs ?? 0, patientReplyProcessingElapsedMs),
              },
            }
          : currentMessage,
      );
      setSession(updatedSession);
      setOptimisticHistoryMessage((currentMessage) => currentMessage?.id === optimisticQuestionId ? null : currentMessage);
      setStatusText(`正在显示${replyStatusLabel}...`);
      await animatePendingPatientReply(pendingPatientReplyId, updatedSession.reply ?? "");
      if (requestContextEpoch !== trainingContextEpochRef.current) {
        return;
      }
      setStatusText(`已收到${replyStatusLabel}：${formatIntentList(updatedSession.current_intents)}`);
    } catch (error) {
      stopProcessingTimelinePolling?.();
      if (
        requestContextEpoch !== null
        && requestContextEpoch !== trainingContextEpochRef.current
      ) {
        return;
      }
      const errorMessage = error instanceof Error ? error.message : "发送问诊失败。";
      const wasDefinitivelyRejected = (
        error instanceof ApiRequestError
        && error.outcome === "rejected"
      );
      if (pendingPatientReplyId) {
        setPendingPatientMessage((currentMessage) => currentMessage?.id === pendingPatientReplyId ? null : currentMessage);
      }
      if (wasDefinitivelyRejected && optimisticQuestionId) {
        setOptimisticHistoryMessage(
          (currentMessage) => currentMessage?.id === optimisticQuestionId ? null : currentMessage,
        );
      }
      if (wasDefinitivelyRejected) {
        setInputValue((currentValue) => currentValue || message);
        if (error instanceof ApiRequestError && error.status === 401) {
          setAuthUser(null);
          setIsAuthDialogOpen(true);
        }
        setErrorText(errorMessage);
        setStatusText("问诊未保存，请查看错误详情后重试。");
      } else {
        if (optimisticQuestionId) {
          setOptimisticHistoryMessage(
            (currentMessage) => currentMessage?.id === optimisticQuestionId
              ? { ...currentMessage, deliveryState: "uncertain" }
              : currentMessage,
          );
        }
        setErrorText(`${errorMessage} 当前问题已标记为“待确认”，请先刷新训练记录，避免重复发送。`);
        setStatusText("本轮问诊结果暂时无法确认，当前问题已保留为待确认记录。");
      }
    } finally {
      stopProcessingTimelinePolling?.();
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
      if (isCompletedOsceSession(activeSession)) {
        setErrorText("训练已结束，请查看报告。");
        setStatusText("该训练已结束，请打开报告复盘或重新选择病例开始新训练。");
        return;
      }
      const shouldShowPhysicalExamSequenceReminder = activeSession.revealed_facts.length === 0;
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
      openProcedureResult(nextProcedureResult);
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

  function toggleIntermediateExamSelection(examCode: string) {
    setSelectedIntermediateExamCodes((currentCodes) =>
      currentCodes.includes(examCode)
        ? currentCodes.filter((currentCode) => currentCode !== examCode)
        : [...currentCodes, examCode],
    );
  }

  function toggleIntermediateTestSelection(testCode: string) {
    setSelectedIntermediateTestCodes((currentCodes) =>
      currentCodes.includes(testCode)
        ? currentCodes.filter((currentCode) => currentCode !== testCode)
        : [...currentCodes, testCode],
    );
  }

  async function handlePhysicalExamBatchRequest() {
    if (isCreating || isRequestingExam || selectedIntermediateExamCodes.length === 0) {
      return;
    }

    setIsRequestingExam(true);
    setErrorText(null);

    try {
      const activeSession = await ensureActiveSession();
      if (!activeSession) {
        return;
      }
      if (isCompletedOsceSession(activeSession)) {
        setErrorText("训练已结束，请查看报告。");
        setStatusText("该训练已结束，请打开报告复盘或重新选择病例开始新训练。");
        return;
      }

      const shouldShowPhysicalExamSequenceReminder = activeSession.revealed_facts.length === 0;
      const updatedSession = await requestPhysicalExamBatch(activeSession.session_id, selectedIntermediateExamCodes);
      const nextProcedureResults = updatedSession.exam_results.map((examResult) => ({
        id: `exam:${examResult.exam_code}`,
        label: `查体：${examResult.exam_name_cn}`,
        result: examResult.result,
      }));
      const nextResultIds = new Set(nextProcedureResults.map((result) => result.id));
      setSession(updatedSession);
      setProcedureResults((currentResults) => [
        ...currentResults.filter((result) => !nextResultIds.has(result.id)),
        ...nextProcedureResults,
      ]);
      openProcedureResultGroup(nextProcedureResults);
      setSelectedIntermediateExamCodes([]);
      setOpenProcedureActionGroup(null);
      const unavailableCount = updatedSession.exam_results.filter((examResult) => examResult.availability_status === "not_available_for_case").length;
      const sequenceReminder = shouldShowPhysicalExamSequenceReminder
        ? " OSCE 通常建议先完成核心病史采集，再进入查体。"
        : "";
      const unavailableReminder = unavailableCount > 0 ? ` 其中 ${unavailableCount} 项当前病例未配置结果。` : "";
      setStatusText(`已批量返回 ${updatedSession.exam_results.length} 项查体结果。${unavailableReminder}${sequenceReminder}`);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "请求查体失败。");
      setStatusText("查体请求失败，请查看错误详情。");
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
      if (isCompletedOsceSession(activeSession)) {
        setErrorText("训练已结束，请查看报告。");
        setStatusText("该训练已结束，请打开报告复盘或重新选择病例开始新训练。");
        return;
      }
      const shouldShowAuxiliaryTestSequenceReminder = activeSession.requested_exams.length === 0;
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
      openProcedureResult(nextProcedureResult);
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

  async function handleAuxiliaryTestBatchRequest() {
    if (isCreating || isRequestingTest || selectedIntermediateTestCodes.length === 0) {
      return;
    }

    setIsRequestingTest(true);
    setErrorText(null);

    try {
      const activeSession = await ensureActiveSession();
      if (!activeSession) {
        return;
      }
      if (isCompletedOsceSession(activeSession)) {
        setErrorText("训练已结束，请查看报告。");
        setStatusText("该训练已结束，请打开报告复盘或重新选择病例开始新训练。");
        return;
      }

      const shouldShowAuxiliaryTestSequenceReminder = activeSession.requested_exams.length === 0;
      const updatedSession = await requestAuxiliaryTestBatch(activeSession.session_id, selectedIntermediateTestCodes);
      const nextProcedureResults = updatedSession.test_results.map((testResult) => ({
        id: `test:${testResult.test_code}`,
        label: `检查：${testResult.test_name_cn}`,
        result: testResult.result,
      }));
      const nextResultIds = new Set(nextProcedureResults.map((result) => result.id));
      setSession(updatedSession);
      setProcedureResults((currentResults) => [
        ...currentResults.filter((result) => !nextResultIds.has(result.id)),
        ...nextProcedureResults,
      ]);
      openProcedureResultGroup(nextProcedureResults);
      setSelectedIntermediateTestCodes([]);
      setOpenProcedureActionGroup(null);
      const unavailableCount = updatedSession.test_results.filter((testResult) => testResult.availability_status === "not_available_for_case").length;
      const sequenceReminder = shouldShowAuxiliaryTestSequenceReminder
        ? " 现实 OSCE 中通常应先基于病史和查体形成初步判断，再选择辅助检查。"
        : "";
      const unavailableReminder = unavailableCount > 0 ? ` 其中 ${unavailableCount} 项当前病例未配置结果。` : "";
      setStatusText(`已批量返回 ${updatedSession.test_results.length} 项辅助检查结果。${unavailableReminder}${sequenceReminder}`);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "申请辅助检查失败。");
      setStatusText("辅助检查申请失败，请查看错误详情。");
    } finally {
      setIsRequestingTest(false);
    }
  }

  async function handleAdvancedProcedureRequest() {
    const requestText = advancedProcedureRequestText.trim();
    if (isCreating || isRequestingAdvancedProcedure || !requestText) {
      return;
    }
    if (requestText.length > PROCEDURE_REQUEST_MAX_CHARS) {
      setErrorText(`检查申请不能超过 ${PROCEDURE_REQUEST_MAX_CHARS} 个字符。`);
      return;
    }

    setIsRequestingAdvancedProcedure(true);
    setErrorText(null);
    setAdvancedProcedureUnmatchedRequests([]);

    try {
      const activeSession = await ensureActiveSession();
      if (!activeSession) {
        return;
      }
      if (isCompletedOsceSession(activeSession)) {
        setErrorText("训练已结束，请查看报告。");
        setStatusText("该训练已结束，请打开报告复盘或重新选择病例开始新训练。");
        return;
      }

      const updatedSession = await requestProcedureText(activeSession.session_id, requestText);
      const nextProcedureResults = updatedSession.matched_procedure_results.map((procedureResult) => ({
        id: procedureResult.id,
        label: procedureResult.label,
        result: procedureResult.result,
        availabilityStatus: procedureResult.availability_status,
        generatedByAi: procedureResult.generated_by_ai,
        approvalStatus: procedureResult.approval_status,
        sourceContextReferences: procedureResult.source_context_references,
        scoringEligible: procedureResult.scoring_eligible,
      }));
      const nextResultIds = new Set(nextProcedureResults.map((result) => result.id));
      setSession(updatedSession);
      setProcedureResults((currentResults) => [
        ...currentResults.filter((result) => !nextResultIds.has(result.id)),
        ...nextProcedureResults,
      ]);
      openProcedureResultGroup(nextProcedureResults);
      setAdvancedProcedureUnmatchedRequests(updatedSession.standardized_request.unmatched_requests);
      setAdvancedProcedureRequestText("");
      const unavailableCount = updatedSession.matched_procedure_results.filter((procedureResult) => procedureResult.availability_status === "not_available_for_case").length;
      const simulatedCount = updatedSession.matched_procedure_results.filter((procedureResult) => procedureResult.availability_status === "ai_simulated_for_training").length;
      setAdvancedProcedureRequestSummary({
        rawRequest: requestText,
        matchedLabels: nextProcedureResults.map((procedureResult) => procedureResult.label),
        unmatchedRequests: updatedSession.standardized_request.unmatched_requests,
        returnedResultCount: nextProcedureResults.length,
        simulatedResultCount: simulatedCount,
        unavailableResultCount: unavailableCount,
      });
      setIsAdvancedProcedureRequestSummaryOpen(false);
      const simulatedText = simulatedCount > 0 ? ` 其中 ${simulatedCount} 项为教学模拟补充，不计分。` : "";
      const unmatchedText = updatedSession.standardized_request.unmatched_requests.length > 0
        ? ` 未识别项目：${updatedSession.standardized_request.unmatched_requests.join("、")}。`
        : "";
      setStatusText(`已解析申请并返回 ${updatedSession.matched_procedure_results.length} 项结果。${simulatedText}${unmatchedText}`);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "提交申请失败。");
      setStatusText("申请处理失败，请查看错误详情。");
    } finally {
      setIsRequestingAdvancedProcedure(false);
    }
  }

  async function handleHintRequest() {
    if (!authUser || !selectedCaseId || isCreating || isRequestingHint || isHintRequestLocked) {
      return;
    }

    setIsRequestingHint(true);
    setErrorText(null);
    let activePendingCoachHintId: string | null = null;
    let stopProcessingTimelinePolling: (() => void) | null = null;

    try {
      const activeSession = await ensureActiveSession();
      if (!activeSession) {
        return;
      }
      if (isCompletedOsceSession(activeSession)) {
        setErrorText("训练已结束，请查看报告。");
        setStatusText("该训练已结束，请打开报告复盘或重新选择病例开始新训练。");
        return;
      }
      const activeHintContextSignature = buildHintContextSignature(activeSession, selectedCaseId, trainingDifficultyMode);
      if (lastHintContextSignature === activeHintContextSignature) {
        setStatusText("当前状态已经给出提示，请先继续问诊、申请查体检查或记录诊断假设。");
        return;
      }

      const pendingCoachHintId = createClientChatMessageId("pending-coach-hint");
      activePendingCoachHintId = pendingCoachHintId;
      const coachHintProcessingStartedAtMs = Date.now();
      setPendingCoachHintMessage({
        id: pendingCoachHintId,
        speaker: "coach",
        label: "过程提示",
        text: "",
        isPending: true,
        processingTimeline: {
          ...buildPendingHintProcessingTimeline(),
          startedAtMs: coachHintProcessingStartedAtMs,
        },
      });
      setStatusText("正在生成过程提示");

      const pendingHintRequest = requestHint(activeSession.session_id);
      stopProcessingTimelinePolling = refreshPendingProcessingTimeline(activeSession.session_id, pendingCoachHintId);
      const updatedSession = await pendingHintRequest;
      stopProcessingTimelinePolling();
      stopProcessingTimelinePolling = null;
      setSession(updatedSession);
      setPendingCoachHintMessage((currentMessage) => currentMessage?.id === pendingCoachHintId ? null : currentMessage);
      setLastHintContextSignature(buildHintContextSignature(updatedSession, selectedCaseId, trainingDifficultyMode));
      setStatusText(`已生成过程提示：${updatedSession.hint}`);
    } catch (error) {
      stopProcessingTimelinePolling?.();
      if (activePendingCoachHintId) {
        setPendingCoachHintMessage((currentMessage) => currentMessage?.id === activePendingCoachHintId ? null : currentMessage);
      }
      setErrorText(error instanceof Error ? error.message : "请求过程提示失败。");
      setStatusText("过程提示请求失败，请确认后端仍在运行。");
    } finally {
      stopProcessingTimelinePolling?.();
      setIsRequestingHint(false);
    }
  }

  async function handleDiagnosisSubmit() {
    const diagnosis = diagnosisValue.trim();
    const otherPossibleDiagnoses = differentialDiagnosisValue.trim();
    const supportingEvidence = supportingEvidenceValue.trim();
    const differentialReasoning = exclusionEvidenceValue.trim();
    const nextStep = nextStepValue.trim();
    const uncertainty = uncertaintyValue.trim();

    if (
      !authUser ||
      !selectedCaseId ||
      !diagnosis ||
      !supportingEvidence ||
      !differentialReasoning ||
      (isNextStepRequired && !nextStep) ||
      isCreating ||
      isSubmittingDiagnosis
    ) {
      return;
    }

    const reasoning = buildStructuredReasoning(
      diagnosis,
      otherPossibleDiagnoses,
      supportingEvidence,
      differentialReasoning,
      nextStep,
      uncertainty,
    );
    if (diagnosis.length > DIAGNOSIS_MAX_CHARS) {
      setErrorText(`诊断不能超过 ${DIAGNOSIS_MAX_CHARS} 个字符。`);
      return;
    }
    if (reasoning.length > DIAGNOSIS_REASONING_MAX_CHARS) {
      setErrorText(`诊断推理不能超过 ${DIAGNOSIS_REASONING_MAX_CHARS} 个字符。`);
      return;
    }

    setIsSubmittingDiagnosis(true);
    setErrorText(null);

    try {
      const activeSession = await ensureActiveSession();
      if (!activeSession) {
        return;
      }
      if (isCompletedOsceSession(activeSession)) {
        setErrorText("训练已结束，请查看报告。");
        setStatusText("该训练已结束，请打开报告复盘或重新选择病例开始新训练。");
        return;
      }

      const submittedSession = await submitDiagnosis(activeSession.session_id, diagnosis, reasoning);
      setSession(submittedSession);
      setStatusText("诊断已提交，正在生成评分报告...");
      try {
        const report = await generateSessionReport(submittedSession.session_id);
        const updatedSession = await getSession(submittedSession.session_id);
        setSession(updatedSession);
        setFeedbackReport(report);
        setStatusText(`已提交诊断并生成评分报告：${report.total_score} 分，正在打开报告页面。`);
        router.push(`/report?session_id=${encodeURIComponent(report.session_id || submittedSession.session_id)}`);
      } catch (reportError) {
        try {
          const updatedSession = await getSession(submittedSession.session_id);
          setSession(updatedSession);
        } catch {
          setSession(submittedSession);
        }
        const reportMessage = reportError instanceof Error ? reportError.message : "报告暂时不可用。";
        setErrorText(`诊断已提交，但报告暂时未取回：${reportMessage}`);
        setStatusText("诊断已提交；评分报告暂时未取回，可稍后从训练记录打开。");
      }
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "提交诊断或获取报告失败。");
      setStatusText("诊断提交失败，请确认后端仍在运行。");
    } finally {
      setIsSubmittingDiagnosis(false);
    }
  }

  const selectedProcedureResultItems = selectedProcedureResult ? (selectedProcedureResults.length > 0 ? selectedProcedureResults : [selectedProcedureResult]) : [];

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

        <Panel title="训练导航" description="当前病例和训练阶段。">
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
            </div>

            <div className="flex flex-wrap items-center justify-center gap-2">
              <Link
                className="flex w-fit items-center justify-center rounded-md border border-border bg-muted/80 px-4 py-2 text-center text-xs font-medium whitespace-nowrap text-foreground shadow-xs transition hover:bg-accent"
                href="/cases"
              >
                选择病例
              </Link>
              <button
                className="flex w-fit items-center justify-center rounded-md border border-brand bg-brand px-4 py-2 text-center text-xs font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
                disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCreating || isSending}
                onClick={() => void handleStartNewSession()}
                type="button"
              >
                开启新会话
              </button>
            </div>

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
                    disabled={isSubmittingAuth || isSending}
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
              登录
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
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-xs font-medium text-muted-foreground">当前病例</p>
                    {selectedCase ? (
                      <span className="rounded-full border border-brand/20 bg-brand/5 px-2.5 py-0.5 text-xs font-semibold text-brand">
                        {getTrainingDifficultyLabel(trainingDifficultyMode)}训练
                      </span>
                    ) : null}
                  </div>
                  <h2 className="mt-1 text-lg font-semibold leading-6 text-foreground">
                    {session?.case_title ?? selectedCase?.title ?? "请先选择病例"}
                  </h2>
                </div>
                {errorText ? (
                  <div
                    aria-live="assertive"
                    className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-600"
                    role="alert"
                  >
                    {errorText}
                  </div>
                ) : null}
              </div>
            </div>

            <div className="flex-1 space-y-4 overflow-y-scroll p-5 pb-40 student-chat-scrollbar" ref={chatScrollContainerRef}>
              {!selectedCase && !isCasePreparationPromptDismissed ? (
                <CaseSelectionPrompt onDismiss={() => setIsCasePreparationPromptDismissed(true)} />
              ) : null}
              <OpeningTaskCardMessage openingTaskCard={preparedOpeningTaskCard} />
              {chatMessages.map((message) => {
                const isStudent = message.speaker === "student";
                const isCoach = message.speaker === "coach";
                const isPatient = !isStudent && !isCoach;
                const isSafetyBoundary = isCoach && message.label === "安全边界";
                const processingTimeline = message.processingTimeline;
                const isPendingProcessingTimeline = message.processingTimeline?.state === "pending";
                const patientSpeechState = speechPlaybackState?.messageId === message.id ? speechPlaybackState.status : null;
                const messageRowClass = isStudent ? "justify-end" : isCoach ? "justify-center" : "justify-start";
                const messageBubbleClass = isStudent
                  ? "max-w-[76%] rounded-xl border border-brand bg-brand px-4 py-3 text-sm leading-6 text-white shadow-xs"
                  : isCoach
                    ? isSafetyBoundary
                      ? "w-full max-w-lg rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm leading-6 text-foreground shadow-xs"
                      : "w-full max-w-lg rounded-xl border border-[#D8C3AF]/70 bg-[#F8F3EA] px-4 py-3 text-sm leading-6 text-foreground shadow-xs"
                    : "max-w-[76%] rounded-xl border border-border bg-muted px-4 py-3 text-sm leading-6 text-foreground shadow-xs";
                return (
                  <div className={`flex ${messageRowClass}`} key={message.id}>
                    <div className={messageBubbleClass}>
                      <div className="flex items-center justify-between gap-3">
                        <p className={isStudent ? "text-white/80" : isSafetyBoundary ? "flex items-center gap-2 font-medium text-red-700" : isCoach ? "text-[#8A5A00]" : "text-muted-foreground"}>
                          {isSafetyBoundary ? (
                            <span
                              aria-label="安全边界提示"
                              className="inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-red-600 text-xs font-bold leading-none text-white"
                            >
                              !
                            </span>
                          ) : null}
                          {message.label}
                          {message.deliveryState === "uncertain" ? (
                            <span className="ml-2 inline-flex items-center rounded-full border border-white/35 bg-white/10 px-2 py-0.5 text-[11px] font-medium text-white">
                              待确认
                            </span>
                          ) : null}
                          {message.emotion ? (
                            <span className="ml-2 inline-flex items-center rounded-full border border-[#D8C3AF] bg-background px-2 py-0.5 text-[11px] font-medium text-[#8A5A00]">
                              情绪：{message.emotion}
                            </span>
                          ) : null}
                        </p>
                        {canShowPatientSpeechPlayback(message) ? (
                          <button
                            aria-label={patientSpeechState === "loading" ? "正在生成患者回复语音" : patientSpeechState === "playing" ? "停止患者回复语音" : "播放患者回复语音"}
                            className="flex size-8 shrink-0 items-center justify-center rounded-full border border-border bg-background text-muted-foreground shadow-xs transition hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                            disabled={!authUser}
                            onClick={() => void handlePatientSpeechButtonClick(message)}
                            title={patientSpeechState === "loading" ? "正在生成语音" : patientSpeechState === "playing" ? "停止播放" : "播放患者回复"}
                            type="button"
                          >
                            {patientSpeechState === "loading" ? <LoadingSpinnerIcon /> : patientSpeechState === "playing" ? <StopIcon /> : <SpeakerIcon />}
                          </button>
                        ) : null}
                      </div>
                      {message.isPending && !message.finalText && isPendingProcessingTimeline ? (
                        <AgentProcessingTimelineView timeline={processingTimeline ?? buildPendingAgentProcessingTimeline()} />
                      ) : (
                        <p className="mt-1">{message.text}</p>
                      )}
                      {processingTimeline && !(message.isPending && !message.finalText) ? (
                        <AgentProcessingTimelineView timeline={processingTimeline} />
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="pointer-events-none absolute inset-x-0 bottom-0 z-20 isolate px-3 pb-4 pt-10">
              <div aria-hidden="true" className="absolute inset-x-0 bottom-0 z-0 h-20 bg-background" />
              <div aria-hidden="true" className="absolute bottom-20 left-1/2 z-0 h-10 w-full max-w-3xl -translate-x-1/2 bg-background/75 backdrop-blur-md [mask-image:linear-gradient(to_top,black,black_52%,transparent)]" />
              <div className="pointer-events-auto relative z-10 mx-auto mb-2 flex max-w-3xl flex-wrap items-center gap-2" ref={procedureActionContainerRef}>
                <button
                  className="rounded-full border border-[#B5812A]/30 bg-[#FFF8E8] px-3 py-1.5 text-xs font-medium whitespace-nowrap text-[#8A5A00] shadow-xs transition hover:bg-[#FFF1CC] disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isRequestingHint || isHintRequestLocked}
                  onClick={handleHintRequest}
                  type="button"
                >{hintButtonLabel}</button>
                <button
                  className="rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium whitespace-nowrap shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={!preparedPatientProfile}
                  onClick={() => setIsPatientProfileOpen(true)}
                  type="button"
                >
                  患者信息
                </button>
                {isAdvancedTrainingMode ? (
                  <div className="flex w-fit max-w-full flex-none items-center gap-1.5 rounded-full border border-border bg-background p-1 shadow-xs">
                    <input
                      autoComplete="off"
                      className="h-7 w-52 min-w-0 bg-transparent px-2 text-xs outline-none placeholder:text-muted-foreground sm:w-60"
                      disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isRequestingAdvancedProcedure}
                      maxLength={PROCEDURE_REQUEST_MAX_CHARS}
                      onChange={(event) => setAdvancedProcedureRequestText(event.target.value)}
                      placeholder="输入想申请的查体或检查"
                      value={advancedProcedureRequestText}
                    />
                    <button
                      className="h-7 rounded-full border border-brand bg-brand px-3 text-xs font-medium whitespace-nowrap text-white transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isRequestingAdvancedProcedure || !advancedProcedureRequestText.trim()}
                      onClick={() => void handleAdvancedProcedureRequest()}
                      type="button"
                    >{isRequestingAdvancedProcedure ? "解析中" : "提交申请"}</button>
                    <button
                      className="h-7 rounded-full border border-border bg-background px-3 text-xs font-medium whitespace-nowrap text-foreground shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:text-muted-foreground disabled:opacity-50"
                      disabled={advancedProcedureRequestSummaryToShow === null}
                      onClick={openAdvancedProcedureRequestSummary}
                      type="button"
                    >
                      查看申请内容
                    </button>
                  </div>
                ) : null}
                {advancedProcedureUnmatchedRequests.length > 0 ? (
                  <span className="rounded-full border border-[#D7A455]/40 bg-[#FFF8E8] px-3 py-1.5 text-xs text-[#8A5A00]">
                    未识别项目：{advancedProcedureUnmatchedRequests.join("、")}
                  </span>
                ) : null}
                {!isAdvancedTrainingMode ? (
                  <>
                    <button
                      aria-expanded={openProcedureActionGroup === "physical_exam"}
                      className="inline-flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium whitespace-nowrap shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={isPhysicalExamActionDisabled}
                      onClick={() => {
                        setOpenProcedureActionGroup((currentGroup) => currentGroup === "physical_exam" ? null : "physical_exam");
                        if (isIntermediateTrainingMode) {
                          void ensureProcedureCatalog();
                        }
                      }}
                      type="button"
                    >
                      查体项目
                      <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                        {isIntermediateTrainingMode ? (
                          <>{completedIntermediatePhysicalExamOptions.length}/{intermediatePhysicalExamOptions.length}</>
                        ) : (
                          <>{completedPhysicalExamOptions.length}/{physicalExamOptions.length}</>
                        )}
                      </span>
                    </button>
                    <button
                      aria-expanded={openProcedureActionGroup === "auxiliary_test"}
                      className="inline-flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium whitespace-nowrap shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={isAuxiliaryTestActionDisabled}
                      onClick={() => {
                        setOpenProcedureActionGroup((currentGroup) => currentGroup === "auxiliary_test" ? null : "auxiliary_test");
                        if (isIntermediateTrainingMode) {
                          void ensureProcedureCatalog();
                        }
                      }}
                      type="button"
                    >
                      辅助检查
                      <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                        {isIntermediateTrainingMode ? (
                          <>{completedIntermediateAuxiliaryTestOptions.length}/{intermediateAuxiliaryTestOptions.length}</>
                        ) : (
                          <>{completedAuxiliaryTestOptions.length}/{auxiliaryTestOptions.length}</>
                        )}
                      </span>
                    </button>
                    {openProcedureActionGroup === "physical_exam" ? (
                  <div className="absolute bottom-11 left-0 z-30 w-80 rounded-2xl border border-border bg-background p-3 shadow-[0_18px_45px_rgba(20,20,19,0.16)]" data-procedure-action-menu="true">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold">查体项目</p>
                      <span className="rounded-full border border-border bg-muted px-2 py-1 text-[11px] text-muted-foreground">
                        {completedPhysicalExamOptions.length} 已查看
                      </span>
                    </div>
                    <div className="mt-3 grid max-h-72 gap-2 overflow-y-scroll pr-1 student-rail-scrollbar" onScroll={handleStudentRailScroll}>
                      {isIntermediateTrainingMode ? (
                        <>
                          {isLoadingProcedureCatalog && !procedureCatalog ? (
                            <p className="rounded-lg border border-dashed border-border bg-muted/40 p-3 text-xs text-muted-foreground">
                              正在读取可申请查体目录。
                            </p>
                          ) : null}
                          {pendingIntermediatePhysicalExamOptions.length > 0 ? (
                            pendingIntermediatePhysicalExamOptions.map((examOption) => {
                              const isSelected = selectedIntermediateExamCodes.includes(examOption.exam_code);
                              return (
                                <button
                                  className={`rounded-lg border px-3 py-2 text-left text-xs font-medium shadow-xs transition disabled:cursor-not-allowed disabled:opacity-50 ${
                                    isSelected ? "border-brand/60 bg-brand/10" : "border-border bg-muted/40 hover:border-brand/30 hover:bg-accent"
                                  }`}
                                  disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isRequestingExam}
                                  key={examOption.exam_code}
                                  onClick={() => toggleIntermediateExamSelection(examOption.exam_code)}
                                  type="button"
                                >
                                  <span className="flex items-center gap-2">
                                    <span className={`h-3 w-3 rounded-sm border ${isSelected ? "border-brand bg-brand" : "border-border bg-background"}`} />
                                    <span className="whitespace-nowrap">{examOption.category}：{examOption.exam_name_cn}</span>
                                  </span>
                                </button>
                              );
                            })
                          ) : (
                            <p className="rounded-lg border border-dashed border-border bg-muted/40 p-3 text-xs text-muted-foreground">
                              当前查体目录都已申请。
                            </p>
                          )}
                          <button
                            className="rounded-lg border border-brand bg-brand px-3 py-2 text-xs font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
                            disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isRequestingExam || selectedIntermediateExamCodes.length === 0}
                            onClick={() => void handlePhysicalExamBatchRequest()}
                            type="button"
                          >提交所选查体</button>
                          {completedIntermediatePhysicalExamOptions.length > 0 ? (
                            <div className="border-t border-border pt-3">
                              <p className="text-xs font-medium text-muted-foreground">已查看</p>
                              <div className="mt-2 grid gap-2">
                                {completedIntermediatePhysicalExamOptions.map((examOption) => (
                                  <button
                                    className="rounded-lg border border-[#86B993]/40 bg-[#EEF6EF] px-3 py-2 text-left text-xs font-medium whitespace-nowrap text-[#236146] shadow-xs transition hover:bg-[#E2F0E4]"
                                    key={examOption.exam_code}
                                    onClick={() => {
                                      openProcedureResult(getProcedureResultById(`exam:${examOption.exam_code}`));
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
                        </>
                      ) : (
                        <>
                          {pendingPhysicalExamOptions.length > 0 ? (
                            pendingPhysicalExamOptions.map((examOption) => (
                              <button
                                className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-left text-xs font-medium shadow-xs transition hover:border-brand/30 hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                                disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isRequestingExam}
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
                                  openProcedureResult(getProcedureResultById(`exam:${examOption.exam_code}`));
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
                        </>
                      )}
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
                      {isIntermediateTrainingMode ? (
                        <>
                          {isLoadingProcedureCatalog && !procedureCatalog ? (
                            <p className="rounded-lg border border-dashed border-border bg-muted/40 p-3 text-xs text-muted-foreground">
                              正在读取可申请检查目录。
                            </p>
                          ) : null}
                          {pendingIntermediateAuxiliaryTestOptions.length > 0 ? (
                            pendingIntermediateAuxiliaryTestOptions.map((testOption) => {
                              const isSelected = selectedIntermediateTestCodes.includes(testOption.test_code);
                              return (
                                <button
                                  className={`rounded-lg border px-3 py-2 text-left text-xs font-medium shadow-xs transition disabled:cursor-not-allowed disabled:opacity-50 ${
                                    isSelected ? "border-brand/60 bg-brand/10" : "border-border bg-muted/40 hover:border-brand/30 hover:bg-accent"
                                  }`}
                                  disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isRequestingTest}
                                  key={testOption.test_code}
                                  onClick={() => toggleIntermediateTestSelection(testOption.test_code)}
                                  type="button"
                                >
                                  <span className="flex items-center gap-2">
                                    <span className={`h-3 w-3 rounded-sm border ${isSelected ? "border-brand bg-brand" : "border-border bg-background"}`} />
                                    <span className="whitespace-nowrap">{testOption.category}：{testOption.test_name_cn}</span>
                                  </span>
                                  <span className="mt-1 block whitespace-nowrap pl-5 text-[11px] font-normal text-muted-foreground">
                                    {testOption.cost_hint} · {testOption.invasiveness}
                                  </span>
                                </button>
                              );
                            })
                          ) : (
                            <p className="rounded-lg border border-dashed border-border bg-muted/40 p-3 text-xs text-muted-foreground">
                              当前辅助检查目录都已申请。
                            </p>
                          )}
                          <button
                            className="rounded-lg border border-brand bg-brand px-3 py-2 text-xs font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
                            disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isRequestingTest || selectedIntermediateTestCodes.length === 0}
                            onClick={() => void handleAuxiliaryTestBatchRequest()}
                            type="button"
                          >提交所选检查</button>
                          {completedIntermediateAuxiliaryTestOptions.length > 0 ? (
                            <div className="border-t border-border pt-3">
                              <p className="text-xs font-medium text-muted-foreground">已查看</p>
                              <div className="mt-2 grid gap-2">
                                {completedIntermediateAuxiliaryTestOptions.map((testOption) => (
                                  <button
                                    className="rounded-lg border border-[#86B993]/40 bg-[#EEF6EF] px-3 py-2 text-left text-xs font-medium whitespace-nowrap text-[#236146] shadow-xs transition hover:bg-[#E2F0E4]"
                                    key={testOption.test_code}
                                    onClick={() => {
                                      openProcedureResult(getProcedureResultById(`test:${testOption.test_code}`));
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
                        </>
                      ) : (
                        <>
                          {pendingAuxiliaryTestOptions.length > 0 ? (
                            pendingAuxiliaryTestOptions.map((testOption) => (
                              <button
                                className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-left text-xs font-medium shadow-xs transition hover:border-brand/30 hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                                disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isRequestingTest}
                                key={testOption.test_code}
                                onClick={() => {
                                  setOpenProcedureActionGroup(null);
                                  void handleAuxiliaryTestRequest(testOption.test_code);
                                }}
                                type="button"
                              >
                                <span className="block whitespace-nowrap">{isRequestingTest ? "检查中" : `${testOption.category}：${testOption.test_name_cn}`}</span>
                                <span className="mt-1 block whitespace-nowrap text-[11px] font-normal text-muted-foreground">
                                  {testOption.cost_hint} · {testOption.invasiveness}
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
                                  openProcedureResult(getProcedureResultById(`test:${testOption.test_code}`));
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
                        </>
                      )}
                    </div>
                  </div>
                    ) : null}
                  </>
                ) : null}
              </div>
              <form className="pointer-events-auto relative z-10 mx-auto max-w-3xl rounded-2xl border border-border bg-background px-3 py-2 shadow-[0_10px_30px_rgba(20,20,19,0.12)]" onSubmit={handleSubmit}>
                <label className="sr-only" htmlFor="history-question">
                  输入下一句问诊问题
                </label>
                <div className="flex items-center gap-2">
                  <input
                    className="h-10 min-w-0 flex-1 rounded-full border-0 bg-transparent px-3 text-sm outline-none transition placeholder:text-muted-foreground focus:ring-0"
                    disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isSending || hasUncertainHistoryMessage || isSpeechInputBusy}
                    id="history-question"
                    ref={questionInputRef}
                    autoComplete="off"
                    autoCorrect="off"
                    maxLength={QUESTION_MAX_CHARS}
                    onChange={(event) => setInputValue(event.target.value)}
                    placeholder="输入问诊问题，开始诊断训练"
                    spellCheck={false}
                    value={inputValue}
                  />
                  <button
                    aria-label={speechInputButtonAriaLabel}
                    className={`flex size-10 shrink-0 items-center justify-center rounded-full border text-sm font-medium shadow-xs transition disabled:cursor-not-allowed disabled:opacity-50 ${
                      isSpeechInputRecording
                        ? "border-red-200 bg-red-50 text-red-700 hover:bg-red-100"
                        : "border-border bg-background text-foreground hover:bg-accent"
                    }`}
                    disabled={isSpeechInputButtonDisabled}
                    onClick={() => void handleSpeechInputButtonClick()}
                    title={speechInputButtonTitle}
                    type="button"
                  >
                    {isSpeechInputTranscribing ? <LoadingSpinnerIcon /> : isSpeechInputRecording ? <StopIcon /> : <MicrophoneIcon />}
                  </button>
                  <button
                    className="rounded-full border border-brand bg-brand px-4 py-2 text-sm font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || !inputValue.trim() || isSending || hasUncertainHistoryMessage || isSpeechInputBusy}
                    type="submit"
                  >
                    {isSending ? "发送中" : hasUncertainHistoryMessage ? "等待确认" : "发送问诊"}
                  </button>
                </div>
                {speechStatusText ? (
                  <p className="px-3 pb-1 text-xs leading-5 text-muted-foreground">{speechStatusText}</p>
                ) : null}
              </form>
            </div>
          </div>

          <aside className="flex min-h-0 flex-col gap-4 overflow-y-scroll student-rail-scrollbar" onScroll={handleStudentRailScroll}>
            <section className="rounded-2xl border border-brand/20 bg-card p-3 shadow-xs">
              <button
                className="flex w-full items-center justify-between gap-3 rounded-xl border border-brand bg-brand px-4 py-3 text-left text-sm font-semibold text-white shadow-[0_12px_30px_rgba(181,87,49,0.22)] transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-60"
                disabled={isCurrentSessionCompleted}
                onClick={() => setIsDiagnosisComposerOpen((isOpen) => !isOpen)}
                type="button"
              >
                <span>{isCurrentSessionCompleted ? "诊断已提交" : isDiagnosisComposerOpen ? "收起诊断表单" : "提交诊断与推理"}</span>
                <span className="rounded-full border border-white/35 px-2 py-0.5 text-[11px] font-medium">
                  {getTrainingDifficultyLabel(trainingDifficultyMode)}
                </span>
              </button>

              {isDiagnosisComposerOpen ? (
                <div className="mt-3 grid gap-3">
                  <div className="rounded-xl border border-border bg-muted/30 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <label className="text-sm font-semibold" htmlFor="diagnosis-input">
                        当前最可能诊断
                      </label>
                      <span className="rounded-full bg-brand/10 px-2 py-0.5 text-[11px] font-medium text-brand">必填</span>
                    </div>
                    <input
                      className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                      disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isSubmittingDiagnosis}
                      id="diagnosis-input"
                      maxLength={DIAGNOSIS_MAX_CHARS}
                      onChange={(event) => setDiagnosisValue(event.target.value)}
                      placeholder="写出你现在最支持的诊断假设"
                      value={diagnosisValue}
                    />
                    {session?.student_hypotheses.length ? (
                      <div className="mt-2">
                        <p className="text-[11px] font-medium text-muted-foreground">训练中已记录的假设</p>
                        <div className="mt-1 flex flex-wrap gap-1.5">
                          {session.student_hypotheses.map((hypothesis, index) => (
                            <span className="rounded-full border border-border bg-background px-2 py-0.5 text-[11px]" key={`${hypothesis}-${index}`}>
                              {hypothesis}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>

                  <div className="rounded-xl border border-border bg-muted/30 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <label className="text-sm font-semibold" htmlFor="differential-diagnosis-input">
                        其他可能诊断
                      </label>
                      <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">选填</span>
                    </div>
                    <input
                      className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                      disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isSubmittingDiagnosis}
                      id="differential-diagnosis-input"
                      maxLength={DIFFERENTIAL_DIAGNOSIS_MAX_CHARS}
                      onChange={(event) => setDifferentialDiagnosisValue(event.target.value)}
                      placeholder="可写 1-3 个，多个用逗号分隔"
                      value={differentialDiagnosisValue}
                    />
                  </div>

                  <label className="grid gap-1.5 rounded-xl border border-border bg-muted/30 p-3 text-sm font-semibold" htmlFor="supporting-evidence-input">
                    <span className="flex items-center justify-between gap-3">
                      支持依据
                      <span className="rounded-full bg-brand/10 px-2 py-0.5 text-[11px] font-medium text-brand">必填</span>
                    </span>
                    <textarea
                      className="min-w-0 resize-y max-h-40 overflow-y-auto rounded-lg border border-border bg-background px-3 py-2 text-sm font-normal outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                      disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isSubmittingDiagnosis}
                      id="supporting-evidence-input"
                      maxLength={DIAGNOSIS_DETAIL_MAX_CHARS}
                      onChange={(event) => setSupportingEvidenceValue(event.target.value)}
                      onInput={(event) => resizeTextareaToContent(event.currentTarget)}
                      placeholder="哪些病史、查体或检查支持当前诊断？"
                      rows={2}
                      value={supportingEvidenceValue}
                    />
                  </label>

                  <label className="grid gap-1.5 rounded-xl border border-border bg-muted/30 p-3 text-sm font-semibold" htmlFor="exclusion-evidence-input">
                    <span className="flex items-center justify-between gap-3">
                      鉴别与排除
                      <span className="rounded-full bg-brand/10 px-2 py-0.5 text-[11px] font-medium text-brand">必填</span>
                    </span>
                    <textarea
                      className="min-w-0 resize-y max-h-40 overflow-y-auto rounded-lg border border-border bg-background px-3 py-2 text-sm font-normal outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                      disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isSubmittingDiagnosis}
                      id="exclusion-evidence-input"
                      maxLength={DIAGNOSIS_DETAIL_MAX_CHARS}
                      onChange={(event) => setExclusionEvidenceValue(event.target.value)}
                      onInput={(event) => resizeTextareaToContent(event.currentTarget)}
                      placeholder="还需要鉴别什么？目前如何支持或排除？证据不足也可以写清。"
                      rows={2}
                      value={exclusionEvidenceValue}
                    />
                  </label>

                  <label className="grid gap-1.5 rounded-xl border border-border bg-muted/30 p-3 text-sm font-semibold" htmlFor="next-step-input">
                    <span className="flex items-center justify-between gap-3">
                      下一步验证计划
                      <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${isNextStepRequired ? "bg-brand/10 text-brand" : "bg-muted text-muted-foreground"}`}>
                        {isNextStepRequired ? "必填" : "选填"}
                      </span>
                    </span>
                    <textarea
                      className="min-w-0 resize-y max-h-40 overflow-y-auto rounded-lg border border-border bg-background px-3 py-2 text-sm font-normal outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                      disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isSubmittingDiagnosis}
                      id="next-step-input"
                      maxLength={DIAGNOSIS_DETAIL_MAX_CHARS}
                      onChange={(event) => setNextStepValue(event.target.value)}
                      onInput={(event) => resizeTextareaToContent(event.currentTarget)}
                      placeholder="如果还能继续训练，下一步最该补哪项问诊、查体或检查？"
                      rows={2}
                      value={nextStepValue}
                    />
                  </label>

                  <label className="grid gap-1.5 rounded-xl border border-border bg-muted/30 p-3 text-sm font-semibold" htmlFor="uncertainty-input">
                    <span className="flex items-center justify-between gap-3">
                      证据不足或不确定点
                      <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">选填</span>
                    </span>
                    <textarea
                      className="min-w-0 resize-y max-h-40 overflow-y-auto rounded-lg border border-border bg-background px-3 py-2 text-sm font-normal outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                      disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isSubmittingDiagnosis}
                      id="uncertainty-input"
                      maxLength={DIAGNOSIS_DETAIL_MAX_CHARS}
                      onChange={(event) => setUncertaintyValue(event.target.value)}
                      onInput={(event) => resizeTextareaToContent(event.currentTarget)}
                      placeholder="哪些判断还不稳？缺少什么证据？"
                      rows={2}
                      value={uncertaintyValue}
                    />
                  </label>

                  <button
                    className="rounded-xl border border-brand bg-brand px-4 py-3 text-sm font-semibold whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={
                      !authUser ||
                      !isTrainingModelConfigReady ||
                      isCurrentSessionCompleted ||
                      isCreating ||
                      !diagnosisValue.trim() ||
                      !supportingEvidenceValue.trim() ||
                      !exclusionEvidenceValue.trim() ||
                      (isNextStepRequired && !nextStepValue.trim()) ||
                      isSubmittingDiagnosis
                    }
                    onClick={handleDiagnosisSubmit}
                    type="button"
                  >
                    {isSubmittingDiagnosis ? "生成报告中" : "提交诊断"}
                  </button>
                </div>
              ) : null}
            </section>

            <CollapsiblePanel
              title="已收集线索"
              description="来自问诊节点的结构化事实。"
              isOpen={rightPanelOpenStates.evidence}
              maxContentHeightClass="max-h-64"
              onToggle={() => toggleRightPanel("evidence")}
            >
              {evidenceItems.length > 0 ? (
                <div className="space-y-2">
                  {evidenceItems.map((item) => {
                    const isLatestRevealedFact = item.id === latestRevealedFactId;
                    return (
                      <div
                        className={`rounded-lg border p-3 transition ${isLatestRevealedFact ? "clinical-osce-evidence-glow overflow-hidden border-[#D6A54F] bg-[#FFF8E8]" : "border-border bg-muted/60"}`}
                        data-latest-revealed-fact={isLatestRevealedFact ? "true" : undefined}
                        key={item.id}
                        ref={isLatestRevealedFact ? latestEvidenceItemRef : undefined}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-medium">{item.label}</p>
                          {isLatestRevealedFact ? (
                            <span className="shrink-0 rounded-full border border-[#D6A54F]/40 bg-background/80 px-2 py-0.5 text-[11px] font-medium text-[#8A5A00]">
                              刚命中
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">{item.detail}</p>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="rounded-lg border border-dashed border-border bg-muted/40 p-3 text-xs leading-5 text-muted-foreground">
                  发送能命中病例意图的问诊问题后，这里会展示后端披露的结构化线索。
                </p>
              )}
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
                      disabled={!authUser || !selectedCaseId || !isTrainingModelConfigReady || isCurrentSessionCompleted || isCreating || isRequestingHint}
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
          aria-label={`打开 OSCE 快捷入口，${backendConnectionStatusLabel}`}
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
          <span className="pointer-events-none absolute right-1.5 top-1.5 flex size-3 items-center justify-center" title={backendConnectionStatusLabel}>
            <span className={`absolute size-3 rounded-full opacity-45 motion-safe:animate-ping ${backendStatusHaloClass}`} />
            <span className={`relative size-2 rounded-full motion-safe:animate-pulse ${backendStatusLightClass}`} />
          </span>
        </button>
      </div>
      {selectedProcedureResult ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={closeProcedureResultModal}>
          <div className="max-h-[82vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-border bg-background p-5 shadow-xl student-chat-scrollbar" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-medium text-brand">已查看结果</p>
                <h2 className="mt-1 text-base font-semibold">
                  {selectedProcedureResultItems.length > 1 ? `已返回 ${selectedProcedureResultItems.length} 项结果` : selectedProcedureResult.label}
                </h2>
                {selectedProcedureResultItems.some((procedureResult) => procedureResult.generatedByAi) ? (
                  <p className="mt-2 inline-flex rounded-full border border-brand/25 bg-brand/5 px-2.5 py-1 text-xs font-medium text-brand">
                    旧版模拟记录 · 不计分
                  </p>
                ) : null}
              </div>
              <button
                aria-label="关闭查体检查结果"
                className="inline-flex shrink-0 items-center justify-center rounded-md border border-border bg-background px-2 py-1 text-xs font-medium whitespace-nowrap shadow-xs transition hover:bg-accent"
                onClick={closeProcedureResultModal}
                type="button"
              >
                关闭
              </button>
            </div>
            <div className="mt-4 space-y-3">
              {selectedProcedureResultItems.map((procedureResult) => (
                <article className="rounded-xl border border-border bg-muted/50 p-4" key={procedureResult.id}>
                  {selectedProcedureResultItems.length > 1 ? (
                    <h3 className="mb-2 text-sm font-semibold text-foreground">{procedureResult.label}</h3>
                  ) : null}
                  <p className="text-sm leading-7 text-foreground">{formatProcedureResultText(procedureResult)}</p>
                </article>
              ))}
            </div>
          </div>
        </div>
      ) : null}
      {isAdvancedProcedureRequestSummaryOpen && advancedProcedureRequestSummaryToShow ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={closeAdvancedProcedureRequestSummary}>
          <div className="w-full max-w-lg rounded-2xl border border-border bg-background p-5 shadow-xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-medium text-brand">申请内容</p>
                <h2 className="mt-1 text-base font-semibold">全部已申请项目</h2>
              </div>
              <button
                aria-label="关闭申请内容"
                className="inline-flex shrink-0 items-center justify-center rounded-md border border-border bg-background px-2 py-1 text-xs font-medium whitespace-nowrap shadow-xs transition hover:bg-accent"
                onClick={closeAdvancedProcedureRequestSummary}
                type="button"
              >
                关闭
              </button>
            </div>
            <div className="mt-4 space-y-3 text-sm leading-6">
              {advancedProcedureRequestSummaryToShow.rawRequest !== "全部已申请项目" ? (
                <div className="rounded-xl border border-border bg-muted/40 p-3">
                  <p className="text-xs font-medium text-muted-foreground">最近一次原始输入</p>
                  <p className="mt-1 text-foreground">{advancedProcedureRequestSummaryToShow.rawRequest}</p>
                </div>
              ) : null}
              <div className="rounded-xl border border-border bg-muted/40 p-3">
                <p className="text-xs font-medium text-muted-foreground">全部已申请项目</p>
                <div className="mt-2 grid gap-2">
                  {advancedProcedureRequestItemsToShow.length > 0 ? (
                    advancedProcedureRequestItemsToShow.map((procedureItem) => (
                      <div className="rounded-lg border border-border bg-background px-3 py-2" key={procedureItem.id}>
                        <p className="font-medium text-foreground">{procedureItem.label}</p>
                        {procedureItem.generatedByAi ? (
                          <p className="mt-1 text-xs text-muted-foreground">教学模拟补充，不计入评分。</p>
                        ) : procedureItem.availabilityStatus === "not_available_for_case" ? (
                          <p className="mt-1 text-xs text-muted-foreground">病例未配置结果，已记录申请。</p>
                        ) : (
                          <p className="mt-1 text-xs text-muted-foreground">已记录申请。</p>
                        )}
                      </div>
                    ))
                  ) : (
                    <p className="text-muted-foreground">暂无已申请项目。</p>
                  )}
                </div>
              </div>
              {advancedProcedureRequestSummaryToShow.unmatchedRequests.length > 0 ? (
                <div className="rounded-xl border border-[#D7A455]/40 bg-[#FFF8E8] p-3 text-[#8A5A00]">
                  <p className="text-xs font-medium">未识别项目</p>
                  <p className="mt-1">{advancedProcedureRequestSummaryToShow.unmatchedRequests.join("、")}</p>
                </div>
              ) : null}
              <p className="text-xs leading-5 text-muted-foreground">
                已返回 {advancedProcedureRequestSummaryToShow.returnedResultCount} 项结果
                {advancedProcedureRequestSummaryToShow.simulatedResultCount > 0 ? `，其中 ${advancedProcedureRequestSummaryToShow.simulatedResultCount} 项为教学模拟补充，不计入评分` : ""}。
              </p>
            </div>
          </div>
        </div>
      ) : null}
      {isPatientProfileOpen && preparedPatientProfile ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={() => setIsPatientProfileOpen(false)}>
          <div className="w-full max-w-sm rounded-2xl border border-border bg-background p-5 shadow-xl" onClick={(event) => event.stopPropagation()}>
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
          </div>
        </div>
      ) : null}
      {isApiConfigHelpOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/70 p-4 backdrop-blur-md" onClick={() => setIsApiConfigHelpOpen(false)}>
          <div className="w-full max-w-lg rounded-2xl border border-border bg-white p-5 shadow-xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-medium text-brand">系统与配置</p>
                <h2 className="mt-1 text-base font-semibold">API 配置</h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{TEST_STAGE_API_CONFIG_MESSAGE}</p>
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
              <div className="rounded-2xl border border-brand/20 bg-[#FFF8E8] p-4">
                <p className="text-sm font-semibold text-foreground">测试阶段，统一使用我们提供的模型</p>
                <span className="sr-only">
                  主对话模型：Gemini 3.5 Flash；备用对话模型：MiMo V2.5 Pro；向量检索：Gemini Embedding；备用向量检索：本地 BAAI/bge-small-zh-v1.5
                </span>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  当前训练、标准化病人、教师智能体提示、评分辅助和 Skill 文案生成都会走后端托管模型配置，学生端不接收自定义 API Key。
                </p>
              </div>
              <dl className="grid gap-2 text-sm">
                <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-background px-3 py-2">
                  <dt className="text-muted-foreground">主对话模型</dt>
                  <dd className="font-medium text-foreground">Gemini 3.5 Flash</dd>
                </div>
                <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-background px-3 py-2">
                  <dt className="text-muted-foreground">备用对话模型</dt>
                  <dd className="font-medium text-foreground">MiMo V2.5 Pro</dd>
                </div>
                <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-background px-3 py-2">
                  <dt className="text-muted-foreground">向量检索</dt>
                  <dd className="font-medium text-foreground">Gemini Embedding</dd>
                </div>
                <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-background px-3 py-2">
                  <dt className="text-muted-foreground">备用向量检索</dt>
                  <dd className="font-medium text-foreground">本地 BAAI/bge-small-zh-v1.5</dd>
                </div>
              </dl>
              <p className="rounded-xl border border-[#E8C28C] bg-[#FFF8E8] px-3 py-2 text-xs leading-5 text-[#8A5A00]">
                请不要高并发连续请求；当前 API 上游有速率限制，短时间大量刷新、连续发送或多人同时压测可能导致模型服务临时失败。
              </p>
              {runtimeApiConfig?.active ? (
                <p className="rounded-xl border border-border bg-muted px-3 py-2 text-xs leading-5 text-muted-foreground">
                  当前后端：{formatRuntimeApiConfigSummary(runtimeApiConfig)}
                </p>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
      </div>
      </div>
      {!isCheckingAuth && isAuthDialogOpen ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-background/75 p-4 backdrop-blur">
          <section className="relative w-full max-w-md rounded-2xl border border-border bg-background p-6 shadow-xl">
            <button
              aria-label="关闭登录弹窗"
              className="absolute right-4 top-4 rounded-full border border-border bg-background px-3 py-1 text-sm font-medium whitespace-nowrap text-muted-foreground transition hover:border-brand hover:text-brand"
              onClick={() => setIsAuthDialogOpen(false)}
              type="button"
            >
              关闭
            </button>
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">临境 OSCE 智能体（TraceOSCE）</p>
              <h2 className="mt-2 text-xl font-semibold">登录</h2>
            </div>
            <form autoComplete="off" className="mt-6 space-y-4" onSubmit={handleAuthSubmit}>
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="auth-email-input">
                  邮箱
                </label>
                <input
                  autoComplete="off"
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                  id="auth-email-input"
                  maxLength={AUTH_EMAIL_MAX_CHARS}
                  onChange={(event) => setAuthEmail(event.target.value)}
                  placeholder="输入登录邮箱"
                  type="email"
                  value={authEmail}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="auth-password-input">
                  密码
                </label>
                <input
                  autoComplete="new-password"
                  className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                  id="auth-password-input"
                  maxLength={AUTH_PASSWORD_MAX_CHARS}
                  onChange={(event) => setAuthPassword(event.target.value)}
                  placeholder="请输入密码"
                  type="password"
                  value={authPassword}
                />
              </div>
              {authErrorText ? <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700">{authErrorText}</p> : null}
              <button
                className="w-full rounded-lg border border-brand bg-brand px-4 py-2 text-sm font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
                disabled={isCheckingAuth || isSubmittingAuth || !authEmail.trim() || !authPassword}
                type="submit"
              >{isSubmittingAuth ? "处理中" : "登录"}</button>
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
