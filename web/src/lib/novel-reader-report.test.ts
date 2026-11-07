import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import NovelReaderReport from "../components/NovelReaderReport";
Object.assign(globalThis, { React });

test("separate fact and expression findings and original evidence remain visible", () => {
  const report = { verdict: "revise", continue_reading_score: 95,
    fact_review: { verdict: "pass", summary: "金额与结局成立" },
    expression_review: { verdict: "revise", summary: "交谈后的解释重复" },
    issues: [{ location: "署名交谈", excerpts: ["她不再等他认错。", "她等的已经不是一句认错。"], impact: "同一决定被解释两次", goal: "保留决定并合并说明", priority: "medium" }] };
  const html = renderToStaticMarkup(createElement(NovelReaderReport, { report }));
  for (const value of ["事实与情节", "对白与表达", "金额与结局成立", "交谈后的解释重复", "原文依据", "她不再等他认错。", "她等的已经不是一句认错。"]) assert.ok(html.includes(value), value);
});

test("structured reader issues show all locations, impacts, goals and priorities", () => {
  const report = { verdict: "revise", continue_reading_score: 76, summary: "中段节奏偏慢", issues: Array.from({ length: 5 }, (_, i) => ({ location: `第${i + 1}处场景`, impact: "重复核账削弱紧迫感", goal: "压缩流程并保留人物选择", priority: "high" })), dimensions: { character_motivation: { note: "需要补足挪水动机" } }, repair_constraints: ["保留第三人称视角"] };
  const html = renderToStaticMarkup(createElement(NovelReaderReport, { report }));
  for (const expected of ["76", "建议返修", "第5处场景", "阅读影响", "修改目标", "优先处理", "人物动机", "保留第三人称视角"]) assert.ok(html.includes(expected), expected);
  assert.ok(!html.includes("[object Object]"));
});

test("older string issues and nested model output remain readable", () => {
  const html = renderToStaticMarkup(createElement(NovelReaderReport, { report: { verdict: "reject", issues: ["钩子不足", { description: { problem: "重复说明", fix: "删除重复段落" } }] } }));
  for (const expected of ["需要重写", "钩子不足", "重复说明", "删除重复段落"]) assert.ok(html.includes(expected));
  assert.ok(!html.includes("[object Object]"));
});
