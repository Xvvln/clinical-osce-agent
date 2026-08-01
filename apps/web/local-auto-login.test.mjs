import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import ts from "typescript";

function loadLocalAutoLoginModule() {
  const source = readFileSync(new URL("./src/app/local-auto-login.ts", import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
  });
  const sandbox = { exports: {} };
  vm.runInNewContext(outputText, sandbox, { filename: "local-auto-login.ts" });
  return sandbox.exports;
}

function memoryStorage({ throws = false } = {}) {
  const values = new Map();
  return {
    getItem(key) {
      if (throws) throw new Error("storage unavailable");
      return values.get(key) ?? null;
    },
    removeItem(key) {
      if (throws) throw new Error("storage unavailable");
      values.delete(key);
    },
    setItem(key, value) {
      if (throws) throw new Error("storage unavailable");
      values.set(key, value);
    },
  };
}

test("explicit logout suppresses local auto-login until a manual login succeeds", () => {
  const {
    clearLocalAutoLoginSuppression,
    isLocalAutoLoginSuppressed,
    suppressLocalAutoLogin,
  } = loadLocalAutoLoginModule();
  const storage = memoryStorage();

  assert.equal(isLocalAutoLoginSuppressed(storage), false);
  suppressLocalAutoLogin(storage);
  assert.equal(isLocalAutoLoginSuppressed(storage), true);
  clearLocalAutoLoginSuppression(storage);
  assert.equal(isLocalAutoLoginSuppressed(storage), false);
});

test("local auto-login suppression is best effort when storage is unavailable", () => {
  const {
    clearLocalAutoLoginSuppression,
    isLocalAutoLoginSuppressed,
    suppressLocalAutoLogin,
  } = loadLocalAutoLoginModule();
  const storage = memoryStorage({ throws: true });

  assert.doesNotThrow(() => suppressLocalAutoLogin(storage));
  assert.equal(isLocalAutoLoginSuppressed(storage), false);
  assert.doesNotThrow(() => clearLocalAutoLoginSuppression(storage));
});
