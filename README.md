# 问诊推理舱 Clinical Reasoning OSCE Agent

问诊推理舱是一个面向诊断学教学的 OSCE（Objective Structured Clinical Examination，客观结构化临床考试）训练智能体平台。项目目标不是做一个普通聊天问答工具，而是构建一套“学生训练、智能体陪练、可追溯评分、教师复盘、系统自学习改进”的闭环系统，帮助医学生在安全、可审计的模拟环境中练习从采集证据、形成假设、验证诊断到表达推理的完整临床思维过程。

> 本项目只用于医学教育模拟训练，不用于真实疾病诊断、治疗决策、用药指导或急救处置。

## 项目目标形态

最终形态下，系统面向三类用户：学生使用学生端完成多轮 OSCE 训练；教师或管理员使用管理端查看病例、评分报告、训练日志、错误模式和系统评测结果；项目维护者通过结构化病例、rubric、来源台账、模型配置和回归测试持续扩展系统能力。学生端以虚拟标准化病人为核心，要求学生主动问诊、选择查体和辅助检查、记录诊断假设并提交最终诊断依据；后端智能体根据病例脚本控制事实披露，根据 rubric 执行规则评分和受控 LLM 语义评分，并生成带来源引用的复盘报告。

系统的关键目标是“可追溯”和“可迭代”。每份训练报告中的优势项、漏项、推理错误、学习建议和知识推荐都应能追溯到病例事实、rubric 评分项、已披露证据或来源登记；RAG 只服务于反馈解释、学习推荐和引用展示，不参与标准诊断裁判或评分决策。在多轮训练之后，系统会把报告进入洞察统计，聚合高频漏项和整体错误模式，生成训练模式级候选 Skill；候选 Skill 必须经过回归门禁和管理员审核，才能进入 enabled Skill 库，并在后续新训练 session 中作为教学提示注入。管理端需要展示候选 Skill 的来源报告、触发漏项、回归结果、审核审计事件、后续应用痕迹和样本不足时的真实效果状态。

这个项目的智能体特性是受控医学教学智能体，而不是开放式自主行动代理。它通过 LangGraph 管理多阶段训练状态，通过工具化节点处理问诊、查体、辅助检查、提示、评分、反馈和 Skill 注入，通过结构化日志形成可复盘轨迹，并通过自动化评测防止 RAG 来源覆盖、报告 JSON 兼容、Skill 审核闭环和管理端页面结构回退。医学事实、标准诊断、rubric、病例隐藏信息和真实诊疗建议始终保持受控边界，模型只在允许范围内承担语言表达、语义评分、学习建议和教学策略生成。

## 参赛定位

本项目面向“临床技能训练智能体”赛道。系统侧重临床实践能力的模拟与训练，以 OSCE 问诊、查体选择、辅助检查申请、诊断推理、评分反馈和可重复复盘为核心，突出交互式训练环境、过程证据留痕和教学改进闭环。它也具备医学教与学辅助能力，但答辩主线应放在“临床技能训练”而不是普通课程问答或教务管理。

## 目标核心能力

- **结构化病例与来源台账**：病例以 JSON（JavaScript Object Notation，结构化数据格式）保存，覆盖主诉、隐藏病史、查体、辅助检查、诊断、鉴别诊断、推理点、EvidenceGraph 证据图谱和来源归属；病例、rubric 和公开数据来源应能被管理端审计。
- **受控标准化病人训练**：虚拟病人只根据病例 `hidden_facts` 披露学生问到的信息，避免提前泄露标准答案、隐藏事实或诊断结论。
- **完整 OSCE 训练工作流**：学生可自然语言问诊、申请查体和辅助检查、记录诊断假设、请求过程提示、提交最终诊断和推理依据。
- **可追溯评分与 RAG 反馈**：按病例 rubric 生成分项得分、漏项、推理问题、知识推荐和来源引用；报告稳定包含 `source_references`、`source_reference_items`、`explanation_source_items` 和 `evidence_graph_summary`。
- **学生画像与学习建议**：系统根据多次训练报告形成学生弱项、强项、训练趋势和下一步训练重点，用于个性化学习路径。
- **Skill 自学习闭环**：从训练报告中聚合高频漏项和整体错误模式，生成候选教学 Skill；LLM 只负责标题、描述和训练策略文案，`candidate_id`、触发漏项、适用阶段、教学动作计划、禁止内容策略和效果指标由后端确定性生成；候选经过回归门禁和管理员审核后，才能影响后续训练。
- **管理端答辩与教学复盘**：教师可查看病例与来源台账、训练 Session、评分报告、RAG 引用、错误模式统计、候选 Skill、审核审计事件、enabled Skill 应用痕迹和效果统计。
- **安全与评测回归**：自动化测试持续验证 RAG 来源覆盖、旧报告兼容、Skill 审核闭环、后续训练注入、训练日志记录和管理端结构稳定性；系统明确拒绝真实诊疗建议。

