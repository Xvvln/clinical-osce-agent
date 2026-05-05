"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type StudentVisiblePatientProfile = Readonly<{
  age: string;
  gender: string;
  occupation: string;
  hospital_department: string;
}>;

type OpeningTaskCard = Readonly<{
  role: string;
  scenario: string;
  tasks: readonly string[];
}>;

type PhysicalExamQuickOption = Readonly<{
  exam_code: string;
  exam_name_cn: string;
}>;

type AuxiliaryTestQuickOption = Readonly<{
  test_code: string;
  test_name_cn: string;
  category: string;
}>;

type CaseSummary = Readonly<{
  case_id: string;
  case_title: string;
  course_module: string;
  difficulty: string;
  chief_complaint: string;
  enabled: boolean;
  patient_profile: StudentVisiblePatientProfile;
  opening_task_card: OpeningTaskCard;
  physical_exam_options: readonly PhysicalExamQuickOption[];
  auxiliary_test_options: readonly AuxiliaryTestQuickOption[];
}>;

type CaseListResponse = Readonly<{
  cases: readonly CaseSummary[];
}>;

async function getCases(): Promise<readonly CaseSummary[]> {
  const response = await fetch("/api/cases", {
    method: "GET",
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `读取病例列表失败：${response.status}`);
  }

  const result = (await response.json()) as CaseListResponse;
  return result.cases;
}

function getDifficultyLabel(difficulty: string): string {
  if (difficulty === "beginner") {
    return "初级";
  }

  if (difficulty === "intermediate") {
    return "进阶";
  }

  return difficulty;
}

export default function CasesPage() {
  const [cases, setCases] = useState<readonly CaseSummary[]>([]);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;

    async function loadCases() {
      try {
        const nextCases = await getCases();
        if (!isMounted) {
          return;
        }

        setCases(nextCases);
        setErrorText(null);
      } catch (error) {
        if (!isMounted) {
          return;
        }

        setErrorText(error instanceof Error ? error.message : "读取病例列表失败。");
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    loadCases();

    return () => {
      isMounted = false;
    };
  }, []);

  return (
    <main className="min-h-screen bg-muted/40 px-4 py-6 text-foreground">
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        <header className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                Clinical OSCE Agent
              </p>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight">病例选择</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                从结构化教学病例中选择一个 OSCE 训练场景。进入工作台后会先展示病例准备态和开局任务卡，首次训练动作才创建后端 session。
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
              <p className="text-sm font-semibold text-brand">训练病例库</p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight">
                {isLoading ? "正在读取病例列表。" : `当前开放 ${cases.length} 个结构化病例。`}
              </h2>
            </div>
            <span className="w-fit rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
              /api/cases
            </span>
          </div>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-muted-foreground">
            本页只展示学生可见的教学病例摘要、主诉和训练入口；完整病例事实、标准答案、查体/检查结果和 Rubric 详情仅在管理端台账中查看。
          </p>
        </section>

        {errorText ? (
          <section className="rounded-2xl border border-destructive/20 bg-destructive/5 p-5 text-sm text-destructive shadow-xs">
            {errorText}
          </section>
        ) : null}

        {isLoading ? (
          <section className="rounded-2xl border border-border bg-background p-8 text-center shadow-xs">
            <h2 className="text-base font-semibold">正在加载病例</h2>
            <p className="mt-2 text-sm text-muted-foreground">请确认本地 FastAPI 服务已启动并开放 `/api/cases`。</p>
          </section>
        ) : (
          <section className="grid gap-3 md:grid-cols-2">
            {cases.map((caseSummary) => (
              <article className="rounded-2xl border border-border bg-background p-5 shadow-xs" key={caseSummary.case_id}>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="font-mono text-[11px] text-muted-foreground">{caseSummary.case_id}</p>
                    <h2 className="mt-2 text-base font-semibold tracking-tight">{caseSummary.case_title}</h2>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      主诉：{caseSummary.chief_complaint}
                    </p>
                  </div>
                  <span className="w-fit rounded-full border border-brand/20 bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
                    {caseSummary.enabled ? "可训练" : "待接入"}
                  </span>
                </div>

                <div className="mt-4 flex flex-wrap gap-2 text-xs">
                  <span className="rounded-full border border-border bg-muted px-3 py-1 font-medium text-muted-foreground">
                    {caseSummary.course_module}
                  </span>
                  <span className="rounded-full border border-border bg-muted px-3 py-1 font-medium text-muted-foreground">
                    {getDifficultyLabel(caseSummary.difficulty)}
                  </span>
                </div>

                <div className="mt-5 flex flex-wrap gap-2 border-t border-border pt-4">
                  {caseSummary.enabled ? (
                    <Link
                      className="inline-flex items-center justify-center rounded-md border border-brand bg-brand px-4 py-2 text-sm font-medium whitespace-nowrap text-white shadow-xs transition hover:bg-brand-hover"
                      href={`/?case_id=${encodeURIComponent(caseSummary.case_id)}`}
                    >
                      选择并进入工作台
                    </Link>
                  ) : (
                    <button
                      className="rounded-md border border-border bg-muted px-4 py-2 text-sm font-medium whitespace-nowrap text-muted-foreground"
                      disabled
                      type="button"
                    >
                      暂未开放训练
                    </button>
                  )}
                </div>
              </article>
            ))}
          </section>
        )}
      </div>
    </main>
  );
}
