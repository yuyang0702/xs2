import {request} from './http-client';

export function automationState<T extends {autoNext?: boolean; autoController?: string; autoArmed?: boolean}>(state: T): T {
  return {...state, autoNext: state.autoController === 'server-v1' && state.autoNext === true,
    autoArmed: state.autoController === 'server-v1' && state.autoArmed === true};
}

export function readAutomation<T>(workflowId: string, workspace: string) {
  return request<{state: T}>(`/novel-console/automation?${new URLSearchParams({workflow_id: workflowId, workspace})}`);
}

export function controlAutomation<T>(action: 'start' | 'stop', workflowId: string, workspace: string, state: T) {
  return request<{state: T; revision: number; workspace: string}>(`/novel-console/automation/${action}`, {
    method: 'POST', body: JSON.stringify({workflow_id: workflowId, workspace, state}),
  });
}
