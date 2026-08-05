"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  getLearningPathTargetKey,
  type LearningPathTargetReference,
} from "./learning-path-target";

type PersistedSessionSummary = Readonly<{
  session_id: string;
  case_id: string;
  case_title: string;
  stage: string;
  stage_label: string;
  created_at: string;
  updated_at: string;
  is_completed: boolean;
  can_continue: boolean;
  has_report: boolean;
  completion_status: "in_progress" | "diagnosis_submitted" | "report_ready";
}>;

type DimensionAverage = Readonly<{
  key: string;
  label: string;
  average: number;
  average_score: number;
  average_max_score: number;
  average_percentage: number;
  sample_count: number;
}>;

type EnabledSkillSummary = Readonly<{
  skill_id: string;
  title: string;
  student_visible_summary: string;
  description: string;
  learning_action: string;
  activation_summary: string;
  source_summary: string;
  effect_status_label: string;
  scope_label: string;
  support_count: number;
  source_report_count: number;
  effect_status: string;
}>;

type SkillProfileItem = Readonly<{
  item_id: string;
  label: string;
}>;

type SkillProfileTrainingGap = Readonly<{
  gap_type: string;
  rubric_item_id: string;
  label: string;
  dimension_id: string;
  skill_type: string;
  gap_source: string;
  severity: string;
  trigger_stage: string;
  trigger_stage_label: string;
  next_training_action: string;
  success_signal: string;
  evidence_summary: string;
  missing_score: number;
  repeat_count: number;
  priority: number;
  status: string;
  status_label: string;
  is_humanistic: boolean;
}>;

type SkillProfileReasoningPattern = Readonly<{
  pattern_id: string;
  label: string;
  category?: string;
  severity?: string;
  count?: number;
}>;

type SkillProfileSequenceIssue = Readonly<{
  flag_id: string;
  label: string;
  severity: string;
  count: number;
  evidence_examples: readonly string[];
}>;

type SkillProfileEvidenceChainFocus = Readonly<{
  breakpoint_id: string;
  statement: string;
  kind: string;
  status: string;
  missing_evidence: readonly string[];
  missing_evidence_labels: readonly string[];
  teacher_action: string;
  count: number;
}>;

type SkillProfileReasoningSummary = Readonly<{
  recent_pattern_ids: readonly string[];
  recent_patterns: readonly SkillProfileReasoningPattern[];
  dominant_patterns: readonly SkillProfileReasoningPattern[];
  current_reasoning_focus: readonly SkillProfileReasoningPattern[];
  sequence_issue_counts: readonly SkillProfileSequenceIssue[];
  evidence_chain_focus: readonly SkillProfileEvidenceChainFocus[];
}>;

type SkillProfileSkillState = Readonly<{
  state: string;
  state_label: string;
  priority: number;
  trigger_item_ids: readonly string[];
  trigger_item_labels: readonly string[];
  trigger_gap_types: readonly string[];
  matched_recent_error_item_ids: readonly string[];
  matched_recent_error_items: readonly SkillProfileItem[];
  matched_recent_reasoning_patterns: readonly SkillProfileReasoningPattern[];
  matched_recent_training_gap_types: readonly string[];
  matched_recent_training_gaps: readonly Pick<SkillProfileTrainingGap, "gap_type" | "label">[];
  matched_recent_training_skill_types: readonly string[];
  effect_status: string;
  effect_status_label: string;
  selection_reason: string;
}>;

type TeachingEffectAbilityAxis = Readonly<{
  axis_id: string;
  axis_label: string;
  state: string;
  state_label: string;
  latest_count: number;
  historical_count: number;
  labels: readonly string[];
  teaching_objective: string;
}>;

type TeachingEffectObservedChange = Readonly<{
  axis_id: string;
  axis_label: string;
  direction: string;
  description: string;
}>;

type TeachingEffectSummary = Readonly<{
  status: string;
  status_label: string;
  summary: string;
  ability_axes: readonly TeachingEffectAbilityAxis[];
  observed_changes: readonly TeachingEffectObservedChange[];
  next_teaching_objectives: readonly string[];
  evidence_boundary: string;
  skill_state_counts: Readonly<Record<string, number>>;
  reasoning_focus_count: number;
}>;

type SkillProfileSummary = Readonly<{
  recent_error_item_ids: readonly string[];
  recent_error_items: readonly SkillProfileItem[];
  current_focus_item_ids: readonly string[];
  current_focus_items: readonly SkillProfileItem[];
  recent_training_gap_types: readonly string[];
  recent_training_skill_types: readonly string[];
  recent_training_gaps: readonly SkillProfileTrainingGap[];
  current_training_gaps: readonly SkillProfileTrainingGap[];
  current_humanistic_gaps: readonly SkillProfileTrainingGap[];
  humanistic_gap_summary: Readonly<{
    recent_count: number;
    current_count: number;
    top_gap_type: string;
    top_next_training_action: string;
  }>;
  reasoning_profile_summary: SkillProfileReasoningSummary;
  skill_states: Readonly<Record<string, SkillProfileSkillState>>;
  teaching_effect_summary: TeachingEffectSummary;
  last_updated_from_report_count: number;
}>;

type SkillAccumulation = Readonly<{
  status: string;
  description: string;
  enabled_skill_count: number;
  applied_skill_count: number;
  enabled_skills: readonly EnabledSkillSummary[];
}>;

type LearningPathItem = Readonly<{
  task_type: string;
  task_type_label: string;
  case_id: string;
  case_title: string;
  objective: string;
  target_rubric_items: readonly string[];
  target_rubric_item_refs?: readonly LearningPathTargetReference[];
  target_rubric_item_labels: readonly string[];
  source_report_count: number;
  source_references: readonly string[];
  source_reference_labels: readonly string[];
}>;

