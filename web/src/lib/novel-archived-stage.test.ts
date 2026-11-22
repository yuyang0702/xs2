import assert from "node:assert/strict";
import { test } from "node:test";
import { isMissingNovelTask, readArchivedNovelStage } from "./novel-archived-stage";

test("only the task endpoint's missing-task response permits archive recovery", () => {
  assert.ok(isMissingNovelTask(new Error('API Error 404: {"detail":"任务不存在"}')));
  assert.equal(isMissingNovelTask(new Error('API Error 404: {"detail":"工作区文件不存在"}')), false);
  assert.equal(isMissingNovelTask(new Error('API Error 503: {"detail":"任务不存在"}')), false);
});

test("recovery requires this book's matching stage, completed task, selection and artifact", async t => {
  const ref = {workflow_id: "wf", task_id: "old"};
  const stage = "adopt-reference";
  const artifact = "learning/active_context.md";
  const manifest = {stages: {[stage]: {...ref}}, evidence_directory: "editorial/archive"};
  const archive = {...ref, status: "completed", parameter_values: {selection_json: '{"selected_candidate_ids":["one"]}'}};
  const blueprint = {version: 2, selected_candidate_ids: ["one", "two"], selected_style_ids: [], selected_conflict_ids: []};
  let content = "本书采用记录";
  t.mock.method(globalThis, "fetch", async (input: string, options: RequestInit) => {
    const url = new URL(input, "http://localhost");
    assert.equal(url.searchParams.get("workspace"), "book");
    assert.equal(options.method ?? "GET", "GET");
    if (url.pathname.endsWith("/adopted-writing")) return Response.json(blueprint);
    switch (url.searchParams.get("path")) {
      case ".novel-project.json": return Response.json({content: JSON.stringify({importedProduction: manifest})});
      case "editorial/archive/adopt-reference-old.json": return Response.json({content: JSON.stringify(archive)});
      case artifact: return Response.json({content});
      default: throw new Error("unexpected file request");
    }
  });
  const recover = () => readArchivedNovelStage("book", stage, ref, artifact);
  assert.equal((await recover()).content, content);
  content = " ";
  await assert.rejects(recover, /缺少/);
  content = "本书采用记录";
  blueprint.selected_candidate_ids = ["two"];
  await assert.rejects(recover, /采用记录/);
  archive.parameter_values.selection_json = "{}";
  await assert.rejects(recover, /采用记录/);
  archive.status = "failed";
  await assert.rejects(recover, /未证实/);
  manifest.stages[stage].task_id = "different";
  await assert.rejects(recover, /编号/);
});
