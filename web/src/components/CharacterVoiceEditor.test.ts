import assert from 'node:assert/strict';
import test from 'node:test';
import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { Window } from 'happy-dom';
import CharacterVoiceEditor from './CharacterVoiceEditor';
import HumanwareScoreCard from './HumanwareScoreCard';

test('voice editor encodes full Windows workspace in queries and saves with workflow identity', async () => {
  const window = new Window();
  Object.assign(globalThis, { window, document: window.document, IS_REACT_ACT_ENVIRONMENT: true });
  const original = globalThis.fetch;
  const calls: Array<{ url: string; body?: Record<string, string> }> = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), body: options?.body ? JSON.parse(String(options.body)) : undefined });
    if (String(url).includes('/status')) return Response.json({ voice_file_exists: true, profiles_file_exists: true, character_count: 1 });
    if (options?.method === 'POST') return Response.json({ detail: '本书正在处理，请稍后保存' }, { status: 409 });
    return Response.json({ status: 'success', content: 'existing voice' });
  };
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  const workspace = 'C:\\Library\\有 空格\\books\\example';
  try {
    await act(async () => { root.render(React.createElement(CharacterVoiceEditor, { workspaceId: workspace, workflowId: 'custom-character' } as never)); });
    const read = calls.find(call => call.url.includes('/voice-file'))!;
    const query = new URL(read.url, 'http://localhost');
    assert.equal(query.pathname, '/api/humanware/voice-file');
    assert.equal(query.searchParams.get('workspace'), workspace);
    assert.equal(query.searchParams.get('workflow_id'), 'custom-character');
    const generate = [...host.querySelectorAll('button')].find(button => button.textContent?.includes('模板'));
    assert.ok(generate?.disabled, 'existing voice cannot be regenerated');
    const save = [...host.querySelectorAll('button')].find(button => button.textContent?.trim() === '保存')!;
    await act(async () => { save.click(); });
    const mutation = calls.find(call => call.body)!;
    assert.equal(mutation.url, '/api/humanware/voice-file');
    assert.deepEqual(mutation.body, { workflow_id: 'custom-character', workspace, content: 'existing voice' });
    assert.ok(host.textContent?.includes('本书正在处理，请稍后保存'));
  } finally {
    await act(async () => root.unmount());
    globalThis.fetch = original;
    window.happyDOM.abort();
  }
});

test('unsupported humanware capability renders no invented score', () => {
  const html = renderToStaticMarkup(React.createElement(HumanwareScoreCard, {
    score: { supported: false, message: '请使用模拟读者报告' },
  } as never));
  assert.ok(html.includes('请使用模拟读者报告'));
  assert.ok(!html.includes('/ 100'));
});
