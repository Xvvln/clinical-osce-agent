import { strict as assert } from "node:assert";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

const rootPageUrl = new URL("./src/app/page.tsx", import.meta.url);
const dashboardUrl = new URL("./src/app/v2/admin-v2-dashboard.tsx", import.meta.url);

const rootPageSource = existsSync(rootPageUrl) ? readFileSync(rootPageUrl, "utf8") : "";
const dashboardSource = existsSync(dashboardUrl) ? readFileSync(dashboardUrl, "utf8") : "";

function expectSourceContains(source, values) {
  for (const value of values) {
    assert.match(source, new RegExp(value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `expected source to contain ${value}`);
  }
}

test("admin root delegates to the v2 dashboard instead of carrying a second dashboard implementation", () => {
  assert.ok(existsSync(rootPageUrl), "admin root page should exist");
  assert.ok(existsSync(dashboardUrl), "admin v2 dashboard should exist");
  assert.match(rootPageSource, /from "\.\/v2\/admin-v2-dashboard"/);
  assert.match(rootPageSource, /<AdminV2Dashboard \/>/);
  assert.doesNotMatch(rootPageSource, /type AdminSessionSummary = Readonly<\{/);
});

test("admin skill review smoke test follows the current v2 dashboard contract", () => {
  expectSourceContains(dashboardSource, [
    "type TrainingSkillCandidateSummary = Readonly<{",
    "type TrainingSkillCandidateDetail = TrainingSkillCandidateSummary",
    "type TrainingSkillAutoApprovalSettings = Readonly<{",
    "type TrainingSkillApprovalAgentReview = Readonly<{",
    "type TrainingSkillTeachingAction = Readonly<{",
    "/api/admin/evolution/candidates?limit=20&review_status=all",
    "/api/admin/evolution/candidates/${candidateId}",
    "/api/admin/evolution/candidates/${candidateId}/events",
    "/api/admin/evolution/approve",
    "/api/admin/evolution/reject",
    "/api/admin/evolution/settings",
    "/api/admin/evolution/candidates/generate",
    "批准并启用",
    "拒绝候选",
    "开启自动应用",
    "关闭自动应用",
    "完整 Skill 内容",
    "适用时机",
    "成功指标",
    "来源报告",
    "审批修改",
    "知识与回归门",
    "getApprovalChangedFieldsText",
    "getApprovalEvidenceText",
    "ready_for_human_review",
    "审批通过，待教师确认",
  ]);
});

test("admin review actions only send candidate id and keep readable labels in the UI", () => {
  assert.match(dashboardSource, /body: JSON\.stringify\(\{ candidate_id: candidateId \}\)/);
  expectSourceContains(dashboardSource, [
    "candidate.skill_type_label",
    "candidate.trigger_item_labels",
    "candidate.case_titles",
    "getCandidateStatusLabel(candidate.status)",
    "getCandidateStatusLabel(selectedCandidate.status)",
    "selectedCandidate.stage_scope_labels",
    "related_recommendation_labels?: readonly string[];",
  ]);
  assert.doesNotMatch(dashboardSource, /<pre/);
  assert.doesNotMatch(dashboardSource, /原始 JSON/);
});

test("admin v2 keeps skill details and audit trails in modal or focused panels", () => {
  expectSourceContains(dashboardSource, [
    "function SkillSection",
    "selectedCandidateEvents",
    "AuditEventList",
    "自动应用开启",
    "人工审核",
    "审批 Agent",
    "自动回归测试",
    "全局审核审计",
  ]);
});
