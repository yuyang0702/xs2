import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { Window } from "happy-dom";
import type { GlobalDialog } from "./ui/use-dialog";
import type { CrossChapterAnalysis, WritingLibraryDeleteResult, WritingLibraryItem } from "../lib/api";
import { localCorpusPath, prepareReferenceCorpus, urlCorpusPath } from "../lib/reference-source";

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
const { default: NovelReferenceUrlImport } = await import("./NovelReferenceUrlImport");
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

async function mount(items: WritingLibraryItem[] = exampleItems, projectPov = "third_person", analysis?: CrossChapterAnalysis) {
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
    if (url.includes("/source-excerpt?start=20&end=23")) return response({source_sha256: "sha", start: 20, end: 23, before: "前文。", excerpt: "旧钥匙", after: "开了锁。"});
    if (url.includes("/library/")) return response({ manifest: items.find(item => url.endsWith("/" + item.id)), profile: {cross_chapter_analysis: analysis}, candidates: { candidates: [] } });
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
      workflowId: "test", workspace: "book", project: { values: { genre: "", narrative_pov: projectPov } },
      onAttach: async () => {}, onBack: () => {}, onConfirm: () => {},
    }))));
}

test("library type filter shows legacy unknowns and selects only matching items", async () => {
  await mount(["short_full", "serial_chapters", "serial_full", undefined].map((mode, i) => ({
    ...exampleItems[0], id: String(i), name: "资料" + i, source_mode: mode,
    source_coverage: mode === "serial_full" ? {chapter_count: 8, analyzed_chapter_count: 6, missing_chapter_count: 2, complete: false} : undefined,
  })));
  assert.match(document.body.textContent!, /已分析 6\/8 章 · 2 章待补/);
  const select = document.querySelector<HTMLSelectElement>('[aria-label="筛选来源类型"]')!;
  assert.deepEqual([...select.options].map(option => option.textContent), ["全部类型", "短篇全文", "长篇章节样本", "长篇全文", "类型待判断"]);
  await act(async () => { select.value = "serial_full"; select.dispatchEvent(new Event("change", {bubbles: true})); });
  await click(document.querySelector<HTMLInputElement>('[aria-label="全选写法"]')!);
  assert.equal(document.querySelectorAll("article").length, 1);
  assert.match(document.querySelector("article")!.textContent!, /资料2/);
  await act(async () => { select.value = "unknown"; select.dispatchEvent(new Event("change", {bubbles: true})); });
  assert.equal(button("批量删除").disabled, true);
  assert.match(document.querySelector("article")!.textContent!, /资料3.*类型待判断.*章节覆盖未记录/);
});

test("reader exposes the last chapter, uncertain findings and verified source context", async () => {
  const chapters = Array.from({length: 21}, (_, i) => ({id: String(i + 1), title: `目录章 ${i + 1}`, start: i * 20, end: i * 20 + 20}));
  await mount([{...exampleItems[0], source_mode: "serial_full", source_sha256: "sha", source_coverage: {
    chapters, analyzed_chapters: chapters.slice(0, -1).map(chapter => chapter.id), missing_chapters: ["21"], complete: false,
  }}], "", {chapter_observations: [], findings: [{id: "f1", dimension: "foreshadowing", status: "possible", statement: "钥匙可能指向旧案", reason: "", limits: "尚无直接回收", evidence: [
    {role: "after", chapter_id: "2", source_start: 20, source_end: 23, excerpt: "旧钥匙"},
  ]}], limitations: [], phase_pacing: []});
  await click(button("查看具体写法"));
  assert.match(document.body.textContent!, /伏笔与回收 · 待核实.*钥匙可能指向旧案/s);
  assert.match(document.body.textContent!, /后文 · 目录章 2.*\[20, 23\)/);
  await click(button("查看原文上下文"));
  assert.equal(document.querySelector("mark")!.textContent, "旧钥匙");
  assert.match(document.body.textContent!, /前文。旧钥匙开了锁/);
  await click(button("下一页"));
  assert.match(document.body.textContent!, /目录章 21.*待补分析/);
});

