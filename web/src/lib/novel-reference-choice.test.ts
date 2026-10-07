import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import NovelReferenceChoice from '../components/NovelReferenceChoice';

test('conflict reading maps text/list/object to causal steps without exposing raw JSON', () => {
  for (const foreshadowing of ['门锁松动', ['门锁松动'], {hint:'门锁松动'}]) {
    const html=renderToStaticMarkup(createElement(NovelReferenceChoice,{choice:{choice_id:'one',kind:'conflict',title:'逃生链',requires_adaptation:true,transfer_guidance:'',goal:'离开楼道',foreshadowing,obstacle:'门被堵住',resolution:'另寻出口',cost:'失去补给',next_obstacle:'暴露位置',causal_link:'行动带来代价'}}));
    for(const text of ['提前埋下的隐患','门锁松动','尝试解决','另寻出口','付出代价','失去补给','为什么会递进'])assert.ok(html.includes(text));
    assert.ok(!html.includes('[object Object]'));assert.ok(!html.includes('source_start'));assert.ok(!html.includes('&quot;hint&quot;'));
  }
});
