import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { Window } from "happy-dom";

const dom = new Window({ url: "http://localhost/" });
for (const name of ["window", "document", "Node", "Text", "HTMLElement", "HTMLTextAreaElement", "Element", "Event", "MouseEvent", "navigator"]) {
  Object.defineProperty(globalThis, name, { configurable: true, value: name === "window" ? dom : dom[name as keyof Window] });
}
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const React = await import("react");
const { act, createElement } = React;
Object.assign(globalThis, { React });
const { createRoot } = await import("react-dom/client");
const { renderToStaticMarkup } = await import("react-dom/server");
const { default: CharacterVoiceEditor } = await import("./CharacterVoiceEditor");
const { default: HumanwareScoreCard } = await import("./HumanwareScoreCard");
let root: ReturnType<typeof createRoot> | undefined;
const originalFetch = globalThis.fetch;
let posts: Record<string, unknown>[];
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const initial = () => ({ status: "success", revision: "a".repeat(64), content: "# 原始声音文档",
  preamble: "# 角色声音\n\n共同规则。", unsectioned_voice: "", characters: [
    { id: "voice-one", name: "林芷", title: "林芷", voice: "说话克制。", voice_status: "present", profile_status: "matched", profile: "- 性格：执拗但有分寸\n- 当前欲望：保留工具" },
    { id: "voice-two", name: "林启", title: "林启", voice: "先谈具体安排。", voice_status: "present", profile_status: "matched", profile: "- 性格：务实\n- 顾虑：搬运费用" },
  ] });
afterEach(async () => { await act(async () => root?.unmount()); root = undefined; document.body.replaceChildren(); globalThis.fetch = originalFetch; });
after(async () => dom.happyDOM.abort());
function button(label: string) {
  const found = [...document.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent?.trim() === label || item.getAttribute("aria-label") === label);
  assert.ok(found, `Missing button ${label}`); return found;
}
async function click(label: string) { await act(async () => button(label).click()); }
async function edit(value: string) {
  const input = document.querySelector("textarea")!;
  assert.ok(input, "selected character must have its own editor");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function mount(options: { failure?: boolean; legacy?: boolean; missing?: boolean } = {}) {
  posts = [];
  let doc = initial();
  if (options.legacy) doc = { ...doc, characters: [], preamble: "", unsectioned_voice: "旧格式：保留原样。", content: "旧格式：保留原样。" };
  if (options.missing) doc.characters[1] = { ...doc.characters[1], voice: "", voice_status: "missing", profile_status: "ambiguous", profile: "" };
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body)); posts.push(body);
      if (options.failure) return response({ detail: "角色档案已更新，请刷新后重新核对。" }, 409);
      doc = { ...doc, revision: "b".repeat(64), characters: doc.characters.map(item => item.id === body.character_id ? { ...item, voice: body.content } : item) };
      return response({ status: "success", character_id: body.character_id });
    }
    if (url.includes("/status?")) return response({ voice_file_exists: true, profiles_file_exists: true, character_count: 2 });
    if (url.includes("/voice-file?")) return response(doc);
    throw new Error(`Unexpected request ${url}`);
  };
  const host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root?.render(createElement(CharacterVoiceEditor, { workspaceId: "books/分角色", workflowId: "character" })));
}

test("voices open as readable individual characters with the matching personality reference", async () => {
  await mount();
  assert.ok(document.querySelector('nav[aria-label="人物列表"]'));
  assert.equal(document.querySelectorAll("textarea").length, 0, "reading should not start in a combined editor");
  const detail = document.querySelector('[aria-label="当前人物声音"]')!;
  assert.match(detail.textContent || "", /说话克制/);
  assert.match(document.querySelector('[aria-label="人物档案参考"]')?.textContent || "", /执拗但有分寸/);
  assert.doesNotMatch(detail.textContent || "", /先谈具体安排/);
  await click("查看林启的声音");
  assert.match(document.querySelector('[aria-label="当前人物声音"]')?.textContent || "", /先谈具体安排/);
  assert.match(document.querySelector('[aria-label="人物档案参考"]')?.textContent || "", /搬运费用/);
});

