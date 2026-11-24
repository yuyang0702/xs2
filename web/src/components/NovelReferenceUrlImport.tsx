import { useEffect, useId, useRef, useState } from "react";
import { importNovelUrl, inspectNovelImportUrl, type PublicChapterLink } from "../lib/api";
import ReferencePages from "./ReferencePages";

export default function NovelReferenceUrlImport({workflowId, workspace, mode, disabled, busy, setBusy, onImport}: {
  workflowId: string; workspace: string; mode: string; disabled: boolean; busy: boolean;
  setBusy: (busy: boolean) => void; onImport: (path: string, mode: string) => void;
}) {
  const [url, setUrl] = useState("");
  const [catalog, setCatalog] = useState<Awaited<ReturnType<typeof inspectNovelImportUrl>>>();
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [feedback, setFeedback] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const inputId = useId();
  const operation = useRef<AbortController>();
  useEffect(() => () => {
    if (operation.current) {
      operation.current.abort();
      operation.current = undefined;
      setBusy(false);
    }
  }, [setBusy]);
  const chapters = catalog?.chapters || [];
  const whole = mode === "serial_full";
  const locked = disabled || busy;
  const selected = whole ? chapters : chapters.filter(chapter => checked.has(chapter.url));
  const button = "rounded-lg border border-primary/40 px-3 py-2 text-sm disabled:opacity-50";
  async function inspect() {
    if (operation.current) return;
    const controller = new AbortController(); operation.current = controller;
    setBusy(true); setFeedback(""); setWarnings([]); setCatalog(undefined);
    try {
      const result = await inspectNovelImportUrl(url.trim(), controller.signal);
      if (controller.signal.aborted) return;
      setCatalog(result); setChecked(new Set(result.chapters.filter(chapter => chapter.selected).map(chapter => chapter.url)));
      setWarnings(result.warnings || []);
      if (!result.chapters.length && !result.has_page_text) setFeedback("这个页面没有可读取的正文或目录。");
    } catch (error) {
      if (!controller.signal.aborted) setFeedback(error instanceof Error ? error.message : String(error));
    } finally { if (operation.current === controller) { operation.current = undefined; setBusy(false); } }
  }
  async function fetchCorpus() {
    if (operation.current) return;
    const controller = new AbortController(); operation.current = controller;
    setBusy(true); setFeedback("");
    try {
      const result = await importNovelUrl({workflow_id: workflowId, workspace, url: url.trim(), source_mode: mode, chapters: selected}, controller.signal);
      if (controller.signal.aborted) return;
      const importedMode = result.source_mode || (mode === "short_full" ? "short_full" : "serial_chapters");
      onImport(result.path, importedMode);
      setWarnings(result.warnings || []);
      setFeedback(`已导入 ${result.chapter_count} 章，可开始蒸馏。`);
    } catch (error) {
      if (!controller.signal.aborted) setFeedback(error instanceof Error ? error.message : String(error));
    } finally { if (operation.current === controller) { operation.current = undefined; setBusy(false); } }
  }
  function toggle(chapter: PublicChapterLink, value: boolean) {
    setChecked(previous => {
      const next = new Set(previous);
      if (value) next.add(chapter.url); else next.delete(chapter.url);
      return next;
    });
  }
  const catalogReady = whole ? catalog?.catalog_complete && catalog.work_finished !== false && chapters.length > 0 : !chapters.length || selected.length > 0;
  return <div className="rounded-xl border border-primary/25 bg-primary/5 p-4">
    <label htmlFor={inputId} className="mb-2 block text-sm">从番茄小说导入</label>
    <div className="flex flex-wrap gap-2">
      <input id={inputId} aria-label="番茄小说作品网址" value={url} disabled={locked} onChange={event => {
        setUrl(event.target.value); setCatalog(undefined); setChecked(new Set()); setWarnings([]); setFeedback("");
      }} placeholder="番茄小说作品详情页或正文页网址" className="min-w-48 flex-1 rounded-xl border border-border bg-background px-3 py-2.5 text-sm" />
      <button disabled={!url.trim() || locked} onClick={() => void inspect()} className={button}>识别章节</button>
    </div>
    {!!chapters.length && <div className="mt-3 space-y-2">
      <p className="text-xs text-muted-foreground">目录共 {chapters.length} 章 · {whole ? "整本模式将读取全部章节" : `已选 ${selected.length} 章`}</p>
      {!whole && <label className="flex gap-2 text-xs"><input type="checkbox" aria-label="选择全部目录章节" disabled={locked} checked={selected.length === chapters.length}
        onChange={event => setChecked(new Set(event.target.checked ? chapters.map(item => item.url) : []))} />选择全部目录章节</label>}
      <ReferencePages items={chapters}>{page => <div className="max-h-48 space-y-1 overflow-auto rounded-lg border border-border bg-background/60 p-2">{page.map(chapter =>
        <label key={chapter.url} className="flex items-center gap-2 px-2 py-1 text-xs"><input type="checkbox" checked={whole || checked.has(chapter.url)} disabled={locked || whole} onChange={event => toggle(chapter, event.target.checked)} />
          <span>{chapter.index}. {chapter.title}</span></label>)}</div>}</ReferencePages>
    </div>}
    {whole && !catalogReady && <p className="mt-2 text-xs text-muted-foreground">{catalog?.work_finished === false ? "作品仍在连载，可按章节样本导入。" : catalog ? "当前页面未提供完整目录，可切换为章节样本或上传整书文件。" : "请先识别作品详情页的完整目录。"}</p>}
    <button onClick={() => void fetchCorpus()} disabled={!url.trim() || locked || !catalogReady || (!!catalog && !chapters.length && !catalog.has_page_text)} className={button + " mt-3 bg-primary text-primary-foreground"}>
      {busy ? "读取中…" : whole ? "导入整本目录" : chapters.length ? `导入所选章节（${selected.length} 章）` : "导入页面正文"}
    </button>
    {feedback && <p role="status" className="mt-2 text-xs text-primary">{feedback}</p>}
    {warnings.map((warning, index) => <p key={index} className="mt-2 text-xs text-amber-300">{warning}</p>)}
  </div>;
}
