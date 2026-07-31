-- TraceOSCE 2026-08-01 比赛功能验收报告的脱敏、可复算数据集。
-- 数据只保留聚合结论，不含账号、密钥、原始 session 标识或完整学生对话。

CREATE TEMP VIEW acceptance_matrix AS
SELECT 1 AS "order", '过程评分，不只看最终诊断' AS claim, '通过' AS result,
       '问诊、查体、检查、假设与最终提交分别进入量表和证据链；存在诊断正确但过程分较低的受控轮次。' AS evidence,
       '分数反映当前量表覆盖，不等于临床执业能力。' AS boundary
UNION ALL SELECT 2, '人文沟通有证据', '通过',
       '人文沟通先由本地信号筛选，再至多调用一次模型复核，并把命中语句保留到报告。',
       '识别的是训练对话表现，不做人格判断。'
UNION ALL SELECT 3, '学生越熟练，提示越少', '通过',
       '首轮出现 3 级不同提示；中间高覆盖轮次无需提示；出现新缺口时提示重新激活。',
       '提示数量受学生主动求助和当前缺口共同影响。'
UNION ALL SELECT 4, 'Patient、Teacher、Approval 边界清楚', '通过',
       '标准化病人负责受限病例回应；教师负责训练解释；Skill 必须经过回归门与审批后才可生效。',
       '个人 Skill 不能修改病例事实、标准答案或安全规则。'
UNION ALL SELECT 5, '报告反哺下一轮', '通过',
       '第 2 轮实际使用了上一轮 3 个反馈目标；纵向报告区分持续、复现与恢复。',
       '调用 Skill 不自动等于学习有效。'
UNION ALL SELECT 6, '来源与模型可追溯', '通过',
       '报告保留训练点和检索来源；最终调用审计中无境外模型，主要调用可绑定到训练 session。',
       '对用户展示脱敏来源，不暴露密钥和内部标识。'
UNION ALL SELECT 7, '至少五病例可运行', '通过',
       '阑尾炎连续 7 轮；急性冠脉综合征、心衰、甲亢和肺炎完成跨病例验收。',
       '病例通过不代表所有输入组合都已穷举。';

CREATE TEMP VIEW appendicitis_rounds AS
SELECT 1 AS round, 56 AS score, 18 AS missed, 3 AS hints, '基础问诊不完整；连续使用三级提示。' AS observable_change
UNION ALL SELECT 2, 91, 3, 1, '主动使用上一轮 3 个反馈目标，提示明显减少。'
UNION ALL SELECT 3, 91, 3, 0, '无需提示完成主要路径，仍保留少量稳定缺口。'
UNION ALL SELECT 4, 93, 2, 0, '被观察的旧缺口恢复。'
UNION ALL SELECT 5, 83, 7, 1, '出现真实回退，新缺口触发提示。';

CREATE TEMP VIEW appendicitis_score_comparison AS
SELECT '第1轮' AS round_label, 56 AS score
UNION ALL SELECT '第2轮', 91
UNION ALL SELECT '第3轮', 91
UNION ALL SELECT '第4轮', 93
UNION ALL SELECT '第5轮', 83
UNION ALL SELECT '第6轮', 91
UNION ALL SELECT '第7轮', 85;

CREATE TEMP VIEW longitudinal_labels AS
SELECT 6 AS round, 91 AS score, 1 AS first, 2 AS repeated, 0 AS reactivated, 5 AS recovered,
       'Qwen 教师分析生成成功，无警告，给出 3 条动作。' AS teacher_result
UNION ALL SELECT 7, 85, 0, 2, 4, 1,
       'Qwen 教师分析生成成功，无警告，明确识别旧问题复现。';

CREATE TEMP VIEW case_transfer AS
SELECT 1 AS "order", '急性冠脉综合征' AS "case", 75 AS score,
       '真实问诊、查体、检查和两次阶段性假设；追加复验确认教师准确读取最终推理。' AS adaptive_behavior,
       0 AS contamination