## 技术栈

### 后端

- FastAPI（Python Web API 框架）：提供病例、训练 session、查体/检查、提示、诊断提交和报告接口。
- LangGraph（状态图编排库）：编排病例加载、问诊、查体、辅助检查、苏格拉底提示、诊断提交、评分和反馈节点。
- Pydantic（数据校验库）：定义病例和评分量表的数据契约。
- SQLite（轻量级关系数据库）：保存本地训练事件、报告和训练 Skill 运行时数据。
- Google Gen AI SDK（Google Gemini/Vertex AI 调用库）：可选接入标准化病人表达层和 LLM（大语言模型）评分能力。

### 前端

- Next.js（React 全栈框架）App Router：实现学生端工作台、病例页、报告页、安全声明页、数据来源页和训练历史页。
- React（前端组件库）：组织 OSCE 工作台交互。
- TypeScript（带类型的 JavaScript）：约束前端 API 响应和组件状态。
- Tailwind CSS（原子化 CSS 框架）：提供页面样式和响应式布局。

## 仓库结构

```text
clinical-osce-agent/
├── apps/
│   ├── web/                     # 学生端 Next.js 工作台
│   └── admin/                   # 管理端 Next.js 看板
├── data/
│   ├── attribution/             # 数据来源、许可和风险登记
│   ├── cases/                   # 结构化教学病例 JSON
│   ├── rubrics/                 # 病例评分量表 YAML
│   ├── schemas/                 # 病例和 rubric JSON Schema
│   └── runtime/                 # 本地运行时数据库，默认不提交
├── docs/
│   ├── 安全边界说明.md
│   ├── 数据来源说明.md
│   └── 病例校验报告_首批.md
├── scripts/
│   └── download_public_data.py  # 公开原始数据下载脚本
├── services/
│   └── api/                     # FastAPI + LangGraph 后端
├── .env.example                 # 环境变量模板，不包含真实密钥
├── README.md
└── 项目开发文档.md              # 设计蓝图、接口边界和开发路线
```

## 训练流程

1. 学生选择病例并创建训练 session。
2. 系统展示主诉和病例基本信息。
3. 学生进行问诊；标准化病人只披露被问到的结构化事实。
4. 学生申请查体和辅助检查；后端返回病例库中的结构化结果。
5. 学生可记录诊断假设，也可请求苏格拉底提示。
6. 学生提交最终诊断和诊断依据。
7. 后端按 rubric 生成评分报告、漏项、推理反馈、知识推荐和来源引用。
8. 前端展示报告摘要和独立报告页，用于教学复盘。

## 数据策略

- `data/cases/` 和 `data/rubrics/` 是运行时直接读取的教学数据。
- `data/schemas/` 约束病例和评分量表结构。
- `data/attribution/source_registry/sources.json` 是数据来源登记清单。
- `data/raw/`、`references/`、`data/runtime/*.sqlite3` 和受限数据默认不提交到 Git。
- 需要额外许可的数据，例如 UMLS canonicalized dataset，不自动下载，也不应直接提交。

当前病例 Schema 已包含 `EvidenceGraph`：节点可引用隐藏病史、查体、辅助检查和 reasoning point，后端会校验节点来源和边端点是否存在。`appendicitis_001` 已补充首个非空证据图谱，其他病例保留空图以维持统一契约；训练报告会返回 `evidence_graph_summary`，学生端和管理端报告详情可展示已收集 / 缺失证据节点与证据链边。该能力只用于复盘展示，不参与诊断裁判、rubric 评分或 RAG 排序。

## 数据来源与使用边界

本项目采用“公开来源登记 + 本地结构化加工 + 教学边界声明”的数据策略。系统不直接接入真实医院 HIS/EMR（医院信息系统 / 电子病历系统），不使用真实患者隐私数据，也不把外部原始大体积数据提交到 GitHub。病例、rubric、反馈引用和 RAG 来源均通过 `data/attribution/source_registry/sources.json` 维护来源台账，管理端可展示来源、许可、用途和风险说明。

已登记的数据 / 参考源包括：

