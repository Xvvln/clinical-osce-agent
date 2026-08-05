import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import ts from "typescript";

function loadReportModel() {
  const source = readFileSync(new URL("./src/app/report/report-model.ts", import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
  });
  const sandbox = { exports: {} };
  vm.runInNewContext(outputText, sandbox, { filename: "report-model.ts" });
  return sandbox.exports;
}

test("report model normalizes partial not-ready AI reflection and personal skill payloads", () => {
  const { normalizeFeedbackReport } = loadReportModel();

  const report = normalizeFeedbackReport({
    session_id: "draft_session",
    case_id: "appendicitis_001",
    total_score: 0,
    dimension_scores: {},
    rubric_scores: {},
    missed_items: [],
    strengths: [],
    reasoning_errors: [],
    next_recommendations: [],
    source_references: [],
    feedback_summary: "提交诊断后生成完整报告。",
    ai_reflection_review: {
      status: "not_ready",
      reason: "ai_reflection_not_recorded",
      summary: "提交诊断后生成 AI 复盘。",
    },
    personal_skill_candidate: {
      status: "not_ready",
      reason: "personal_skill_not_recorded",
      candidate_id: null,
      skill_id: null,
      scope: "personal",
    },
  });

  assert.equal(Array.isArray(report.ai_reflection_review.mistake_patterns), true);
  assert.equal(report.ai_reflection_review.mistake_patterns.length, 0);
  assert.equal(report.ai_reflection_review.teacher_feedback, "");
  assert.equal(report.ai_reflection_review.next_focus, "");
  assert.equal(Array.isArray(report.ai_reflection_review.source_references), true);
  assert.equal(report.ai_reflection_review.source_references.length, 0);
  assert.equal(Array.isArray(report.ai_reflection_review.source_reference_items), true);
  assert.equal(report.ai_reflection_review.source_reference_items.length, 0);
  assert.equal(report.ai_reflection_review.teacher_analysis_context.analysis_summary, "");
  assert.equal(report.ai_reflection_review.teacher_analysis_context.student_thinking_hypothesis, "");
  assert.equal(Object.keys(report.ai_reflection_review.teacher_analysis_context.clinical_thinking_profile).length, 0);
  assert.deepEqual(
    { ...report.ai_reflection_review.teacher_analysis_context.longitudinal_context.gap_status_counts },
    {
      first_seen_current_window: 0,
      repeated: 0,
      reactivated_after_improvement: 0,
      recovered_since_previous_report: 0,
    },
  );
  assert.equal(report.ai_reflection_review.teacher_analysis_context.longitudinal_context.applied_personal_skills.length, 0);
  assert.equal(report.personal_skill_candidate.teacher_analysis_context.analysis_summary, "");
  assert.equal(report.personal_skill_candidate.teacher_analysis_context.student_thinking_hypothesis, "");
  assert.equal(Object.keys(report.personal_skill_candidate.teacher_analysis_context.clinical_thinking_profile).length, 0);
  assert.equal(Array.isArray(report.personal_skill_candidate.rag_evidence_items), true);
  assert.equal(report.personal_skill_candidate.rag_evidence_items.length, 0);
  assert.equal(Array.isArray(report.personal_skill_candidate.external_evidence_checks), true);
  assert.equal(report.personal_skill_candidate.external_evidence_checks.length, 0);
  assert.equal(report.personal_skill_candidate.web_check_status, "not_configured");
  assert.equal(report.student_training_report.version, "student_training_report_v2");
  assert.equal(report.student_training_report.decision_replays.length, 1);
  assert.equal(report.student_training_report.training_prescriptions.length, 1);
  assert.equal(report.student_training_report.longitudinal_summary.status, "insufficient_history");
});

test("report model blocks internal identifiers from student-facing training report fields", () => {
  const { normalizeFeedbackReport } = loadReportModel();
  const rawSessionId = "5d459949-de1e-4e4d-83ea-4d9d026b268e";
  const report = normalizeFeedbackReport({
    session_id: rawSessionId,
    case_id: "appendicitis_001",
    total_score: 83,
    dimension_scores: {},
    rubric_scores: {},
    missed_items: [],
    strengths: [],
    reasoning_errors: [],
    next_recommendations: [],
    source_references: [],
    feedback_summary: "本轮报告已生成。",
    student_training_report: {
      version: "student_training_report_v2",
      status: "generated",
      outcome: {
        summary: "delayed_and_undifferentiated",
        score_summary: "本轮总分 83/100。",
        diagnosis_status: "correct",
        diagnosis_summary: rawSessionId,
        safety_summary: "本轮未记录明确安全越界。",
        communication_summary: "本轮未记录明确沟通漏项。",
      },
      decision_replays: [{
        replay_id: "decision-1",
        kind: "reasoning",
        phase: "clinical_reasoning",
        title: "evidence_collection_without_target",
        observed_evidence: rawSessionId,
        teacher_judgement: "需要补齐证据链。",
        why_it_matters: "结论需要可观察证据支持。",
        next_action: "下一轮先明确假设，再选择验证动作。",
        evidence_labels: ["narrow_and_exclusion_absent"],
      }],
      training_prescriptions: [],
      longitudinal_summary: {
        status: "repeated",
        label: "连续出现",
        summary: "2 个问题连续出现。",
      },
      personal_memory_summary: "explicit_hypothesis_before_physical_exam",
    },
  });

  const serializedStudentReport = JSON.stringify(report.student_training_report);
  assert.equal(serializedStudentReport.includes(rawSessionId), false);
  assert.equal(serializedStudentReport.includes("delayed_and_undifferentiated"), false);
  assert.equal(serializedStudentReport.includes("evidence_collection_without_target"), false);
  assert.equal(serializedStudentReport.includes("narrow_and_exclusion_absent"), false);
  assert.equal(serializedStudentReport.includes("explicit_hypothesis_before_physical_exam"), false);
  assert.equal(report.student_training_report.outcome.score_summary, "本轮总分 83/100。");
  assert.equal(report.student_training_report.longitudinal_summary.repeated_count, 0);
});