UNION ALL SELECT 2, '心力衰竭', 80,
       '修复可选重排阻塞后，在同一已完成轨迹上恢复生成报告；记录 8 次自适应跟进。', 0
UNION ALL SELECT 3, '甲状腺功能亢进', 70,
       '完成两阶段假设与针对性检查，报告和个人 Skill 正常生成。', 0
UNION ALL SELECT 4, '肺炎', 75,
       '完成两阶段假设与针对性检查，报告和个人 Skill 正常生成。', 0;

CREATE TEMP VIEW regression_summary AS
SELECT 1 AS "order", '后端 API' AS surface, 1121 AS passed, 0 AS failed,
       '全量 pytest；重启后 /health 与 /ready 正常；2 条第三方依赖弃用预告。' AS additional_checks, '通过' AS result
UNION ALL SELECT 2, '学生端', 131, 0,
       'TypeScript 类型检查通过；Next.js 生产构建通过，共 10 个路由；重启后入口 200。', '通过'
UNION ALL SELECT 3, '教师管理端', 26, 0,
       'TypeScript 类型检查通过；Next.js 生产构建通过，共 5 个页面；重启后入口 200。', '通过';

CREATE TEMP VIEW issues_fixed AS
SELECT 1 AS "order", '教师模型超时后报告核心字段为空' AS problem,
       '学生看到空泛或残缺结论。' AS impact,
       '只回填空字段，保留已成功生成的 Qwen 内容；超时使用有证据的确定性分析。' AS resolution,
       '第 6、7 轮 Qwen 正常生成；超时路径有持久化回退测试。' AS verification
UNION ALL SELECT 2, '报告增强任务可能长期停在 pending',
       '教师端看不到最终 Skill 或失败原因。',
       '超时采用受控模板；深层失败写入明确 failed 状态。',
       '后台流程不再永久 pending，相关 51 项测试通过。'
UNION ALL SELECT 3, '可选 rerank 超时导致主报告 504',
       '已经完成训练的学生拿不到报告。',
       '超时或过载退回本地向量顺序；请求策略错误仍显式抛出。',
       '同一心衰轨迹恢复生成，检索相关 48 项测试通过。'
UNION ALL SELECT 4, '教师分析没有收到学生最终推理',
       'Qwen 误写“学生推理为空”。',
       '教师请求和失败回退都使用真实最终诊断与推理，但不扩张对外报告接口。',
       '追加 11 回合急性冠脉综合征复验未再出现空提交误判。'
UNION ALL SELECT 5, '报告建议过长且事实可能互相冲突',
       '学生不知道下一轮先练什么。',
       '首屏固定为分数、首要薄弱点和最多 3 条动作；深层证据默认折叠并做事实一致性保护。',
       '连续训练每轮建议保持 2—3 条，前端测试和生产构建通过。'
UNION ALL SELECT 6, '硬性模型策略错误可能被宽泛异常吞掉',
       '请求体过大等配置问题被伪装成正常降级。',
       '只允许超时和过载走业务回退，其他策略错误优先重新抛出。',
       '针对性 122 项与最终后端 1121 项回归全部通过。';

SELECT 'acceptance_matrix' AS dataset, COUNT(*) AS row_count FROM acceptance_matrix
UNION ALL SELECT 'appendicitis_rounds', COUNT(*) FROM appendicitis_rounds
UNION ALL SELECT 'appendicitis_score_comparison', COUNT(*) FROM appendicitis_score_comparison
UNION ALL SELECT 'longitudinal_labels', COUNT(*) FROM longitudinal_labels
UNION ALL SELECT 'case_transfer', COUNT(*) FROM case_transfer
UNION ALL SELECT 'regression_summary', COUNT(*) FROM regression_summary
UNION ALL SELECT 'issues_fixed', COUNT(*) FROM issues_fixed;
