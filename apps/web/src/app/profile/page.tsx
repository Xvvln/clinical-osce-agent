"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

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

type SkillProfileSkillState = Readonly<{
  state: string;
  state_label: string;
  priority: number;
  trigger_item_ids: readonly string[];
  trigger_item_labels: readonly string[];
  matched_recent_error_item_ids: readonly string[];
  matched_recent_error_items: readonly SkillProfileItem[];
  effect_status: string;
  effect_status_label: string;
  selection_reason: string;
}>;

type SkillProfileSummary = Readonly<{
  recent_error_item_ids: readonly string[];
  recent_error_items: readonly SkillProfileItem[];
  current_focus_item_ids: readonly string[];
  current_focus_items: readonly SkillProfileItem[];
  skill_states: Readonly<Record<string, SkillProfileSkillState>>;
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

const EMPTY_SKILL_PROFILE_SUMMARY: SkillProfileSummary = {
  recent_error_item_ids: [],
  recent_error_items: [],
  current_focus_item_ids: [],
  current_focus_items: [],
  skill_states: {},
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
    description: "Step 8 会把已审核教学 Skill、常见错误模式和个性化提示策略接入这里；当前页面先展示由评分报告聚合出的学习画像。",
    enabled_skill_count: 0,
    applied_skill_count: 0,
    enabled_skills: [],
  },
  skillProfileSummary: EMPTY_SKILL_PROFILE_SUMMARY,
};

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
    skillProfileSummary: payload.skill_profile_summary ?? EMPTY_SKILL_PROFILE_SUMMARY,
  };
}

async function getCurrentUserProfile(): Promise<LearningProfile> {
  const response = await fetch("/api/me/profile", {
    credentials: "same-origin",
    method: "GET",
  });

  if (response.status === 401) {
    return EMPTY_LEARNING_PROFILE;
  }

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `请求失败：${response.status}`);
  }

  const payload = (await response.json()) as CurrentUserProfileResponse;
  return toLearningProfile(payload.profile);
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

