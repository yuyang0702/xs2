import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { Window } from "happy-dom";
import { initialNovelWorkbenchView } from "../lib/novel-flow-entry";
import type { NovelProgress } from "../lib/novel-progress-types";

const dom = new Window({ url: "http://localhost/" });
for (const name of ["window", "document", "Node", "Text", "HTMLElement", "Element", "Event", "navigator"]) {
  Object.defineProperty(globalThis, name, { configurable: true, value: name === "window" ? dom : dom[name as keyof Window] });
}
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const { act, createElement, useLayoutEffect } = await import("react");
const { createRoot } = await import("react-dom/client");
const { useNovelWorkspaceProgress } = await import("./useNovelWorkspaceProgress");
const originalFetch = globalThis.fetch;
let root: ReturnType<typeof createRoot> | undefined;
let timer: (() => void) | undefined;
let reads: { workspace: string; resolve: (response: Response) => void }[];
let renders: string[];

function Preview({ workspace }: { workspace: string }) {
  const { progress, progressError } = useNovelWorkspaceProgress("novel-build", workspace);
  const view = workspace + ":" + (progress?.label || progressError || "loading");
  useLayoutEffect(() => { renders.push(view); }, [view]);
  return createElement("p", {}, view);
}
function progress(label: string): NovelProgress {
  return { label, percent: 0, completed_count: 0, total_count: 9, chapter_count: 0, can_download: false,
    export_current: false, reader_verdict: "" };
}
async function deliver(index: number, label: string) {
  await act(async () => reads[index].resolve(new Response(JSON.stringify(progress(label)))));
}
async function render(workspace: string) {
  await act(async () => root!.render(createElement(Preview, { workspace })));
}
function start() {
  reads = [];
  renders = [];
  timer = undefined;
  globalThis.fetch = input => new Promise<Response>(resolve => reads.push({
    workspace: new URL(String(input), "http://localhost").searchParams.get("workspace")!, resolve,
  }));
  Object.defineProperty(window, "setInterval", { configurable: true, value: (callback: () => void) => { timer = callback; return 1; } });
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
}
afterEach(async () => {
  if (root) await act(async () => root?.unmount());
  root = undefined;
  document.body.replaceChildren();
  globalThis.fetch = originalFetch;
});
after(async () => dom.happyDOM.abort());

test("direct character-center link preserves flow and default workbench entry", () => {
  assert.equal(initialNovelWorkbenchView("?tab=novel-workbench&view=humanware"), "humanware");
  assert.equal(initialNovelWorkbenchView("?tab=novel-workbench&view=flow"), "flow");
  assert.equal(initialNovelWorkbenchView("?tab=novel-workbench"), "home");
  assert.equal(initialNovelWorkbenchView("?tab=novel-workbench&view=unknown"), "home");
});

test("switching books never paints old progress before passive effects or after a late reply", async () => {
  start();
  await render("book-a");
  await deliver(0, "book-a progress");
  await act(async () => timer!());
  await render("book-b");
  assert.deepEqual(reads.map(read => read.workspace), ["book-a", "book-a", "book-b"]);
  await deliver(1, "late book-a progress");
  await deliver(2, "book-b progress");
  assert.deepEqual(renders, ["book-a:loading", "book-a:book-a progress", "book-b:loading", "book-b:book-b progress"]);
});

test("a slow poll cannot overwrite a newer recorded observation", async () => {
  start();
  await render("book-a");
  await act(async () => timer!());
  await deliver(1, "newer progress");
  await deliver(0, "older progress");
  assert.equal(document.body.textContent, "book-a:newer progress");
  assert.ok(!renders.some(value => value.includes("older progress")));
});
