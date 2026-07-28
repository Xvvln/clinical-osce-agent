# 临境 OSCE 智能体（TraceOSCE）

**临境 OSCE 智能体（TraceOSCE）** 是一个面向医学教育场景的诊断学 OSCE 训练系统。项目围绕“问诊、查体、辅助检查、诊断推理、评分反馈、教师复盘和个性化再训练”构建闭环，目标是帮助医学生在可重复的模拟病例中训练临床思维。

本项目定位于 **临床技能训练智能体**：它不是医学问答机器人，也不提供真实诊断、治疗、用药或急救建议。

## 核心亮点

- **标准化病人对话**：学生用自然语言问诊，PatientAgent 只根据病例事实和当前可披露范围回答。
- **三档训练难度**：初级提供核心查体与检查入口；中级要求学生从通用目录批量选择项目；只有高级模式支持自由文本申请。活动训练只路由病例已配置项目，未配置项目返回 `unavailable`，不生成病例事实，也不参与评分。
- **TeacherAgent 教学引导**：结合当前对话、已收集线索、病例结构、学生画像、Skill 记忆和知识库，给出下一步提示与训练后复盘。
- **RAG 教学知识库**：教师可维护全局或病例知识库，知识检索用于提示、复盘、Skill 生成 / 审批和来源追溯，不参与诊断裁判或 rubric 评分。
- **Skill 自学习闭环**：训练报告沉淀为学生画像和候选 Skill，经审批后成为后续训练可调用的教学记忆。
- **可追溯训练报告**：报告展示评分、证据覆盖、未覆盖线索、教师式复盘、训练建议和可追溯来源。
- **管理端 v2**：面向教师和管理员，管理病例、Rubric、知识库、训练记录、报告、模型调用日志、Skill 审核和系统评测。

## 使用场景

TraceOSCE 适合用于：

- 医学生诊断学问诊与临床思维训练。
- OSCE 课程或比赛作品演示。
- 医学教育中“教、学、评、改”闭环原型验证。
- RAG、Agent、学生画像和教学 Skill 机制的研究型系统实验。

不适合用于：

- 真实患者诊断或治疗。
- 用药剂量、急救处置或临床决策支持。
- 未经医学教师审核的正式课程评价。

## 学生端

学生端覆盖完整训练路径：

1. 选择病例和训练难度。
2. 与标准化病人进行问诊。
3. 申请查体和辅助检查。
4. 形成诊断假设。
5. 提交最终诊断、鉴别诊断、证据和不确定点。
6. 查看训练报告和教师复盘。
7. 在学习画像中查看近期问题、Skill 积累和后续训练方向。

训练中，系统会记录已披露线索、已申请项目、诊断推理轨迹和 TeacherAgent 的教学提示。学生提交诊断后，系统才展示完整报告和更深入的复盘内容。

## 管理端

管理端 v2 采用更接近教学后台的工作台结构，主要包括：

- **病例工坊**：查看、新建和维护结构化病例。
- **Rubric 管理**：维护评分维度、评分项和命中规则。
- **知识库**：上传或编辑全局 / 病例知识文档，并控制可见性和可用 Agent。
- **训练管理**：查看 Session、报告、日志、训练请求安全审计和 Agent 轨迹。
- **教学洞察**：聚合高频漏项、训练重点和来源热度。
- **Skill 进化**：生成候选 Skill、查看审批 Agent 记录、人工审核或启用自动应用。
- **质量评测**：查看报告评测、RAG 检索评测和回归状态。
- **模型日志**：查看模型调用成功率、耗时、失败原因和调用人。

管理端用于答辩时展示“病例与来源台账、训练证据、教师复盘、Skill 审批、后续生效痕迹和系统边界”。

## 智能体边界

项目对外采用三类核心智能体口径：

| 智能体 | 职责 |
| --- | --- |
| PatientAgent | 扮演标准化病人，只回答当前允许披露的病例事实 |
| TeacherAgent | 负责训练提示、上下文评估、Skill Router、RAG 教学知识辅助和训练后复盘 |
| ApprovalAgent | 审核 Skill 候选和需要进入受控链路的模型输出；审批异常时按 fail-closed（失败关闭）处理 |

以下部分保持确定性或工具层实现：

- 病例事实加载和隐藏事实保护。
- 学生会话响应投影：活动会话只下发已揭示线索、已申请结果和安全进度摘要，内部待覆盖项、Rubric、教学策略与审计轨迹不进入学生端 JSON。
- 查体 / 辅助检查路由与病例已配置结果查询；未配置项目只返回 `unavailable`。
- Rubric 规则评分。
- RAG 可见性过滤。
- Skill 写入门禁和学生画像更新。
- 会话、报告、事件和审计存储。