| 来源 | 用途 | 许可与边界 |
| --- | --- | --- |
| Fareez OSCE 数据集 | 问诊语料风格、话轮结构、症状采集模式参考 | CC BY 4.0；偏呼吸系统问诊，不直接覆盖完整病例闭环 |
| MediTOD | 意图识别、槽位抽取、医学对话标注结构参考 | 公共仓库；canonicalized 数据需要 UMLS 许可，不自动下载 |
| MedCaseReasoning | 诊断推理依据、鉴别诊断 reasoning point 提炼参考 | 以数据集卡说明为准；复杂病例报告需二次教学化加工 |
| CaseReportCollective | 后续扩展病例筛选与结构化参考 | CC BY 4.0；当前只作为扩展来源，不直接进入 MVP 主数据 |
| EasyMED | 标准化病人、意图识别和评测模块设计参考 | 仅做架构参考，不直接照搬产品形态 |

当前仓库中的教学病例是面向 OSCE 训练目标进行结构化加工后的演示病例，用于医学教育模拟和系统评测，不代表正式临床指南或真实诊疗建议。若后续引入新的公开数据或教师审核病例，应同步更新来源台账、许可说明、风险说明和项目开发文档。

## 快速开始

### 环境要求

- Python 3.11+
- uv（Python 依赖与运行工具）
- Node.js 20+
- Corepack（Node 包管理器代理）与 pnpm（前端包管理器）

### 1. 克隆仓库

```bash
git clone https://github.com/Xvvln/clinical-osce-agent.git
cd clinical-osce-agent
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

`.env` 可以保持空密钥运行大部分本地测试。需要真实模型能力时，再按需配置：

```env
OSCE_GEMINI_PATIENT_API_KEY=
OSCE_GEMINI_PATIENT_USE_VERTEX=false
OSCE_GEMINI_PATIENT_PROJECT=
OSCE_GEMINI_PATIENT_LOCATION=global
OSCE_GEMINI_PATIENT_MODEL=gemini-3.1-pro-preview
OSCE_GEMINI_PATIENT_PROXY_URL=http://127.0.0.1:7897

OSCE_VERTEX_ENABLED=false
OSCE_VERTEX_API_KEY=
OSCE_VERTEX_PROJECT=
OSCE_VERTEX_LOCATION=global
OSCE_VERTEX_MODEL=gemini-3.1-pro-preview
OSCE_VERTEX_SKILL_CANDIDATE_ENABLED=false
OSCE_VERTEX_SKILL_CANDIDATE_MODEL=gemini-3.1-pro-preview
OSCE_VERTEX_PROXY_URL=http://127.0.0.1:7897
OSCE_VERTEX_EMBEDDING_ENABLED=false
OSCE_VERTEX_EMBEDDING_PROJECT=
OSCE_VERTEX_EMBEDDING_LOCATION=global
OSCE_VERTEX_EMBEDDING_MODEL=gemini-embedding-001
OSCE_VERTEX_EMBEDDING_OUTPUT_DIMENSIONALITY=3072
OSCE_VERTEX_EMBEDDING_PROXY_URL=http://127.0.0.1:7897
OSCE_CHROMA_ENABLED=false
CHROMA_PERSIST_DIRECTORY=./data/processed/chroma
OSCE_CHROMA_COLLECTION=clinical_osce_retrieval

OSCE_OPENAI_ENABLED=false
OSCE_OPENAI_API_KEY=
OSCE_OPENAI_BASE_URL=https://api.openai.com/v1
OSCE_OPENAI_MODEL=
OSCE_OPENAI_PROXY_URL=http://127.0.0.1:7897

