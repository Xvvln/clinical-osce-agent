"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type TrainingDifficultyMode = "beginner" | "intermediate" | "advanced";

type TrainingDifficultyOption = Readonly<{
  mode: TrainingDifficultyMode;
  label: string;
  description: string;
}>;

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

type CaseTeachingErrorPattern = Readonly<{
  pattern_id: string;
  title: string;
  focus: string;
  related_rubric_items: readonly string[];
}>;

type CaseTeachingFocus = Readonly<{
  learning_objectives: readonly string[];
  common_error_patterns: readonly CaseTeachingErrorPattern[];
  recommended_training_path: readonly string[];
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

type CaseContentStats = Readonly<{
  history_clue_count: number;
  physical_exam_count: number;
  auxiliary_test_count: number;
  total_training_items: number;
}>;

type CaseSummary = Readonly<{
  case_id: string;
  case_title: string;
  course_module: string;
  difficulty: string;
  chief_complaint: string;
  enabled: boolean;
  content_stats: CaseContentStats;
  patient_profile: StudentVisiblePatientProfile;
  opening_task_card: OpeningTaskCard;
  teaching_focus: CaseTeachingFocus;
  physical_exam_options: readonly PhysicalExamQuickOption[];
  auxiliary_test_options: readonly AuxiliaryTestQuickOption[];
}>;

type CaseListResponse = Readonly<{
  cases: readonly CaseSummary[];
}>;

const RECOMMENDED_CASE_ID = "appendicitis_001";
const TRAINING_DIFFICULTY_OPTIONS: readonly TrainingDifficultyOption[] = [
  {
    mode: "beginner",
    label: "初级",
    description: "直接点选病例提供的核心查体与检查，适合先熟悉 OSCE 训练流程。",
  },
  {
    mode: "intermediate",
    label: "中级",
    description: "从完整目录里勾选查体或辅助检查，提交后统一返回所选项目结果。",
  },
  {
    mode: "advanced",
    label: "高级",
    description: "自由输入想申请的查体或检查；已有数据直接返回，缺失项目由 AI 教学模拟并标注不计分。",
  },
];

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

function getCaseTrainingItemTotal(caseSummary: CaseSummary): number {
  return caseSummary.content_stats.total_training_items;
}

function sortCasesByTrainingContent(nextCases: readonly CaseSummary[]): readonly CaseSummary[] {
  return [...nextCases].sort((leftCase, rightCase) => {
    const totalDifference = getCaseTrainingItemTotal(rightCase) - getCaseTrainingItemTotal(leftCase);
    if (totalDifference !== 0) {
      return totalDifference;
    }
    return leftCase.case_title.localeCompare(rightCase.case_title, "zh-Hans-CN");
  });
}

function getDifficultyLabel(difficulty: string): string {
  if (difficulty === "beginner") {
    return "初级";
  }

  if (difficulty === "intermediate") {
    return "中级";
  }

  if (difficulty === "advanced") {
    return "高级";
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

        setCases(sortCasesByTrainingContent(nextCases));
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
                临境 OSCE 智能体（TraceOSCE）
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

        {errorText ? (
          <section className="rounded-2xl border border-destructive/20 bg-destructive/5 p-5 text-sm text-destructive shadow-xs">
            {errorText}
          </section>
        ) : null}

        {isLoading ? (
          <section className="rounded-2xl border border-border bg-background p-8 text-center shadow-xs">
            <h2 className="text-base font-semibold">正在加载病例</h2>
            <p className="mt-2 text-sm text-muted-foreground">正在读取当前可训练病例。</p>
          </section>
        ) : (
          <section className="grid gap-3 md:grid-cols-2">
            {cases.map((caseSummary) => {
              const isRecommendedCase = caseSummary.case_id === RECOMMENDED_CASE_ID;
              return (
                <article
                  className={`rounded-2xl border p-5 shadow-xs ${
                    isRecommendedCase ? "border-brand/35 bg-brand/10" : "border-border bg-background"
                  }`}
                  key={caseSummary.case_id}
                >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="font-mono text-[11px] text-muted-foreground">{caseSummary.case_id}</p>
                    <h2 className="mt-2 text-base font-semibold tracking-tight">{caseSummary.case_title}</h2>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      主诉：{caseSummary.chief_complaint}
                    </p>
                  </div>
                  <div className="flex flex-wrap justify-start gap-2 sm:justify-end">
                    {isRecommendedCase ? (
                      <span className="w-fit rounded-full border border-brand/25 bg-brand px-3 py-1 text-xs font-semibold text-white">
                        推荐
                      </span>
                    ) : null}
                    <span className="w-fit rounded-full border border-brand/20 bg-brand/5 px-3 py-1 text-xs font-medium text-brand">
                      {caseSummary.enabled ? "可训练" : "待接入"}
                    </span>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-2 text-xs">
                  <span className="rounded-full border border-border bg-muted px-3 py-1 font-medium text-muted-foreground">
                    {caseSummary.course_module}
                  </span>
                  <span className="rounded-full border border-border bg-muted px-3 py-1 font-medium text-muted-foreground">
                    {getDifficultyLabel(caseSummary.difficulty)}
                  </span>
                  <span className="rounded-full border border-border bg-background px-3 py-1 font-medium text-foreground">
                    {caseSummary.content_stats.history_clue_count} 条线索
                  </span>
                  <span className="rounded-full border border-border bg-background px-3 py-1 font-medium text-muted-foreground">
                    {caseSummary.content_stats.physical_exam_count} 项查体
                  </span>
                  <span className="rounded-full border border-border bg-background px-3 py-1 font-medium text-muted-foreground">
                    {caseSummary.content_stats.auxiliary_test_count} 项检查
                  </span>
                  <span className="rounded-full border border-border bg-background px-3 py-1 font-medium text-muted-foreground">
                    共 {caseSummary.content_stats.total_training_items} 项训练素材
                  </span>
                </div>

                <div className="mt-5 grid gap-2 border-t border-border pt-4">
                  <p className="text-xs font-semibold text-muted-foreground">选择训练难度</p>
                  {caseSummary.enabled ? (
                    <div className="grid gap-2">
                      {TRAINING_DIFFICULTY_OPTIONS.map((difficultyOption) => (
                        <Link
                          className="group rounded-2xl border border-border bg-background px-3 py-2.5 text-left shadow-xs transition hover:border-brand/35 hover:bg-brand-hover/5"
                          href={`/?case_id=${encodeURIComponent(caseSummary.case_id)}&difficulty=${difficultyOption.mode}`}
                          key={difficultyOption.mode}
                        >
                          <span className="flex flex-wrap items-center justify-between gap-2">
                            <span className="inline-flex rounded-full border border-border bg-muted px-3 py-1 text-xs font-semibold whitespace-nowrap text-foreground transition group-hover:border-brand/30 group-hover:bg-brand group-hover:text-white">
                              {difficultyOption.label}
                            </span>
                            <span className="text-xs font-medium whitespace-nowrap text-brand">
                              选择{difficultyOption.label}并进入工作台
                            </span>
                          </span>
                          <span className="mt-2 block text-xs leading-5 text-muted-foreground">
                            {difficultyOption.description}
                          </span>
                        </Link>
                      ))}
                    </div>
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
              );
            })}
          </section>
        )}
      </div>
    </main>
  );
}
