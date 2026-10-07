import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import NovelArchiveContent from "../components/NovelArchiveContent";
import NovelReferenceContent from "../components/NovelReferenceContent";
import { parseArchiveJSON, readableArchiveMarkdown } from "./novel-archive";

test("location archives render Chinese fields and named cards without JSON syntax", () => {
  const content = JSON.stringify({ space_time: { key_locations: [{ name: "白汀水库", terrain: "山间库盆", controlling_force: "留守站", risk: "滑坡" }] } });
  const html = renderToStaticMarkup(createElement(NovelArchiveContent, { content, structured: true }));
  for (const expected of ["白汀水库", "关键地点", "地形", "控制势力", "滑坡"]) assert.ok(html.includes(expected));
  assert.ok(!html.includes("space_time"));
  assert.ok(!html.includes("controlling_force"));
  assert.ok(!html.includes("<pre"));
});

test("JSON stored as a string or embedded in older Markdown also renders readably", () => {
  const value = { core_laws: { essence: "没有无代价治愈" } };
  assert.deepEqual(parseArchiveJSON(JSON.stringify(JSON.stringify(value))), { parsed: true, value });
  const readable = readableArchiveMarkdown('# Style Profile\n\n- narrative pov：third_person\n\n```json\n' + JSON.stringify(value) + '\n```');
  assert.ok(readable.includes("统一风格基线"));
  assert.ok(readable.includes("叙事视角：第三人称"));
  assert.ok(readable.includes("核心法则"));
  assert.ok(!readable.includes("core_laws"));
  assert.ok(!readable.includes("```"));
});

test("malformed structured archives show a useful failure instead of dumping raw JSON", () => {
  const html = renderToStaticMarkup(createElement(NovelArchiveContent, { content: '{"secret":', structured: true }));
  assert.ok(html.includes("暂时无法展示"));
  assert.ok(!html.includes("secret"));
});

test("dynamic character state renders named characters and current knowledge as fields", () => {
  const content = JSON.stringify({ "档案进度": "已更新至第 2 章", "人物状态": [{ name: "赵磊", identity: "普通租客", snapshot: { knowledge: "知道邻居已经付款", emotion: "想帮忙但怕担责" }, evidence_position: "第12段" }] });
  const html = renderToStaticMarkup(createElement(NovelReferenceContent, { content }));
  for (const expected of ["赵磊", "当前处境", "所知信息", "情绪", "依据位置", "已更新至第 2 章"]) assert.ok(html.includes(expected));
  for (const raw of ["snapshot", "knowledge", "evidence_position", "<pre"]) assert.ok(!html.includes(raw));
});

test("bold Markdown field labels do not expose formatting markers in archive readers", () => {
  const html = renderToStaticMarkup(createElement(NovelReferenceContent, { content: "## 赵磊\n\n- **身份**：普通租客\n- **当前目标**：换水" }));
  assert.ok(html.includes("普通租客") && html.includes("当前目标"));
  assert.ok(!html.includes("**身份**") && !html.includes("**当前目标**"));
});
