import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const pageSource = readFileSync(new URL("./src/app/page.tsx", import.meta.url), "utf8");

function getHeaderSource() {
  const headerMatch = pageSource.match(/<header[\s\S]*?<\/header>/);
  assert.ok(headerMatch, "home page should render a top header");
  return headerMatch[0];
}

test("home header exposes compact safety and source links", () => {
  const headerSource = getHeaderSource();

  assert.match(headerSource, /href="\/safety"[\s\S]*?>\s*安全声明\s*<\/Link>/);
  assert.match(headerSource, /href="\/sources"[\s\S]*?>\s*数据来源\s*<\/Link>/);
});

test("home page does not render large safety and source panels", () => {
  assert.doesNotMatch(pageSource, /<Panel title="安全声明"/);
  assert.doesNotMatch(pageSource, /<Panel title="数据来源"/);
});

test("home side panel shows procedure results before diagnosis hypotheses", () => {
  const procedurePanelIndex = pageSource.indexOf('<Panel title="查体与检查申请">');
  const hypothesisPanelIndex = pageSource.indexOf('<Panel title="诊断假设">');

  assert.notEqual(procedurePanelIndex, -1);
  assert.notEqual(hypothesisPanelIndex, -1);
  assert.ok(procedurePanelIndex < hypothesisPanelIndex);
});

test("home diagnosis hypothesis panel can record in-progress hypotheses", () => {
  assert.match(pageSource, /function recordHypothesis\(sessionId: string, hypothesis: string\): Promise<OsceSession>/);
  assert.match(pageSource, /\/api\/sessions\/\$\{sessionId\}\/hypotheses/);
  assert.match(pageSource, /id="hypothesis-input"/);
  assert.match(pageSource, />\{isRecordingHypothesis \? "记录中" : "记录假设"\}<\/button>/);
});


test("home workspace can request socratic hints and render coach messages", () => {
  assert.match(pageSource, /type HintResponse = OsceSession &/);
  assert.match(pageSource, /function requestHint\(sessionId: string\): Promise<HintResponse>/);
  assert.match(pageSource, /\/api\/sessions\/\$\{sessionId\}\/hint/);
  assert.match(pageSource, /message\.role === "coach"/);
  assert.match(pageSource, /label: "过程提示"/);
  assert.match(pageSource, /onClick=\{handleHintRequest\}/);
  assert.match(pageSource, />\{isRequestingHint \? "提示生成中" : "请求提示"\}<\/button>/);
});
