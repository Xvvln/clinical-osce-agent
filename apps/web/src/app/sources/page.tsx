import Link from "next/link";

type SourceReferenceType = Readonly<{
  label: string;
  example: string;
  description: string;
}>;

type RegisteredSource = Readonly<{
  sourceId: string;
  sourceName: string;
  dataType: string;
  license: string;
  allowedUsage: string;
  transformation: string;
  riskNote: string;
}>;

const referenceTypes: readonly SourceReferenceType[] = [
  {
    label: "case",
    example: "case:appendicitis_001",
    description: "指向当前训练使用的结构化病例 JSON。",
  },
  {
    label: "source",
    example: "source:fareez_osce_2022",
    description: "指向病例加工时登记的公开数据或参考工程来源。",
  },
  {
    label: "rubric",
    example: "rubric:appendicitis_001_rubric.item.ht_location",
    description: "指向评分报告中命中或漏项对应的 rubric 条目。",
  },
  {
    label: "evidence",
    example: "evidence:lab.cbc",
    description: "指向本轮训练实际披露、请求或提交过的证据。",
  },
];

const registeredSources: readonly RegisteredSource[] = [
  {
    sourceId: "fareez_osce_2022",
    sourceName: "A dataset of simulated patient-physician medical interviews with a focus on respiratory cases",
    dataType: "dialogue",
    license: "CC BY 4.0",
    allowedUsage: "training_reference / evaluation_reference / demo_reference",
    transformation: "下载原始 zip 后抽取、翻译、改写并转换为结构化 OSCE 病例资产。",
    riskNote: "原始数据偏呼吸系统问诊，不足以直接覆盖完整病例闭环。",
  },
  {
    sourceId: "meditod_2024",
    sourceName: "MediTOD",
    dataType: "dialogue_annotations",
    license: "See repository license and dataset notes",
    allowedUsage: "intent_reference / evaluation_reference",
    transformation: "克隆公开仓库，用公开对话文件研究意图 schema 和标注结构。",
    riskNote: "canonicalized 数据需要 UMLS 许可与申请，不自动拉取。",
  },
  {
    sourceId: "medcase_reasoning_2025",
    sourceName: "MedCaseReasoning",
    dataType: "reasoning",
    license: "See dataset card",
    allowedUsage: "reasoning_reference / evaluation_reference",
    transformation: "下载公开 parquet 文件，用于诊断推理点和鉴别诊断素材提炼。",
    riskNote: "病例报告复杂度较高，不能直接作为新手病例。",
  },
  {
    sourceId: "case_report_collective_2025",
    sourceName: "CaseReportCollective",
    dataType: "structured_case_reports",
    license: "CC-BY-4.0",
    allowedUsage: "expansion_reference",
    transformation: "下载公开 parquet 文件，作为后续结构化筛选和扩展病例素材。",
    riskNote: "仅作为二期扩展数据源，MVP 不直接入库。",
  },
  {
    sourceId: "easymed_repo",
    sourceName: "EasyMED",
    dataType: "framework_reference",
    license: "See repository license",
    allowedUsage: "architecture_reference / evaluation_reference",
    transformation: "克隆公开仓库，参考患者模拟、意图识别和评测设计。",
    riskNote: "仅借鉴教育评测模块，不直接照搬产品形态。",
  },
];

export default function SourcesPage() {
  return (
    <main className="min-h-screen bg-muted/40 px-4 py-6 text-foreground">
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        <header className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                Clinical OSCE Agent
              </p>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight">数据来源说明</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                本页说明评分报告中来源引用的含义，以及当前公开数据和参考工程的登记范围。
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
              <p className="text-sm font-semibold text-brand">来源登记口径</p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight">当前公开来源以 source registry 为准。</h2>
            </div>
            <span className="w-fit rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
              5 条登记源
            </span>
          </div>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-muted-foreground">
            MVP 运行时直接使用的是 data/cases 与 data/rubrics 中的结构化资产，data/raw 中的原始公开数据只作为加工参考，不直接暴露给学生端训练流程。
          </p>
        </section>

        <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <h2 className="text-sm font-semibold">报告引用类型</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            评分报告中的 source_references 会使用以下稳定前缀，便于追溯病例、来源、评分依据和训练证据。
          </p>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {referenceTypes.map((item) => (
              <article className="rounded-xl border border-border bg-muted/40 p-4" key={item.label}>
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-sm font-semibold">{item.label}</h3>
                  <p className="font-mono text-[11px] text-muted-foreground">{item.example}</p>
                </div>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">{item.description}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
            <div>
              <h2 className="text-sm font-semibold">已登记公开来源</h2>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                以下内容对应 data/attribution/source_registry/sources.json 的当前登记范围。
              </p>
            </div>
            <span className="w-fit rounded-full border border-border bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
              attribution required
            </span>
          </div>
          <div className="mt-4 grid gap-3">
            {registeredSources.map((source) => (
              <article className="rounded-xl border border-border bg-muted/40 p-4" key={source.sourceId}>
                <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <p className="font-mono text-[11px] text-brand">{source.sourceId}</p>
                    <h3 className="mt-1 text-sm font-semibold">{source.sourceName}</h3>
                  </div>
                  <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                    <span className="rounded-full border border-border bg-background px-2 py-1">{source.dataType}</span>
                    <span className="rounded-full border border-border bg-background px-2 py-1">{source.license}</span>
                  </div>
                </div>
                <dl className="mt-4 grid gap-3 text-sm md:grid-cols-3">
                  <div>
                    <dt className="text-xs font-medium text-foreground">允许用途</dt>
                    <dd className="mt-1 leading-6 text-muted-foreground">{source.allowedUsage}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-foreground">加工方式</dt>
                    <dd className="mt-1 leading-6 text-muted-foreground">{source.transformation}</dd>
                  </div>
                  <div>
                    <dt className="text-xs font-medium text-foreground">风险说明</dt>
                    <dd className="mt-1 leading-6 text-muted-foreground">{source.riskNote}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
