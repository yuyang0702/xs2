import { useEffect, useState, type ReactNode } from "react";
import { errorText, type CharacterApi, type CharacterPreview, type CharacterState, type HistoryEntry, type Inventory, type Person, type Section } from "./api";
import { FieldSuggestion, SceneTrial } from "./CharacterAssistant";
import { box, button, Comparison, field, muted, primary, Problem, prose } from "./ui";
import { useAction } from "./useAction";

const tabs = [
  ["overview", "概况"], ["motivation", "性格与动机"], ["relationships", "关系"], ["voice", "声线"],
  ["state", "本章状态"], ["arc", "成长与计划"], ["raw", "原文"], ["history", "修订记录"], ["trial", "场景试读"],
] as const;
type Tab = typeof tabs[number][0];
type Props = {
  person: Person; inventory: Inventory; api: CharacterApi; ready: boolean; actionChapter: string; roster: Person[];
  onChanged: () => void; onSelect: (id: string) => void; onLegacy: () => void; lifecycle?: ReactNode;
};
type Edit = { sectionId: string; text: string };
const sourceLabels: Record<string, string> = { profile: "人物档案", voice: "声线", confirmed_state: "已确认正文记录" };
const stateLabels: Record<string, string> = {
  location: "所在位置", physical: "身体处境", resources: "资源", emotion: "情绪", goal: "目标", current_state: "处境",
  bottom_line: "底线", desire: "欲望", want: "所求", fear: "担忧", current_goal: "当前目标", motivation: "动机",
  target: "对象", change: "变化", nature: "性质", status: "现状", meaning_to_character: "对人物的意义",
  hidden_tension: "潜在张力", default_attitude: "态度",
};

