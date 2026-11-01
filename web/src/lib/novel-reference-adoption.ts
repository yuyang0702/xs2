import {request} from './http-client';

export type ReferenceAdoptionJob = {
  id: string; request_id?: string; entry_id?: string; advisor_entry_id?:string;
  status: 'checking' | 'applied' | 'no_match' | 'review_required' | 'failed';
  message?: string; summary?: string; error?: string;
  selected_references?: Array<{library_id:string;kind:string;candidate_id?:string;choice_id?:string;title?:string;name?:string;reason?:string;adaptation?:string}>;
  skipped?: Array<Record<string, unknown>>;
  voice_status?: 'adapted' | 'pending_characters' | 'not_requested';
  voice_adaptations?: Array<Record<string,unknown>>;
};
export type ReferenceAdoptionPayload = {workflow_id:string;workspace:string;entry_id:string;request_id:string;expected_revision?:number;model_override?:string};
type Options = {signal?:AbortSignal;pollIntervalMs?:number;onJob?:(job:ReferenceAdoptionJob)=>void};
export class ReferenceAdoptionRejectedError extends Error {}
export async function recoverReferenceAdoption(job:ReferenceAdoptionJob,workflowId:string,workspace:string,options:Options = {}):Promise<ReferenceAdoptionJob|null> {
  try {
    return await followReferenceAdoption({...job,status:'checking'},workflowId,workspace,options);
  } catch (error) {
    if (!(error instanceof Error) || !/^API Error 404:/.test(error.message)) throw error;
    return restoreReferenceAdoption(workflowId,workspace,options);
  }
}

function waitForPoll(delay:number,signal?:AbortSignal) {
  signal?.throwIfAborted();
  return new Promise<void>((resolve,reject)=>{
    const abort=()=>{clearTimeout(timer);reject(signal?.reason || new DOMException('Observation cancelled','AbortError'));};
    const timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve();},delay);
    signal?.addEventListener('abort',abort,{once:true});
  });
}

export async function followReferenceAdoption(job:ReferenceAdoptionJob,workflowId:string,workspace:string,options:Options = {}):Promise<ReferenceAdoptionJob> {
  let current=job;
  for (;;) {
    current={...current,entry_id:current.entry_id || current.advisor_entry_id};
    options.signal?.throwIfAborted();
    options.onJob?.(current);
    options.signal?.throwIfAborted();
    if (current.status !== 'checking') return current;
    await waitForPoll(options.pollIntervalMs ?? 2000,options.signal);
    const query=new URLSearchParams({workflow_id:workflowId,workspace,request_id:current.request_id || current.id});
    const result=await request<{job:ReferenceAdoptionJob}>(`/novel-console/reference-adoption?${query}`,{signal:options.signal});
    current=result.job;
  }
}

export async function startReferenceAdoption(payload:ReferenceAdoptionPayload,options:Options = {}):Promise<ReferenceAdoptionJob> {
  let result:{job:ReferenceAdoptionJob};
  try {
    result=await request<{job:ReferenceAdoptionJob}>('/novel-console/reference-adoption',{
      method:'POST',body:JSON.stringify(payload),signal:options.signal,
    });
  } catch (error) {
    const rejected=error instanceof Error && error.message.match(/^API Error 4\d\d: ([\s\S]+)$/);
    if (!rejected) throw error;
    let message=rejected[1];
    try {const body=JSON.parse(message);if (typeof body.detail === 'string') message=body.detail;} catch {/* Preserve a plain-text server response. */}
    throw new ReferenceAdoptionRejectedError(message);
  }
  return followReferenceAdoption(result.job,payload.workflow_id,payload.workspace,options);
}

export async function restoreReferenceAdoption(workflowId:string,workspace:string,options:Options = {}):Promise<ReferenceAdoptionJob|null> {
  const query=new URLSearchParams({workflow_id:workflowId,workspace});
  const result=await request<{job:ReferenceAdoptionJob|null}>(`/novel-console/reference-adoption/latest?${query}`,{signal:options.signal});
  return result.job ? followReferenceAdoption(result.job,workflowId,workspace,options) : null;
}

export function referenceAdoptionOutcome(job:ReferenceAdoptionJob):{success:boolean;message:string} {
  const count=job.selected_references?.length || 0;
  if (job.status === 'applied') {
    if (!count) return {success:false,message:'后台未返回已保存的参考写法，请重新核对采用结果。'};
    const voices=job.voice_status === 'pending_characters' ? '当前已采用抽象对话规则。先创建角色，再次检查可适配具体人物。'
      : job.voice_status === 'adapted' ? `已适配 ${job.voice_adaptations?.length || 0} 个本书角色的声音。` : '';
    return {success:true,message:`已检查兼容并保存 ${count} 条本书参考写法。${voices}${job.message || job.summary || ''}`};
  }
  const fallback={checking:'正在核对推荐来源、兼容性与本书角色声音，可切换页面后回来查看。',no_match:'未确认可采用的来源，请查看来源提示或手动选择参考写法。',review_required:'部分建议需要你确认，请查看适配说明后手动选择。',failed:'本次采用未完成，请查看原因后再重试。'};
  return {success:false,message:job.message || job.error || job.summary || fallback[job.status]};
}

type Selection = {selected:string[];selectedStyles?:string[];selectedConflicts?:string[];libraryRefs:string[]};
type AdoptedWriting = {selected_candidate_ids:string[];selected_style_ids:string[];selected_conflict_ids:string[]};
export function mergeReferenceAdoption<T extends Selection>(project:T,job:ReferenceAdoptionJob,adopted:AdoptedWriting):T {
  if (!referenceAdoptionOutcome(job).success) return project;
  const unique=(values:string[])=>[...new Set(values)];
  const selected=unique([...project.selected,...adopted.selected_candidate_ids]);
  const selectedStyles=unique([...(project.selectedStyles || []),...adopted.selected_style_ids]);
  const selectedConflicts=unique([...(project.selectedConflicts || []),...adopted.selected_conflict_ids]);
  const libraryRefs=unique([...project.libraryRefs,...(job.selected_references || []).map(item=>item.library_id).filter(Boolean)]);
  if (JSON.stringify([selected,selectedStyles,selectedConflicts,libraryRefs]) === JSON.stringify([project.selected,project.selectedStyles || [],project.selectedConflicts || [],project.libraryRefs])) return project;
  return {...project,selected,selectedStyles,selectedConflicts,libraryRefs};
}