这个边界的核心原则是：**大模型可以参与理解、表达、教学引导和复盘，但不能直接修改病例事实、标准诊断、Rubric 或评分裁判。**

## RAG 与 Skill

### RAG 的用途

RAG 在本项目中用于教学辅助：

- TeacherAgent 生成提示时查找相关教学知识。
- 训练后复盘时补充可追溯解释。
- Skill 生成和审批时提供参考上下文。
- 管理端展示知识来源、文档片段和检索评测。

RAG 不用于：

- 判断标准诊断是否正确。
- 决定 Rubric 分数。
- 证明学生“确实漏了某项”。
- 替代病例结构化事实。

### Skill 的用途

Skill 是学生训练后的可复用教学记忆。它不是医学事实库，而是记录“这个学生在某类病例或某类思维环节上反复出现的问题，以及下次训练时 TeacherAgent 应该如何引导”。

当前 Skill 闭环包括：

1. 训练完成后生成报告。
2. 报告进入学生画像和教学洞察。
3. 高频问题或本轮关键问题生成候选 Skill。
4. 审批 Agent 和回归门禁检查候选内容。
5. 管理员审核或自动应用。
6. enabled Skill 在后续训练中由 TeacherAgent 按上下文选择性调用。

当样本不足时，系统只展示“样本不足”或应用痕迹，不伪造能力提升。

## 内置病例与数据来源

当前仓库内置 5 个结构化教学病例：

| 病例 | 模块 | 难度 | 训练主题 |
| --- | --- | --- | --- |
| 右下腹痛教学病例 | 腹痛 | 初级 | 急腹症问诊、查体和阑尾炎证据链 |
| 发热咳嗽伴胸痛教学病例 | 呼吸系统 | 初级 | 感染线索、肺部查体和胸痛鉴别 |
| 心慌、手抖与消瘦教学病例 | 内分泌 | 中级 | 高代谢症状、甲状腺查体和甲功证据 |
| 胸痛伴出汗教学病例 | 心血管 | 中级 | 高危胸痛、心电图和心肌损伤证据 |
| 活动后气短伴夜间憋醒教学病例 | 心血管 | 中级 | 心衰容量负荷、肺部体征和 BNP / 超声证据 |

数据来源与知识来源采用公开资料改写和结构化加工，主要包括：

- Fareez OSCE 公开数据：用于问诊风格和部分病例结构参考。
- MedCaseReasoning：用于诊断推理和证据链素材参考。
- EasyMED / SPBench：用于公开教学病例结构参考。
- AAFP、Merck Manual Professional、NCBI StatPearls：用于短文本教学知识条目和 RAG 默认种子。

详细来源和合规说明见：

- [`data/README.md`](data/README.md)
- [`docs/数据来源说明.md`](docs/数据来源说明.md)
- [`data/attribution/source_registry/sources.json`](data/attribution/source_registry/sources.json)

## 技术栈

- 前端：Next.js、React、TypeScript。
- 管理端：Next.js + shadcn/ui 风格 Dashboard Blocks 改造。
- 后端：FastAPI、Pydantic、SQLite。
- 训练流程：LangGraph 编排 OSCE 会话节点。
- RAG：ChromaDB、Vertex Gemini Embedding、本地 embedding fallback。
- 测试：pytest、Node test、TypeScript typecheck。

## 本地体验

环境建议：

- Python 3.11+
- Node.js 20+
- `uv`
- `pnpm`，推荐通过 `corepack` 使用

便捷启动统一入口：

```powershell
python '.\start-dev.py'
```

该命令会启动同一套本地后端和两个前端：

- API：`http://127.0.0.1:8000`
- 学生端：`http://127.0.0.1:3000`
- 管理端：`http://127.0.0.1:3100`

如需在 API 已经运行时单独调试管理端，可参考：

```powershell
python '.\start-admin.py'
```

`start-admin.py` 不再启动第二套 API，只会将管理端连接到 `http://127.0.0.1:8000`。换机器或正式部署时，请以 `.env.example`、`apps/web/README.md`、`apps/admin/README.md` 和 `docker-compose.yml` 为准。

本地脚本与 Docker Compose 使用不同的管理端端口：`start-dev.py` 使用 `3100`，Compose 使用 `3001`。Compose 默认只绑定回环地址，入口分别为 API `127.0.0.1:8000`、学生端 `127.0.0.1:3000`、管理端 `127.0.0.1:3001`；如需对外提供服务，应在反向代理和访问控制就绪后再显式调整 `CLINICAL_OSCE_BIND_HOST`。

