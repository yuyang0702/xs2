import assert from 'node:assert/strict';
import test from 'node:test';
import {beginReaderRepair} from './novel-repair-flow';

test('explicit repair retains planning, invalidates old delivery and passes the exact approved file to polish', () => {
  const old = {mode:'serial', values:{chapter_number:'0012',chapter_ending_mode:'continue'},
    refs:{build:{task_id:'world'},mvp:{task_id:'body'},polish:{task_id:'old'},'reader-sim':{task_id:'reader'},export:{task_id:'delivery'}},
    completed:['build','mvp','polish','reader-sim','post-hoc','export'], autoChapterLimit:5};
  const next = beginReaderRepair(old,9,'quality/repairs/0012/plan/instructions.md','provider:current-default');
  assert.equal(next.values.author_feedback_file,'quality/repairs/0012/plan/instructions.md');
  assert.equal(next.values.chapter_number,'0012');
  assert.deepEqual(next.refs,{build:{task_id:'world'},mvp:{task_id:'body'}});
  assert.deepEqual(next.completed,['build','mvp']);
  assert.equal(next.autoLaunchStage,'polish');
  assert.equal(next.repairReviewOnly,true);
  assert.equal(next.repairModel,'provider:current-default');
  assert.equal(next.autoScope,'short_full'); // never starts the next serial chapter
  assert.equal(old.refs.export.task_id,'delivery');
});

test('automatic repairs retain serial batch limits and count only an adopted plan', () => {
  const old = {values:{chapter_number:'0012'}, refs:{mvp:{task_id:'body'},'reader-sim':{task_id:'reader'}},
    completed:['mvp','reader-sim'], autoScope:'serial_batch' as const, autoChapterLimit:5, autoChapterStarted:2, readerRepairCount:1};
  const next = beginReaderRepair(old,9,'quality/repairs/0012/new/instructions.md','default-model',false);
  assert.equal(next.autoScope,'serial_batch');
  assert.equal(next.autoChapterLimit,5);
  assert.equal(next.autoChapterStarted,2);
  assert.equal(next.readerRepairCount,2);
  assert.equal(next.repairReviewOnly,false);
  assert.equal(next.autoRepairPlanId,'');
  assert.equal(next.values.chapter_number,'0012');
});