test("whole URL mode requires an inspected directory and submits every chapter across pages", async () => {
  const chapters = Array.from({length: 205}, (_, i) => ({index: i + 1, url: `https://fanqienovel.com/reader/${i}`, title: `章节 ${i + 1}`, selected: i < 3}));
  let submitted: {source_mode: string; chapters: typeof chapters} | undefined;
  let savedMode = "";
  globalThis.fetch = async (input, init) => {
    if (String(input).endsWith("/inspect")) return response({chapters, catalog_complete: true, work_finished: null});
    submitted = JSON.parse(String(init?.body));
    return response({path: "references/url-imported-corpus.txt", chapter_count: 205, source_mode: "serial_full"});
  };
  const host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => root?.render(createElement(NovelReferenceUrlImport, {workflowId: "test", workspace: "book", mode: "serial_full", busy: false, disabled: false, setBusy: () => {}, onImport: (_path, mode) => { savedMode = mode; }})));
  const url = document.querySelector<HTMLInputElement>('[aria-label="番茄小说作品网址"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(dom.HTMLInputElement.prototype, "value")!.set!.call(url, "https://fanqienovel.com/page/123");
    url.dispatchEvent(new Event("input", {bubbles: true}));
  });
  assert.equal(button("导入整本目录").disabled, true);
  await click(button("识别章节"));
  assert.equal(button("导入整本目录").disabled, false);
  assert.equal(document.querySelectorAll('input[type="checkbox"]').length, 20);
  await click(button("导入整本目录"));
  assert.equal(submitted?.chapters.length, 205);
  assert.equal(submitted?.source_mode, "serial_full");
  assert.equal(savedMode, "serial_full");
});

test("new local files supersede old URL samples and preserve each file in input order", async () => {
  await assert.rejects(prepareReferenceCorpus([], urlCorpusPath, "serial_full", "serial_chapters"), /导入完整目录/);
  await assert.rejects(prepareReferenceCorpus([], urlCorpusPath, "serial_full"), /没有完整目录记录/);
  assert.deepEqual(await prepareReferenceCorpus([], urlCorpusPath, "auto", "serial_chapters"), {path: urlCorpusPath, mode: "serial_chapters"});
  const files = [{name: "上.txt", text: async () => "第一章"}, {name: "下.md", text: async () => "第二章"}];
  assert.deepEqual(await prepareReferenceCorpus(files, urlCorpusPath, "serial_full", "serial_chapters"), {
    path: localCorpusPath, mode: "serial_full", content: "===== SOURCE FILE: 上.txt =====\n\n第一章\n\n===== SOURCE FILE: 下.md =====\n\n第二章",
  });
  await assert.rejects(prepareReferenceCorpus([{name: "空.txt", text: async () => ""}], urlCorpusPath, "serial_full"), /非空/);
});

test("library cards and reader distinguish source narration from supported target views", async () => {
  await mount([{ ...exampleItems[0], pov: ["third_person"], pov_metadata: {
    source_pov: ["first_person"], source_status: "known", source_basis: "candidates",
    target_pov: ["first_person", "third_person"], target_status: "known",
  } }], "first_person");
  const source = document.querySelector('[aria-label="原作叙事视角"]');
  assert.ok(source, "Source narration must be displayed separately from applicability");
  assert.match(source.textContent || "", /第一人称/);
  assert.doesNotMatch(source.textContent || "", /第三人称/);
  assert.match(document.querySelector('[aria-label="写法适用视角"]')?.textContent || "", /第一人称.*第三人称/);
  assert.match(document.querySelector('article')?.textContent || "", /初步匹配/);
  await click(button("查看具体写法"));
  assert.match(document.querySelector('[aria-label="原作叙事视角"]')?.textContent || "", /第一人称/);
  assert.match(document.querySelector('[aria-label="写法适用视角"]')?.textContent || "", /第一人称.*第三人称/);
});

test("unknown project and source views never silently become third-person labels", async () => {
  await mount([{ ...exampleItems[0], pov: ["third_person"] }], "");
  assert.match(document.querySelector('[aria-label="原作叙事视角"]')?.textContent || "", /待判断/);
  assert.match(document.querySelector('[aria-label="写法适用视角"]')?.textContent || "", /待核对/);
  assert.match(document.querySelector('article')?.textContent || "", /本书视角待设置/);
  assert.doesNotMatch(document.querySelector('article')?.textContent || "", /第三人称|初步匹配/);
});

test("mixed source narration and partial applicability stay explicit", async () => {
  await mount([{ ...exampleItems[0], pov: [], pov_metadata: {
    source_pov: ["first_person", "third_person"], source_status: "mixed", source_basis: "candidates",
    target_pov: ["first_person"], target_status: "partial",
  } }], "first_person");
  assert.match(document.querySelector('[aria-label="原作叙事视角"]')?.textContent || "", /混合.*第一人称.*第三人称/);
  assert.match(document.querySelector('[aria-label="写法适用视角"]')?.textContent || "", /第一人称.*部分.*待核对/);
  assert.doesNotMatch(document.querySelector('article')?.textContent || "", /初步匹配/);
});

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
