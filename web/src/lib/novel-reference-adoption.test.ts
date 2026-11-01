import assert from 'node:assert/strict';
import {test,type TestContext} from 'node:test';
import React, {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import NovelReferenceAdoptionStatus from '../components/NovelReferenceAdoptionStatus';
import NovelAdvisorConversation from '../components/NovelAdvisorConversation';
import type {NovelAssistantEntry} from './api';
Object.assign(globalThis, {React});
import {
  startReferenceAdoption, restoreReferenceAdoption, recoverReferenceAdoption, referenceAdoptionOutcome,
  mergeReferenceAdoption, ReferenceAdoptionRejectedError, type ReferenceAdoptionJob,
} from './novel-reference-adoption';

const checking: ReferenceAdoptionJob = {id:'request-1', advisor_entry_id:'advisor-7', status:'checking'};
const applied: ReferenceAdoptionJob = {...checking, status:'applied', selected_references:[
  {library_id:'book-b', kind:'mechanism', candidate_id:'b-mechanism'},
  {library_id:'book-a', kind:'style', choice_id:'a-style'},
], voice_status:'pending_characters'};
const payload = {workflow_id:'novel-build',workspace:'books/中文',entry_id:'advisor-7',request_id:'request-1',expected_revision:4};

function responses(t: TestContext, values: Array<unknown | Error>, seen: Array<{url:string;init?:RequestInit}> = []) {
  t.mock.method(globalThis, 'fetch', async (url: string | URL | Request, init?: RequestInit) => {
    seen.push({url:String(url),init});
    const value = values.shift();
    if (value instanceof Error) throw value;
    assert.notEqual(value, undefined, 'unexpected extra request');
    return new Response(JSON.stringify(value), {status:200});
  });
}

test('adoption waits for the saved result and sends the exact advisor source once', async t => {
  const seen: Array<{url:string;init?:RequestInit}> = [], progress: string[] = [];
  responses(t,[{job:checking},{job:checking},{job:applied}],seen);
  const result = await startReferenceAdoption(payload,{pollIntervalMs:1,onJob:job=>progress.push(job.status)});
  assert.equal(result.status,'applied');
  assert.equal(result.entry_id,'advisor-7');
  assert.deepEqual(progress,['checking','checking','applied']);
  assert.deepEqual(JSON.parse(String(seen[0].init?.body)),payload);
  assert.equal(seen.filter(call=>call.init?.method==='POST').length,1);
  const poll = new URL(seen[1].url,'http://localhost');
  assert.equal(poll.searchParams.get('request_id'),'request-1');
  assert.equal(poll.searchParams.get('workspace'),'books/中文');
});

test('a one-check model is sent only with the adoption request', async t => {
  const seen: Array<{url:string;init?:RequestInit}> = [];
  responses(t,[{job:applied}],seen);
  await startReferenceAdoption({...payload,model_override:'provider:backup'});
  assert.equal(JSON.parse(String(seen[0].init?.body)).model_override,'provider:backup');
  assert.equal(seen.length,1);
});

test('no source match stays unsuccessful and does not start a replacement job',async t=>{
  const seen: Array<{url:string;init?:RequestInit}> = [];
  responses(t,[{job:{...checking,status:'no_match',message:'来源未确认'}}],seen);
  const outcome=referenceAdoptionOutcome(await startReferenceAdoption(payload));
  assert.equal(outcome.success,false);
  assert.match(outcome.message,/来源未确认/);
  assert.equal(seen.length,1);
});

test('an empty applied receipt never claims successful adoption',()=>{
  assert.equal(referenceAdoptionOutcome({...checking,status:'applied',selected_references:[]}).success,false);
});

test('the plugin review explanation is visible even when it is supplied as summary',()=>{
  const result=referenceAdoptionOutcome({...checking,status:'review_required',summary:'两个来源都叫短句节奏，请手动确认来源'});
  assert.equal(result.success,false);
  assert.match(result.message,/两个来源都叫短句节奏/);
});

test('network failure after acceptance retains the same operation for later recovery',async t=>{
  const seen: Array<{url:string;init?:RequestInit}> = [];
  responses(t,[{job:checking},new Error('connection lost')],seen);
  await assert.rejects(startReferenceAdoption(payload,{pollIntervalMs:1}),/connection lost/);
  assert.equal(seen.length,2);
  assert.equal(seen.filter(call=>call.init?.method==='POST').length,1);
});

test('a server rejection exposes its reason and allows an explicit retry without implying saved work',async t=>{
  t.mock.method(console,'error',()=>{});
  t.mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({detail:'请先暂停后台自动创作'}),{status:409}));
  await assert.rejects(startReferenceAdoption(payload),error=>error instanceof ReferenceAdoptionRejectedError && /请先暂停后台自动创作/.test(error.message));
});

