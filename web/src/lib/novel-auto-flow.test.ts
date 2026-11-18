import assert from "node:assert/strict";
import test from "node:test";
import { shouldAdvanceSerialChapter } from "./novel-auto-flow";

test("serial batches stop at their requested count and short stories never add another chapter", () => {
  const finished: number[] = [];
  let started: number | null = null;
  do { started = (started || 0) + 1; finished.push(started); } while (shouldAdvanceSerialChapter("serial", "serial_batch", started, 3));
  assert.deepEqual(finished, [1, 2, 3]);
  assert.equal(shouldAdvanceSerialChapter("serial", "serial_batch", 1, 1), false);
  assert.equal(shouldAdvanceSerialChapter("short", "serial_batch", 1, 5), false);
  assert.equal(shouldAdvanceSerialChapter("serial", "short_full", 1, 5), false);
  assert.equal(shouldAdvanceSerialChapter("serial", "serial_batch", 1, 5, "book_final"), false);
  assert.equal(shouldAdvanceSerialChapter("serial", "serial_batch", 1, 5, "continue"), true);
});
