# 临境 OSCE 智能体（TraceOSCE）

TraceOSCE 是一个面向医学教育场景的 OSCE（Objective Structured Clinical Examination，客观结构化临床考试）训练系统。它不是通用医学问答机器人，而是围绕“标准化病人问诊 - 体格检查 - 辅助检查 - 诊断推理 - 评分反馈 - 个性化再训练”构建的受控多 Agent 教学平台。

> 医学教育模拟声明：本项目仅用于教学训练、病例推理练习和系统研究，不提供真实诊断、治疗方案、用药剂量、急救处置或临床决策建议。

![TraceOSCE controlled multi-agent architecture](docs/architecture/traceosce-agent-architecture-biorender.png)

## 项目一眼看懂

| 维度 | 说明 |
| --- | --- |
| 核心对象 | 医学生、住培学员、OSCE 教学团队、医学智能体研究者 |
| 核心任务 | 在受控病例中训练病史采集、查体选择、辅助检查选择、鉴别诊断、诊断推理和复盘能力 |
| 交互形态 | 学生端三栏式 OSCE 工作台 + 管理端教师/研究仪表盘 + FastAPI 后端服务 |
| 智能体形态 | LangGraph（图式智能体编排）驱动的受控多 Agent 工作流，真实 Agent 与确定性服务分层协作 |
| 关键亮点 | 标准化病人事实边界、可追溯评分、RAG 安全分层、Skill 教学策略积累、学生画像驱动训练、自学习候选策略审计 |
| 明确不做 | 不做真实医疗建议，不让模型自由编造病例事实，不让 RAG 或 LLM 直接替代评分裁判 |

## 核心亮点

### 1. 不是聊天机器人，而是受控 OSCE 训练闭环

系统把一次训练拆成可审计的节点：病例加载、输入意图识别、标准化病人回应、查体、辅助检查、提示、诊断提交、规则评分和教师式复盘。每个节点都有输入输出边界，避免把整场训练交给一个不透明的大模型自由发挥。

### 2. 标准化病人只披露“学生已经问到的事实”

Patient Responder（标准化病人回应 Agent）不会直接读取并倾倒全部病例答案。后端会先根据学生输入识别意图，再只把可回答的事实候选、禁用内容和安全边界交给 Agent。系统还会校验 `fact_ids_used`，阻止 Agent 使用没有被允许披露的隐藏事实。

### 3. 评分不是黑箱大模型打分

评分以 Rubric（评分量表）为中心，支持病史意图、查体项目、辅助检查、诊断概念、推理覆盖和可选 LLM Rubric 辅助项。每个得分项会生成 `ScoreTrace`（评分证据追踪），说明命中了什么、缺了什么、依据是什么。RAG 只能提供解释、引用和复盘素材，不作为评分裁判。

### 4. RAG 有角色、可见性和安全分层

RAG（Retrieval-Augmented Generation，检索增强生成）不是全局知识库随意注入。知识条目按 `pre_submit_safe`、`post_submit_review`、`admin_only`、`source_only`、`secret_scoring_only` 等可见性分层，并按 Agent 角色授权。Coach 训练提示、Reflection 复盘、Skill 生成和 Skill 审批看到的内容不同。

### 5. Skill 是会积累的教学策略，不只是提示词

系统会从训练事件、报告、反复失分项和异常学习路径中生成 Skill（可积累的教学策略单元）候选。候选 Skill 经过审批 Agent、回归安全门和人工管理后，才能进入启用状态。启用后的 Skill 会参与后续训练编排，并反过来影响学生画像。

Skill 闭环大致如下：

| 阶段 | 系统行为 |
| --- | --- |
| 发现问题 | 从报告、事件、反复失分项、过早查体/检查、越界提问等模式中提取训练信号 |
| 生成候选 | 生成教学策略候选，保留触发项、适用病例、阶段范围、来源报告和证据 |
| 审批与拦截 | 审批 Agent 只能改写教学表达，不能篡改受保护字段；回归门拦截答案泄露、治疗剂量、越界医疗建议 |
| 启用与检索 | 合格 Skill 写入长期 Skill Store，并带有适用条件、证据条目和教学行动计划 |
| 个性化编排 | Skill Orchestrator 根据当前病例、训练阶段、学生画像、近期错误和冷却状态选择 Top-K Skill |
| 画像更新 | 学生完成训练后，Skill 使用效果、失分变化和稳定覆盖情况会更新 Skill 状态，进入 active、cooldown、reactivated、retired 等生命周期 |

