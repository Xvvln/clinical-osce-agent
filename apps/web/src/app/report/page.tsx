"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  normalizeFeedbackReport,
  type EvidenceGraphSummary,
  type ExplanationSourceItem,
  type FeedbackReport,
  type FeedbackReportPayload,
  type KnowledgeRecommendationItem,
  type LlmReasoningFeedbackItem,
  type RubricScoreItem,
  type SourceReferenceItem,
} from "./report-model";

type DimensionInsight = Readonly<{
  key: string;
  label: string;
  score: number;
  maxScore: number;
  percent: number;
}>;

type RadarPoint = Readonly<{
  x: number;
  y: number;
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

type ExplanationChainDisplayItem = Readonly<{
  reference: string;
  title: string;
  sourceType: string;
}>;

type BackendMessage = Readonly<{
  role: "student" | "patient" | "coach" | string;
  content: string;
}>;

type BackendPhysicalExamOption = Readonly<{
  exam_code: string;
  exam_name_cn: string;
  result: string;
}>;

type BackendAuxiliaryTestOption = Readonly<{
  test_code: string;
  test_name_cn: string;
  result: string;
}>;

type BackendSession = Readonly<{
  session_id: string;
  messages: readonly BackendMessage[];
  requested_exams: readonly string[];
  requested_tests: readonly string[];
  physical_exam_options: readonly BackendPhysicalExamOption[];
  auxiliary_test_options: readonly BackendAuxiliaryTestOption[];
}>;

type BackendProcedureResult = Readonly<{
  id: string;
  label: string;
  result: string;
}>;

const scoreDimensionLabels: Readonly<Record<string, string>> = {
  history_taking: "问诊",
  physical_exam: "查体",
  auxiliary_test: "辅助检查",
  main_diagnosis: "主诊断",
  differential_diagnosis: "鉴别诊断",
  reasoning: "推理链",
};

const REPORT_BRAND_COLOR = "var(--brand)";
const REPORT_BRAND_SCORE_TRACK_COLOR = "color-mix(in srgb, var(--brand) 12%, transparent)";
const REPORT_BRAND_GRID_OPACITY = 0.16;
const REPORT_BRAND_FILL_OPACITY = 0.22;

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

function getScoreStatus(score: number): string {
  if (score >= 80) {
    return "表现优秀";
  }

  if (score >= 60) {
    return "基本达标";
  }

  return "继续训练";
}

function getRadarPoint(index: number, total: number, percent: number): RadarPoint {
  const angle = (-90 + (360 * index) / total) * (Math.PI / 180);
  const radius = 42 * (Math.min(percent, 100) / 100);

  return {
    x: 50 + Math.cos(angle) * radius,
    y: 50 + Math.sin(angle) * radius,
  };
}

function formatRadarPoint(point: RadarPoint): string {
  return `${point.x.toFixed(2)},${point.y.toFixed(2)}`;
}

function getRadarPolygonPoints(items: readonly DimensionInsight[], percent: number): string {
  return items.map((_, index) => formatRadarPoint(getRadarPoint(index, items.length, percent))).join(" ");
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

function getRecommendationKindLabel(reference: string): string {
  if (reference.startsWith("case:")) {
    return "下一病例训练";
  }

  if (reference.startsWith("knowledge:")) {
    return "知识点复习";
  }

  if (reference.startsWith("rubric:")) {
    return "评分补强点";
  }

  return "学习建议";
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

function getExplanationKindLabel(kind: string): string {
  if (kind === "strength") {
    return "优势项";
  }
  if (kind === "reasoning_error") {
    return "推理问题";
  }
  if (kind === "llm_reasoning_feedback") {
    return "语义评分解释";
  }
  return "反馈解释";
}

function getExplanationSourceDisplayItems(
  sourceReferenceItems: readonly SourceReferenceItem[],
  sourceReferences: readonly string[],
): readonly ExplanationChainDisplayItem[] {
  return sourceReferences.map((reference) => {
    const sourceItem = sourceReferenceItems.find((item) => item.reference === reference);
    return {
      reference,
      title: sourceItem?.title ?? getSourceReferenceLabel(reference),
      sourceType: sourceItem?.source_type ?? getSourceReferenceGroupKey(reference),
    };
  });
}

function getBackendMessageLabel(message: BackendMessage): string {
  if (message.role === "student") {
    return "学生";
  }

  if (message.role === "coach") {
    return message.content.includes("本系统仅用于 OSCE 教学模拟训练") ? "安全边界" : "过程提示";
  }

  return "标准化病人";
}

function buildBackendProcedureResults(session: BackendSession | null): readonly BackendProcedureResult[] {
  if (!session) {
    return [];
  }

  const examResults = session.requested_exams.map((examCode) => {
    const exam = session.physical_exam_options.find((option) => option.exam_code === examCode);
    return {
      id: `exam:${examCode}`,
      label: `查体：${exam?.exam_name_cn ?? examCode}`,
      result: exam?.result ?? "后端 session 未保存该查体结果。",
    };
  });

  const testResults = session.requested_tests.map((testCode) => {
    const test = session.auxiliary_test_options.find((option) => option.test_code === testCode);
    return {
      id: `test:${testCode}`,
      label: `检查：${test?.test_name_cn ?? testCode}`,
      result: test?.result ?? "后端 session 未保存该辅助检查结果。",
    };
  });

  return [...examResults, ...testResults];
}

async function requestJson<TResponse>(path: string): Promise<TResponse> {
  const response = await fetch(path, {
    credentials: "same-origin",
    method: "GET",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return (await response.json()) as TResponse;
}

export default function ReportPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [report, setReport] = useState<FeedbackReport | null>(null);
  const [backendSession, setBackendSession] = useState<BackendSession | null>(null);
  const [statusText, setStatusText] = useState("正在读取评分报告...");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [shareStatusText, setShareStatusText] = useState<string | null>(null);

  async function handleCopyReportLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setShareStatusText("已复制报告链接。");
    } catch {
      setShareStatusText("复制失败，请手动复制地址栏链接。");
    }
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const nextSessionId = params.get("session_id");
    setSessionId(nextSessionId);

    if (!nextSessionId) {
      setStatusText("缺少 session_id，无法读取评分报告。");
      return;
    }

    let isMounted = true;

    async function loadReport() {
      try {
        const [nextReport, nextSession] = await Promise.all([
          requestJson<FeedbackReportPayload>(`/api/me/sessions/${nextSessionId}/report`),
          requestJson<BackendSession>(`/api/me/sessions/${nextSessionId}`),
        ]);
        if (!isMounted) {
          return;
        }

        setReport(normalizeFeedbackReport(nextReport));
        setBackendSession(nextSession);
        setStatusText("已读取评分报告和后端训练快照。");
        setErrorText(null);
      } catch (error) {
        if (!isMounted) {
          return;
        }

        setStatusText("评分报告读取失败，请确认后端仍在运行且会话已经提交诊断。");
        setErrorText(error instanceof Error ? error.message : "读取评分报告失败。");
      }
    }

    loadReport();

    return () => {
      isMounted = false;
    };
  }, []);

  const dimensionMaxScores = useMemo(() => getDimensionMaxScoresFromRubricScores(report?.rubric_scores), [report?.rubric_scores]);
  const dimensions = useMemo<readonly DimensionInsight[]>(
    () =>
      Object.entries(report?.dimension_scores ?? {}).map(([key, score]) => {
        const maxScore = dimensionMaxScores[key] ?? 100;
        return {
          key,
          label: scoreDimensionLabels[key] ?? key,
          score,
          maxScore,
          percent: getScorePercent(score, maxScore),
        };
      }),
    [dimensionMaxScores, report?.dimension_scores],
  );

  const sortedDimensions = useMemo(
    () => [...dimensions].sort((first, second) => second.percent - first.percent),
    [dimensions],
  );

  const strongestDimension = sortedDimensions[0] ?? null;
  const weakestDimension = sortedDimensions[sortedDimensions.length - 1] ?? null;
  const sourceReferenceGroups = useMemo(
    () => groupSourceReferences(report?.source_reference_items ?? [], report?.source_references ?? []),
    [report?.source_reference_items, report?.source_references],
  );
  const backendProcedureResults = useMemo(() => buildBackendProcedureResults(backendSession), [backendSession]);
  const totalPercent = report ? getScorePercent(report.total_score, 100) : 0;
  const scoreBackground = `conic-gradient(${REPORT_BRAND_COLOR} ${totalPercent * 3.6}deg, ${REPORT_BRAND_SCORE_TRACK_COLOR} 0deg)`;
  const workbenchHref = sessionId ? `/?session_id=${sessionId}` : "/";

  return (
    <main className="min-h-screen bg-muted/40 px-4 py-6 text-foreground">
      <div className="mx-auto flex max-w-7xl flex-col gap-4">
        <header className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                Clinical OSCE Agent
              </p>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight">评分报告</h1>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                独立报告页用于集中展示总分、维度雷达、强弱项摘要、训练建议和来源引用。
              </p>
            </div>
            <div className="flex flex-col items-stretch gap-2 sm:items-end">
              <div className="flex flex-col gap-2 sm:flex-row">
                <button
                  className="rounded-md border border-brand bg-brand px-4 py-2 text-sm font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover"
                  onClick={handleCopyReportLink}
                  type="button"
                >
                  复制报告链接
                </button>
                <Link
                  className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium whitespace-nowrap shadow-xs transition hover:bg-accent"
                  href={workbenchHref}
                >
                  返回工作台
                </Link>
              </div>
              {shareStatusText ? <p className="text-xs text-muted-foreground">{shareStatusText}</p> : null}
            </div>
          </div>
        </header>

        <section className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
          <aside className="space-y-4">
            <div className="rounded-2xl border border-brand/20 bg-brand/5 p-5 shadow-xs">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-semibold">OSCE 训练总分</p>
                <span className="rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
                  {report ? getScoreStatus(report.total_score) : "待读取"}
                </span>
              </div>
              {report ? (
                <>
                  <div className="mx-auto mt-6 flex size-44 items-center justify-center rounded-full p-3" style={{ background: scoreBackground }}>
                    <div className="flex size-full flex-col items-center justify-center rounded-full bg-background text-brand shadow-inner">
                      <span className="text-5xl font-semibold leading-none">{report.total_score}</span>
                      <span className="mt-1 text-xs font-medium text-muted-foreground">/ 100</span>
                    </div>
                  </div>
                  <p className="mt-5 text-sm leading-6 text-muted-foreground">{report.feedback_summary}</p>
                </>
              ) : (
                <p className="mt-3 text-sm leading-6 text-muted-foreground">{statusText}</p>
              )}
            </div>

            <div className="rounded-2xl border border-border bg-background p-5 shadow-xs">
              <p className="text-sm font-semibold">报告上下文</p>
              <dl className="mt-3 space-y-3 text-sm">
                <div>
                  <dt className="text-xs text-muted-foreground">Session</dt>
                  <dd className="mt-1 break-all font-medium">{sessionId ?? "未提供"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">病例</dt>
                  <dd className="mt-1 font-medium">{report?.case_id ?? "待读取"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">使用边界</dt>
                  <dd className="mt-1 leading-6 text-muted-foreground">仅用于 OSCE 教学复盘，不提供真实诊断或治疗建议。</dd>
                </div>
              </dl>
            </div>

            {report ? (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                <InsightCard label="优势维度" title={strongestDimension?.label ?? "暂无"} detail={strongestDimension ? `${strongestDimension.percent}% 达成` : "暂无维度数据"} />
                <InsightCard label="优先补强" title={weakestDimension?.label ?? "暂无"} detail={weakestDimension ? `${weakestDimension.percent}% 达成` : "暂无维度数据"} />
              </div>
            ) : null}
          </aside>

          <section className="space-y-4">
            {errorText ? (
              <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-700">{errorText}</div>
            ) : null}

            <div className="rounded-2xl border border-border bg-background p-5 shadow-xs">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold">维度图表</h2>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">用雷达雏形和进度条同时展示各 rubric 维度表现。</p>
                </div>
                <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
                  {report ? "已生成" : "待读取"}
                </span>
              </div>

              {dimensions.length > 0 ? (
                <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(260px,0.85fr)_minmax(0,1fr)]">
                  <div className="rounded-2xl border border-border bg-muted/30 p-4">
                    <div className="mx-auto max-w-sm">
                      <svg aria-label="维度雷达图" className="h-72 w-full" role="img" viewBox="0 0 100 100">
                        {[25, 50, 75, 100].map((level) => (
                          <polygon
                            fill="none"
                            key={level}
                            points={getRadarPolygonPoints(dimensions, level)}
                            stroke={REPORT_BRAND_COLOR}
                            strokeOpacity={REPORT_BRAND_GRID_OPACITY}
                            strokeWidth="0.6"
                          />
                        ))}
                        {dimensions.map((item, index) => {
                          const outerPoint = getRadarPoint(index, dimensions.length, 100);
                          const labelPoint = getRadarPoint(index, dimensions.length, 115);
                          return (
                            <g key={item.key}>
                              <line
                                stroke={REPORT_BRAND_COLOR}
                                strokeOpacity={REPORT_BRAND_GRID_OPACITY}
                                strokeWidth="0.5"
                                x1="50"
                                x2={outerPoint.x}
                                y1="50"
                                y2={outerPoint.y}
                              />
                              <text
                                className="fill-muted-foreground text-[4px]"
                                dominantBaseline="middle"
                                textAnchor="middle"
                                x={labelPoint.x}
                                y={labelPoint.y}
                              >
                                {item.label}
                              </text>
                            </g>
                          );
                        })}
                        <polygon
                          fill={REPORT_BRAND_COLOR}
                          fillOpacity={REPORT_BRAND_FILL_OPACITY}
                          points={dimensions.map((item, index) => formatRadarPoint(getRadarPoint(index, dimensions.length, item.percent))).join(" ")}
                          stroke={REPORT_BRAND_COLOR}
                          strokeLinejoin="round"
                          strokeWidth="1.2"
                        />
                        {dimensions.map((item, index) => {
                          const point = getRadarPoint(index, dimensions.length, item.percent);
                          return <circle cx={point.x} cy={point.y} fill={REPORT_BRAND_COLOR} key={item.key} r="1.4" />;
                        })}
                      </svg>
                    </div>
                  </div>

                  <div className="grid content-start gap-3">
                    {dimensions.map((item) => (
                      <div className="rounded-xl border border-border bg-muted/40 p-4" key={item.key}>
                        <div className="flex items-center justify-between gap-2 text-sm">
                          <span className="font-medium">{item.label}</span>
                          <span className="text-muted-foreground">
                            {item.score} / {item.maxScore} 分
                          </span>
                        </div>
                        <div className="mt-3 h-2 overflow-hidden rounded-full bg-background">
                          <div className="h-full rounded-full bg-brand" style={{ width: `${item.percent}%` }} />
                        </div>
                        <p className="mt-2 text-xs text-muted-foreground">完成度 {item.percent}%</p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="mt-5 rounded-xl border border-dashed border-border bg-muted/30 p-4 text-sm leading-6 text-muted-foreground">
                  {statusText}
                </p>
              )}
            </div>

            <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold">原始对话记录</h2>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    从后端训练 session 读取医患对话、教练提示和已返回的查体/检查结果。
                  </p>
                </div>
                <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
                  {backendSession ? `${backendSession.messages.length} 条` : "待读取"}
                </span>
              </div>
              <div className="mt-4 space-y-4">
                {backendSession?.messages.length ? (
                  <div className="space-y-3">
                    {backendSession?.messages.map((message, index) => (
                      <article
                        className={[
                          "rounded-xl border px-3 py-2 text-sm leading-6",
                          message.role === "student"
                            ? "border-brand/20 bg-brand/10 text-brand"
                            : "border-border bg-muted/50 text-muted-foreground",
                        ].join(" ")}
                        key={`${message.role}-${index}-${message.content}`}
                      >
                        <p className="text-xs font-medium text-foreground">{getBackendMessageLabel(message)}</p>
                        <p className="mt-1 whitespace-pre-wrap">{message.content}</p>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className="rounded-xl border border-dashed border-border bg-muted/30 p-4 text-sm leading-6 text-muted-foreground">
                    后端 session 暂无原始对话记录。
                  </p>
                )}
                <div className="rounded-xl border border-dashed border-border bg-muted/30 p-3">
                  <h3 className="text-xs font-semibold text-foreground">查体与检查结果</h3>
                  {backendProcedureResults.length > 0 ? (
                    <div className="mt-2 space-y-2">
                      {backendProcedureResults.map((result) => (
                        <article className="rounded-lg bg-background px-3 py-2 text-xs leading-5 text-muted-foreground" key={result.id}>
                          <p className="font-medium text-foreground">{result.label}</p>
                          <p className="mt-1 whitespace-pre-wrap">{result.result}</p>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">后端 session 暂无查体或辅助检查结果。</p>
                  )}
                </div>
              </div>
            </section>

            {report ? (
              <div className="grid gap-4 xl:grid-cols-2">
                <ReportList title="已完成亮点" items={report.strengths} />
                <ReportList title="推理问题" items={report.reasoning_errors} />
                <ReportList title="下一轮训练重点" items={report.next_recommendations} />
                <KnowledgeRecommendations items={report.knowledge_recommendations} />
                <LlmReasoningFeedback items={report.llm_reasoning_feedback} />
                <DefenseEvidenceChainSection explanationItems={report.explanation_source_items} sourceReferenceItems={report.source_reference_items} />
                <EvidenceGraphSummarySection summary={report.evidence_graph_summary} />
                <SourceReferenceGroups groups={sourceReferenceGroups} />
              </div>
            ) : null}
          </section>
        </section>
      </div>
    </main>
  );
}

function InsightCard({
  label,
  title,
  detail,
}: Readonly<{
  label: string;
  title: string;
  detail: string;
}>) {
  return (
    <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-2 text-lg font-semibold text-brand">{title}</p>
      <p className="mt-1 text-sm leading-6 text-muted-foreground">{detail}</p>
    </section>
  );
}

function ReportList({
  title,
  items,
}: Readonly<{
  title: string;
  items: readonly string[];
}>) {
  return (
    <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
      <h2 className="text-sm font-semibold">{title}</h2>
      {items.length > 0 ? (
        <ul className="mt-3 space-y-2 text-sm leading-6 text-muted-foreground">
          {items.map((item) => (
            <li className="rounded-lg bg-muted/60 px-3 py-2" key={item}>
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm leading-6 text-muted-foreground">暂无内容。</p>
      )}
    </section>
  );
}

function KnowledgeRecommendations({ items }: Readonly<{ items: readonly KnowledgeRecommendationItem[] }>) {
  return (
    <section className="rounded-2xl border border-brand/20 bg-background p-5 shadow-xs xl:col-span-2">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">学习推荐与下一病例</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            根据本轮漏项检索 rubric、知识点和病例库，推荐复习重点与下一轮训练方向。
          </p>
        </div>
        <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
          {items.length} 项
        </span>
      </div>
      {items.length > 0 ? (
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {items.map((item) => (
            <article className="rounded-xl border border-border bg-muted/40 p-4" key={item.reference}>
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-sm font-semibold">{item.title}</h3>
                <span className="shrink-0 rounded-full bg-background px-2.5 py-1 text-xs font-medium text-brand">
                  {getRecommendationKindLabel(item.reference)}
                </span>
              </div>
              <p className="mt-2 text-xs font-mono text-muted-foreground">{item.reference}</p>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">{item.reason}</p>
            </article>
          ))}
        </div>
      ) : (
        <p className="mt-3 rounded-xl border border-dashed border-border bg-muted/30 p-4 text-sm leading-6 text-muted-foreground">
          当前报告暂无学习推荐。完成评分后，系统会根据漏项和病例库生成复习重点。
        </p>
      )}
    </section>
  );
}

function LlmReasoningFeedback({ items }: Readonly<{ items: readonly LlmReasoningFeedbackItem[] }>) {
  return (
    <section className="rounded-2xl border border-brand/20 bg-brand/5 p-5 shadow-xs xl:col-span-2">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">AI 临床推理评价</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            大模型只依据本轮已披露事实和 rubric 证据评价学生推理表达，不生成病例外医学事实。
          </p>
        </div>
        <span className="rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
          {items.length} 项
        </span>
      </div>
      {items.length > 0 ? (
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {items.map((item) => (
            <article className="rounded-xl border border-border bg-background/90 p-4" key={item.rubric_item_id}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold">{item.description}</h3>
                  <p className="mt-1 text-xs font-mono text-muted-foreground">{item.rubric_item_id}</p>
                </div>
                <span className="rounded-full bg-brand px-3 py-1 text-xs font-semibold text-white">
                  {item.score} / {item.max_score}
                </span>
              </div>
              <p className="mt-3 rounded-lg bg-muted/60 px-3 py-2 text-sm leading-6 text-muted-foreground">
                {item.rationale}
              </p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <EvidenceList title="已覆盖证据" items={item.covered_evidence} />
                <EvidenceList title="缺失证据" items={item.missing_evidence} />
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="mt-3 rounded-xl border border-dashed border-border bg-background/70 p-4 text-sm leading-6 text-muted-foreground">
          当前报告暂无 LLM 推理评分结果。开启模型评分或使用包含 llm_rubric 的 rubric 后会显示。
        </p>
      )}
    </section>
  );
}

function DefenseEvidenceChainSection({
  explanationItems,
  sourceReferenceItems,
}: Readonly<{
  explanationItems: readonly ExplanationSourceItem[];
  sourceReferenceItems: readonly SourceReferenceItem[];
}>) {
  return (
    <section className="rounded-2xl border border-border bg-background p-5 shadow-xs xl:col-span-2">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold">评分项 → 证据 → 来源</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            将优势项、推理问题和语义评分解释绑定回 rubric 与本轮证据，只用于答辩复盘和可追溯展示，不参与评分裁判。
          </p>
        </div>
        <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
          {explanationItems.length} 条链路
        </span>
      </div>
      {explanationItems.length > 0 ? (
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {explanationItems.map((item, index) => {
            const rubricReferences = item.source_references.filter((reference) => reference.startsWith("rubric:"));
            const evidenceReferences = item.source_references.filter((reference) => reference.startsWith("evidence:"));
            const sourceItems = getExplanationSourceDisplayItems(sourceReferenceItems, item.source_references);
            return (
              <article className="rounded-xl border border-border bg-muted/35 p-4" key={`${item.kind}-${item.rubric_item_id}-${index}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="rounded-full bg-background px-2.5 py-1 text-xs font-medium text-brand">
                    {getExplanationKindLabel(item.kind)}
                  </span>
                  <span className="break-all font-mono text-[11px] text-muted-foreground">{item.rubric_item_id}</span>
                </div>
                <p className="mt-3 text-sm leading-6 text-foreground">{item.text}</p>
                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  <TraceColumn title="评分项" items={rubricReferences} emptyText="未绑定 rubric 来源" />
                  <TraceColumn title="训练证据" items={evidenceReferences} emptyText="暂无直接证据引用" />
                  <div>
                    <h3 className="text-xs font-semibold text-foreground">来源</h3>
                    <ul className="mt-2 space-y-1">
                      {sourceItems.map((sourceItem) => (
                        <li className="rounded-md bg-background px-2 py-1 text-[11px] leading-5 text-muted-foreground" key={`${item.kind}-${sourceItem.reference}`}>
                          <span className="font-medium text-foreground">{sourceItem.title}</span>
                          <span className="mt-1 block break-all font-mono">{sourceItem.reference}</span>
                          <span className="mt-1 block">类型：{sourceItem.sourceType}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <p className="mt-3 rounded-xl border border-dashed border-border bg-muted/30 p-4 text-sm leading-6 text-muted-foreground">
          当前报告暂无逐条解释来源链。旧报告仍可通过来源引用分组查看基本依据。
        </p>
      )}
    </section>
  );
}

function TraceColumn({ title, items, emptyText }: Readonly<{ title: string; items: readonly string[]; emptyText: string }>) {
  return (
    <div>
      <h3 className="text-xs font-semibold text-foreground">{title}</h3>
      {items.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {items.map((item) => (
            <li className="rounded-md bg-background px-2 py-1 font-mono text-[11px] leading-5 break-all text-muted-foreground" key={item}>
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-xs leading-5 text-muted-foreground">{emptyText}</p>
      )}
    </div>
  );
}

function EvidenceList({ title, items }: Readonly<{ title: string; items: readonly string[] }>) {
  return (
    <div>
      <h4 className="text-xs font-semibold text-foreground">{title}</h4>
      {items.length > 0 ? (
        <ul className="mt-2 space-y-1 text-xs leading-5 text-muted-foreground">
          {items.map((item) => (
            <li className="rounded-md bg-muted/60 px-2 py-1 font-mono" key={item}>
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-xs leading-5 text-muted-foreground">无。</p>
      )}
    </div>
  );
}

function EvidenceGraphSummarySection({ summary }: Readonly<{ summary: EvidenceGraphSummary | null }>) {
  const coveragePercent = summary ? Math.round(summary.coverage_ratio * 100) : 0;

  return (
    <section className="rounded-2xl border border-brand/20 bg-brand/5 p-5 shadow-xs xl:col-span-2">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold">证据图谱覆盖</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            证据图谱仅用于复盘已收集和缺失的训练证据，不参与诊断裁判或评分。
          </p>
        </div>
        <span className="rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
          {summary ? `${summary.covered_evidence_node_count} / ${summary.total_evidence_node_count} · ${coveragePercent}%` : "暂无"}
        </span>
      </div>
      {summary && summary.total_evidence_node_count > 0 ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <EvidenceGraphNodeList title="已收集证据节点" nodes={summary.covered_evidence_nodes} />
          <EvidenceGraphNodeList title="缺失证据节点" nodes={summary.missing_evidence_nodes} />
          <EvidenceGraphEdgeList title="已连通证据链" edges={summary.covered_edges} />
          <EvidenceGraphEdgeList title="待补齐证据链" edges={summary.missing_edges} />
        </div>
      ) : (
        <p className="mt-3 rounded-xl border border-dashed border-border bg-background/70 p-4 text-sm leading-6 text-muted-foreground">
          当前病例暂无可展示的证据图谱覆盖数据。
        </p>
      )}
    </section>
  );
}

function EvidenceGraphNodeList({
  title,
  nodes,
}: Readonly<{
  title: string;
  nodes: EvidenceGraphSummary["covered_evidence_nodes"];
}>) {
  return (
    <div className="rounded-xl border border-border bg-background/90 p-4">
      <h3 className="text-xs font-semibold text-foreground">{title}</h3>
      {nodes.length > 0 ? (
        <ul className="mt-3 space-y-2 text-xs leading-5 text-muted-foreground">
          {nodes.map((node) => (
            <li className="rounded-lg bg-muted/60 px-3 py-2" key={node.node_id}>
              <p className="font-medium text-foreground">{node.label}</p>
              <p className="mt-1 break-all font-mono">{node.node_id} · {node.source_id}</p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-xs leading-5 text-muted-foreground">无。</p>
      )}
    </div>
  );
}

function EvidenceGraphEdgeList({
  title,
  edges,
}: Readonly<{
  title: string;
  edges: EvidenceGraphSummary["covered_edges"];
}>) {
  return (
    <div className="rounded-xl border border-border bg-background/90 p-4">
      <h3 className="text-xs font-semibold text-foreground">{title}</h3>
      {edges.length > 0 ? (
        <ul className="mt-3 space-y-2 text-xs leading-5 text-muted-foreground">
          {edges.map((edge) => (
            <li className="rounded-lg bg-muted/60 px-3 py-2" key={`${edge.from_node}-${edge.to_node}-${edge.relation}`}>
              <p className="font-medium text-foreground">{edge.from_label} → {edge.to_label}</p>
              <p className="mt-1 break-all font-mono">{edge.from_node} / {edge.relation} / {edge.to_node}</p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-xs leading-5 text-muted-foreground">无。</p>
      )}
    </div>
  );
}

function SourceReferenceGroups({ groups }: Readonly<{ groups: readonly SourceReferenceGroup[] }>) {
  return (
    <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">来源引用</h2>
        <Link className="text-xs font-medium text-brand hover:underline" href="/sources">
          查看说明
        </Link>
      </div>
      {groups.length > 0 ? (
        <div className="mt-3 space-y-3 text-sm leading-6 text-muted-foreground">
          {groups.map((group) => (
            <article className="rounded-xl bg-muted/60 p-3" key={group.key}>
              <h3 className="text-sm font-semibold text-foreground">{group.title}</h3>
              <p className="mt-1 text-xs leading-5">{group.description}</p>
              <ul className="mt-3 space-y-2">
                {group.references.map((item) => {
                  const metadataText = getSourceReferenceMetadataText(item.metadata);
                  return (
                    <li className="rounded-lg bg-background/80 px-3 py-2 text-xs" key={item.reference}>
                      <p className="font-medium text-foreground">{item.title}</p>
                      <p className="mt-1 break-all font-mono text-muted-foreground">{item.reference}</p>
                      {metadataText ? <p className="mt-1 break-all text-muted-foreground">{metadataText}</p> : null}
                    </li>
                  );
                })}
              </ul>
            </article>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-sm leading-6 text-muted-foreground">暂无来源引用。</p>
      )}
    </section>
  );
}
