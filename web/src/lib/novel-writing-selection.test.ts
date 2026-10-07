import assert from 'node:assert/strict';
import {test} from 'node:test';
import {retainAdoptedWriting, toggleWriting, validateReferenceAdaptations, resumeProductionStage} from './novel-writing-selection';

test('confirmed writing survives stale selection, new imports and attempted uncheck', () => {
  assert.deepEqual(retainAdoptedWriting([], ['old']), ['old']);
  assert.deepEqual(toggleWriting(['new'], ['old'], 'old', false), ['old', 'new']);
  assert.deepEqual(toggleWriting(['new'], ['old'], 'new', false), ['old']);
  assert.deepEqual(toggleWriting(['old'], ['old'], 'new', true), ['new', 'old']);
});

test('source conflict needs reviewed book guidance; existing confirmed choices are retained', () => {
  const choices = [{choice_id:'conflict', title:'递进链', requires_adaptation:true}];
  assert.ok(validateReferenceAdaptations(choices, ['conflict'], [], {}).includes('适配说明'));
  assert.equal(validateReferenceAdaptations(choices, ['conflict'], [], {conflict:'本书目标经已有线索触发行动，付出代价再回收'}), '');
  assert.equal(validateReferenceAdaptations(choices, ['conflict'], ['conflict'], {}), '');
});

test('moving reference preparation out of production resumes the existing book stage', () => {
  const stages=[{id:'novel-advisor'},{id:'build'},{id:'character'},{id:'mvp'},{id:'export'}];
  assert.equal(resumeProductionStage(stages, {'adopt-reference':{},'build':{},'mvp':{},'export':{}}), 'export');
  assert.equal(resumeProductionStage(stages, {'adopt-reference':{},'build':{},'mvp':{}}), 'mvp');
  assert.equal(resumeProductionStage(stages, {'reference-distillation':{}}), 'build');
});
