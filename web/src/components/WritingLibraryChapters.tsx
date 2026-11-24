import { useState } from "react";
import { getWritingLibraryExcerpt, type CrossChapterAnalysis, type WritingLibraryItem } from "../lib/api";
import { coverageSummary, sourceType, sourceTypes } from "../lib/reference-source";
import ReferencePages from "./ReferencePages";

const dimensions: Record<string, string> = {
  foreshadowing: "伏笔与回收", character_arc: "人物弧线", phase_pacing: "阶段节奏",
  conflict: "冲突递进", relationship: "人物关系", plot: "情节推进",
};
const phases: Record<string, string> = {opening: "前段", middle: "中段", closing: "后段"};
const roles: Record<string, string> = {before: "前文", intermediate: "中间变化", after: "后文"};
const scopeBasis: Record<string, string> = {
  user_declared: "按导入时指定的整书范围分析",
  end_marker: "根据连续章号与完结标记识别整书",
  catalog: "按导入时读取的作品目录核对",
  archived_short_full: "已核对短篇全文快照和归档的分析记录",
  imported_text: "按此次导入的原文统计",
};
const panel = "rounded-xl border border-border bg-card p-4 text-sm";
type Evidence = CrossChapterAnalysis["findings"][number]["evidence"][number];

function SourceEvidence({manifest, title, item}: {manifest: WritingLibraryItem; title: string; item: Evidence}) {
  const [context, setContext] = useState<Awaited<ReturnType<typeof getWritingLibraryExcerpt>>>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function readOriginal() {
    setBusy(true); setError("");
    try {
      const result = await getWritingLibraryExcerpt(manifest.id, item.source_start, item.source_end);
      if ((manifest.source_sha256 && result.source_sha256 !== manifest.source_sha256) || result.excerpt !== item.excerpt || result.start !== item.source_start || result.end !== item.source_end)
        throw new Error("原文与这条证据的记录不一致。");
      setContext(result);
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setBusy(false); }
  }
  return <figure className="mt-2 border-l-2 border-primary/30 pl-3">
    <figcaption className="text-xs text-muted-foreground">{item.role && roles[item.role] && roles[item.role] + " · "}{title} · 原文字符位置 [{item.source_start}, {item.source_end})</figcaption>
    <blockquote className="mt-1 whitespace-pre-wrap leading-7">{context ? <>{context.before}<mark>{context.excerpt}</mark>{context.after}</> : item.excerpt}</blockquote>
    {manifest.source_mode === "serial_full" && <button disabled={busy} className="mt-1 text-xs text-primary" onClick={() => context ? setContext(undefined) : void readOriginal()}>
      {busy ? "正在读取…" : context ? "收起上下文" : "查看原文上下文"}
    </button>}
    {error && <p role="alert" className="mt-1 text-xs text-destructive">{error}</p>}
  </figure>;
}