test('remount restores and polls an existing operation without another POST',async t=>{
  const seen: Array<{url:string;init?:RequestInit}> = [];
  responses(t,[{job:checking},{job:applied}],seen);
  assert.equal((await restoreReferenceAdoption(payload.workflow_id,payload.workspace,{pollIntervalMs:1}))?.status,'applied');
  assert.ok(seen[0].url.includes('/reference-adoption/latest?'));
  assert.equal(seen.filter(call=>call.init?.method==='POST').length,0);
});

test('a missing uncertain request is checked against latest before allowing another explicit adoption',async t=>{
  t.mock.method(console,'error',()=>{});
  const seen:string[]=[];
  t.mock.method(globalThis,'fetch',async(url:string|URL|Request)=>{
    seen.push(String(url));
    return seen.length === 1 ? new Response('not found',{status:404}) : new Response('{"job":null}',{status:200});
  });
  assert.equal(await recoverReferenceAdoption(checking,payload.workflow_id,payload.workspace,{pollIntervalMs:1}),null);
  assert.equal(seen.length,2);
  assert.ok(seen[1].includes('/reference-adoption/latest?'));
});

test('cancelling page observation stops polling without cancelling the server operation',async t=>{
  const controller=new AbortController();
  const seen: Array<{url:string;init?:RequestInit}> = [];
  responses(t,[{job:checking}],seen);
  await assert.rejects(startReferenceAdoption(payload,{signal:controller.signal,pollIntervalMs:100,onJob:()=>controller.abort()}),{name:'AbortError'});
  assert.equal(seen.length,1);
});

test('saved selections refresh without changing book settings or production progress',()=>{
  const current={selected:['draft'],selectedStyles:[],selectedConflicts:['old-conflict'],libraryRefs:['old-library'],
    values:{premise:'手动创意'},refs:{mvp:{task_id:'chapter-8'}},index:8,stageId:'mvp'};
  const result=mergeReferenceAdoption(current,applied,{selected_candidate_ids:['b-mechanism'],selected_style_ids:['a-style'],selected_conflict_ids:['old-conflict']});
  assert.deepEqual(result.selected,['draft','b-mechanism']);
  assert.deepEqual(result.selectedStyles,['a-style']);
  assert.deepEqual(result.libraryRefs,['old-library','book-b','book-a']);
  assert.equal(result.values,current.values);
  assert.equal(result.refs,current.refs);
  assert.equal(result.index,8);
  assert.equal(result.stageId,'mvp');
});

test('voice receipts distinguish real adaptations from waiting for book characters',()=>{
  assert.match(referenceAdoptionOutcome(applied).message,/角色.*创建|创建.*角色/);
  const outcome=referenceAdoptionOutcome({...applied,voice_status:'adapted',voice_adaptations:[{character_id:'hero',name:'本书主角'}]});
  assert.equal(outcome.success,true);
  assert.match(outcome.message,/1.*角色|角色.*1/);
});

test('the receipt shows saved writing, pending voices and skipped recommendations separately',()=>{
  const html=renderToStaticMarkup(createElement(NovelReferenceAdoptionStatus,{job:{...applied,skipped:[{title:'不兼容的推荐',reason:'与本书视角冲突'}]}}));
  assert.match(html,/保存 2 条/);
  assert.match(html,/先创建角色/);
  assert.match(html,/不兼容的推荐/);
  assert.match(html,/与本书视角冲突/);
});

test('the receipt exposes each book character adaptation and the profile evidence behind it',()=>{
  const html=renderToStaticMarkup(createElement(NovelReferenceAdoptionStatus,{job:{...applied,voice_status:'adapted',voice_adaptations:[
    {character_name:'许青',guidance:'面对妹妹先问身体，再谈证据。',profile_evidence:'对妹妹温和，对矿长克制质疑'},
    {character_name:'许宁',guidance:'对姐姐用反问掩饰害怕。',profile_evidence:'常以反问掩饰恐惧'},
  ]}}));
  for (const text of ['许青','许宁','面对妹妹先问身体','对姐姐用反问','对妹妹温和','常以反问掩饰恐惧']) assert.ok(html.includes(text),text);
  assert.ok(!html.includes('[object Object]'));
});

