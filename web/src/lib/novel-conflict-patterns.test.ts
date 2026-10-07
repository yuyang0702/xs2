import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import NovelConflictPatterns from '../components/NovelConflictPatterns';

test('writing selection reads foreshadowing as text, list or structured evidence without crashing', () => {
  for (const foreshadowing of ['先看到异常痕迹', ['先看到异常痕迹'], [{evidence: '先看到异常痕迹'}]]) {
    const html = renderToStaticMarkup(createElement(NovelConflictPatterns, {patterns: [{goal:'寻找出路', obstacle:'通道被阻', resolution:'求助', foreshadowing}]}));
    for (const text of ['寻找出路','通道被阻','求助','先看到异常痕迹']) assert.ok(html.includes(text));
    assert.ok(!html.includes('[object Object]'));
    assert.ok(!html.includes('undefined'));
  }
});
