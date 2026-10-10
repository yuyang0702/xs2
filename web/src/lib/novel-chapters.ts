import type {NovelChapterContext} from "./api";

const PRODUCTION = ["mvp", "polish", "reader-sim", "post-hoc", "export"];
type ChapterProject = {
  values: Record<string, string>; refs: Record<string, {workflow_id:string;task_id:string}>;
  completed: string[]; index: number; stageId?: string;
  chapterDrafts?: Record<string, Record<string, string>>;
};

export function nextSerialChapter(chapters: string[], current: string) {
  const next = Math.max(0, ...chapters.map(Number)) + 1;
  return String(Math.max(next, Number(current) || 1)).padStart(4, "0");
}

export function selectProductionChapter<T extends ChapterProject>(
  project: T, context: NovelChapterContext, stageId: string, index: number, automatic = false,
) {
  const same = project.values.chapter_number === context.chapter;
  const draftKeys = ["human_intent", "world_intent", "target_word_count", "chapter_ending_mode"];
  const chapterDrafts = {...project.chapterDrafts,
    [project.values.chapter_number]: Object.fromEntries(draftKeys.map(key => [key, project.values[key] || ""]))};
  const draft = chapterDrafts[context.chapter];
  // Book preparation and adopted style survive; production refs are chapter-owned.
  return {...project, index, stageId, autoNext: automatic,
    autoScope: automatic ? "serial_batch" as const : "manual" as const,
    autoLaunchStage: automatic ? stageId : "", autoRepairPlanId: "", autoPauseReason: "",
    repairReviewOnly: false, assessmentOnly: false, repairModel: "", readerRepairCount: 0,
    continuationIssue: null, chapterDrafts,
    refs: {...Object.fromEntries(Object.entries(project.refs).filter(([id]) => !PRODUCTION.includes(id))), ...context.refs},
    completed: [...new Set([...project.completed.filter(id => !PRODUCTION.includes(id)), ...context.completed])],
    values: {...project.values, human_intent: same ? project.values.human_intent || "" : "",
      world_intent: same ? project.values.world_intent || "" : "",
      chapter_ending_mode: "continue", ...context.values,
      ...(draft ? Object.fromEntries(Object.entries(draft).filter(([, value]) => value !== "")) : {}),
      chapter_number: context.chapter, prev_chapter: String(Number(context.chapter) - 1).padStart(4, "0"),
      latest_chapter: String(Math.max(Number(project.values.latest_chapter) || 0, Number(context.chapter) - 1)).padStart(4, "0"),
      author_feedback_file: "quality/author_feedback.md"}};
}