type CurrentUserProfilePayload = Readonly<{
  student_id: string;
  total_sessions: number;
  report_count: number;
  average_score: number;
  dimension_averages: readonly DimensionAverage[];
  strongest_dimension: DimensionAverage | null;
  weakest_dimension: DimensionAverage | null;
  next_focus: string;
  learning_path: readonly LearningPathItem[];
  recent_sessions: readonly PersistedSessionSummary[];
  skill_accumulation: SkillAccumulation;
  skill_profile_summary: SkillProfileSummary;
}>;

type CurrentUserProfileResponse = Readonly<{
  profile: CurrentUserProfilePayload;
}>;

type ProfileLoadState = "loading" | "ready" | "unauthenticated" | "empty" | "error";

type LearningProfile = Readonly<{
  totalSessions: number;
  reportCount: number;
  averageScore: number;
  dimensionAverages: readonly DimensionAverage[];
  strongestDimension: DimensionAverage | null;
  weakestDimension: DimensionAverage | null;
  nextFocus: string;
  learningPath: readonly LearningPathItem[];
  recentSessions: readonly PersistedSessionSummary[];
  skillAccumulation: SkillAccumulation;
  skillProfileSummary: SkillProfileSummary;
}>;

const EMPTY_SKILL_PROFILE_REASONING_SUMMARY: SkillProfileReasoningSummary = {
  recent_pattern_ids: [],
  recent_patterns: [],
  dominant_patterns: [],
  current_reasoning_focus: [],
  sequence_issue_counts: [],
  evidence_chain_focus: [],
};

const EMPTY_TEACHING_EFFECT_SUMMARY: TeachingEffectSummary = {
  status: "not_started",
  status_label: "尚未开始",
  summary: "完成一次完整训练并生成报告后，系统会开始观察临床思维训练效果。",
  ability_axes: [],
  observed_changes: [],
  next_teaching_objectives: ["先完成一次完整训练，形成可复盘的问诊、查体、检查和诊断轨迹。"],
  evidence_boundary: "教学效果观察只来自训练报告、临床思维轨迹和 Skill 应用痕迹；不改变病例事实、rubric、标准诊断或评分裁判，也不把小样本观察写成已证明提升。",
  skill_state_counts: {},
  reasoning_focus_count: 0,
};

const EMPTY_SKILL_PROFILE_SUMMARY: SkillProfileSummary = {
  recent_error_item_ids: [],
  recent_error_items: [],
  current_focus_item_ids: [],
  current_focus_items: [],
  recent_training_gap_types: [],
  recent_training_skill_types: [],
  recent_training_gaps: [],
  current_training_gaps: [],
  current_humanistic_gaps: [],
  humanistic_gap_summary: {
    recent_count: 0,
    current_count: 0,
    top_gap_type: "",
    top_next_training_action: "",
  },
  reasoning_profile_summary: EMPTY_SKILL_PROFILE_REASONING_SUMMARY,
  skill_states: {},
  teaching_effect_summary: EMPTY_TEACHING_EFFECT_SUMMARY,
  last_updated_from_report_count: 0,
};

const EMPTY_LEARNING_PROFILE: LearningProfile = {
  totalSessions: 0,
  reportCount: 0,
  averageScore: 0,
  dimensionAverages: [],
  strongestDimension: null,
  weakestDimension: null,
  nextFocus: "先完成一次完整训练并生成评分报告。",
  learningPath: [],
  recentSessions: [],
  skillAccumulation: {
    status: "planned",
    description: "长期 Skill 记忆会沉淀反复出现的问题模式、历史证据和干预策略；完成训练报告后开始积累。",
    enabled_skill_count: 0,
    applied_skill_count: 0,
    enabled_skills: [],
  },
  skillProfileSummary: EMPTY_SKILL_PROFILE_SUMMARY,
};

const FEATURED_SKILL_LIMIT = 5;

type CurrentPriorityIssue = Readonly<{
  id: string;
  sourceLabel: string;
  title: string;
  description: string;
  count?: number;
}>;

