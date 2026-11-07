import {request} from './http-client';

export function automationState<T extends {autoNext?: boolean; autoController?: string; autoArmed?: boolean}>(state: T): T {
  return {...state, autoNext: state.autoController === 'server-v1' && state.autoNext === true,
    autoArmed: state.autoController === 'server-v1' && state.autoArmed === true};
}

export function readAutomation<T>(workflowId: string, workspace: string) {
  return request<{state: T}>(`/novel-console/automation?${new URLSearchParams({workflow_id: workflowId, workspace})}`);
}

function comparableState(state: unknown): string {
  const intent = new Set(['_revision','autoController','autoNext','autoArmed','autoPauseReason','persisted','automaticRecovery','automaticCheckpoint']);
  const sort = (value: unknown, root=false): unknown => {
    if(Array.isArray(value)) return value.map(item=>sort(item));
    if(value && typeof value==='object') return Object.fromEntries(Object.entries(value)
      .filter(([key,value])=>value!==undefined && !(root && intent.has(key)))
      .sort(([a],[b])=>a.localeCompare(b)).map(([key,value])=>[key,sort(value)]));
    return value;
  };
  return JSON.stringify(sort(state,true));
}

export async function controlAutomation<T>(action: 'start' | 'stop', workflowId: string, workspace: string, state: T) {
  const submit = (value:T) => request<{state: T; revision: number; workspace: string}>(`/novel-console/automation/${action}`, {
    method: 'POST', body: JSON.stringify({workflow_id: workflowId, workspace, state:value}),
  });
  try { return await submit(state); }
  catch(error) {
    if(action!=='start' || !String(error).includes('API Error 409:')) throw error;
    const {state:latest}=await readAutomation<T & {_revision?:number;autoArmed?:boolean}>(workflowId,workspace);
    // Only an identical autosave may advance the revision. Divergent edits,
    // another running controller, and another conflict remain explicit errors.
    if(latest.autoArmed || !Number.isInteger(latest._revision)
      || comparableState(latest)!==comparableState(state)) throw error;
    return submit({...state,_revision:latest._revision});
  }
}
