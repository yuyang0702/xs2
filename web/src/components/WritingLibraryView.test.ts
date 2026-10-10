import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { Window } from "happy-dom";
import type { GlobalDialog } from "./ui/use-dialog";
import type { WritingLibraryDeleteResult } from "../lib/api";

const dom = new Window({ url: "http://localhost/" });
for (const name of ["window", "document", "Node", "Text", "HTMLElement", "Element", "Event", "MouseEvent", "navigator", "sessionStorage"]) {
  Object.defineProperty(globalThis, name, { configurable: true, value: name === "window" ? dom : dom[name as keyof Window] });
}
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const React = await import("react");
const { act, createElement } = React;
Object.assign(globalThis, { React });
const { createRoot } = await import("react-dom/client");
const { DialogContext } = await import("./ui/use-dialog");
const { default: WritingLibraryView } = await import("./WritingLibraryView");
let root: ReturnType<typeof createRoot> | undefined;
const originalFetch = globalThis.fetch;
let confirmResult: ((value: boolean | null) => void) | undefined;
let confirmation: { title: string; description?: string } | undefined;
let deleteCalls: string[][] = [];
let deleteResult: (ids: string[]) => Promise<Response>;
const exampleItems = ["first", "second"].map((id, index) => ({
  id, name: index ? "人物写法" : "悬疑写法", genres: [], pov: [], tone: [],
  language: "中文", candidate_count: 2, created_at: "", version: 1,
}));
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });

afterEach(async () => {
  confirmResult?.(null);
  await act(async () => root?.unmount());
  root = undefined; document.body.replaceChildren(); sessionStorage.clear();
  globalThis.fetch = originalFetch; confirmation = undefined; confirmResult = undefined;
});
after(async () => dom.happyDOM.abort());

function button(label: string) {
  const target = [...document.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent?.includes(label));
  assert.ok(target, `Missing button: ${label}`);
  return target;
}

async function click(target: HTMLElement) { await act(async () => target.click()); }
async function confirm(value: boolean) { await act(async () => confirmResult?.(value)); }

async function mount(items = exampleItems) {
  deleteCalls = [];
  deleteResult = async ids => response({ success: true, deleted_ids: ids, missing_ids: [], failed: [] });
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    if (url.includes("/library-usage")) return response({ items: { first: { status: "adopted", selected_count: 1 } } });
    if (url.endsWith("/library/delete")) {
      const ids = JSON.parse(String(init?.body)).library_ids as string[];
      deleteCalls.push(ids);
      return deleteResult(ids);
    }
    if (url.endsWith("/library")) return response({ items });
    throw new Error(`Unexpected request: ${url}`);
  };
  const dialog: GlobalDialog = {
    open: options => {
      confirmation = options;
      return new Promise(resolve => { confirmResult = resolve as (value: boolean | null) => void; });
    },
    confirm: async () => false,
    cancelMatching: () => confirmResult?.(null),
  };
  const host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root?.render(createElement(DialogContext.Provider, { value: dialog },
    createElement(WritingLibraryView, {
      workflowId: "test", workspace: "book", project: { values: { genre: "", narrative_pov: "third_person" } },
      onAttach: async () => {}, onBack: () => {}, onConfirm: () => {},
    }))));
}

test("select all and batch deletion require confirmation and update the list", async () => {
  await mount();
  assert.equal(button("批量删除").disabled, true);
  await click(document.querySelector<HTMLInputElement>('[aria-label="全选写法"]')!);
  assert.match(document.body.textContent || "", /已选 2 份/);
  await click(button("批量删除"));
  assert.match(confirmation!.title, /2 份/);
  assert.match(confirmation!.description!, /永久删除.*实际文件/);
  assert.match(confirmation!.description!, /已经复制到小说/);
  assert.deepEqual(deleteCalls, []);
  await confirm(true);
  assert.deepEqual(deleteCalls, [["first", "second"]]);
  assert.match(document.body.textContent || "", /已删除 2 份写法/);
  assert.match(document.body.textContent || "", /还没有共享写法/);
  assert.equal(document.querySelectorAll('article').length, 0);
});

