import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { Window } from "happy-dom";

const dom = new Window({ url: "http://localhost/" });
for (const name of ["window", "document", "Node", "Text", "HTMLElement", "HTMLTextAreaElement", "HTMLInputElement", "Element", "Event", "MouseEvent", "navigator"]) {
  Object.defineProperty(globalThis, name, { configurable: true, value: name === "window" ? dom : dom[name as keyof Window] });
}
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const React = await import("react");
const { act, createElement } = React;
Object.assign(globalThis, { React });
const { createRoot } = await import("react-dom/client");
const { default: CharacterCenterPanel } = await import("./CharacterCenterPanel");

const workspace = "C:\\Books\\井 口";
const section = { id: "voice-one", source_id: "meta/character_voice.md", source_revision: "a", group: "voice", label: "表达倾向", text: "原先说法", editable: true, ai_editable: true, line: 4 };
const oldState = { chapter: "0001", source_chapter: "0001", source_id: "story/0001/chapter.md", evidence: "纸还在桌上", snapshot: { goal: "核对纸" }, drives: {}, knowledge: [], beliefs: [], relationships: [] };
const profile = {
  revision: "a", chapter: "0001", chapters: ["0001"], stale_chapters: ["0003"], world_facts: [], warnings: [],
  sources: [{ source_id: section.source_id, status: "present", kind: "voice", revision: "a", raw: "原先说法" }],
  characters: [
    { id: "a", name: "许青", title: "许青", status: "structured", sections: [section], relationships: [
      { target: "许宁", target_id: "b", nature: "旧友", meaning: "可信", tension: "藏纸", attitude: "试探", text: "旧友", source_id: section.source_id, section_id: section.id, provenance: "voice" },
    ], states: [oldState], planned_arcs: [], raw: [{ source_id: section.source_id, title: "许青", text: "原先说法" }], warnings: [] },
    { id: "b", name: "许宁", title: "许宁", status: "legacy", sections: [], relationships: [], states: [], planned_arcs: [], raw: [{ source_id: section.source_id, title: "许宁", text: "旧档案待整理" }], warnings: [] },
  ],
};
const receipt = {
  preview_id: "signed", revision: "a", source_revision: "a", source_id: section.source_id, character_id: "a", section_id: section.id,
  before: "原先说法", after: "新的说法", line: 4, impact: "仅替换这一行", history_id: null,
};
const originalFetch = globalThis.fetch;
let root: ReturnType<typeof createRoot>;
let mutations: Array<{ path: string; body: Record<string, unknown> }>;
let handle: (url: URL, body?: Record<string, unknown>) => Response | Promise<Response> | undefined;
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
async function mount() {
  mutations = [];
  globalThis.fetch = async (input, options) => {
    const url = new URL(String(input), "http://localhost");
    const body = options?.body ? JSON.parse(String(options.body)) : undefined;
    if (body) mutations.push({ path: url.pathname, body });
    return await handle(url, body) ?? (
      url.pathname.endsWith("/characters")
        ? json({ ...profile, chapter: url.searchParams.get("chapter") || "0001" })
        : url.pathname.endsWith("/character-history") ? json({ entries: [] }) : json({ detail: "unexpected request" }, 404));
  };
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(createElement(CharacterCenterPanel, { workspace, workflowId: "character" })));
}
const text = () => document.body.textContent || "";
function button(label: string) {
  return [...document.querySelectorAll("button")].find(item => item.textContent?.trim() === label);
}
async function click(label: string) {
  const found = button(label);
  assert.ok(found, "missing button " + label);
  await act(async () => found.click());
}
async function fill(label: string, value: string) {
  const target = document.querySelector<HTMLInputElement | HTMLTextAreaElement>('[aria-label="' + label + '"]');
  assert.ok(target, "missing input " + label);
  const proto = target.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(target, value);
    target.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
afterEach(async () => {
  if (root) await act(async () => root.unmount());
  document.body.replaceChildren();
  globalThis.fetch = originalFetch;
  handle = () => undefined;
});
after(async () => dom.happyDOM.abort());

test("comparison binds the original receipt and a 409 keeps the edit but blocks the receipt", async () => {
  handle = url => url.pathname.endsWith("/character-preview") ? json(receipt)
    : url.pathname.endsWith("/character-apply") ? json({ detail: "原件已更新" }, 409) : undefined;
  await mount();
  await click("声线");
  await click("编辑表达倾向");
  await fill("替换内容", "新的说法");
  assert.equal(mutations.length, 0);
  await click("预览修改");
  assert.match(text(), /仅替换这一行/);
  await click("确认修改");
  assert.equal(document.querySelector<HTMLTextAreaElement>('[aria-label="替换内容"]')?.value, "新的说法");
  assert.match(text(), /原件已更新/);
  assert.ok(!button("确认修改") || button("确认修改")?.disabled);
  assert.deepEqual(mutations[1].body.preview, receipt);
  assert.equal(mutations[0].body.workspace, workspace);
});

test("planned chapters do not promote past snapshots to the chapter under review", async () => {
  await mount();
  await click("本章状态");
  assert.match(text(), /纸还在桌上/);
  await fill("章节号", "2");
  await click("查看章节");
  await click("本章状态");
  assert.match(text(), /本章没有已确认/);
  assert.doesNotMatch(document.querySelector('[aria-label="本章状态"]')?.textContent || "", /纸还在桌上/);
  await click("成长与计划");
  assert.match(text(), /纸还在桌上/);
});

test("a switched character cannot receive a late preview for the old character", async () => {
  let resolve!: (response: Response) => void;
  handle = url => url.pathname.endsWith("/character-preview")
    ? new Promise<Response>(done => { resolve = done; }) : undefined;
  await mount();
  await click("声线");
  await click("编辑表达倾向");
  await fill("替换内容", "新的说法");
  await click("预览修改");
  await click("许宁");
  await act(async () => resolve(json(receipt)));
  assert.doesNotMatch(text(), /仅替换这一行/);
  assert.equal(button("确认修改"), undefined);
  await click("原文");
  assert.match(text(), /旧档案待整理/);
});

test("relationship view shows direction and source and history restore uses a fresh preview", async () => {
  const entry = { id: "history-a", character_id: "a", source_id: section.source_id, section_id: section.id, before: "以前的说法", after: "原先说法", created_at: "2026-11-04T00:00:00Z" };
  handle = url => url.pathname.endsWith("/character-history") ? json({ entries: [entry] })
    : url.pathname.endsWith("/character-preview") ? json({ ...receipt, history_id: entry.id, before: entry.after, after: entry.before }) : undefined;
  await mount();
  await click("关系");
  assert.match(text(), /许青 → 许宁/);
  assert.match(text(), /meta\/character_voice.md/);
  await click("修订记录");
  await click("预览回退");
  assert.equal(mutations.length, 1);
  assert.equal(mutations[0].body.history_id, entry.id);
  assert.match(text(), /以前的说法/);
  assert.ok(button("确认回退"));
});

test("an assistant result with a different request ID cannot be adopted", async () => {
  handle = url => url.pathname.endsWith("/assistant") ? json({ entry: {
    id: "different-job", chapter: "0001", purpose: "character_edit", status: "completed", suggestion: receipt,
  } }) : undefined;
  await mount();
  await click("声线");
  await click("编辑表达倾向");
  await fill("表达建议说明", "让它更自然");
  await click("请求表达建议");
  assert.match(text(), /请求编号不符/);
  assert.equal(button("采用为修改预览"), undefined);
  assert.equal(mutations.length, 1);
});

test("an expression rule is written only after review of the full preview", async () => {
  const rule = { source_id: section.source_id, source_kind: "voice", source_sha256: "a", source_category: "expression_advice", provenance: "unknown",
    review_status: "candidate", quote: "每句对白必须有具体目的", start: 0, end: 13, line: 1, rule: "purpose", reason: "待核对",
    override_eligible: true, suggestion: "根据场景安排对白" };
  const override = { preview_id: "rule-a", revision: "p", source_id: rule.source_id, source_sha256: "a", source_category: rule.source_category,
    quote: rule.quote, replacement: rule.suggestion, start: 0, end: 13, before: rule.quote, after: rule.suggestion };
  const policy = { revision: "p", mode: "inherit", overrides: [], stale_overrides: [] };
  handle = (url, body) => url.pathname.endsWith("/prose-policy") ? json(body ? { ...policy, revision: "p2", mode: "narrative_led", overrides: [override] } : policy)
    : url.pathname.endsWith("/rule-audit") ? json(body ? override : { chapter: "0001", revision: "p", findings: [rule, { ...rule, quote: "身份事实", start: 40, override_eligible: false }], stale_overrides: [], sources: [] }) : undefined;
  await mount();
  await click("叙述偏好与规则体检");
  assert.equal([...document.querySelectorAll("button")].filter(item => item.textContent?.trim() === "选择表达建议").length, 1);
  await click("选择表达建议");
  await click("预览覆盖");
  assert.equal(mutations.length, 1);
  assert.equal(mutations[0].path, "/api/humanware/rule-audit");
  await click("确认覆盖并采用叙述优先");
  assert.deepEqual(mutations[1].body.overrides, [override]);
  assert.equal(mutations[1].body.mode, "narrative_led");
});


test("trial acceptance displays an unmatched production binding and sends author guidance only", async () => {
  handle = (url, body) => {
    if (url.pathname.endsWith("/assistant") && body) return json({ entry: {
      id: body.request_id, chapter: body.chapter, purpose: body.purpose, status: "completed", model: "fixture:model", attempt: 1,
      elapsed_seconds: 2, trial: { chapter: body.chapter, character_ids: body.character_ids, scene: body.scene,
        baseline: body.baseline, candidate: "她摊开纸。", checks: ["保持核对动作"] },
    } });
    if (url.pathname.endsWith("/trial-accept") && body) return json({ preference: {
      ...body, chapter: "0001", scene: "井口", character_ids: ["a"], production_match: false,
    } });
  };
  await mount();
  await click("场景试读");
  await fill("场景", "井口");
  await fill("对照原文", "她把纸摊开。");
  await fill("试读说明", "试试精简");
  await click("请求场景试读");
  assert.match(text(), /fixture:model/);
  assert.match(text(), /保持核对动作/);
  await fill("采用理由", "行动更清楚");
  await fill("保留的表达建议", "先写动作");
  await click("确认并保存表达偏好");
  assert.match(text(), /同场景试读的参考/);
  assert.doesNotMatch(text(), /后续生成可读取/);
  assert.deepEqual(mutations[1].body, { workspace, workflow_id: "character", entry_id: mutations[0].body.request_id,
    preferred: "candidate", reason: "行动更清楚", carry_forward: "先写动作" });
});
