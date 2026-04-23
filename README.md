# 问诊推理舱 Clinical Reasoning OSCE Agent

面向诊断学课程的 OSCE 临床思维训练智能体。

## 项目定位

本项目是医学教育模拟系统，不用于真实诊疗；基于公开数据和结构化教学病例构建；自我进化仅作用于教学策略，不自动修改医学事实。

## 当前仓库结构

```text
clinical-osce-agent/
├── apps/
│   ├── web/                  # 前端工作台（后续从参考项目中裁剪实现）
│   └── admin/                # 管理后台（后续补充）
├── services/
│   └── api/                  # FastAPI + LangGraph 后端骨架
├── data/
│   ├── raw/                  # 原始公开数据（本地保留，不提交 Git）
│   ├── processed/            # 清洗后的中间数据
│   ├── cases/                # 结构化病例 JSON
│   ├── rubrics/              # 评分表
│   └── attribution/          # 来源登记
├── docs/
│   └── 数据来源说明.md
├── references/               # 参考仓库（本地保留，不提交 Git）
└── scripts/
    └── download_public_data.py
```

## 已拉取的参考仓库

这些仓库保留在 `references/` 下，仅用于阅读和裁剪，不直接并入主代码：

- `agent-chat-ui`
- `agent-service-toolkit`
- `EasyMED`
- `MediTOD`

## 环境

推荐使用 `conda` 的 `agent` 环境。

### 安装后端依赖

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && pip install -e ./services/api[dev]
```

### 启动后端

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && uvicorn app.main:app --app-dir services/api --reload
```

### 运行测试

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && pytest services/api/tests -q
```

## 原始数据下载

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && python scripts/download_public_data.py
```

脚本默认下载：

- Fareez OSCE Figshare 原始压缩包
- MedCaseReasoning 公共 parquet 文件
- CaseReportCollective 公共 parquet 文件

> `references/MediTOD` 已通过 Git 仓库拉取，其中自带公开数据文件；其需要 UMLS 许可的 canonicalized 数据不做自动下载。

## Git 策略

- `references/` 与 `data/raw/` 默认不提交到 GitHub
- GitHub 仓库只保存项目骨架、脚本、文档、结构化病例与后续业务代码
