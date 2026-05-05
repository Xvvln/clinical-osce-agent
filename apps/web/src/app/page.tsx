"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
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

type RightPanelKey = "evidence" | "procedures" | "hypotheses" | "report";

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
  result: string;
  is_abnormal: boolean;
}>;

type PhysicalExamQuickOption = Readonly<Pick<PhysicalExamOption, "exam_code" | "exam_name_cn">>;

type AuxiliaryTestQuickOption = Readonly<Pick<AuxiliaryTestOption, "test_code" | "test_name_cn" | "category">>;

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

type OsceSession = Readonly<{
  session_id: string;
  student_id: string;
  case_id: string;
  stage: string;
  case_title: string;
  chief_complaint: string;
  patient_profile: StudentVisiblePatientProfile;
  opening_task_card: OpeningTaskCard;
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
  reply?: string;
  current_intent?: string;
}>;

type ChatMessage = {
  readonly id: string;
  readonly speaker: "student" | "patient" | "coach";
  readonly label: string;
  readonly text: string;
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
  { test_code: "lab.cbc", test_name_cn: "血常规", category: "实验室" },
  { test_code: "lab.crp", test_name_cn: "C 反应蛋白", category: "实验室" },
  { test_code: "img.abd_us", test_name_cn: "腹部超声", category: "影像" },
  { test_code: "lab.urinalysis", test_name_cn: "尿常规", category: "实验室" },
  { test_code: "img.abd_ct", test_name_cn: "腹部 CT", category: "影像" },
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

const defaultCaseOption: CaseOption = {
  id: DEFAULT_CASE_ID,
  title: "右下腹痛教学病例",
  module: "腹痛",
  difficulty: "初级",
  chiefComplaint: "转移性右下腹痛 24 小时，伴恶心、低热",
  enabled: true,
  patientProfile: appendicitisPatientProfile,
  openingTaskCard: appendicitisOpeningTaskCard,
  physicalExamOptions: appendicitisPhysicalExamOptions,
  auxiliaryTestOptions: appendicitisAuxiliaryTestOptions,
};
const STUDENT_ID = "web_demo";
const DEFAULT_AUTH_EMAIL = "1@1.test";
const DEFAULT_AUTH_PASSWORD = "1";
const DIAGNOSIS_TEXTAREA_MAX_HEIGHT = 160;

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

function formatProgressCount(covered: number, total: number): string {
  return `${covered}/${total}`;
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

function getCoachMessageLabel(content: string): "安全边界" | "过程提示" {
  return content.includes("本系统仅用于 OSCE 教学模拟训练") ? "安全边界" : "过程提示";
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
      title: "病例来源",
      description: "指向当前训练使用的结构化病例。",
    },
    source: {
      key: "source",
      title: "公开数据来源",
      description: "指向病例加工时登记的公开数据或参考工程。",
    },
    rubric: {
      key: "rubric",
      title: "评分依据",
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
  const groupOrder = ["case", "source", "rubric", "evidence", "other"];
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
      {isOpen ? <div className={`${maxContentHeightClass} overflow-y-auto pr-1`}>{children}</div> : null}
    </Panel>
  );
}

function CoverageMapSection({
  title,
  items,
}: Readonly<{
  title: string;
  items: readonly CoverageMapItem[];
}>) {
  return (
    <section className="rounded-xl border border-border bg-background p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-xs font-semibold text-foreground">{title}</p>
        <p className="text-[11px] text-muted-foreground">{items.filter((item) => item.status === "covered").length}/{items.length}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {items.map((item) => (
          <span
            className={
              item.status === "covered"
                ? "rounded-lg border border-brand/30 bg-brand/10 px-2.5 py-1.5 text-[11px] font-medium text-brand"
                : "rounded-lg border border-dashed border-border bg-muted/50 px-2.5 py-1.5 text-[11px] text-muted-foreground"
            }
            key={`${title}-${item.status}-${item.label}`}
          >
            <span className="mr-1 font-semibold">{item.status === "covered" ? "已覆盖" : "待覆盖"}</span>
            <span>{item.label}</span>
            <span className="mt-1 block font-mono text-[10px] opacity-70">{item.id}</span>
          </span>
        ))}
      </div>
    </section>
  );
}

function CoverageMap({ trainingProgress }: Readonly<{ trainingProgress: TrainingProgress }>) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <CoverageMapSection title="问诊事实" items={trainingProgress.coverage_map.history} />
      <CoverageMapSection title="查体项目" items={trainingProgress.coverage_map.physical_exam} />
      <CoverageMapSection title="辅助检查" items={trainingProgress.coverage_map.auxiliary_test} />
      <CoverageMapSection title="推理证据" items={trainingProgress.coverage_map.reasoning} />
    </div>
  );
}

