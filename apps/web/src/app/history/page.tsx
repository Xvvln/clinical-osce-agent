"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { deleteTrainingHistoryRecord } from "../training-history";

type TrainingDifficultyMode = "beginner" | "intermediate" | "advanced";

type PersistedSessionSummary = Readonly<{
  session_id: string;
  case_id: string;
  case_title: string;
  training_difficulty: TrainingDifficultyMode;
  stage: string;
  created_at: string;
  updated_at: string;
  is_completed: boolean;
  can_continue: boolean;
  has_report: boolean;
  completion_status: "in_progress" | "diagnosis_submitted" | "report_ready";
}>;

type PersistedSessionListResponse = Readonly<{
  sessions: readonly PersistedSessionSummary[];
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

function getTrainingSessionStatusLabel(session: PersistedSessionSummary): string {
  if (session.completion_status === "report_ready") {
    return "报告已生成";
  }
  if (session.completion_status === "diagnosis_submitted") {
    return "已提交诊断";
  }
  return "训练中";
}

function getTrainingSessionStatusClass(session: PersistedSessionSummary): string {
  if (session.is_completed) {
    return "border-brand/20 bg-brand/10 text-brand";
  }
  return "border-border bg-background text-muted-foreground";
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

async function getCurrentUserSessions(): Promise<readonly PersistedSessionSummary[]> {
  const response = await fetch("/api/me/sessions", {
    credentials: "same-origin",
    method: "GET",
  });

  if (response.status === 401) {
    return [];
  }

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `请求失败：${response.status}`);
  }

  const payload = (await response.json()) as PersistedSessionListResponse;
  return payload.sessions;
}

async function deleteCurrentUserSession(sessionId: string): Promise<void> {
  const response = await fetch(`/api/me/sessions/${sessionId}`, {
    credentials: "same-origin",
    method: "DELETE",
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `请求失败：${response.status}`);
  }
}

