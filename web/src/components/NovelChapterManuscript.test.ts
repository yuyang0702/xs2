import assert from 'node:assert/strict';
import test from 'node:test';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Window } from 'happy-dom';
import NovelChapterManuscript from './NovelChapterManuscript';
import { setNovelResources } from '../lib/novel-resources';

Object.assign(globalThis, { React });

test('chapter reading fetches only the manuscript and exposes audit and polish actions', async () => {
  const window = new Window();
  Object.assign(globalThis, { window, document: window.document, IS_REACT_ACT_ENVIRONMENT: true });
  setNovelResources({mvp: 'chapter-workflow'});
  const original = globalThis.fetch;
  const requests: URL[] = [];
  globalThis.fetch = async input => {
    requests.push(new URL(String(input), 'http://localhost'));
    return Response.json({content:'雨打在船舷。'});
  };
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const actions: string[] = [];
  try {
    await act(async () => {
      root.render(React.createElement(NovelChapterManuscript, {
        workspace:'books/story', chapter:'0002', opening:false,
        onBack:() => actions.push('back'), onAudit:() => actions.push('audit'), onPolish:() => actions.push('polish'),
      }));
    });
    assert.equal(requests.length, 1);
    assert.equal(requests[0].searchParams.get('workflow_id'), 'chapter-workflow');
    assert.equal(requests[0].searchParams.get('path'), 'story/0002/chapter.md');
    assert.match(host.textContent || '', /雨打在船舷。/);
    assert.doesNotMatch(host.textContent || '', /读者评估|评分/);
    for (const label of ['审核档案', '润色本章']) {
      await act(async () => { [...host.querySelectorAll('button')].find(button => button.textContent === label)!.click(); });
    }
    assert.deepEqual(actions, ['audit', 'polish']);
    assert.equal(requests.length, 1);
  } finally {
    await act(async () => root.unmount());
    globalThis.fetch = original;
    setNovelResources({});
    window.happyDOM.abort();
  }
});
