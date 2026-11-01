import assert from 'node:assert/strict';
import test from 'node:test';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Window } from 'happy-dom';
import NovelResourceGate from './NovelResourceGate';

const required = ['reference-distillation', 'novel-advisor', 'style-compatibility-advisor',
  'adopt-reference', 'build', 'character', 'story-plan', 'outline', 'mvp', 'polish',
  'reader-sim', 'post-hoc', 'export'];

test('incomplete resources keep children unmounted and allow retry with renamed identities', async () => {
  const window = new Window();
  Object.assign(globalThis, { window, document: window.document, IS_REACT_ACT_ENVIRONMENT: true });
  const original = globalThis.fetch;
  let response: unknown = { workflows: { build: 'renamed-build' } };
  globalThis.fetch = async () => Response.json(response);
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  let mounts = 0;
  function Child() { mounts++; return React.createElement('p', {}, 'workbench mounted'); }
  try {
    await act(async () => { root.render(React.createElement(NovelResourceGate, { children: React.createElement(Child) })); });
    assert.equal(mounts, 0);
    assert.ok(host.textContent?.includes('novel-advisor'));
    assert.ok(host.textContent?.includes('重新检查插件'));
    response = { workflows: Object.fromEntries(required.map(id => [id, 'renamed-' + id])) };
    await act(async () => { host.querySelector('button')!.click(); });
    assert.equal(mounts, 1);
    assert.ok(host.textContent?.includes('workbench mounted'));
  } finally {
    await act(async () => root.unmount());
    globalThis.fetch = original;
    window.happyDOM.abort();
  }
});
