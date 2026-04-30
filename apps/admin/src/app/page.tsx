"use client";

import { useEffect, useState } from "react";

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

type AdminSessionReport = Readonly<{
  report_id: string;
  session_id: string;
  case_id: string;
  student_id: string;
  total_score: number;
  dimension_scores: Record<string, number>;
  missed_items: readonly string[];
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

type AdminTrainingInsights = Readonly<{
  session_count: number;
  report_count: number;
  frequent_missed_items: readonly FrequentMissedItem[];
  frequent_learning_recommendations: readonly FrequentLearningRecommendation[];
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

type TrainingEventRecord = Readonly<{
  session_id: string;
  case_id: string;
  student_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}>;

type AdminSessionsResponse = Readonly<{
  sessions: readonly AdminSessionSummary[];
}>;

type AdminSessionReportResponse = Readonly<{
  report: AdminSessionReport;
}>;

type EvaluationListResponse = Readonly<{
  evaluations: readonly EvaluationBatchSummary[];
}>;

type EvaluationDetailResponse = Readonly<{
  evaluation: EvaluationBatchDetail;
}>;

type AdminInsightsResponse = Readonly<{
  insights: AdminTrainingInsights;
}>;

type CandidateListResponse = Readonly<{
  candidates: readonly TrainingSkillCandidateSummary[];
}>;

type CandidateDetailResponse = Readonly<{
  candidate: TrainingSkillCandidateDetail;
}>;

type SessionEventsResponse = Readonly<{
  events: readonly TrainingEventRecord[];
}>;

async function getAdminSessions(): Promise<readonly AdminSessionSummary[]> {
  const response = await fetch("/api/admin/sessions", { method: "GET" });
  if (!response.ok) {
    throw new Error(`读取训练 Session 失败：${response.status}`);
  }
  const payload = (await response.json()) as AdminSessionsResponse;
  return payload.sessions;
}

async function getAdminSessionReport(sessionId: string): Promise<AdminSessionReport> {
  const response = await fetch(`/api/admin/sessions/${sessionId}/report`, { method: "GET" });
  if (!response.ok) {
    throw new Error(`读取评分报告失败：${response.status}`);
  }
  const payload = (await response.json()) as AdminSessionReportResponse;
  return payload.report;
}

async function getAdminSessionEvents(sessionId: string): Promise<readonly TrainingEventRecord[]> {
  const response = await fetch(`/api/admin/sessions/${sessionId}/events`, { method: "GET" });
  if (!response.ok) {
    throw new Error(`读取训练日志失败：${response.status}`);
  }
  const payload = (await response.json()) as SessionEventsResponse;
  return payload.events;
}

async function getAdminInsights(): Promise<AdminTrainingInsights> {
  const response = await fetch("/api/admin/insights", { method: "GET" });
  if (!response.ok) {
    throw new Error(`读取错误模式统计失败：${response.status}`);
  }
  const payload = (await response.json()) as AdminInsightsResponse;
  return payload.insights;
}

async function getAdminEvaluations(): Promise<readonly EvaluationBatchSummary[]> {
  const response = await fetch("/api/admin/evaluations", { method: "GET" });
  if (!response.ok) {
    throw new Error(`读取系统评测失败：${response.status}`);
  }
  const payload = (await response.json()) as EvaluationListResponse;
  return payload.evaluations;
}

async function getAdminEvaluation(batchId: string): Promise<EvaluationBatchDetail> {
  const response = await fetch(`/api/admin/evaluations/${batchId}`, { method: "GET" });
  if (!response.ok) {
    throw new Error(`读取评测详情失败：${response.status}`);
  }
  const payload = (await response.json()) as EvaluationDetailResponse;
  return payload.evaluation;
}

async function getTrainingSkillCandidates(): Promise<readonly TrainingSkillCandidateSummary[]> {
  const response = await fetch("/api/admin/evolution/candidates", { method: "GET" });
  if (!response.ok) {
    throw new Error(`读取候选 Skill 失败：${response.status}`);
  }
  const payload = (await response.json()) as CandidateListResponse;
  return payload.candidates;
}

async function getTrainingSkillCandidate(candidateId: string): Promise<TrainingSkillCandidateDetail> {
  const response = await fetch(`/api/admin/evolution/candidates/${candidateId}`, { method: "GET" });
  if (!response.ok) {
    throw new Error(`读取候选 Skill 详情失败：${response.status}`);
  }
  const payload = (await response.json()) as CandidateDetailResponse;
  return payload.candidate;
}

async function approveTrainingSkillCandidate(candidateId: string): Promise<void> {
  const response = await fetch("/api/admin/evolution/approve", {
    body: JSON.stringify({ candidate_id: candidateId, reviewer_id: "local-admin" }),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`批准候选 Skill 失败：${response.status}`);
  }
}

async function rejectTrainingSkillCandidate(candidateId: string): Promise<void> {
  const response = await fetch("/api/admin/evolution/reject", {
    body: JSON.stringify({ candidate_id: candidateId, reviewer_id: "local-admin" }),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`拒绝候选 Skill 失败：${response.status}`);
  }
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

export default function AdminDashboardPage() {
  const [sessions, setSessions] = useState<readonly AdminSessionSummary[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [selectedReport, setSelectedReport] = useState<AdminSessionReport | null>(null);
  const [insights, setInsights] = useState<AdminTrainingInsights | null>(null);
  const [evaluations, setEvaluations] = useState<readonly EvaluationBatchSummary[]>([]);
  const [selectedEvaluation, setSelectedEvaluation] = useState<EvaluationBatchDetail | null>(null);
  const [candidates, setCandidates] = useState<readonly TrainingSkillCandidateSummary[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<TrainingSkillCandidateDetail | null>(null);
  const [sessionIdInput, setSessionIdInput] = useState("");
  const [trainingEvents, setTrainingEvents] = useState<readonly TrainingEventRecord[]>([]);
  const [statusText, setStatusText] = useState("正在读取管理后台数据...");

  async function loadDashboard() {
    const [nextSessions, nextInsights, nextEvaluations, nextCandidates] = await Promise.all([
      getAdminSessions(),
      getAdminInsights(),
      getAdminEvaluations(),
      getTrainingSkillCandidates(),
    ]);
    setSessions(nextSessions);
    setInsights(nextInsights);
    setEvaluations(nextEvaluations);
    setCandidates(nextCandidates);
    setStatusText("已读取管理后台数据。");
    if (nextSessions[0]) {
      setSelectedSessionId(nextSessions[0].session_id);
      setSessionIdInput(nextSessions[0].session_id);
    }
    if (nextEvaluations[0]) {
      setSelectedEvaluation(await getAdminEvaluation(nextEvaluations[0].batch_id));
    }
    if (nextCandidates[0]) {
      setSelectedCandidate(await getTrainingSkillCandidate(nextCandidates[0].candidate_id));
    }
  }

  useEffect(() => {
    loadDashboard().catch((error: unknown) => {
      setStatusText(error instanceof Error ? error.message : "读取管理后台数据失败。");
    });
  }, []);

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

  async function handleSelectCandidate(candidateId: string) {
    setSelectedCandidate(await getTrainingSkillCandidate(candidateId));
  }

  async function handleReview(action: "approve" | "reject") {
    if (!selectedCandidate) {
      return;
    }
    if (action === "approve") {
      await approveTrainingSkillCandidate(selectedCandidate.candidate_id);
    } else {
      await rejectTrainingSkillCandidate(selectedCandidate.candidate_id);
    }
    const nextCandidates = await getTrainingSkillCandidates();
    setCandidates(nextCandidates);
    setStatusText(action === "approve" ? "已批准并启用候选 Skill。" : "已拒绝候选 Skill。");
  }

  return (
    <main className="min-h-screen bg-[#FAF9F5] px-6 py-8 text-[#141413]">
      <div className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(circle_at_20%_20%,rgba(174,86,48,0.10),transparent_30%),linear-gradient(135deg,rgba(255,255,255,0.75),rgba(250,249,245,0.35))]" />
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
            <p className="rounded-full border border-[#AE5630]/20 bg-[#AE5630]/10 px-4 py-2 text-xs font-medium text-[#AE5630]">{statusText}</p>
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
                    className="rounded-md border border-[#AE5630] bg-[#AE5630] px-3 py-2 text-sm font-medium text-white transition hover:bg-[#C4633A]"
                    onClick={() => void handleLoadSessionReport()}
                    type="button"
                  >
                    读报告
                  </button>
                  <button
                    className="rounded-md border border-[#E6DFD2] bg-white px-3 py-2 text-sm font-medium text-[#6F6257] transition hover:bg-[#F1ECE2]"
                    onClick={() => void handleLoadSessionEvents()}
                    type="button"
                  >
                    读日志
                  </button>
                </div>
              </div>
              <div className="mt-4 grid max-h-80 gap-2 overflow-y-auto pr-1">
                {sessions.length > 0 ? (
                  sessions.map((session) => (
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
                  <p className="rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">暂无训练 Session。</p>
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
                </div>
              ) : (
                <p className="mt-4 rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">正在读取错误模式统计。</p>
              )}
            </section>

            <section className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-5 shadow-sm">
              <h2 className="text-xl font-semibold">系统评测</h2>
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
                  <p className="text-xs font-medium text-[#AE5630]">{getPassLabel(selectedEvaluation.passed)}</p>
                  <h3 className="mt-1 text-sm font-semibold">{selectedEvaluation.batch_id}</h3>
                  <p className="mt-2 text-sm text-[#6F6257]">
                    通过 {selectedEvaluation.passed_cases}/{selectedEvaluation.total_cases} 例 · 耗时 {selectedEvaluation.total_duration_ms} ms
                  </p>
                  <div className="mt-3 grid gap-2">
                    {selectedEvaluation.results.map((result) => (
                      <p className="rounded-lg border border-[#E6DFD2] bg-white p-3 text-xs text-[#6F6257]" key={result.session_id}>
                        {result.session_id} · {getPassLabel(result.passed)} · 实际 {result.actual_total_score} / 期望 {result.expected_total_score}
                      </p>
                    ))}
                  </div>
                </article>
              ) : null}
            </section>

            <section className="rounded-2xl border border-[#E6DFD2] bg-white/70 p-5 shadow-sm">
              <h2 className="text-xl font-semibold">候选 Skill 审核</h2>
              <div className="mt-4 grid gap-2">
                {candidates.map((candidate) => (
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
                ))}
              </div>
              {selectedCandidate ? (
                <article className="mt-4 rounded-xl border border-[#E6DFD2] bg-[#FAF9F5] p-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div>
                      <p className="text-xs font-medium text-[#AE5630]">{selectedCandidate.review.status}</p>
                      <h3 className="mt-1 text-lg font-semibold">{selectedCandidate.title}</h3>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        className="rounded-md border border-[#AE5630] bg-[#AE5630] px-3 py-2 text-sm font-medium text-white transition hover:bg-[#C4633A]"
                        onClick={() => void handleReview("approve")}
                        type="button"
                      >
                        批准并启用
                      </button>
                      <button
                        className="rounded-md border border-[#E6DFD2] bg-white px-3 py-2 text-sm font-medium text-[#6F6257] transition hover:bg-[#F1ECE2]"
                        onClick={() => void handleReview("reject")}
                        type="button"
                      >
                        拒绝候选
                      </button>
                    </div>
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
                  </div>
                </article>
              ) : (
                <p className="mt-4 rounded-xl border border-dashed border-[#E6DFD2] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">请选择一个候选 Skill。</p>
              )}
            </section>
          </div>
        </div>
      </div>
    </main>
  );
}
