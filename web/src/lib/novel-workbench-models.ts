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

type RecordedUsageState = {
  token_usage_calls?: Array<{ model_id?: string; provider?: string; model?: string }>;
  token_usage?: Record<string, { call_count?: number; total_tokens?: number }>;
  child_states?: Record<string, RecordedUsageState>;
};

export type TaskModelRecord = { id: string; models: string[]; status: string; hasUnrecordedCalls: boolean };

function recordedModel(value: unknown): string {
  if (typeof value !== "string") return "";
  const model = value.trim();
  return model && model.split(":").every(part => part && part.toLowerCase() !== "unknown") ? model : "";
}

export function recordedTaskModels(task: WorkflowTask | null | undefined): TaskModelRecord[] {
  return Object.entries(task?.node_states || {}).map(([id, state]) => {
    const models = new Set<string>();
    let hasUnrecordedCalls = false;
    function collect(row: RecordedUsageState) {
      const calls = row.token_usage_calls || [];
      for (const call of calls) {
        const id = recordedModel(call.model_id), provider = recordedModel(call.provider), model = recordedModel(call.model);
        // Old ledgers sometimes omitted model_id but retained both actual fields.
        // Never fill gaps from today's workflow settings.
        const identity = id.includes(":") ? id : provider && model ? `${provider}:${model}` : id || model;
        if (identity) models.add(identity);
        else hasUnrecordedCalls = true;
      }
      if (!calls.length && Object.values(row.token_usage || {}).some(usage => (usage.call_count || usage.total_tokens || 0) > 0)) {
        hasUnrecordedCalls = true;
      }
      for (const child of Object.values(row.child_states || {})) collect(child);
    }
    collect(state as unknown as RecordedUsageState);
    return { id, status: state.status, models: [...models], hasUnrecordedCalls };
  });
}