export default function HistoryPage() {
  const [backendSessions, setBackendSessions] = useState<readonly PersistedSessionSummary[]>([]);
  const [backendStatusText, setBackendStatusText] = useState("正在读取后端持久记录...");
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);
  const [pendingDeleteSession, setPendingDeleteSession] = useState<PersistedSessionSummary | null>(null);

  useEffect(() => {
    async function loadBackendSessions() {
      try {
        setBackendSessions(await getCurrentUserSessions());
        setBackendStatusText("已从后端数据库读取当前账号的训练记录。");
      } catch (error) {
        setBackendStatusText(error instanceof Error ? error.message : "读取后端持久记录失败。");
      }
    }

    loadBackendSessions();
  }, []);

  async function handleDeleteBackendSession(sessionId: string) {
    if (deletingSessionId) {
      return;
    }

    setDeletingSessionId(sessionId);
    try {
      await deleteCurrentUserSession(sessionId);
      deleteTrainingHistoryRecord(sessionId);
      setBackendSessions((currentSessions) => currentSessions.filter((session) => session.session_id !== sessionId));
      setPendingDeleteSession(null);
      setBackendStatusText("已删除后端训练记录。");
    } catch (error) {
      setBackendStatusText(error instanceof Error ? error.message : "删除后端训练记录失败。");
    } finally {
      setDeletingSessionId(null);
    }
  }

  return (
    <main className="min-h-screen bg-muted/40 px-4 py-6 text-foreground">
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        <header className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                临境 OSCE 智能体（TraceOSCE）
              </p>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight">训练记录</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                本页只展示当前账号保存在后端数据库中的训练记录，作为正式训练历史的唯一来源。
              </p>
            </div>
            <Link
              className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium whitespace-nowrap shadow-xs transition hover:bg-accent"
              href="/"
            >
              返回工作台
            </Link>
          </div>
        </header>

        <section className="rounded-2xl border border-brand/20 bg-brand/5 p-5 shadow-xs">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-sm font-semibold text-brand">后端持久记录</p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight">已同步 {backendSessions.length} 条训练记录。</h2>
            </div>
            <span className="w-fit rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
              SQLite
            </span>
          </div>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-muted-foreground">{backendStatusText}</p>
        </section>

        {backendSessions.length > 0 ? (
          <section className="grid gap-3">
            {backendSessions.map((session) => (
              <article className="rounded-2xl border border-border bg-background p-5 shadow-xs" data-session-id={session.session_id} key={session.session_id}>
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <h2 className="text-base font-semibold tracking-tight">病例：{session.case_title || "病例信息暂缺"}</h2>
                    <p className="mt-1 text-sm text-muted-foreground">当前阶段：{session.stage}</p>
                  </div>
                  <span className={`w-fit rounded-full border px-3 py-1 text-xs font-medium ${getTrainingSessionStatusClass(session)}`}>
                    {getTrainingSessionStatusLabel(session)}
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2 text-xs">
                  <span className="rounded-full border border-brand/20 bg-brand/5 px-3 py-1 font-medium whitespace-nowrap text-brand">
                    {getTrainingDifficultyLabel(session.training_difficulty)}训练
                  </span>
                </div>
                <div className="mt-4 flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-xs leading-5 text-muted-foreground">
                    更新时间：{formatSavedAt(session.updated_at)} · 创建时间：{formatSavedAt(session.created_at)}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {session.can_continue ? (
                      <Link
                        className="w-fit rounded-md border border-border bg-background px-3 py-2 text-xs font-medium whitespace-nowrap text-muted-foreground shadow-xs transition hover:bg-accent"
                        href={`/?session_id=${session.session_id}`}
                      >
                        继续训练
                      </Link>
                    ) : (
                      <span className="w-fit rounded-md border border-border bg-muted px-3 py-2 text-xs font-medium whitespace-nowrap text-muted-foreground">
                        训练已结束
                      </span>
                    )}
                    {session.is_completed || session.has_report ? (
                      <Link
                        className="w-fit rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover"
                        href={`/report?session_id=${session.session_id}`}
                      >
                        打开报告
                      </Link>
                    ) : (
                      <span className="w-fit rounded-md border border-border bg-muted px-3 py-2 text-xs font-medium whitespace-nowrap text-muted-foreground">
                        提交诊断后可查看报告
                      </span>
                    )}
                    <button
                      className="w-fit rounded-md border border-destructive bg-destructive px-3 py-2 text-xs font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-destructive/90 disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={deletingSessionId !== null}
                      onClick={() => setPendingDeleteSession(session)}
                      type="button"
                    >
                      {deletingSessionId === session.session_id ? "删除中" : "删除记录"}
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </section>
        ) : (
          <section className="rounded-2xl border border-dashed border-border bg-background p-8 text-center shadow-xs">
            <h2 className="text-base font-semibold">暂无后端训练记录</h2>
            <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
              登录后开始训练会自动创建数据库记录；完成问诊、查体、检查或报告后，可回到这里继续训练或打开报告。
            </p>
            <Link
              className="mt-5 inline-flex items-center justify-center rounded-md border border-brand bg-brand px-4 py-2 text-sm font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover"
              href="/"
            >
              开始训练
            </Link>
          </section>
        )}
      </div>
      {pendingDeleteSession ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/20 px-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-border bg-background p-5 shadow-[0_24px_70px_rgba(20,20,19,0.22)]">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-destructive">删除确认</p>
            <h2 className="mt-2 text-lg font-semibold tracking-tight">确认删除训练记录</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              删除后将无法从训练记录继续训练或打开该记录。病例：{pendingDeleteSession.case_title ?? pendingDeleteSession.case_id}，
              难度：{getTrainingDifficultyLabel(pendingDeleteSession.training_difficulty)}训练。
            </p>
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <button
                className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium whitespace-nowrap shadow-xs transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                disabled={deletingSessionId !== null}
                onClick={() => setPendingDeleteSession(null)}
                type="button"
              >
                取消
              </button>
              <button
                className="rounded-md border border-destructive bg-destructive px-4 py-2 text-sm font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-destructive/90 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={deletingSessionId !== null}
                onClick={() => handleDeleteBackendSession(pendingDeleteSession.session_id)}
                type="button"
              >
                {deletingSessionId === pendingDeleteSession.session_id ? "删除中" : "确认删除"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
