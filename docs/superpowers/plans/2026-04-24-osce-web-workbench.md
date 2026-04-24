# OSCE Web Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Step 6 frontend slice: a runnable static OSCE three-column workbench in `apps/web`, styled after `references/agent-chat-ui`.

**Architecture:** `apps/web` will be an independent Next.js App Router application. The first slice stays static and does not call the backend, LangGraph SDK, or session APIs. UI styles copy the visual language of Agent Chat UI: Inter font, Tailwind v4 design tokens, light cards, subtle borders, rounded corners, muted panels, and brand `#2F6868` buttons.

**Tech Stack:** Next.js 15, React 19, TypeScript 5.7, Tailwind CSS 4, pnpm scripts.

---

## File Structure

- Create: `apps/web/package.json` — frontend package metadata, scripts, and dependencies aligned with Agent Chat UI versions.
- Create: `apps/web/next-env.d.ts` — Next.js TypeScript ambient declarations.
- Create: `apps/web/tsconfig.json` — strict TypeScript configuration for the web app.
- Create: `apps/web/postcss.config.mjs` — Tailwind v4 PostCSS plugin configuration.
- Create: `apps/web/src/app/layout.tsx` — root layout, metadata, Inter font, global CSS import, favicon metadata.
- Create: `apps/web/src/app/globals.css` — Tailwind v4 import, Agent Chat UI design tokens, base styles, utility shadows.
- Create: `apps/web/src/app/page.tsx` — static OSCE workbench page with typed data and three-column layout.
- Create: `apps/web/public/favicon.svg` — brand-colored favicon to avoid browser favicon 404.
- Modify: `apps/web/README.md` — replace placeholder status with run/build instructions and current slice scope.
- Modify: `项目开发文档.md` — append Step 6 execution note after implementation succeeds.

## Task 1: Create the minimal Next.js app shell

**Files:**
- Create: `apps/web/package.json`
- Create: `apps/web/next-env.d.ts`
- Create: `apps/web/tsconfig.json`

- [ ] **Step 1: Write package metadata and scripts**

Create `apps/web/package.json` with this exact content:

```json
{
  "name": "clinical-osce-web",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "@tailwindcss/postcss": "^4.2.1",
    "next": "^15.5.14",
    "react": "^19.1.0",
    "react-dom": "^19.1.0",
    "tailwindcss": "^4.2.1"
  },
  "devDependencies": {
    "@types/node": "^22.15.18",
    "@types/react": "^19.1.4",
    "@types/react-dom": "^19.1.5",
    "typescript": "~5.7.3"
  },
  "packageManager": "pnpm@10.5.1"
}
```

- [ ] **Step 2: Add Next.js ambient declarations**

Create `apps/web/next-env.d.ts` with this exact content:

```ts
/// <reference types="next" />
/// <reference types="next/image-types/global" />
```

- [ ] **Step 3: Add strict TypeScript config**

Create `apps/web/tsconfig.json` with this exact content:

```json
{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 4: Verify the shell files exist**

Run:

```bash
ls "F:/杂物/个人开发/clinical-osce-agent/.worktrees/step6-osce-web-workbench/apps/web/package.json" "F:/杂物/个人开发/clinical-osce-agent/.worktrees/step6-osce-web-workbench/apps/web/next-env.d.ts" "F:/杂物/个人开发/clinical-osce-agent/.worktrees/step6-osce-web-workbench/apps/web/tsconfig.json"
```

Expected: all three paths are printed without `No such file or directory`.

## Task 2: Add Agent Chat UI aligned layout and global styles

**Files:**
- Create: `apps/web/src/app/layout.tsx`
- Create: `apps/web/src/app/globals.css`

- [ ] **Step 1: Create the App Router layout**

Create `apps/web/src/app/layout.tsx` with this exact content:

```tsx
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  preload: true,
  display: "swap",
});

export const metadata: Metadata = {
  title: "问诊推理舱",
  description: "OSCE diagnostic reasoning training workbench",
};

type RootLayoutProps = Readonly<{
  children: ReactNode;
}>;

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="zh-CN">
      <body className={inter.className}>{children}</body>
    </html>
  );
}
```

- [ ] **Step 2: Create global Tailwind and token styles**

Create `apps/web/src/app/globals.css` with this exact content:

```css
@import "tailwindcss";

:root {
  --background: oklch(1 0 0);
  --foreground: oklch(0.145 0 0);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.145 0 0);
  --primary: oklch(0.205 0 0);
  --primary-foreground: oklch(0.985 0 0);
  --secondary: oklch(0.97 0 0);
  --secondary-foreground: oklch(0.205 0 0);
  --muted: oklch(0.97 0 0);
  --muted-foreground: oklch(0.556 0 0);
  --accent: oklch(0.97 0 0);
  --accent-foreground: oklch(0.205 0 0);
  --border: oklch(0.922 0 0);
  --input: oklch(0.922 0 0);
  --ring: oklch(0.87 0 0);
  --radius: 0.625rem;
  --brand: #2f6868;
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
}

@layer base {
  * {
    @apply border-border outline-ring/50;
  }

  body {
    @apply bg-background text-foreground;
  }
}

