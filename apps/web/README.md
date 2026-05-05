# apps/web

`apps/web` 承接 `references/agent-chat-ui` 的裁剪与改造，目标是实现 OSCE 三栏工作台。

## 当前状态

已建立最小 Next.js + TypeScript 前端骨架，并实现 OSCE 三栏工作台：

- 左侧：病例信息、病例选择入口、训练阶段；
- 中间：医患对话区与问诊输入栏；
- 右侧：已收集线索、诊断假设、查体/检查申请、评分报告。

当前已接入最小后端 session API：页面加载后创建训练会话，问诊输入会调用 `/api/sessions/{session_id}/message` 并展示标准化病人回复；查体和辅助检查快捷项会随当前病例 session 返回的 `physical_exam_options` 与 `auxiliary_test_options` 动态渲染，并分别调用 `/api/sessions/{session_id}/physical-exam` 与 `/api/sessions/{session_id}/auxiliary-test` 展示返回结果；诊断提交区会随当前病例 session 返回的 `diagnosis_draft` 初始化默认诊断与推理依据，提交时调用 `/api/sessions/{session_id}/submit-diagnosis`，随后读取 `/api/sessions/{session_id}/report` 并在右侧展示结构化评分报告，包括总分、维度进度、亮点、推理问题、下一轮训练重点，以及按 `case`、`source`、`rubric`、`evidence` 分组展示的来源引用。

病例选择入口已在左侧落地，并会从 `/api/cases` 读取 `data/cases/*.json` 生成的学生可见病例摘要；独立病例选择页 `/cases` 已接入，可展示 5 个结构化病例并跳转工作台创建对应训练 session，但不再读取完整病例 raw JSON；当前 5 个结构化病例均可创建训练 session，查体、辅助检查按钮和诊断提交草稿已按病例数据动态切换。

工作台顶部已接入安全声明和数据来源两个小入口；独立安全声明页 `/safety` 用于集中展示教学模拟、真实诊疗边界、急症提示和输出边界清单，独立数据来源页 `/sources` 用于解释 `case`、`source`、`rubric`、`evidence` 四类来源引用，并展示 5 条公开来源登记、加工方式、许可和风险说明。

学生端已关闭 Next.js 开发模式自带悬浮 indicator，并在左下角实现自有 OSCE Dock：圆形入口可展开病例、记录、画像、安全、来源、报告、过程提示和患者信息等快捷操作。该入口只调用既有学生端页面和训练 API，不参与诊断裁判或评分逻辑。

独立评分报告路由已接入，工作台生成报告后可打开 `/report?session_id=...` 查看集中式报告；报告页包含总分环形视图、维度雷达雏形、维度进度条、强弱项摘要、训练建议、按类型分组的来源引用，以及复制当前报告链接的分享入口。

工作台已接入本地训练记录保存入口，生成报告后可将 session、病例、总分、保存时间和报告链接写入浏览器 `localStorage`；独立训练记录页 `/history` 会展示本机已保存记录，支持删除单条记录或清空全部记录，并可跳转对应报告。

本阶段尚未接入 LangGraph SDK streaming、后端报告持久化或跨设备分享。

## 设计风格

新增页面以 `references/agent-chat-ui` 为主要视觉参考，沿用 Inter 字体、Tailwind v4 design tokens、浅色卡片、细边框、圆角、低强度阴影和 `#2F6868` brand 按钮。

Tailwind v4 通过 `postcss.config.mjs` 加载 `@tailwindcss/postcss`，确保响应式 utility classes 正常生成。

## 本地运行

先启动后端 API 服务：

```bash
cd "F:/杂物/个人开发/clinical-osce-agent"
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate base && uvicorn app.main:app --app-dir services/api --reload --host 127.0.0.1 --port 8000
```

再启动前端：

```bash
cd "F:/杂物/个人开发/clinical-osce-agent/apps/web"
corepack pnpm install
corepack pnpm dev
```

打开浏览器访问 `http://127.0.0.1:3000`。如果 3000 端口被占用，Next.js 会在终端提示实际端口，例如 `http://127.0.0.1:3001`。

## 常用命令

```bash
corepack pnpm typecheck
corepack pnpm build
corepack pnpm dev
```
