# apps/web

`apps/web` 承接 `references/agent-chat-ui` 的裁剪与改造，目标是实现 OSCE 三栏工作台。

## 当前状态

已建立最小 Next.js + TypeScript 前端骨架，并实现 OSCE 三栏工作台：

- 左侧：病例信息、病例选择入口、训练阶段；
- 中间：医患对话区与问诊输入栏；
- 右侧：已收集线索、诊断假设、查体/检查申请、评分报告。

当前已接入后端 session API：进入训练工作台后可按病例创建训练会话，问诊输入会调用 `/api/sessions/{session_id}/message` 并展示标准化病人回复；活动会话使用版本化的 `student_session.v2` 学生安全投影，只返回已揭示线索、已申请的 `collected_procedure_results`、安全进度计数和当前教学提示，不下发未覆盖事实、未申请结果、Rubric、Skill 选择细节或审计轨迹。

初级模式可从 session 获得不含结果与诊断作用的查体 / 检查快捷项，中级模式使用通用目录批量选择，只有高级模式支持自由文本申请。活动训练只路由病例已配置项目；未配置项目返回 `unavailable`，不生成事实、不写回训练结果，也不计分。各动作分别调用 `/api/sessions/{session_id}/physical-exam` 与 `/api/sessions/{session_id}/auxiliary-test` 展示本次返回结果。

学生提交诊断前，发送给外部 provider 的 payload 只包含当前受控任务所需的最小已揭示上下文；需要审批的输出在审批超时、异常、空响应或状态不明时按 fail-closed（失败关闭）处理。评分只接受病例已配置且由学生实际获取的证据。若未来提供反事实查体 / 检查模拟，只能放在提交后的独立 sandbox，不能回写活动会话或评分链路。

诊断提交表单保持空白结构化草稿，学生需自行填写诊断、鉴别诊断、支持依据、排除依据和下一步方向，后端不得下发标准诊断作为默认值；提交时调用 `/api/sessions/{session_id}/submit-diagnosis`，随后用 `POST /api/sessions/{session_id}/report/generate` 显式生成基础报告。报告页通过纯读取 `GET /api/me/sessions/{session_id}/report` 展示结构化评分结果；需要个人 Skill 时仅调用一次 `POST /api/sessions/{session_id}/report/enrich`，后续继续用 GET 轮询，避免页面刷新或读取操作暗中触发模型与持久化写入。

病例选择入口已在左侧落地，并会从 `/api/cases` 读取 `data/cases/*.json` 生成的学生可见病例摘要；独立病例选择页 `/cases` 已接入，可展示 5 个结构化病例并跳转工作台创建对应训练 session，但不再读取完整病例 raw JSON；当前 5 个结构化病例均可创建训练 session，查体和辅助检查按钮会按病例数据动态切换，诊断提交表单仍保持空白以避免预填标准答案。

独立安全声明页 `/safety` 用于集中展示教学模拟、真实诊疗边界、急症提示和输出边界清单，独立数据来源页 `/sources` 用于解释 `case`、`source`、`rubric`、`evidence` 四类来源引用，并展示 5 条公开来源登记、加工方式、许可和风险说明；这两个入口已收纳到 OSCE Dock，不再占用顶部导航。

学生端已关闭 Next.js 开发模式自带悬浮 indicator，并实现自有 OSCE Dock：圆形入口默认位于左下角，按钮内部带白色镂空圆环，可自由拖动，松手后自动吸附到左右屏幕边缘；展开后默认只显示白色一级菜单，一级菜单按“训练操作台 / 系统与配置 / 资料与说明 / 关闭菜单”排列，点击前三项才会在侧边继续展开对应子菜单，进入病例库、评分报告、过程提示、患者信息、安全声明和数据来源。当前比赛 / 测试构建采用服务端统一托管模型配置，`API 配置` 为只读说明弹窗，学生端不提供 provider 选择、API Key 输入、保存或连通性测试，也不会把模型密钥写入浏览器。底层 `/api/model-config/test` 仅保留给显式启用账号级配置的 `local-dev` / `local-demo` 环境：要求普通用户登录但不要求管理员角色，匿名请求返回 401 且不会发出上游探针；服务端托管模式及生产模式返回 403。在显式启用该能力的共享本地环境中，账号配置只允许服务端批准的 HTTPS provider 主机和 direct 连接，拒绝自定义后端、账号代理、内网 / 回环地址、HTTP 重定向和服务端 Vertex ADC；保存、测试和真实调用使用同一策略，旧的不安全配置也不会重新绑定。只有单人本机 `local-dev` 可显式开启不安全端点兼容开关，该开关在 `local-demo` 和生产模式无效。规则评分、病例标准答案和诊断裁判仍由后端确定性控制。

