# apps/admin

`apps/admin` 承载 Clinical OSCE Agent 的教师/管理端页面。当前实现采用 Next.js（React 全栈框架）+ TypeScript（静态类型 JavaScript）路线，而不是早期文档中的 Streamlit（Python 快速看板框架）路线，以便和学生端共用前端技术栈。

## 当前已实现

- 总览区：展示训练 Session、错误模式、候选 Skill、系统评测和当前报告状态。
- 训练 Session：读取 `GET /api/admin/sessions`，展示全部训练记录摘要。
- 评分报告：读取 `GET /api/admin/sessions/{session_id}/report`，展示单个训练报告。
- 训练日志：读取 `GET /api/admin/sessions/{session_id}/events`，展示训练事件类型与事件内容。
- 错误模式统计：读取 `GET /api/admin/insights`，展示常见漏项和学习建议。
- 系统评测：读取 `GET /api/admin/evaluations` 与 `GET /api/admin/evaluations/{batch_id}`，展示评测批次和失败详情。
- 候选 Skill 审核：读取候选列表与详情，并调用批准/拒绝接口。
- 独立构建配置：已提供 `package.json`、`tsconfig.json`、`next.config.mjs`、`postcss.config.mjs`、root layout 和全局样式。

## 当前边界

- 这是本地演示阶段的教师视角只读后台，尚未接入管理员登录态、角色鉴权、审计日志、分页筛选或图表化统计。
- 病例/rubric 编辑、跨 Session 报告列表和从管理端触发评测运行仍延后。
- 当前页面契约由结构测试锁定，真实编译由独立 `typecheck` 和 `build` 命令验证。

## 验证

```bash
node --test "F:/杂物/个人开发/clinical-osce-agent/apps/admin/admin-skill-review.test.mjs"
corepack pnpm --dir "F:/杂物/个人开发/clinical-osce-agent/apps/admin" typecheck
corepack pnpm --dir "F:/杂物/个人开发/clinical-osce-agent/apps/admin" build
```

后端管理 API 回归测试：

```bash
source /d/Anaconda3/etc/profile.d/conda.sh && conda activate agent && PYTHONPATH="F:/杂物/个人开发/clinical-osce-agent/services/api" pytest "F:/杂物/个人开发/clinical-osce-agent/services/api/tests/test_admin_api.py" -q
```
