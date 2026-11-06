import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { Window } from "happy-dom";

const dom = new Window({ url: "http://localhost/" });
for (const name of ["window", "document", "Node", "Text", "HTMLElement", "HTMLInputElement", "Element", "Event", "MouseEvent", "navigator", "localStorage"]) {
  Object.defineProperty(globalThis, name, { configurable: true, value: name === "window" ? dom : dom[name as keyof Window] });
}
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const React = await import("react");
const { act, createElement } = React;
Object.assign(globalThis, { React });
const { createRoot } = await import("react-dom/client");
const { default: NovelMarketPage } = await import("./NovelMarketPage");
const originalFetch = globalThis.fetch;
let root: ReturnType<typeof createRoot> | undefined;
const deletedBook = "data/workspaces/books/deleted-book";
const resources = Object.fromEntries(["reference-distillation", "novel-advisor", "style-compatibility-advisor",
  "adopt-reference", "build", "character", "story-plan", "outline", "mvp", "polish", "reader-sim", "post-hoc",
  "export", "market-ranking"].map(stage => [stage, "novel-" + stage]));
const snapshot = {
  source_name: "榜单样本", captured_at: "2026-11-06T12:00:00Z", boundary: "公开样本",
  work_count: 1, rankings: ["推荐"], works: [{ ranking_name: "推荐", rank: 1,
    platform_work_id: "one", title: "仍然可读的榜单", category: "古风" }],
};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
async function mount(handle: (url: URL, options?: RequestInit) => Response | Promise<Response> | undefined) {
  localStorage.setItem("xs2-novel-workspace", deletedBook);
  globalThis.fetch = async (input, options) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname === "/api/novel-console/resources") return json({ workflows: resources });
    return await handle(url, options) ?? json({ tasks: [], total: 0, page: 1, page_size: 20 });
  };
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root!.render(createElement(NovelMarketPage)));
}
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  root = undefined;
  document.body.replaceChildren();
  localStorage.clear();
  globalThis.fetch = originalFetch;
});
after(async () => dom.happyDOM.abort());

test("market collection uses an independent workspace and leaves the selected novel intact", async () => {
  let created: Record<string, unknown> | undefined;
  await mount((url, options) => {
    if (url.pathname.endsWith("/tasks") && options?.method === "POST") {
      created = JSON.parse(String(options.body));
      return json({ task_id: "new", workflow_id: "novel-market-ranking" });
    }
    if (url.pathname.endsWith("/run")) return json({ detail: "测试抓取失败" }, 500);
  });
  assert.equal(document.querySelector("input")?.value, "data/workspaces/market");
  const refresh = [...document.querySelectorAll("button")].find(button => button.textContent === "更新当前平台")!;
  await act(async () => refresh.click());
  assert.equal(created?.workspace_override, "data/workspaces/market");
  assert.equal(localStorage.getItem("xs2-novel-workspace"), deletedBook);
  assert.equal(localStorage.getItem("xs2-market-workspace"), "data/workspaces/market");
});

test("deleted snapshot directories are skipped across history pages", async () => {
  const pages: string[] = [];
  await mount(url => {
    if (url.pathname.endsWith("/tasks")) {
      const page = url.searchParams.get("page") || "1";
      pages.push(page);
      return json({ tasks: page === "1" ? Array.from({ length: 20 }, (_, i) => ({ task_id: "missing-" + i }))
        : [{ task_id: "available" }], total: 21, page: Number(page), page_size: 20 });
    }
    if (url.pathname.includes("/missing-")) return json({ detail: "工作区文件不存在" }, 404);
    if (url.pathname.includes("/available/")) return json({ content: JSON.stringify(snapshot) });
  });
  assert.match(document.body.textContent || "", /仍然可读的榜单/);
  assert.doesNotMatch(document.body.textContent || "", /API Error/);
  assert.deepEqual(pages, ["1", "2"]);
});

test("missing historical files leave a usable empty page while service errors remain visible", async () => {
  await mount(url => url.pathname.endsWith("/tasks") ? json({ tasks: [{ task_id: "missing" }], total: 1, page: 1, page_size: 20 })
    : json({ detail: "工作区文件不存在" }, 404));
  assert.match(document.body.textContent || "", /还没有榜单快照/);
  assert.doesNotMatch(document.body.textContent || "", /API Error 404/);
  assert.ok(document.querySelector("button:not([disabled])"));
});

test("a server failure is surfaced instead of being treated as a deleted snapshot", async () => {
  await mount(url => url.pathname.endsWith("/tasks") ? json({ tasks: [{ task_id: "available" }], total: 1, page: 1, page_size: 20 })
    : json({ detail: "服务暂不可用" }, 503));
  assert.match(document.body.textContent || "", /503/);
});
