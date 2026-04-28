"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { saveTrainingHistoryRecord } from "./training-history";

type StageStatus = "done" | "active" | "locked";

type StageDefinition = {
  readonly key: string;
  readonly label: string;
};

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

type OsceSession = Readonly<{
  session_id: string;
  student_id: string;
  case_id: string;
  stage: string;
  case_title: string;
  chief_complaint: string;
  diagnosis_draft: DiagnosisDraft;
  physical_exam_options: readonly PhysicalExamOption[];
  auxiliary_test_options: readonly AuxiliaryTestOption[];
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
  feedback_summary: string;
}>;

type CaseOption = Readonly<{
  id: string;
  title: string;
  module: string;
  difficulty: string;
  chiefComplaint: string;
  enabled: boolean;
}>;

type CaseSummary = Readonly<{
  case_id: string;
  case_title: string;
  course_module: string;
  difficulty: string;
  chief_complaint: string;
  enabled: boolean;
}>;

type CaseListResponse = Readonly<{
  cases: readonly CaseSummary[];
}>;

type SourceReferenceGroup = Readonly<{
  key: string;
  title: string;
  description: string;
  references: readonly string[];
}>;

const defaultCaseOption: CaseOption = {
  id: "appendicitis_001",
  title: "右下腹痛教学病例",
  module: "腹痛",
  difficulty: "初级",
  chiefComplaint: "转移性右下腹痛 24 小时，伴恶心、低热",
  enabled: true,
};

const DEFAULT_CASE_ID = defaultCaseOption.id;
const STUDENT_ID = "web_demo";
const DEFAULT_DIAGNOSIS = "急性阑尾炎";
const DEFAULT_REASONING = "转移性右下腹痛、反跳痛和白细胞升高支持诊断。";

function getTrainingRecordStatus(totalScore: number): string {
  if (totalScore >= 60) {
    return "基本达标";
  }

  return "继续训练";
}

