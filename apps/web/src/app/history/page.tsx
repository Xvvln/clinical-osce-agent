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
      setBackendSessions((currentSessions) => currentSessions.filter((session) => session.session_id !== sessionId));
      setBackendStatusText("已删除后端训练记录。");
    } catch (error) {
      setBackendStatusText(error instanceof Error ? error.message : "删除后端训练记录失败。");
    } finally {
      setDeletingSessionId(null);
    }
  }

  const workbenchHref = backendSessions[0] ? `/?session_id=${backendSessions[0].session_id}` : "/";

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
                本页只展示当前登录账号保存在后端数据库中的训练 session，作为正式训练记录的唯一来源。
              </p>
            </div>
            <Link
              className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium whitespace-nowrap shadow-xs transition hover:bg-accent"
              href={workbenchHref}
            >
              返回工作台
            </Link>
          </div>
        </header>

        <section className="rounded-2xl border border-brand/20 bg-brand/5 p-5 shadow-xs">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-sm font-semibold text-brand">后端持久记录</p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight">已同步 {backendSessions.length} 个训练 session。</h2>
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
              <article className="rounded-2xl border border-border bg-background p-5 shadow-xs" key={session.session_id}>
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <p className="font-mono text-[11px] text-muted-foreground">{session.session_id}</p>
                    <h2 className="mt-2 text-base font-semibold tracking-tight">病例：{session.case_id}</h2>
                    <p className="mt-1 text-sm text-muted-foreground">当前阶段：{session.stage}</p>
                  </div>
                  <span className="w-fit rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
                    后端持久化
                  </span>
                </div>
                <div className="mt-4 flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-xs leading-5 text-muted-foreground">
                    更新时间：{formatSavedAt(session.updated_at)} · 创建时间：{formatSavedAt(session.created_at)}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Link
                      className="w-fit rounded-md border border-border bg-background px-3 py-2 text-xs font-medium whitespace-nowrap text-muted-foreground shadow-xs transition hover:bg-accent"
                      href={`/api/me/sessions/${session.session_id}`}
                    >
                      查看状态
                    </Link>
                    <Link
                      className="w-fit rounded-md border border-border bg-background px-3 py-2 text-xs font-medium whitespace-nowrap text-muted-foreground shadow-xs transition hover:bg-accent"
                      href={`/?session_id=${session.session_id}`}
                    >
                      继续训练
                    </Link>
                    <Link
                      className="w-fit rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover"
                      href={`/report?session_id=${session.session_id}`}
                    >
                      打开报告
                    </Link>
                    <button
                      className="w-fit rounded-md border border-destructive/30 bg-background px-3 py-2 text-xs font-medium whitespace-nowrap text-destructive shadow-xs transition hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={deletingSessionId !== null}
                      onClick={() => handleDeleteBackendSession(session.session_id)}
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
              登录后开始训练会自动创建数据库 session；完成问诊、查体、检查或报告后，可回到这里继续训练或打开报告。
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
    </main>
  );
}
