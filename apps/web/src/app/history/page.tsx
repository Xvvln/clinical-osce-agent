"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  clearTrainingHistoryRecords,
  deleteTrainingHistoryRecord,
  readTrainingHistoryRecords,
} from "../training-history";
import type { TrainingHistoryRecord } from "../training-history";

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

export default function HistoryPage() {
  const [records, setRecords] = useState<readonly TrainingHistoryRecord[]>([]);

  useEffect(() => {
    setRecords(readTrainingHistoryRecords());
  }, []);

  function handleDeleteRecord(sessionId: string) {
    setRecords(deleteTrainingHistoryRecord(sessionId));
  }

  function handleClearRecords() {
    setRecords(clearTrainingHistoryRecords());
  }

  return (
    <main className="min-h-screen bg-muted/40 px-4 py-6 text-foreground">
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        <header className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                Clinical OSCE Agent
              </p>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight">训练记录</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                本页展示保存在当前浏览器 localStorage 中的 OSCE 训练记录，用于本机演示和复盘，不代表后端持久化。
              </p>
            </div>
            <Link
              className="rounded-md border border-border bg-background px-4 py-2 text-sm font-medium shadow-xs transition hover:bg-accent"
              href="/"
            >
              返回工作台
            </Link>
          </div>
        </header>

        <section className="rounded-2xl border border-brand/20 bg-[#2F6868]/5 p-5 shadow-xs">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-sm font-semibold text-brand">本机历史</p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight">已保存 {records.length} 条训练记录。</h2>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {records.length > 0 ? (
                <button
                  className="rounded-md border border-border bg-background px-3 py-2 text-xs font-medium text-muted-foreground shadow-xs transition hover:bg-accent"
                  onClick={handleClearRecords}
                  type="button"
                >
                  清空记录
                </button>
              ) : null}
              <span className="w-fit rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
                localStorage
              </span>
            </div>
          </div>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-muted-foreground">
            当前记录只保存在这台设备和这个浏览器中。后端数据库持久化、跨设备同步和历史训练检索仍属于后续阶段。
          </p>
        </section>

        {records.length > 0 ? (
          <section className="grid gap-3">
            {records.map((record) => (
              <article className="rounded-2xl border border-border bg-background p-5 shadow-xs" key={record.sessionId}>
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <p className="font-mono text-[11px] text-muted-foreground">{record.sessionId}</p>
                    <h2 className="mt-2 text-base font-semibold tracking-tight">{record.caseTitle}</h2>
                    <p className="mt-1 text-sm text-muted-foreground">病例：{record.caseId}</p>
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs">
                    <span className="rounded-full border border-brand/20 bg-[#2F6868]/10 px-3 py-1 font-medium text-brand">
                      {record.totalScore} / 100
                    </span>
                    <span className="rounded-full border border-border bg-muted px-3 py-1 font-medium text-muted-foreground">
                      {record.status}
                    </span>
                  </div>
                </div>
                <div className="mt-4 flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-xs leading-5 text-muted-foreground">保存时间：{formatSavedAt(record.savedAt)}</p>
                  <div className="flex flex-wrap gap-2">
                    <button
                      className="w-fit rounded-md border border-border bg-background px-3 py-2 text-xs font-medium text-muted-foreground shadow-xs transition hover:bg-accent"
                      onClick={() => handleDeleteRecord(record.sessionId)}
                      type="button"
                    >
                      删除记录
                    </button>
                    <Link
                      className="w-fit rounded-md border border-brand bg-brand px-3 py-2 text-xs font-medium text-white shadow-xs transition hover:bg-[#2F6868]/90"
                      href={record.reportUrl}
                    >
                      打开报告
                    </Link>
                  </div>
                </div>
              </article>
            ))}
          </section>
        ) : (
          <section className="rounded-2xl border border-dashed border-border bg-background p-8 text-center shadow-xs">
            <h2 className="text-base font-semibold">暂无训练记录</h2>
            <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
              在工作台完成一次诊断提交并生成评分报告后，点击“保存训练记录”即可在这里看到本机历史。
            </p>
            <Link
              className="mt-5 inline-flex rounded-md border border-brand bg-brand px-4 py-2 text-sm font-medium text-white shadow-xs transition hover:bg-[#2F6868]/90"
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
