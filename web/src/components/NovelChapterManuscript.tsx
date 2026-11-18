import { useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { readWorkspaceFile } from "../lib/api";
import { novelWorkflowId } from "../lib/novel-resources";
import NovelArchiveContent from "./NovelArchiveContent";

type Props = {
  workspace: string;
  chapter: string;
  opening: boolean;
  onBack: () => void;
  onAudit: () => void;
  onPolish: () => void;
};

export default function NovelChapterManuscript({workspace, chapter, opening, onBack, onAudit, onPolish}: Props) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setContent("");
    setLoading(true);
    setError("");
    async function read() {
      try {
        const result = await readWorkspaceFile(novelWorkflowId("mvp"), workspace, `story/${chapter}/chapter.md`);
        if (active) setContent(result.content);
      } catch (failure) {
        if (active) setError(failure instanceof Error ? failure.message : "读取正文失败。");
      } finally {
        if (active) setLoading(false);
      }
    }
    void read();
    return () => { active = false; };
  }, [workspace, chapter]);

  const actionClass = "rounded-xl border border-border px-4 py-2 text-sm disabled:opacity-50";
  const disabled = loading || opening || !content.trim();
  return <div className="space-y-5">
    <button onClick={onBack} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-3 w-3" />返回章节目录
    </button>
    <div className="flex flex-wrap items-center justify-between gap-4">
      <h1 className="text-3xl font-semibold tracking-tight">第 {Number(chapter)} 章 · 正文</h1>
      <div className="flex flex-wrap gap-2">
        <button disabled={disabled} onClick={onAudit} className={actionClass}>审核档案</button>
        <button disabled={disabled} onClick={onPolish} className={actionClass}>润色本章</button>
      </div>
    </div>
    <article aria-busy={loading} className="rounded-2xl border border-border bg-card p-6 sm:p-8">
      <div className="mx-auto max-w-[76ch]">
        {error ? <p role="alert" className="text-sm text-destructive">读取正文失败。{error}</p>
          : loading ? <p role="status" className="text-sm text-muted-foreground">正在读取正文…</p>
          : content.trim() ? <NovelArchiveContent content={content} />
          : <p className="text-sm text-muted-foreground">本章暂无正文。</p>}
      </div>
    </article>
  </div>;
}
