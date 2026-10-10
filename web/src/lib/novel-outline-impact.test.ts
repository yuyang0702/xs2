import assert from "node:assert/strict";
import { test } from "node:test";
import { compareNovelOutlines, outlineChapterImpacts, outlineImpactInventory } from "./novel-outline-impact";

test("outline impact inventory separates plans, prose, and confirmed archives", () => {
  assert.deepEqual(outlineImpactInventory([
    { path: "planning/chapters/0001.json" },
    { path: "story/0001/chapter.md" },
    { path: "story/0001/confirmed_state.json" },
    { path: "story/0002/chapter.md" },
  ]), {
    plannedChapters: ["0001"],
    writtenChapters: ["0001", "0002"],
    confirmedChapters: ["0001"],
  });
});

test("outline impact inventory recognizes rendered chapter guides and readable archive mirrors", () => {
  assert.deepEqual(outlineImpactInventory([
    { path: "story/0001/single_chapter_guide.md" },
    { path: "story/0002/single_chapter_guide.json" },
    { path: "story/0002/confirmed_state.md" },
  ]), {
    plannedChapters: ["0001", "0002"],
    writtenChapters: [],
    confirmedChapters: ["0002"],
  });
});

test("outline comparison reports only chapters whose section changed or was added", () => {
  const previous = "### 第 1 章 不足一天\n存粮见底。\n\n### 第 2 章 门外的价\n交易压价。";
  const current = "### 第 1 章 不足一天\n存粮见底，赵磊出门。\n\n### 第 2 章 门外的价\n交易压价。\n\n### 第 3 章 隔门借粮\n邻居借粮。";
  assert.deepEqual(compareNovelOutlines(previous, current), {
    comparisonAvailable: true,
    changedChapters: ["0001", "0003"],
    changes: [
      { chapter: "0001", type: "updated" },
      { chapter: "0003", type: "added" },
    ],
  });
});

test("outline comparison asks for a manual read when chapter headings are unavailable", () => {
  assert.deepEqual(compareNovelOutlines("旧提纲", "新提纲"), {
    comparisonAvailable: false,
    changedChapters: [],
    changes: [],
  });
});

test("outline comparison reports removed chapters explicitly", () => {
  const result = compareNovelOutlines(
    "### 第1章 开局\n开局\n### 第2章 旧计划\n旧计划",
    "### 第1章 开局\n开局",
  );
  assert.deepEqual(result.changes, [{ chapter: "0002", type: "removed" }]);
});

test("outline impact names the exact existing artifacts affected in each changed chapter", () => {
  const inventory = outlineImpactInventory([
    { path: "planning/chapters/0001.json" },
    { path: "story/0001/chapter.md" },
    { path: "story/0001/confirmed_state.json" },
    { path: "planning/chapters/0002.json" },
  ]);
  assert.deepEqual(outlineChapterImpacts([
    { chapter: "0001", type: "updated" },
    { chapter: "0002", type: "removed" },
    { chapter: "0003", type: "added" },
  ], inventory), [
    { chapter: "0001", type: "updated", hasPlan: true, hasDraft: true, hasConfirmedArchive: true },
    { chapter: "0002", type: "removed", hasPlan: true, hasDraft: false, hasConfirmedArchive: false },
    { chapter: "0003", type: "added", hasPlan: false, hasDraft: false, hasConfirmedArchive: false },
  ]);
});

test("outline impact flags later existing chapter artifacts for continuity review", () => {
  const inventory = outlineImpactInventory([
    { path: "planning/chapters/0001.json" },
    { path: "planning/chapters/0002.json" },
    { path: "planning/chapters/0003.json" },
    { path: "story/0002/chapter.md" },
    { path: "story/0003/chapter.md" },
    { path: "story/0003/confirmed_state.json" },
  ]);
  assert.deepEqual(outlineChapterImpacts([
    { chapter: "0001", type: "updated" },
  ], inventory), [
    { chapter: "0001", type: "updated", hasPlan: true, hasDraft: false, hasConfirmedArchive: false },
    { chapter: "0002", type: "downstream", hasPlan: true, hasDraft: true, hasConfirmedArchive: false },
    { chapter: "0003", type: "downstream", hasPlan: true, hasDraft: true, hasConfirmedArchive: true },
  ]);
});
