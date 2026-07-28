import { strict as assert } from "node:assert";
import { afterEach, test } from "node:test";

import {
  deleteTrainingHistoryRecord,
  readTrainingHistoryRecords,
  TRAINING_HISTORY_STORAGE_KEY,
} from "./src/app/training-history.ts";

const originalWindowDescriptor = Object.getOwnPropertyDescriptor(globalThis, "window");

function createLocalStorage(initialEntries = []) {
  const values = new Map(initialEntries);

  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    removeItem(key) {
      values.delete(key);
    },
    setItem(key, value) {
      values.set(key, value);
    },
  };
}

function installWindow(localStorage) {
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { localStorage },
    writable: true,
  });
}

afterEach(() => {
  if (originalWindowDescriptor) {
    Object.defineProperty(globalThis, "window", originalWindowDescriptor);
    return;
  }

  delete globalThis.window;
});

test("readTrainingHistoryRecords removes malformed legacy JSON", () => {
  const localStorage = createLocalStorage([[TRAINING_HISTORY_STORAGE_KEY, "{malformed"]]);
  installWindow(localStorage);

  assert.deepEqual(readTrainingHistoryRecords(), []);
  assert.equal(localStorage.getItem(TRAINING_HISTORY_STORAGE_KEY), null);
});

test("deleteTrainingHistoryRecord succeeds when legacy JSON is malformed", () => {
  const localStorage = createLocalStorage([[TRAINING_HISTORY_STORAGE_KEY, "[not-json"]]);
  installWindow(localStorage);

  assert.deepEqual(deleteTrainingHistoryRecord("session-1"), []);
  assert.equal(localStorage.getItem(TRAINING_HISTORY_STORAGE_KEY), null);
});
