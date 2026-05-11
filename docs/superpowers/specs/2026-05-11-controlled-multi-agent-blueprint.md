# TraceOSCE 受控多 Agent 长期蓝图

## Summary

TraceOSCE 当前已经具备 RAG 来源追溯、Skill 自学习闭环、训练报告、学习画像、管理端和确定性教学状态，但学生每轮问诊仍容易退化为“关键词路由 + 标准答案改写”。长期方向是升级为受控多 Agent 医学教学系统：模型参与每轮对话理解、患者扮演、教学引导、反思和审计，但病例事实披露、标准诊断、rubric 评分和真实医疗安全边界仍由后端确定性控制。

## Agent Architecture

- **Turn Intake / Safety Agent**：接收学生输入，结合确定性安全规则识别真实医疗建议、用药剂量、索要标准答案等边界。
- **Intent Recognition Agent**：理解本轮学生意图，输出结构化意图、置信度、偏题标记和候选证据类型；只能看到公开病例信息、学生消息、历史摘要和关键词 hints，不能看到完整隐藏事实或标准诊断。
- **Case Fact Gate**：后端确定性门禁；根据意图决定本轮允许披露哪一条 `hidden_fact`、查体结果或辅助检查结果。
- **Patient Agent**：生成学生可见的标准化病人回复；只接收本轮允许披露的 `canonical_answer`、禁用词、安全策略和对话记忆摘要。
- **Coach / Teaching Strategy Agent**：基于训练记忆、TeachingPlan、StageCheckpoint、Hint Ladder 和 enabled Skill 生成教学引导，不替代诊断裁判。
- **Reflection Agent**：报告后基于训练路径、漏项、推理错误和来源引用生成复盘摘要。
- **Skill Evolution Agents**：基于多轮结构化训练记忆和报告聚合错误模式，生成、审查、修订候选 Skill；只允许改教学策略。
- **Audit / Trace Layer**：记录每轮 observe / decide / act / reflect、模型调用状态、turn policy、后端门禁结果和脱敏摘要，供管理端审计。

## Data Flow

```text
学生输入
→ 保存原始 turn
→ 安全 / 答题边界预检
→ Intent Recognition Agent
→ Case Fact Gate 决定允许披露内容
→ Patient Agent 或 Coach Agent 生成可见回复
→ 后端输出安全校验
→ 更新 agent_turn_memory / pedagogy_state / agent_decision_trace
→ 写入 training_event
→ 前端显示回复
```

阶段性链路：

```text
多轮训练记忆
→ Reflection Agent
→ RAG 可追溯报告
→ 错误模式聚合
→ Skill Candidate Agent
→ Approval / Safety Agent
→ enabled Skill
→ 后续训练注入
```

## Boundaries

- RAG 只用于反馈解释、学习建议、引用展示和可追溯性，不参与诊断裁判或评分决策。
- Skill 只能影响教学策略、提示方式、训练路径和反馈模板，不能修改医学事实、标准诊断、病例隐藏信息、rubric、治疗方案或用药剂量。
- Patient Agent 不得看到完整隐藏病例、标准诊断、rubric 全量或真实治疗建议。
- 生产环境不应保存 API Key 明文；本地演示 runtime SQLite 只适合作为开发过渡方案。

## Roadmap

1. **Turn Memory 与 Trace 底座**：统一记录原始话轮和结构化 turn memory，训练事件携带可审计 `agent_turn`。
2. **Turn Intent Agent**：把关键词识别降级为 hints，引入可注入的意图识别 Agent。
3. **Patient / Coach 分工**：每轮可见回复由 Patient Agent 或 Coach Agent 生成，边界话术也走受控回复层。
4. **Teaching Strategy Agent**：让 `/hint`、阶段引导、enabled Skill 注入和动态教学重点共用训练记忆。
5. **Skill 进化接入训练记忆**：候选 Skill 不只来自最终报告，也来自多轮对话中的跳步、偏题、过早诊断和检查滥用模式。
6. **管理端审计台**：展示每轮输入、意图识别、事实门禁、Agent 路径、模型调用状态、回复和安全校验。

## Acceptance Tests

- `你好`、`你是谁`、偏题输入不会被固定话术短路，会进入受控回复 Agent 并写入 turn memory。
- 有效问诊只披露本轮允许事实。
- 索要标准答案和治疗建议不会泄露诊断、治疗方案或剂量。
- 训练事件可追溯每轮 Agent 路径和事实门禁结果。
- 无外部 LLM 时，deterministic / fake agent 路径能完整通过测试。
