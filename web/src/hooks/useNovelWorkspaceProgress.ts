import { useEffect, useState } from "react";
import { getNovelProgress, type NovelProgress } from "../lib/api";

type WorkspaceProgress = {
  workflowId: string;
  workspace: string;
  progress: NovelProgress | null;
  progressError: string;
};

export function useNovelWorkspaceProgress(workflowId: string, workspace: string) {
  const [record, setRecord] = useState<WorkspaceProgress>();
  useEffect(() => {
    const controller = new AbortController();
    let sequence = 0;
    let latestSettled = 0;
    let progress: NovelProgress | null = null;

    function publish(request: number, next: NovelProgress | null, progressError: string) {
      if (controller.signal.aborted || request < latestSettled) return;
      latestSettled = request;
      if (next) progress = next;
      setRecord({ workflowId, workspace, progress, progressError });
    }
    async function refresh() {
      const request = ++sequence;
      try {
        const next = await getNovelProgress(workflowId, workspace, "", controller.signal);
        publish(request, next, "");
      } catch (failure) {
        publish(request, null, failure instanceof Error ? failure.message : "读取进度失败");
      }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [workflowId, workspace]);

  return record?.workflowId === workflowId && record.workspace === workspace
    ? record : { progress: null, progressError: "" };
}
