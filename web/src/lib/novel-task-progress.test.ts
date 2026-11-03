import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { NodeExecutionInfo, TaskDetailResponse, WorkflowDefinition, WorkflowNodeDef, WorkflowTask } from "../types";
import { buildNovelTaskProgress } from "./novel-task-progress";

const now = Date.parse("2026-11-01T03:02:00Z");
const node = (id: string, status: NodeExecutionInfo["status"], extra: Partial<NodeExecutionInfo> = {}): NodeExecutionInfo => ({
  node_id: id, status, session_id: "", summary: "", ...extra,
});
const definition = (nodes: Array<[string, string]>): WorkflowDefinition => ({
  workflow_id: "historical-workflow", name: "任务快照", version: 1, created_at: "", updated_at: "", edges: [],
  nodes: nodes.map(([id, label]): WorkflowNodeDef => ({ id, label, node_type: "agent", agent_type: "writer",
    system_prompt_template: "", first_message: "", position: { x: 0, y: 0 } })),
});
const task = (patch: Partial<WorkflowTask> = {}, snapshot: WorkflowDefinition | null = null): WorkflowTask => ({
  task_id: "one", workflow_id: "historical-workflow", name: "分析来源", status: "running", current_node_id: "review",
  run_id: "run", created_at: "2026-11-01T03:00:00Z", started_at: "2026-11-01T03:00:00Z", completed_at: null,
  node_states: {}, snapshot_definition: snapshot, ...patch,
});

test("snapshot nodes determine real completion, conditional skips and pending counts", () => {
  const result = buildNovelTaskProgress(task({ node_states: {
    done: node("done", "completed"), branch: node("branch", "skipped"),
    review: node("review", "running", { started_at: "2026-11-01T03:01:30Z" }),
    error: node("error", "failed"),
  } }, definition([["done", "读入"], ["branch", "条件分支"], ["review", "历史分析名称"], ["error", "校验"], ["future", "保存"]])), now);
  assert.deepEqual(result.counts, { completed: 1, skipped: 1, running: 1, pending: 1, failed: 1, retryWaiting: 0, waitingApproval: 0, unknown: 0 });
  assert.equal(result.total, 5);
  assert.equal(result.percent, 40);
  assert.equal(result.elapsedSeconds, 120);
  assert.equal(result.activeNodes[0].label, "历史分析名称");
  assert.equal(result.activeNodes[0].elapsedSeconds, 30);
});

test("running foreach descendants retain ancestor labels and retry timing recursively", () => {
  const result = buildNovelTaskProgress(task({ node_states: {
    windows: node("windows", "running", { child_states: {
      "window-2": node("window-2", "running", { child_states: {
        analyze: node("analyze", "retry_waiting", { automatic_retry_count: 2, next_retry_at: "2026-11-01T03:02:30Z", started_at: "2026-11-01T03:01:00Z", completed_at: "2026-11-01T03:01:40Z" }),
        skipped: node("skipped", "skipped"),
      } }),
    } }),
  } }, definition([["windows", "分窗分析"]])), now);
  assert.deepEqual(result.activeNodes.map(value => value.path), ["分窗分析", "分窗分析 › window-2", "分窗分析 › window-2 › analyze"]);
  assert.equal(result.activeNodes[2].retryInSeconds, 30);
  assert.equal(result.activeNodes[2].automaticRetryCount, 2);
  assert.equal(result.activeNodes[2].elapsedSeconds, 40);
  assert.equal(result.childCounts.retryWaiting, 1);
  assert.equal(result.childCounts.skipped, 1);
  assert.equal(result.counts.completed, 0);
  assert.equal(result.percent, 0);
});

test("unknown and recovered records never become completed nodes", () => {
  const result = buildNovelTaskProgress(task({ status: "resume_pending", node_states: {
    old: { ...node("old", "pending"), status: "recovered" as NodeExecutionInfo["status"] },
  } }, definition([["old", "恢复节点"], ["next", "后续节点"]])), now);
  assert.equal(result.counts.unknown, 1);
  assert.equal(result.counts.pending, 1);
  assert.equal(result.counts.completed, 0);
  assert.equal(result.percent, 0);
});

test("legacy skip flags remain skips and malformed saved statuses stay unknown", () => {
  const result = buildNovelTaskProgress(task({ node_states: {
    legacy: node("legacy", "completed", { is_skipped: true }),
    malformed: { ...node("malformed", "pending"), status: "" as NodeExecutionInfo["status"] },
  } }, definition([["legacy", "旧版跳过"], ["malformed", "状态缺失"]])), now);
  assert.equal(result.counts.skipped, 1);
  assert.equal(result.counts.completed, 0);
  assert.equal(result.counts.unknown, 1);
  assert.equal(result.counts.pending, 0);
});

test("only a completed task can report 100 percent, including when a failed task has stale full progress", () => {
  const failed = task({ status: "failed", completed_at: "2026-11-01T03:01:00Z", progress: { completed: 3, total: 3 } });
  assert.equal(buildNovelTaskProgress(failed, now).percent, null);
  const recorded = buildNovelTaskProgress(task({ status: "running", node_states: { done: node("done", "completed") } }, definition([["done", "已处理节点"]])), now);
  assert.equal(recorded.percent, null);
  assert.equal(recorded.counts.completed, 1);
  assert.equal(buildNovelTaskProgress(failed, now + 60_000).elapsedSeconds, 60);
  assert.equal(buildNovelTaskProgress(task({ status: "completed" }), now).percent, 100);
  assert.equal(buildNovelTaskProgress(task({ status: "pending" }, definition([["next", "未执行"]])), now).percent, 0);
});

