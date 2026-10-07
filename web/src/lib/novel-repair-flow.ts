const INVALIDATED = ['polish', 'reader-sim', 'post-hoc', 'export'];

// Restart only the existing revision cycle; keep world/characters/outline and
// stop at the new reader assessment instead of delivering unchecked changes.
export function beginReaderRepair<T extends {values: Record<string, string>; refs: Record<string, unknown>; completed: string[]; autoScope?: 'manual' | 'short_full' | 'serial_batch'; readerRepairCount?: number}>(project: T, index: number, feedbackPath: string, modelId = '', reviewOnly = true) {
  return {...project, index, stageId: 'polish', autoNext: true, autoScope: reviewOnly ? 'short_full' as const : project.autoScope || 'short_full' as const,
    autoLaunchStage: 'polish', repairReviewOnly: reviewOnly, repairModel: modelId, autoRepairPlanId: '', autoPauseReason: '', readerRepairCount: reviewOnly ? 0 : (project.readerRepairCount || 0) + 1,
    refs: Object.fromEntries(Object.entries(project.refs).filter(([id]) => !INVALIDATED.includes(id))),
    completed: project.completed.filter(id => !INVALIDATED.includes(id)),
    values: {...project.values, author_feedback_file: feedbackPath}};
}