const caseOptions: readonly CaseOption[] = [
  defaultCaseOption,
  {
    id: "pneumonia_001",
    title: "发热咳嗽伴胸痛教学病例",
    module: "发热",
    difficulty: "初级",
    chiefComplaint: "发热、咳嗽 3 天，右侧胸痛 1 天。",
    enabled: false,
  },
  {
    id: "hyperthyroid_001",
    title: "心慌、手抖与消瘦教学病例",
    module: "心悸",
    difficulty: "中级",
    chiefComplaint: "心慌、手抖 2 个月，消瘦 1 个月。",
    enabled: false,
  },
  {
    id: "acs_001",
    title: "胸痛伴出汗教学病例",
    module: "胸痛",
    difficulty: "中级",
    chiefComplaint: "胸骨后压榨性胸痛 2 小时，伴大汗。",
    enabled: false,
  },
  {
    id: "heart_failure_001",
    title: "活动后气短伴夜间憋醒教学病例",
    module: "呼吸困难",
    difficulty: "中级",
    chiefComplaint: "活动后气短 2 周，加重伴夜间憋醒 3 天。",
    enabled: false,
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

const scoreDimensionMaxScores: Readonly<Record<string, number>> = {
  history_taking: 25,
  physical_exam: 15,
  auxiliary_test: 15,
  main_diagnosis: 15,
  differential_diagnosis: 15,
  reasoning: 15,
};

function getStageClass(status: StageStatus): string {
  if (status === "done") {
    return "border-brand/20 bg-[#2F6868]/10 text-brand";
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

function formatStage(stage: string | undefined): string {
  const stageLabel = stageDefinitions.find((definition) => definition.key === stage)?.label;
  return stageLabel ?? "等待会话";
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
      label: "过程提示",
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

function groupSourceReferences(references: readonly string[]): readonly SourceReferenceGroup[] {
  const groupOrder = ["case", "source", "rubric", "evidence", "other"];
  const groupedReferences = references.reduce<Record<string, string[]>>((groups, reference) => {
    const key = getSourceReferenceGroupKey(reference);
    return {
      ...groups,
      [key]: [...(groups[key] ?? []), reference],
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

function mapCaseSummary(caseSummary: CaseSummary): CaseOption {
  return {
    id: caseSummary.case_id,
    title: caseSummary.case_title,
    module: caseSummary.course_module,
    difficulty: caseSummary.difficulty,
    chiefComplaint: caseSummary.chief_complaint,
    enabled: caseSummary.enabled,
  };
}

async function requestJson<TResponse>(path: string, init: RequestInit): Promise<TResponse> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");

  const response = await fetch(path, {
    ...init,
    headers,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `请求失败：${response.status}`);
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
  return requestJson<OsceSession>(`/api/sessions/${sessionId}`, {
    method: "GET",
  });
}

function getSessionReport(sessionId: string): Promise<FeedbackReport> {
  return requestJson<FeedbackReport>(`/api/sessions/${sessionId}/report`, {
    method: "GET",
  });
}

function Panel({
  title,
  description,
  children,
}: Readonly<{
  title: string;
  description?: string;
  children: ReactNode;
}>) {
  return (
    <section className="rounded-xl border border-border bg-card p-4 shadow-xs">
      <div className="mb-4 space-y-1">
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        {description ? <p className="text-xs leading-5 text-muted-foreground">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

function HomeContent() {
  const searchParams = useSearchParams();
  const initialCaseId = searchParams.get("case_id") ?? DEFAULT_CASE_ID;
  const [selectedCaseId, setSelectedCaseId] = useState(initialCaseId);
  const [caseOptionsState, setCaseOptionsState] = useState<readonly CaseOption[]>(caseOptions);
  const [session, setSession] = useState<OsceSession | null>(null);
  const [inputValue, setInputValue] = useState("");
  const [statusText, setStatusText] = useState("正在连接本地 OSCE 后端...");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [isRequestingExam, setIsRequestingExam] = useState(false);
  const [isRequestingTest, setIsRequestingTest] = useState(false);
  const [hypothesisValue, setHypothesisValue] = useState("");
  const [isRecordingHypothesis, setIsRecordingHypothesis] = useState(false);
  const [isRequestingHint, setIsRequestingHint] = useState(false);
  const [diagnosisValue, setDiagnosisValue] = useState(DEFAULT_DIAGNOSIS);
  const [reasoningValue, setReasoningValue] = useState(DEFAULT_REASONING);
  const [isSubmittingDiagnosis, setIsSubmittingDiagnosis] = useState(false);
  const [feedbackReport, setFeedbackReport] = useState<FeedbackReport | null>(null);
  const [savedHistorySessionId, setSavedHistorySessionId] = useState<string | null>(null);
  const [procedureResults, setProcedureResults] = useState<readonly ProcedureResult[]>([]);

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
          nextCaseOptions.some((caseOption) => caseOption.id === currentSelectedCaseId)
            ? currentSelectedCaseId
            : nextCaseOptions[0].id,
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
    let isMounted = true;

    async function startSession() {
      setIsCreating(true);
      setSession(null);
      setInputValue("");
      setHypothesisValue("");
      setDiagnosisValue(DEFAULT_DIAGNOSIS);
      setReasoningValue(DEFAULT_REASONING);
      setFeedbackReport(null);
      setSavedHistorySessionId(null);
      setProcedureResults([]);
      setStatusText("正在连接本地 OSCE 后端...");
      setErrorText(null);

      try {
        const createdSession = await createSession(selectedCaseId);
        if (!isMounted) {
          return;
        }

        setSession(createdSession);
        setDiagnosisValue(createdSession.diagnosis_draft.diagnosis);
        setReasoningValue(createdSession.diagnosis_draft.reasoning);
        setStatusText("已创建本地训练会话，可以开始问诊。");
        setErrorText(null);
      } catch (error) {
        if (!isMounted) {
          return;
        }

        setStatusText("后端未连接，页面暂时只显示工作台框架。");
        setErrorText(error instanceof Error ? error.message : "创建训练会话失败。");
      } finally {
        if (isMounted) {
          setIsCreating(false);
        }
      }
    }

    startSession();

    return () => {
      isMounted = false;
    };
  }, [selectedCaseId]);

  const selectedCase = useMemo(
    () => caseOptionsState.find((caseOption) => caseOption.id === selectedCaseId) ?? defaultCaseOption,
    [caseOptionsState, selectedCaseId],
  );

  const chatMessages = useMemo<readonly ChatMessage[]>(() => {
    if (!session) {
      return [
        {
          id: "loading-patient-message",
          speaker: "patient",
          label: "标准化病人",
          text: "正在等待本地后端创建 OSCE 训练会话。",
        },
      ];
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
    () => groupSourceReferences(feedbackReport?.source_references ?? []),
    [feedbackReport?.source_references],
  );

  const scoringPreview = useMemo(
    () => [
      `当前阶段：${formatStage(session?.stage)}`,
      `已问问题：${session?.asked_questions.length ?? 0} 个`,
      `已披露线索：${session?.revealed_facts.length ?? 0} 条`,
      `最终诊断：${session?.final_submission?.diagnosis ?? "尚未提交"}`,
    ],
    [session?.asked_questions.length, session?.final_submission?.diagnosis, session?.revealed_facts.length, session?.stage],
  );

  const reportDimensions = useMemo(
    () => Object.entries(feedbackReport?.dimension_scores ?? {}),
    [feedbackReport?.dimension_scores],
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = inputValue.trim();

    if (!session || !message || isSending) {
      return;
    }

    setIsSending(true);
    setErrorText(null);

    try {
      const updatedSession = await sendHistoryMessage(session.session_id, message);
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
    if (!session || isRequestingExam) {
      return;
    }

    setIsRequestingExam(true);
    setErrorText(null);

    try {
      const updatedSession = await requestPhysicalExam(session.session_id, examCode);
      setSession(updatedSession);
      setProcedureResults((currentResults) => [
        ...currentResults.filter((result) => result.id !== `exam:${updatedSession.exam_code}`),
        {
          id: `exam:${updatedSession.exam_code}`,
          label: `查体：${updatedSession.exam_name_cn}`,
          result: updatedSession.result,
        },
      ]);
      setStatusText(`已返回查体结果：${updatedSession.exam_name_cn}`);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "请求查体失败。");
      setStatusText("查体请求失败，请确认后端仍在运行。");
    } finally {
      setIsRequestingExam(false);
    }
  }

  async function handleAuxiliaryTestRequest(testCode: string) {
    if (!session || isRequestingTest) {
      return;
    }

    setIsRequestingTest(true);
    setErrorText(null);

    try {
      const updatedSession = await requestAuxiliaryTest(session.session_id, testCode);
      setSession(updatedSession);
      setProcedureResults((currentResults) => [
        ...currentResults.filter((result) => result.id !== `test:${updatedSession.test_code}`),
        {
          id: `test:${updatedSession.test_code}`,
          label: `检查：${updatedSession.test_name_cn}`,
          result: updatedSession.result,
        },
      ]);
      setStatusText(`已返回辅助检查结果：${updatedSession.test_name_cn}`);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "申请辅助检查失败。");
      setStatusText("辅助检查申请失败，请确认后端仍在运行。");
    } finally {
      setIsRequestingTest(false);
    }
  }

  function handleSaveTrainingRecord() {
    if (!session || !feedbackReport) {
      return;
    }

    saveTrainingHistoryRecord({
      sessionId: feedbackReport.session_id,
      caseId: feedbackReport.case_id,
      caseTitle: session.case_title,
      totalScore: feedbackReport.total_score,
      status: getTrainingRecordStatus(feedbackReport.total_score),
      savedAt: new Date().toISOString(),
      reportUrl: `/report?session_id=${feedbackReport.session_id}`,
    });
    setSavedHistorySessionId(feedbackReport.session_id);
    setStatusText("已保存到本机训练记录。");
  }

  async function handleHypothesisSubmit() {
    const hypothesis = hypothesisValue.trim();

    if (!session || !hypothesis || isRecordingHypothesis) {
      return;
    }

    setIsRecordingHypothesis(true);
    setErrorText(null);

    try {
      const updatedSession = await recordHypothesis(session.session_id, hypothesis);
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
    if (!session || isRequestingHint) {
      return;
    }

    setIsRequestingHint(true);
    setErrorText(null);

    try {
      const updatedSession = await requestHint(session.session_id);
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
    const reasoning = reasoningValue.trim();

    if (!session || !diagnosis || !reasoning || isSubmittingDiagnosis) {
      return;
    }

    setIsSubmittingDiagnosis(true);
    setErrorText(null);

    try {
      const submittedSession = await submitDiagnosis(session.session_id, diagnosis, reasoning);
      const report = await getSessionReport(submittedSession.session_id);
      const updatedSession = await getSession(submittedSession.session_id);
      setSession(updatedSession);
      setFeedbackReport(report);
      setSavedHistorySessionId(null);
      setStatusText(`已提交诊断并生成评分报告：${report.total_score} 分。`);
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "提交诊断或获取报告失败。");
      setStatusText("诊断提交失败，请确认后端仍在运行。");
    } finally {
      setIsSubmittingDiagnosis(false);
    }
  }

  return (
    <main className="flex min-h-screen bg-muted/40 text-foreground">
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

        <Panel title="当前病例" description="MVP 示例病例 · 教学模拟">
          <div className="space-y-3 text-sm">
            <div className="rounded-lg border border-border bg-muted/60 p-3">
              <p className="text-xs text-muted-foreground">主诉</p>
              <p className="mt-1 font-medium">{session?.chief_complaint ?? selectedCase.chiefComplaint}</p>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-md bg-muted p-2">
                <p className="text-muted-foreground">病例</p>
                <p className="mt-1 font-medium">{session?.case_title ?? selectedCase.title}</p>
              </div>
              <div className="rounded-md bg-muted p-2">
                <p className="text-muted-foreground">会话</p>
                <p className="mt-1 truncate font-medium">{session?.session_id ?? "待创建"}</p>
              </div>
            </div>
          </div>
        </Panel>

        <div className="mt-4">
          <Panel title="病例选择" description="先开放已完成前端闭环的 demo 病例。">
            <Link
              className="mb-3 block rounded-md border border-border bg-background px-3 py-2 text-center text-xs font-medium shadow-xs transition hover:bg-accent"
              href="/cases"
            >
              查看全部病例
            </Link>
            <div className="space-y-2">
              {caseOptionsState.map((caseOption) => {
                const isSelected = selectedCaseId === caseOption.id;
                return (
                  <button
                    className={`w-full rounded-lg border px-3 py-2 text-left text-xs transition ${
                      isSelected
                        ? "border-brand bg-[#2F6868]/10 text-brand"
                        : "border-border bg-background text-foreground hover:bg-accent"
                    } disabled:cursor-not-allowed disabled:opacity-60`}
                    disabled={!caseOption.enabled || isSelected || isCreating}
                    key={caseOption.id}
                    onClick={() => setSelectedCaseId(caseOption.id)}
                    type="button"
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="font-medium">{caseOption.title}</span>
                      <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                        {caseOption.enabled ? "可训练" : "待接入"}
                      </span>
                    </span>
                    <span className="mt-1 block text-muted-foreground">
                      {caseOption.module} · {caseOption.difficulty}
                    </span>
                  </button>
                );
              })}
            </div>
          </Panel>
        </div>

        <div className="mt-4">
          <Panel title="训练阶段">
            <div className="space-y-2">
              {stageDefinitions.map((stage) => (
                <div
                  className={`rounded-md border px-3 py-2 text-sm font-medium ${getStageClass(
                    getStageStatus(stage.key, session?.stage),
                  )}`}
                  key={stage.key}
                >
                  {stage.label}
                </div>
              ))}
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
            <button
              className="rounded-md border border-brand bg-brand px-4 py-2 text-sm font-medium text-white shadow-xs transition hover:bg-[#2F6868]/90 disabled:cursor-not-allowed disabled:border-border disabled:bg-muted disabled:text-muted-foreground"
              disabled={!feedbackReport || savedHistorySessionId === feedbackReport.session_id}
              onClick={handleSaveTrainingRecord}
              type="button"
            >
              {feedbackReport && savedHistorySessionId === feedbackReport.session_id ? "已保存记录" : "保存训练记录"}
            </button>
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
              {chatMessages.map((message) => {
                const isStudent = message.speaker === "student";
                const isCoach = message.speaker === "coach";
                return (
                  <div className={`flex ${isStudent ? "justify-end" : "justify-start"}`} key={message.id}>
                    <div
                      className={`max-w-[76%] rounded-xl border px-4 py-3 text-sm leading-6 shadow-xs ${
                        isStudent
                          ? "border-brand bg-[#2F6868] text-white"
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
                      className="min-w-0 flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-[#2F6868]/15"
                      disabled={!session || isCreating || isSending}
                      id="history-question"
                      onChange={(event) => setInputValue(event.target.value)}
                      placeholder="例如：什么时候开始疼的？疼痛在哪里？有没有恶心或腹泻？"
                      value={inputValue}
                    />
                    <button
                      className="rounded-lg border border-brand bg-brand px-4 py-2 text-sm font-medium text-white shadow-xs transition hover:bg-[#2F6868]/90 disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={!session || !inputValue.trim() || isSending}
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
                    disabled={!session || isRequestingHint}
                    onClick={handleHintRequest}
                    type="button"
                  >{isRequestingHint ? "提示生成中" : "请求提示"}</button>
                  {session?.physical_exam_options.map((examOption) => (
                    <button
                      className="rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={isRequestingExam}
                      key={examOption.exam_code}
                      onClick={() => handlePhysicalExamRequest(examOption.exam_code)}
                      type="button"
                    >
                      {isRequestingExam ? "查体中" : `查体：${examOption.exam_name_cn}`}
                    </button>
                  ))}
                  {session?.auxiliary_test_options.map((testOption) => (
                    <button
                      className="rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={isRequestingTest}
                      key={testOption.test_code}
                      onClick={() => handleAuxiliaryTestRequest(testOption.test_code)}
                      type="button"
                    >
                      {isRequestingTest ? "检查中" : `${testOption.category}：${testOption.test_name_cn}`}
                    </button>
                  ))}
                </div>
                <div className="mt-3 rounded-lg border border-border bg-background p-3">
                  <div className="grid gap-2 sm:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)_auto]">
                    <label className="sr-only" htmlFor="diagnosis-input">
                      输入最终诊断
                    </label>
                    <input
                      className="min-w-0 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-[#2F6868]/15"
                      disabled={!session || isSubmittingDiagnosis}
                      id="diagnosis-input"
                      onChange={(event) => setDiagnosisValue(event.target.value)}
                      placeholder="最终诊断"
                      value={diagnosisValue}
                    />
                    <label className="sr-only" htmlFor="reasoning-input">
                      输入诊断依据
                    </label>
                    <input
                      className="min-w-0 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-[#2F6868]/15"
                      disabled={!session || isSubmittingDiagnosis}
                      id="reasoning-input"
                      onChange={(event) => setReasoningValue(event.target.value)}
                      placeholder="诊断依据"
                      value={reasoningValue}
                    />
                    <button
                      className="rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium text-white shadow-xs transition hover:bg-[#2F6868]/90 disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={!session || !diagnosisValue.trim() || !reasoningValue.trim() || isSubmittingDiagnosis}
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

          <aside className="grid min-h-0 gap-4 overflow-y-auto xl:grid-cols-1">
            <Panel title="已收集线索" description="来自问诊节点的结构化事实。">
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
            </Panel>

            <Panel title="查体与检查申请">
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
            </Panel>

            <Panel title="诊断假设">
              <div className="space-y-3">
                <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                  <label className="sr-only" htmlFor="hypothesis-input">
                    输入训练中的诊断假设
                  </label>
                  <input
                    className="min-w-0 rounded-md border border-border bg-background px-3 py-2 text-xs outline-none transition placeholder:text-muted-foreground focus:border-brand focus:ring-2 focus:ring-[#2F6868]/15"
                    disabled={!session || isRecordingHypothesis}
                    id="hypothesis-input"
                    onChange={(event) => setHypothesisValue(event.target.value)}
                    placeholder="例如：急性阑尾炎"
                    value={hypothesisValue}
                  />
                  <button
                    className="rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium text-white shadow-xs transition hover:bg-[#2F6868]/90 disabled:cursor-not-allowed disabled:opacity-50"
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
            </Panel>

            <Panel title="评分报告" description="提交诊断后展示结构化复盘报告。">
              <div className="space-y-2">
                {scoringPreview.map((item) => (
                  <p className="rounded-md border border-border bg-background px-3 py-2 text-xs" key={item}>
                    {item}
                  </p>
                ))}
                <p className="rounded-md border border-brand/20 bg-[#2F6868]/5 px-3 py-2 text-xs leading-5 text-brand">
                  本报告仅用于教学复盘，评分依据来自病例、rubric 与来源引用。
                </p>
              </div>
              {feedbackReport ? (
                <div className="mt-3 space-y-4 rounded-xl border border-brand/20 bg-[#2F6868]/5 p-3">
                  <div className="rounded-xl border border-brand/20 bg-background p-4 shadow-xs">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="text-xs text-muted-foreground">OSCE 训练总分</p>
                        <div className="mt-1 flex items-end gap-1 text-brand">
                          <span className="text-4xl font-semibold leading-none">{feedbackReport.total_score}</span>
                          <span className="pb-1 text-sm font-medium">/ 100</span>
                        </div>
                      </div>
                      <span className="rounded-full border border-brand/20 bg-[#2F6868]/10 px-3 py-1 text-xs font-medium text-brand">
                        {feedbackReport.total_score >= 60 ? "基本达标" : "继续训练"}
                      </span>
                    </div>
                    <div className="mt-4 h-2 overflow-hidden rounded-full bg-muted">
                      <div className="h-full rounded-full bg-brand" style={{ width: `${feedbackReport.total_score}%` }} />
                    </div>
                    <p className="mt-3 text-xs leading-5 text-muted-foreground">{feedbackReport.feedback_summary}</p>
                    <Link
                      className="mt-4 inline-flex rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium text-white shadow-xs transition hover:bg-[#2F6868]/90"
                      href={`/report?session_id=${feedbackReport.session_id}`}
                    >
                      打开独立报告页
                    </Link>
                  </div>

                  {reportDimensions.length > 0 ? (
                    <div className="space-y-2 rounded-xl border border-border bg-background p-3">
                      <p className="text-xs font-medium">维度得分</p>
                      {reportDimensions.map(([key, score]) => {
                        const maxScore = scoreDimensionMaxScores[key] ?? 100;
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
                              {group.references.map((reference) => (
                                <li className="rounded-md bg-background/80 px-2 py-1 font-mono text-[11px]" key={reference}>
                                  {getSourceReferenceLabel(reference)}
                                </li>
                              ))}
                            </ul>
                          </section>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              ) : null}
            </Panel>
          </aside>
        </div>
      </section>
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
