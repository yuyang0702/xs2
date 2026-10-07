import { useRef, useState } from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';
import { applyNovelPlotPlan, type NovelAssistantEntry } from '../lib/api';

const labels = {goal:'本章目标',conflict:'阻力与利益关系',choice:'人物选择',turning_point:'转折',cost:'代价与后果',reveal:'信息变化',payoff:'期待与兑现',hook:'收束与后续',time_advance:'世界时间推进'};
export default function NovelPlotProposals({entry,workspace,workflowId,disabled=false,onApplied}: {entry:NovelAssistantEntry;workspace:string;workflowId:string;disabled?:boolean;onApplied:()=>void}) {
  const [selected,setSelected]=useState('');
  const [applying,setApplying]=useState(false);
  const [feedback,setFeedback]=useState('');
  const [localReceipts,setLocalReceipts]=useState<Record<string,boolean>>({});
  const guard=useRef(false);
  const options=entry.plot_options || [];
  const option=options.find(item=>item.id===selected);
  const apply=async()=>{
    if(!option || applying || disabled || guard.current)return;
    guard.current=true;setApplying(true);setFeedback('正在核对前文并采用方案…');
    try {
      const result=await applyNovelPlotPlan({workflow_id:workflowId,workspace,entry_id:entry.id,option_id:option.id});
      setLocalReceipts(current=>({...current,[option.id]:true}));
      setFeedback(`${result.already_applied?'此前已采用':'已采用'}「${result.title}」，已加入第 ${result.chapters.map(Number).join('、')} 章计划，后续创作会读取。`);
      setSelected('');onApplied();window.dispatchEvent(new CustomEvent('novel-artifacts-updated',{detail:{workspace}}));
    }catch(error){setFeedback(error instanceof Error?`未采用：${error.message}`:'采用失败，请重试。');}
    finally{guard.current=false;setApplying(false);}
  };
  if(!options.length)return null;
  return <section className="mt-5 space-y-3 border-t border-border pt-4"><h4 className="text-sm font-semibold">候选剧情方案</h4><p className="text-xs leading-6 text-muted-foreground">讨论不会修改小说。先查看影响与章节计划，再选择采用；已写正文请走返修流程。</p>
    {options.map(item=>{const applied=!!entry.plot_receipts?.[item.id] || !!localReceipts[item.id];return <div key={item.id} className="rounded-xl border border-border bg-background/40 p-4"><div className="flex items-center justify-between gap-2"><strong className="text-sm">{item.title}</strong><span className={`shrink-0 text-xs ${applied?'text-emerald-400':'text-muted-foreground'}`}>{applied?<><CheckCircle2 className="mr-1 inline h-3.5 w-3.5"/>已采用</>:'尚未采用'}</span></div><p className="mt-2 text-sm leading-7">{item.reason}</p><p className="mt-2 text-xs text-muted-foreground">影响第 {item.chapters.map(p=>Number(p.chapter)).join('、')} 章 · 推荐分 {item.score}（模型判断）</p><button disabled={disabled || applying || applied} onClick={()=>setSelected(item.id)} className="mt-3 rounded-lg border border-primary/40 px-3 py-2 text-sm text-primary disabled:opacity-50">{applied?'此方案已进入章节计划':'查看修改并采用'}</button></div>})}
    {option && <div role="dialog" aria-label="查看剧情方案" className="rounded-xl border border-primary/40 bg-background p-4"><h4 className="font-semibold">{option.title} · 修改预览</h4>{option.chapters.map(plan=><section key={plan.chapter} className="mt-4 border-t border-border pt-4"><h5 className="font-medium">第 {Number(plan.chapter)} 章 · {plan.title}</h5><dl className="mt-3 space-y-3">{Object.entries(labels).filter(([key])=>!!plan[key as keyof typeof labels]).map(([key,label])=><div key={key}><dt className="text-xs text-primary">{label}</dt><dd className="mt-1 whitespace-pre-wrap text-sm leading-7">{plan[key as keyof typeof labels]}</dd></div>)}</dl><details className="mt-3 text-sm"><summary className="cursor-pointer text-primary">前文依据与使用方式</summary>{plan.setup.map((anchor,i)=><div key={i} className="mt-3 border-l-2 border-primary/40 pl-3"><p className="text-muted-foreground">“{anchor.quote}”</p><p className="mt-1 leading-7">{anchor.use}</p></div>)}</details></section>)}{option.new_info?.length>0 && <p className="mt-4 text-sm leading-7 text-amber-300">新增设计：{option.new_info.join('；')}。采用后进入待写计划。</p>}{option.risks?.map((risk,i)=><p key={i} className="mt-2 text-sm leading-7 text-amber-300">风险：{risk}</p>)}<p className="mt-4 text-xs leading-6 text-muted-foreground">将更新现有近期大纲中的对应章节，并保留备份。已采用写法、人物基础档案和已有正文不会被覆盖。</p><div className="mt-4 flex gap-2"><button disabled={applying || disabled} onClick={()=>void apply()} className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50">{applying?<><Loader2 className="mr-1 inline h-4 w-4 animate-spin"/>正在采用…</>:'确认采用到章节计划'}</button><button disabled={applying} onClick={()=>setSelected('')} className="rounded-lg border border-border px-3 py-2 text-sm">继续讨论</button></div></div>}
    {feedback && <p role="status" className="text-sm leading-7 text-primary">{feedback}</p>}
  </section>;
}
