import type { NodeExecutionInfo, WorkflowTask } from "../types";

export type NovelNodeCounts = {
  completed: number; skipped: number; running: number; pending: number; failed: number;
  retryWaiting: number; waitingApproval: number; unknown: number;
};

export type NovelProgressNode = {
  id: string; label: string; path: string; status: string;
  elapsedSeconds: number | null; automaticRetryCount: number; retryInSeconds: number | null;
  children: NovelProgressNode[];
};

export type NovelTaskProgressSummary = {
  status: string; counts: NovelNodeCounts; childCounts: NovelNodeCounts;
  total: number | null; percent: number | null; elapsedSeconds: number | null;
  disabledCount: number; activeNodes: NovelProgressNode[]; failedNodes: NovelProgressNode[];
  progressBasis: "snapshot" | "reported" | "unknown";
};

const emptyCounts = (): NovelNodeCounts => ({
  completed: 0, skipped: 0, running: 0, pending: 0, failed: 0, retryWaiting: 0, waitingApproval: 0, unknown: 0,
});

const activeStatuses = new Set(["running", "retry_waiting", "waiting_approval"]);
const countKeys: Record<string, keyof NovelNodeCounts> = {
  completed: "completed", skipped: "skipped", running: "running", pending: "pending", failed: "failed",
  retry_waiting: "retryWaiting", waiting_approval: "waitingApproval",
};

function timestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function elapsed(start: string | null | undefined, end: number | null): number | null {
  const begin = timestamp(start);
  return begin === null || end === null || !Number.isFinite(end) ? null : Math.max(0, Math.floor((end - begin) / 1000));
}

function addCount(counts: NovelNodeCounts, status: string) {
  counts[countKeys[status] || "unknown"]++;
}

function nodeStatus(state: NodeExecutionInfo | undefined, disabled = false): string {
  if (!state) return disabled ? "skipped" : "pending";
  if (state.is_skipped && !activeStatuses.has(state.status)) return "skipped";
  return state.status || "unknown";
}

/** Only the task's persisted snapshot proves which nodes and labels belong to its history. */
export function buildNovelTaskProgress(task: WorkflowTask | null, now = Date.now()): NovelTaskProgressSummary {
  const result: NovelTaskProgressSummary = { status: task?.status || "idle", counts: emptyCounts(), childCounts: emptyCounts(), total: null,
    percent: null, elapsedSeconds: null, disabledCount: 0, activeNodes: [], failedNodes: [], progressBasis: "unknown" };
  if (!task) return result;
  const terminal = ["completed", "failed", "stopped"].includes(task.status);
  const taskEnd = terminal ? timestamp(task.completed_at) : now;
  result.elapsedSeconds = elapsed(task.started_at, taskEnd);
  const savedSnapshot = task.snapshot_definition;
  const snapshot = savedSnapshot?.workflow_id === task.workflow_id ? savedSnapshot : undefined;
  const snapshotNodes = new Map((snapshot?.nodes || []).map(value => [value.id, value]));
  const states = task.node_states || {};
  const disabled = new Set(task.disabled_node_ids || []);
  result.disabledCount = [...snapshotNodes.keys()].filter(id => disabled.has(id)).length;

  function visit(id: string, state: NodeExecutionInfo | undefined, parents: string[], label = id): NovelProgressNode {
    const status = nodeStatus(state, parents.length === 0 && disabled.has(id));
    const end = activeStatuses.has(status) && status !== "retry_waiting"
      ? taskEnd
      : timestamp(state?.completed_at) ?? (activeStatuses.has(status) ? taskEnd : null);
    const retryAt = timestamp(state?.next_retry_at);
    const retryCount = state?.automatic_retry_count;
    const row: NovelProgressNode = {
      id, label, path: [...parents, label].join(" › "), status,
      elapsedSeconds: elapsed(state?.started_at, end),
      automaticRetryCount: typeof retryCount === "number" && Number.isFinite(retryCount) ? Math.max(0, Math.floor(retryCount)) : 0,
      retryInSeconds: retryAt !== null && Number.isFinite(now) ? Math.max(0, Math.ceil((retryAt - now) / 1000)) : null,
      children: [],
    };
    addCount(parents.length ? result.childCounts : result.counts, status);
    if (activeStatuses.has(status)) result.activeNodes.push(row);
    if (status === "failed") result.failedNodes.push(row);
    for (const [childId, childState] of Object.entries(state?.child_states || {})) {
      row.children.push(visit(childId, childState, [...parents, label]));
    }
    return row;
  }
  for (const id of new Set([...snapshotNodes.keys(), ...Object.keys(states)])) {
    visit(id, states[id], [], snapshotNodes.get(id)?.label || id);
  }

  let settled: number | null = null;
  if (snapshot && snapshotNodes.size > 0) {
    const executable = [...snapshotNodes.keys()].filter(id => !disabled.has(id));
    result.total = executable.length;
    settled = executable.filter(id => ["completed", "skipped"].includes(nodeStatus(states[id]))).length;
    result.progressBasis = "snapshot";
  } else if (task.progress && Number.isInteger(task.progress.total) && task.progress.total > 0
    && Number.isInteger(task.progress.completed) && task.progress.completed >= 0
    && task.progress.completed <= task.progress.total) {
    result.total = task.progress.total;
    settled = task.progress.completed;
    result.progressBasis = "reported";
  }
  if (task.status === "completed") result.percent = 100;
  else if (settled !== null && result.total && result.total > 0) {
    // All node records can settle before publication/finalization succeeds.
    // Preserve the actual counts and withhold a contradictory percentage.
    if (settled < result.total) result.percent = Math.floor(settled / result.total * 100);
  }
  return result;
}