顶部导航的登录态入口已改为“测试账号”菜单，展开后居中显示训练记录和学习画像，并提供红色退出登录按钮，避免学生端顶部堆叠过多入口。

后端不再内置始终可登录的固定学生账号。受控本地演示如需测试学生，必须在私有环境配置中同时设置 `CLINICAL_OSCE_DEMO_STUDENT_ENABLED=true`、非空邮箱和非空密码；缺少任一项都会拒绝登录，`single-node-prod` / `vertex-prod` 即使误设 enabled 也不会启用固定学生。公开文档和前端代码不保存演示凭据。

独立评分报告路由已接入，工作台生成报告后可打开 `/report?session_id=...` 查看集中式报告；报告页包含总分环形视图、维度雷达雏形、维度进度条、强弱项摘要、训练建议、按类型分组的来源引用，以及复制当前报告链接的分享入口。

训练记录页 `/history` 已改为读取 `/api/me/sessions` 的后端持久记录，支持继续训练、打开评分报告和删除记录；独立评分报告页会读取 `/api/me/sessions/{session_id}/report` 和 session 快照；学习画像页 `/profile` 会读取 `/api/me/profile` 聚合训练次数、报告均分、维度强弱项、Skill 应用次数和样本不足提示。旧的 `training-history.ts` 仅作为遗留兼容工具保留，不是官方训练记录链路。

工作台问诊输入栏已接入语音输入：浏览器录音会上传到 `/api/audio/transcriptions` 转写，并只填入输入框，不自动发送。标准化病人消息支持逐条播放，前端调用 `/api/audio/speech` 获取后端生成的音频；阿里云 DashScope key 只放在 API 服务端环境变量中，前端不保存语音密钥。

本阶段尚未接入 LangGraph SDK streaming、跨设备协同分享、完整 thread history 面板或 artifact panel。

## 设计风格

新增页面以 `references/agent-chat-ui` 为主要视觉参考，沿用 Inter 字体、Tailwind v4 design tokens、浅色卡片、细边框、圆角、低强度阴影和 `#AE5630` brand 按钮。

Tailwind v4 通过 `postcss.config.mjs` 加载 `@tailwindcss/postcss`，确保响应式 utility classes 正常生成。

## 本地运行

先启动后端 API 服务：

```bash
cd services/api
uv sync --frozen --extra dev
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

再从仓库根目录启动学生端：

```bash
cd apps/web
pnpm install --frozen-lockfile
pnpm dev
```

打开浏览器访问 `http://localhost:3000`。同一浏览器演示时，学生端必须保留 `localhost`，管理端使用 `127.0.0.1`，让两端的 host-only 登录 Cookie 相互隔离。若 3000 端口被占用，请为学生端显式选择其他空闲端口并继续使用 `localhost`，同时把新入口加入 API 端的 `CLINICAL_OSCE_TRUSTED_BROWSER_ORIGINS`；不要把学生端改为 `127.0.0.1:3000`，也不要占用 Compose 管理端使用的 3001。

### ChromaDB 召回稳定性配置

API 默认使用 `OSCE_CHROMA_SEARCH_EF=500` 作为 ChromaDB HNSW 查询深度。该值必须是正整数；缺失、非法或小于 1 时回退到 500。增大它会增加单次查询工作量，但能降低小型教学知识库中近似检索偶发漏召回的概率。

索引 manifest 会记录 `hnsw:space` 和 `hnsw:search_ef`。旧版 manifest 或上述配置变化会被标记为 `stale`，下一次真实检索会重建 collection。若首轮 Top-K 结果经过相似度过滤后为空，后端会复用已经生成的 query embedding 拉取当前 collection 的全部文档，再过滤并截断到请求的 `limit`；该补偿只提升本地检索稳定性，不改变 RAG 不参与诊断和评分裁判的边界。

## 常用命令

```bash
pnpm typecheck
pnpm test
pnpm build
pnpm dev
```
