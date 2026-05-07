# apps/web

`apps/web` 承接 `references/agent-chat-ui` 的裁剪与改造，目标是实现 OSCE 三栏工作台。

## 当前状态

已建立最小 Next.js + TypeScript 前端骨架，并实现 OSCE 三栏工作台：

- 左侧：病例信息、病例选择入口、训练阶段；
- 中间：医患对话区与问诊输入栏；
- 右侧：已收集线索、诊断假设、查体/检查申请、评分报告。

当前已接入后端 session API：进入训练工作台后可按病例创建训练会话，问诊输入会调用 `/api/sessions/{session_id}/message` 并展示标准化病人回复；查体和辅助检查快捷项会随当前病例 session 返回的 `physical_exam_options` 与 `auxiliary_test_options` 动态渲染，并分别调用 `/api/sessions/{session_id}/physical-exam` 与 `/api/sessions/{session_id}/auxiliary-test` 展示返回结果；诊断提交表单保持空白结构化草稿，学生需自行填写诊断、鉴别诊断、支持依据、排除依据和下一步方向，后端不得下发标准诊断作为默认值；提交时调用 `/api/sessions/{session_id}/submit-diagnosis`，随后读取 `/api/sessions/{session_id}/report` 并在右侧展示结构化评分报告，包括总分、维度进度、亮点、推理问题、下一轮训练重点，以及按 `case`、`source`、`rubric`、`evidence` 分组展示的来源引用。

病例选择入口已在左侧落地，并会从 `/api/cases` 读取 `data/cases/*.json` 生成的学生可见病例摘要；独立病例选择页 `/cases` 已接入，可展示 5 个结构化病例并跳转工作台创建对应训练 session，但不再读取完整病例 raw JSON；当前 5 个结构化病例均可创建训练 session，查体和辅助检查按钮会按病例数据动态切换，诊断提交表单仍保持空白以避免预填标准答案。

独立安全声明页 `/safety` 用于集中展示教学模拟、真实诊疗边界、急症提示和输出边界清单，独立数据来源页 `/sources` 用于解释 `case`、`source`、`rubric`、`evidence` 四类来源引用，并展示 5 条公开来源登记、加工方式、许可和风险说明；这两个入口已收纳到 OSCE Dock，不再占用顶部导航。

学生端已关闭 Next.js 开发模式自带悬浮 indicator，并实现自有 OSCE Dock：圆形入口默认位于左下角，按钮内部带白色镂空圆环，可自由拖动，松手后自动吸附到左右屏幕边缘；展开后默认只显示白色一级菜单，一级菜单按“训练操作台 / 系统与配置 / 资料与说明 / 关闭菜单”排列，点击前三项才会在侧边继续展开对应子菜单，进入病例库、评分报告、过程提示、患者信息、安全声明和数据来源。`API 配置` 会在学生端白色弹窗内选择自定义后端、Gemini Developer API、Vertex Gemini ADC、Vertex Gemini API Key 或 OpenAI 兼容服务端；Gemini Developer API 与 Vertex Gemini ADC 默认模型为 `gemini-3.1-pro-preview`，Vertex Gemini API Key / Express Mode 默认模型为 `gemini-2.5-flash`，Vertex Gemini ADC 不需要 API Key，只填写 Project ID、模型和代理，Vertex Gemini API Key 不需要 Project ID。OpenAI 兼容、Vertex Gemini ADC 或 Vertex Gemini API Key 配置保存时会调用 `/api/model-config/runtime` 应用到本次后端进程内存，并可用于标准化病人、`llm_rubric` 和 Skill 候选文案生成。`/api/model-config/test` 可测试连通性：自定义后端测试 `/health`，Gemini Developer API 测试 `/v1beta/models`，Vertex Gemini ADC 通过本机 ADC 发起最小 Gemini 调用，Vertex Gemini API Key 通过 Google Gen AI SDK 发起最小 Gemini 调用，OpenAI 兼容服务端发出最小 `/chat/completions` 探针。学生端配置保存到浏览器 `localStorage`；后端运行时配置不落库、不回显密钥，重启后需要重新应用或改用 `.env` / 环境变量持久化。规则评分、病例标准答案和诊断裁判仍由后端确定性控制。

顶部导航的登录态入口已改为“测试账号”菜单，展开后居中显示训练记录和学习画像，并提供红色退出登录按钮，避免学生端顶部堆叠过多入口。

独立评分报告路由已接入，工作台生成报告后可打开 `/report?session_id=...` 查看集中式报告；报告页包含总分环形视图、维度雷达雏形、维度进度条、强弱项摘要、训练建议、按类型分组的来源引用，以及复制当前报告链接的分享入口。

训练记录页 `/history` 已改为读取 `/api/me/sessions` 的后端持久记录，支持继续训练、打开评分报告和删除记录；独立评分报告页会读取 `/api/me/sessions/{session_id}/report` 和 session 快照；学习画像页 `/profile` 会读取 `/api/me/profile` 聚合训练次数、报告均分、维度强弱项、Skill 应用次数和样本不足提示。旧的 `training-history.ts` 仅作为遗留兼容工具保留，不是官方训练记录链路。

本阶段尚未接入 LangGraph SDK streaming、跨设备协同分享、完整 thread history 面板或 artifact panel。

## 设计风格

新增页面以 `references/agent-chat-ui` 为主要视觉参考，沿用 Inter 字体、Tailwind v4 design tokens、浅色卡片、细边框、圆角、低强度阴影和 `#AE5630` brand 按钮。

Tailwind v4 通过 `postcss.config.mjs` 加载 `@tailwindcss/postcss`，确保响应式 utility classes 正常生成。

## 本地运行

先启动后端 API 服务：

```bash
cd "F:/杂物/个人开发/clinical-osce-agent"
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && python -m uvicorn app.main:app --app-dir services/api --reload --host 127.0.0.1 --port 8000
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