export default function CharacterDetail({ person, inventory, api, ready, actionChapter, roster, onChanged, onSelect, onLegacy, lifecycle }: Props) {
  const [tab, setTab] = useState<Tab>("overview");
  const [edit, setEdit] = useState<Edit | null>(null);
  const [receipt, setReceipt] = useState<CharacterPreview | null>(null);
  const [restore, setRestore] = useState<string>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [history, setHistory] = useState<HistoryEntry[]>();
  const [historyError, setHistoryError] = useState("");
  const action = useAction();
  const revision = inventory.revision;
  const editedSection = person.sections.find(section => section.id === edit?.sectionId);
  const available = ready && !action.busy;
  const usableReceipt = available && receipt?.revision === revision && receipt.character_id === person.id;
  const latestState = person.states.find(state => state.chapter === inventory.chapter);
  const latestRelationshipState = person.states[person.states.length - 1];
  const pastStates = person.states.filter(state => state.chapter !== inventory.chapter);
  useEffect(() => {
    if (tab !== "history" || !ready) return;
    const controller = new AbortController();
    setHistoryError("");
    void api.history(person.id, controller.signal).then(value => {
      if (!controller.signal.aborted) setHistory(value.entries);
    }).catch(failure => {
      if (!controller.signal.aborted) setHistoryError(errorText(failure));
    });
    return () => controller.abort();
  }, [api, person.id, ready, revision, tab]);

  function changeTab(value: Tab) {
    setTab(value);
    setReceipt(null);
    setError("");
    setNotice("");
    setRestore(undefined);
  }
  function preview(input: Parameters<CharacterApi["preview"]>[2]) {
    setReceipt(null);
    setError("");
    setNotice("");
    void action.run(async signal => {
      try {
        const value = await api.preview(person.id, revision, input, signal);
        if (!signal.aborted) setReceipt(value);
      } catch (failure) { if (!signal.aborted) setError(errorText(failure)); }
    });
  }
  function apply() {
    if (!usableReceipt || !receipt) return;
    setError("");
    void action.run(async signal => {
      try {
        await api.apply(revision, receipt, signal);
        if (signal.aborted) return;
        setReceipt(null);
        setEdit(null);
        setRestore(undefined);
        setNotice(receipt.history_id ? "所选片段已回退。" : "所选片段已保存。");
        onChanged();
      } catch (failure) {
        if (!signal.aborted) {
          setReceipt(null);
          setError(errorText(failure) + " 请刷新资料后重新预览。");
        }
      }
    });
  }
  function sectionList(sections: Section[]) {
    return sections.length === 0 ? <p className={muted}>这个分组暂无可辨识的档案。</p> : sections.map(section =>
      <article key={section.id} className={box}>
        <h3 className="font-semibold">{section.label}</h3>
        <p className={muted}>{section.source_id} · 第 {section.line} 行</p>
        <p className={prose}>{section.text}</p>
        {section.editable && person.status === "structured" && edit?.sectionId !== section.id &&
          <button className={button} disabled={!available} onClick={() => {
            setEdit({ sectionId: section.id, text: section.text }); setReceipt(null); setNotice(""); setError("");
          }}>编辑{section.label}</button>}
        {section.editable && edit?.sectionId === section.id && <div className="space-y-3">
          <label className="grid gap-1 text-sm">替换内容
            <textarea aria-label="替换内容" className={field} maxLength={12000} rows={3} value={edit.text} disabled={action.busy}
              onChange={event => { setEdit({ sectionId: section.id, text: event.target.value }); setReceipt(null); }} />
          </label>
          <div className="flex flex-wrap gap-2">
            <button className={primary} disabled={!available || !edit.text.trim() || edit.text === section.text || /[\r\n]/.test(edit.text)}
              onClick={() => preview({ section_id: section.id, source_id: section.source_id, replacement: edit.text })}>预览修改</button>
            <button className={button} disabled={action.busy} onClick={() => { setEdit(null); setReceipt(null); setError(""); }}>取消编辑</button>
          </div>
          {section.ai_editable && <FieldSuggestion key={section.id} api={api} person={person} section={section} chapter={actionChapter}
            revision={revision} ready={available} onUse={value => {
              if (value.section_id !== section.id || value.source_id !== section.source_id || value.character_id !== person.id) return;
              setEdit({ sectionId: section.id, text: value.after }); setReceipt(value); setError(""); setNotice("");
            }} />}
        </div>}
      </article>);
  }
  return <section className="min-w-0 space-y-4" aria-label={person.name + "的人物档案"}>
    <header className={box}>
      <h2 className="text-xl font-bold">{person.title || person.name}</h2>
      {person.status === "legacy" && <p className={muted}>旧格式档案，可在原文查看保留内容。<button className={button + " ml-2"} onClick={onLegacy}>打开旧版声音编辑</button></p>}
      {person.warnings.map(warning => <p key={warning} className={muted}>{warning}</p>)}
      <nav aria-label="人物档案分组" className="flex flex-wrap gap-2">{tabs.map(([value, label]) =>
        <button className={value === tab ? primary : button} key={value} aria-pressed={value === tab} disabled={action.busy}
          onClick={() => changeTab(value)}>{label}</button>)}</nav>
    </header>
    <Problem message={error} />
    {notice && <p role="status" className={muted}>{notice}</p>}
    {receipt && <section aria-label="确认片段比较" className={box}>
      <h3 className="font-semibold">{receipt.history_id ? "回退预览" : "修改预览"}</h3>
      <p className={muted}>{receipt.source_id} · 第 {receipt.line} 行 · {receipt.impact}</p>
      <Comparison before={receipt.before} after={receipt.after} />
      {receipt.revision !== revision && <Problem message="人物资料已更新。请重新预览当前草稿。" />}
      <div className="flex flex-wrap gap-2">
        <button className={primary} disabled={!usableReceipt} onClick={apply}>{receipt.history_id ? "确认回退" : "确认修改"}</button>
        <button className={button} disabled={action.busy} onClick={() => setReceipt(null)}>放弃本次预览</button>
      </div>
    </section>}
    {tab === "overview" && sectionList(person.sections.filter(section => ["overview", "facts", "constraints"].includes(section.group)))}
    {tab === "motivation" && sectionList(person.sections.filter(section => section.group === "motivation"))}
    {tab === "voice" && sectionList(person.sections.filter(section => section.group === "voice"))}
    {tab === "relationships" && <>
      <section className={box} aria-label="有方向的关系">
        <h3 className="font-semibold">关系方向</h3>
        {person.relationships.length === 0 && <p className={muted}>暂无明确的关系记录。</p>}
        {person.relationships.map((relation, index) => <article key={index} className="space-y-2 rounded-lg border border-border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="font-medium">{person.name} → {relation.target}</h4>
            {relation.target_id && <button className={button} disabled={!ready} onClick={() => onSelect(relation.target_id!)}>查看{relation.target}</button>}
          </div>
          <p className={muted}>{sourceLabels[relation.provenance] || "来源类别待核对"} · {relation.source_id}
            {relation.provenance === "confirmed_state" && latestRelationshipState?.chapter !== inventory.chapter ? " · 早于当前章节的记录" : ""}</p>
          <Facts values={{ 性质: relation.nature, 意义: relation.meaning, 张力: relation.tension, 态度: relation.attitude }} />
          {relation.text && <p className={prose}>{relation.text}</p>}
        </article>)}
      </section>
      {sectionList(person.sections.filter(section => section.group === "relationships"))}
    </>}
    {tab === "state" && <section className={box} aria-label="本章状态">
      {lifecycle}
      <h3 className="font-semibold">本章已确认状态</h3>
      {inventory.stale_chapters.includes(inventory.chapter) ? <p className={muted}>本章确认依据已失效，请核对正文后重新确认。</p>
        : latestState ? <StateCard state={latestState} /> : <p className={muted}>本章没有已确认的人物状态。早期记录可在成长与计划中查看。</p>}
      <h3 className="pt-2 font-semibold">世界事实</h3>
      {inventory.chapters.includes(inventory.chapter) && inventory.world_facts.length > 0 ?
        inventory.world_facts.map((fact, index) => <article key={index} className="space-y-1"><p>{fact.description}</p><Proof {...fact} /></article>) :
        <p className={muted}>本章暂无可展示的已确认世界事实。</p>}
    </section>}
    {tab === "arc" && <>
      <section className={box}><h3 className="font-semibold">待写计划</h3>
        <p className={muted}>这里的弧线是写作计划。</p>
        {sectionList(person.planned_arcs)}
      </section>
      <section className={box}><h3 className="font-semibold">早期已确认状态</h3>
        {pastStates.length ? [...pastStates].reverse().map(state => <StateCard key={state.chapter} state={state} />)
          : <p className={muted}>暂无更早的有效记录。</p>}
      </section>
    </>}
    {tab === "raw" && <section className={box} aria-label="当前人物原文">
      {person.raw.length ? person.raw.map((raw, index) => <article key={index} className={box}>
        <h3 className="font-semibold">{raw.title}</h3><p className={muted}>{raw.source_id}</p><pre className={prose + " max-h-[32rem] overflow-auto"}>{raw.text}</pre>
      </article>) : <p className={muted}>暂无当前人物的原文。</p>}
    </section>}
    {tab === "history" && <section className={box} aria-label="修订记录">
      <h3 className="font-semibold">修订记录</h3><Problem message={historyError} />
      {history?.length === 0 && <p className={muted}>暂无已保存的修订。</p>}
      {!history && !historyError && <p className={muted}>正在读取修订…</p>}
      {history?.map(entry => <article key={entry.id} className={box}>
        <details><summary className="cursor-pointer">{new Date(entry.created_at).toLocaleString()} · {entry.source_id}{entry.restored_from ? " · 回退" : ""}</summary>
          <Comparison before={entry.before} after={entry.after} />
        </details>
        <button className={button} disabled={!available} aria-pressed={restore === entry.id}
          onClick={() => { setRestore(entry.id); preview({ history_id: entry.id }); }}>预览回退</button>
      </article>)}
    </section>}
    {tab === "trial" && <SceneTrial api={api} person={person} roster={roster} chapter={actionChapter} revision={revision} ready={ready} />}
    {edit && !editedSection && <Problem message="该原文小节已不再可定位。当前草稿可在重新选择前复制。" />}
    {edit && !editedSection && <textarea aria-label="未保存的草稿" className={field + " w-full"} readOnly value={edit.text} />}
  </section>;
}

