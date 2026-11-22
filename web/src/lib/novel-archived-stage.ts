import { getNovelAdoptedWriting, readWorkspaceFile } from "./api";
import type { WorkflowTask } from "../types";

type TaskRef = Pick<WorkflowTask, "workflow_id" | "task_id">;

export function isMissingNovelTask(error: unknown): boolean {
  return error instanceof Error && /^API Error 404: \{\s*"detail"\s*:\s*"任务不存在"\s*\}$/.test(error.message);
}

export async function readArchivedNovelStage(workspace: string, stage: string, ref: TaskRef, artifact: string, chapter?: string) {
  const read = async (path: string) => (await readWorkspaceFile(ref.workflow_id, workspace, path)).content;
  const manifest = JSON.parse(await read(".novel-project.json")).importedProduction;
  const recorded = manifest?.stages?.[stage];
  const dir = manifest?.evidence_directory;
  if (recorded?.workflow_id !== ref.workflow_id || recorded?.task_id !== ref.task_id ||
      typeof dir !== "string" || !dir.split("/").every(part => part && part !== "." && part !== ".." && !/[\\:]/.test(part)) ||
      !/^[\w-]+$/.test(stage) || !/^[\w-]+$/.test(ref.task_id)) {
    throw new Error("本书没有与此步骤和任务编号相符的归档。");
  }
  const archive = JSON.parse(await read(`${dir}/${stage}-${ref.task_id}.json`));
  if (archive.workflow_id !== ref.workflow_id || archive.task_id !== ref.task_id || archive.status !== "completed") {
    throw new Error("本书归档未证实该任务已完成。");
  }
  if (chapter && String(archive.parameter_values?.chapter_number ?? "").padStart(4, "0") !== chapter.padStart(4, "0")) {
    throw new Error("归档任务的章节与当前章节不符。");
  }
  if (stage === "adopt-reference") {
    const blueprint = await getNovelAdoptedWriting(ref.workflow_id, workspace);
    const selection = archive.parameter_values?.selection_json;
    const requested = typeof selection === "string" ? JSON.parse(selection) : null;
    const fields = ["selected_candidate_ids", "selected_style_ids", "selected_conflict_ids"] as const;
    if (!(blueprint.version > 0) || !fields.some(key => Array.isArray(requested?.[key])) ||
        !fields.every(key => requested[key] === undefined || (Array.isArray(requested[key]) &&
          requested[key].every((id: string) => blueprint[key].includes(id))))) {
      throw new Error("本书当前的采用记录无法印证这次历史采用。");
    }
  }
  const content = await read(artifact);
  if (!content.trim()) throw new Error("归档已完成，但当前作品缺少该步骤的产物。");
  return { task: archive as WorkflowTask, content };
}
