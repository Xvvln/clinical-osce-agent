# Coach Hint Policy

## 背景

画像和长期 Skill 会把学生的短期问题、反复问题和下一轮训练目标注入到训练过程里。但这些目标不能无条件变成可见提示。

例如学生刚进入病例还没有开始问诊时，即使画像里存在 `relationship_empathy_missing`，Coach 也不应该直接提示“先回应患者担忧”。因为当前患者尚未表达担忧，正确的开场提示应当引导学生开始病史采集。

## 设计原则

- 画像和 Skill 只提供训练目标，不直接决定本轮可见提示。
- 可见提示必须经过统一策略裁决，判断当前阶段是否已经出现触发条件。
- 图节点只负责编排，不在节点里堆叠具体 gap 分支。
- 后续新增人文沟通 gap 时，优先扩展策略服务和测试，而不是在前端或图节点里追加局部补丁。

## 数据流

```text
student state
  -> build_pedagogy_state
  -> _build_socratic_hint
  -> active_training_goals_from_state
  -> resolve_coach_hint_policy
  -> CoachAgent
  -> visible hint
```

`resolve_coach_hint_policy` 输出 `CoachHintPolicyDecision`：

- `intent`: 当前提示意图，如开场引导、关系修复、伦理同意、阶段总结。
- `hint`: 当前阶段默认提示。
- `training_goal_hint`: 已满足触发条件后才注入的训练目标提示。
- `selected_goal_type`: 本轮被选中的 gap 类型。
- `suppressed_goal_types`: 因当前场景未触发而被暂缓的 gap 类型。
- `candidate_goal_types`: 来自画像或 Skill 的候选 gap 类型。

这些字段会写入 `hint_context.hint_policy`，用于测试、调试和后续报告分析。

## 触发规则

开场阶段：

- 没有学生训练动作时，默认意图是 `case_onboarding`。
- 只允许与开场直接相关的沟通目标进入提示，如 `communication_intro_missing`、`communication_open_question_missing`。
- 情绪回应、伦理同意、阶段总结等目标会被暂缓。

关系建立：

- `relationship_empathy_missing` 必须在患者已经表达担忧、害怕、焦虑等情绪信号后才触发。
- 如果情绪信号之后学生已经做出共情回应，则不再触发该提示。

医学伦理：

- `ethics_consent_missing` 和 `ethics_privacy_comfort_missing` 只在查体阶段触发。
- `ethics_autonomy_missing` 只在辅助检查阶段触发。
- 策略服务只决定提示时机，不修改病例事实、检查结果或评分标准。

沟通结构：

- `communication_summary_missing` 需要已有至少两个证据点，或已经进入查体、辅助检查、诊断提交阶段。
- `communication_confirm_understanding_missing` 只在需要解释检查、提交诊断或反馈阶段触发。

## 扩展方式

新增 gap 时需要同步完成：

1. 在训练 gap 生成处定义稳定的 `gap_type`、`trigger_stage` 和 `next_training_action`。
2. 在 `coach_hint_policy_service` 增加触发条件。
3. 添加策略服务单测，覆盖未触发、已触发和 recovered 状态。
4. 如影响图编排，添加 `osce_graph` 集成测试，验证 `hint_context.hint_policy`。

这样可以保证画像、Skill 和下一轮训练驱动继续走同一条可测试链路。