test("report model retains only the compact longitudinal teaching summary", () => {
  const { normalizeFeedbackReport } = loadReportModel();
  const report = normalizeFeedbackReport({
    session_id: "longitudinal_context_session",
    case_id: "appendicitis_001",
    total_score: 63,
    dimension_scores: {},
    rubric_scores: {},
    missed_items: [],
    strengths: [],
    reasoning_errors: [],
    next_recommendations: [],
    source_references: [],
    feedback_summary: "纵向复盘报告。",
    ai_reflection_review: {
      status: "ready",
      summary: "教师复盘已生成。",
      teacher_analysis_context: {
        longitudinal_context: {
          report_window_size: 3,
          gap_status_counts: {
            first_seen_current_window: 2,
            repeated: 1,
            reactivated_after_improvement: 1,
            recovered_since_previous_report: 3,
          },
          applied_personal_skills: [
            { skill_id: "skill-personal-1", title: "证据链补强" },
            { skill_id: "skill-personal-2", title: "鉴别诊断拓展" },
          ],
          recent_report_session_ids: ["must-not-render-1", "must-not-render-2"],
        },
      },
    },
  });

  const longitudinalContext = report.ai_reflection_review.teacher_analysis_context.longitudinal_context;
  assert.deepEqual(
    { ...longitudinalContext.gap_status_counts },
    {
      first_seen_current_window: 2,
      repeated: 1,
      reactivated_after_improvement: 1,
      recovered_since_previous_report: 3,
    },
  );
  assert.equal(longitudinalContext.applied_personal_skills.length, 2);
  assert.equal("recent_report_session_ids" in longitudinalContext, false);
  assert.equal("report_window_size" in longitudinalContext, false);
});

test("report model preserves TeacherAgent thinking profile for reflection and personal skill", () => {
  const { normalizeFeedbackReport } = loadReportModel();

  const teacherAnalysisContext = {
    agent_id: "teacher_agent",
    analysis_mode: "post_session_teacher_analysis",
    analysis_summary: "学生没有把病史、查体和排除依据组织成验证链。",
    student_thinking_hypothesis: "学生过早进入结论，验证动作不足。",
    clinical_thinking_profile: {
      hypothesis_management: "诊断假设形成偏早。",
      verification_strategy: "查体和检查没有围绕假设形成证据。",
    },
    skill_memory_focus: {
      problem_pattern_summary: "假设形成后缺少验证路径",
      recommended_intervention: "用反问要求学生说明下一步证据验证什么。",
    },
    source_anchor_labels: ["追问疼痛部位及转移特征"],
  };

  const report = normalizeFeedbackReport({
    session_id: "teacher_context_session",
    case_id: "appendicitis_001",
    total_score: 55,
    dimension_scores: {},
    rubric_scores: {},
    missed_items: [],
    strengths: [],
    reasoning_errors: [],
    next_recommendations: [],
    source_references: [],
    feedback_summary: "教师分析报告。",
    ai_reflection_review: {
      status: "ready",
      summary: "教师复盘已生成。",
      teacher_analysis_context: teacherAnalysisContext,
    },
    personal_skill_candidate: {
      status: "approved",
      candidate_id: "candidate-1",
      skill_id: "skill-1",
      scope: "personal",
      teacher_analysis_context: teacherAnalysisContext,
    },
  });

  assert.equal(report.ai_reflection_review.teacher_analysis_context.student_thinking_hypothesis, "学生过早进入结论，验证动作不足。");
  assert.equal(
    report.ai_reflection_review.teacher_analysis_context.clinical_thinking_profile.verification_strategy,
    "查体和检查没有围绕假设形成证据。",
  );
  assert.equal(
    report.personal_skill_candidate.teacher_analysis_context.skill_memory_focus.recommended_intervention,
    "用反问要求学生说明下一步证据验证什么。",
  );
});

test("report model collapses repeated training actions from legacy reports", () => {
  const { normalizeFeedbackReport } = loadReportModel();
  const repeatedGap = {
    dimension_id: "relationship_building",
    rubric_item_id: "",
    gap_type: "relationship_empathy_missing",
    label: "错失患者沟通信号",
    missing_score: 2,
    severity: "medium",
    evidence_summary: "我很担心是不是严重的病。",
    next_training_action: "下一轮先回应患者情绪，再继续医学问诊。",
    skill_type: "relationship_repair",
    gap_source: "missed_opportunity",
  };
  const report = normalizeFeedbackReport({
    session_id: "legacy_duplicate_gaps",
    case_id: "acs_001",
    total_score: 75,
    dimension_scores: {},
    rubric_scores: {},
    missed_items: [],
    training_gaps: [
      repeatedGap,
      { ...repeatedGap, evidence_summary: "我还是很害怕。" },
      { ...repeatedGap, gap_type: "communication_summary_missing" },
    ],
    strengths: [],
    reasoning_errors: [],
    next_recommendations: [],
    source_references: [],
    feedback_summary: "旧报告包含重复训练动作。",
  });

  assert.equal(report.training_gaps.length, 2);
  assert.equal(report.training_gaps[0].gap_type, "relationship_empathy_missing");
  assert.equal(report.training_gaps[1].gap_type, "communication_summary_missing");
});
