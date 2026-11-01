import assert from "node:assert/strict";
import { test } from "node:test";
import React, { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import NovelStepModels from "../components/NovelStepModels";
import type { WorkflowTask } from "../types";
import { recordedTaskModels } from "./novel-workbench-models";

Object.assign(globalThis, { React });

function task(nodeStates: Record<string, unknown>): WorkflowTask {
  return { task_id: "historic-task", workflow_id: "workflow", name: "Historic task", status: "completed",
    current_node_id: null, run_id: "run", created_at: "2026-10-01", started_at: null, completed_at: null,
    node_states: nodeStates } as WorkflowTask;
}

test("recorded models use historical provider/model fields and exclude unknown placeholders", () => {
  const historical = task({ writer: { status: "completed", token_usage_calls: [
    { model_id: "unknown", provider: "relay", model: "actual-writer" },
    { model_id: "relay:actual-writer", provider: "relay", model: "actual-writer" },
    { model_id: "unknown", provider: "unknown", model: "unknown" },
    { model_id: "backup:reviewer" },
  ] } });
  const before = JSON.stringify(historical);
  assert.deepEqual(recordedTaskModels(historical), [{ id: "writer", status: "completed",
    models: ["relay:actual-writer", "backup:reviewer"], hasUnrecordedCalls: true }]);
  assert.equal(JSON.stringify(historical), before);
});

test("recorded task models include subprocess and retry calls", () => {
  assert.deepEqual(recordedTaskModels(task({ subflow: { status: "completed", child_states: {
    writer: { status: "completed", token_usage_calls: [{ model_id: "backup:old" }, { model_id: "relay:new" }] },
  } } })), [{ id: "subflow", status: "completed", models: ["backup:old", "relay:new"], hasUnrecordedCalls: false }]);
});

test("historical missing identity is shown separately from a task with no calls", () => {
  const panel = (current: WorkflowTask) => renderToStaticMarkup(createElement(NovelStepModels, {
    workflowId: "workflow", task: current, disabled: false, onPendingChange() {}, onSaved() {},
  }));
  const missing = panel(task({ writer: { status: "completed", token_usage_calls: [
    { model_id: "unknown", provider: "unknown", model: "unknown" },
  ] } }));
  assert.match(missing, /历史调用未记录模型/);
  assert.doesNotMatch(missing, /unknown/);
  assert.match(panel(task({ writer: { status: "pending" } })), /尚无调用记录/);
  assert.match(panel(task({ writer: { status: "completed", token_usage_calls: [
    { model_id: "relay:writer" }, { model_id: "unknown" },
  ] } })), /部分调用未记录模型/);
});