function Facts({ values }: { values: Record<string, string | string[]> }) {
  const fields = Object.entries(values).filter(([, value]) => value.length > 0);
  return fields.length ? <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
    {fields.map(([key, value]) => <div key={key} className="contents">
      <dt className="text-muted-foreground">{stateLabels[key] || key}</dt>
      <dd className={prose}>{Array.isArray(value) ? value.join("\n") : value}</dd>
    </div>)}
  </dl> : null;
}

function Proof({ source_chapter, source_id, evidence }: Pick<CharacterState, "source_chapter" | "source_id" | "evidence">) {
  return <blockquote className="border-l-2 border-primary/30 pl-3">
    <p className={muted}>正文依据 · 第 {Number(source_chapter)} 章 · {source_id}</p>
    <p className={prose}>{Array.isArray(evidence) ? evidence.join("\n") : evidence}</p>
  </blockquote>;
}
function StateCard({ state }: { state: CharacterState }) {
  const snapshot = Object.fromEntries(Object.entries(state.snapshot).filter(([key]) => key !== "knowledge" && key !== "misbelief"));
  return <article className={box}>
    <h4 className="font-medium">第 {Number(state.chapter)} 章确认记录</h4>
    <Facts values={snapshot} /><Facts values={state.drives} />
    <Facts values={{ 所知: state.knowledge, 误解: state.beliefs }} />
    {state.relationships.map((relation, index) => <Facts values={relation} key={index} />)}
    <Proof {...state} />
  </article>;
}
