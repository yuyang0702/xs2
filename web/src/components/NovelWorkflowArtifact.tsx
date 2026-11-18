import { useState } from "react";
import NovelArchiveContent from "./NovelArchiveContent";
import NovelReadingDialog from "./NovelReadingDialog";

export default function NovelWorkflowArtifact({ content, title }: { content: string; title: string }) {
  const [reading, setReading] = useState(false);
  return <div className="mt-4"><div className="flex flex-wrap items-center justify-between gap-3"><p className="text-sm font-medium">已生成内容</p><button onClick={() => setReading(true)} className="rounded-lg border border-border px-3 py-2 text-sm hover:bg-secondary/60">展开阅读</button></div><div className="mt-4 max-h-[500px] overflow-auto rounded-xl border border-border bg-background/30 p-4 sm:p-6"><div className="mx-auto max-w-[76ch]"><NovelArchiveContent content={content} /></div></div>{reading && <NovelReadingDialog title={title} onClose={() => setReading(false)}><NovelArchiveContent content={content} /></NovelReadingDialog>}</div>;
}
