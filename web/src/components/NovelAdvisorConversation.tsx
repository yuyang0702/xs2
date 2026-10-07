import { useRef, useState } from 'react';
import { Loader2, MessageCircle, Sparkles } from 'lucide-react';
import type { NovelAssistantEntry } from '../lib/api';
import type { ConfigurationReceipt } from '../lib/novel-assistant-configuration';
import NovelArchiveContent from './NovelArchiveContent';
import NovelConfigurationSuggestions from './NovelConfigurationSuggestions';
import { advisorMarkdown } from '../lib/novel-advisor';

export default function NovelAdvisorConversation({question, onQuestion, onAsk, entries, busy, loading,
  feedback, now, receipts, onAdopt, onRead, workflowBusy, established, hasReference}: {
  question:string; onQuestion:(value:string)=>void; onAsk:(question?:string)=>void;
  entries:NovelAssistantEntry[]; busy:boolean; loading:boolean; feedback:string; now:number;
  receipts?:Record<string, ConfigurationReceipt>;
  onAdopt:(entry:NovelAssistantEntry)=>{success:boolean;message:string};
  onRead:(entry:NovelAssistantEntry)=>void; workflowBusy:boolean; established:boolean; hasReference:boolean;
}) {
  const input = useRef<HTMLTextAreaElement>(null);
  const [notice, setNotice] = useState('');
  const [followup, setFollowup] = useState(false);
  const running = entries.find(entry=>entry.status==='running');
  const latest = [...entries].reverse().find(entry=>entry.status==='completed' && entry.purpose==='advisor');
  const last = entries[entries.length - 1];
  const disabled = busy || loading || workflowBusy;
  const quick = (value:string) => {onQuestion(value); setFollowup(false); input.current?.focus();};
  return <div className="mt-6 space-y-6">
    <div className="flex items-center gap-2 text-xs text-emerald-400"><Sparkles className="h-4 w-4"/>默认大模型负责分析 · 一句想法就能开始</div>
    <div className="flex flex-wrap gap-2">
      <button disabled={disabled} onClick={()=>quick('')} className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50">我已有一个想法</button>
      <button disabled={disabled} onClick={()=>quick('我还没想好写什么，请给我几个具体的故事方向，明确推荐一个，并说明主要看点和适合的写法。')} className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50">还没想好，帮我找方向</button>
      <button disabled={disabled} onClick={()=>quick('请结合本书已采用的参考写法，推荐具体故事方向，解释核心看点、适合的写法和适配风险。如果没有参考，也可以给原创建议。')} className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50">结合本书参考写法推荐</button>
    </div>
    <label className="block text-sm font-medium" htmlFor="novel-advisor-idea">{followup ? '继续讨论这个方向' : '说说你想写的故事'}</label>
    <textarea id="novel-advisor-idea" ref={input} disabled={disabled} rows={5} value={question} onChange={event=>onQuestion(event.target.value)} placeholder={followup ? '例如：保留信任危机，但我希望主角更主动，开局从一次救援开始。' : '例如：我想写一个末日故事，幸存者越聚集越危险。帮我判断主角该追求什么，这本书的看点在哪里。'} className="w-full rounded-xl border border-border bg-background px-4 py-3 text-sm leading-7 outline-none focus:border-primary disabled:opacity-60"/>
    <div className="flex flex-wrap items-center gap-3"><button disabled={disabled} onClick={()=>{setNotice(''); onAsk();}} className="flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground disabled:opacity-60">{busy ? <Loader2 className="h-4 w-4 animate-spin"/> : <Sparkles className="h-4 w-4"/>}{busy ? '大模型正在分析…' : loading ? '正在恢复讨论…' : followup ? '让 AI 继续分析' : '让 AI 帮我分析'}</button><p className="text-xs leading-6 text-muted-foreground">{hasReference ? '会参考本书已采用的写法。' : '没有参考资料也可以分析原创故事。'}分析后由你决定采用。</p></div>
    {running && <p role="status" aria-live="polite" className="rounded-xl border border-primary/25 bg-primary/5 p-4 text-sm leading-7">{running.message || 'AI 正在判断故事方向、看点与写法…'} 已等待 {Math.max(0, Math.floor((now-Date.parse(running.created_at))/1000))} 秒。可以切换页面，讨论结果会保留。</p>}
    {(feedback || notice) && <p role="status" className="rounded-lg border border-primary/25 p-3 text-sm leading-7">{notice || feedback}</p>}
    {last?.status==='failed' && <div role="alert" className="rounded-xl border border-amber-300/30 p-4 text-sm leading-7"><p>本次分析未完成：{last.message}</p><button disabled={disabled} onClick={()=>onAsk(last.question)} className="mt-2 rounded-lg border border-border px-3 py-2 disabled:opacity-50">重新分析这个问题</button></div>}
    {latest && <section className="space-y-5" aria-label="小说顾问分析结果">
      <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-lg font-semibold">AI 对这本小说的判断</h3><button onClick={()=>onRead(latest)} className="rounded-lg border border-border px-3 py-2 text-xs">展开阅读</button></div>
      <details className="text-xs leading-6 text-muted-foreground"><summary className="cursor-pointer">本次讨论：{latest.question.length>100 ? latest.question.slice(0,100)+'…' : latest.question}</summary><p className="mt-3 whitespace-pre-wrap">{latest.question}</p></details>
      <NovelArchiveContent content={advisorMarkdown(latest.reply || '')}/>
      <div className="grid gap-4 lg:grid-cols-2">{([
        ['direction','推荐的故事方向'], ['hook','核心看点'], ['writing','适合的写法'], ['risks','需要注意的问题'],
      ] as const).map(([key,title])=><article key={key} className={`rounded-xl border p-5 ${key==='risks'?'border-amber-300/25 bg-amber-300/5':'border-border bg-background/40'}`}><h4 className="mb-3 font-medium">{title}</h4><NovelArchiveContent content={advisorMarkdown(latest.advisor_sections?.[key] || '本次暂未提供，请继续讨论。')}/></article>)}</div>
      <details className="rounded-xl border border-border p-4"><summary className="cursor-pointer text-sm font-medium">{receipts?.[latest.id] ? '查看本次填写记录' : '查看建议参数（尚未采用）'}</summary><NovelConfigurationSuggestions entry={{...latest,purpose:'configure'}} receipt={receipts?.[latest.id]} pendingApproval={!receipts?.[latest.id]}/></details>
      <div className="flex flex-wrap gap-3"><button disabled={disabled} onClick={()=>{setFollowup(true); onQuestion(''); input.current?.focus();}} className="flex items-center gap-2 rounded-xl border border-border px-4 py-3 text-sm disabled:opacity-50"><MessageCircle className="h-4 w-4"/>继续讨论这个方向</button><button disabled={disabled || !!receipts?.[latest.id] || !(latest.suggestions || []).some(item=>item.key==='premise')} onClick={()=>setNotice(onAdopt(latest).message)} className="rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground disabled:opacity-50">{receipts?.[latest.id] ? '这套方案已采用' : established ? '采用建议，保留现有进度' : '采用方案，填写设置并继续'}</button></div>
    </section>}
    {entries.filter(entry=>entry.status!=='running' && entry.id!==latest?.id).length>0 && <details className="rounded-xl border border-border p-4"><summary className="cursor-pointer text-sm">查看之前的讨论</summary>{entries.filter(entry=>entry.status!=='running' && entry.id!==latest?.id).reverse().map(entry=><div key={entry.id} className="mt-4 border-t border-border pt-4"><p className="text-sm leading-7">{entry.question.length>140 ? entry.question.slice(0,140)+'…' : entry.question}</p><button onClick={()=>onRead(entry)} className="mt-2 rounded-lg border border-border px-3 py-2 text-xs">{entry.status==='completed'?'阅读分析':'查看失败原因'}</button></div>)}</details>}
  </div>;
}