### 6. 学生画像参与下一次训练

系统不是只生成一次报告。每次训练结束后，后端会把评分结果、遗漏项、训练事件、Skill 应用记录和个人化复盘汇总成学生画像。下一次训练时，画像会影响 Skill 选择、提示重点和复盘策略。

### 7. 管理端覆盖内容、运行和审计

管理端不是简单后台列表。它覆盖病例、Rubric、来源台账、RAG 知识、训练会话、报告、事件、洞察、评测、Skill 候选审批、Skill 效果观察和运行时模型配置，适合教学团队做内容维护和研究审计。

## 系统架构

| 层级 | 主要模块 | 作用 |
| --- | --- | --- |
| 学生端 | `apps/web` | 选择病例、进行问诊、请求查体/检查、记录假设、提交诊断、查看报告和学习画像 |
| 管理端 | `apps/admin` | 管理病例/Rubric/RAG/来源，查看训练记录、报告、事件、评测和 Skill 审批 |
| API 层 | `services/api/app/main.py` | FastAPI（Python API 框架）入口，提供认证、会话、报告、管理、配置和评测接口 |
| 编排层 | `services/api/app/graph/osce_graph.py` | LangGraph 工作流，负责把一次 OSCE 训练拆成可控节点 |
| 受控 Agent 层 | Turn Intent、Patient Responder、Coach、Reflection、Skill Generation、Skill Approval | 只在限定任务内调用模型，输出必须经过结构化校验和安全约束 |
| 确定性服务层 | 评分、查体/检查、RAG 过滤、Skill Orchestrator、学生画像、事件/报告存储 | 保持关键业务规则可复现、可测试、可审计 |
| 数据层 | `data/` 与 `data/runtime/` | 病例、Rubric、来源台账、RAG 种子知识、运行期 SQLite 数据库、Chroma/embedding 缓存 |

## 智能体与服务边界

### 真正的 Agent

| Agent | 文件/服务 | 职责 | 关键约束 |
| --- | --- | --- | --- |
| Turn Intent Agent | `turn_intent_agent.py` | 判断学生输入属于病史、问候、越界、离题、索要答案等意图 | 只能输出允许的意图标签和结构化 JSON |
| Patient Responder | `gemini_patient_responder.py` | 扮演标准化病人，回答学生已经问到的病史信息 | 只能使用可回答事实，禁止泄露诊断、Rubric、隐藏答案和治疗建议 |
| Coach Agent | `coach_agent.py` | 给出苏格拉底式下一步提示 | 不能直接给诊断答案，不能新增病例事实 |
| Reflection / Teacher Review | `personal_training_skill_service.py` 等 | 生成教师式复盘和个人训练策略 | 只基于病例、Rubric、覆盖情况和学生提交内容 |
| Skill Generation | `training_skill_candidate_service.py` | 从群体/个人训练信号中生成教学策略候选 | 候选字段受保护，不能越权修改来源和触发条件 |
| Skill Approval | `training_skill_auto_approval_service.py` | 审核 Skill 候选的安全性、表达和教学计划 | 不能放行答案泄露、治疗剂量、真实医疗建议 |

### 不应被误称为 Agent 的确定性模块

| 模块 | 职责 |
| --- | --- |
| Physical Exam / Auxiliary Test | 从病例结构化数据中返回查体和辅助检查结果 |
| Rule Evaluator | 按 Rubric 规则打分并生成 `ScoreTrace` |
| Retrieval Index | 构建病例、来源、Rubric 和 RAG 知识的检索索引 |
| Agent RAG Context Service | 按角色、病例范围和可见性过滤 RAG 上下文 |
| Skill Orchestrator | 根据病例、阶段、失分项、学生画像和冷却状态选择可用 Skill |
| Student Profile Summary | 汇总历史报告和 Skill 状态，维护学生学习画像 |
| Training Event / Report Store | 保存训练事件、会话摘要、报告和审计数据 |

## 一次训练如何流转

