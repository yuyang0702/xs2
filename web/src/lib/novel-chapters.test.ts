import assert from "node:assert/strict";
import {test} from "node:test";
import {nextSerialChapter, selectProductionChapter} from "./novel-chapters";
import {beginReaderRepair} from "./novel-repair-flow";

const project = {
  index:9, stageId:"export", values:{chapter_number:"0001", human_intent:"第一章目标", latest_chapter:"0000"},
  refs:{build:{workflow_id:"build",task_id:"world"}, mvp:{workflow_id:"mvp",task_id:"body1"}, export:{workflow_id:"export",task_id:"export1"}},
  completed:["build","character","story-plan","outline","mvp","polish","reader-sim","post-hoc","export"],
  selected:["keep-style"], autoNext:false,
};
const context = {chapter:"0002",has_body:false, refs:{},completed:[],values:{human_intent:"第二章目标"},later_chapters:[],message:""};

test("second chapter retains book preparation and writing, clears first chapter production refs", () => {
  const next = selectProductionChapter(project,context,"mvp",5);
  assert.equal(next.values.chapter_number,"0002");
  assert.equal(next.values.prev_chapter,"0001");
  assert.equal(next.values.human_intent,"第二章目标");
  assert.equal(next.stageId,"mvp");
  assert.deepEqual(next.completed,["build","character","story-plan","outline"]);
  assert.deepEqual(next.refs,{build:project.refs.build});
  assert.deepEqual(next.selected,["keep-style"]);
  assert.equal(next.autoNext,false);
  assert.equal(next.autoLaunchStage,"");
  assert.equal(project.refs.mvp.task_id,"body1");
});

test("automatic serial continuation launches only target chapter and keeps batch scope", () => {
  const next = selectProductionChapter(project,context,"mvp",5,true);
  assert.equal(next.autoNext,true); assert.equal(next.autoScope,"serial_batch");
  assert.equal(next.autoLaunchStage,"mvp");
});

test("targeted revision uses target chapter refs and never inherits another chapter feedback", () => {
  const current = {...project,values:{...project.values,chapter_number:"0003",author_feedback_file:"quality/repairs/0003/old.md"}};
  const target = {...context,chapter:"0001",has_body:true,refs:{mvp:project.refs.mvp},completed:["mvp"]};
  const next = beginReaderRepair(selectProductionChapter(current,target,"polish",6),6,"quality/repairs/0001/new.md","model");
  assert.equal(next.values.chapter_number,"0001");
  assert.equal(next.values.prev_chapter,"0000");
  assert.equal(next.refs.mvp.task_id,"body1");
  assert.equal(next.values.author_feedback_file,"quality/repairs/0001/new.md");
  assert.equal(next.repairReviewOnly,true);
  assert.equal(next.autoScope,"short_full");
});

test("reading or revising an early chapter cannot cause another copy of a written chapter", () => {
  assert.equal(nextSerialChapter(["0001","0002","0003"],"0001"),"0004");
  assert.equal(nextSerialChapter(["0001"],"0002"),"0002");
});

test("unfinished chapter requirements survive an excursion into old chapter revision", () => {
  const current = {...project, values:{...project.values,chapter_number:"0002",human_intent:"用户尚未生成的第二章想法"}};
  const old = selectProductionChapter(current,{...context,chapter:"0001",has_body:true},"polish",6);
  const restored = selectProductionChapter(old,context,"mvp",5);
  assert.equal(restored.values.human_intent,"用户尚未生成的第二章想法");
});