function formatSavedAt(savedAt: string): string {
  const date = new Date(savedAt);
  if (Number.isNaN(date.getTime())) {
    return savedAt;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

class UnauthenticatedProfileError extends Error {
  constructor() {
    super("请先登录查看近期学习画像。");
    this.name = "UnauthenticatedProfileError";
  }
}

function toLearningProfile(payload: CurrentUserProfilePayload): LearningProfile {
  return {
    totalSessions: payload.total_sessions,
    reportCount: payload.report_count,
    averageScore: payload.average_score,
    dimensionAverages: payload.dimension_averages,
    strongestDimension: payload.strongest_dimension,
    weakestDimension: payload.weakest_dimension,
    nextFocus: payload.next_focus,
    learningPath: payload.learning_path,
    recentSessions: payload.recent_sessions,
    skillAccumulation: payload.skill_accumulation,
    skillProfileSummary: normalizeSkillProfileSummary(payload.skill_profile_summary),
  };
}

function normalizeSkillProfileSummary(summary?: Partial<SkillProfileSummary>): SkillProfileSummary {
  const skillStates = Object.fromEntries(
    Object.entries(summary?.skill_states ?? {}).map(([skillId, state]) => [
      skillId,
      {
        ...state,
        trigger_gap_types: state.trigger_gap_types ?? [],
        matched_recent_error_items: state.matched_recent_error_items ?? [],
        matched_recent_reasoning_patterns: state.matched_recent_reasoning_patterns ?? [],
        matched_recent_training_gap_types: state.matched_recent_training_gap_types ?? [],
        matched_recent_training_gaps: state.matched_recent_training_gaps ?? [],
        matched_recent_training_skill_types: state.matched_recent_training_skill_types ?? [],
      },
    ]),
  );

  return {
    ...EMPTY_SKILL_PROFILE_SUMMARY,
    ...summary,
    recent_training_gap_types: summary?.recent_training_gap_types ?? [],
    recent_training_skill_types: summary?.recent_training_skill_types ?? [],
    recent_training_gaps: summary?.recent_training_gaps ?? [],
    current_training_gaps: summary?.current_training_gaps ?? [],
    current_humanistic_gaps: summary?.current_humanistic_gaps ?? [],
    humanistic_gap_summary: {
      ...EMPTY_SKILL_PROFILE_SUMMARY.humanistic_gap_summary,
      ...(summary?.humanistic_gap_summary ?? {}),
    },
    reasoning_profile_summary: {
      ...EMPTY_SKILL_PROFILE_REASONING_SUMMARY,
      ...(summary?.reasoning_profile_summary ?? {}),
    },
    teaching_effect_summary: {
      ...EMPTY_TEACHING_EFFECT_SUMMARY,
      ...(summary?.teaching_effect_summary ?? {}),
    },
    skill_states: skillStates,
  };
}

async function getCurrentUserProfile(): Promise<LearningProfile> {
  const response = await fetch("/api/me/profile", {
    credentials: "same-origin",
    method: "GET",
  });

  if (response.status === 401) {
    throw new UnauthenticatedProfileError();
  }

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `请求失败：${response.status}`);
  }

  const payload = (await response.json()) as CurrentUserProfileResponse;
  return toLearningProfile(payload.profile);
}

function getDimensionPercentageWidth(averagePercentage: number): string {
  return `${Math.max(0, Math.min(100, averagePercentage))}%`;
}

function isEmptyLearningProfile(profile: LearningProfile): boolean {
  return profile.totalSessions === 0 && profile.reportCount === 0;
}

function getCurrentPriorityIssues(summary: SkillProfileSummary): readonly CurrentPriorityIssue[] {
  const reasoningSummary = summary.reasoning_profile_summary;

  const humanisticIssues = summary.current_humanistic_gaps.slice(0, 2).map((gap) => ({
    id: `humanistic-${gap.gap_type}`,
    sourceLabel: gap.gap_source === "missed_opportunity" ? "错失机会" : "人文沟通",
    title: gap.label,
    description: `${gap.trigger_stage_label || "下一轮"}：${gap.next_training_action || gap.success_signal}`,
    count: gap.repeat_count,
  }));

  const focusIssues = summary.current_focus_items.slice(0, 2).map((item) => ({
    id: `focus-${item.item_id}`,
    sourceLabel: "近期漏项",
    title: item.label,
    description: "最近报告中仍需要补齐的训练点。",
  }));

  const evidenceIssues = reasoningSummary.evidence_chain_focus.slice(0, 2).map((focus) => ({
    id: `evidence-${focus.breakpoint_id}`,
    sourceLabel: "证据链",
    title: focus.statement,
    description:
      focus.missing_evidence_labels.length > 0
        ? `缺少证据：${focus.missing_evidence_labels.join("、")}`
        : focus.teacher_action || "需要把诊断判断和已采集证据连接起来。",
    count: focus.count,
  }));

  const sequenceIssues = reasoningSummary.sequence_issue_counts.slice(0, 2).map((issue) => ({
    id: `sequence-${issue.flag_id}`,
    sourceLabel: "顺序问题",
    title: issue.label,
    description: issue.evidence_examples[0] ?? "训练顺序需要在下一轮中优先纠偏。",
    count: issue.count,
  }));

  const reasoningIssues = reasoningSummary.current_reasoning_focus.slice(0, 2).map((pattern) => ({
    id: `reasoning-${pattern.pattern_id}`,
    sourceLabel: "思维模式",
    title: pattern.label,
    description: pattern.category ? `当前思维焦点：${pattern.category}` : "最近训练中反复出现的推理模式。",
    count: pattern.count,
  }));

  return [...humanisticIssues, ...focusIssues, ...evidenceIssues, ...sequenceIssues, ...reasoningIssues].slice(0, 5);
}

function getRankedEnabledSkills(skills: readonly EnabledSkillSummary[]): readonly EnabledSkillSummary[] {
  return [...skills].sort((left, right) => {
    const rightScore = right.support_count * 2 + right.source_report_count;
    const leftScore = left.support_count * 2 + left.source_report_count;
    if (rightScore !== leftScore) {
      return rightScore - leftScore;
    }
    return left.title.localeCompare(right.title, "zh-CN");
  });
}

function ProfileStateNotice({
  state,
  message,
}: Readonly<{
  state: ProfileLoadState;
  message: string;
}>) {
  const titleByState: Record<ProfileLoadState, string> = {
    loading: "正在读取近期学习画像",
    ready: "近期学习画像已生成",
    unauthenticated: "请先登录查看近期学习画像",
    empty: "暂无近期学习画像",
    error: "读取近期学习画像失败",
  };

  return (
    <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
      <p className="text-xs font-medium text-brand">近期学习画像</p>
      <h2 className="mt-2 text-xl font-semibold tracking-tight">{titleByState[state]}</h2>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">{message}</p>
      {state === "unauthenticated" ? (
        <Link
          className="mt-4 inline-flex rounded-md border border-brand bg-brand px-4 py-2 text-sm font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover"
          href="/"
        >
          返回工作台登录
        </Link>
      ) : null}
    </section>
  );
}