1. 学生在前端选择病例，后端创建 OSCE session。
2. 后端加载病例、Rubric、学生历史画像和可用 Skill。
3. 学生输入问诊内容，Turn Intent Agent 识别意图。
4. 图工作流决定进入标准化病人回应、查体、辅助检查、提示或安全重定向。
5. Patient Responder 只根据允许披露的事实回应，系统记录本轮事实、RAG 引用和 Skill 使用情况。
6. 学生记录假设，逐步补充查体和辅助检查。
7. 学生提交最终诊断和推理，Rule Evaluator 生成分项得分、遗漏项和证据追踪。
8. Feedback / Reflection 生成报告、知识建议、EvidenceGraph（证据图谱）摘要和个性化 Skill。
9. 报告和事件进入学生画像，影响下一次训练的 Skill 编排。

## 已实现能力

### 学生端

- 病例列表与病例介绍页。
- 三栏式 OSCE 工作台：病例阶段、医患对话、线索/假设/查体/检查/报告。
- 问诊、查体、辅助检查、假设记录、提示请求、诊断提交。
- 训练报告：维度分数、遗漏项、教师复盘、知识建议、来源引用、EvidenceGraph 摘要。
- 学习画像：历史训练、近期错误、Skill 状态、学习路径和个性化建议。
- 安全说明页和来源说明页。
- 本地演示用模型配置入口：连通性测试支持 Gemini、Vertex Gemini、OpenAI-compatible、Anthropic；训练运行时写入支持 OpenAI-compatible、Anthropic、Vertex Gemini ADC/API Key，生产模式下应使用服务端环境变量或密钥服务。

### 管理端

- 概览仪表盘：病例、报告、训练事件、Skill 候选等运行概况。
- 资源管理：病例、Rubric、来源台账、RAG 知识、文档导入。
- 训练管理：会话、报告、事件、日志和导出。
- 洞察分析：反复失分项、训练路径异常、教学关注点。
- 评测面板：检索评测、端到端报告评测、失败样例查看。
- Skill 审批：候选来源、适用条件、证据、审批对话、回归门、启用/拒绝。
- Skill 效果观察：应用次数、相关维度变化、样本量提示和审计线索。

### 后端服务

- FastAPI 接口：认证、病例、会话、训练动作、报告、学生画像、管理端、RAG、评测和模型配置。
- LangGraph OSCE 编排：把训练动作拆成可控节点。
- SQLite 运行期存储：会话、报告、事件、用户、模型配置、RAG 知识、Skill 候选和已启用 Skill。
- Chroma（向量数据库）与 fastembed（本地嵌入模型）可选检索后端。
- Vertex embedding 可选接入。
- Docker Compose 本地演示部署。

## 数据与病例资产

运行时直接使用的数据位于 `data/`：

| 目录 | 作用 |
| --- | --- |
| `data/cases/` | 结构化教学病例 |
| `data/rubrics/` | 与病例对应的评分量表 |
| `data/schemas/` | 病例和 Rubric JSON Schema |
| `data/attribution/` | 数据来源台账和许可证/归因信息 |
| `data/rag_knowledge/` | 默认 RAG 知识条目 |
| `data/runtime/` | 运行期数据库、缓存和索引，通常不作为源码资产提交 |

当前内置病例：

| Case ID | 模块 | 难度 | 教学目标 | 结构化资产 |
| --- | --- | --- | --- | --- |
| `appendicitis_001` | 腹痛 | 初级 | 急性阑尾炎 OSCE 训练 | 10 个隐藏事实、7 个查体项、5 个检查项、10 个证据节点 |
| `pneumonia_001` | 发热 / 呼吸系统 | 初级 | 社区获得性肺炎 OSCE 训练 | 4 个隐藏事实、2 个查体项、2 个检查项、11 个证据节点 |
| `hyperthyroid_001` | 心悸 / 内分泌 | 中级 | 甲状腺功能亢进症 OSCE 训练 | 6 个隐藏事实、3 个查体项、3 个检查项、13 个证据节点 |
| `acs_001` | 胸痛 / 心血管 | 中级 | 急性冠脉综合征 OSCE 训练 | 4 个隐藏事实、2 个查体项、2 个检查项、11 个证据节点 |
| `heart_failure_001` | 呼吸困难 / 心血管 | 中级 | 慢性心力衰竭急性加重 OSCE 训练 | 4 个隐藏事实、3 个查体项、2 个检查项、12 个证据节点 |

数据来源和归因说明见：

- [`docs/数据来源说明.md`](docs/数据来源说明.md)
- [`data/README.md`](data/README.md)
- [`data/attribution/source_registry/sources.json`](data/attribution/source_registry/sources.json)

## 目录结构