function resizeTextareaToContent(textarea: HTMLTextAreaElement): void {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, DIAGNOSIS_TEXTAREA_MAX_HEIGHT)}px`;
  textarea.style.overflowY = textarea.scrollHeight > DIAGNOSIS_TEXTAREA_MAX_HEIGHT ? "auto" : "hidden";
}

function CaseSelectionPrompt({ selectedCase }: Readonly<{ selectedCase: CaseOption | null }>) {
  return (
    <div className="flex justify-center">
      <div className="w-full max-w-xl rounded-xl border border-brand/20 bg-brand/5 p-4 text-center shadow-xs">
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
          className="mt-3 inline-flex rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium text-white shadow-xs transition hover:bg-brand-hover"
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
    <div className="rounded-xl border border-brand/20 bg-brand/5 p-4 shadow-xs">
      <p className="text-xs font-medium text-brand">开局任务卡</p>
      <p className="mt-2 text-sm font-semibold text-foreground">{openingTaskCard.role}</p>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">{openingTaskCard.scenario}</p>
      <ul className="mt-3 grid gap-2 text-xs leading-5 sm:grid-cols-2">
        {openingTaskCard.tasks.map((task) => (
          <li className="rounded-md border border-brand/15 bg-background px-3 py-2" key={task}>
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
  const [isCoverageMapOpen, setIsCoverageMapOpen] = useState(false);
  const [isOsceDockOpen, setIsOsceDockOpen] = useState(false);
  const [rightPanelOpenStates, setRightPanelOpenStates] = useState<Record<RightPanelKey, boolean>>({
    evidence: true,
    procedures: true,
    hypotheses: true,
    report: true,
  });
  const [session, setSession] = useState<OsceSession | null>(null);
  const [inputValue, setInputValue] = useState("");
  const [statusText, setStatusText] = useState("选择病例后，发送问诊或点击训练操作才会创建新会话。");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isSending, setIsSending] = useState(false);
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
  const [isSubmittingDiagnosis, setIsSubmittingDiagnosis] = useState(false);
  const [feedbackReport, setFeedbackReport] = useState<FeedbackReport | null>(null);
  const [procedureResults, setProcedureResults] = useState<readonly ProcedureResult[]>([]);
  const [isPatientProfileOpen, setIsPatientProfileOpen] = useState(false);
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [isAuthDialogOpen, setIsAuthDialogOpen] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authEmail, setAuthEmail] = useState(DEFAULT_AUTH_EMAIL);
  const [authPassword, setAuthPassword] = useState(DEFAULT_AUTH_PASSWORD);
  const [authDisplayName, setAuthDisplayName] = useState("");
  const [authErrorText, setAuthErrorText] = useState<string | null>(null);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [isSubmittingAuth, setIsSubmittingAuth] = useState(false);

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
      setIsPatientProfileOpen(false);
      setStatusText(selectedCaseId ? "已选择病例，发送问诊或点击训练操作后开始新会话。" : "请选择病例后再开始训练。");
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
  }, [authUser, isCheckingAuth, requestedSessionId, selectedCaseId]);

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

  const selectedCase = useMemo(
    () => selectedCaseId ? caseOptionsState.find((caseOption) => caseOption.id === selectedCaseId) ?? null : null,
    [caseOptionsState, selectedCaseId],
  );
  const physicalExamOptions = session?.physical_exam_options ?? selectedCase?.physicalExamOptions ?? [];
  const auxiliaryTestOptions = session?.auxiliary_test_options ?? selectedCase?.auxiliaryTestOptions ?? [];
  const preparedOpeningTaskCard = session?.opening_task_card ?? selectedCase?.openingTaskCard ?? null;
  const preparedPatientProfile = session?.patient_profile ?? selectedCase?.patientProfile ?? null;

  const chatMessages = useMemo<readonly ChatMessage[]>(() => {
    if (!session) {
      return [];
    }

    return [
      {
        id: "chief-complaint",
        speaker: "patient",
        label: "标准化病人",
        text: `医生您好，我这次主要是${session.chief_complaint}。`,
      },
      ...session.messages.map(mapApiMessage),
    ];
  }, [session]);

  const evidenceItems = useMemo(
    () => session?.revealed_facts.map(getEvidenceItem) ?? [],
    [session?.revealed_facts],
  );

  const requestedItems = useMemo(
    () => [
      ...(session?.requested_exams.map((exam) => ({ id: `exam:${exam}`, label: `查体：${exam}` })) ?? []),
      ...(session?.requested_tests.map((test) => ({ id: `test:${test}`, label: `检查：${test}` })) ?? []),
    ],
    [session?.requested_exams, session?.requested_tests],
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

  async function ensureActiveSession(): Promise<OsceSession | null> {
    if (session) {
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

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = inputValue.trim();

    if (!authUser || !selectedCaseId || !message || isCreating || isSending) {
      return;
    }

    setIsSending(true);
    setErrorText(null);

    try {
      const activeSession = await ensureActiveSession();
      if (!activeSession) {
        return;
      }

      const updatedSession = await sendHistoryMessage(activeSession.session_id, message);
      setSession(updatedSession);
      setInputValue("");
      setStatusText(`已收到标准化病人回复：${updatedSession.current_intent ?? "未识别意图"}`);
    } catch (error) {
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
      setSession(updatedSession);
      setProcedureResults((currentResults) => [
        ...currentResults.filter((result) => result.id !== `exam:${updatedSession.exam_code}`),
        {
          id: `exam:${updatedSession.exam_code}`,
          label: `查体：${updatedSession.exam_name_cn}`,
          result: updatedSession.result,
        },
      ]);
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
      setSession(updatedSession);
      setProcedureResults((currentResults) => [
        ...currentResults.filter((result) => result.id !== `test:${updatedSession.test_code}`),
        {
          id: `test:${updatedSession.test_code}`,
          label: `检查：${updatedSession.test_name_cn}`,
          result: updatedSession.result,
        },
      ]);
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
    <main className="relative min-h-screen bg-muted/40 text-foreground">
      <div className={isAuthDialogOpen ? "pointer-events-none blur-sm" : ""}>
        <div className="flex min-h-screen">
      <aside className="hidden w-80 shrink-0 border-r border-border bg-background p-4 shadow-inner-right lg:block">
        <div className="mb-6">
          <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
            Clinical OSCE Agent
          </p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">问诊推理舱</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            基于公开 OSCE 病例数据的诊断学临床思维训练工作台。
          </p>
        </div>

        <div className="mt-4">
          <Panel title="问诊引导" description="优先完成不会泄露诊断的核心病史采集。">
            {session ? (
              <div className="space-y-3 text-xs leading-5">
                <p className="rounded-lg border border-[#B5812A]/30 bg-[#FFF8E8] p-3 text-[#8A5A00]">
                  {session?.inquiry_guidance.priority}
                </p>
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
              </div>
            ) : (
              <p className="rounded-lg border border-dashed border-border bg-muted/40 p-3 text-xs leading-5 text-muted-foreground">
                创建训练会话后，这里会展示推荐问诊顺序和示例问题。
              </p>
            )}
          </Panel>
        </div>

        <div className="mt-4">
          <Panel title="病例信息与选择" description="先选择病例，再开始 OSCE 训练。">
            <div className="space-y-3">
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
                  className="mt-3 w-full rounded-md border border-border bg-background px-3 py-2 text-center text-xs font-medium shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={!preparedPatientProfile}
                  onClick={() => setIsPatientProfileOpen(true)}
                  type="button"
                >
                  患者信息
                </button>
              </div>
              <Link
                className="block rounded-md border border-brand bg-brand px-3 py-2 text-center text-xs font-medium text-white shadow-xs transition hover:bg-brand-hover"
                href="/cases"
              >
                选择病例
              </Link>
            </div>
          </Panel>
        </div>

        <div className="mt-4">
          <Panel title="OSCE 流程导航" description="按完整训练闭环提示下一步操作。">
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
            <div className="mt-3 rounded-lg border border-brand/20 bg-brand/5 p-3">
              <p className="text-sm font-semibold text-brand">下一步建议</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">{trainingSuggestion}</p>
            </div>
          </Panel>
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 items-center justify-between border-b border-border bg-background px-5">
          <div>
            <p className="text-xs text-muted-foreground">OSCE 工作台 · 教学模拟，非真实诊疗建议</p>
            <h2 className="text-base font-semibold">
              {formatStage(session?.stage)} · {session?.case_title ?? "本地训练会话"}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <Link
              className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium shadow-xs transition hover:bg-accent"
              href="/safety"
            >
              安全声明
            </Link>
            <Link
              className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium shadow-xs transition hover:bg-accent"
              href="/sources"
            >
              数据来源
            </Link>
            <Link
              className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium shadow-xs transition hover:bg-accent"
              href="/history"
            >
              训练记录
            </Link>
            <Link
              className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium shadow-xs transition hover:bg-accent"
              href="/profile"
            >
              学习画像
            </Link>
            {authUser ? (
              <span className="max-w-40 truncate rounded-md border border-brand/20 bg-brand/10 px-3 py-2 text-sm font-medium text-brand">
                {authUser.display_name}
              </span>
            ) : (
              <button
                className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium shadow-xs transition hover:bg-accent"
                onClick={() => setIsAuthDialogOpen(true)}
                type="button"
              >
                登录 / 注册
              </button>
            )}
            {authUser ? (
              <button
                className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                disabled={isSubmittingAuth}
                onClick={handleLogout}
                type="button"
              >
                退出登录
              </button>
            ) : null}
          </div>
        </header>

        <div className="grid flex-1 grid-cols-1 gap-4 overflow-hidden p-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="flex min-h-0 flex-col rounded-xl border border-border bg-background shadow-xs">
            <div className="border-b border-border p-4">
              <p className="text-sm font-semibold">医患对话</p>
              <p className="mt-1 text-xs text-muted-foreground">
                已接入本地 FastAPI session API；支持问诊、查体、辅助检查、诊断提交与最小报告展示。
              </p>
            </div>

            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              {!session ? <CaseSelectionPrompt selectedCase={selectedCase} /> : null}
              <OpeningTaskCardMessage openingTaskCard={preparedOpeningTaskCard} />
              {chatMessages.map((message) => {
                const isStudent = message.speaker === "student";
                const isCoach = message.speaker === "coach";
                return (
                  <div className={`flex ${isStudent ? "justify-end" : "justify-start"}`} key={message.id}>
                    <div
                      className={`max-w-[76%] rounded-xl border px-4 py-3 text-sm leading-6 shadow-xs ${
                        isStudent
                          ? "border-brand bg-brand text-white"
                          : isCoach
                            ? "border-[#B5812A]/30 bg-[#FFF8E8] text-foreground"
                            : "border-border bg-muted text-foreground"
                      }`}
                    >
                      <p className={isStudent ? "text-white/80" : isCoach ? "text-[#8A5A00]" : "text-muted-foreground"}>
                        {message.label}
                      </p>
                      <p className="mt-1">{message.text}</p>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="border-t border-border bg-background p-4">
              <div className="rounded-xl border border-input bg-muted/50 p-3">
                <form onSubmit={handleSubmit}>
                  <label className="sr-only" htmlFor="history-question">
                    输入下一句问诊问题
                  </label>
                  <div className="flex gap-2">
                    <input
                      className="min-w-0 flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                      disabled={!authUser || !selectedCaseId || isCreating || isSending}
                      id="history-question"
                      onChange={(event) => setInputValue(event.target.value)}
                      placeholder="例如：什么时候开始疼的？疼痛在哪里？有没有恶心或腹泻？"
                      value={inputValue}
                    />
                    <button
                      className="rounded-lg border border-brand bg-brand px-4 py-2 text-sm font-medium text-white shadow-xs transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={!authUser || !selectedCaseId || isCreating || !inputValue.trim() || isSending}
                      type="submit"
                    >
                      {isSending ? "发送中" : "发送问诊"}
                    </button>
                  </div>
                </form>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    className="rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium shadow-xs transition hover:bg-accent"
                    onClick={() => setInputValue("什么时候开始疼的？")}
                    type="button"
                  >
                    问现病史
                  </button>
                  <button
                    className="rounded-md border border-[#B5812A]/30 bg-[#FFF8E8] px-3 py-1.5 text-xs font-medium text-[#8A5A00] shadow-xs transition hover:bg-[#FFF1CC] disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={!authUser || !selectedCaseId || isCreating || isRequestingHint}
                    onClick={handleHintRequest}
                    type="button"
                  >{isRequestingHint ? "提示生成中" : "请求提示"}</button>
                  {physicalExamOptions.map((examOption) => (
                    <button
                      className="rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={!authUser || !selectedCaseId || isCreating || isRequestingExam}
                      key={examOption.exam_code}
                      onClick={() => handlePhysicalExamRequest(examOption.exam_code)}
                      type="button"
                    >
                      {isRequestingExam ? "查体中" : `查体：${examOption.exam_name_cn}`}
                    </button>
                  ))}
                  {auxiliaryTestOptions.map((testOption) => (
                    <button
                      className="rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={!authUser || !selectedCaseId || isCreating || isRequestingTest}
                      key={testOption.test_code}
                      onClick={() => handleAuxiliaryTestRequest(testOption.test_code)}
                      type="button"
                    >
                      {isRequestingTest ? "检查中" : `${testOption.category}：${testOption.test_name_cn}`}
                    </button>
                  ))}
                </div>
                <div className="mt-3 rounded-lg border border-border bg-background p-3">
                  <div className="grid gap-2">
                    <div className="grid gap-2 sm:grid-cols-2">
                      <label className="sr-only" htmlFor="diagnosis-input">
                        输入最终诊断
                      </label>
                      <input
                        className="min-w-0 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-brand/15"
                        disabled={!authUser || !selectedCaseId || isCreating || isSubmittingDiagnosis}
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
                        disabled={!authUser || !selectedCaseId || isCreating || isSubmittingDiagnosis}
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
                      disabled={!authUser || !selectedCaseId || isCreating || isSubmittingDiagnosis}
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
                      disabled={!authUser || !selectedCaseId || isCreating || isSubmittingDiagnosis}
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
                      disabled={!authUser || !selectedCaseId || isCreating || isSubmittingDiagnosis}
                      id="next-step-input"
                      onChange={(event) => setNextStepValue(event.target.value)}
                      onInput={(event) => resizeTextareaToContent(event.currentTarget)}
                      placeholder="若继续训练，下一步最需要验证什么"
                      rows={2}
                      value={nextStepValue}
                    />
                    <button
                      className="rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium text-white shadow-xs transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50 sm:w-fit"
                      disabled={
                        !authUser ||
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
                <p className="mt-3 text-xs leading-5 text-muted-foreground">{statusText}</p>
                {errorText ? <p className="mt-2 text-xs leading-5 text-red-600">{errorText}</p> : null}
              </div>
            </div>
          </div>

          <aside className="flex min-h-0 flex-col gap-4 overflow-y-auto">
            <Panel title="训练进度与素材覆盖" description="用病例素材覆盖度提示下一步训练动作。">
              {session ? (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="rounded-lg border border-border bg-background p-3">
                      <p className="text-muted-foreground">问诊线索</p>
                      <p className="mt-1 text-lg font-semibold text-brand">
                        {formatProgressCount(session.training_progress.history.covered, session.training_progress.history.total)}
                      </p>
                    </div>
                    <div className="rounded-lg border border-border bg-background p-3">
                      <p className="text-muted-foreground">查体项目</p>
                      <p className="mt-1 text-lg font-semibold text-brand">
                        {formatProgressCount(
                          session.training_progress.physical_exam.requested,
                          session.training_progress.physical_exam.total,
                        )}
                      </p>
                    </div>
                    <div className="rounded-lg border border-border bg-background p-3">
                      <p className="text-muted-foreground">辅助检查</p>
                      <p className="mt-1 text-lg font-semibold text-brand">
                        {formatProgressCount(
                          session.training_progress.auxiliary_test.requested,
                          session.training_progress.auxiliary_test.total,
                        )}
                      </p>
                    </div>
                    <div className="rounded-lg border border-border bg-background p-3">
                      <p className="text-muted-foreground">推理证据</p>
                      <p className="mt-1 text-lg font-semibold text-brand">
                        {formatProgressCount(
                          session.training_progress.reasoning.collected_evidence_count,
                          session.training_progress.reasoning.total_evidence,
                        )}
                      </p>
                    </div>
                  </div>
                  <div className="rounded-lg border border-brand/20 bg-brand/5 p-3 text-xs leading-5 text-brand">
                    {session.training_progress.next_focus}
                  </div>
                  <button
                    className="w-full rounded-lg border border-dashed border-brand/30 bg-brand/5 px-3 py-2 text-left text-xs font-medium text-brand transition hover:bg-brand/10"
                    onClick={() => setIsCoverageMapOpen(true)}
                    type="button"
                  >
                    开发者功能：查看素材覆盖图谱
                  </button>
                </div>
              ) : (
                <p className="rounded-lg border border-dashed border-border bg-muted/40 p-3 text-xs leading-5 text-muted-foreground">
                  创建训练会话后，这里会展示病例素材覆盖度和下一步建议。
                </p>
              )}
            </Panel>

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
              title="查体与检查申请"
              isOpen={rightPanelOpenStates.procedures}
              maxContentHeightClass="max-h-64"
              onToggle={() => toggleRightPanel("procedures")}
            >
              {procedureItems.length > 0 ? (
                <ul className="space-y-2 text-sm">
                  {procedureItems.map((item) => (
                    <li className="rounded-md bg-muted px-3 py-2" key={item.id}>
                      <p className="font-medium">{item.label}</p>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">{item.result}</p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs leading-5 text-muted-foreground">
                  点击快捷操作后，这里会展示后端返回的查体和辅助检查结果。
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
                    className="rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium text-white shadow-xs transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
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
                      className="mt-4 inline-flex rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium text-white shadow-xs transition hover:bg-brand-hover"
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
      <div className="fixed bottom-5 left-5 z-40">
        {isOsceDockOpen ? (
          <section className="mb-3 w-[min(22rem,calc(100vw-2rem))] rounded-2xl border border-border bg-background p-4 shadow-xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-medium uppercase tracking-[0.22em] text-muted-foreground">OSCE Dock</p>
                <h2 className="mt-1 text-base font-semibold">OSCE 快捷入口</h2>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">{trainingSuggestion}</p>
              </div>
              <button
                aria-label="关闭 OSCE 快捷入口"
                className="rounded-md border border-border bg-background px-2 py-1 text-xs font-medium shadow-xs transition hover:bg-accent"
                onClick={() => setIsOsceDockOpen(false)}
                type="button"
              >
                关闭
              </button>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
              <Link className="rounded-lg border border-border bg-muted px-3 py-2 font-medium transition hover:bg-accent" href="/cases">
                病例
              </Link>
              <Link className="rounded-lg border border-border bg-muted px-3 py-2 font-medium transition hover:bg-accent" href="/history">
                记录
              </Link>
              <Link className="rounded-lg border border-border bg-muted px-3 py-2 font-medium transition hover:bg-accent" href="/profile">
                画像
              </Link>
              <Link className="rounded-lg border border-border bg-muted px-3 py-2 font-medium transition hover:bg-accent" href="/safety">
                安全
              </Link>
              <Link className="rounded-lg border border-border bg-muted px-3 py-2 font-medium transition hover:bg-accent" href="/sources">
                来源
              </Link>
              {feedbackReport ? (
                <Link className="rounded-lg border border-brand bg-brand px-3 py-2 font-medium text-white transition hover:bg-brand-hover" href={`/report?session_id=${feedbackReport.session_id}`}>
                  报告
                </Link>
              ) : (
                <span className="rounded-lg border border-border bg-muted px-3 py-2 font-medium text-muted-foreground">报告</span>
              )}
              <button
                className="rounded-lg border border-border bg-background px-3 py-2 text-left font-medium transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                disabled={!authUser || !selectedCaseId || isCreating || isRequestingHint}
                onClick={() => void handleHintRequest()}
                type="button"
              >
                提示
              </button>
              <button
                className="rounded-lg border border-border bg-background px-3 py-2 text-left font-medium transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                disabled={!preparedPatientProfile}
                onClick={() => setIsPatientProfileOpen(true)}
                type="button"
              >
                患者
              </button>
            </div>
          </section>
        ) : null}
        <button
          aria-label="打开 OSCE 快捷入口"
          className="flex size-14 items-center justify-center rounded-full border border-brand/30 bg-brand text-xs font-semibold tracking-[0.12em] text-white shadow-xl transition hover:bg-brand-hover focus:ring-2 focus:ring-brand/20"
          onClick={() => setIsOsceDockOpen((isOpen) => !isOpen)}
          type="button"
        >
          OSCE
        </button>
      </div>
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
                className="rounded-md border border-border bg-background px-2 py-1 text-xs font-medium shadow-xs transition hover:bg-accent"
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
      {isCoverageMapOpen && session ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="max-h-[82vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-border bg-background p-5 shadow-xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-medium text-brand">开发者功能</p>
                <h2 className="mt-1 text-base font-semibold">开发者功能 · 素材覆盖图谱</h2>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  用于调试病例素材覆盖，不直接作为学生评分依据。
                </p>
              </div>
              <button
                aria-label="关闭素材覆盖图谱"
                className="rounded-md border border-border bg-background px-2 py-1 text-xs font-medium shadow-xs transition hover:bg-accent"
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
        </div>
      </div>
      {!isCheckingAuth && isAuthDialogOpen ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-background/75 p-4 backdrop-blur">
          <section className="w-full max-w-md rounded-2xl border border-border bg-background p-6 shadow-xl">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">Clinical OSCE Agent</p>
              <h2 className="mt-2 text-xl font-semibold">登录 / 注册</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {isCheckingAuth ? "正在读取登录状态..." : "登录后训练记录、报告和后续会话管理会逐步绑定到当前账号。"}
              </p>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-2 rounded-xl bg-muted p-1">
              <button
                className={`rounded-lg px-3 py-2 text-sm font-medium transition ${
                  authMode === "login" ? "bg-background text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground"
                }`}
                onClick={() => setAuthMode("login")}
                type="button"
              >
                登录
              </button>
              <button
                className={`rounded-lg px-3 py-2 text-sm font-medium transition ${
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
                className="w-full rounded-lg border border-brand bg-brand px-4 py-2 text-sm font-medium text-white shadow-xs transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
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
