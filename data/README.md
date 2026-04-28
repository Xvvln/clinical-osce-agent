# data 目录说明

本目录保存 Clinical OSCE Agent 的数据资产。它同时包含三类内容：当前系统直接使用的结构化教学病例、用于评分与反馈的数据契约，以及尚未完全加工的公开原始数据。运行时默认读取 `cases/`、`rubrics/`、`schemas/` 和 `attribution/`；`raw/` 主要是后续扩展病例库与知识库的素材来源。

## 目录结构

| 路径 | 内容 | 当前状态 |
| --- | --- | --- |
| `cases/` | 结构化 OSCE 教学病例 JSON | 当前训练系统直接使用 |
| `rubrics/` | 每个病例对应的评分量表 YAML | 当前报告与评分系统直接使用 |
| `schemas/` | 病例和 rubric 的 JSON Schema | 用于校验数据结构 |
| `attribution/source_registry/` | 数据来源、许可、用途和风险登记 | 当前来源引用与合规说明使用 |
| `raw/` | 下载的公开原始数据 | 作为素材库保存，不被运行时直接读取 |
| `processed/` | 清洗、抽取、转写后的中间数据 | 预留目录，目前为空 |
| `runtime/` | 本地 SQLite 运行时产物 | 本机调试生成，不应作为源数据提交 |

## 当前直接使用的数据

### `cases/`

当前系统直接加载 `cases/*.json` 生成病例列表、创建训练 session、展示患者信息、问诊隐藏事实、查体项、辅助检查项、诊断草稿和推理证据。已有病例包括：

| 文件 | 模块 | 难度 | 主诊断 |
| --- | --- | --- | --- |
| `appendicitis_001.json` | 腹痛 | 初级 | 急性阑尾炎 |
| `pneumonia_001.json` | 发热 / 呼吸系统 | 初级 | 社区获得性肺炎 |
| `hyperthyroid_001.json` | 心悸 / 内分泌 | 中级 | 甲状腺功能亢进症 |
| `acs_001.json` | 胸痛 / 心血管 | 中级 | 急性冠脉综合征 |
| `heart_failure_001.json` | 呼吸困难 / 心血管 | 中级 | 慢性心力衰竭急性加重 |

病例中的关键字段包括：

- `history.hidden_facts`：标准化病人根据学生问诊逐步披露的信息。
- `physical_exam.must_items` 和 `physical_exam.optional_items`：前端查体快捷按钮和后端查体结果来源。
- `auxiliary_tests.must_items` 和 `auxiliary_tests.optional_items`：前端辅助检查快捷按钮和后端检查结果来源。
- `diagnosis.reasoning_points`：报告、知识推荐和推理反馈使用的核心证据链。
- `source_attribution`：病例改写来源与合规说明。

### `rubrics/`

当前系统直接加载 `rubrics/*_rubric.yaml` 进行规则评分和报告生成。每个病例对应一个 rubric，评分维度包括：

- `history_taking`：问诊是否覆盖关键病史。
- `physical_exam`：是否申请关键查体。
- `auxiliary_test`：是否申请关键辅助检查。
- `main_diagnosis`：主诊断是否命中。
- `differential_diagnosis`：鉴别诊断质量。
- `reasoning`：诊断推理链覆盖情况。

目前 rubric 支持的匹配规则包括 `intent_keyword`、`exam_code`、`test_code`、`diagnosis_concept`、`reasoning_coverage` 和 `llm_rubric`。其中 `llm_rubric` 是可选的大语言模型语义评分入口；未启用模型时，该类评分项不会调用外部模型。

### `schemas/`

`schemas/case.schema.json` 和 `schemas/rubric.schema.json` 规定病例和评分量表的数据契约。新增病例或 rubric 时，应先满足 schema，再进入训练系统。

### `attribution/source_registry/`

`sources.json` 是数据来源登记清单，用于记录来源名称、来源地址、许可、允许用途、转换方式、归属要求和风险说明。病例中的 `source_attribution.source_id` 必须能在这里找到对应条目。

## 原始数据使用现状

### 已部分使用：Fareez OSCE

路径：`raw/fareez_osce/Data.zip`

当前用途：

