import test from 'node:test';
import assert from 'node:assert/strict';
import type { NovelAssistantEntry } from './api';
import { adoptNovelAdvisor } from './novel-advisor';
import { applyAssistantConfiguration, premiseWithWorldDirection } from './novel-assistant-configuration';

const defaults = {genre:'都市情感',premise:'',target_word_count:'3000-4000'};
const project = () => ({mode:'serial',values:{...defaults},refs:{} as Record<string,unknown>,completed:[] as string[],
  index:0,stageId:'novel-advisor',directionConfirmed:false,advisorAccepted:false,autoNext:false,
  selected:['existing-writing'],selectedStyles:['existing-style'],selectedConflicts:['existing-conflict']});
const entry = ():NovelAssistantEntry => ({id:'proposal',question:'首次设定',stage:'小说顾问',source:'llm',status:'completed',purpose:'advisor',created_at:'now',
  reply:'判断',configuration_base:{mode:'serial',values:{...defaults},advisor_brief:'完整原始设定：潜伏期72-120小时\n补充：保留三派'},
  suggestions:[{key:'premise',label:'创意',value:'救援引发信任危机',reason:'明确主线'},
    {key:'genre',label:'题材',value:'末日悬疑',reason:'设定匹配'}],
  advisor_sections:{direction:'救援开局',hook:'聚集悖论',writing:'限定视角',risks:'澄清8人与12人密度的区别'}});
const stages = [{id:'novel-advisor'},{id:'build'},{id:'mvp'},{id:'export'}];

test('discussion is read-only; explicit adoption fills a draft and preserves full original rules and selected writing',()=>{
  const current=project(), proposal=entry();
  assert.equal(applyAssistantConfiguration(current,proposal,defaults),current);
  const result=adoptNovelAdvisor(current,proposal,defaults,stages);
  assert.equal(result.success,true);
  assert.equal(result.project.stageId,'build');
  assert.equal(result.project.directionConfirmed,true);
  assert.deepEqual(result.project.selected,current.selected);
  assert.deepEqual(result.project.selectedStyles,current.selectedStyles);
  assert.deepEqual(result.project.selectedConflicts,current.selectedConflicts);
  const context=premiseWithWorldDirection(result.project.values);
  assert.match(context,/72-120小时/);
  assert.match(context,/澄清8人与12人密度/);
  assert.equal(adoptNovelAdvisor(result.project,proposal,defaults,stages).success,false);
});

test('adoption cannot restart an existing book or overwrite a manually chosen premise',()=>{
  const current={...project(),values:{...defaults,premise:'本书已有创意'},refs:{build:{},mvp:{}},completed:['build']};
  const proposal=entry(); proposal.configuration_base!.values.premise='本书已有创意';
  const result=adoptNovelAdvisor(current,proposal,defaults,stages,true);
  assert.equal(result.success,true);
  assert.equal(result.project.stageId,'mvp');
  assert.equal(result.project.values.premise,'本书已有创意');
  assert.deepEqual(result.project.refs,current.refs);
});

test('incomplete, incompatible or empty plans do not move the workbench',()=>{
  const current=project();
  for (const proposal of [{...entry(),status:'running' as const},
    {...entry(),configuration_base:{mode:'short',values:defaults}}, {...entry(),suggestions:[]}]) {
    const result=adoptNovelAdvisor(current,proposal,defaults,stages);
    assert.equal(result.success,false);
    assert.equal(result.project,current);
  }
});
