import { useState } from "react";
import NovelArchiveContent from "./NovelArchiveContent";
import NovelReaderReport from "./NovelReaderReport";
import NovelReadingDialog from "./NovelReadingDialog";

export default function NovelWorkflowArtifact({ content, title, readerReport = false }: { content: string; title: string; readerReport?: boolean }) {
  const [reading, setReading] = useState(false);
  let report: Record<string, unknown> | null = null;
  if (readerReport) {
    try { const value: unknown = JSON.parse(content); if (value && typeof value === "object" && !Array.isArray(value)) report = value as Record<string, unknown>; } catch { /* Use the readable format error below. */ }
  }
  const body = () => report ? <NovelReaderReport report={report} /> : <NovelArchiveContent content={content} structured={readerReport} />;
  return <div className="mt-4"><div className="flex flex-wrap items-center justify-between gap-3"><p className="text-sm font-medium">已生成内容</p><button onClick={() => setReading(true)} className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-secondary/60">展开阅读</button></div><div className="mt-4 max-h-[500px] overflow-auto rounded-xl border border-border bg-background/30 p-4 sm:p-6"><div className="mx-auto max-w-[76ch]">{body()}</div></div>{reading && <NovelReadingDialog title={title} onClose={() => setReading(false)}>{body()}</NovelReadingDialog>}</div>;
}
