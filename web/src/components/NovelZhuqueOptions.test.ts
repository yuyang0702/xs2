import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { Window } from "happy-dom";

const dom = new Window({ url: "http://localhost/" });
for (const name of ["window", "document", "Node", "Text", "HTMLElement", "HTMLInputElement", "HTMLTextAreaElement", "Element", "Event", "navigator"]) {
  Object.defineProperty(globalThis, name, { configurable: true, value: name === "window" ? dom : dom[name as keyof Window] });
}
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const React = await import("react");
Object.assign(globalThis, { React });
const { act, createElement } = React;
const { createRoot } = await import("react-dom/client");
const { default: NovelZhuqueOptions } = await import("./NovelZhuqueOptions");
const originalFetch = globalThis.fetch;
let root: ReturnType<typeof createRoot> | undefined;
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  document.body.replaceChildren();
  globalThis.fetch = originalFetch;
});
after(async () => dom.happyDOM.abort());

test("opening a book reads settings; switching the checkbox persists only to that book", async () => {
  const saved = new Map([["book-a", { enabled: true, reference_text: "钥匙响了两声。" }]]);
  const writes: string[] = [];
  globalThis.fetch = async (url, init) => {
    assert.match(String(url), /\/novel-console\/zhuque-options/);
    if (init?.method === "PATCH") {
      const { workspace, workflow_id, ...changes } = JSON.parse(String(init.body));
      assert.equal(workflow_id, "build");
      writes.push(workspace);
      saved.set(workspace, { enabled: false, reference_text: "", ...saved.get(workspace), ...changes });
      return Response.json(saved.get(workspace));
    }
    const book = new URL(String(url), "http://localhost").searchParams.get("workspace")!;
    return Response.json(saved.get(book) || { enabled: false, reference_text: "" });
  };
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const open = (workspace: string) => act(async () => root!.render(createElement(NovelZhuqueOptions,
    { key: workspace, workflowId: "build", workspace, disabled: false, onPendingChange: () => {} })));
  await open("book-a");
  assert.equal(host.querySelector("input")!.checked, true);
  assert.equal(host.querySelector("textarea")!.value, "钥匙响了两声。");
  await open("book-b");
  assert.equal(host.querySelector("input")!.checked, false);
  assert.deepEqual(writes, []);
  await act(async () => host.querySelector("input")!.click());
  assert.deepEqual(writes, ["book-b"]);
  assert.deepEqual(saved.get("book-b"), { enabled: true, reference_text: "" });
  assert.equal(host.querySelector("textarea")!.value, "");
  const area = host.querySelector("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(area, "天还没亮。");
    area.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const save = [...host.querySelectorAll("button")].find(button => button.textContent === "保存参考稿");
  assert.ok(save);
  await act(async () => save.click());
  await act(async () => host.querySelector("input")!.click());
  assert.deepEqual(saved.get("book-b"), { enabled: false, reference_text: "天还没亮。" });
  assert.equal(saved.get("book-a")?.reference_text, "钥匙响了两声。");
});
