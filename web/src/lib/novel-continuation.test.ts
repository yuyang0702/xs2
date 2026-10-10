import assert from "node:assert/strict";
import { test } from "node:test";
import { nextNovelStageAfterReferenceAdoption } from "./novel-continuation";

const setupComplete = ["build", "character", "story-plan", "outline"];

test("reference adoption reports the earliest unfinished production prerequisite", () => {
  assert.equal(nextNovelStageAfterReferenceAdoption([], "mvp"), "build");
  assert.equal(nextNovelStageAfterReferenceAdoption(["build"], "mvp"), "character");
  assert.equal(nextNovelStageAfterReferenceAdoption(["build", "character"], "mvp"), "story-plan");
});

test("a stale chapter plan routes the user back to planning before prose generation", () => {
  assert.equal(
    nextNovelStageAfterReferenceAdoption(setupComplete, "mvp", {
      ready: false,
      action: "outline",
      chapter: "0001",
      message: "第 1 章方案依据已变化。",
      reason_code: "adopted_plan_stale",
    }),
    "outline",
  );
});

test("a valid plan keeps the current writing stage as the next action", () => {
  assert.equal(
    nextNovelStageAfterReferenceAdoption(setupComplete, "mvp", {
      ready: true,
      action: "mvp",
      chapter: "0001",
      message: "可以开始正文。",
    }),
    "mvp",
  );
  assert.equal(nextNovelStageAfterReferenceAdoption([...setupComplete, "mvp"], "polish"), "polish");
});