function SkillDetailRow({ label, value }: Readonly<{ label: string; value: string }>) {
  const trimmedValue = value.trim();
  if (!trimmedValue) {
    return null;
  }

  return (
    <div className="rounded-lg border border-border bg-muted/30 p-3">
      <p className="text-xs font-semibold text-muted-foreground">{label}</p>
      <p className="mt-1 text-foreground">{trimmedValue}</p>
    </div>
  );
}

function formatSkillEffectSummary(skill: EnabledSkillSummary): string {
  const sourceSummary = skill.source_summary.trim();
  const effectStatusLabel = skill.effect_status_label.trim();
  if (sourceSummary && effectStatusLabel) {
    return `${sourceSummary} 当前效果：${effectStatusLabel}。`;
  }
  if (sourceSummary) {
    return sourceSummary;
  }
  if (effectStatusLabel) {
    return `当前效果：${effectStatusLabel}。`;
  }
  return "";
}

function getSkillPreviewSummary(skill: EnabledSkillSummary): string {
  const studentVisibleSummary = skill.student_visible_summary.trim();
  if (studentVisibleSummary) {
    return studentVisibleSummary;
  }

  const description = skill.description.trim();
  if (description) {
    return description;
  }

  return "该 Skill 会作为长期教学记忆，在后续训练中按病例、阶段和近期缺口被选择性注入。";
}

