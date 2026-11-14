import { useRef, useState } from 'react';
import { Loader2, MessageCircle, Sparkles } from 'lucide-react';
import type { NovelAdvisorTask, NovelAssistantEntry } from '../lib/api';
import type { ConfigurationReceipt } from '../lib/novel-assistant-configuration';
import NovelArchiveContent from './NovelArchiveContent';
import NovelConfigurationSuggestions from './NovelConfigurationSuggestions';
import NovelTopicSelection from './NovelTopicSelection';
import { advisorMarkdown } from '../lib/novel-advisor';

function hasReferenceRecommendations(entry?: NovelAssistantEntry) {
  return entry?.purpose === 'advisor' && entry.status === 'completed' && !!(
    entry.advisor_sections?.mechanism_recommendations?.adopted_from_library?.length
    || entry.advisor_sections?.style_recommendations?.adopted_styles?.length
    || entry.advisor_sections?.conflict_recommendations?.adopted_conflicts?.length);
}

export default function NovelAdvisorConversation({
  question, onQuestion, onAsk, entries, busy, loading,
  feedback, now, receipts, onAdopt, onRead, workflowBusy, established, hasReference, shortStory,
  librarySize, adoptedCount, onQuickAdopt, onManualSelect, referenceAdoptionBusy = false, referenceAdoptionApplied = false,
  referenceModels = [], referenceModel = '', onReferenceModelChange
}: {
  question: string;
  onQuestion: (value: string) => void;
  onAsk: (question?: string, task?: NovelAdvisorTask) => void;
  librarySize?: number;
  adoptedCount?: number;
  entries: NovelAssistantEntry[];
  busy: boolean;
  loading: boolean;
  feedback: string;
  now: number;
  receipts?: Record<string, ConfigurationReceipt>;
  onAdopt: (entry: NovelAssistantEntry) => { success: boolean; message: string };
  onRead: (entry: NovelAssistantEntry) => void;
  workflowBusy: boolean;
  established: boolean;
  hasReference: boolean;
  shortStory?: boolean;
  onQuickAdopt?: (entry: NovelAssistantEntry) => Promise<{ success: boolean; message: string }>;
  onManualSelect?: () => void;
  referenceAdoptionBusy?: boolean;
  referenceAdoptionApplied?: boolean;
  referenceModels?: Array<{value:string;label:string}>;
  referenceModel?: string;
  onReferenceModelChange?: (model:string)=>void;
}) {
  const input = useRef<HTMLTextAreaElement>(null);
  const [notice, setNotice] = useState('');
  const [followup, setFollowup] = useState(false);
  const [quickAdopting, setQuickAdopting] = useState(false);
  const running = entries.find(entry => entry.status === 'running');
  const latest = [...entries].reverse().find(entry => entry.status === 'completed' && entry.purpose === 'advisor');
  const last = entries[entries.length - 1];
  const disabled = busy || loading || workflowBusy;
  const hasLibrary = (librarySize || 0) > 0;
  const hasAdopted = hasReference || (adoptedCount || 0) > 0;
  const hasRecommendations = hasReferenceRecommendations(latest);
  const styles = latest?.advisor_sections?.style_recommendations;
  const quick = (value: string) => { onQuestion(value); setFollowup(false); input.current?.focus(); };

  const handleQuickAdopt = async (entry = latest) => {
    if (!entry || !onQuickAdopt || disabled || quickAdopting || referenceAdoptionBusy) return;
    setNotice('');
    setQuickAdopting(true);
    try {
      const result = await onQuickAdopt(entry);
      setNotice(result.message);
    } catch (error) {
      setNotice(`采用结果尚未确认：${error instanceof Error ? error.message : String(error)}。请核对后台结果。`);
    } finally {
      setQuickAdopting(false);
    }
  };

  return <div className="mt-6 space-y-6">
    <div className="flex items-center gap-2 text-xs text-emerald-400">
      <Sparkles className="h-4 w-4" />
      默认大模型负责分析 · 一句想法就能开始
    </div>

    {onQuickAdopt && onReferenceModelChange && <label className="block rounded-xl border border-border p-3 text-xs">
      本次兼容检查模型
      <select aria-label="本次兼容检查模型" value={referenceModel} disabled={disabled || quickAdopting || referenceAdoptionBusy} onChange={event=>onReferenceModelChange(event.target.value)} className="ml-3 max-w-full rounded-lg border border-border bg-background px-2 py-1.5">
        <option value="">沿用小说顾问模型</option>
        {referenceModels.map(model=><option key={model.value} value={model.value}>{model.label}</option>)}
      </select>
      <span className="mt-2 block text-muted-foreground">仅用于下一次兼容与人物适配检查，不保存到作品或工作流默认配置。</span>
    </label>}

    <div className="flex flex-wrap gap-2">
      {/* 模式1: 原创模式（始终可见）*/}
      <button
        disabled={disabled}
        onClick={() => quick('')}
        className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50"
      >
        我已有想法
      </button>

      {/* 模式2: 灵感推荐（写法库有内容时）*/}
      {hasLibrary && (
        <button
          disabled={disabled}
          onClick={() => quick('我还没想好写什么。请借鉴写法库里的抽象写法，给出原创故事方向，说明各自的核心看点。')}
          className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50"
        >
          从写法库找灵感
          <span className="ml-1 text-xs text-muted-foreground">({librarySize} 本参考)</span>
        </button>
      )}

      {/* 模式3: 已有参考优化（本书已采用写法时）*/}
      {hasAdopted && (
        <button
          disabled={disabled}
          onClick={() => quick('请结合本书已采用的参考写法，推荐具体故事方向，解释核心看点、如何运用已采用的写法和适配风险。')}
          className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50"
        >
          基于已采用写法优化
          <span className="ml-1 text-xs text-muted-foreground">({adoptedCount} 条)</span>
        </button>
      )}
    </div>

    <label className="block text-sm font-medium" htmlFor="novel-advisor-idea">
      {followup ? '继续讨论这个方向' : '说说你想写的故事'}
    </label>

    <textarea
      id="novel-advisor-idea"
      ref={input}
      disabled={disabled}
      rows={5}
      value={question}
      onChange={event => onQuestion(event.target.value)}
      placeholder={followup ? '例如：保留信任危机，但我希望主角更主动，开局从一次救援开始。' : '例如：我想写一个末日故事，幸存者越聚集越危险。帮我判断主角该追求什么，这本书的看点在哪里。'}
      className="w-full rounded-xl border border-border bg-background px-4 py-3 text-sm leading-7 outline-none focus:border-primary disabled:opacity-60"
    />

    <div className="flex flex-wrap items-center gap-3">
      <button
        disabled={disabled}
        onClick={() => { setNotice(''); onAsk(); }}
        className="flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground disabled:opacity-60"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
        {busy ? '大模型正在分析…' : loading ? '正在恢复讨论…' : followup ? '让 AI 继续分析' : '让 AI 帮我分析'}
      </button>

      {shortStory && <button type="button" disabled={disabled}
        onClick={() => { setNotice(''); onAsk(undefined, 'topic_selection'); }}
        className="rounded-xl border border-primary/45 px-5 py-3 text-sm font-semibold disabled:opacity-60">
        选题盲读
      </button>}

      <p className="text-xs leading-6 text-muted-foreground">
        {!hasLibrary && !hasAdopted && '暂无参考资料，可原创故事'}
        {hasLibrary && !hasAdopted && `写法库有 ${librarySize} 本参考，可推荐灵感`}
        {hasAdopted && `本书已采用 ${adoptedCount} 条写法，可基于优化`}
        。分析后由你决定采用。
      </p>
    </div>

    {running && <p role="status" aria-live="polite" className="rounded-xl border border-primary/25 bg-primary/5 p-4 text-sm leading-7">{running.message || 'AI 正在判断故事方向、看点与写法…'} 已等待 {Math.max(0, Math.floor((now - Date.parse(running.created_at)) / 1000))} 秒。可以切换页面，讨论结果会保留。</p>}
    {(feedback || notice) && <p role="status" className="rounded-lg border border-primary/25 p-3 text-sm leading-7">{notice || feedback}</p>}
    {last?.status === 'failed' && <div role="alert" className="rounded-xl border border-amber-300/30 p-4 text-sm leading-7"><p>本次分析未完成：{last.message}</p><button disabled={disabled} onClick={() => onAsk(last.question, last.advisor_task)} className="mt-2 rounded-lg border border-border px-3 py-2 disabled:opacity-50">重新分析这个问题</button></div>}
    {latest?.topic_selection && <section className="space-y-5">
      <h3 className="text-lg font-semibold">候选题材与盲读结果</h3>
      <p className="text-sm leading-7">{latest.reply}</p>
      <NovelTopicSelection selection={latest.topic_selection} onChoose={disabled ? undefined : idea => {
        setFollowup(true); onQuestion(idea); input.current?.focus();
      }} />
    </section>}
    {latest && !latest.topic_selection && <section className="space-y-5" aria-label="小说顾问分析结果">
      <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-lg font-semibold">AI 对这本小说的判断</h3><button onClick={() => onRead(latest)} className="rounded-lg border border-border px-3 py-2 text-xs">展开阅读</button></div>
      <details className="text-xs leading-6 text-muted-foreground"><summary className="cursor-pointer">本次讨论：{latest.question.length > 100 ? latest.question.slice(0, 100) + '…' : latest.question}</summary><p className="mt-3 whitespace-pre-wrap">{latest.question}</p></details>
      <NovelArchiveContent content={advisorMarkdown(latest.reply || '')} />
      <div className="grid gap-4 lg:grid-cols-2">{([
        ['direction', '推荐的故事方向'], ['hook', '核心看点'], ['writing', '适合的写法'], ['risks', '需要注意的问题'],
      ] as const).map(([key, title]) => <article key={key} className={`rounded-xl border p-5 ${key === 'risks' ? 'border-amber-300/25 bg-amber-300/5' : 'border-border bg-background/40'}`}><h4 className="mb-3 font-medium">{title}</h4><NovelArchiveContent content={advisorMarkdown(latest.advisor_sections?.[key] || '本次暂未提供，请继续讨论。')} /></article>)}</div>
      <details className="rounded-xl border border-border p-4"><summary className="cursor-pointer text-sm font-medium">{receipts?.[latest.id] ? '查看本次填写记录' : '查看建议参数（尚未采用）'}</summary><NovelConfigurationSuggestions entry={{ ...latest, purpose: 'configure' }} receipt={receipts?.[latest.id]} pendingApproval={!receipts?.[latest.id]} /></details>
      {latest.advisor_sections?.mechanism_recommendations && <details className="rounded-xl border border-blue-300/25 bg-blue-300/5 p-4"><summary className="cursor-pointer text-sm font-medium">📝 推荐的写法机制</summary><div className="mt-4 space-y-4 text-xs"><div>{(latest.advisor_sections.mechanism_recommendations.adopted_from_library?.length ?? 0) > 0 && <div><p className="mb-2 font-medium text-blue-700">从参考作品采用：</p><ul className="space-y-1 ml-4">{latest.advisor_sections.mechanism_recommendations.adopted_from_library!.map((m, i) => <li key={i}>【{m.priority}】<strong>{m.mechanism}</strong> - {m.usage_in_story}（在{m.chapter_placement || '创作中'}使用）{m.library_id && m.candidate_id && <span className="block break-all text-muted-foreground">{m.library_id} / {m.candidate_id}</span>}</li>)}</ul></div>}{(latest.advisor_sections.mechanism_recommendations.new_mechanisms?.length ?? 0) > 0 && <div className="mt-3"><p className="mb-2 font-medium text-blue-700">补充的新机制：</p><ul className="space-y-1 ml-4">{latest.advisor_sections.mechanism_recommendations.new_mechanisms!.map((m, i) => <li key={i}>【{m.priority}】<strong>{m.mechanism}</strong> - {m.reason}{m.synergy_with?.length > 0 && `（与${m.synergy_with.join('、')}协同）`}</li>)}</ul></div>}{(latest.advisor_sections.mechanism_recommendations.avoid_combinations?.length ?? 0) > 0 && <div className="mt-3"><p className="mb-2 font-medium text-amber-600">⚠️ 避免的组合：</p><ul className="space-y-1 ml-4">{latest.advisor_sections.mechanism_recommendations.avoid_combinations!.map((c, i) => <li key={i}><strong>{c.a}</strong> + <strong>{c.b}</strong>：{c.reason}</li>)}</ul></div>}</div></div></details>}
      {styles && <details className="rounded-xl border border-purple-300/25 bg-purple-300/5 p-4">
        <summary className="cursor-pointer text-sm font-medium">推荐的文风选择</summary>
        <div className="mt-4 space-y-4 text-xs">
          {(styles.adopted_styles?.length ?? 0) > 0 && <ul className="space-y-3">
            {styles.adopted_styles?.map((style, index) => <li key={style.choice_id || index}>
              <strong>{style.style}</strong>
              <p>{style.reason}</p>
              <p>本书用法 · {style.usage_in_story}</p>
              {style.library_id && style.choice_id && <p className="break-all text-muted-foreground">{style.library_id} / {style.choice_id}</p>}
            </li>)}
          </ul>}
          {styles.no_match_reason && <p>{styles.no_match_reason}</p>}
          {(styles.avoid_styles?.length ?? 0) > 0 && <div>
            <p className="mb-2 font-medium text-amber-600">建议避开的风格</p>
            <ul className="space-y-1">
              {styles.avoid_styles?.map((style, index) => <li key={index}><strong>{style.style}</strong> · {style.reason}</li>)}
            </ul>
          </div>}
        </div>
      </details>}
      {latest.advisor_sections?.conflict_recommendations && <details className="rounded-xl border border-orange-300/25 bg-orange-300/5 p-4"><summary className="cursor-pointer text-sm font-medium">⚔️ 推荐的冲突模式</summary><div className="mt-4 space-y-4 text-xs">{(latest.advisor_sections.conflict_recommendations.adopted_conflicts?.length ?? 0) > 0 && <div><p className="mb-2 font-medium text-orange-700">推荐采用的冲突：</p><ul className="space-y-1 ml-4">{latest.advisor_sections.conflict_recommendations.adopted_conflicts!.map((c, i) => <li key={i}>【{c.priority}】<strong>{c.conflict}</strong> - {c.reason}（{c.usage_in_story}）</li>)}</ul></div>}{(latest.advisor_sections.conflict_recommendations.avoid_conflicts?.length ?? 0) > 0 && <div className="mt-3"><p className="mb-2 font-medium text-amber-600">⚠️ 避免的冲突：</p><ul className="space-y-1 ml-4">{latest.advisor_sections.conflict_recommendations.avoid_conflicts!.map((c, i) => <li key={i}><strong>{c.conflict}</strong>：{c.reason}</li>)}</ul></div>}</div></details>}

      {hasLibrary && !hasRecommendations && <p role="status" className="text-sm leading-6 text-muted-foreground">本轮未提供可检查的参考清单。可在之前的讨论中复核已有推荐，或继续讨论补充。</p>}
      <div className="flex flex-wrap gap-3">
        <button disabled={disabled} onClick={() => { setFollowup(true); onQuestion(''); input.current?.focus(); }} className="flex items-center gap-2 rounded-xl border border-border px-4 py-3 text-sm disabled:opacity-50"><MessageCircle className="h-4 w-4" />继续讨论这个方向</button>

        {hasRecommendations && onQuickAdopt && (
          <button
            disabled={disabled || quickAdopting || referenceAdoptionBusy}
            onClick={() => void handleQuickAdopt()}
            className="flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            {quickAdopting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {quickAdopting || referenceAdoptionBusy ? '正在检查兼容…' : referenceAdoptionApplied ? '重新检查兼容与人物适配' : '检查兼容并采用'}
          </button>
        )}

        {onManualSelect && <button disabled={disabled || referenceAdoptionBusy} onClick={onManualSelect} className="rounded-xl border border-border px-4 py-3 text-sm disabled:opacity-50">手动选择参考写法</button>}

        <button disabled={disabled || !!receipts?.[latest.id] || !(latest.suggestions || []).some(item => item.key === 'premise')} onClick={() => setNotice(onAdopt(latest).message)} className="rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground disabled:opacity-50">{receipts?.[latest.id] ? '这套方案已采用' : established ? '采用建议，保留现有进度' : '采用方案，填写设置并继续'}</button>
      </div>
    </section>}
    {entries.filter(entry => entry.status !== 'running' && entry.id !== latest?.id).length > 0 && <details className="rounded-xl border border-border p-4">
      <summary className="cursor-pointer text-sm">查看之前的讨论</summary>
      {entries.filter(entry => entry.status !== 'running' && entry.id !== latest?.id).reverse().map(entry => <div key={entry.id} className="mt-4 border-t border-border pt-4">
        <p className="text-sm leading-7">{entry.question.length > 140 ? entry.question.slice(0, 140) + '…' : entry.question}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          <button onClick={() => onRead(entry)} className="rounded-lg border border-border px-3 py-2 text-xs">{entry.status === 'completed' ? '阅读分析' : '查看失败原因'}</button>
          {onQuickAdopt && hasReferenceRecommendations(entry) && <button disabled={disabled || quickAdopting || referenceAdoptionBusy} onClick={() => void handleQuickAdopt(entry)} className="rounded-lg border border-border px-3 py-2 text-xs disabled:opacity-50">检查兼容并采用本轮推荐</button>}
        </div>
        {onQuickAdopt && hasReferenceRecommendations(entry) && <p className="mt-2 text-xs leading-6 text-muted-foreground">按本书当前设置和人物档案重新检查，历史推荐不会直接生效。</p>}
      </div>)}
    </details>}
  </div>;
}
