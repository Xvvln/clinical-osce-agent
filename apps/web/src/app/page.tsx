type Stage = {
  readonly label: string;
  readonly status: "done" | "active" | "locked";
};

type Message = {
  readonly speaker: "student" | "patient";
  readonly label: string;
  readonly text: string;
};

type EvidenceItem = {
  readonly label: string;
  readonly detail: string;
};

const stages: readonly Stage[] = [
  { label: "阅读主诉", status: "done" },
  { label: "问诊", status: "active" },
  { label: "查体", status: "locked" },
  { label: "辅助检查", status: "locked" },
  { label: "诊断提交", status: "locked" },
  { label: "复盘反馈", status: "locked" },
];

const messages: readonly Message[] = [
  {
    speaker: "patient",
    label: "标准化病人",
    text: "医生您好，我从昨晚开始右下腹疼，走路时会更明显。",
  },
  {
    speaker: "student",
    label: "学生",
    text: "疼痛是一开始就在右下腹，还是从其他位置转移过来的？",
  },
  {
    speaker: "patient",
    label: "标准化病人",
    text: "一开始像是在肚脐周围，后来慢慢转到右下腹。",
  },
];

const evidenceItems: readonly EvidenceItem[] = [
  { label: "起病时间", detail: "昨晚开始，持续存在" },
  { label: "疼痛迁移", detail: "脐周转移至右下腹" },
  { label: "伴随表现", detail: "轻度恶心，暂未披露发热" },
];

const examRequests: readonly string[] = ["腹部触诊", "右下腹反跳痛", "生命体征"];
const hypotheses: readonly string[] = ["急性阑尾炎", "胃肠炎", "泌尿系结石"];
const scoringPreview: readonly string[] = ["已命中：起病时间", "待补充：疼痛部位", "待补充：鉴别诊断"];

function getStageClass(status: Stage["status"]): string {
  if (status === "done") {
    return "border-brand/20 bg-[#2F6868]/10 text-brand";
  }

  if (status === "active") {
    return "border-brand bg-brand text-white shadow-sm";
  }

  return "border-border bg-muted text-muted-foreground";
}

function Panel({
  title,
  description,
  children,
}: Readonly<{
  title: string;
  description?: string;
  children: React.ReactNode;
}>) {
  return (
    <section className="rounded-xl border border-border bg-card p-4 shadow-xs">
      <div className="mb-4 space-y-1">
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        {description ? (
          <p className="text-xs leading-5 text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {children}
    </section>
  );
}

export default function Home() {
  return (
    <main className="flex min-h-screen bg-muted/40 text-foreground">
      <aside className="hidden w-80 shrink-0 border-r border-border bg-background p-4 shadow-inner-right lg:block">
        <div className="mb-6">
          <p className="text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
            Clinical OSCE Agent
          </p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">问诊推理舱</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            基于公开 OSCE 病例数据的诊断学临床思维训练工作台。
          </p>
        </div>

        <Panel title="当前病例" description="MVP 示例病例 · 教学模拟">
          <div className="space-y-3 text-sm">
            <div className="rounded-lg border border-border bg-muted/60 p-3">
              <p className="text-xs text-muted-foreground">主诉</p>
              <p className="mt-1 font-medium">右下腹痛 12 小时</p>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-md bg-muted p-2">
                <p className="text-muted-foreground">年龄</p>
                <p className="mt-1 font-medium">22 岁</p>
              </div>
              <div className="rounded-md bg-muted p-2">
                <p className="text-muted-foreground">场景</p>
                <p className="mt-1 font-medium">急诊问诊</p>
              </div>
            </div>
          </div>
        </Panel>

        <div className="mt-4">
          <Panel title="训练阶段">
            <div className="space-y-2">
              {stages.map((stage) => (
                <div
                  className={`rounded-md border px-3 py-2 text-sm font-medium ${getStageClass(stage.status)}`}
                  key={stage.label}
                >
                  {stage.label}
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 items-center justify-between border-b border-border bg-background px-5">
          <div>
            <p className="text-xs text-muted-foreground">OSCE 工作台</p>
            <h2 className="text-base font-semibold">问诊阶段 · 右下腹痛病例</h2>
          </div>
          <button className="rounded-md border border-brand bg-brand px-4 py-2 text-sm font-medium text-white shadow-xs transition hover:bg-[#2F6868]/90">
            保存训练记录
          </button>
        </header>

        <div className="grid flex-1 grid-cols-1 gap-4 overflow-hidden p-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="flex min-h-0 flex-col rounded-xl border border-border bg-background shadow-xs">
            <div className="border-b border-border p-4">
              <p className="text-sm font-semibold">医患对话</p>
              <p className="mt-1 text-xs text-muted-foreground">
                中间区域保留 Agent Chat UI 的对话核心体验，后续接入 LangGraph streaming。
              </p>
            </div>

            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              {messages.map((message) => {
                const isStudent = message.speaker === "student";
                return (
                  <div
                    className={`flex ${isStudent ? "justify-end" : "justify-start"}`}
                    key={`${message.speaker}-${message.text}`}
                  >
                    <div
                      className={`max-w-[76%] rounded-xl border px-4 py-3 text-sm leading-6 shadow-xs ${
                        isStudent
                          ? "border-brand bg-[#2F6868] text-white"
                          : "border-border bg-muted text-foreground"
                      }`}
                    >
                      <p className={isStudent ? "text-white/80" : "text-muted-foreground"}>
                        {message.label}
                      </p>
                      <p className="mt-1">{message.text}</p>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="border-t border-border bg-background p-4">
              <div className="rounded-xl border border-input bg-muted/50 p-3">
                <p className="text-sm text-muted-foreground">输入下一句问诊问题，例如：疼痛有没有加重？</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {[
                    "问现病史",
                    "请求查体",
                    "申请辅助检查",
                    "提交诊断",
                  ].map((action) => (
                    <button
                      className="rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium shadow-xs transition hover:bg-accent"
                      key={action}
                    >
                      {action}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <aside className="grid min-h-0 gap-4 overflow-y-auto xl:grid-cols-1">
            <Panel title="已收集线索" description="来自问诊节点的结构化事实占位。">
              <div className="space-y-2">
                {evidenceItems.map((item) => (
                  <div className="rounded-lg border border-border bg-muted/60 p-3" key={item.label}>
                    <p className="text-sm font-medium">{item.label}</p>
                    <p className="mt-1 text-xs leading-5 text-muted-foreground">{item.detail}</p>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="诊断假设">
              <div className="flex flex-wrap gap-2">
                {hypotheses.map((hypothesis) => (
                  <span className="rounded-full border border-border bg-background px-3 py-1 text-xs" key={hypothesis}>
                    {hypothesis}
                  </span>
                ))}
              </div>
            </Panel>

            <Panel title="查体与检查申请">
              <ul className="space-y-2 text-sm">
                {examRequests.map((request) => (
                  <li className="rounded-md bg-muted px-3 py-2" key={request}>
                    {request}
                  </li>
                ))}
              </ul>
            </Panel>

            <Panel title="评分预览" description="仅展示训练过程提示，不提前给出完整答案。">
              <div className="space-y-2">
                {scoringPreview.map((item) => (
                  <p className="rounded-md border border-border bg-background px-3 py-2 text-xs" key={item}>
                    {item}
                  </p>
                ))}
              </div>
            </Panel>
          </aside>
        </div>
      </section>
    </main>
  );
}
