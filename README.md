# 问诊推理舱 Clinical Reasoning OSCE Agent

问诊推理舱是一个面向诊断学教学的 OSCE（Objective Structured Clinical Examination，客观结构化临床考试）训练智能体。它用结构化病例、受控标准化病人、过程提示、查体/检查申请、诊断提交和评分反馈，帮助学生练习临床问诊与诊断推理。

> 本项目只用于医学教育模拟训练，不用于真实疾病诊断、治疗决策、用药指导或急救处置。

## 核心能力

- **结构化病例训练**：病例以 JSON（JavaScript Object Notation，结构化数据格式）保存，覆盖主诉、隐藏病史、查体、辅助检查、诊断、鉴别诊断、推理点和来源归属。
- **受控标准化病人**：后端只根据病例 `hidden_facts` 披露学生问到的信息，避免提前泄露诊断。
- **问诊与工具申请**：学生可以自然语言问诊，也可以通过快捷入口申请病例定义中的查体和辅助检查。
- **诊断假设草稿**：训练中途可记录初步诊断假设，但不会触发最终评分。
- **苏格拉底提示**：学生可请求过程提示；提示通过 LangGraph（状态图编排库）中的 `socratic_hint_node` 生成，只给下一步思考方向，不直接给答案。
- **评分与反馈报告**：按病例 rubric（评分量表）生成分项得分、漏项、推理问题、知识推荐和来源引用。
- **来源与安全边界**：病例和数据来源在 `data/attribution/source_registry/` 登记；安全声明明确拒绝真实诊疗建议。
- **训练日志与复盘基础**：后端记录训练事件、报告和训练 Skill（教学策略）相关数据，为后续教学分析和受控进化提供基础。

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

## 后端 API

| API | 方法 | 说明 |
| --- | --- | --- |
| `/health` | GET | 健康检查 |
| `/api/cases` | GET | 获取病例摘要列表 |
| `/api/cases/{case_id}/raw` | GET | 获取单个病例完整结构 |
| `/api/sessions` | POST | 创建训练 session |
| `/api/sessions/{session_id}` | GET | 查询训练状态 |
| `/api/sessions/{session_id}/message` | POST | 发送问诊问题 |
| `/api/sessions/{session_id}/physical-exam` | POST | 申请查体 |
| `/api/sessions/{session_id}/auxiliary-test` | POST | 申请辅助检查 |
| `/api/sessions/{session_id}/hypotheses` | POST | 记录训练中的诊断假设 |
| `/api/sessions/{session_id}/hint` | POST | 请求苏格拉底过程提示 |
| `/api/sessions/{session_id}/submit-diagnosis` | POST | 提交最终诊断 |
| `/api/sessions/{session_id}/report` | GET | 生成或读取评分报告 |

## 数据策略

- `data/cases/` 和 `data/rubrics/` 是运行时直接读取的教学数据。
- `data/schemas/` 约束病例和评分量表结构。
- `data/attribution/source_registry/sources.json` 是数据来源登记清单。
- `data/raw/`、`references/`、`data/runtime/*.sqlite3` 和受限数据默认不提交到 Git。
- 需要额外许可的数据，例如 UMLS canonicalized dataset，不自动下载，也不应直接提交。

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
OSCE_GEMINI_PATIENT_MODEL=gemini-3.1-flash-lite-preview
```

如果通过 Vertex AI（Google Cloud 托管模型服务）使用 ADC（Application Default Credentials，应用默认凭证），请在本机完成 Google Cloud 登录，并把 `OSCE_GEMINI_PATIENT_PROJECT` 设置为你自己的项目 ID，不要把真实项目 ID 或凭证提交到仓库。

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