- 作为 OSCE 医患问诊风格、话轮结构和呼吸系统病例结构的参考。
- 已有部分结构化病例以它作为来源或改写参考，例如腹痛、肺炎类教学病例。

尚未完成的部分：

- 原始压缩包没有被后端运行时直接读取。
- 尚未形成稳定的批量抽取脚本，把原始对话自动转换为 `cases/*.json`。

后续可用方向：

- 扩展更多问诊病例。
- 抽取标准化病人回答风格和问诊话轮模板。
- 构造学生问诊覆盖度评测样例。

### 已部分使用：MedCaseReasoning

路径：`raw/medcase_reasoning/`

当前用途：

- 作为诊断推理、鉴别诊断和 evidence chain 的素材来源。
- 已有心血管相关病例以它作为公开推理素材改写来源，例如胸痛和心衰病例。

尚未完成的部分：

- parquet、CSV 和 PQT 文件没有被后端运行时直接读取。
- 尚未建立从原始病例报告到 `diagnosis.reasoning_points` 的自动抽取流水线。

后续可用方向：

- 批量抽取主诊断、鉴别诊断、关键证据和推理点。
- 为 `reasoning` 维度生成更细的 rubric。
- 构造自动评测集，用来测试不同训练策略是否真的提升诊断推理质量。

### 暂未使用：CaseReportCollective

路径：`raw/case_report_collective/train-00000-of-00001.parquet`

当前用途：

- 已下载并登记，但当前 MVP 不直接使用。
- 定位为二期病例扩展来源。

尚未完成的部分：

- 未进入 `cases/`。
- 未进入 `processed/`。
- 未被评分、问诊或知识推荐模块读取。

后续可用方向：

- 筛选适合教学的病例报告，扩展多学科病例库。
- 生成更复杂的中高级病例。
- 为病例来源引用、知识推荐和错因分析提供更丰富的背景材料。

### 已登记但未纳入 `raw/`：MediTOD 公开仓库

位置：`references/MediTOD/`，不在 `data/raw/` 下。

当前用途：

- 作为医学问诊对话标注结构、意图识别和槽位抽取设计参考。
- 当前没有被运行时直接读取。

后续可用方向：

- 改进 `trigger_intents` 设计。
- 增强问诊问题到病史槽位的映射能力。
- 建立更接近真实问诊数据的意图和槽位评测集。

## 尚未获得的数据：MediTOD canonicalized dataset

MediTOD canonicalized dataset 是 MediTOD 使用 UMLS 词表标准化后的版本。它需要先获得 UMLS License，再向作者提交数据申请表。该数据当前尚未放入本目录，也不会由下载脚本自动获取。

潜在价值：

- 提供已标准化到 UMLS 概念的医学实体和标签。
- 帮助把学生自然语言问诊与标准医学概念对齐。
- 支持更稳定的 intent / slot / concept mapping，而不是只依赖关键词。
- 可用于构建病例知识点、概念同义词、标准化症状表达和问诊覆盖评估。
- 有助于后续从“固定病例按钮式训练”升级到“更自然语言、更概念化”的训练系统。

建议拿到后放置策略：

- 不要直接提交到 Git。
- 建议放在受限本地目录，例如 `data/restricted/meditod_canonicalized/`。
- 在 `attribution/source_registry/sources.json` 中补充实际许可和使用限制。
- 先加工出脱敏、可提交的中间统计或 schema 样例，再进入 `processed/`。

## 当前没有被运行时直接读取的数据

以下内容目前主要是本地素材或运行痕迹，不属于训练服务启动时必须读取的源数据：

- `raw/`：公开原始数据，只作为病例扩展和研究素材。
- `processed/`：目前为空。
- `runtime/*.sqlite3`：本地报告、训练事件和训练 Skill 数据库，是运行时产物。

## Git 与合规注意事项

- `data/raw/`、`runtime/*.sqlite3` 和大体积受限数据默认不应提交。
- 新增病例应保留 `source_attribution`，并确保 `source_id` 已登记。
- 受限数据、需要额外许可的数据和第三方数据包应只保存在本地或受控环境。
- 本项目病例仅用于医学教育模拟，不替代真实诊疗决策。