test("switching characters retains drafts and saving sends only the selected section with its revision", async () => {
  await mount(); await click("编辑声音"); await edit("先说自己的具体请求。");
  await click("查看林启的声音"); await click("查看林芷的声音");
  assert.equal(document.querySelector("textarea")?.value, "先说自己的具体请求。");
  await click("保存当前人物");
  assert.deepEqual(posts, [{ workflow_id: "character", workspace: "books/分角色", character_id: "voice-one", expected_revision: "a".repeat(64), content: "先说自己的具体请求。" }]);
  await click("查看林启的声音");
  assert.match(document.querySelector('[aria-label="当前人物声音"]')?.textContent || "", /先谈具体安排/);
});

test("a stale save preserves the user's draft and exposes the server reason", async () => {
  await mount({ failure: true }); await click("编辑声音"); await edit("待核对的新声音。"); await click("保存当前人物");
  assert.equal(document.querySelector("textarea")?.value, "待核对的新声音。");
  assert.match(document.querySelector('[role="alert"]')?.textContent || "", /角色档案已更新/);
});

test("missing or uncertain character references are explicit rather than invented", async () => {
  await mount({ missing: true }); await click("查看林启的声音");
  assert.match(document.querySelector('[aria-label="人物档案参考"]')?.textContent || "", /无法唯一对应/);
  assert.match(document.querySelector('[aria-label="当前人物声音"]')?.textContent || "", /尚未填写/);
  assert.ok(button("填写声音"));
});

test("unstructured legacy content remains readable and editable without pretending it was split", async () => {
  await mount({ legacy: true });
  assert.match(document.body.textContent || "", /旧格式：保留原样/);
  assert.match(document.body.textContent || "", /未按人物分段/);
  assert.ok(button("编辑原文"));
});

test("voice editor encodes full Windows workspace and preserves drafts when busy saving is rejected", async () => {
  const calls: Array<{ url: string; body?: Record<string, string> }> = [];
  globalThis.fetch = async (input, options) => {
    calls.push({ url: String(input), body: options?.body ? JSON.parse(String(options.body)) : undefined });
    if (String(input).includes('/status')) return response({ voice_file_exists: true, profiles_file_exists: true, character_count: 1 });
    if (options?.method === 'POST') return response({ detail: '本书正在处理，请稍后保存' }, 409);
    return response({ status: 'success', content: 'existing voice' });
  };
  const host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  const workspace = 'C:\\Library\\有 空格\\books\\example';
  await act(async () => root?.render(createElement(CharacterVoiceEditor, { workspaceId: workspace, workflowId: 'custom-character' })));
  const read = calls.find(call => call.url.includes('/voice-file'))!;
  const query = new URL(read.url, 'http://localhost');
  assert.equal(query.pathname, '/api/humanware/voice-file');
  assert.equal(query.searchParams.get('workspace'), workspace);
  assert.equal(query.searchParams.get('workflow_id'), 'custom-character');
  assert.equal(button('创建待填写模板').disabled, true, 'existing voice cannot be regenerated');
  await click('编辑原文'); await edit('existing voice updated'); await click('保存原文');
  const mutation = calls.find(call => call.body)!;
  assert.equal(mutation.url, '/api/humanware/voice-file');
  assert.deepEqual(mutation.body, { workflow_id: 'custom-character', workspace, content: 'existing voice updated' });
  assert.match(document.querySelector('[role="alert"]')?.textContent || '', /本书正在处理/);
  assert.equal(document.querySelector('textarea')?.value, 'existing voice updated');
});

test("unsupported humanware capability renders no invented score", () => {
  const html = renderToStaticMarkup(createElement(HumanwareScoreCard, {
    score: { supported: false, message: '请使用模拟读者报告' },
  } as never));
  assert.ok(html.includes('请使用模拟读者报告'));
  assert.ok(!html.includes('/ 100'));
});