test("missing snapshot and reported totals leave percentage unknown and ignore unrelated workflow labels", () => {
  const current = task({ node_states: { review: node("review", "running") } });
  const unrelated = { ...definition([["review", "别的流程当前名称"]]), workflow_id: "another-workflow" };
  assert.equal(buildNovelTaskProgress(current, now).percent, null);
  assert.equal(buildNovelTaskProgress({ ...current, snapshot_definition: unrelated }, now).activeNodes[0].label, "review");
  assert.equal(buildNovelTaskProgress(null, now).percent, null);
});

test("legacy task query fallback never adds today's compact nodes or labels to progress", async () => {
  const response: TaskDetailResponse = {
    task: task({ node_states: { review: node("review", "running") }, snapshot_definition: null }),
    definition: definition([["review", "今天修改后的分析名称"], ["compact-new", "新增短篇准备"]]),
  };
  const result = buildNovelTaskProgress(response.task, now);
  assert.equal(result.counts.pending, 0);
  assert.equal(result.counts.running, 1);
  assert.equal(result.total, null);
  assert.equal(result.percent, null);
  assert.equal(result.activeNodes[0].label, "review");
  const { default: NovelTaskProgress } = await import("../components/NovelTaskProgress");
  const html = renderToStaticMarkup(createElement(NovelTaskProgress, { task: response.task, now }));
  assert.match(html, /待执行 0/);
  assert.match(html, /节点总数待确认/);
  assert.doesNotMatch(html, /今天修改后的分析名称|新增短篇准备|aria-valuenow/);
});

test("malformed and future clocks do not fabricate negative durations or retry countdowns", () => {
  const result = buildNovelTaskProgress(task({ started_at: "invalid", node_states: {
    future: node("future", "running", { started_at: "2026-11-01T04:00:00Z" }),
    retry: node("retry", "retry_waiting", { started_at: "invalid", next_retry_at: "invalid", automatic_retry_count: -1 }),
  } }), now);
  assert.equal(result.elapsedSeconds, null);
  assert.equal(result.activeNodes[0].elapsedSeconds, 0);
  assert.equal(result.activeNodes[1].elapsedSeconds, null);
  assert.equal(result.activeNodes[1].retryInSeconds, null);
  assert.equal(result.activeNodes[1].automaticRetryCount, 0);
});

test("disabled snapshot nodes are transparent and do not inflate executable progress", () => {
  const result = buildNovelTaskProgress(task({ disabled_node_ids: ["disabled"], node_states: {
    done: node("done", "completed"), disabled: node("disabled", "skipped"), pending: node("pending", "pending"),
  } }, definition([["done", "完成"], ["disabled", "未启用"], ["pending", "待执行"]])), now);
  assert.equal(result.total, 2);
  assert.equal(result.disabledCount, 1);
  assert.equal(result.percent, 50);
  assert.equal(result.counts.skipped, 1);
});

test("progress UI exposes snapshot labels, node counts, elapsed time and retry instead of an ETA", async () => {
  const { default: NovelTaskProgress } = await import("../components/NovelTaskProgress");
  const html = renderToStaticMarkup(createElement(NovelTaskProgress, { now,
    task: task({ status: "retry_waiting", node_states: {
      done: node("done", "completed"), branch: node("branch", "skipped"),
      retry: node("retry", "retry_waiting", { started_at: "2026-11-01T03:01:30Z", attempt_count: 3,
        automatic_retry_count: 2, next_retry_at: "2026-11-01T03:02:30Z", error: "连接暂时中断" }),
    } }, definition([["done", "读入"], ["branch", "可选分支"], ["retry", "历史写法分析"]])),
  }));
  assert.match(html, /历史写法分析/);
  assert.match(html, /已完成 1/);
  assert.match(html, /已跳过 1/);
  assert.match(html, /等待重试 1/);
  assert.match(html, /阶段耗时 2 分/);
  assert.match(html, /节点耗时 30 秒/);
  assert.match(html, /自动重试 2 次/);
  assert.match(html, /尝试 3 次/);
  assert.match(html, /连接暂时中断/);
  assert.match(html, /30 秒后重试/);
  assert.doesNotMatch(html, /预计完成|token|令牌/i);
});

test("failed finalization shows settled records without inventing a completion percentage", async () => {
  const { default: NovelTaskProgress } = await import("../components/NovelTaskProgress");
  const html = renderToStaticMarkup(createElement(NovelTaskProgress, { now,
    task: task({ status: "failed", node_states: { done: node("done", "completed") } }, definition([["done", "已处理节点"]])),
  }));
  assert.match(html, /执行失败/);
  assert.match(html, /已完成 1/);
  assert.match(html, /节点记录已处理，任务结果待确认/);
  assert.doesNotMatch(html, /aria-valuenow|99%|100%/);
});
