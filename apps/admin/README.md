# apps/admin

`apps/admin` 承载 Clinical OSCE Agent 的教师/管理端页面。当前实现采用 Next.js（React 全栈框架）+ TypeScript（静态类型 JavaScript）路线，而不是早期文档中的 Streamlit（Python 快速看板框架）路线，以便和学生端共用前端技术栈。

## 当前已实现

- 总览区：展示训练 Session、错误模式、候选 Skill、系统评测和当前报告状态。
- 训练 Session：读取 `GET /api/admin/sessions`，展示训练记录摘要，支持 `limit` / `offset` / `q` 服务端分页筛选和当前页 JSON 导出。
- 评分报告：读取 `GET /api/admin/reports` 展示跨 Session 报告列表，并读取 `GET /api/admin/sessions/{session_id}/report` 展示单个训练报告；报告列表支持服务端分页筛选和当前页 JSON 导出。
- 训练日志：读取 `GET /api/admin/sessions/{session_id}/events`，展示训练事件类型与事件内容。
- 错误模式统计：读取 `GET /api/admin/insights`，展示常见漏项和学习建议。
- 系统评测：读取 `GET /api/admin/evaluations` 与 `GET /api/admin/evaluations/{batch_id}`，展示评测批次和失败详情，支持服务端分页筛选和当前页 JSON 导出；也可通过 `POST /api/admin/evals/run` 触发一次演示 smoke 评测并刷新选中新批次。
- 候选 Skill 审核：读取候选列表、详情与候选维度审核审计事件，可通过 `POST /api/admin/evolution/candidates/generate` 从训练日志生成候选，并调用批准/拒绝接口；候选列表支持服务端分页筛选和当前页 JSON 导出。
- 长列表筛选：病例台账保留前端本地筛选；训练 Session、跨 Session 报告、系统评测、候选 Skill 和独立审核审计日志使用服务端分页筛选。
- 独立构建配置：已提供 `package.json`、`tsconfig.json`、`next.config.mjs`、`postcss.config.mjs`、root layout 和全局样式。
- 未登录/无权限提示：当 `/api/admin/*` 返回 401 或 403 时，页面状态区分别展示登录提示和管理员权限提示，而不是泛化读取失败。
- 管理员白名单：后端通过 `CLINICAL_OSCE_ADMIN_EMAILS` 管理员邮箱白名单限制 `/api/admin/*`。
- 演示管理员：登录弹窗默认预填 `admin-demo@example.test / safe-admin-password`；本地演示后端默认允许这组凭据首次登录时创建或刷新演示管理员账号。
- 审核审计事件：批准/拒绝候选 Skill 后，后端写入最小审核审计事件；页面展示独立审核审计日志，并在候选详情区展示候选维度审计事件；独立审核审计日志支持服务端分页筛选和当前页 JSON 导出。

## 当前边界

- 这是本地演示阶段的教师视角复盘与审核后台；后端 `/api/admin/*` 已要求登录 Cookie，并通过 `CLINICAL_OSCE_ADMIN_EMAILS` 管理员邮箱白名单做最小鉴权，前端提供 401 未登录提示和 403 无管理员权限提示；候选生成与审核动作已写入最小审计事件，页面已展示独立审核审计日志和候选维度审计事件；主要增长型列表已支持服务端分页筛选和当前页 JSON 导出。
- 演示管理员硬编码只为本地答辩演示减少重复输入；正式部署前应设置 `CLINICAL_OSCE_DEMO_ADMIN_ENABLED=false`，并改用真实管理员账号与邮箱白名单。
- CSV/PDF、跨页全量服务端导出、复杂图表化统计和更复杂的评测编排仍延后。
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
