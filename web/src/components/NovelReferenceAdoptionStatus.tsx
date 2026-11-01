import {referenceAdoptionOutcome,type ReferenceAdoptionJob} from '../lib/novel-reference-adoption';
import {referenceText} from './NovelReferenceChoice';

export default function NovelReferenceAdoptionStatus({job,error,restoring,onRefresh}:{job:ReferenceAdoptionJob|null;error?:string;restoring?:boolean;onRefresh?:()=>void}) {
  if (!job && !error && !restoring) return null;
  return <section aria-label="参考写法采用状态" aria-live="polite" className="mt-4 space-y-3 rounded-xl border border-primary/25 bg-primary/5 p-4 text-sm leading-7">
    <p className="font-medium">本书参考写法 · {restoring ? '正在恢复后台结果' : job?.status === 'checking' ? '正在检查兼容' : job?.status === 'applied' && referenceAdoptionOutcome(job).success ? '已保存' : '需要查看结果'}</p>
    {job && <p role="status">{referenceAdoptionOutcome(job).message}</p>}
    {!!job?.selected_references?.length && job.status === 'applied' && <details><summary className="cursor-pointer">查看已采用写法与适配说明（{job.selected_references.length}）</summary><ul className="mt-2 space-y-3">{job.selected_references.map((item,index)=><li key={index}><p className="font-medium">{item.name || item.title || '参考写法'}</p>{item.reason && <p className="text-muted-foreground">{item.reason}</p>}{item.adaptation && <p className="whitespace-pre-wrap">{item.adaptation}</p>}</li>)}</ul></details>}
    {!!job?.skipped?.length && <details><summary className="cursor-pointer">查看未采用的建议（{job.skipped.length}）</summary><ul className="mt-2 space-y-2">{job.skipped.map((item,index)=><li key={index}>{referenceText(item.name || item.title || item.recommendation) || '本次建议'}：{referenceText(item.reason || item.message) || '请手动确认来源与适配。'}</li>)}</ul></details>}
    {!!job?.voice_adaptations?.length && job.status === 'applied' && <details><summary className="cursor-pointer">查看本书角色声音适配（{job.voice_adaptations.length}）</summary><div className="mt-3 space-y-4">{job.voice_adaptations.map((voice,index)=><article key={index}><p className="font-medium">{referenceText(voice.character_name) || '本书角色'}</p><p className="whitespace-pre-wrap">{referenceText(voice.guidance)}</p>{referenceText(voice.profile_evidence) && <details className="mt-2 text-muted-foreground"><summary className="cursor-pointer">人物档案依据</summary><p className="whitespace-pre-wrap">{referenceText(voice.profile_evidence)}</p></details>}</article>)}</div></details>}
    {error && <p role="alert" className="text-warning">{error}</p>}
    {error && onRefresh && <button onClick={onRefresh} disabled={restoring} className="rounded-lg border border-border px-3 py-2 text-xs disabled:opacity-50">重新核对后台结果</button>}
  </section>;
}
