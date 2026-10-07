import test from 'node:test';
import assert from 'node:assert/strict';
import type { NovelAssistantEntry } from './api';
import { applyAssistantConfiguration, premiseWithWorldDirection } from './novel-assistant-configuration';

const defaults = { genre: '都市情感', narrative_pov: 'third_person', target_word_count: '3000-4000' };
const project = () => ({ mode: 'short', values: { ...defaults }, refs: {}, completed: [], configuredFields: [] as string[] });
const entry = (): NovelAssistantEntry => ({ id: 'one', question: '末日创意', stage: '小说顾问', status: 'completed',
  source: 'llm', purpose: 'configure', reply: '方案', created_at: 'now',
  configuration_base: { mode: 'short', values: { ...defaults } }, suggestions: [
    { key: 'genre', label: '题材', value: '末日生存', reason: '符合想法' },
    { key: 'narrative_pov', label: '视角', value: 'first_person', reason: '信息受限' },
    { key: 'target_word_count', label: '字数', value: '6000-8000', reason: '承载冲突链' },
  ] });

test('fills fresh defaults, preserves explicit default-valued choices and concurrent user edits', () => {
  const current = project();
  current.configuredFields = ['narrative_pov'];
  current.values.target_word_count = '10000';
  const result = applyAssistantConfiguration(current, entry(), defaults);
  assert.equal(result.values.genre, '末日生存');
  assert.equal(result.values.narrative_pov, 'third_person');
  assert.equal(result.values.target_word_count, '10000');
  assert.deepEqual(result.assistantConfigurations?.one.applied, ['genre']);
  assert.deepEqual(result.assistantConfigurations?.one.preserved, ['narrative_pov', 'target_word_count']);
  assert.equal(applyAssistantConfiguration(result, entry(), defaults), result);
});

test('established facts, changed modes and ordinary conversation never replace book configuration', () => {
  const established = { ...project(), refs: { build: {} } };
  const result = applyAssistantConfiguration(established, entry(), defaults);
  assert.equal(result.values.genre, defaults.genre);
  assert.equal(result.values.narrative_pov, defaults.narrative_pov);
  assert.equal(result.values.target_word_count, '6000-8000');
  const changedMode = { ...project(), mode: 'serial' };
  assert.deepEqual(applyAssistantConfiguration(changedMode, entry(), defaults).values, changedMode.values);
  const locked = entry(); locked.configuration_base!.has_story_facts = true;
  assert.equal(applyAssistantConfiguration(project(), locked, defaults).values.genre, defaults.genre);
  const normal = entry(); normal.purpose = 'general';
  const current = project();
  assert.equal(applyAssistantConfiguration(current, normal, defaults), current);
});

test('world direction is forwarded as planning context without becoming a formal archive', () => {
  assert.equal(premiseWithWorldDirection({ premise: '困在楼内', world_direction: '停电，感染通过伤口传播' }),
    '困在楼内\n\n世界观方向（规划草稿）：\n停电，感染通过伤口传播');
  assert.equal(premiseWithWorldDirection({ premise: '困在楼内' }), '困在楼内');
});