```text
.
├── apps/
│   ├── web/                 # 学生端 Next.js 应用
│   └── admin/               # 管理端 Next.js 应用
├── services/
│   └── api/                 # FastAPI + LangGraph 后端
│       ├── app/
│       │   ├── graph/       # OSCE 工作流
│       │   ├── models/      # Case、Rubric、状态模型
│       │   └── services/    # Agent、评分、RAG、Skill、画像、存储
│       ├── evals/           # 检索与端到端评测样例
│       └── tests/           # 后端测试
├── data/
│   ├── cases/               # 教学病例
│   ├── rubrics/             # 评分量表
│   ├── rag_knowledge/       # 默认 RAG 知识
│   ├── attribution/         # 来源台账
│   └── runtime/             # 运行期数据，按环境生成
├── docs/                    # 安全、来源、规格和架构图
├── docker-compose.yml       # 本地三服务演示
├── start-dev.py             # Windows 本地学生端联调脚本
└── start-admin.py           # Windows 本地管理端联调脚本
```

## API 能力概览

| 分组 | 典型接口 | 说明 |
| --- | --- | --- |
| 健康检查 | `/health`、`/api/health/config` | 服务状态、部署模式、配置问题 |
| 认证 | `/api/auth/register`、`/api/auth/login`、`/api/auth/me` | 本地演示账号与 Cookie 登录 |
| 病例 | `/api/cases`、`/api/cases/{case_id}` | 学生端病例列表和详情 |
| 训练会话 | `/api/sessions`、`/api/sessions/{id}/message` | 创建会话、问诊、查体、检查、提示、提交诊断 |
| 学生画像 | `/api/me/profile`、`/api/me/sessions` | 学生个人训练记录和画像 |
| 报告 | `/api/sessions/{id}/report`、`/api/me/sessions/{id}/report` | 训练报告和复盘 |
| 管理端 | `/api/admin/...` | 病例、Rubric、来源、RAG、报告、事件、评测、Skill 审批 |
| 模型配置 | `/api/model-config/test`、`/api/model-config/runtime` | 本地演示用模型连通性测试和运行时配置 |

## 本地运行

### 前置要求

- Python 3.11 或更高版本。
- Node.js 20 或更高版本。
- `uv`（Python 包管理与运行工具）。
- `pnpm` 10.x，可通过 `corepack` 启用。
- 可选：Docker / Docker Compose。

### 1. 准备环境变量

```powershell
Copy-Item '.env.example' '.env'
```

本地默认部署模式是 `local-demo`。如需接入模型，可在 `.env` 中配置 OpenAI-compatible、Anthropic、Gemini/Vertex 相关变量，或在学生端本地演示配置页写入账号级运行时配置。

生产或准生产部署应禁用前端写入 API Key，使用环境变量、密钥服务或平台身份认证。

### 2. 启动后端 API

```powershell
Set-Location 'services/api'
uv sync
uv run uvicorn app.main:app --host '127.0.0.1' --port 8000 --reload
```

后端地址：

- API: `http://127.0.0.1:8000`
- Health: `http://127.0.0.1:8000/health`

### 3. 启动学生端

```powershell
corepack pnpm --dir 'apps/web' install
corepack pnpm --dir 'apps/web' exec next dev --hostname '127.0.0.1' --port 3000
```

学生端地址：`http://127.0.0.1:3000`

### 4. 启动管理端

```powershell
$env:CLINICAL_OSCE_ADMIN_API_URL = 'http://127.0.0.1:8000'
corepack pnpm --dir 'apps/admin' install
corepack pnpm --dir 'apps/admin' exec next dev --hostname '127.0.0.1' --port 3001
```

管理端地址：`http://127.0.0.1:3001`

### 5. Windows 便捷脚本

仓库提供了两个本地联调脚本：

```powershell
python '.\start-dev.py'
python '.\start-admin.py'
```

这两个脚本面向当前开发机环境，内部包含本地 conda 环境路径和端口策略。跨机器使用时，优先采用上面的手动命令或按本机环境调整脚本。

### 6. Docker Compose 演示

```powershell
docker compose up --build
```

如果当前 Docker 版本只提供旧命令，也可以使用：

```powershell
docker-compose up --build
```

默认服务：

| 服务 | 地址 |
| --- | --- |
| API | `http://127.0.0.1:8000` |
| 学生端 | `http://127.0.0.1:3000` |
| 管理端 | `http://127.0.0.1:3001` |