export default function WritingLibraryChapters({manifest, analysis}: {
  manifest: WritingLibraryItem; analysis?: CrossChapterAnalysis;
}) {
  const [query, setQuery] = useState("");
  const catalog = manifest.source_coverage?.chapters || [];
  const titles = new Map(catalog.map(chapter => [chapter.id, chapter.title]));
  const analyzed = new Set(manifest.source_coverage?.analyzed_chapters);
  const missing = new Set(manifest.source_coverage?.missing_chapters);
  const notes = new Map(analysis?.chapter_observations?.map(item => [item.chapter_id, item.observations]));
  const matches = catalog.filter(chapter => (chapter.title + " " + chapter.id).includes(query.trim()));
  const evidence = (items: Evidence[]) => items?.map(item =>
    <SourceEvidence key={`${item.chapter_id}-${item.source_start}-${item.source_end}`} manifest={manifest} title={titles.get(item.chapter_id) || item.chapter_id} item={item} />);
  return <section aria-label="来源与章节分析" className="space-y-3">
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span aria-label="来源类型" className="rounded-full bg-primary/10 px-2 py-1 text-primary">{sourceTypes[sourceType(manifest.source_mode)]}</span>
      <span className="text-muted-foreground">{coverageSummary(manifest.source_coverage)}</span>
    </div>
    {!!catalog.length && <details className={panel}>
      <summary className="cursor-pointer font-medium">章节目录与覆盖 · {catalog.length} 章</summary>
      <div className="mt-2 space-y-1 text-xs text-muted-foreground">
        {manifest.source_coverage?.completeness_basis && <p>{scopeBasis[manifest.source_coverage.completeness_basis]}</p>}
        {manifest.source_coverage?.analyzed_window_count != null && manifest.source_coverage.window_count != null &&
          <p>已分析原文窗口 {manifest.source_coverage.analyzed_window_count}/{manifest.source_coverage.window_count} 个</p>}
      </div>
      <input aria-label="搜索章节" placeholder="按章节名或编号搜索" value={query} onChange={event => setQuery(event.target.value)} className="my-3 w-full rounded-lg border border-border bg-background px-3 py-2" />
      {!matches.length && <p className="text-muted-foreground">没有匹配的章节。</p>}
      <ReferencePages key={query} items={matches}>{page => <ul className="divide-y divide-border">{page.map(chapter =>
        <li key={chapter.id} className="py-2">
          <details><summary className="cursor-pointer">{chapter.title} <span className="ml-2 text-xs text-muted-foreground">{analyzed.has(chapter.id) ? "已分析" : missing.has(chapter.id) ? "待补分析" : "覆盖待核对"}</span></summary>
            <p className="mt-2 text-xs text-muted-foreground">{chapter.id} · 原文字符位置 [{chapter.start}, {chapter.end})</p>
            {notes.get(chapter.id)?.map((note, i) => <div key={i} className="mt-3">
              <p><strong>{dimensions[note.dimension] || note.dimension}</strong> · {note.statement}</p>
              {note.character_state && <p>人物变化 · {note.character_state}</p>}
              {note.lead && <p>待核对线索 · {note.lead}</p>}
              {evidence(note.evidence)}
            </div>)}
          </details>
        </li>
      )}</ul>}</ReferencePages>
    </details>}
    {analysis && (manifest.source_mode === "serial_full" || !!analysis.findings?.length) && <details className={panel}>
      <summary className="cursor-pointer font-medium">跨章分析 · {analysis.findings?.length || 0} 条结论</summary>
      {analysis.coverage && <p className="mt-3 text-xs text-muted-foreground">
        {analysis.coverage.first_pass_chapter_count == null
          ? `跨章复核已读 ${analysis.coverage.reviewed_chapter_count}/${analysis.coverage.chapter_count} 章`
          : `首轮已读 ${analysis.coverage.first_pass_chapter_count}/${analysis.coverage.chapter_count} 章 · 跨章重点回查 ${analysis.coverage.reviewed_chapter_count} 个焦点章`}
      </p>}
      <ReferencePages items={analysis.findings || []} pageSize={6}>{page => page.map(finding =>
        <div key={finding.id} className="mt-4 border-t border-border pt-4">
          <p className="text-xs text-primary">{dimensions[finding.dimension] || finding.dimension} · {finding.status === "confirmed" ? "有原文支持" : "待核实"}</p>
          <h3 className="my-2 font-medium">{finding.statement}</h3>
          {finding.reason && <p className="leading-7">{finding.reason}</p>}
          {finding.limits && <p className="mt-1 text-xs leading-6 text-muted-foreground">{finding.limits}</p>}
          {!!finding.evidence?.length && <details className="mt-2"><summary className="cursor-pointer text-primary">查看来源证据 · {finding.evidence.length} 处</summary>{evidence(finding.evidence)}</details>}
        </div>
      )}</ReferencePages>
      {!analysis.findings?.length && <p className="mt-3 text-muted-foreground">本次分析尚无可列出的跨章结论。</p>}
      {!!analysis.phase_pacing?.length && <div className="mt-4"><h3 className="font-medium">按章节顺序分段的节奏统计</h3>{analysis.phase_pacing.map(phase => <p key={phase.phase} className="mt-1 text-xs leading-6 text-muted-foreground">{phases[phase.phase] || phase.phase} · {phase.chapter_count} 章 · 章均 {phase.mean_chapter_chars} 字 · 句均 {phase.mean_sentence_chars} 字</p>)}</div>}
      {analysis.limitations?.map((item, index) => <p key={index} className="mt-2 text-xs leading-6 text-muted-foreground">{item}</p>)}
    </details>}
  </section>;
}