function SkillProfileSummarySection({ summary }: Readonly<{ summary: SkillProfileSummary }>) {
  const skillStateEntries = Object.entries(summary.skill_states);

  return (
    <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-xs font-medium text-brand">Skill 编排依据</p>
          <h2 className="mt-2 text-xl font-semibold tracking-tight">当前训练问题</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            由最近评分报告中的未覆盖训练点派生，Coach 会优先参考这些问题选择少量相关 Skill。
          </p>
        </div>
        <span className="w-fit rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
          {summary.last_updated_from_report_count} 份报告
        </span>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div className="rounded-xl border border-border bg-muted/30 p-4">
          <h3 className="text-sm font-semibold">近期漏项</h3>
          {summary.current_focus_items.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {summary.current_focus_items.map((focusItem) => (
                <span className="rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand" key={focusItem.item_id}>
                  {focusItem.label}
                </span>
              ))}
            </div>
          ) : (
            <p className="mt-3 rounded-lg border border-dashed border-border bg-background p-3 text-sm leading-6 text-muted-foreground">
              暂无近期漏项。完成训练报告后，这里会显示当前最需要补的训练点。
            </p>
          )}
        </div>

        <div className="rounded-xl border border-border bg-muted/30 p-4">
          <h3 className="text-sm font-semibold">Skill 编排依据</h3>
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
                  {state.matched_recent_error_items.length > 0 ? (
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">
                      命中训练点：{state.matched_recent_error_items.map((item) => item.label).join("、")}
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
              暂无可编排 Skill。管理员审核启用 Skill 后，这里会显示 Coach 的选择依据。
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

function SkillAccumulationSection({ accumulation }: Readonly<{ accumulation: SkillAccumulation }>) {
  return (
    <section className="rounded-2xl border border-brand/20 bg-brand/5 p-5 shadow-xs">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-medium text-brand">Skill 积累</p>
          <h2 className="mt-2 text-xl font-semibold tracking-tight">个人训练 Skill</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            已审核的教学策略会在后续训练中按病例、阶段和当前缺口注入 Coach 提示；样本不足时只展示应用痕迹，不伪造提升。
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

      {accumulation.enabled_skills.length > 0 ? (
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {accumulation.enabled_skills.map((skill) => {
            const effectStatusLabel = skill.effect_status_label.trim();
            const scopeLabel = skill.scope_label.trim();
            const studentVisibleSummary = skill.student_visible_summary.trim();

            return (
              <details className="rounded-xl border border-border bg-background p-4 shadow-xs" key={skill.skill_id}>
                <summary className="flex cursor-pointer list-none items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-base font-semibold">{skill.title}</h3>
                      {scopeLabel ? (
                        <span className="rounded-full border border-brand/20 bg-brand/10 px-2 py-1 text-[11px] font-medium text-brand">
                          {scopeLabel}
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {effectStatusLabel ? `已启用教学策略 · 效果状态：${effectStatusLabel}` : "已启用教学策略"}
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-2">
                    <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
                      支持次数 {skill.support_count}
                    </span>
                    <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
                      查看 Skill 详情
                    </span>
                  </div>
                </summary>

                {studentVisibleSummary ? (
                  <p className="mt-4 text-sm leading-6 text-muted-foreground">{studentVisibleSummary}</p>
                ) : null}
                <div className="mt-4 grid gap-3 text-sm leading-6">
                  <SkillDetailRow label="训练目标" value={skill.description} />
                  <SkillDetailRow label="Coach 应用方式" value={skill.learning_action} />
                  <SkillDetailRow label="生效条件" value={skill.activation_summary} />
                  <SkillDetailRow label="来源与效果" value={formatSkillEffectSummary(skill)} />
                </div>
              </details>
            );
          })}
        </div>
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
  const [statusText, setStatusText] = useState("正在读取当前账号的学习画像...");

  useEffect(() => {
    async function loadLearningProfile() {
      try {
        const nextProfile = await getCurrentUserProfile();
        setLearningProfile(nextProfile);
        setStatusText(nextProfile.reportCount > 0 ? "已根据后端聚合画像生成个人训练主页。" : "暂无已生成报告，完成一次诊断提交后会形成学习画像。");
      } catch (error) {
        setStatusText(error instanceof Error ? error.message : "读取学习画像失败。");
      }
    }

    loadLearningProfile();
  }, []);

  const profile = learningProfile ?? EMPTY_LEARNING_PROFILE;

  return (
    <main className="min-h-screen bg-muted/40 px-4 py-6 text-foreground">
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        <header className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                临境 OSCE 智能体（TraceOSCE）
              </p>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight">学习画像</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                汇总当前账号的训练次数、平均分、长期薄弱项和下一步训练重点，后续承接个人 Skill 积累。
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

        <section className="rounded-2xl border border-brand/20 bg-brand/5 p-5 shadow-xs">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-sm font-semibold text-brand">个人训练主页</p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight">长期表现从后端训练记录聚合生成。</h2>
            </div>
            <span className="w-fit rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
              当前账号
            </span>
          </div>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-muted-foreground">{statusText}</p>
        </section>

        <section className="grid gap-3 md:grid-cols-3">
          <article className="rounded-2xl border border-border bg-background p-5 shadow-xs">
            <p className="text-xs font-medium text-muted-foreground">训练次数</p>
            <p className="mt-3 text-3xl font-semibold text-brand">{profile.totalSessions}</p>
            <p className="mt-2 text-sm text-muted-foreground">当前账号保存的后端 session 总数。</p>
          </article>
          <article className="rounded-2xl border border-border bg-background p-5 shadow-xs">
            <p className="text-xs font-medium text-muted-foreground">已生成报告</p>
            <p className="mt-3 text-3xl font-semibold text-brand">{profile.reportCount}</p>
            <p className="mt-2 text-sm text-muted-foreground">完成诊断提交后生成的可评分训练记录。</p>
          </article>
          <article className="rounded-2xl border border-border bg-background p-5 shadow-xs">
            <p className="text-xs font-medium text-muted-foreground">平均分</p>
            <p className="mt-3 text-3xl font-semibold text-brand">{profile.reportCount > 0 ? profile.averageScore : "--"}</p>
            <p className="mt-2 text-sm text-muted-foreground">基于已有评分报告计算。</p>
          </article>
        </section>

        <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">个性化学习路径</h2>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                由评分报告、薄弱维度、漏项和相似病例推荐确定性生成，用于安排下一轮训练。
              </p>
            </div>
            <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
              {profile.learningPath.length} 项
            </span>
          </div>
          {profile.learningPath.length > 0 ? (
            <div className="mt-4 grid gap-3 md:grid-cols-2">
                  {profile.learningPath.map((task) => (
                    <article className="rounded-xl border border-border bg-muted/30 p-4" key={`${task.task_type}-${task.case_id}`}>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-[11px] font-medium text-muted-foreground">{task.task_type_label || task.task_type}</p>
                          <h3 className="mt-1 text-sm font-semibold">病例：{task.case_title || task.case_id}</h3>
                        </div>
                    <span className="rounded-full border border-brand/20 bg-background px-2 py-1 text-[11px] font-medium text-brand">
                      {task.source_report_count} 份报告
                    </span>
                  </div>
                  <p className="mt-3 text-sm leading-6 text-muted-foreground">{task.objective}</p>
                      {(task.target_rubric_item_labels ?? []).length > 0 ? (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {(task.target_rubric_item_labels ?? []).map((itemLabel, index) => (
                            <span className="rounded-full border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground" key={`${task.case_id}-${task.target_rubric_items[index] ?? itemLabel}`}>
                              {itemLabel}
                            </span>
                          ))}
                        </div>
                      ) : null}
                      {(task.source_reference_labels ?? []).length > 0 ? (
                        <p className="mt-3 break-words text-[11px] leading-5 text-muted-foreground">
                          来源：{(task.source_reference_labels ?? []).join(" · ")}
                        </p>
                      ) : null}
                </article>
              ))}
            </div>
          ) : (
            <p className="mt-4 rounded-xl border border-dashed border-border bg-muted/30 p-4 text-sm leading-6 text-muted-foreground">
              暂无学习路径。完成一次评分报告后，系统会从本轮漏项和病例推荐生成下一步训练任务。
            </p>
          )}
        </section>

        <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="rounded-2xl border border-border bg-background p-5 shadow-xs">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold">能力维度趋势</h2>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  按报告中的分项分聚合，帮助判断长期优势和薄弱项。
                </p>
              </div>
              <span className="rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
                {profile.dimensionAverages.length} 维
              </span>
            </div>
            {profile.dimensionAverages.length > 0 ? (
              <div className="mt-4 grid gap-3">
                {profile.dimensionAverages.map((dimension) => (
                  <article className="rounded-xl border border-border bg-muted/40 p-4" key={dimension.key}>
                    <div className="flex items-center justify-between gap-3 text-sm">
                      <p className="font-medium">{dimension.label}</p>
                      <p className="text-muted-foreground">{dimension.average} 分</p>
                    </div>
                    <div className="mt-3 h-2 overflow-hidden rounded-full bg-background">
                      <div className="h-full rounded-full bg-brand" style={{ width: `${Math.min(dimension.average, 100)}%` }} />
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <p className="mt-4 rounded-xl border border-dashed border-border bg-muted/30 p-4 text-sm leading-6 text-muted-foreground">
                暂无可聚合维度。完成评分报告后，这里会展示问诊、查体、辅助检查、诊断和推理链趋势。
              </p>
            )}
          </div>

          <aside className="grid content-start gap-4">
            <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
              <p className="text-xs font-medium text-muted-foreground">薄弱项</p>
              <h2 className="mt-2 text-lg font-semibold text-brand">{profile.weakestDimension?.label ?? "暂无"}</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{profile.nextFocus}</p>
            </section>
            <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
              <p className="text-xs font-medium text-muted-foreground">优势项</p>
              <h2 className="mt-2 text-lg font-semibold text-brand">{profile.strongestDimension?.label ?? "暂无"}</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">用于后续推荐更高阶病例或巩固型训练。</p>
            </section>
          </aside>
        </section>

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
                <article className="rounded-xl border border-border bg-muted/40 p-4" key={session.session_id}>
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                          <p className="font-mono text-[11px] text-muted-foreground">{session.session_id}</p>
                          <h3 className="mt-1 text-sm font-semibold">病例：{session.case_title || session.case_id}</h3>
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
      </div>
    </main>
  );
}
