"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type PersistedSessionSummary = Readonly<{
  session_id: string;
  case_id: string;
  stage: string;
  created_at: string;
  updated_at: string;
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
  support_count: number;
  effect_status: string;
}>;

type SkillAccumulation = Readonly<{
  status: string;
  description: string;
  enabled_skill_count: number;
  applied_skill_count: number;
  enabled_skills: readonly EnabledSkillSummary[];
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
  recent_sessions: readonly PersistedSessionSummary[];
  skill_accumulation: SkillAccumulation;
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
  recentSessions: readonly PersistedSessionSummary[];
  skillAccumulation: SkillAccumulation;
}>;

const EMPTY_LEARNING_PROFILE: LearningProfile = {
  totalSessions: 0,
  reportCount: 0,
  averageScore: 0,
  dimensionAverages: [],
  strongestDimension: null,
  weakestDimension: null,
  nextFocus: "先完成一次完整训练并生成评分报告。",
  recentSessions: [],
  skillAccumulation: {
    status: "planned",
    description: "Step 8 会把已审核教学 Skill、常见错误模式和个性化提示策略接入这里；当前页面先展示由评分报告聚合出的学习画像。",
    enabled_skill_count: 0,
    applied_skill_count: 0,
    enabled_skills: [],
  },
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
    recentSessions: payload.recent_sessions,
    skillAccumulation: payload.skill_accumulation,
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
                Clinical OSCE Agent
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
            <section className="rounded-2xl border border-brand/20 bg-brand/5 p-5 shadow-xs">
              <p className="text-xs font-medium text-brand">Skill 积累</p>
              <h2 className="mt-2 text-lg font-semibold">已启用 Skill</h2>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <div className="rounded-xl border border-brand/20 bg-background p-3">
                  <p className="text-xs text-muted-foreground">已启用 Skill</p>
                  <p className="mt-1 text-2xl font-semibold text-brand">{profile.skillAccumulation.enabled_skill_count}</p>
                </div>
                <div className="rounded-xl border border-brand/20 bg-background p-3">
                  <p className="text-xs text-muted-foreground">应用次数</p>
                  <p className="mt-1 text-2xl font-semibold text-brand">{profile.skillAccumulation.applied_skill_count}</p>
                </div>
              </div>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">{profile.skillAccumulation.description}</p>
              {profile.skillAccumulation.enabled_skills.length > 0 ? (
                <div className="mt-3 grid gap-2">
                  {profile.skillAccumulation.enabled_skills.map((skill) => (
                    <article className="rounded-xl border border-border bg-background p-3" key={skill.skill_id}>
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <h3 className="text-sm font-semibold">{skill.title}</h3>
                          <p className="mt-1 text-[11px] text-muted-foreground">已启用教学策略</p>
                          <p className="mt-1 text-[11px] text-muted-foreground">效果状态：{skill.effect_status}</p>
                        </div>
                        <span className="rounded-full border border-brand/20 bg-brand/10 px-2 py-1 text-[11px] font-medium text-brand">
                          支持次数 {skill.support_count}
                        </span>
                      </div>
                      <p className="mt-2 text-xs leading-5 text-muted-foreground">
                        {skill.student_visible_summary}
                      </p>
                    </article>
                  ))}
                </div>
              ) : (
                <p className="mt-3 rounded-xl border border-dashed border-brand/20 bg-background p-3 text-xs leading-5 text-muted-foreground">
                  暂无已启用 Skill。后续管理端审核通过后，这里会展示可用于个性化训练的教学策略。
                </p>
              )}
            </section>
          </aside>
        </section>

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
                      <h3 className="mt-1 text-sm font-semibold">病例：{session.case_id}</h3>
                      <p className="mt-1 text-xs text-muted-foreground">
                        当前阶段：{session.stage} · 更新：{formatSavedAt(session.updated_at)}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Link
                        className="rounded-md border border-border bg-background px-3 py-2 text-xs font-medium whitespace-nowrap text-muted-foreground shadow-xs transition hover:bg-accent"
                        href={`/?session_id=${session.session_id}`}
                      >
                        继续训练
                      </Link>
                      <Link
                        className="rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover"
                        href={`/report?session_id=${session.session_id}`}
                      >
                        打开报告
                      </Link>
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
