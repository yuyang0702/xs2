import assert from "node:assert/strict";
import { after, test } from "node:test";
import { Window } from "happy-dom";
import type { ProviderSchema } from "../types";

const dom = new Window({ url: "http://localhost/" });
for (const name of ["window", "document", "Node", "Text", "HTMLElement", "Element", "Event", "MouseEvent", "navigator"]) {
  Object.defineProperty(globalThis, name, { configurable: true, value: name === "window" ? dom : dom[name as keyof Window] });
}
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const React = await import("react");
const { act, createElement } = React;
Object.assign(globalThis, { React });
const { createRoot } = await import("react-dom/client");
const { default: AddModelProviderDialog } = await import("./AddModelProviderDialog");
after(async () => dom.happyDOM.abort());

test("selecting Ark submits its preset model without fetching models or replacing existing providers", async () => {
  const common: ProviderSchema = { provider_type: "openai_compatible", display_name: "兼容接口",
    default_base_url: "", api_format: "openai", reasoning_efforts: [], model_params: {}, hyperparams: {} };
  const ark = { ...common, provider_type: "volcengine", display_name: "火山方舟",
    default_base_url: "https://ark.cn-beijing.volces.com/api/v3",
    default_models: ["doubao-seed-character-260628"] };
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  let submitted: unknown;
  try {
    await act(async () => root.render(createElement(AddModelProviderDialog, {
      open: true, schemas: { openai_compatible: common, volcengine: ark },
      existingProviderIds: ["existing", "volcengine"], onClose: () => {},
      onAdd: async input => { submitted = input; },
      onDiscoverModels: async () => { throw new Error("Preset must not require discovery"); },
    })));
    const select = document.querySelector("select")!;
    await act(async () => {
      select.value = "volcengine";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const add = [...document.querySelectorAll("button")].find(button => button.textContent?.trim() === "添加供应商")!;
    assert.equal(add.disabled, false, "a preset model must enable saving without network discovery");
    await act(async () => add.click());
    assert.deepEqual(submitted, { provider_id: "volcengine-2", provider_type: "volcengine",
      name: "火山方舟", base_url: "https://ark.cn-beijing.volces.com/api/v3", api_key: "",
      models: ["doubao-seed-character-260628"] });
    await act(async () => {
      select.value = "openai_compatible";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    assert.equal(add.disabled, true, "another provider must not inherit Ark's model");
  } finally {
    await act(async () => root.unmount()); host.remove();
  }
});
