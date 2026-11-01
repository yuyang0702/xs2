import assert from 'node:assert/strict';
import test from 'node:test';
import {automationState} from './novel-automation';

test('legacy browser auto flags never arm background production on upgrade', () => {
  assert.equal(automationState({autoNext: true, autoArmed: true}).autoNext, false);
  assert.equal(automationState({autoNext: true, autoArmed: true}).autoArmed, false);
  assert.deepEqual(automationState({autoNext: true, autoArmed: true, autoController: 'server-v1'}),
    {autoNext: true, autoArmed: true, autoController: 'server-v1'});
});
