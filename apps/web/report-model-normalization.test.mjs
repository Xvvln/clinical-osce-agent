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
  assert.equal(Array.isArray(report.personal_skill_candidate.rag_evidence_items), true);
  assert.equal(report.personal_skill_candidate.rag_evidence_items.length, 0);
  assert.equal(Array.isArray(report.personal_skill_candidate.external_evidence_checks), true);
  assert.equal(report.personal_skill_candidate.external_evidence_checks.length, 0);
  assert.equal(report.personal_skill_candidate.web_check_status, "not_configured");
});
