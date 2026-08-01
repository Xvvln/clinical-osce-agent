import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import ts from "typescript";

function loadLearningPathTargetModel() {
  const source = readFileSync(new URL("./src/app/profile/learning-path-target.ts", import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
  });
  const sandbox = { exports: {} };
  vm.runInNewContext(outputText, sandbox, { filename: "learning-path-target.ts" });
  return sandbox.exports;
}

test("learning target keys include the source case when item ids repeat", () => {
  const { getLearningPathTargetKey } = loadLearningPathTargetModel();
  const task = {
    case_id: "acs_001",
    target_rubric_items: ["reasoning_core", "reasoning_core"],
    target_rubric_item_refs: [
      { case_id: "acs_001", item_id: "reasoning_core" },
      { case_id: "heart_failure_001", item_id: "reasoning_core" },
    ],
  };

  const keys = [
    getLearningPathTargetKey(task, "急性冠脉综合征推理链", 0),
    getLearningPathTargetKey(task, "心力衰竭推理链", 1),
  ];

  assert.deepEqual(keys, ["acs_001-reasoning_core-0", "heart_failure_001-reasoning_core-1"]);
  assert.equal(new Set(keys).size, keys.length);
});

test("legacy learning targets still receive collision-free keys", () => {
  const { getLearningPathTargetKey } = loadLearningPathTargetModel();
  const task = {
    case_id: "acs_001",
    target_rubric_items: ["reasoning_core", "reasoning_core"],
  };

  const keys = [
    getLearningPathTargetKey(task, "急性冠脉综合征推理链", 0),
    getLearningPathTargetKey(task, "心力衰竭推理链", 1),
  ];

  assert.equal(new Set(keys).size, keys.length);
});
