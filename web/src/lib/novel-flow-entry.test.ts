import assert from 'node:assert/strict';
import {test} from 'node:test';
import {novelEntryStage, canOpenNovelStage} from './novel-flow-entry';

const stages=[{id:'novel-advisor'},{id:'build'},{id:'character'},{id:'mvp'},{id:'export'}];
const draft={persisted:false,index:1,stageId:'build',refs:{},completed:[],directionConfirmed:false};

test('a new or previously untouched draft enters the adviser instead of silently skipping it', () => {
  assert.equal(novelEntryStage(draft,stages),'novel-advisor');
  assert.equal(novelEntryStage({...draft,persisted:true},stages),'novel-advisor');
  assert.equal(novelEntryStage({...draft,stageId:undefined,index:0},stages),'novel-advisor');
  assert.equal(novelEntryStage({...draft,directionConfirmed:true},stages),'build');
  assert.equal(novelEntryStage({...draft,persisted:true,stageId:'mvp',index:3},stages),'mvp');
});

test('opening settings or moving reference modules keeps the existing production position', () => {
  assert.equal(novelEntryStage({...draft,persisted:true,stageId:'mvp',index:3,refs:{build:{},mvp:{}}},stages),'mvp');
  assert.equal(novelEntryStage({...draft,persisted:true,stageId:'adopt-reference',refs:{build:{},export:{}}},stages),'export');
});

test('an optional adviser remains accessible without unlocking future production or leaving a running task', () => {
  assert.equal(canOpenNovelStage('novel-advisor','build',[],false),true);
  assert.equal(canOpenNovelStage('novel-advisor','mvp',['build'],false),true);
  assert.equal(canOpenNovelStage('character','build',[],false),false);
  assert.equal(canOpenNovelStage('build','mvp',['build'],false),true);
  assert.equal(canOpenNovelStage('novel-advisor','mvp',['build'],true),false);
});