CLINICAL_OSCE_ADMIN_EMAILS=admin-demo@example.test
CLINICAL_OSCE_DEMO_ADMIN_ENABLED=true
CLINICAL_OSCE_DEMO_ADMIN_EMAIL=admin-demo@example.test
CLINICAL_OSCE_DEMO_ADMIN_PASSWORD=safe-admin-password
```

当前模型配置边界：

- Gemini Developer API 可用于学生端标准化病人表达层，密钥只从环境变量读取。
- Vertex Gemini 可用于标准化病人、`llm_rubric` 评分和 Skill 候选文案生成；支持 ADC（Application Default Credentials，应用默认凭证）或 Vertex Express/API Key 两种认证方式。学生端 API 配置弹窗可选择 `Vertex Gemini ADC` 填写 Project ID，也可选择 `Vertex Gemini API Key` 只填写 API Key、模型和代理后应用到本次后端运行时。
- Vertex embedding RAG 检索可通过 `OSCE_VERTEX_EMBEDDING_ENABLED=true` 和 `OSCE_VERTEX_EMBEDDING_PROJECT=<project_id>` 启用，默认模型为 `gemini-embedding-001`，只用于 RAG 来源片段召回、反馈解释和学习推荐；启用 `OSCE_CHROMA_ENABLED=true` 后可使用本地 ChromaDB `PersistentClient` 持久化病例、rubric 和 knowledge 来源条目向量，并在持久化目录生成 `retrieval_index_manifest.json` 供管理端展示索引状态、文档数、覆盖病例和是否需重建。该链路不参与评分或诊断，pgvector / 生产级向量检索仍属于后续扩展。
- OpenAI 兼容配置可通过 `OSCE_OPENAI_*` 环境变量，或学生端 `/api/model-config/runtime` 本次运行时内存配置，接入标准化病人、`llm_rubric` 评分和 Skill 候选文案生成；底层按 Chat Completions 请求 `{base_url}/chat/completions`，可用 `OSCE_OPENAI_PROXY_URL=http://127.0.0.1:7897` 或 `direct` 控制代理。
- 管理端登录后可在“模型 / API 配置”区块查看 `/api/admin/model-config` 返回的配置状态、缺失环境变量和接入边界；接口不会返回真实密钥值，也不会把运行时密钥写入数据库或 `.env`。学生端弹窗配置会保存在浏览器 `localStorage`，后端运行时配置只保存在当前 FastAPI 进程内存；需要重启后仍生效时，请写入 `.env` / 环境变量。

本地演示管理员账号已在管理端登录弹窗中预填：`admin-demo@example.test / safe-admin-password`。后端会在首次使用这组凭据登录时创建或刷新该演示账号，并把它视为管理员邮箱；正式部署前应设置 `CLINICAL_OSCE_DEMO_ADMIN_ENABLED=false`，改用自己的 `CLINICAL_OSCE_ADMIN_EMAILS` 白名单和真实账号。

如果通过 Vertex AI（Google Cloud 托管模型服务）使用 ADC，请在本机完成 Google Cloud 登录，并把项目 ID 设置到 `OSCE_GEMINI_PATIENT_PROJECT` 或 `OSCE_VERTEX_PROJECT`；如果使用 Vertex Express/API Key，则设置 `OSCE_VERTEX_API_KEY` 或在学生端弹窗临时填写。不要把真实项目 ID、API Key 或凭证提交到仓库。真实模型调用默认按本地演示环境使用 `http://127.0.0.1:7897` 代理；如果你的网络环境不同，请修改对应 `*_PROXY_URL`。ADC 凭据由本机 Google Cloud 配置管理；API Key 只允许来自环境变量、前端临时请求或后端进程内存，接口不会回显真实密钥。

### 3. 启动后端

```bash
uv --directory services/api run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

后端健康检查：

```bash
curl http://127.0.0.1:8000/health
```

### 4. 启动前端

```bash
corepack pnpm --dir apps/web install
corepack pnpm --dir apps/web dev
```

访问：

```text
http://localhost:3000
```

前端开发服务会把 `/api/*` 请求转发到 `http://127.0.0.1:8000/api/*`。

## 测试与验证

后端测试：

```bash
uv --directory services/api run pytest tests -q
```

前端源码结构测试：

```bash
node apps/web/home-navigation-layout.test.mjs
node apps/web/next-config.test.mjs
```

前端类型检查：

```bash
corepack pnpm --dir apps/web typecheck
```

前端生产构建：

```bash
corepack pnpm --dir apps/web build
```

## 安全边界

系统必须拒绝或避免以下用途：

- 真实症状咨询；
- 具体用药剂量；
- 真实急症处置；
- 替代医生作出真实诊断；
- 生成真实治疗方案或手术方案。

系统回答和报告只服务于 OSCE 教学复盘。病例事实来自结构化病例库，训练策略可以迭代，但医学事实不能由模型自动改写。

## 隐私与公开仓库注意事项

公开仓库不应包含：

- `.env`、`.env.*` 中的真实密钥；
- Google Cloud、Gemini、Anthropic、Langfuse 等服务凭证；
- 本地运行数据库 `data/runtime/*.sqlite3`；
- 原始大体积数据 `data/raw/`；
- 参考仓库 `references/`；
- 个人助手配置 `.claude/`、`CLAUDE.md`；
- 邮件、许可证批准信或其他私人通信。

提交前建议运行：

```bash
git status --short
git diff --stat
```

并检查是否误加入密钥、受限数据或个人文件。

## 许可证

仓库代码许可证尚未单独声明。病例和数据素材的来源、许可与使用限制以 `data/attribution/source_registry/sources.json` 和 `docs/数据来源说明.md` 为准。
