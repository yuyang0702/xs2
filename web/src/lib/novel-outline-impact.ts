export type OutlineImpactFile = { path: string };

export type OutlineImpactInventory = {
  plannedChapters: string[];
  writtenChapters: string[];
  confirmedChapters: string[];
};

export type OutlineChapterChange = { chapter: string; type: "added" | "removed" | "updated" };
export type OutlineChapterImpact = {
  chapter: string;
  type: OutlineChapterChange["type"] | "downstream";
  hasPlan: boolean;
  hasDraft: boolean;
  hasConfirmedArchive: boolean;
};

function chapterFromPath(path: string, pattern: RegExp) {
  const match = path.match(pattern);
  return match ? String(Number(match[1])).padStart(4, "0") : "";
}

export function outlineImpactInventory(files: OutlineImpactFile[]): OutlineImpactInventory {
  const planned = new Set<string>();
  const written = new Set<string>();
  const confirmed = new Set<string>();

  for (const file of files) {
    // 不同版本的正文工作流会把章节计划保存在 planning/chapters，
    // 也可能在章节目录里渲染成 single_chapter_guide。两者都代表
    // “已经有一份可供正文生成使用的章节方案”。
    const plannedChapter =
      chapterFromPath(file.path, /^planning\/chapters\/(\d{4})\.json$/i) ||
      chapterFromPath(file.path, /^story\/(\d{4})\/single_chapter_guide\.(?:md|json)$/i);
    const writtenChapter = chapterFromPath(file.path, /^story\/(\d{4})\/chapter\.md$/i);
    // confirmed_state.md 是给用户阅读的映射文件，JSON 是后续工作流读取的
    // 权威文件。任一存在都说明本章已有确认档案。
    const confirmedChapter = chapterFromPath(file.path, /^story\/(\d{4})\/confirmed_state\.(?:json|md)$/i);
    if (plannedChapter) planned.add(plannedChapter);
    if (writtenChapter) written.add(writtenChapter);
    if (confirmedChapter) confirmed.add(confirmedChapter);
  }

  return {
    plannedChapters: [...planned].sort(),
    writtenChapters: [...written].sort(),
    confirmedChapters: [...confirmed].sort(),
  };
}

function chapterSections(text: string) {
  const headings = [...text.matchAll(/^\s{0,3}(?:#{1,6}\s*)?(?:[-*]\s*)?(?:第\s*)?0*(\d+)\s*章(?:\s*[:：·—-].*|\s+.*)?\s*$/gm)];
  const sections = new Map<string, string>();

  headings.forEach((heading, index) => {
    const chapter = String(Number(heading[1])).padStart(4, "0");
    const start = heading.index ?? 0;
    const end = headings[index + 1]?.index ?? text.length;
    const section = text.slice(start, end).replace(/\s+/g, " ").trim();
    sections.set(chapter, section);
  });

  return sections;
}

export function compareNovelOutlines(previous: string, current: string) {
  const before = chapterSections(previous);
  const after = chapterSections(current);
  if (!before.size || !after.size) {
    return { comparisonAvailable: false, changedChapters: [] as string[], changes: [] as OutlineChapterChange[] };
  }

  const changes = [...new Set([...before.keys(), ...after.keys()])]
    .flatMap((chapter): OutlineChapterChange[] => {
      if (!before.has(chapter)) return [{ chapter, type: "added" }];
      if (!after.has(chapter)) return [{ chapter, type: "removed" }];
      if (before.get(chapter) !== after.get(chapter)) return [{ chapter, type: "updated" }];
      return [];
    })
    .sort((a, b) => a.chapter.localeCompare(b.chapter));
  return { comparisonAvailable: true, changedChapters: changes.map((change) => change.chapter), changes };
}

export function outlineChapterImpacts(
  changes: OutlineChapterChange[],
  inventory: OutlineImpactInventory,
): OutlineChapterImpact[] {
  const planned = new Set(inventory.plannedChapters);
  const written = new Set(inventory.writtenChapters);
  const archived = new Set(inventory.confirmedChapters);
  const directImpacts = changes.map((change) => ({
    ...change,
    hasPlan: planned.has(change.chapter),
    hasDraft: written.has(change.chapter),
    hasConfirmedArchive: archived.has(change.chapter),
  }));
  const earliestChangedChapter = changes
    .map((change) => Number(change.chapter))
    .filter(Number.isFinite)
    .sort((a, b) => a - b)[0];
  if (!earliestChangedChapter) return directImpacts;

  const directlyChanged = new Set(changes.map((change) => change.chapter));
  const downstreamChapters = new Set([
    ...inventory.plannedChapters,
    ...inventory.writtenChapters,
    ...inventory.confirmedChapters,
  ]);
  const downstreamImpacts = [...downstreamChapters]
    .filter((chapter) => Number(chapter) > earliestChangedChapter && !directlyChanged.has(chapter))
    .sort((a, b) => Number(a) - Number(b))
    .map((chapter) => ({
      chapter,
      type: "downstream" as const,
      hasPlan: planned.has(chapter),
      hasDraft: written.has(chapter),
      hasConfirmedArchive: archived.has(chapter),
    }));

  return [...directImpacts, ...downstreamImpacts].sort((a, b) =>
    Number(a.chapter) - Number(b.chapter) || (a.type === "downstream" ? 1 : -1),
  );
}