test('an unconfirmed connection shows recovery instead of successful adoption',()=>{
  const html=renderToStaticMarkup(createElement(NovelReferenceAdoptionStatus,{job:checking,error:'连接中断，结果尚未确认',onRefresh:()=>{}}));
  assert.match(html,/结果尚未确认/);
  assert.match(html,/重新核对后台结果/);
  assert.ok(!html.includes('已检查兼容并保存'));
});

test('the advisor offers compatibility checking for style recommendations and reflects existing adoption',()=>{
  const entry:NovelAssistantEntry={id:'advisor-7',question:'创意',reply:'建议',status:'completed',purpose:'advisor',source:'llm',stage:'小说顾问',created_at:'now',advisor_sections:{direction:'方向',hook:'看点',writing:'写法',risks:'风险',style_recommendations:{adopted_styles:[{style:'冷静克制',priority:'高',reason:'匹配',usage_in_story:'叙述'}],avoid_styles:[]}}};
  const props={question:'',onQuestion:()=>{},onAsk:()=>{},entries:[entry],busy:false,loading:false,feedback:'',now:0,onAdopt:()=>({success:true,message:''}),onRead:()=>{},workflowBusy:false,established:true,hasReference:true,adoptedCount:2,onQuickAdopt:async()=>({success:true,message:''})};
  const html=renderToStaticMarkup(createElement(NovelAdvisorConversation,props));
  assert.match(html,/检查兼容并采用/);
  assert.match(html,/基于已采用写法优化/);
  const recheck=renderToStaticMarkup(createElement(NovelAdvisorConversation,{...props,referenceAdoptionApplied:true}));
  const button=[...recheck.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)].find(match=>match[2].includes('重新检查兼容与人物适配'));
  assert.ok(button,'a saved result must allow explicit rechecking after characters are created');
  assert.ok(!/\sdisabled(?:=|\s|$)/.test(button[1]));
});

test('a later discussion without structured references can recheck an earlier saved recommendation',()=>{
  const earlier:NovelAssistantEntry={id:'earlier-advisor',question:'有可复核来源的上一轮',reply:'先核对再采用',status:'completed',purpose:'advisor',source:'llm',stage:'小说顾问',created_at:'before',advisor_sections:{direction:'本书方向',hook:'人物选择',writing:'保持有限视角',risks:'先确认兼容',style_recommendations:{adopted_styles:[{library_id:'source-1',choice_id:'style-1',style:'有限视角',priority:'HIGH',reason:'待核对',usage_in_story:'适配本书叙述'}]}}};
  const latest:NovelAssistantEntry={...earlier,id:'latest-advisor',question:'只补充人物讨论',advisor_sections:{direction:'保留现有角色事实',hook:'保持看点',writing:'保持写法方向',risks:'保留边界'}};
  const html=renderToStaticMarkup(createElement(NovelAdvisorConversation,{
    question:'',onQuestion:()=>{},onAsk:()=>{},entries:[earlier,latest],busy:false,loading:false,
    feedback:'',now:0,onAdopt:()=>({success:true,message:''}),onRead:()=>{},workflowBusy:false,
    established:true,hasReference:false,adoptedCount:0,librarySize:1,onQuickAdopt:async()=>({success:true,message:''}),
  }));
  assert.match(html,/本轮未提供可检查的参考清单/);
  assert.match(html,/检查兼容并采用本轮推荐/);
  assert.match(html,/按本书当前设置和人物档案重新检查/);
});

test('one-check model selection explicitly leaves saved defaults unchanged',()=>{
  const html=renderToStaticMarkup(createElement(NovelAdvisorConversation,{
    question:'',onQuestion:()=>{},onAsk:()=>{},entries:[],busy:false,loading:false,
    feedback:'',now:0,onAdopt:()=>({success:true,message:''}),onRead:()=>{},workflowBusy:false,
    established:true,hasReference:false,onQuickAdopt:async()=>({success:true,message:''}),
    referenceModels:[{value:'provider:backup',label:'备用模型'}],referenceModel:'provider:backup',onReferenceModelChange:()=>{},
  }));
  assert.match(html,/本次兼容检查模型/);
  assert.match(html,/不保存到作品或工作流默认配置/);
  assert.match(html,/<option value="provider:backup" selected="">备用模型<\/option>/);
});
