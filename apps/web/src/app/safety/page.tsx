import Link from "next/link";

type SafetySection = Readonly<{
  title: string;
  detail: string;
}>;

const safetySections: readonly SafetySection[] = [
  {
    title: "教学模拟用途",
    detail: "Clinical OSCE Agent 仅用于医学生 OSCE 问诊、查体、检查申请、诊断推理和复盘训练，不构成真实医疗服务。",
  },
  {
    title: "不替代真实诊疗",
    detail: "页面中的标准化病人回复、评分报告、训练建议和来源引用都不能替代医生面诊、临床检查、诊断结论或治疗方案。",
  },
  {
    title: "急症与真实不适边界",
    detail: "如果用户或身边人员存在真实胸痛、呼吸困难、意识改变、剧烈腹痛、持续高热等急症表现，应立即寻求正规医疗服务。",
  },
  {
    title: "评分反馈依据",
    detail: "系统评分只依据结构化病例、rubric、训练过程记录和来源引用，用于教学复盘，不用于判断真实患者病情。",
  },
];

const safetyChecklist: readonly string[] = [
  "不输出具体药物剂量、处方或个体化治疗方案。",
  "不把训练病例回答包装成真实患者诊断结论。",
  "不鼓励用户延误线下就医或忽视急症信号。",
  "所有报告都应保留教学模拟和来源依据说明。",
];

export default function SafetyPage() {
  return (
    <main className="min-h-screen bg-muted/40 px-4 py-6 text-foreground">
      <div className="mx-auto flex max-w-5xl flex-col gap-4">
        <header className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
                Clinical OSCE Agent
              </p>
              <h1 className="mt-2 text-2xl font-semibold tracking-tight">安全声明</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                本页集中说明 OSCE 教学模拟的使用边界，帮助学生、教师和演示评审理解系统输出的适用范围。
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

        <section className="rounded-2xl border border-brand/20 bg-brand/5 p-5 shadow-xs">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-sm font-semibold text-brand">核心结论</p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight">这是教学训练系统，不是真实诊疗系统。</h2>
            </div>
            <span className="w-fit rounded-full border border-brand/20 bg-background px-3 py-1 text-xs font-medium text-brand">
              OSCE 教学边界
            </span>
          </div>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-muted-foreground">
            系统可帮助学习者练习临床问诊思路、证据收集和结构化复盘，但不能用于真实患者的诊断、治疗、分诊或用药决策。
          </p>
        </section>

        <section className="grid gap-4 md:grid-cols-2">
          {safetySections.map((section) => (
            <article className="rounded-2xl border border-border bg-background p-5 shadow-xs" key={section.title}>
              <h2 className="text-sm font-semibold">{section.title}</h2>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">{section.detail}</p>
            </article>
          ))}
        </section>

        <section className="rounded-2xl border border-border bg-background p-5 shadow-xs">
          <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
            <div>
              <h2 className="text-sm font-semibold">输出边界检查清单</h2>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                后续新增反馈、报告或智能体能力时，应继续满足这些边界。
              </p>
            </div>
            <span className="w-fit rounded-full border border-border bg-muted px-3 py-1 text-xs font-medium text-muted-foreground">
              持续适用
            </span>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {safetyChecklist.map((item) => (
              <div className="rounded-xl border border-border bg-muted/40 p-4 text-sm leading-6 text-muted-foreground" key={item}>
                {item}
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
