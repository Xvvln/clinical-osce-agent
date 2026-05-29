"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  normalizeFeedbackReport,
  type AiReflectionReview,
  type EvidenceGraphSummary,
  type ExplanationSourceItem,
  type FeedbackReport,
  type FeedbackReportPayload,
  type KnowledgeRecommendationItem,
  type LlmReasoningFeedbackItem,
  type PersonalTrainingSkillCandidate,
  type ProcedureSimulationAuditItem,
  type ReportCoverageMapItem,
  type ReportCoverageMapPayload,
  type RubricScoreItem,
  type SourceReferenceItem,
  type TeacherAnalysisContext,
  type TeacherReasoningTraceSummary,
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
  case_id?: string;
  case_title?: string;
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

type RequestJsonOptions = Readonly<{
  timeoutMs?: number;
}>;

type ReportSectionId =
  | "overview"
  | "reflection"
  | "personal_skill"
  | "dimensions"
  | "feedback"
  | "recommendations"
  | "conversation"
  | "evidence";

type ReportSection = Readonly<{
  id: ReportSectionId;
  label: string;
  eyebrow: string;
  targetId: string;
}>;

type ApprovalAgentChangedFieldDisplay = Readonly<{
  label: string;
  summary: string;
  explanation: string;
  before: string;
  after: string;
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
const REPORT_SECTION_ACTIVATION_OFFSET_PX = 96;
const REPORT_REQUEST_TIMEOUT_MS = 45_000;
const PERSONAL_SKILL_POLL_INTERVAL_MS = 3_500;
const PERSONAL_SKILL_NOTICE_TIMEOUT_MS = 7_000;
const sectionHeadingClassName = "text-2xl font-semibold tracking-tight";

const reportSections: readonly ReportSection[] = [
  { id: "overview", label: "总览", eyebrow: "分数与上下文", targetId: "report-overview" },
  { id: "reflection", label: "复盘", eyebrow: "教师点评", targetId: "report-reflection" },
  { id: "personal_skill", label: "Skill", eyebrow: "个人策略", targetId: "report-personal-skill" },
  { id: "dimensions", label: "图表", eyebrow: "rubric 维度", targetId: "report-dimensions" },
  { id: "feedback", label: "结论", eyebrow: "本轮问题", targetId: "report-feedback" },
  { id: "conversation", label: "对话", eyebrow: "训练过程", targetId: "report-conversation" },
  { id: "recommendations", label: "推荐", eyebrow: "下一病例", targetId: "report-recommendations" },
  { id: "evidence", label: "依据", eyebrow: "折叠来源", targetId: "report-evidence" },
];

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

  return "需要补强";
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

function getAiReflectionStatusLabel(status: string): string {
  if (status === "generated") {
    return "已生成";
  }
  if (status === "not_ready") {
    return "待完整训练";
  }
  if (status === "legacy_report") {
    return "历史报告";
  }
  return status;
}

function getPersonalSkillStatusLabel(status: string): string {
  if (status === "approved") {
    return "已自动启用";
  }
  if (status === "not_complete") {
    return "待完成训练";
  }
  if (status === "generation_pending") {
    return "后台生成中";
  }
  if (status === "blocked_by_regression") {
    return "回归阻塞";
  }
  if (status === "legacy_report") {
    return "历史报告";
  }
  return status;
}

function getPersonalSkillCompletionNoticeText(status: string): string | null {
  if (status === "approved") {
    return "个人训练 Skill 已生成，报告内容已自动刷新。";
  }
  if (status === "blocked_by_regression") {
    return "个人训练 Skill 已完成审核，但未进入训练库，报告内容已自动刷新。";
  }
  if (status === "generation_failed") {
    return "个人训练 Skill 生成失败，报告内容已自动刷新，可稍后重试。";
  }
  return null;
}

function createTrainingPointLabelResolver(report: FeedbackReport): (itemId: string) => string {
  const labelById = new Map<string, string>();
  const addLabel = (itemId: string | undefined, label: string | undefined) => {
    const normalizedLabel = normalizeTrainingPointLabel(label);
    if (!itemId || !normalizedLabel) {
      return;
    }
    for (const key of getTrainingPointLookupKeys(itemId)) {
      if (!labelById.has(key)) {
        labelById.set(key, normalizedLabel);
      }
    }
  };

  Object.entries(report.rubric_scores).forEach(([rubricItemId, rubricScore]) => {
    addLabel(rubricItemId, rubricScore.description);
  });
  collectCoverageMapLabels(report.training_progress_snapshot?.coverage_map, labelById);
  report.llm_reasoning_feedback.forEach((feedbackItem) => {
    addLabel(feedbackItem.rubric_item_id, feedbackItem.description);
  });
  report.knowledge_recommendations.forEach((recommendation) => {
    addLabel(recommendation.reference, recommendation.title);
  });

  return (itemId: string) => {
    for (const key of getTrainingPointLookupKeys(itemId)) {
      const label = labelById.get(key);
      if (label) {
        return label;
      }
    }
    return formatTrainingPointIdentifier(itemId);
  };
}

function collectCoverageMapLabels(coverageMap: ReportCoverageMapPayload | null | undefined, labelById: Map<string, string>): void {
  if (!coverageMap) {
    return;
  }
  const addCoverageItem = (item: ReportCoverageMapItem) => {
    for (const key of getTrainingPointLookupKeys(item.id)) {
      if (!labelById.has(key)) {
        labelById.set(key, normalizeTrainingPointLabel(item.label) ?? formatTrainingPointIdentifier(item.id));
      }
    }
  };
  coverageMap.history.forEach(addCoverageItem);
  coverageMap.physical_exam.forEach(addCoverageItem);
  coverageMap.auxiliary_test.forEach(addCoverageItem);
  coverageMap.reasoning.forEach(addCoverageItem);
}

function getTrainingPointLookupKeys(itemId: string): readonly string[] {
  const rawItemId = itemId.trim();
  const withoutRubricPrefix = rawItemId.replace(/^rubric:[^.]+\.item\./, "");
  const withoutReferencePrefix = withoutRubricPrefix.includes(":") ? withoutRubricPrefix.split(":").at(-1) ?? withoutRubricPrefix : withoutRubricPrefix;
  const lastSegment = withoutReferencePrefix.split(/[.:]/).at(-1) ?? withoutReferencePrefix;
  const underscoreNormalized = withoutReferencePrefix.replace(/[:.]/g, "_");
  return Array.from(new Set([rawItemId, withoutRubricPrefix, withoutReferencePrefix, underscoreNormalized, lastSegment].filter(Boolean)));
}

function normalizeTrainingPointLabel(label: string | undefined): string | null {
  const normalizedLabel = label?.trim();
  if (!normalizedLabel) {
    return null;
  }
  return normalizedLabel
    .replace(/^追问/, "")
    .replace(/^请求/, "")
    .replace(/^申请/, "")
    .replace(/：已完成。$/, "")
    .replace(/：评分轨迹未找到足够证据。$/, "")
    .trim();
}

function formatTrainingPointIdentifier(itemId: string): string {
  const lastSegment = getTrainingPointLookupKeys(itemId).at(-1) ?? itemId;
  return lastSegment.replace(/_/g, " ");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatUnknownValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "无";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.length > 0 ? value.map((item) => formatUnknownValue(item)).join("、") : "无";
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function getApprovalFieldLabel(field: string): string {
  const labels: Readonly<Record<string, string>> = {
    title: "标题",
    description: "说明",
    suggested_strategy: "教学策略",
    teaching_action_plan: "训练动作计划",
  };
  return labels[field] ?? field;
}

function getApprovalFieldSummary(field: string): string {
  const summaries: Readonly<Record<string, string>> = {
    title: "调整 Skill 标题，避免标题里直接出现答案或不适合学生端展示的措辞。",
    description: "清理 Skill 说明，让它只描述训练问题和教学目标。",
    suggested_strategy: "清理教学策略，并补充不得泄露标准答案或隐藏事实的边界。",
    teaching_action_plan: "把策略拆成 Coach 可执行动作，供后续训练提示和复盘调用。",
  };
  return summaries[field] ?? "审批 Agent 调整了这个字段，让候选 Skill 更适合教学使用。";
}

function getApprovalFieldExplanation(field: string): string {
  const explanations: Readonly<Record<string, string>> = {
    title: "标题会出现在学生端和管理员端，所以审批 Agent 会删掉可能泄露答案或过度医疗化的表述。",
    description: "说明用于解释这个 Skill 要训练什么，应该聚焦学习行为，不能写病例隐藏信息、治疗方案或标准答案。",
    suggested_strategy: "教学策略会进入后续 Coach 上下文，因此审批 Agent 会把它限制在提示方式、训练步骤和复盘方法内。",
    teaching_action_plan: "这是系统内部给 Coach 使用的执行计划，不是新的医学事实；它只说明何时提示、如何复盘和围绕哪些训练点提醒。",
  };
  return explanations[field] ?? "审批 Agent 只允许修改教学表达和训练策略，不允许修改病例事实、rubric 或标准诊断。";
}

function getApprovalActionTypeLabel(actionType: string): string {
  const labels: Readonly<Record<string, string>> = {
    hint_ladder: "分层提示",
    reflection_prompt: "训练后复盘",
  };
  return labels[actionType] ?? actionType.replace(/_/g, " ");
}

function formatApprovalActionPlan(value: unknown): string {
  if (!Array.isArray(value) || value.length === 0) {
    return "无";
  }

  const actionLabels = value
    .map((action) => isRecord(action) && typeof action.action_type === "string" ? getApprovalActionTypeLabel(action.action_type) : "")
    .filter(Boolean);
  const uniqueActionLabels = Array.from(new Set(actionLabels));
  const actionSummary = uniqueActionLabels.length > 0 ? uniqueActionLabels.join("、") : "教学提示动作";
  return `${value.length} 个动作：${actionSummary}`;
}

function formatApprovalFieldValue(field: string, value: unknown): string {
  if (field === "teaching_action_plan") {
    return formatApprovalActionPlan(value);
  }
  return formatUnknownValue(value);
}

function getApprovalAgentChangedFieldDisplay(item: unknown): ApprovalAgentChangedFieldDisplay {
  if (!isRecord(item)) {
    const value = formatUnknownValue(item);
    return {
      label: "修改项",
      summary: "审批 Agent 调整了候选 Skill 的一项内容。",
      explanation: "原始修改记录不是标准字段对象，页面保留其文本，方便管理员追溯。",
      before: "无",
      after: value,
    };
  }

  const field = typeof item.field === "string" ? item.field : "field";
  return {
    label: getApprovalFieldLabel(field),
    summary: getApprovalFieldSummary(field),
    explanation: getApprovalFieldExplanation(field),
    before: formatApprovalFieldValue(field, item.before),
    after: formatApprovalFieldValue(field, item.after),
  };
}

function formatApprovalAgentChangedField(item: unknown): string {
  const display = getApprovalAgentChangedFieldDisplay(item);
  return `${display.label}：${display.summary}`;
}

function formatApprovalAgentIssue(issue: unknown): string {
  if (typeof issue === "string") {
    return issue;
  }
  if (!isRecord(issue)) {
    return formatUnknownValue(issue);
  }
  const message = issue.message ?? issue.reason ?? issue.detail ?? issue.id ?? issue.code;
  return formatUnknownValue(message ?? issue);
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

async function readResponseErrorMessage(response: Response): Promise<string> {
  const responseText = await response.text();
  if (!responseText) {
    return response.statusText || "请求失败。";
  }

  try {
    const parsedBody = JSON.parse(responseText) as { detail?: unknown; message?: unknown; error?: unknown };
    const detail = parsedBody.detail ?? parsedBody.message ?? parsedBody.error;
    if (typeof detail === "string" && detail.trim()) {
      return detail.trim();
    }
  } catch {
    return responseText;
  }

  return responseText;
}

function formatRequestErrorMessage(error: unknown): string {
  if (error instanceof DOMException && error.name === "AbortError") {
    return "报告读取超时，请稍后从训练记录重新打开。";
  }

  const rawMessage = error instanceof Error ? error.message : "读取评分报告失败。";
  if (/模型服务调用失败|HTTP 429|RESOURCE_EXHAUSTED|quota/i.test(rawMessage)) {
    return `${rawMessage}\n\n模型服务暂时不可用或配额不足，本次报告可以稍后重新打开读取。`;
  }

  return rawMessage;
}

async function requestJson<TResponse>(path: string, options: RequestJsonOptions = {}): Promise<TResponse> {
  const controller = options.timeoutMs ? new AbortController() : null;
  const timeoutId = controller && options.timeoutMs
    ? window.setTimeout(() => controller.abort(), options.timeoutMs)
    : null;

  try {
    const response = await fetch(path, {
      credentials: "same-origin",
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
      signal: controller?.signal,
    });

    if (!response.ok) {
      const errorMessage = await readResponseErrorMessage(response);
      throw new Error(`HTTP ${response.status}：${errorMessage}`);
    }

    return (await response.json()) as TResponse;
  } finally {
    if (timeoutId !== null) {
      window.clearTimeout(timeoutId);
    }
  }
}

function ReportSectionNavigator({
  activeSectionId,
  isCollapsed,
  onSectionSelect,
  onToggle,
}: Readonly<{
  activeSectionId: ReportSectionId;
  isCollapsed: boolean;
  onSectionSelect: (sectionId: ReportSectionId) => void;
  onToggle: () => void;
}>) {
  return (
    <aside className="scroll-mt-6 xl:sticky xl:top-6 xl:self-start">
      <div className="rounded-[28px] border border-white/70 bg-background/75 p-2 shadow-[0_18px_50px_rgb(73_49_34_/_0.12)] backdrop-blur-xl xl:max-h-[calc(100vh-3rem)] xl:overflow-y-auto report-card-scrollbar">
        <div className={["flex items-start gap-2 px-3 pt-2", isCollapsed ? "justify-center xl:px-1" : "justify-between"].join(" ")}>
          <div className={isCollapsed ? "sr-only" : ""}>
            <p className="text-xs font-semibold text-foreground">报告目录</p>
            <p className="mt-1 hidden text-[11px] leading-4 text-muted-foreground xl:block">快速跳转长报告小节</p>
          </div>
          <button
            aria-expanded={!isCollapsed}
            aria-label={isCollapsed ? "展开评分报告目录" : "收起评分报告目录"}
            className="flex size-8 shrink-0 items-center justify-center rounded-full border border-border/70 bg-background/80 text-sm font-semibold text-muted-foreground shadow-xs transition hover:border-brand/25 hover:bg-brand/10 hover:text-brand"
            onClick={onToggle}
            type="button"
          >
            <span aria-hidden="true">{isCollapsed ? "›" : "‹"}</span>
          </button>
        </div>
        <nav aria-label="评分报告章节导航" className="mt-2 flex gap-2 overflow-x-auto pb-1 report-card-scrollbar xl:grid xl:overflow-visible xl:pb-0">
          {reportSections.map((section) => {
            const isActive = activeSectionId === section.id;
            return (
              <a
                className={[
                  "min-w-fit rounded-2xl text-sm transition whitespace-nowrap",
                  isCollapsed ? "px-2 py-2 text-center" : "px-3 py-2 text-left",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand",
                  isActive
                    ? "border border-brand/25 bg-brand/10 text-brand shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--brand)_18%,transparent)]"
                    : "border border-border/70 bg-background/70 text-foreground hover:bg-muted/80",
                ].join(" ")}
                href={`#${section.targetId}`}
                key={section.id}
                onClick={() => onSectionSelect(section.id)}
                title={`${section.label}：${section.eyebrow}`}
              >
                <span className="font-semibold">{section.label}</span>
                {isCollapsed ? null : (
                  <span className={["ml-2 text-[11px] xl:ml-0 xl:mt-0.5 xl:block", isActive ? "text-brand/70" : "text-muted-foreground"].join(" ")}>
                    {section.eyebrow}
                  </span>
                )}
              </a>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}

export default function ReportPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [report, setReport] = useState<FeedbackReport | null>(null);
  const [backendSession, setBackendSession] = useState<BackendSession | null>(null);
  const [statusText, setStatusText] = useState("正在读取评分报告...");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [shareStatusText, setShareStatusText] = useState<string | null>(null);
  const [personalSkillNoticeText, setPersonalSkillNoticeText] = useState<string | null>(null);
  const [activeSectionId, setActiveSectionId] = useState<ReportSectionId>("overview");
  const [isReportNavigatorCollapsed, setIsReportNavigatorCollapsed] = useState(false);

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
          requestJson<FeedbackReportPayload>(`/api/me/sessions/${nextSessionId}/report`, { timeoutMs: REPORT_REQUEST_TIMEOUT_MS }),
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
        setErrorText(formatRequestErrorMessage(error));
      }
    }

    loadReport();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (!sessionId || report?.personal_skill_candidate.status !== "generation_pending") {
      return;
    }

    let isCancelled = false;
    let pollTimer: number | null = null;

    async function pollPersonalSkillCandidate() {
      try {
        const nextReportPayload = await requestJson<FeedbackReportPayload>(`/api/me/sessions/${sessionId}/report`, {
          timeoutMs: REPORT_REQUEST_TIMEOUT_MS,
        });
        if (isCancelled) {
          return;
        }

        const nextReport = normalizeFeedbackReport(nextReportPayload);
        setReport(nextReport);
        if (nextReport.personal_skill_candidate.status !== "generation_pending") {
          const noticeText = getPersonalSkillCompletionNoticeText(nextReport.personal_skill_candidate.status);
          if (noticeText) {
            setPersonalSkillNoticeText(noticeText);
          }
          return;
        }
      } catch {
        if (isCancelled) {
          return;
        }
      }

      pollTimer = window.setTimeout(pollPersonalSkillCandidate, PERSONAL_SKILL_POLL_INTERVAL_MS);
    }

    pollTimer = window.setTimeout(pollPersonalSkillCandidate, PERSONAL_SKILL_POLL_INTERVAL_MS);

    return () => {
      isCancelled = true;
      if (pollTimer) {
        window.clearTimeout(pollTimer);
      }
    };
  }, [sessionId, report?.personal_skill_candidate.status]);

  useEffect(() => {
    if (!personalSkillNoticeText) {
      return;
    }

    const dismissTimer = window.setTimeout(() => {
      setPersonalSkillNoticeText(null);
    }, PERSONAL_SKILL_NOTICE_TIMEOUT_MS);

    return () => {
      window.clearTimeout(dismissTimer);
    };
  }, [personalSkillNoticeText]);

  useEffect(() => {
    function updateActiveSection() {
      let nextActiveSectionId: ReportSectionId = "overview";
      let closestDistance = Number.POSITIVE_INFINITY;

      if (window.scrollY > 0 && window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
        nextActiveSectionId = reportSections[reportSections.length - 1].id;
        setActiveSectionId((currentSectionId) => (currentSectionId === nextActiveSectionId ? currentSectionId : nextActiveSectionId));
        return;
      }

      const viewportAnchor = REPORT_SECTION_ACTIVATION_OFFSET_PX;

      for (const section of reportSections) {
        const element = document.getElementById(section.targetId);
        if (!element) {
          continue;
        }
        const elementRect = element.getBoundingClientRect();
        if (elementRect.bottom < 0 || elementRect.top > window.innerHeight) {
          continue;
        }
        const distance = Math.abs(elementRect.top - viewportAnchor);
        if (distance < closestDistance) {
          closestDistance = distance;
          nextActiveSectionId = section.id;
        }
      }

      setActiveSectionId((currentSectionId) => (currentSectionId === nextActiveSectionId ? currentSectionId : nextActiveSectionId));
    }

    updateActiveSection();
    window.addEventListener("scroll", updateActiveSection, { passive: true });

    return () => {
      window.removeEventListener("scroll", updateActiveSection);
    };
  }, [report]);

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
  const trainingPointLabelResolver = useMemo(() => report ? createTrainingPointLabelResolver(report) : formatTrainingPointIdentifier, [report]);
  const backendProcedureResults = useMemo(() => buildBackendProcedureResults(backendSession), [backendSession]);
  const totalPercent = report ? getScorePercent(report.total_score, 100) : 0;
  const scoreBackground = `conic-gradient(${REPORT_BRAND_COLOR} ${totalPercent * 3.6}deg, ${REPORT_BRAND_SCORE_TRACK_COLOR} 0deg)`;
  const workbenchHref = "/";
  const reportLayoutClassName = ["grid gap-4 transition-[grid-template-columns] duration-200", isReportNavigatorCollapsed ? "xl:grid-cols-[76px_minmax(0,1fr)]" : "xl:grid-cols-[240px_minmax(0,1fr)]"].join(" ");

  return (
    <main className="min-h-screen bg-muted/40 px-4 py-6 text-foreground">
      {personalSkillNoticeText ? (
        <div
          className="fixed right-5 bottom-5 z-50 max-w-sm rounded-2xl border border-brand/20 bg-background/95 p-4 text-sm leading-6 text-foreground shadow-[0_18px_60px_rgba(0,0,0,0.14)] backdrop-blur"
          role="status"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="font-semibold text-brand">个人 Skill 已更新</p>
              <p className="mt-1 text-muted-foreground">{personalSkillNoticeText}</p>
            </div>
            <button
              aria-label="关闭个人 Skill 提示"
              className="rounded-full border border-border bg-muted/40 px-2 py-0.5 text-xs text-muted-foreground transition hover:bg-muted"
              onClick={() => setPersonalSkillNoticeText(null)}
              type="button"
            >
              关闭
            </button>
          </div>
        </div>
      ) : null}
      <div className="mx-auto flex max-w-7xl flex-col gap-4">
        <header className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                临境 OSCE 智能体（TraceOSCE）
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

        <section className={reportLayoutClassName}>
          <ReportSectionNavigator
            activeSectionId={activeSectionId}
            isCollapsed={isReportNavigatorCollapsed}
            onSectionSelect={setActiveSectionId}
            onToggle={() => setIsReportNavigatorCollapsed((currentValue) => !currentValue)}
          />

          <section className="min-w-0 space-y-4">
            <section className="scroll-mt-6 grid gap-4 lg:grid-cols-[minmax(0,1.05fr)_minmax(280px,0.95fr)]" id="report-overview">
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

              <div className="grid gap-4">
                <div className="rounded-2xl border border-border bg-background p-5 shadow-xs">
                  <p className="text-sm font-semibold">报告上下文</p>
                  <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-3 lg:grid-cols-1">
                    <div>
                      <dt className="text-xs text-muted-foreground">Session</dt>
                      <dd className="mt-1 break-all font-medium">{sessionId ?? "未提供"}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">病例</dt>
                      <dd className="mt-1 font-medium">{backendSession?.case_title ?? report?.case_id ?? "待读取"}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">使用边界</dt>
                      <dd className="mt-1 leading-6 text-muted-foreground">仅用于 OSCE 教学复盘，不提供真实诊断或治疗建议。</dd>
                    </div>
                  </dl>
                </div>

                {report ? (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <InsightCard label="优势维度" title={strongestDimension?.label ?? "暂无"} detail={strongestDimension ? `${strongestDimension.percent}% 达成` : "暂无维度数据"} />
                    <InsightCard label="优先补强" title={weakestDimension?.label ?? "暂无"} detail={weakestDimension ? `${weakestDimension.percent}% 达成` : "暂无维度数据"} />
                  </div>
                ) : null}
              </div>
            </section>
            {errorText ? (
              <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-700" role="alert">
                <p className="font-semibold">报告读取失败</p>
                <p className="mt-2 whitespace-pre-line">{errorText}</p>
              </div>
            ) : null}
            {report ? (
              <AiReflectionReviewSection review={report.ai_reflection_review} trainingPointLabelResolver={trainingPointLabelResolver} />
            ) : null}
            {report ? (
              <PersonalTrainingSkillSection candidate={report.personal_skill_candidate} trainingPointLabelResolver={trainingPointLabelResolver} />
            ) : null}
            <DimensionChartSection dimensions={dimensions} report={report} statusText={statusText} />
            {report ? <StudentReportSummary report={report} sectionId="report-feedback" /> : null}

            <ConversationDetailsSection backendProcedureResults={backendProcedureResults} backendSession={backendSession} />
            {report ? <CaseRecommendations items={report.knowledge_recommendations} /> : null}
            {report ? (
              <TraceabilityDetailsSection
                explanationItems={report.explanation_source_items}
                llmReasoningItems={report.llm_reasoning_feedback}
                procedureSimulationAuditItems={report.procedure_simulation_audit_items}
                sourceReferenceItems={report.source_reference_items}
                evidenceGraphSummary={report.evidence_graph_summary}
                sourceReferenceGroups={sourceReferenceGroups}
              />
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

function DimensionChartSection({
  dimensions,
  report,
  statusText,
}: Readonly<{
  dimensions: readonly DimensionInsight[];
  report: FeedbackReport | null;
  statusText: string;
}>) {
  return (
    <div className="scroll-mt-6 rounded-2xl border border-border bg-background p-5 shadow-xs" id="report-dimensions">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className={sectionHeadingClassName}>维度图表</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">用雷达雏形和进度条同时展示各 rubric 维度表现。</p>
        </div>
        <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
          {report ? "已生成" : "待读取"}
        </span>
      </div>

      {dimensions.length > 0 ? (
        <div className="mt-5 grid items-start gap-5 lg:grid-cols-[minmax(260px,0.85fr)_minmax(0,1fr)]">
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

          <div className="grid max-h-80 content-start gap-3 overflow-y-auto pr-1 report-card-scrollbar">
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
  );
}

function ConversationDetailsSection({
  backendProcedureResults,
  backendSession,
}: Readonly<{
  backendProcedureResults: readonly BackendProcedureResult[];
  backendSession: BackendSession | null;
}>) {
  return (
    <details className="scroll-mt-6 rounded-2xl border border-border bg-background p-5 shadow-xs" id="report-conversation">
      <summary className="flex cursor-pointer list-none items-start justify-between gap-3">
        <div>
              <h2 className={sectionHeadingClassName}>原始对话记录</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            从后端训练 session 读取医患对话、教练提示和已返回的查体/检查结果；默认折叠，可展开查看完整训练过程。
          </p>
        </div>
        <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
          {backendSession ? `${backendSession.messages.length} 条` : "待读取"}
        </span>
      </summary>
      <div className="mt-4 max-h-[34rem] space-y-4 overflow-y-auto pr-1 report-card-scrollbar">
        {backendSession?.messages.length ? (
          <div className="space-y-3">
            {backendSession?.messages.map((message, index) => (
              <article
                className={[
                  "rounded-xl border px-3 py-2 text-sm leading-6",
                  message.role === "student" ? "border-brand/20 bg-brand/10 text-brand" : "border-border bg-muted/50 text-muted-foreground",
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
    </details>
  );
}

function StudentReportSummary({ report, sectionId }: Readonly<{ report: FeedbackReport; sectionId: string }>) {
  const coverageMap = report.training_progress_snapshot?.coverage_map;
  const coverageStats = coverageMap ? getCoverageMapStats(coverageMap) : null;
  return (
    <section className="scroll-mt-6 rounded-2xl border border-border bg-background p-5 shadow-xs xl:col-span-2" id={sectionId}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className={sectionHeadingClassName}>本轮结论</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            用素材覆盖图谱复盘本轮训练，详细评分依据放在下方折叠区。
          </p>
        </div>
        <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
          {coverageStats ? `素材覆盖 ${coverageStats.covered}/${coverageStats.total}` : `${report.missed_items.length} 个待补强点`}
        </span>
      </div>
      {coverageMap ? (
        <ReportCoverageMapOverview coverageMap={coverageMap} />
      ) : (
        <p className="mt-4 rounded-xl border border-dashed border-border bg-muted/30 p-4 text-sm leading-6 text-muted-foreground">
          当前报告缺少素材覆盖快照，建议重新生成报告后查看本轮问诊、查体、辅助检查和推理证据覆盖情况。
        </p>
      )}
    </section>
  );
}

function ReportCoverageMapOverview({ coverageMap }: Readonly<{ coverageMap: ReportCoverageMapPayload }>) {
  const groups = [
    { title: "问诊线索", items: coverageMap.history },
    { title: "查体项目", items: coverageMap.physical_exam },
    { title: "辅助检查", items: coverageMap.auxiliary_test },
    { title: "推理证据", items: coverageMap.reasoning },
  ];

  return (
    <div className="mt-4 grid gap-3 lg:grid-cols-2">
      {groups.map((group) => (
        <ReportCoverageMapGroup items={group.items} key={group.title} title={group.title} />
      ))}
    </div>
  );
}

function ReportCoverageMapGroup({
  title,
  items,
}: Readonly<{
  title: string;
  items: readonly ReportCoverageMapItem[];
}>) {
  const coveredCount = items.filter((item) => item.status === "covered").length;
  const visibleItems = items.slice(0, 6);
  const hiddenCount = Math.max(0, items.length - visibleItems.length);

  return (
    <section className="rounded-xl border border-border bg-muted/20 p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">{title}</h3>
        <span className="rounded-full border border-border bg-background px-2.5 py-1 text-[11px] text-muted-foreground">
          {coveredCount}/{items.length}
        </span>
      </div>
      <div className="mt-3 grid gap-2">
        {visibleItems.length > 0 ? (
          visibleItems.map((item) => (
            <div className="rounded-lg border border-border bg-background px-3 py-2 text-xs leading-5" key={item.id}>
              <div className="flex items-start justify-between gap-3">
                <span className="min-w-0 text-foreground">{item.label}</span>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${
                    item.status === "covered" ? "bg-[#EEF6EF] text-[#236146]" : "bg-muted text-muted-foreground"
                  }`}
                >
                  {item.status === "covered" ? "已覆盖" : "未覆盖"}
                </span>
              </div>
            </div>
          ))
        ) : (
          <p className="rounded-lg border border-dashed border-border bg-background px-3 py-2 text-xs text-muted-foreground">
            暂无素材项。
          </p>
        )}
      </div>
      {hiddenCount > 0 ? <p className="mt-2 text-xs text-muted-foreground">另有 {hiddenCount} 项在详细评分依据中查看。</p> : null}
    </section>
  );
}

function hasTeacherAnalysisContext(context: TeacherAnalysisContext): boolean {
  return Boolean(
    context.analysis_summary
    || context.student_thinking_hypothesis
    || Object.keys(context.clinical_thinking_profile).length > 0
    || Object.keys(context.skill_memory_focus).length > 0
    || context.source_anchor_labels.length > 0,
  );
}

function stringifyTeacherAnalysisValue(value: unknown): string {
  if (typeof value === "string") {
    return value.trim();
  }
  if (Array.isArray(value)) {
    return value.map((item) => stringifyTeacherAnalysisValue(item)).filter(Boolean).join("、");
  }
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, nestedValue]) => {
        const nestedText = stringifyTeacherAnalysisValue(nestedValue);
        return nestedText ? `${formatTeacherAnalysisKey(key)}：${nestedText}` : "";
      })
      .filter(Boolean)
      .join("；");
  }
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}

function formatTeacherAnalysisKey(key: string): string {
  const labels: Readonly<Record<string, string>> = {
    problem_representation: "问题表征",
    hypothesis_management: "假设管理",
    verification_strategy: "验证策略",
    differential_reasoning: "鉴别诊断",
    metacognitive_next_move: "下一步思维动作",
    next_teacher_move: "下一步教学动作",
    problem_pattern_summary: "问题模式",
    recommended_intervention: "建议干预",
  };
  return labels[key] ?? key.replaceAll("_", " ");
}

function getCoverageMapStats(coverageMap: ReportCoverageMapPayload) {
  const items = [
    ...coverageMap.history,
    ...coverageMap.physical_exam,
    ...coverageMap.auxiliary_test,
    ...coverageMap.reasoning,
  ];
  return {
    total: items.length,
    covered: items.filter((item) => item.status === "covered").length,
  };
}

function AiReflectionReviewSection({
  review,
  trainingPointLabelResolver,
}: Readonly<{
  review: AiReflectionReview;
  trainingPointLabelResolver: (itemId: string) => string;
}>) {
  const overallComment = review.overall_comment || review.summary;
  const strengthsReview = review.strengths_review.length > 0 ? review.strengths_review : [];
  const majorIssues = review.major_issues;
  const nextPracticePlan = review.next_practice_plan.length > 0 ? review.next_practice_plan : review.next_focus ? [review.next_focus] : [];
  return (
    <section className="scroll-mt-6 rounded-2xl border border-brand/20 bg-background p-5 shadow-xs xl:col-span-2" id="report-reflection">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className={sectionHeadingClassName}>教师复盘</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            围绕当前病例和本轮证据链生成老师式点评，重点回答问题在哪、为什么要补、下一轮怎么练。
          </p>
        </div>
        <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
          {getAiReflectionStatusLabel(review.status)}
        </span>
      </div>
      <div className="mt-4 rounded-xl border border-brand/15 bg-brand/5 p-4">
        <h3 className="text-sm font-semibold text-foreground">总体判断</h3>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">{overallComment}</p>
      </div>
      <TeacherAnalysisContextSection context={review.teacher_analysis_context} />
      {review.teacher_coaching_review.length > 0 ? (
        <div className="mt-3 rounded-xl border border-border bg-muted/20 p-4">
          <h3 className="text-sm font-semibold text-foreground">老师带你重走一遍临床思路</h3>
          <div className="mt-3 grid gap-3">
            {review.teacher_coaching_review.map((section, index) => (
              <article className="rounded-lg border border-border bg-background p-3" key={section.section_id}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full border border-brand/20 bg-brand/10 text-xs font-semibold text-brand">
                    {index + 1}
                  </span>
                  <h4 className="text-sm font-semibold text-foreground">{section.title}</h4>
                </div>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">{section.teacher_comment}</p>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <div className="rounded-lg bg-muted/30 p-3">
                    <p className="text-xs font-semibold text-foreground">为什么这样看</p>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">{section.why_it_matters}</p>
                  </div>
                  <div className="rounded-lg bg-muted/30 p-3">
                    <p className="text-xs font-semibold text-foreground">下一步动作</p>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">{section.next_move}</p>
                  </div>
                </div>
                {section.evidence_labels.length > 0 ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {section.evidence_labels.map((label) => (
                      <span className="rounded-full border border-border bg-muted/40 px-2.5 py-1 text-[11px] text-muted-foreground" key={label}>
                        {label}
                      </span>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        </div>
      ) : null}
      {strengthsReview.length > 0 ? (
        <div className="mt-3 rounded-xl border border-border bg-muted/20 p-4">
          <h3 className="text-sm font-semibold text-foreground">本轮可以保留的做法</h3>
          <ul className="mt-2 grid gap-2 text-sm leading-6 text-muted-foreground">
            {strengthsReview.map((strength) => (
              <li className="rounded-lg bg-background px-3 py-2" key={strength}>
                {strength}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {majorIssues.length > 0 ? (
        <div className="mt-3">
          <h3 className="text-sm font-semibold text-foreground">老师指出的问题</h3>
          <div className="mt-2 grid gap-3">
            {majorIssues.map((issue) => (
              <article className="rounded-xl border border-border bg-muted/20 p-4" key={issue.title}>
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <h4 className="text-base font-semibold text-foreground">{issue.title}</h4>
                  {issue.linked_items.length > 0 ? (
                    <span className="w-fit rounded-full border border-border bg-background px-2.5 py-1 text-[11px] text-muted-foreground">
                      {issue.linked_items.length} 个相关训练点
                    </span>
                  ) : null}
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <div>
                    <p className="text-xs font-semibold text-foreground">本轮表现</p>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">{issue.observed_behavior}</p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-foreground">为什么重要</p>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">{issue.why_it_matters}</p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-foreground">正确做法</p>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">{issue.correct_approach}</p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-foreground">下一轮具体练法</p>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">{issue.next_action}</p>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </div>
      ) : review.teacher_feedback ? (
        <div className="mt-3 rounded-xl border border-border bg-muted/25 p-3">
          <h3 className="text-sm font-semibold">教师点评</h3>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">{review.teacher_feedback}</p>
        </div>
      ) : null}
      {review.reasoning_chain_review || nextPracticePlan.length > 0 ? (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {review.reasoning_chain_review ? (
            <div className="rounded-xl border border-border bg-muted/25 p-4">
              <h3 className="text-sm font-semibold">推理链点评</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{review.reasoning_chain_review}</p>
            </div>
          ) : null}
          <div className="rounded-xl border border-border bg-muted/25 p-4">
            <h3 className="text-sm font-semibold">下一轮练习步骤</h3>
            {nextPracticePlan.length > 0 ? (
              <ol className="mt-2 grid gap-2 text-sm leading-6 text-muted-foreground">
                {nextPracticePlan.map((item, index) => (
                  <li className="rounded-lg bg-background px-3 py-2" key={`${item}-${index}`}>
                    {index + 1}. {item}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="mt-2 text-sm leading-6 text-muted-foreground">暂无下一轮练习步骤。</p>
            )}
          </div>
        </div>
      ) : null}
      <TeacherReasoningTraceSummarySection summary={review.reasoning_trace_summary} />
      {review.mistake_patterns.length > 0 ? (
        <div className="mt-3">
          <h3 className="text-xs font-semibold">相关训练点</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {review.mistake_patterns.map((pattern) => (
              <span className="rounded-full border border-border bg-muted/40 px-2.5 py-1 text-[11px] text-muted-foreground" key={pattern}>
                {trainingPointLabelResolver(pattern)}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {review.teacher_note ? <p className="mt-3 rounded-xl border border-border bg-muted/20 p-3 text-xs leading-5 text-muted-foreground">{review.teacher_note}</p> : null}
      <details className="mt-3 rounded-xl border border-border bg-muted/20 p-3">
        <summary className="flex cursor-pointer list-none items-start justify-between gap-3">
          <div>
            <h3 className="text-xs font-semibold">复盘来源</h3>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              默认折叠，可展开查看教师复盘引用的结构化来源。
            </p>
          </div>
          <span className="rounded-full border border-border bg-background px-2.5 py-1 text-[11px] text-muted-foreground">
            {review.source_reference_items.length > 0 ? `${review.source_reference_items.length} 条` : "暂无"}
          </span>
        </summary>
        {review.source_reference_items.length > 0 ? (
          <ul className="mt-3 grid max-h-[28rem] gap-2 overflow-y-auto pr-1 report-card-scrollbar md:grid-cols-2">
            {review.source_reference_items.map((sourceItem) => (
              <li className="rounded-lg border border-border bg-background p-3 text-xs leading-5 text-muted-foreground" key={sourceItem.reference}>
                <span className="font-medium text-foreground">{sourceItem.title}</span>
                <span className="mt-1 block break-all font-mono">{sourceItem.reference}</span>
                <span className="mt-1 block">类型：{sourceItem.source_type}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 rounded-lg border border-dashed border-border bg-background p-3 text-sm leading-6 text-muted-foreground">
            历史报告暂无教师复盘来源链。
          </p>
        )}
      </details>
      {review.safety_note ? <p className="mt-3 text-xs leading-5 text-muted-foreground">{review.safety_note}</p> : null}
    </section>
  );
}

function TeacherAnalysisContextSection({
  context,
  title = "教师智能体分析",
}: Readonly<{
  context: TeacherAnalysisContext;
  title?: string;
}>) {
  if (!hasTeacherAnalysisContext(context)) {
    return null;
  }
  const thinkingProfileEntries = Object.entries(context.clinical_thinking_profile)
    .map(([key, value]) => [key, stringifyTeacherAnalysisValue(value)] as const)
    .filter(([, value]) => value);
  const skillMemoryFocusEntries = Object.entries(context.skill_memory_focus)
    .map(([key, value]) => [key, stringifyTeacherAnalysisValue(value)] as const)
    .filter(([, value]) => value);

  return (
    <section className="mt-3 rounded-xl border border-brand/15 bg-brand/5 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            这是 TeacherAgent 基于本轮训练材料形成的教学分析，只用于复盘和 Skill 记忆，不参与评分裁判。
          </p>
        </div>
        {context.analysis_mode ? (
          <span className="w-fit rounded-full border border-brand/20 bg-background px-2.5 py-1 text-[11px] text-brand">
            {context.analysis_mode}
          </span>
        ) : null}
      </div>

      {context.analysis_summary ? <p className="mt-3 text-sm leading-6 text-muted-foreground">{context.analysis_summary}</p> : null}
      {context.student_thinking_hypothesis ? (
        <div className="mt-3 rounded-lg border border-border bg-background p-3">
          <p className="text-xs font-semibold text-foreground">学生思维假设</p>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">{context.student_thinking_hypothesis}</p>
        </div>
      ) : null}

      {thinkingProfileEntries.length > 0 ? (
        <div className="mt-3">
          <p className="text-xs font-semibold text-foreground">临床思维画像</p>
          <div className="mt-2 grid gap-2 md:grid-cols-2">
            {thinkingProfileEntries.map(([key, value]) => (
              <article className="rounded-lg border border-border bg-background p-3 text-xs leading-5" key={key}>
                <p className="font-semibold text-foreground">{formatTeacherAnalysisKey(key)}</p>
                <p className="mt-1 text-muted-foreground">{value}</p>
              </article>
            ))}
          </div>
        </div>
      ) : null}

      {skillMemoryFocusEntries.length > 0 ? (
        <details className="mt-3 rounded-lg border border-border bg-background p-3">
          <summary className="cursor-pointer list-none text-xs font-semibold text-foreground">Skill 记忆来源</summary>
          <div className="mt-2 grid gap-2">
            {skillMemoryFocusEntries.map(([key, value]) => (
              <p className="text-xs leading-5 text-muted-foreground" key={key}>
                <span className="font-medium text-foreground">{formatTeacherAnalysisKey(key)}：</span>
                {value}
              </p>
            ))}
          </div>
        </details>
      ) : null}
    </section>
  );
}

function TeacherReasoningTraceSummarySection({ summary }: Readonly<{ summary: TeacherReasoningTraceSummary }>) {
  const hasSequenceFlags = summary.sequence_flags.length > 0;
  const hasEvidenceBreakpoints = summary.evidence_chain_breakpoints.length > 0;
  if (!hasSequenceFlags && !hasEvidenceBreakpoints) {
    return null;
  }

  return (
    <div className="mt-3 rounded-xl border border-border bg-muted/20 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-foreground">临床思维轨迹</h3>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            来自本轮训练动作顺序和证据链断点，只用于复盘，不参与评分。
          </p>
        </div>
        {summary.trace_version ? (
          <span className="w-fit rounded-full border border-border bg-background px-2.5 py-1 text-[11px] text-muted-foreground">
            {summary.trace_version}
          </span>
        ) : null}
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="rounded-lg border border-border bg-background p-3">
          <h4 className="text-xs font-semibold text-foreground">顺序问题</h4>
          {hasSequenceFlags ? (
            <ul className="mt-2 grid gap-2">
              {summary.sequence_flags.map((flag) => (
                <li className="rounded-lg bg-muted/30 px-3 py-2 text-xs leading-5 text-muted-foreground" key={flag.flag_id}>
                  <span className="font-medium text-foreground">{flag.label}</span>
                  {flag.evidence ? <span className="mt-1 block">{flag.evidence}</span> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-xs leading-5 text-muted-foreground">未识别到明显顺序跳步。</p>
          )}
        </div>
        <div className="rounded-lg border border-border bg-background p-3">
          <h4 className="text-xs font-semibold text-foreground">证据链断点</h4>
          {hasEvidenceBreakpoints ? (
            <ul className="mt-2 grid gap-2">
              {summary.evidence_chain_breakpoints.map((breakpoint) => (
                <li className="rounded-lg bg-muted/30 px-3 py-2 text-xs leading-5 text-muted-foreground" key={breakpoint.breakpoint_id}>
                  <span className="font-medium text-foreground">{breakpoint.statement}</span>
                  {breakpoint.missing_evidence_labels.length > 0 ? (
                    <span className="mt-1 block">缺少证据：{breakpoint.missing_evidence_labels.join("、")}</span>
                  ) : null}
                  {breakpoint.teacher_action ? <span className="mt-1 block">{breakpoint.teacher_action}</span> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-xs leading-5 text-muted-foreground">暂无证据链断点。</p>
          )}
        </div>
      </div>
    </div>
  );
}

function PersonalTrainingSkillSection({
  candidate,
  trainingPointLabelResolver,
}: Readonly<{
  candidate: PersonalTrainingSkillCandidate;
  trainingPointLabelResolver: (itemId: string) => string;
}>) {
  const approvalDialogue = candidate.approval_dialogue ?? [];
  return (
    <section className="scroll-mt-6 rounded-2xl border border-border bg-background p-5 shadow-xs xl:col-span-2" id="report-personal-skill">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className={sectionHeadingClassName}>个人训练 Skill</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            完整训练后生成个人级训练策略，后续同一学生的新 session 会作为针对性提示上下文。
          </p>
        </div>
        <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
          {getPersonalSkillStatusLabel(candidate.status)}
        </span>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <div className="rounded-xl border border-border bg-muted/25 p-3">
          <p className="text-xs text-muted-foreground">候选</p>
          <p className="mt-1 break-all font-mono text-[11px] text-foreground">{candidate.candidate_id ?? "尚未生成"}</p>
        </div>
        <div className="rounded-xl border border-border bg-muted/25 p-3">
          <p className="text-xs text-muted-foreground">Skill</p>
          <p className="mt-1 break-all font-mono text-[11px] text-foreground">{candidate.skill_id ?? "尚未启用"}</p>
        </div>
        <div className="rounded-xl border border-border bg-muted/25 p-3">
          <p className="text-xs text-muted-foreground">联网核查状态</p>
          <p className="mt-1 text-sm font-semibold text-foreground">{candidate.web_check_status}</p>
        </div>
      </div>
      {candidate.title ? <p className="mt-3 text-sm font-semibold text-foreground">{candidate.title}</p> : null}
      <TeacherAnalysisContextSection context={candidate.teacher_analysis_context} title="Skill 记忆来源" />
      {candidate.description || candidate.suggested_strategy ? (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <div className="rounded-xl border border-border bg-muted/25 p-3">
            <h3 className="text-xs font-semibold">候选说明</h3>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{candidate.description || "暂无候选说明。"}</p>
          </div>
          <div className="rounded-xl border border-border bg-muted/25 p-3">
            <h3 className="text-xs font-semibold">教学策略</h3>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{candidate.suggested_strategy || "暂无教学策略。"}</p>
          </div>
        </div>
      ) : null}
      {(candidate.trigger_item_ids ?? []).length > 0 ? (
        <div className="mt-3">
          <h3 className="text-xs font-semibold">关联训练点</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {candidate.trigger_item_ids?.map((triggerItemId) => (
              <span className="rounded-full border border-border bg-muted/40 px-2.5 py-1 text-xs text-muted-foreground" key={triggerItemId}>
                {trainingPointLabelResolver(triggerItemId)}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      <details className="mt-3 rounded-xl border border-border bg-muted/20 p-3">
        <summary className="flex cursor-pointer list-none items-start justify-between gap-3">
          <div>
            <h3 className="text-xs font-semibold">RAG 证据来源</h3>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              默认折叠，可展开查看 Skill 生成与审批使用的来源。
            </p>
          </div>
          <span className="rounded-full border border-border bg-background px-2.5 py-1 text-[11px] text-muted-foreground">
            {candidate.rag_evidence_items.length > 0 ? `${candidate.rag_evidence_items.length} 条` : "暂无"}
          </span>
        </summary>
        {candidate.rag_evidence_items.length > 0 ? (
          <ul className="mt-3 grid max-h-[28rem] gap-2 overflow-y-auto pr-1 report-card-scrollbar md:grid-cols-2">
            {candidate.rag_evidence_items.map((sourceItem) => (
              <li className="rounded-lg border border-border bg-background p-3 text-xs leading-5 text-muted-foreground" key={sourceItem.reference}>
                <span className="font-medium text-foreground">{sourceItem.title}</span>
                <span className="mt-1 block break-all font-mono">{sourceItem.reference}</span>
                <span className="mt-1 block">类型：{sourceItem.source_type}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 rounded-lg border border-dashed border-border bg-background p-3 text-sm leading-6 text-muted-foreground">
            暂无结构化 RAG 证据来源，或该报告为旧报告。
          </p>
        )}
      </details>
      {approvalDialogue.length > 0 ? (
        <div className="mt-3">
          <h3 className="text-xs font-semibold">审批 Agent 记录</h3>
          <div className="mt-2 grid max-h-80 gap-2 overflow-y-auto pr-1 report-card-scrollbar">
            {approvalDialogue.map((turn) => (
              <details className="rounded-lg border border-border bg-muted/25 p-3 text-xs leading-5 text-muted-foreground" key={`${turn.agent_id}-${turn.round}`}>
                <summary className="flex cursor-pointer list-none items-start justify-between gap-3">
                  <div>
                    <p className="font-medium text-foreground">
                      第 {turn.round} 轮 · {turn.agent_id} · {turn.decision} · {turn.revision_status}
                    </p>
                    <p className="mt-1">RAG 引用 {turn.rag_reference_count} 条 · 联网核查状态 {turn.web_check_status}</p>
                    <p className="mt-1">展开查看修改内容、门禁结果和问题清单。</p>
                  </div>
                  <span className="rounded-full border border-border bg-background px-2.5 py-1 text-[11px] text-muted-foreground">
                    详情
                  </span>
                </summary>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <div className="rounded-lg border border-border bg-background p-3">
                    <h4 className="text-xs font-semibold text-foreground">修改内容</h4>
                    {turn.changed_fields.length > 0 ? (
                      <ul className="mt-2 space-y-2">
                        {turn.changed_fields.map((changedField, index) => {
                          const changedFieldDisplay = getApprovalAgentChangedFieldDisplay(changedField);
                          return (
                            <li className="min-w-0 rounded-lg border border-border bg-muted/35 p-3" key={`${turn.agent_id}-${turn.round}-change-${index}`}>
                              <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
                                <p className="font-semibold text-foreground">{changedFieldDisplay.label}</p>
                                <span className="w-fit rounded-full border border-border bg-background px-2 py-0.5 text-[11px] text-muted-foreground">
                                  已整理为教学可用表达
                                </span>
                              </div>
                              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                                <span className="font-medium text-foreground">为什么改：</span>
                                {changedFieldDisplay.explanation}
                              </p>
                              <p className="mt-1 text-xs leading-5 text-muted-foreground">{changedFieldDisplay.summary}</p>
                              <div className="mt-3 grid gap-2 md:grid-cols-2">
                                <div className="min-w-0">
                                  <p className="text-[11px] font-semibold text-muted-foreground">修改前</p>
                                  <p className="mt-1 max-h-24 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-background px-2 py-1 text-xs leading-5 text-muted-foreground report-card-scrollbar [overflow-wrap:anywhere]">
                                    {changedFieldDisplay.before}
                                  </p>
                                </div>
                                <div className="min-w-0">
                                  <p className="text-[11px] font-semibold text-muted-foreground">修改后</p>
                                  <p className="mt-1 max-h-24 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-background px-2 py-1 text-xs leading-5 text-muted-foreground report-card-scrollbar [overflow-wrap:anywhere]">
                                    {changedFieldDisplay.after}
                                  </p>
                                </div>
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                    ) : (
                      <p className="mt-2">本轮未修改候选 Skill 内容。</p>
                    )}
                  </div>
                  <div className="rounded-lg border border-border bg-background p-3">
                    <h4 className="text-xs font-semibold text-foreground">门禁与问题</h4>
                    {turn.blocking_failures.length > 0 ||
                    turn.candidate_safety_violations.length > 0 ||
                    turn.candidate_context_violations.length > 0 ? (
                      <div className="mt-2 space-y-3">
                        {turn.blocking_failures.length > 0 ? (
                          <div>
                            <p className="font-semibold text-foreground">阻塞项</p>
                            <ul className="mt-1 space-y-1">
                              {turn.blocking_failures.map((issue, index) => (
                                <li className="rounded-md bg-muted/50 px-2 py-1" key={`${turn.agent_id}-${turn.round}-blocking-${index}`}>
                                  {formatApprovalAgentIssue(issue)}
                                </li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                        {turn.candidate_safety_violations.length > 0 ? (
                          <div>
                            <p className="font-semibold text-foreground">安全违规</p>
                            <ul className="mt-1 space-y-1">
                              {turn.candidate_safety_violations.map((issue, index) => (
                                <li className="rounded-md bg-muted/50 px-2 py-1" key={`${turn.agent_id}-${turn.round}-safety-${index}`}>
                                  {formatApprovalAgentIssue(issue)}
                                </li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                        {turn.candidate_context_violations.length > 0 ? (
                          <div>
                            <p className="font-semibold text-foreground">上下文泄漏</p>
                            <ul className="mt-1 space-y-1">
                              {turn.candidate_context_violations.map((issue, index) => (
                                <li className="rounded-md bg-muted/50 px-2 py-1" key={`${turn.agent_id}-${turn.round}-context-${index}`}>
                                  {formatApprovalAgentIssue(issue)}
                                </li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                      </div>
                    ) : (
                      <p className="mt-2">未发现阻塞项、安全违规或上下文泄漏问题。</p>
                    )}
                  </div>
                </div>
              </details>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function CaseRecommendations({ items }: Readonly<{ items: readonly KnowledgeRecommendationItem[] }>) {
  const caseItems = items.filter((item) => item.reference.startsWith("case:"));
  return (
    <section className="scroll-mt-6 rounded-2xl border border-brand/20 bg-background p-5 shadow-xs xl:col-span-2" id="report-recommendations">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className={sectionHeadingClassName}>推荐训练病例</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            仅展示适合下一轮对照或复训的病例；知识点和评分依据放到折叠审计区，不挤占主阅读路径。
          </p>
        </div>
        <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
          {caseItems.length} 个病例
        </span>
      </div>
      {caseItems.length > 0 ? (
        <div className="mt-4 grid max-h-[34rem] gap-3 overflow-y-auto pr-1 report-card-scrollbar md:grid-cols-2">
          {caseItems.map((item) => (
            <article className="rounded-xl border border-border bg-muted/40 p-4" key={item.reference}>
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-sm font-semibold">{item.title}</h3>
                <span className="shrink-0 rounded-full bg-background px-2.5 py-1 text-xs font-medium text-brand">
                  下一病例训练
                </span>
              </div>
              <p className="mt-2 text-xs font-mono text-muted-foreground">{item.reference}</p>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">{item.reason}</p>
            </article>
          ))}
        </div>
      ) : (
        <p className="mt-3 rounded-xl border border-dashed border-border bg-muted/30 p-4 text-sm leading-6 text-muted-foreground">
          当前病例库暂未找到适合的下一轮训练病例。病例库扩展后，这里会优先展示相似或对照训练病例。
        </p>
      )}
    </section>
  );
}

function LlmReasoningAuditSection({ items }: Readonly<{ items: readonly LlmReasoningFeedbackItem[] }>) {
  return (
    <section className="rounded-2xl border border-brand/20 bg-brand/5 p-5 shadow-xs">
      <details>
        <summary className="flex cursor-pointer list-none flex-col gap-3 rounded-xl border border-border bg-background/80 p-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className={sectionHeadingClassName}>AI 评分审计</h2>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              默认折叠，用于查看大模型 rubric 评分过程，不作为学生主阅读内容。
            </p>
          </div>
          <span className="rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
            {items.length} 项
          </span>
        </summary>
        {items.length > 0 ? (
          <div className="mt-4 grid max-h-[34rem] gap-3 overflow-y-auto pr-1 report-card-scrollbar lg:grid-cols-2">
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
      </details>
    </section>
  );
}

function ProcedureSimulationAuditSection({ items }: Readonly<{ items: readonly ProcedureSimulationAuditItem[] }>) {
  return (
    <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
      <details>
        <summary className="flex cursor-pointer list-none flex-col gap-3 rounded-xl border border-border bg-muted/30 p-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className={sectionHeadingClassName}>AI 模拟检查结果</h2>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              仅用于高级训练连续性，不进入评分；默认折叠，展开后可查看安全边界和来源上下文。
            </p>
          </div>
          <span className="rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
            {items.length} 项
          </span>
        </summary>
        {items.length > 0 ? (
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {items.map((item) => (
              <article className="rounded-xl border border-border bg-muted/35 p-4" key={item.procedure_id}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">{item.label || item.code}</h3>
                    <p className="mt-1 break-words font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
                      {item.procedure_id}
                    </p>
                  </div>
                  <span className="rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
                    {item.scoring_eligible ? "可进入评分" : "不进入评分"}
                  </span>
                </div>
                <p className="mt-3 rounded-lg bg-background px-3 py-2 text-sm leading-6 text-muted-foreground">
                  {item.result}
                </p>
                <dl className="mt-3 grid gap-3 text-xs leading-5 text-muted-foreground sm:grid-cols-2">
                  <div>
                    <dt className="font-semibold text-foreground">审批状态</dt>
                    <dd className="mt-1 break-words [overflow-wrap:anywhere]">{item.approval_status || "未记录"}</dd>
                  </div>
                  <div>
                    <dt className="font-semibold text-foreground">安全边界</dt>
                    <dd className="mt-1">{item.safety_boundary}</dd>
                  </div>
                </dl>
                <div className="mt-3 rounded-xl border border-border bg-background/80 p-3">
                  <h4 className="text-xs font-semibold text-foreground">审批 Agent 记录</h4>
                  <dl className="mt-2 grid gap-2 text-xs leading-5 text-muted-foreground sm:grid-cols-2">
                    <div>
                      <dt className="font-medium text-foreground">审核结论</dt>
                      <dd className="mt-1">{getProcedureApprovalDecisionLabel(getProcedureApprovalText(item.approval_agent_review, "decision"))}</dd>
                    </div>
                    <div>
                      <dt className="font-medium text-foreground">审核方式</dt>
                      <dd className="mt-1">{getProcedureApprovalText(item.approval_agent_review, "approval_mode")}</dd>
                    </div>
                    <div className="sm:col-span-2">
                      <dt className="font-medium text-foreground">审核理由</dt>
                      <dd className="mt-1">{getProcedureApprovalText(item.approval_agent_review, "rationale", "未记录审核理由。")}</dd>
                    </div>
                    <div className="sm:col-span-2">
                      <dt className="font-medium text-foreground">安全问题</dt>
                      <dd className="mt-1">
                        {getProcedureApprovalSafetyIssues(item.approval_agent_review).length > 0
                          ? getProcedureApprovalSafetyIssues(item.approval_agent_review).join("；")
                          : "未发现需要阻断的问题。"}
                      </dd>
                    </div>
                  </dl>
                </div>
                <div className="mt-3">
                  <h4 className="text-xs font-semibold text-foreground">来源上下文</h4>
                  {item.source_context_references.length > 0 ? (
                    <ul className="mt-2 space-y-1">
                      {item.source_context_references.map((reference) => (
                        <li
                          className="rounded-md bg-background px-2 py-1 font-mono text-[11px] leading-5 break-words text-muted-foreground [overflow-wrap:anywhere]"
                          key={`${item.procedure_id}-${reference}`}
                        >
                          {reference}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">未记录额外上下文。</p>
                  )}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className="mt-3 rounded-xl border border-dashed border-border bg-muted/30 p-4 text-sm leading-6 text-muted-foreground">
            本轮没有使用 AI 模拟查体或检查结果。
          </p>
        )}
      </details>
    </section>
  );
}

function getProcedureApprovalText(
  review: Readonly<Record<string, unknown>> | undefined,
  key: string,
  fallback = "未记录",
): string {
  const value = review?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function getProcedureApprovalDecisionLabel(decision: string): string {
  if (decision === "approved") {
    return "通过";
  }
  if (decision === "revise") {
    return "已改写后通过";
  }
  if (decision === "blocked") {
    return "已阻断";
  }
  return decision;
}

function getProcedureApprovalSafetyIssues(review: Readonly<Record<string, unknown>> | undefined): readonly string[] {
  const issues = review?.safety_issues;
  if (!Array.isArray(issues)) {
    return [];
  }
  return issues.map((item) => String(item).trim()).filter(Boolean);
}

function TraceabilityDetailsSection({
  explanationItems,
  llmReasoningItems,
  procedureSimulationAuditItems,
  sourceReferenceItems,
  evidenceGraphSummary,
  sourceReferenceGroups,
}: Readonly<{
  explanationItems: readonly ExplanationSourceItem[];
  llmReasoningItems: readonly LlmReasoningFeedbackItem[];
  procedureSimulationAuditItems: readonly ProcedureSimulationAuditItem[];
  sourceReferenceItems: readonly SourceReferenceItem[];
  evidenceGraphSummary: EvidenceGraphSummary | null;
  sourceReferenceGroups: readonly SourceReferenceGroup[];
}>) {
  return (
    <section className="scroll-mt-6 rounded-2xl border border-border bg-background p-5 shadow-xs xl:col-span-2" id="report-evidence">
      <details className="group">
        <summary className="flex cursor-pointer list-none flex-col gap-3 rounded-xl border border-border bg-muted/25 p-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className={sectionHeadingClassName}>评分依据与来源</h2>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              结构化评分依据，不是 RAG 评分裁判；默认折叠，供复盘、答辩和管理员追溯时查看。
            </p>
          </div>
          <span className="rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
            展开查看
          </span>
        </summary>
          <div className="mt-4 grid gap-4">
            <DefenseEvidenceChainSection explanationItems={explanationItems} sourceReferenceItems={sourceReferenceItems} />
            <LlmReasoningAuditSection items={llmReasoningItems} />
            <ProcedureSimulationAuditSection items={procedureSimulationAuditItems} />
            <EvidenceGraphSummarySection summary={evidenceGraphSummary} />
            <SourceReferenceGroups groups={sourceReferenceGroups} />
          </div>
      </details>
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
    <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className={sectionHeadingClassName}>结构化评分链</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            将优势项、推理问题和语义评分解释绑定回 rubric 与本轮证据；这是确定性追溯，不参与评分裁判。
          </p>
        </div>
        <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
          {explanationItems.length} 条链路
        </span>
      </div>
      {explanationItems.length > 0 ? (
        <div className="mt-4 max-h-[34rem] space-y-3 overflow-y-auto pr-1 report-card-scrollbar">
          {explanationItems.map((item, index) => {
            const rubricReferences = item.source_references.filter((reference) => reference.startsWith("rubric:"));
            const evidenceReferences = item.source_references.filter((reference) => reference.startsWith("evidence:"));
            const sourceItems = getExplanationSourceDisplayItems(sourceReferenceItems, item.source_references);
            const itemKey = `${item.kind}-${item.rubric_item_id}-${index}`;
            return (
              <article className="min-w-0 rounded-xl border border-border bg-muted/35 p-4" key={itemKey}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="rounded-full bg-background px-2.5 py-1 text-xs font-medium text-brand">
                    {getExplanationKindLabel(item.kind)}
                  </span>
                  <span className="max-w-full break-words font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]">{item.rubric_item_id}</span>
                </div>
                <p className="mt-3 text-sm leading-6 text-foreground">{item.text}</p>
                <TraceReferenceRows
                  evidenceReferences={evidenceReferences}
                  itemKey={itemKey}
                  rubricReferences={rubricReferences}
                  sourceItems={sourceItems}
                />
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

function TraceReferenceRows({
  rubricReferences,
  evidenceReferences,
  sourceItems,
  itemKey,
}: Readonly<{
  rubricReferences: readonly string[];
  evidenceReferences: readonly string[];
  sourceItems: readonly ExplanationChainDisplayItem[];
  itemKey: string;
}>) {
  return (
    <div className="mt-3 space-y-3">
      <TraceReferenceList title="评分项来源" items={rubricReferences} emptyText="未绑定 rubric 来源" />
      <TraceReferenceList title="训练证据来源" items={evidenceReferences} emptyText="暂无直接证据引用" />
      <div>
        <h3 className="text-xs font-semibold text-foreground">结构化来源</h3>
        {sourceItems.length > 0 ? (
          <ul className="mt-2 space-y-2">
            {sourceItems.map((sourceItem) => (
              <li className="min-w-0 rounded-md bg-background px-3 py-2 text-[11px] leading-5 text-muted-foreground" key={`${itemKey}-${sourceItem.reference}`}>
                <span className="font-medium text-foreground">{sourceItem.title}</span>
                <span className="mt-1 block break-words font-mono [overflow-wrap:anywhere]">{sourceItem.reference}</span>
                <span className="mt-1 block">类型：{sourceItem.sourceType}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-xs leading-5 text-muted-foreground">暂无结构化来源引用。</p>
        )}
      </div>
    </div>
  );
}

function TraceReferenceList({ title, items, emptyText }: Readonly<{ title: string; items: readonly string[]; emptyText: string }>) {
  return (
    <div>
      <h3 className="text-xs font-semibold text-foreground">{title}</h3>
      {items.length > 0 ? (
        <ul className="mt-2 space-y-2">
          {items.map((item) => (
            <li className="min-w-0 rounded-md bg-background px-3 py-2 font-mono text-[11px] leading-5 break-words text-muted-foreground [overflow-wrap:anywhere]" key={item}>
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
          <h2 className={sectionHeadingClassName}>结构化证据覆盖</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            证据图谱仅用于复盘已收集和缺失的训练证据，不参与诊断裁判或评分。
          </p>
        </div>
        <span className="rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
          {summary ? `${summary.covered_evidence_node_count} / ${summary.total_evidence_node_count} · ${coveragePercent}%` : "暂无"}
        </span>
      </div>
      {summary && summary.total_evidence_node_count > 0 ? (
        <div className="mt-4 grid max-h-[34rem] gap-4 overflow-y-auto pr-1 report-card-scrollbar lg:grid-cols-2">
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
    <section className="rounded-2xl border border-border bg-background p-5 shadow-xs xl:col-span-2">
      <div className="flex items-center justify-between gap-3">
        <h2 className={sectionHeadingClassName}>来源台账</h2>
        <Link className="text-xs font-medium text-brand hover:underline" href="/sources">
          查看说明
        </Link>
      </div>
      {groups.length > 0 ? (
        <div className="mt-3 max-h-[34rem] space-y-3 overflow-y-auto pr-1 text-sm leading-6 text-muted-foreground report-card-scrollbar">
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
