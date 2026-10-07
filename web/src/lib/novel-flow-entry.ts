import {resumeProductionStage} from './novel-writing-selection';

type EntryProject = {
  persisted: boolean;
  stageId?: string;
  index: number;
  refs: Record<string, unknown>;
  completed: string[];
  directionConfirmed: boolean;
};

export function novelEntryStage(project: EntryProject, stages: Array<{id: string}>) {
  const emptyDraft = !Object.keys(project.refs).length && !project.completed.length &&
    (!project.persisted || project.stageId === 'build' || (!project.stageId && project.index <= 1));
  if (emptyDraft && !project.directionConfirmed) return 'novel-advisor';
  if (stages.some(stage => stage.id === project.stageId)) return project.stageId!;
  if (['reference-distillation', 'style-compatibility-advisor', 'adopt-reference'].includes(project.stageId || '')) {
    return resumeProductionStage(stages, project.refs);
  }
  return stages[Math.max(0, Math.min(project.index, stages.length - 1))]?.id || 'novel-advisor';
}

export function canOpenNovelStage(id: string, current: string, completed: string[], busy: boolean) {
  return !busy && (id === 'novel-advisor' || id === current || completed.includes(id));
}
