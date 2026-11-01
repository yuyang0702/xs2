import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle, CheckCircle, Edit3, RefreshCw, Save, Search, Users, Wand2 } from 'lucide-react';
import MarkdownRenderer from './MarkdownRenderer';

interface HumanwareStatus {
  voice_file_exists: boolean; profiles_file_exists: boolean; character_count: number;
}
interface VoiceCharacter {
  id: string; name: string; title: string; voice: string; profile: string;
  voice_status: 'present' | 'missing'; profile_status: 'matched' | 'missing' | 'ambiguous';
}
interface VoiceDocument {
  status: string; content: string; revision?: string; characters?: VoiceCharacter[];
  preamble?: string; unsectioned_voice?: string;
}
interface CharacterVoiceEditorProps {
  workspaceId: string; workflowId: string; onClose?: () => void;
}

async function responseJson(response: Response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === 'string' ? detail : detail?.message || data.message || `请求失败（${response.status}）`);
  }
  return data;
}
async function readDocuments(query: string, signal?: AbortSignal): Promise<[HumanwareStatus, VoiceDocument]> {
  return Promise.all([
    fetch(`/api/humanware/status?${query}`, { signal }).then(responseJson),
    fetch(`/api/humanware/voice-file?${query}`, { signal }).then(responseJson),
  ]);
}

const cardClass = 'rounded-2xl border border-border bg-card p-5';
const buttonClass = 'inline-flex items-center justify-center gap-2 rounded-lg border border-border px-3 py-2 text-sm transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50';
const primaryClass = `${buttonClass} border-primary bg-primary text-primary-foreground hover:bg-primary/90`;
const readingClass = 'break-words text-sm [&_p]:leading-7 [&_li]:leading-7 [&_h3]:text-base [&_h3]:mt-6';