test("single-item cancellation never sends a delete request", async () => {
  await mount();
  await click(document.querySelector<HTMLButtonElement>('[aria-label="删除写法：悬疑写法"]')!);
  assert.equal(confirmation!.title, "删除这份写法？");
  await confirm(false);
  assert.deepEqual(deleteCalls, []);
  assert.equal(document.querySelectorAll("article").length, 2);
});

test("a partially failed batch keeps failed items selected and permits retry", async () => {
  await mount();
  deleteResult = async () => response({
    success: false, deleted_ids: ["first"], missing_ids: [], failed: [{ id: "second", message: "文件正在使用" }],
  } satisfies WritingLibraryDeleteResult);
  await click(document.querySelector<HTMLInputElement>('[aria-label="全选写法"]')!);
  await click(button("批量删除")); await confirm(true);
  assert.equal(document.querySelectorAll("article").length, 1);
  assert.equal(document.querySelector<HTMLInputElement>('[aria-label="选择写法：人物写法"]')!.checked, true);
  assert.match(document.querySelector('[role="alert"]')!.textContent || "", /人物写法.*文件正在使用/);
  deleteResult = async ids => response({ success: true, deleted_ids: ids, missing_ids: [], failed: [] });
  await click(button("批量删除")); await confirm(true);
  assert.deepEqual(deleteCalls, [["first", "second"], ["second"]]);
  assert.equal(document.querySelectorAll("article").length, 0);
});

test("deletion remains visibly busy and double clicks cannot send another request", async () => {
  await mount();
  let finish: ((value: Response) => void) | undefined;
  deleteResult = () => new Promise(resolve => { finish = resolve; });
  await click(document.querySelector<HTMLInputElement>('[aria-label="全选写法"]')!);
  await click(button("批量删除")); await confirm(true);
  assert.equal(button("正在删除").disabled, true);
  assert.match(document.querySelector('[role="status"]')!.textContent || "", /正在删除 2 份/);
  await click(button("正在删除"));
  assert.equal(deleteCalls.length, 1);
  await act(async () => finish!(response({ success: true, deleted_ids: ["first", "second"], missing_ids: [], failed: [] })));
  assert.match(document.body.textContent || "", /已删除 2 份写法/);
});

test("an HTTP failure shows an error and preserves selection", async () => {
  await mount();
  deleteResult = async () => response({ detail: "磁盘异常" }, 500);
  await click(document.querySelector<HTMLInputElement>('[aria-label="全选写法"]')!);
  await click(button("批量删除")); await confirm(true);
  assert.match(document.querySelector('[role="alert"]')!.textContent || "", /删除未完成.*磁盘异常/);
  assert.equal(button("批量删除").disabled, false);
  assert.match(document.body.textContent || "", /已选 2 份/);
  assert.equal(document.querySelectorAll("article").length, 2);
});

test("large selections show prior successes when a later request fails", async () => {
  await mount(Array.from({ length: 201 }, (_, index) => ({ ...exampleItems[0], id: `item-${index}`, name: `写法 ${index}` })));
  deleteResult = async ids => deleteCalls.length === 1
    ? response({ success: true, deleted_ids: ids, missing_ids: [], failed: [] })
    : response({ detail: "连接中断" }, 503);
  await click(document.querySelector<HTMLInputElement>('[aria-label="全选写法"]')!);
  await click(button("批量删除")); await confirm(true);
  assert.equal(deleteCalls[0].length, 200);
  assert.deepEqual(deleteCalls[1], ["item-200"]);
  assert.equal(document.querySelectorAll("article").length, 1);
  assert.equal(document.querySelector<HTMLInputElement>('[aria-label="选择写法：写法 200"]')!.checked, true);
  assert.match(document.body.textContent || "", /已删除 200 份/);
  assert.match(document.querySelector('[role="alert"]')!.textContent || "", /连接中断/);
});
