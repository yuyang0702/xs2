import assert from 'node:assert/strict';
import test from 'node:test';
import {advanceRepairPlan} from './novel-repair-runner';
import type {NovelAssistantEntry} from './api';

const entry: NovelAssistantEntry = {id:'same-request',question:'返修',stage:'reader',status:'completed',source:'llm',
  reply:'针对读者指出的重复段落修改，并保留结尾。',created_at:'2026-10-07',purpose:'reader_repair',chapter:'0012'};

test('reopening reuses the completed plan and passes its actual text before restarting polish', async () => {
  let asked = false;
  const result = await advanceRepairPlan(entry.id,{active:()=>true,history:async()=>[entry],ask:async()=>{asked=true; return entry;},
    apply:async plan=>{assert.equal(plan.reply,entry.reply); return {feedback_path:'quality/repairs/0012/plan/instructions.md',model_id:'default'};}});
  assert.equal(asked,false);
  assert.equal(result?.feedback_path,'quality/repairs/0012/plan/instructions.md');
});

test('unfinished plans and another busy assistant never start revision', async () => {
  for (const records of [[{...entry,status:'running' as const}],[{...entry,id:'another',status:'running' as const}]]) {
    const result = await advanceRepairPlan(entry.id,{active:()=>true,history:async()=>records,
      ask:async()=>{throw new Error('must wait');},apply:async()=>{throw new Error('must not apply');}});
    assert.equal(result,null);
  }
});

test('failed analysis pauses instead of skipping to polish or export', async () => {
  await assert.rejects(advanceRepairPlan(entry.id,{active:()=>true,history:async()=>[{...entry,status:'failed',message:'模型不可用'}],
    ask:async()=>entry,apply:async()=>{throw new Error('must not apply');}}),/模型不可用/);
});

test('navigation cancellation leaves the durable request for resuming and does not apply', async () => {
  const result = await advanceRepairPlan(entry.id,{active:()=>false,history:async()=>[entry],
    ask:async()=>entry,apply:async()=>{throw new Error('must not apply');}});
  assert.equal(result,null);
});