@layer utilities {
  .shadow-inner-right {
    box-shadow: inset -9px 0 6px -1px rgb(0 0 0 / 0.02);
  }

  .shadow-inner-left {
    box-shadow: inset 9px 0 6px -1px rgb(0 0 0 / 0.02);
  }

  .bg-brand {
    background-color: var(--brand);
  }

  .text-brand {
    color: var(--brand);
  }

  .border-brand {
    border-color: var(--brand);
  }
}
```

- [ ] **Step 3: Verify TypeScript can resolve the layout file**

Run:

```bash
cd "F:/杂物/个人开发/clinical-osce-agent/.worktrees/step6-osce-web-workbench/apps/web" && pnpm typecheck
```

Expected before dependencies are installed: command may fail with `pnpm: command not found` or missing `node_modules`. If dependencies are already installed, expected PASS with no TypeScript errors.

## Task 3: Implement the static OSCE three-column workbench

**Files:**
- Create: `apps/web/src/app/page.tsx`

- [ ] **Step 1: Create typed static page data and UI**

Create `apps/web/src/app/page.tsx` with this exact content:

```tsx
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
```

- [ ] **Step 2: Run TypeScript check**

Run:

```bash
cd "F:/杂物/个人开发/clinical-osce-agent/.worktrees/step6-osce-web-workbench/apps/web" && pnpm typecheck
```

Expected after dependencies are installed: PASS with no TypeScript errors.

- [ ] **Step 3: Run production build**

Run:

```bash
cd "F:/杂物/个人开发/clinical-osce-agent/.worktrees/step6-osce-web-workbench/apps/web" && pnpm build
```

Expected: Next.js build completes successfully and reports static route `/`.

## Task 4: Update docs for the frontend slice

**Files:**
- Modify: `apps/web/README.md`
- Modify: `项目开发文档.md`

- [ ] **Step 1: Replace the web README placeholder**

Replace `apps/web/README.md` with this exact content:

```markdown
# apps/web

`apps/web` 承接 `references/agent-chat-ui` 的裁剪与改造，目标是实现 OSCE 三栏工作台。

## 当前状态

已建立最小 Next.js + TypeScript 前端骨架，并实现静态 OSCE 三栏工作台：

- 左侧：病例信息、训练阶段、可用操作；
- 中间：医患对话区与输入栏占位；
- 右侧：已收集线索、诊断假设、查体/检查申请、评分预览。

本阶段尚未接入后端 session API、LangGraph SDK streaming 或评分报告页。

## 设计风格

新增页面以 `references/agent-chat-ui` 为主要视觉参考，沿用 Inter 字体、Tailwind v4 design tokens、浅色卡片、细边框、圆角、低强度阴影和 `#2F6868` brand 按钮。

## 常用命令

```bash
pnpm typecheck
pnpm build
pnpm dev
```
```

- [ ] **Step 2: Append Step 6 execution note to project development doc**

Append this exact note to the latest execution log or changelog section in `项目开发文档.md`:

```markdown
### 2026-04-24 · Step 6 前端 OSCE 工作台静态骨架

- 在 `apps/web` 建立最小 Next.js + TypeScript 前端骨架。
- 首页实现静态 OSCE 三栏工作台：左侧病例与阶段面板、中间医患对话区、右侧推理与评分预览面板。
- 视觉风格以 `references/agent-chat-ui` 为主，沿用 Inter 字体、Tailwind v4 token、浅色卡片、细边框、圆角和 `#2F6868` brand 按钮。
- 当前不接后端 API、不接 LangGraph SDK streaming、不实现评分报告页；后续 Step 6 小单元再接入 session 创建、对话提交和报告跳转。
- 验证：`pnpm typecheck` 与 `pnpm build`。
```

- [ ] **Step 3: Run verification again after docs update**

Run:

```bash
cd "F:/杂物/个人开发/clinical-osce-agent/.worktrees/step6-osce-web-workbench/apps/web" && pnpm typecheck && pnpm build
```

Expected: both commands pass.

## Task 5: Final verification and handoff

**Files:**
- Read/check: `apps/web/package.json`
- Read/check: `apps/web/src/app/page.tsx`
- Read/check: `apps/web/README.md`
- Read/check: `项目开发文档.md`

- [ ] **Step 1: Check working tree changes**

Run:

```bash
git status --short "F:/杂物/个人开发/clinical-osce-agent/.worktrees/step6-osce-web-workbench/apps/web" "F:/杂物/个人开发/clinical-osce-agent/docs/superpowers" "F:/杂物/个人开发/clinical-osce-agent/项目开发文档.md"
```

Expected: only the planned web app files, design/plan docs, and project development doc are shown for this slice.

- [ ] **Step 2: Verify no backend files changed in this slice**

Run:

```bash
git status --short "F:/杂物/个人开发/clinical-osce-agent/services/api" "F:/杂物/个人开发/clinical-osce-agent/data"
```

Expected: no new changes caused by this frontend slice. Pre-existing changes from earlier work may still appear; do not modify them here.

- [ ] **Step 3: Summarize completion**

Report these items to the user:

```text
已完成 Step 6 前端第一个小单元：apps/web 最小 Next.js + TypeScript 静态 OSCE 三栏工作台。
验证命令：pnpm typecheck；pnpm build。
潜在问题：尚未接入后端 API；尚未验证真实浏览器交互；依赖安装可能受网络代理影响。
建议测试用例：打开首页检查三栏布局；缩放到窄屏确认右栏下移；后续接入 session API 后测试问诊提交和报告跳转。
```

## Self-Review

- Spec coverage: this plan covers the static runnable `apps/web` shell, Agent Chat UI aligned visual style, three-column workbench, TypeScript validation, and project docs update. It intentionally excludes backend API integration, LangGraph SDK streaming, scoring report page, and admin work.
- Placeholder scan: no `TBD`, `TODO`, `implement later`, or vague implementation steps remain.
- Type consistency: `Stage`, `Message`, and `EvidenceItem` are defined before use; `getStageClass` consumes `Stage["status"]`; page props and layout props use explicit TypeScript types.