Compose 默认挂载 `./data/runtime:/app/data/runtime`，并启用本地 embedding 与 Chroma 检索缓存，适合演示和离线复现，不等同于生产部署方案。

## 部署模式与配置边界

`CLINICAL_OSCE_DEPLOYMENT_MODE` 支持以下模式：

| 模式 | 用途 | 行为 |
| --- | --- | --- |
| `local-dev` | 开发调试 | 允许本地写入运行时配置和注册 |
| `local-demo` | 本地演示 | 默认启用 demo admin，便于课堂或答辩演示 |
| `single-node-prod` | 单机生产基线 | 禁用运行时模型配置写入和公开注册 |
| `vertex-prod` | Vertex 环境部署 | 倾向使用平台身份和服务端配置 |

重要边界：

- 账号级模型配置会保存到本地 SQLite，适合演示，不适合生产保存明文 API Key。
- 生产模式下应通过环境变量、密钥服务或云平台身份配置模型访问。
- 多模型接入是工程配置能力，不是项目的核心研究亮点；核心价值在受控训练、可追溯评分、RAG 安全分层和 Skill 教学闭环。

## 测试与评测

后端测试：

```powershell
Set-Location 'services/api'
uv run pytest -q
```

常用定向测试：

```powershell
uv run pytest tests/test_osce_graph.py tests/test_osce_sessions.py tests/test_rule_evaluator.py -q
uv run pytest tests/test_training_skill_orchestrator_service.py tests/test_training_skill_regression_gate.py -q
uv run pytest tests/test_agent_rag_context_service.py tests/test_retrieval_index.py -q
```

学生端检查：

```powershell
corepack pnpm --dir 'apps/web' typecheck
node --test 'apps/web/home-navigation-layout.test.mjs'
node --test 'apps/web/report-model-normalization.test.mjs'
```

管理端检查：

```powershell
corepack pnpm --dir 'apps/admin' typecheck
node --test 'apps/admin/admin-skill-review.test.mjs'
```

检索评测样例位于：

- `services/api/evals/retrieval/gold_queries.json`

端到端评测会检查总分、禁用词、RAG 来源覆盖、Rubric 引用覆盖、解释来源覆盖、EvidenceGraph 覆盖，以及 RAG 不参与评分裁判的隔离边界。

## 安全边界

系统内置多层安全边界：

- 病例事实来自结构化教学病例，不允许 Agent 自由创造新的临床事实。
- 标准化病人不能泄露诊断答案、评分规则、隐藏事实和治疗方案。
- Coach 只能提供学习提示，不能直接给结论。
- RAG 条目按角色和可见性过滤，`secret_scoring_only`、`admin_only` 等内容不会进入学生端报告。
- Skill 生成和审批不能绕过受保护字段，不能把答案、剂量、处方或真实医疗建议写入策略。
- 报告中的 EvidenceGraph 和来源引用用于复盘与审计，不用于替代评分裁判。

更完整说明见 [`docs/安全边界说明.md`](docs/安全边界说明.md)。

## 当前限制

- 当前病例数量有限，仍需要医学教师继续审查和扩展。
- 现有 Skill 效果观察是样本量敏感的相关性提示，不构成因果证明。
- `web_check_status` 和 `external_evidence_checks` 是审计字段，目前不是实时外部医学事实核验。
- 本地 demo 认证、Cookie、安全策略和 SQLite 存储不等同于生产级 RBAC、审计、密钥托管和合规部署。
- RAG 检索已具备角色过滤、Chroma 和本地 embedding 能力，但尚未实现完整的混合检索、reranker、大规模评测集和长期线上监控。
- 部分观测能力仍以本地事件、报告和评测为主，尚未形成完整生产监控体系。

## 相关文档

- [`docs/安全边界说明.md`](docs/安全边界说明.md)
- [`docs/数据来源说明.md`](docs/数据来源说明.md)
- [`docs/病例校验报告_首批.md`](docs/病例校验报告_首批.md)
- [`apps/web/README.md`](apps/web/README.md)
- [`apps/admin/README.md`](apps/admin/README.md)
- [`data/README.md`](data/README.md)
- [`项目开发文档.md`](项目开发文档.md)

## 许可证与来源

当前仓库未单独声明代码许可证。数据、病例参考和外部来源请以 `data/attribution/source_registry/sources.json` 与 `docs/数据来源说明.md` 为准。若用于课程、论文、比赛或公开演示，请保留来源归因并明确医学教育模拟边界。