export default function CharacterVoiceEditor({ workspaceId, workflowId }: CharacterVoiceEditorProps) {
  const query = new URLSearchParams({ workflow_id: workflowId, workspace: workspaceId }).toString();
  const scope = useRef(query); scope.current = query;
  const mounted = useRef(true);
  const mutation = useRef<string | null>(null);
  const [document, setDocument] = useState<VoiceDocument | null>(null);
  const [status, setStatus] = useState<HumanwareStatus | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState('');
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState('');
  const [legacyDraft, setLegacyDraft] = useState('');
  const [legacyEditing, setLegacyEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setDocument(null); setStatus(null); setDrafts({}); setMessage(null);
    setSearch(''); setSelected(''); setEditing(''); setLegacyEditing(false); setLegacyDraft('');
    setSaving(false); setGenerating(false);
    readDocuments(query, controller.signal).then(([nextStatus, nextDocument]) => {
      if (controller.signal.aborted) return;
      setStatus(nextStatus); setDocument(nextDocument); setLegacyDraft(nextDocument.content || '');
    }).catch(error => {
      if (!controller.signal.aborted) setMessage({ type: 'error', text: error.message });
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [query]);

  const characters = document?.characters || [];
  const filtered = characters.filter(item => `${item.name} ${item.title}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const current = filtered.find(item => item.id === selected) || filtered[0];
  const value = current ? drafts[current.id] ?? current.voice : '';
  const dirty = (item: VoiceCharacter) => item.id in drafts && drafts[item.id] !== item.voice;
  const changedCount = characters.filter(dirty).length;
  const legacyChanged = legacyDraft !== (document?.content || '');
  const busy = loading || saving || generating;
  const legacyContent = document?.unsectioned_voice || (!characters.length ? document?.content : '') || '';

  async function refresh() {
    if (busy || changedCount || legacyChanged) return;
    const requestQuery = query;
    setLoading(true); setMessage(null);
    try {
      const [nextStatus, nextDocument] = await readDocuments(requestQuery);
      if (!mounted.current || scope.current !== requestQuery) return;
      setStatus(nextStatus); setDocument(nextDocument); setDrafts({}); setLegacyDraft(nextDocument.content || '');
    } catch (error) {
      if (mounted.current && scope.current === requestQuery) setMessage({ type: 'error', text: error instanceof Error ? error.message : '读取失败，请重试。' });
    } finally { if (mounted.current && scope.current === requestQuery) setLoading(false); }
  }

  async function write(kind: 'character' | 'legacy' | 'template') {
    if (busy || mutation.current === query || !document || kind === 'character' && !current) return;
    const requestQuery = query, savedCharacter = current;
    const endpoint = kind === 'character' ? 'voice-character' : kind === 'legacy' ? 'voice-file' : 'generate-voice-file';
    const payload = { workflow_id: workflowId, workspace: workspaceId,
      ...(kind === 'character' ? { character_id: savedCharacter!.id, content: value, expected_revision: document.revision }
        : kind === 'legacy' ? { content: legacyDraft, expected_revision: document.revision } : {}) };
    mutation.current = requestQuery;
    if (kind === 'template') setGenerating(true);
    else setSaving(true);
    setMessage(null);
    let written = false;
    try {
      const result = await fetch(`/api/humanware/${endpoint}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      }).then(responseJson);
      written = true;
      const [nextStatus, nextDocument] = await readDocuments(requestQuery);
      if (!mounted.current || scope.current !== requestQuery) return;
      setStatus(nextStatus); setDocument(nextDocument); setLegacyDraft(nextDocument.content || '');
      if (kind === 'character') {
        setDrafts(previous => Object.fromEntries(Object.entries(previous).filter(([id]) => id !== savedCharacter!.id)));
        setSelected(result.character_id || savedCharacter!.id); setEditing('');
      } else { setDrafts({}); setLegacyEditing(false); }
      setMessage({ type: 'success', text: kind === 'template' ? result.message : kind === 'character' ? `${savedCharacter!.name}的声音已保存。` : '原文已保存。' });
    } catch (error) {
      if (mounted.current && scope.current === requestQuery) setMessage({ type: 'error', text:
        `${written ? '保存已完成，但重新读取失败。请先保留编辑内容，再刷新核对。' : ''}${error instanceof Error ? error.message : '操作失败，请重试。'}` });
    } finally {
      if (mutation.current === requestQuery) mutation.current = null;
      if (mounted.current && scope.current === requestQuery) { setSaving(false); setGenerating(false); }
    }
  }

  return <div className="space-y-5">
    <section className={cardClass}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div><div className="flex items-center gap-2"><Users className="h-5 w-5 text-primary" /><h2 className="text-lg font-semibold">角色声音</h2></div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">按人物查看说话方式，结合本书档案中的性格、目标和关系核对。</p>
          {!loading && <p className="mt-2 text-xs text-muted-foreground">{characters.length} 个人物 · {characters.filter(item => item.voice_status === 'present').length} 份声音{changedCount > 0 ? ` · ${changedCount} 处修改待保存` : ''}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => void refresh()} disabled={busy || changedCount > 0 || legacyChanged} title={changedCount || legacyChanged ? '请先保存或撤销修改，再刷新资料' : '重新读取人物档案与声音'} className={buttonClass}><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新资料</button>
          <button onClick={() => void write('template')} disabled={busy || !status?.profiles_file_exists || status.voice_file_exists || !!document?.content?.trim() || changedCount > 0} className={buttonClass}><Wand2 className="h-4 w-4" />{generating ? '创建中…' : '创建待填写模板'}</button>
        </div>
      </div>
    </section>

    {message && <div role={message.type === 'error' ? 'alert' : 'status'} className={`flex items-start gap-2 rounded-xl border p-4 text-sm leading-6 ${message.type === 'error' ? 'border-destructive/30 bg-destructive/5 text-destructive' : 'border-primary/25 bg-primary/5 text-foreground'}`}>
      {message.type === 'error' ? <AlertCircle className="mt-1 h-4 w-4 shrink-0" /> : <CheckCircle className="mt-1 h-4 w-4 shrink-0 text-primary" />}<span>{message.text}</span>
    </div>}
    {loading && <p role="status" className="py-12 text-center text-sm text-muted-foreground">正在读取人物资料…</p>}

    {!loading && characters.length > 0 && <div className="grid items-start gap-5 lg:grid-cols-[12rem_minmax(0,1fr)]">
      <nav aria-label="人物列表" className={`${cardClass} !p-3 lg:sticky lg:top-4`}>
        <label className="mb-3 flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2"><Search className="h-4 w-4 shrink-0 text-muted-foreground" /><input aria-label="搜索人物" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索人物" className="min-w-0 w-full bg-transparent text-sm outline-none" /></label>
        <div className="flex max-h-[60vh] gap-2 overflow-auto lg:flex-col">{filtered.map((item, index) => <button key={item.id} aria-label={`查看${item.name}的声音`} aria-pressed={item.id === current?.id} onClick={() => { setSelected(item.id); setMessage(null); }} disabled={saving || generating} className={`min-w-[8rem] shrink-0 rounded-xl border p-3 text-left transition-colors lg:min-w-0 ${item.id === current?.id ? 'border-primary/40 bg-primary/10' : 'border-transparent hover:bg-secondary/60'}`}>
          <span className="block break-words text-sm font-semibold">{item.name}{dirty(item) && <span className="ml-1 text-primary">·</span>}</span>
          <span className="mt-1 block text-xs text-muted-foreground">{dirty(item) ? '修改未保存' : item.voice.trim() ? '已有声音条目' : '声音待填写'}{characters.filter(other => other.name === item.name).length > 1 ? ` · 条目 ${index + 1}` : ''}</span>
        </button>)}</div>
        {!filtered.length && <p className="py-4 text-sm text-muted-foreground">没有找到这个人物。</p>}
      </nav>

      {current && <div className="min-w-0 space-y-4">
        <div><h3 className="text-xl font-semibold">{current.title}</h3><p className="mt-1 text-xs leading-6 text-muted-foreground">声音与档案独立保存。切换人物会保留本页尚未保存的编辑。</p></div>
        <div className="grid items-start gap-4 xl:grid-cols-2">
          <section aria-label="当前人物声音" className={`${cardClass} min-w-0`}>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2"><h4 className="font-semibold">声音设定</h4>
              {editing !== current.id && !dirty(current) && <button onClick={() => setEditing(current.id)} disabled={busy || legacyEditing} className={buttonClass}><Edit3 className="h-3.5 w-3.5" />{current.voice_status === 'missing' ? '填写声音' : '编辑声音'}</button>}
            </div>
            {editing === current.id || dirty(current) ? <>
              <textarea aria-label={`${current.name}的声音设定`} value={value} onChange={event => setDrafts(previous => ({ ...previous, [current.id]: event.target.value }))} disabled={saving} rows={15} placeholder="依据此人物的性格、处境和关系，填写说话方式、不同场景下的表现及应避免的表达。" className="min-h-60 w-full resize-y rounded-xl border border-border bg-background p-3 text-sm leading-7 outline-none focus:ring-2 focus:ring-primary/25" />
              <div className="mt-3 flex flex-wrap items-center gap-2"><button onClick={() => void write('character')} disabled={busy || !dirty(current) || !document?.revision} className={primaryClass}><Save className="h-4 w-4" />{saving ? '保存中…' : '保存当前人物'}</button>
                <button onClick={() => { setDrafts(previous => Object.fromEntries(Object.entries(previous).filter(([id]) => id !== current.id))); setEditing(''); }} disabled={busy} className={buttonClass}>撤销当前修改</button></div>
              <p className="mt-3 text-xs leading-6 text-muted-foreground">只修改当前人物的声音；旁边的性格与经历供参考。</p>
            </> : current.voice.trim() ? <div className="max-h-[65vh] overflow-y-auto pr-1"><MarkdownRenderer content={current.voice} className={readingClass} /></div> : <p className="text-sm leading-7 text-muted-foreground">尚未填写这个人物的声音。可参考人物档案填写，或通过角色创建工作流生成。</p>}
          </section>
          <section aria-label="人物档案参考" className={`${cardClass} min-w-0 bg-secondary/15`}>
            <h4 className="font-semibold">人物档案参考</h4><p className="mb-4 mt-1 text-xs leading-6 text-muted-foreground">本书已有的性格、目标、顾虑和关系资料。</p>
            {current.profile_status === 'ambiguous' ? <p className="text-sm leading-7 text-muted-foreground">人物档案中有重名或相近标题，无法唯一对应。请先核对档案，再参考其性格。</p>
              : current.profile.trim() ? <div className="max-h-[65vh] overflow-y-auto pr-1"><MarkdownRenderer content={current.profile} className={readingClass} /></div>
              : <p className="text-sm leading-7 text-muted-foreground">尚未找到这个人物的档案。请先完善人物档案；这里不推测或补写性格。</p>}
          </section>
        </div>
      </div>}
    </div>}

    {!loading && document?.preamble?.trim() && <details className={cardClass}><summary className="cursor-pointer text-sm font-medium">通用声音规则</summary><div className="mt-4"><MarkdownRenderer content={document.preamble} className={readingClass} /></div></details>}
    {!loading && (legacyContent || legacyEditing) && <section className={cardClass}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-semibold">原有声音内容</h3><p className="mt-1 text-xs leading-6 text-muted-foreground">这份内容未按人物分段，已保留原样。可用二级标题（## 人物姓名）区分人物。</p></div><button onClick={() => setLegacyEditing(true)} disabled={busy || changedCount > 0 || !!editing || legacyEditing} className={buttonClass}>编辑原文</button></div>
      {legacyEditing ? <><textarea aria-label="声音原文" value={legacyDraft} onChange={event => setLegacyDraft(event.target.value)} rows={18} disabled={busy} className="w-full rounded-xl border border-border bg-background p-4 text-sm leading-7" /><div className="mt-3 flex gap-2"><button onClick={() => void write('legacy')} disabled={busy || !legacyChanged} className={primaryClass}>保存原文</button><button onClick={() => { setLegacyDraft(document?.content || ''); setLegacyEditing(false); }} disabled={busy} className={buttonClass}>撤销原文修改</button></div></> : <MarkdownRenderer content={legacyContent} className={readingClass} />}
    </section>}
    {!loading && document && !characters.length && !legacyContent && !legacyEditing && <div className={`${cardClass} text-sm leading-7 text-muted-foreground`}><p>还没有人物声音。先完成角色创建，或根据现有人物档案创建待填写模板。</p><button onClick={() => setLegacyEditing(true)} className={`${buttonClass} mt-3`}>手动填写声音</button></div>}
    <p className="text-xs leading-6 text-muted-foreground">已保存的声音会供后续写作任务读取。请结合正文和读者评估，检查人物是否在实际场景中保持一致；无需给每个人强加口头禅。</p>
  </div>;
}
