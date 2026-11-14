import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import React, { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import NovelAdvisorConversation from '../components/NovelAdvisorConversation';
import type { NovelAssistantEntry } from './api';

Object.assign(globalThis, {React});

test('the adviser shows the blind-read favorite and the feasible recommendation separately', () => {
  const candidates = ['门铃', '船钟'].map(title => ({id: title, title, genre: '短篇', opening: `她听见${title}响了。`,
    premise: '故事梗概', choice: '她要开门', cost: '来不及离开', middle: '她去认来客', ending: '来客把旧事说清'}));
  const entry: NovelAssistantEntry = {id: 'advisor', purpose: 'advisor', advisor_task: 'topic_selection',
    source: 'llm', status: 'completed', question: '选题', reply: '综合推荐《船钟》。', stage: '小说顾问', created_at: 'now',
    topic_selection: {target_words: '10000', candidates, recommended_id: '船钟',
      ranking: candidates.map(({id}) => ({id, excerpt: '她听见', reason: '来客很可疑', question: '是谁来了？'})),
      assessments: candidates.map(({id}) => ({id, verdict: id === '门铃' ? 'too_thin' : 'fits',
        reason: '中段须继续行动', development: '她去认来客', risk: '减少旧事回述'}))}};
  const html = renderToStaticMarkup(createElement(NovelAdvisorConversation, {question: '', onQuestion: () => {},
    onAsk: () => {}, entries: [entry], busy: false, loading: false, feedback: '', now: 0,
    onAdopt: () => ({success: true, message: ''}), onRead: () => {}, workflowBusy: false, established: false,
    hasReference: false, shortStory: true}));
  assert.match(html, /门铃[\s\S]*盲读首选[\s\S]*她听见门铃响了。/);
  assert.match(html, /船钟[\s\S]*综合推荐[\s\S]*她听见船钟响了。/);
  assert.match(html, /中段支撑不足/);
  assert.match(html, /继续讨论这个题材/);
  assert.doesNotMatch(html, /采用方案，填写设置并继续/);
});
