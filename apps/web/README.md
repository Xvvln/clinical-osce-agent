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

Tailwind v4 通过 `postcss.config.mjs` 加载 `@tailwindcss/postcss`，确保响应式 utility classes 正常生成。

## 常用命令

```bash
pnpm typecheck
pnpm build
pnpm dev
```
