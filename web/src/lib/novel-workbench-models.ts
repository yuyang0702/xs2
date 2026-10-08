import { request } from "./http-client";
import type { WorkflowDefinition, WorkflowTask } from "../types";

export type NovelModelNode = {
  id: string; label: string; override: string; effective_model: string;
  source: "workflow" | "agent" | "system" | "parameter";
  editable: boolean; available: boolean; condition: string;
};
export type NovelModelSettings = { workflow_id: string; version: number; digest: string; nodes: NovelModelNode[] };
export function readNovelModels(workflowId: string) {
  return request<NovelModelSettings>(`/novel-console/workflow-models?${new URLSearchParams({ workflow_id: workflowId })}`);
}
export function saveNovelModels(settings: NovelModelSettings, nodeModels: Record<string, string>) {
  return request<NovelModelSettings>("/novel-console/workflow-models", {
    method: "PATCH", body: JSON.stringify({ workflow_id: settings.workflow_id, expected_digest: settings.digest, node_models: nodeModels }),
  });
}

// A reader's temporary repair choice must never replace an explicit Workflow
// node choice or a parameter binding when manual/automatic tasks are created.
export function repairNodeModels(definition: WorkflowDefinition, model: string) {
  return Object.fromEntries(definition.nodes.filter(node => node.node_type === "agent" &&
    !node.model_override && !node.var_bindings?.model_override?.var_key).map(node => [node.id, model]));
}

export function recordedTaskModels(task: WorkflowTask | null | undefined): Array<{ id: string; models: string[]; status: string }> {
  return Object.entries(task?.node_states || {}).map(([id, state]) => {
    const calls = (state as unknown as { token_usage_calls?: Array<{ model_id?: string; model?: string }> }).token_usage_calls || [];
    return { id, status: state.status, models: [...new Set(calls.map(call => call.model_id || call.model || "").filter(Boolean))] };
  });
}
