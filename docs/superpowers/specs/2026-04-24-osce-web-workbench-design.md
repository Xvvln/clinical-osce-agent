# Step 6 OSCE 前端工作台小单元设计

## 背景

`项目开发文档.md` 将前端基座定义为 Agent Chat UI 改造后的 OSCE 工作台。当前 `apps/web` 只有 README 空壳，尚未建立可运行前端。参考项目 `references/agent-chat-ui` 是 Next.js + React + TypeScript 应用，视觉语言以 Inter 字体、Tailwind v4 设计变量、浅色背景、细边框、圆角卡片和 `#2F6868` brand 按钮为主。

## 范围

本小单元只实现可运行的静态 OSCE 三栏工作台骨架，不接后端 API，不接 LangGraph SDK，不实现真实会话流和评分报告页。

## 目标

1. 在 `apps/web` 建立最小 Next.js App Router 前端骨架。
2. 实现 `/` 首页即 OSCE 工作台静态页面。
3. 页面结构对齐开发文档 §10：左侧病例面板、中间医患对话区、右侧推理面板、底部操作入口。
4. 新增内容的视觉风格以 `references/agent-chat-ui` 为主。
5. 保持 TypeScript 类型完整，并通过构建或类型检查。

## 非目标

- 不接 `services/api` 的 session/report API。
- 不引入 LangGraph SDK streaming。
- 不实现病例选择页、评分报告页、学习画像页或管理后台。
- 不一次性复制完整 Agent Chat UI 组件树。

## 推荐 approach

采用轻量迁移 Agent Chat UI 风格的方式，而不是整套复制参考项目前端。

原因：

- 能满足“设计风格以原前端项目为主”。
- 改动范围小，适合作为 Step 6 第一个小单元。
- 避免一次性引入大量 Provider、streaming、artifact、thread history 和 LangGraph 客户端依赖。

## UI 结构

### 左侧病例面板

展示：

- 项目名与训练状态。
- 当前病例主诉与基本信息。
- 当前训练阶段。
- 可用操作占位，例如问诊、查体、辅助检查、提交诊断。

### 中间医患对话区

展示：

- 静态医患对话消息。
- 与 Agent Chat UI 一致的气泡式 message 区域。
- 底部输入栏占位和主操作按钮。

### 右侧推理面板

展示：

- 已收集线索。
- 诊断假设。
- 已申请查体和辅助检查。
- rubric 评分预览占位。

## 视觉约束

- 使用 Inter 字体。
- 使用 Agent Chat UI 的 Tailwind v4 token 风格：`background`、`foreground`、`muted`、`border`、`primary`、`accent` 等。
- 使用浅色背景、细边框、圆角卡片、低强度阴影。
- 主按钮使用 Agent Chat UI 的 brand 色 `#2F6868`。
- 避免医疗系统常见的重蓝色后台风，保持原前端的轻量聊天产品质感。

## 技术设计

- `apps/web/package.json` 定义 Next.js、React、TypeScript、Tailwind 相关依赖与脚本。
- `apps/web/src/app/layout.tsx` 配置 metadata、字体和全局样式。
- `apps/web/src/app/page.tsx` 实现静态工作台页面。
- `apps/web/src/app/globals.css` 承接 Agent Chat UI 的基础 design tokens，并补充少量全局样式。
- 如需工具函数，保持最小化，不提前抽象组件库。

## 验收标准

1. 打开 `apps/web` 能运行或构建 Next.js 应用。
2. 首页呈现三栏 OSCE 工作台。
3. 页面内容体现病例信息、对话、推理面板和操作入口。
4. 视觉风格明显继承 Agent Chat UI，而不是另起一套后台风格。
5. TypeScript 无类型错误。

## 风险与处理

- 依赖安装可能受网络影响：优先使用项目已有代理规则，访问 npm 等国外资源时走 `http://127.0.0.1:7897`。
- Tailwind v4 配置与 Next.js 版本可能存在兼容差异：优先参考 `references/agent-chat-ui/package.json` 的依赖版本。
- 一次性新增文件较多：执行时拆为前端骨架小单元，不接 API，避免扩大范围。
