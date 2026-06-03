"use client";

import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";
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
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  Wrench,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

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
  dimension_scores?: Record<string, number>;
  missed_items?: readonly string[];
  missed_item_labels?: readonly string[];
  source_reference_items?: readonly AdminSourceReferenceItem[];
  explanation_source_items?: readonly AdminSourceReferenceItem[];
  knowledge_recommendations?: readonly ReportRecommendation[];
  generation_warnings?: readonly string[];
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
  changed_fields?: readonly string[];
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
    stage_scope_labels?: readonly string[];
    applies_when?: readonly string[];
    effect_status?: string;
    effect_status_label?: string;
    suggested_strategy?: string;
    teaching_action_plan?: readonly TrainingSkillTeachingAction[];
    success_metrics?: readonly string[];
    related_recommendation_labels?: readonly string[];
    source_report_ids?: readonly string[];
    source_session_ids?: readonly string[];
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

type AdminSourceSummary = Readonly<{
  source_id: string;
  title?: string;
  source_type?: string;
}>;

type AdminRagDocument = Readonly<{
  document_id: string;
  title?: string;
  filename?: string;
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

type ApiCallLog = Readonly<{
  created_at: string;
  provider: string;
  operation: string;
  model: string;
  endpoint: string;
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

type TrainingInsights = Readonly<{
  session_count: number;
  report_count: number;
  frequent_missed_items?: readonly unknown[];
  frequent_turn_patterns?: readonly unknown[];
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
  insights: TrainingInsights | null;
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
  insights: null,
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
    insightsPayload,
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
    fetchJson<{ insights: TrainingInsights }>("/api/admin/insights"),
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
    insights: insightsPayload.insights,
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
  const [errorText, setErrorText] = useState("");
  const [loginErrorText, setLoginErrorText] = useState("");

  const selectedSession = useMemo(
    () => data.sessions.find((session) => session.session_id === selectedSessionId) ?? data.sessions[0] ?? null,
    [data.sessions, selectedSessionId],
  );

  useEffect(() => {
    let isMounted = true;
    fetchJson<{ user: AuthUser }>("/api/auth/me")
      .then((payload) => {
        if (!isMounted) {
          return;
        }
        setAuthUser(payload.user);
        if (payload.user.is_admin) {
          void refreshDashboard();
        }
      })
      .catch(() => {
        if (isMounted) {
          setAuthUser(null);
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsAuthLoading(false);
        }
      });
    return () => {
      isMounted = false;
    };
  }, []);

  async function refreshDashboard() {
    setIsDataLoading(true);
    setErrorText("");
    try {
      const nextData = await loadDashboardData();
      setData(nextData);
      setSelectedSessionId((current) => current || nextData.sessions[0]?.session_id || "");
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : "读取管理端数据失败");
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
      setErrorText(error instanceof Error ? error.message : "读取报告失败");
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
    try {
      const nextDocument = await setRagDocumentEnabled(documentId, enabled);
      setData((current) => ({
        ...current,
        documents: current.documents.map((document) => (document.document_id === documentId ? nextDocument : document)),
      }));
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : enabled ? "启用文档失败" : "停用文档失败");
    } finally {
      setIsDocumentBusy(false);
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
              <Input autoComplete="off" onChange={(event) => setEmail(event.target.value)} placeholder="输入管理员邮箱" type="email" value={email} />
            </label>
            <label className="grid gap-2 text-sm font-medium">
              密码
              <Input autoComplete="new-password" onChange={(event) => setPassword(event.target.value)} placeholder="输入管理员账号密码" type="password" value={password} />
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
            <Button onClick={() => void handleLogout()} variant="ghost">
              <LogOut />
              退出登录
            </Button>
          </div>
        </aside>
        <section className="min-w-0 p-4 sm:p-6">
          <header className="flex flex-col gap-4 rounded-3xl border border-[#E7E0D4] bg-white p-5 shadow-sm lg:flex-row lg:items-center lg:justify-between">
            <h2 className="text-2xl font-semibold">临境 OSCE 管理工作台</h2>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="success">管理员已登录</Badge>
              <Button disabled={isDataLoading} onClick={() => void refreshDashboard()} variant="secondary">
                {isDataLoading ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                刷新
              </Button>
            </div>
          </header>

          {errorText ? <p className="mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{errorText}</p> : null}

          <div className="mt-4">
            {activeSectionId === "overview" ? (
              <OverviewSection data={data} onGenerateSkillCandidates={() => void generateSkillCandidates()} onRunEvaluation={() => void runEvaluation()} isMutating={isMutating} />
            ) : null}
            {activeSectionId === "resources" ? <ResourcesSection data={data} isDocumentBusy={isDocumentBusy} onSetDocumentEnabled={(documentId, enabled) => void handleSetDocumentEnabled(documentId, enabled)} /> : null}
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
  onSetDocumentEnabled,
}: Readonly<{
  data: DashboardData;
  isDocumentBusy: boolean;
  onSetDocumentEnabled: (documentId: string, enabled: boolean) => void;
}>) {
  return (
    <div className="grid gap-4">
      <SectionIntro eyebrow="教学资源" title="病例、来源和知识库" description="查看病例、来源和知识库启用状态。" />
      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard icon={<BookOpen />} label="病例" value={formatCount(data.cases.length)} helper="学生可训练病例" />
        <MetricCard icon={<FileText />} label="来源" value={formatCount(data.sources.length)} helper="来源台账" />
        <MetricCard icon={<Brain />} label="知识库文档" value={formatCount(data.documents.length)} helper={`${data.documents.filter((document) => document.enabled).length} 份已启用`} />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>知识库文档</CardTitle>
          <CardDescription>教师上传的全局或病例知识库，启用后进入所选 Agent 的 RAG 检索。</CardDescription>
        </CardHeader>
        <CardContent>
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
                      <Button disabled={isDocumentBusy} onClick={() => onSetDocumentEnabled(document.document_id, !document.enabled)} size="sm" variant={document.enabled ? "outline" : "secondary"}>
                        {document.enabled ? "停用文档" : "启用文档"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.documents.length === 0 ? <EmptyText>暂无知识库文档。</EmptyText> : null}
        </CardContent>
      </Card>
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
                  <Button disabled={isDetailBusy} onClick={() => onReadReport(selectedSession.session_id)} size="sm">
                    {isDetailBusy ? <Loader2 className="animate-spin" /> : <FileText />}
                    读取报告
                  </Button>
                  <Button disabled={isDetailBusy} onClick={() => onReadEvents(selectedSession.session_id)} size="sm" variant="secondary">
                    {isDetailBusy ? <Loader2 className="animate-spin" /> : <Activity />}
                    读取日志
                  </Button>
                </div>
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
    </div>
  );
}

function InsightsSection({ data }: Readonly<{ data: DashboardData }>) {
  return (
    <div className="grid gap-4">
      <SectionIntro eyebrow="教学洞察" title="错误模式与训练重点" description="聚合训练报告中的高频问题，供 Skill 生成和教师复盘参考。" />
      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard icon={<Stethoscope />} label="洞察 Session" value={formatCount(data.insights?.session_count ?? 0)} helper="进入统计的训练" />
        <MetricCard icon={<FileText />} label="洞察报告" value={formatCount(data.insights?.report_count ?? 0)} helper="进入统计的报告" />
        <MetricCard icon={<Brain />} label="错误模式" value={formatCount(data.insights?.frequent_turn_patterns?.length ?? 0)} helper="训练模式级聚合" />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>当前训练问题</CardTitle>
          <CardDescription>按训练报告聚合高频问题。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-2xl border border-[#E7E0D4] bg-[#FAF9F5] p-4 text-sm leading-6 text-[#6F6257]">
            高频漏项、教学重点和来源热度已由后端聚合，用于生成候选 Skill 和教师复盘。
          </div>
        </CardContent>
      </Card>
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
                <InfoBlock className="lg:col-span-2" title="教学策略" value={selectedCandidate.suggested_strategy || "暂无策略。"} />
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
    </div>
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
        <SectionIntro eyebrow="系统评测" title="回归批次和用例结果" description="用于证明 RAG 覆盖、报告兼容和 Skill 闭环不会回退。" />
        <Button disabled={isMutating} onClick={onRunEvaluation}>
          {isMutating ? <Loader2 className="animate-spin" /> : <ClipboardCheck />}
          运行系统评测
        </Button>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard icon={<ClipboardCheck />} label="评测批次" value={formatCount(data.evaluationPagination?.total ?? data.evaluations.length)} helper="历史批次" />
        <MetricCard icon={<Gauge />} label="总通过率" value={`${passRate}%`} helper={`${passedCases}/${totalCases} 用例`} />
        <MetricCard icon={<Wrench />} label="失败用例" value={formatCount(data.evaluations.reduce((sum, evaluation) => sum + evaluation.failed_cases, 0))} helper="需要排查" />
      </div>
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

function LogsSection({ data }: Readonly<{ data: DashboardData }>) {
  return (
    <div className="grid gap-4">
      <SectionIntro eyebrow="模型调用" title="API 成功率和最近错误" description="用于排查模型中转、embedding、TeacherAgent 和审批 Agent 的调用稳定性。" />
      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard icon={<Activity />} label="总调用" value={formatCount(data.apiLogs?.summary.total_calls ?? 0)} helper="最近日志窗口" />
        <MetricCard icon={<Gauge />} label="成功率" value={`${Math.round((data.apiLogs?.summary.success_rate ?? 0) * 100)}%`} helper={`平均 ${data.apiLogs?.summary.avg_duration_ms ?? 0} ms`} />
        <MetricCard icon={<Wrench />} label="失败调用" value={formatCount(data.apiLogs?.summary.failed_calls ?? 0)} helper="已脱敏展示" />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>最近模型 API 日志</CardTitle>
          <CardDescription>不显示密钥或完整 URL，只显示脱敏后的调用结果。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-[#8A7D6F]">
                <tr className="border-b border-[#E7E0D4]">
                  <th className="py-3 pr-4">时间</th>
                  <th className="py-3 pr-4">Provider</th>
                  <th className="py-3 pr-4">用途</th>
                  <th className="py-3 pr-4">模型</th>
                  <th className="py-3 pr-4">耗时</th>
                  <th className="py-3 pr-4">状态</th>
                </tr>
              </thead>
              <tbody>
                {(data.apiLogs?.logs ?? []).slice(0, 18).map((log, index) => (
                  <tr className="border-b border-[#F0E8DC]" key={`${log.created_at}-${log.operation}-${index}`}>
                    <td className="py-3 pr-4 text-[#6F6257]">{formatDateTime(log.created_at)}</td>
                    <td className="py-3 pr-4 font-medium">{log.provider || "unknown"}</td>
                    <td className="py-3 pr-4 text-[#6F6257]">{getOperationLabel(log.operation)}</td>
                    <td className="py-3 pr-4 text-[#6F6257]">{log.model || "未记录"}</td>
                    <td className="py-3 pr-4 text-[#6F6257]">{log.duration_ms} ms</td>
                    <td className="py-3 pr-4">
                      <Badge variant={log.success ? "success" : "danger"}>{log.success ? "成功" : `失败 ${log.status_code ?? ""}`}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(data.apiLogs?.logs ?? []).length === 0 ? <EmptyText>暂无模型调用日志。</EmptyText> : null}
        </CardContent>
      </Card>
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

function EmptyText({ children }: Readonly<{ children: ReactNode }>) {
  return <p className="rounded-2xl border border-dashed border-[#E7E0D4] bg-[#FAF9F5] p-4 text-sm text-[#6F6257]">{children}</p>;
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

function getOperationLabel(operation: string): string {
  const labels: Record<string, string> = {
    embedding: "向量检索",
    patient_response: "标准化病人",
    chat_completion: "对话模型",
    skill_candidate: "Skill 生成",
    procedure_result: "检查模拟",
  };
  return labels[operation] ?? (operation || "未记录");
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

function getApprovalReviewText(review: TrainingSkillApprovalAgentReview | undefined): string {
  if (!review) {
    return "暂无审批 Agent 记录。";
  }
  const parts = [
    review.decision ? `结论：${review.decision}` : "",
    review.revision_status ? `修改：${review.revision_status}` : "",
    review.regression_status ? `回归：${review.regression_status}` : "",
    review.changed_fields?.length ? `调整字段：${review.changed_fields.join("、")}` : "",
  ].filter(Boolean);
  return parts.join("；") || "审批 Agent 已记录，但暂无摘要。";
}
