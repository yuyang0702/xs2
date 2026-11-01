import {test} from 'node:test';
import assert from 'node:assert/strict';
import {setNovelResources, novelWorkflowId, novelStageId} from './novel-resources';

test('workbench uses installed resource identities and cannot invent missing workflows', () => {
  setNovelResources({build: 'my-book-build', mvp: 'my-book-write'});
  assert.equal(novelWorkflowId('mvp'), 'my-book-write');
  assert.equal(novelStageId('my-book-write'), 'mvp');
  assert.equal(novelStageId('other-mvp'), undefined);
  assert.throws(() => novelWorkflowId('polish'), /插件/);
  setNovelResources({});
  assert.throws(() => novelWorkflowId('build'), /插件/);
});
