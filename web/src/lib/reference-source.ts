import type { SourceCoverage } from "./api";

export const sourceTypes = {
  short_full: "短篇全文",
  serial_chapters: "长篇章节样本",
  serial_full: "长篇全文",
  unknown: "类型待判断",
};

export function sourceType(mode?: string): keyof typeof sourceTypes {
  switch (mode) {
    case "short_full": case "serial_chapters": case "serial_full": return mode;
    default: return "unknown";
  }
}

export function coverageSummary(coverage?: SourceCoverage) {
  const total = coverage?.chapter_count ?? coverage?.chapters?.length;
  const analyzed = coverage?.analyzed_chapter_count ?? coverage?.analyzed_chapters?.length;
  if (!total || analyzed == null) return "章节覆盖未记录";
  const missing = coverage?.missing_chapter_count ?? coverage?.missing_chapters?.length;
  return `已分析 ${analyzed}/${total} 章` + (coverage?.complete ? " · 已覆盖全部导入章节" : missing ? ` · ${missing} 章待补` : " · 覆盖待核对");
}

export const localCorpusPath = "references/imported-corpus.txt";
export const urlCorpusPath = "references/url-imported-corpus.txt";

export async function prepareReferenceCorpus(files: Pick<File, "name" | "text">[], savedPath: string | undefined, mode: string, savedUrlMode?: string) {
  if (files.length) {
    const sources = await Promise.all(files.map(async file => ({name: file.name, text: await file.text()})));
    if (sources.some(source => !source.text.trim() || source.text.includes("\ufffd")))
      throw new Error("参考文件需为非空 UTF-8 文本，请检查编码。");
    return {path: localCorpusPath, mode, content: sources.map(source => `===== SOURCE FILE: ${source.name} =====\n\n${source.text}`).join("\n\n")};
  }
  if (savedPath === urlCorpusPath) {
    if (mode === "serial_full" && savedUrlMode !== "serial_full")
      throw new Error("请先导入完整目录，或选择整书文件。当前网址语料没有完整目录记录。");
    if (mode !== "auto" && savedUrlMode && savedUrlMode !== mode)
      throw new Error("来源类型已更改，请按当前类型重新导入网址，或选择本地文件。");
    return {path: savedPath, mode: savedUrlMode || mode};
  }
  if (savedPath === localCorpusPath) return {path: savedPath, mode};
  throw new Error("请先选择参考文件或导入公开网址。");
}
