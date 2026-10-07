import assert from "node:assert/strict";
import test from "node:test";
import { readerRepairDecision, shouldAdvanceSerialChapter } from "./novel-auto-flow";

test("unapproved reader results cannot silently advance to delivery", () => {
  for (const verdict of ["", "unknown"]) assert.ok(readerRepairDecision(verdict, true, 0, 2).pauseReason);
  assert.deepEqual(readerRepairDecision("revise", true, 0, 2), { repair: true, pauseReason: "" });
  assert.deepEqual(readerRepairDecision("reject", true, 1, 2), { repair: true, pauseReason: "" });
  assert.ok(readerRepairDecision("revise", true, 2, 2).pauseReason);
  assert.deepEqual(readerRepairDecision("pass", true, 2, 2), { repair: false, pauseReason: "" });
  assert.deepEqual(readerRepairDecision("revise", false, 2, 2), { repair: true, pauseReason: "" });
});

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
