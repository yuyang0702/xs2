import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { Window } from "happy-dom";

const dom = new Window({ url: "http://localhost/" });
for (const name of ["window", "document", "Node", "Text", "HTMLElement", "HTMLSelectElement", "Element", "Event", "navigator"]) {
  Object.defineProperty(globalThis, name, { configurable: true, value: name === "window" ? dom : dom[name as keyof Window] });
}
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const React = await import("react");
const { act, createElement, useState } = React;
Object.assign(globalThis, { React });
const { createRoot } = await import("react-dom/client");
const { default: NovelBookModels } = await import("./NovelBookModels");
const originalFetch = globalThis.fetch;
let root: ReturnType<typeof createRoot> | undefined;
const initial = { analysisModel: "", writerModel: "old:writer", polishModel: "" };
let saved = initial;
async function mount(fail = false) {
  globalThis.fetch = async () => new Response(JSON.stringify(fail ? { detail: "暂不可用" } : {
    models: [{ value: "system:default", label: "系统默认模型" }, { value: "volcano:writer", label: "火山写手" },
      { value: "flare:polish", label: "ModelFlare 润色" }],
  }), { status: fail ? 503 : 200 });
  function Host() {
    const [value, setValue] = useState(initial);
    return createElement(NovelBookModels, { value, onChange: next => { saved = next; setValue(next); } });
  }
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root!.render(createElement(Host)));
}
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  root = undefined;
  document.body.replaceChildren();
  globalThis.fetch = originalFetch;
  saved = initial;
});
after(async () => dom.happyDOM.abort());

test("book model choices preserve the other roles and a saved unavailable model", async () => {
  await mount();
  const fields = document.querySelectorAll("select");
  assert.equal(fields.length, 3);
  assert.equal(fields[1].value, "old:writer");
  await act(async () => {
    fields[2].value = "flare:polish";
    fields[2].dispatchEvent(new Event("change", { bubbles: true }));
  });
  assert.deepEqual(saved, { ...initial, polishModel: "flare:polish" });
  await act(async () => {
    fields[0].value = "system:default";
    fields[0].dispatchEvent(new Event("change", { bubbles: true }));
  });
  assert.deepEqual(saved, { ...initial, polishModel: "flare:polish", analysisModel: "system:default" });
});

test("a catalogue error preserves the book's saved choice", async () => {
  await mount(true);
  assert.match(document.body.textContent || "", /503/);
  assert.equal(document.querySelectorAll("select")[1].value, "old:writer");
  assert.equal(saved, initial);
});