function TeachingEffectSummarySection({ summary }: Readonly<{ summary: TeachingEffectSummary }>) {
  const previewAbilityAxes = summary.ability_axes.slice(0, 3);
  const previewObservedChanges = summary.observed_changes.slice(0, 2);
  const previewObjectives = summary.next_teaching_objectives.slice(0, 3);

  return (
    <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-medium text-brand">教学效果观察</p>
          <h2 className="mt-2 text-xl font-semibold tracking-tight">最近能看到的训练变化</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">{summary.summary}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
            {summary.status_label}
          </span>
          <span className="rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
            {summary.reasoning_focus_count} 个思维信号
          </span>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="rounded-xl border border-border bg-muted/30 p-4">
          <h3 className="text-sm font-semibold">关键能力轴</h3>
          {previewAbilityAxes.length > 0 ? (
            <div className="mt-3 grid gap-2">
              {previewAbilityAxes.map((axis) => (
                <article className="rounded-lg border border-border bg-muted/30 p-3" key={axis.axis_id}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="text-sm font-semibold">{axis.axis_label}</p>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">{axis.teaching_objective}</p>
                    </div>
                    <span className="rounded-full border border-brand/20 bg-background px-2 py-1 text-[11px] font-medium text-brand">
                      {axis.state_label}
                    </span>
                  </div>
                  {axis.labels.length > 0 ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {axis.labels.map((label) => (
                        <span className="rounded-full border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground" key={`${axis.axis_id}-${label}`}>
                          {label}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">
                    最新报告 {axis.latest_count} 个信号 · 历史报告 {axis.historical_count} 个信号
                  </p>
                </article>
              ))}
            </div>
          ) : (
            <p className="mt-3 rounded-lg border border-dashed border-border bg-muted/30 p-3 text-sm leading-6 text-muted-foreground">
              暂无可观察能力轴。完成一次带报告的训练后，这里会显示临床思维训练信号。
            </p>
          )}
        </div>

        <div className="grid content-start gap-3">
          <div className="rounded-xl border border-border bg-muted/30 p-4">
            <h3 className="text-sm font-semibold">观察到的变化</h3>
            {previewObservedChanges.length > 0 ? (
              <div className="mt-3 grid gap-2">
                {previewObservedChanges.map((change) => (
                  <article className="rounded-lg border border-border bg-background p-3" key={`${change.axis_id}-${change.direction}`}>
                    <p className="text-sm font-semibold">{change.axis_label}</p>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">{change.description}</p>
                  </article>
                ))}
              </div>
            ) : (
              <p className="mt-3 rounded-lg border border-dashed border-border bg-muted/30 p-3 text-sm leading-6 text-muted-foreground">
                暂无稳定变化信号。样本不足时只展示观察，不把小样本观察写成已证明提升。
              </p>
            )}
          </div>

          <div className="rounded-xl border border-border bg-muted/30 p-4">
            <h3 className="text-sm font-semibold">下一轮教学目标</h3>
            <div className="mt-3 grid gap-2">
              {previewObjectives.map((objective) => (
                <p className="rounded-lg border border-border bg-background p-3 text-sm leading-6 text-muted-foreground" key={objective}>
                  {objective}
                </p>
              ))}
            </div>
          </div>

          <details className="rounded-xl border border-dashed border-brand/20 bg-muted/30 p-4 text-xs leading-5 text-muted-foreground">
            <summary className="cursor-pointer list-none font-medium text-brand">查看完整观察边界</summary>
            <p className="mt-3">{summary.evidence_boundary}</p>
            {summary.ability_axes.length > previewAbilityAxes.length ? (
              <div className="mt-3 grid gap-2">
                {summary.ability_axes.map((axis) => (
                  <p className="rounded-lg border border-border bg-background p-3" key={`full-${axis.axis_id}`}>
                    {axis.axis_label}：{axis.teaching_objective}
                  </p>
                ))}
              </div>
            ) : null}
            {summary.observed_changes.length > previewObservedChanges.length ? (
              <div className="mt-3 grid gap-2">
                {summary.observed_changes.map((change) => (
                  <p className="rounded-lg border border-border bg-background p-3" key={`full-${change.axis_id}-${change.direction}`}>
                    {change.axis_label}：{change.description}
                  </p>
                ))}
              </div>
            ) : null}
            {summary.next_teaching_objectives.length > previewObjectives.length ? (
              <div className="mt-3 grid gap-2">
                {summary.next_teaching_objectives.map((objective) => (
                  <p className="rounded-lg border border-border bg-background p-3" key={`full-${objective}`}>
                    {objective}
                  </p>
                ))}
              </div>
            ) : null}
          </details>
        </div>
      </div>
    </section>
  );
}

function SkillProfileSummarySection({ summary }: Readonly<{ summary: SkillProfileSummary }>) {
  const skillStateEntries = Object.entries(summary.skill_states);
  const reasoningSummary = summary.reasoning_profile_summary;
  const priorityIssues = getCurrentPriorityIssues(summary);

  return (
    <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-xs font-medium text-brand">Skill 编排依据</p>
          <h2 className="mt-2 text-xl font-semibold tracking-tight">近期训练问题</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            近期画像只保留最影响下一轮训练的短期问题；TeacherAgent 会优先参考这些问题选择少量相关 Skill。
          </p>
        </div>
        <span className="w-fit rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
          {summary.last_updated_from_report_count} 份报告
        </span>
      </div>

      <div className="mt-4 grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="rounded-xl border border-border bg-muted/30 p-4">
          <h3 className="text-sm font-semibold">当前最影响训练的 Top 问题</h3>
          {priorityIssues.length > 0 ? (
            <div className="mt-3 grid gap-2">
              {priorityIssues.map((issue, index) => (
                <article className="rounded-lg border border-border bg-background p-3" key={issue.id}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-medium text-brand">
                        {index + 1}. {issue.sourceLabel}
                      </p>
                      <h4 className="mt-1 text-sm font-semibold">{issue.title}</h4>
                    </div>
                    {issue.count !== undefined ? (
                      <span className="rounded-full border border-brand/20 bg-brand/10 px-2 py-1 text-[11px] font-medium text-brand">
                        {issue.count} 次
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">{issue.description}</p>
                </article>
              ))}
            </div>
          ) : (
            <p className="mt-3 rounded-lg border border-dashed border-border bg-background p-3 text-sm leading-6 text-muted-foreground">
              暂无近期训练问题。完成训练报告后，这里会显示当前最需要补的训练点。
            </p>
          )}
        </div>

        <div className="rounded-xl border border-border bg-muted/30 p-4">
          <h3 className="text-sm font-semibold">Skill 选择线索</h3>
          {skillStateEntries.length > 0 ? (
            <div className="mt-3 grid gap-2">
              {skillStateEntries.slice(0, 3).map(([skillId, state]) => (
                <article className="rounded-lg border border-border bg-background p-3" key={skillId}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-semibold">{state.selection_reason}</p>
                    <span className="rounded-full border border-brand/20 bg-brand/10 px-2 py-1 text-[11px] font-medium text-brand">
                      {state.state_label || state.effect_status_label}
                    </span>
                  </div>
                  {state.matched_recent_training_gaps.length > 0 ? (
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">
                      命中训练缺口：{state.matched_recent_training_gaps.map((item) => item.label).join("、")}
                    </p>
                  ) : state.matched_recent_error_items.length > 0 ? (
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">
                      命中训练点：{state.matched_recent_error_items.map((item) => item.label).join("、")}
                    </p>
                  ) : state.matched_recent_reasoning_patterns.length > 0 ? (
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">
                      命中思维模式：{state.matched_recent_reasoning_patterns.map((item) => item.label).join("、")}
                    </p>
                  ) : (
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">
                      当前未命中近期漏项，作为可用教学策略保留。
                    </p>
                  )}
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    效果状态：{state.effect_status_label || "样本不足"} · 优先级 {state.priority}
                  </p>
                </article>
              ))}
            </div>
          ) : (
            <p className="mt-3 rounded-lg border border-dashed border-border bg-background p-3 text-sm leading-6 text-muted-foreground">
              暂无可编排 Skill。管理员审核启用 Skill 后，这里会显示 TeacherAgent 的选择依据。
            </p>
          )}
        </div>
      </div>

      <details className="mt-4 rounded-xl border border-dashed border-border bg-muted/30 p-4">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold">
          <span>查看完整近期问题证据</span>
          <span className="rounded-full border border-brand/20 bg-background px-2 py-1 text-[11px] font-medium text-brand">
            漏项 {summary.current_focus_items.length} · 人文 {summary.current_humanistic_gaps.length} · 证据链 {reasoningSummary.evidence_chain_focus.length}
          </span>
        </summary>

        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          <div className="rounded-lg border border-border bg-background p-3">
            <h3 className="text-sm font-semibold">近期漏项</h3>
            {summary.current_focus_items.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {summary.current_focus_items.map((focusItem) => (
                  <span className="rounded-full border border-brand/20 bg-muted/30 px-3 py-1 text-xs font-medium text-brand" key={focusItem.item_id}>
                    {focusItem.label}
                  </span>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-sm leading-6 text-muted-foreground">暂无近期漏项。</p>
            )}
          </div>

          <div className="rounded-lg border border-border bg-background p-3">
            <h3 className="text-sm font-semibold">近期思维模式</h3>
            {reasoningSummary.current_reasoning_focus.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {reasoningSummary.current_reasoning_focus.slice(0, 6).map((pattern) => (
                  <span className="rounded-full border border-brand/20 bg-muted/30 px-3 py-1 text-xs font-medium text-brand" key={pattern.pattern_id}>
                    {pattern.label}
                  </span>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-sm leading-6 text-muted-foreground">暂无近期思维模式。</p>
            )}
          </div>

          <div className="rounded-lg border border-border bg-background p-3">
            <h3 className="text-sm font-semibold">人文沟通缺口</h3>
            {summary.current_humanistic_gaps.length > 0 ? (
              <div className="mt-3 grid gap-2">
                {summary.current_humanistic_gaps.slice(0, 6).map((gap) => (
                  <article className="rounded-lg border border-border bg-muted/30 p-3" key={gap.gap_type}>
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-sm font-semibold">{gap.label}</p>
                      <span className="rounded-full border border-brand/20 bg-brand/10 px-2 py-1 text-[11px] font-medium text-brand">
                        {gap.status_label}
                      </span>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">{gap.next_training_action}</p>
                    {gap.success_signal ? <p className="mt-1 text-xs leading-5 text-muted-foreground">成功信号：{gap.success_signal}</p> : null}
                  </article>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-sm leading-6 text-muted-foreground">暂无当前人文沟通缺口。</p>
            )}
          </div>

          <div className="rounded-lg border border-border bg-background p-3">
            <h3 className="text-sm font-semibold">顺序问题</h3>
          {reasoningSummary.sequence_issue_counts.length > 0 ? (
            <div className="mt-3 grid gap-2">
              {reasoningSummary.sequence_issue_counts.slice(0, 6).map((issue) => (
                <article className="rounded-lg border border-border bg-muted/30 p-3" key={issue.flag_id}>
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm font-semibold">{issue.label}</p>
                    <span className="rounded-full border border-brand/20 bg-brand/10 px-2 py-1 text-[11px] font-medium text-brand">
                      {issue.count} 次
                    </span>
                  </div>
                  {issue.evidence_examples.length > 0 ? (
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">{issue.evidence_examples[0]}</p>
                  ) : null}
                </article>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm leading-6 text-muted-foreground">暂无明显顺序问题。</p>
          )}
        </div>

          <div className="rounded-lg border border-border bg-background p-3">
            <h3 className="text-sm font-semibold">证据链焦点</h3>
          {reasoningSummary.evidence_chain_focus.length > 0 ? (
            <div className="mt-3 grid gap-2">
              {reasoningSummary.evidence_chain_focus.slice(0, 6).map((focus) => (
                <article className="rounded-lg border border-border bg-muted/30 p-3" key={focus.breakpoint_id}>
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm font-semibold">{focus.statement}</p>
                    <span className="rounded-full border border-brand/20 bg-brand/10 px-2 py-1 text-[11px] font-medium text-brand">
                      {focus.count} 次
                    </span>
                  </div>
                  {focus.missing_evidence_labels.length > 0 ? (
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">
                      缺少证据：{focus.missing_evidence_labels.join("、")}
                    </p>
                  ) : null}
                  {focus.teacher_action ? <p className="mt-1 text-xs leading-5 text-muted-foreground">{focus.teacher_action}</p> : null}
                </article>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-sm leading-6 text-muted-foreground">暂无证据链焦点。</p>
          )}
          </div>
        </div>
      </details>
    </section>
  );
}

function SkillAccumulationSection({ accumulation }: Readonly<{ accumulation: SkillAccumulation }>) {
  const sortedSkills = getRankedEnabledSkills(accumulation.enabled_skills);
  const visibleSkills = sortedSkills.slice(0, FEATURED_SKILL_LIMIT);
  const hiddenSkills = sortedSkills.slice(FEATURED_SKILL_LIMIT);

  return (
    <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-medium text-brand">长期 Skill 记忆</p>
          <h2 className="mt-2 text-xl font-semibold tracking-tight">长期问题与干预策略</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            Skill 沉淀学生反复出现的问题模式、历史证据和干预策略；后续训练会按病例、阶段和近期缺口注入 TeacherAgent 提示。
          </p>
        </div>
        <div className="grid w-full gap-2 sm:grid-cols-2 lg:w-80">
          <div className="rounded-xl border border-brand/20 bg-background p-4">
            <p className="text-xs text-muted-foreground">已启用 Skill</p>
            <p className="mt-1 text-3xl font-semibold text-brand">{accumulation.enabled_skill_count}</p>
          </div>
          <div className="rounded-xl border border-brand/20 bg-background p-4">
            <p className="text-xs text-muted-foreground">应用次数</p>
            <p className="mt-1 text-3xl font-semibold text-brand">{accumulation.applied_skill_count}</p>
          </div>
        </div>
      </div>

      <p className="mt-4 text-sm leading-6 text-muted-foreground">{accumulation.description}</p>

      {sortedSkills.length > 0 ? (
        <>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {visibleSkills.map((skill) => {
            const effectStatusLabel = skill.effect_status_label.trim();
            const scopeLabel = skill.scope_label.trim();
            const studentVisibleSummary = skill.student_visible_summary.trim();
            const previewSummary = getSkillPreviewSummary(skill);

            return (
              <details className="rounded-xl border border-border bg-background shadow-xs" key={skill.skill_id}>
                <summary className="cursor-pointer p-4">
                  <div className="ml-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-base font-semibold">{skill.title}</h3>
                      {scopeLabel ? (
                        <span className="rounded-full border border-brand/20 bg-brand/10 px-2 py-1 text-[11px] font-medium text-brand">
                          {scopeLabel}
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-2 line-clamp-2 text-sm leading-6 text-muted-foreground">{previewSummary}</p>
                    <p className="mt-2 text-xs text-muted-foreground">
                      已启用教学策略
                      {effectStatusLabel ? ` · 效果状态：${effectStatusLabel}` : ""} · 支持 {skill.support_count} 次
                    </p>
                  </div>
                </summary>

                {studentVisibleSummary ? (
                  <p className="border-t border-border px-4 pt-4 text-sm leading-6 text-muted-foreground">{studentVisibleSummary}</p>
                ) : null}
                <div className="grid gap-3 px-4 py-4 text-sm leading-6">
                  <SkillDetailRow label="训练目标" value={skill.description} />
                  <SkillDetailRow label="TeacherAgent 应用方式" value={skill.learning_action} />
                  <SkillDetailRow label="生效条件" value={skill.activation_summary} />
                  <SkillDetailRow label="来源与效果" value={formatSkillEffectSummary(skill)} />
                </div>
              </details>
            );
          })}
          </div>

          {hiddenSkills.length > 0 ? (
            <details className="mt-4 rounded-xl border border-dashed border-brand/20 bg-muted/30 p-4">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-semibold">
                <span>查看全部 {sortedSkills.length} 条长期 Skill</span>
                <span className="rounded-full border border-brand/20 bg-background px-2 py-1 text-[11px] font-medium text-brand">
                  另有 {hiddenSkills.length} 条
                </span>
              </summary>
              <div className="mt-3 grid gap-2">
                {hiddenSkills.map((skill) => (
                  <article className="rounded-lg border border-border bg-background p-3" key={`hidden-${skill.skill_id}`}>
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p className="text-sm font-semibold">{skill.title}</p>
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">
                          {skill.student_visible_summary.trim() || skill.description}
                        </p>
                        <p className="mt-1 text-[11px] text-muted-foreground">支持 {skill.support_count} 次</p>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </details>
          ) : null}
        </>
      ) : (
        <p className="mt-4 rounded-xl border border-dashed border-brand/20 bg-background p-4 text-sm leading-6 text-muted-foreground">
          暂无已启用 Skill。后续管理端审核通过后，这里会展示可用于个性化训练的教学策略。
        </p>
      )}
    </section>
  );
}

export default function ProfilePage() {
  const [learningProfile, setLearningProfile] = useState<LearningProfile | null>(null);
  const [loadState, setLoadState] = useState<ProfileLoadState>("loading");
  const [statusText, setStatusText] = useState("正在读取近期学习画像...");

  useEffect(() => {
    async function loadLearningProfile() {
      try {
        setLoadState("loading");
        const nextProfile = await getCurrentUserProfile();
        setLearningProfile(nextProfile);
        if (isEmptyLearningProfile(nextProfile)) {
          setLoadState("empty");
          setStatusText("暂无近期学习画像。完成一次完整训练并生成报告后，这里会汇总最近训练状态。");
          return;
        }
        setLoadState("ready");
        setStatusText("已根据后端聚合画像生成近期学习主页。");
      } catch (error) {
        if (error instanceof UnauthenticatedProfileError) {
          setLoadState("unauthenticated");
          setLearningProfile(null);
          setStatusText("请先登录查看近期学习画像。");
          return;
        }
        setLoadState("error");
        setLearningProfile(null);
        setStatusText(error instanceof Error ? error.message : "读取近期学习画像失败。");
      }
    }

    loadLearningProfile();
  }, []);

  const profile = learningProfile ?? EMPTY_LEARNING_PROFILE;
  const shouldRenderProfile = loadState === "ready" || loadState === "empty";
  const primaryLearningTask = profile.learningPath[0] ?? null;
  const secondaryLearningTasks = profile.learningPath.slice(1, 3);
  const sortedDimensionAverages = [...profile.dimensionAverages].sort(
    (left, right) => right.average_percentage - left.average_percentage,
  );

  return (
    <main className="min-h-screen bg-muted/40 px-4 py-6 text-foreground">
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        <header className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                临境 OSCE 智能体（TraceOSCE）
              </p>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight">近期学习画像</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                画像记录最近训练状态，长期 Skill 记忆沉淀反复出现的问题模式、历史证据和干预策略。
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Link
                className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium whitespace-nowrap shadow-xs transition hover:bg-accent"
                href="/history"
              >
                训练记录
              </Link>
              <Link
                className="rounded-md border border-brand bg-brand px-4 py-2 text-sm font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover"
                href="/"
              >
                返回工作台
              </Link>
            </div>
          </div>
        </header>

        {loadState !== "ready" && loadState !== "empty" ? (
          <ProfileStateNotice state={loadState} message={statusText} />
        ) : null}

        {loadState === "empty" ? (
          <ProfileStateNotice state={loadState} message={statusText} />
        ) : null}

        {shouldRenderProfile ? (
          <>
        <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="rounded-2xl border border-brand/20 bg-background p-6 shadow-xs">
            <p className="text-sm font-semibold text-brand">当前最该练什么</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight">{profile.nextFocus}</h2>
            <p className="mt-2 text-xs font-medium text-muted-foreground">
              薄弱项：{profile.weakestDimension?.label ?? "暂无"}
            </p>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">{statusText}</p>

            <div className="mt-5 rounded-xl border border-border bg-muted/30 p-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <p className="text-xs font-medium text-brand">下一轮训练任务</p>
                  {primaryLearningTask ? (
                    <>
                      <h3 className="mt-1 text-lg font-semibold">病例：{primaryLearningTask.case_title || primaryLearningTask.case_id}</h3>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">{primaryLearningTask.objective}</p>
                    </>
                  ) : (
                    <>
                      <h3 className="mt-1 text-lg font-semibold">先完成一次完整训练</h3>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">
                        完成评分报告后，系统会根据薄弱项、漏项和相似病例生成下一轮训练任务。
                      </p>
                    </>
                  )}
                </div>
                <Link
                  className="inline-flex w-fit rounded-md border border-brand bg-brand px-4 py-2 text-sm font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover"
                  href="/cases"
                >
                  开始下一轮训练
                </Link>
              </div>
              {primaryLearningTask && primaryLearningTask.target_rubric_item_labels.length > 0 ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  {primaryLearningTask.target_rubric_item_labels.map((itemLabel, index) => (
                    <span className="rounded-full border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground" key={getLearningPathTargetKey(primaryLearningTask, itemLabel, index)}>
                      {itemLabel}
                    </span>
                  ))}
                </div>
              ) : null}
              {primaryLearningTask && primaryLearningTask.source_reference_labels.length > 0 ? (
                <p className="mt-3 break-words text-[11px] leading-5 text-muted-foreground">
                  来源：{primaryLearningTask.source_reference_labels.join(" · ")}
                </p>
              ) : null}
            </div>

            {secondaryLearningTasks.length > 0 ? (
              <div className="mt-4 grid gap-2 md:grid-cols-2">
                {secondaryLearningTasks.map((task) => (
                  <article className="rounded-lg border border-border bg-muted/20 p-3" key={`${task.task_type}-${task.case_id}`}>
                    <p className="text-[11px] font-medium text-muted-foreground">{task.task_type_label || task.task_type}</p>
                    <h3 className="mt-1 text-sm font-semibold">病例：{task.case_title || task.case_id}</h3>
                    <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{task.objective}</p>
                  </article>
                ))}
              </div>
            ) : null}
          </div>

          <aside className="grid content-start gap-3">
            <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
              <p className="text-xs font-medium text-muted-foreground">训练次数</p>
              <p className="mt-2 text-3xl font-semibold text-brand">{profile.totalSessions}</p>
              <p className="mt-1 text-xs text-muted-foreground">当前账号保存的后端 session 总数。</p>
            </section>
            <section className="grid grid-cols-2 gap-3">
              <div className="rounded-2xl border border-border bg-background p-4 shadow-xs">
                <p className="text-xs font-medium text-muted-foreground">已生成报告</p>
                <p className="mt-2 text-2xl font-semibold text-brand">{profile.reportCount}</p>
              </div>
              <div className="rounded-2xl border border-border bg-background p-4 shadow-xs">
                <p className="text-xs font-medium text-muted-foreground">平均分</p>
                <p className="mt-2 text-2xl font-semibold text-brand">{profile.reportCount > 0 ? profile.averageScore : "--"}</p>
              </div>
            </section>
            <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
              <p className="text-xs font-medium text-muted-foreground">优势项</p>
              <h2 className="mt-2 text-lg font-semibold text-brand">{profile.strongestDimension?.label ?? "暂无"}</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {profile.strongestDimension
                  ? `平均完成度 ${profile.strongestDimension.average_percentage}%`
                  : "用于后续推荐更高阶病例或巩固型训练。"}
              </p>
            </section>
          </aside>
        </section>

        <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">能力维度趋势</h2>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                每份报告先按各自 Rubric 分母换算为完成度，再跨报告求平均，避免不同评分上限误导比较。
              </p>
            </div>
            <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
              {profile.dimensionAverages.length} 维
            </span>
          </div>
          {sortedDimensionAverages.length > 0 ? (
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {sortedDimensionAverages.map((dimension) => (
                <article className="rounded-xl border border-border bg-muted/30 p-4" key={dimension.key}>
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <p className="font-medium">{dimension.label}</p>
                    <p className="text-muted-foreground">
                      平均完成度 {dimension.average_percentage}% · {dimension.sample_count} 份报告
                    </p>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-background">
                    <div className="h-full rounded-full bg-brand" style={{ width: getDimensionPercentageWidth(dimension.average_percentage) }} />
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <p className="mt-4 rounded-xl border border-dashed border-border bg-muted/30 p-4 text-sm leading-6 text-muted-foreground">
              暂无可聚合维度。完成评分报告后，这里会展示问诊、查体、辅助检查、诊断和推理链趋势。
            </p>
          )}
        </section>

        <TeachingEffectSummarySection summary={profile.skillProfileSummary.teaching_effect_summary} />

        <SkillProfileSummarySection summary={profile.skillProfileSummary} />

        <SkillAccumulationSection accumulation={profile.skillAccumulation} />

        <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">最近训练</h2>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">用于从个人主页回到具体 session 或报告页继续复盘。</p>
            </div>
            <Link className="text-xs font-medium text-brand hover:underline" href="/history">
              查看全部
            </Link>
          </div>
          {profile.recentSessions.length > 0 ? (
            <div className="mt-4 grid gap-3">
              {profile.recentSessions.map((session) => (
                <article className="rounded-xl border border-border bg-muted/40 p-4" data-session-id={session.session_id} key={session.session_id}>
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                          <h3 className="text-sm font-semibold">病例：{session.case_title || "病例信息暂缺"}</h3>
                          <p className="mt-1 text-xs text-muted-foreground">
                            当前阶段：{session.stage_label || session.stage} · {session.is_completed ? "已结束" : "训练中"} · 更新：
                            {formatSavedAt(session.updated_at)}
                          </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {session.can_continue ? (
                        <Link
                          className="rounded-md border border-border bg-background px-3 py-2 text-xs font-medium whitespace-nowrap text-muted-foreground shadow-xs transition hover:bg-accent"
                          href={`/?session_id=${session.session_id}`}
                        >
                          继续训练
                        </Link>
                      ) : (
                        <span className="rounded-md border border-border bg-muted px-3 py-2 text-xs font-medium whitespace-nowrap text-muted-foreground">
                          训练已结束
                        </span>
                      )}
                      {session.is_completed || session.has_report ? (
                        <Link
                          className="rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover"
                          href={`/report?session_id=${session.session_id}`}
                        >
                          打开报告
                        </Link>
                      ) : null}
                    </div>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <p className="mt-4 rounded-xl border border-dashed border-border bg-muted/30 p-4 text-sm leading-6 text-muted-foreground">
              暂无训练记录。先选择病例并完成一次训练后，这里会展示个人训练轨迹。
            </p>
          )}
        </section>
          </>
        ) : null}
      </div>
    </main>
  );
}