Compose 和 API 进程默认都不启用固定演示管理员或固定演示学生，也不提供默认邮箱与密码。受控演示环境必须在不提交到仓库的私有 `.env` 中分别显式设置 `CLINICAL_OSCE_DEMO_ADMIN_ENABLED/EMAIL/PASSWORD` 与 `CLINICAL_OSCE_DEMO_STUDENT_ENABLED/EMAIL/PASSWORD`；两类账号只在 `local-dev` / `local-demo` 生效，生产模式即使误设 enabled 也会拒绝固定账号登录。演示 seed API 与脚本同样要求两组配置完整，否则会在写入前失败关闭。

Session 主记录使用 SQLite revision 的 compare-and-swap（比较并交换）更新和独立删除墓碑：共享同一台机器数据库文件的多个 API worker 不会再静默覆盖彼此写入，旧 worker 也不能把已删除 session 重新插回；版本冲突返回 409，客户端刷新后再重试。该机制仍是单机 SQLite 边界，不支持把数据库文件放到 NFS / SMB 后当作多机一致性存储；升级时应排空并一次性重启旧 worker，正式多机部署应迁移 PostgreSQL。

本地和测试阶段默认采用服务端统一托管模型配置，关键默认值与 `.env.example` 保持一致：

```env
CLINICAL_OSCE_SERVER_MANAGED_MODEL_CONFIG=true
OSCE_OPENAI_MODEL=gemini-3.5-flash
OSCE_OPENAI_FALLBACK_MODEL=mimo-v2.5-pro
OSCE_VERTEX_EMBEDDING_MODEL=gemini-embedding-001
OSCE_LOCAL_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
```

仅在本地显式启用账号级模型配置时，后端才会按当前登录账号读取配置，并在单次训练或报告请求的上下文中绑定；读取配置状态不会改写进程级模型状态，后台报告增强也会按 session 所属账号重新绑定。Provider 客户端按配置快照隔离缓存，OpenAI / Anthropic / Google GenAI 请求均使用客户端级代理且不继承进程代理环境。由于 ADC 凭据刷新无法做到账号级代理隔离，账号级 Vertex ADC 只允许直连；需要代理时应改用 Vertex API Key，或由运维配置服务端托管代理。

语音输入与患者回复播放通过后端 `/api/audio/*` 统一接入 DashScope。浏览器不保存阿里云 key；如需启用，在 API 服务端环境配置：

```env
OSCE_DASHSCOPE_SPEECH_API_KEY=
OSCE_DASHSCOPE_ASR_MODEL=qwen3-asr-flash
OSCE_DASHSCOPE_TTS_MODEL=qwen3-tts-flash
OSCE_DASHSCOPE_TTS_VOICE=Serena
```

## 常用验证

后端测试：

```powershell
Set-Location 'services/api'
uv sync --frozen --extra dev
uv run python3 -m pytest -q tests ../../tests
```

学生端：

```powershell
corepack pnpm --dir 'apps/web' install --frozen-lockfile
corepack pnpm --dir 'apps/web' check
```

管理端：

```powershell
corepack pnpm --dir 'apps/admin' install --frozen-lockfile
corepack pnpm --dir 'apps/admin' check
```

GitHub Actions 会以 Python 3.12、Node.js 20 和 pnpm 10.5.1 并行执行上述 API、学生端和管理端检查。

## 当前边界

- 当前病例数量有限，医学内容仍需要教师持续审核和扩展。
- 认证、权限、密钥托管和审计仍是演示级或单机部署基线，不是完整生产安全方案。
- 自由文本查体 / 检查申请仅在高级模式开放；活动训练仍只返回病例已配置项目，未配置项目返回 `unavailable`，不生成事实、不写回训练结果，也不参与评分。
- 学生提交诊断前，发送给外部 provider 的 payload 采用最小披露，只包含完成当前受控任务所需的已揭示上下文；需要审批的输出在审批故障时按 fail-closed 处理。
- 评分只接受病例中已配置且由学生实际获取的证据，不接受未配置项目、模型补写内容或审批失败内容。
- 如果未来保留反事实查体 / 检查模拟，它只能在学生提交诊断后进入独立 sandbox，不得回写活动会话事实、标准答案或评分证据。
- Skill 效果统计需要足够样本后才能判断趋势；样本不足时不会显示虚假的提升。
- RAG 当前用于教学知识辅助和来源追溯，不是诊断或评分裁判。
- 外部医学事实核验、混合检索、reranker、大规模评测和生产监控仍是后续扩展方向。

## 项目文档

- [`项目开发文档.md`](项目开发文档.md)
- [`docs/admin-v2-dashboard.md`](docs/admin-v2-dashboard.md)
- [`docs/安全边界说明.md`](docs/安全边界说明.md)
- [`docs/数据来源说明.md`](docs/数据来源说明.md)
- [`data/README.md`](data/README.md)

## License

当前仓库未单独声明代码许可证。病例参考、数据来源和外部材料归因请以 `data/attribution/source_registry/sources.json` 与 `docs/数据来源说明.md` 为准。
