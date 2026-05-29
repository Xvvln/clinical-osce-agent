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
  assert.equal(report.personal_skill_candidate.teacher_analysis_context.analysis_summary, "");
  assert.equal(report.personal_skill_candidate.teacher_analysis_context.student_thinking_hypothesis, "");
  assert.equal(Object.keys(report.personal_skill_candidate.teacher_analysis_context.clinical_thinking_profile).length, 0);
  assert.equal(Array.isArray(report.personal_skill_candidate.rag_evidence_items), true);
  assert.equal(report.personal_skill_candidate.rag_evidence_items.length, 0);
  assert.equal(Array.isArray(report.personal_skill_candidate.external_evidence_checks), true);
  assert.equal(report.personal_skill_candidate.external_evidence_checks.length, 0);
  assert.equal(report.personal_skill_candidate.web_check_status, "not_configured");
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
