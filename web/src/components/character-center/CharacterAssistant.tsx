import { useEffect, useRef, useState } from "react";
import { CharacterCenterError, errorText, type CharacterApi, type CharacterPreview, type Job, type JobInput, type Person, type Preference, type Preferred, type Section } from "./api";
import { box, button, Comparison, field, muted, primary, Problem, prose } from "./ui";
import { useAction } from "./useAction";

type JobProps = { api: CharacterApi; person: Person; chapter: string; revision: string; ready: boolean };
type Ticket = { id: string; input: JobInput };
const requestMatches = (job: Job, ticket: Ticket) =>
  job.id === ticket.id && job.purpose === ticket.input.purpose && job.chapter === ticket.input.chapter;

function useAssistant(api: CharacterApi) {
  const action = useAction();
  const [ticket, setTicket] = useState<Ticket>();
  const [entry, setEntry] = useState<Job>();
  const [error, setError] = useState("");
  const unresolved = useRef<Ticket>();
  useEffect(() => {
    if (!ticket || entry?.status !== "running") return;
    const controller = new AbortController();
    let timer: number;
    async function poll(current: Ticket) {
      try {
        const next = (await api.jobs(controller.signal)).entries.find(job => requestMatches(job, current));
        if (controller.signal.aborted) return;
        if (next) {
          setEntry(next);
          setError("");
          if (next.status !== "running") return;
        } else setError("还未读取到本次请求，正在等待该任务记录。");
      } catch (failure) {
        if (!controller.signal.aborted) setError("读取任务失败，稍后继续查询本次记录。 " + errorText(failure));
      }
      if (!controller.signal.aborted) timer = window.setTimeout(() => void poll(current), 1500);
    }
    timer = window.setTimeout(() => void poll(ticket), 750);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [api, entry?.status, ticket]);

  function start(input: JobInput) {
    if (entry?.status === "running" || action.busy) return;
    const current = unresolved.current || { id: globalThis.crypto.randomUUID(), input };
    unresolved.current = current;
    setTicket(current);
    setEntry(undefined);
    setError("");
    void action.run(async signal => {
      try {
        const { entry: response } = await api.start(current.id, current.input, signal);
        if (signal.aborted) return;
        if (!requestMatches(response, current)) throw new Error("助手返回的请求编号不符。");
        unresolved.current = undefined;
        setEntry(response);
      } catch (failure) {
        if (signal.aborted) return;
        // Validation and busy responses are determinate. Transport failures can
        // arrive after the server accepted the task, so replay only that UUID.
        if (failure instanceof CharacterCenterError && failure.status < 500) unresolved.current = undefined;
        setError(errorText(failure));
      }
    });
  }

  return { entry, ticket, error, start, busy: action.busy || entry?.status === "running",
    retryTransport: !!unresolved.current && !!error && !action.busy };
}

function JobStatus({ entry, busy, error, current }: { entry?: Job; busy: boolean; error: string; current: boolean }) {
  return <div className="space-y-2">
    <Problem message={error} />
    {busy && !entry && <p role="status" className={muted}>正在提交本次助手任务…</p>}
    {entry && <div className={box} aria-label="助手任务">
      <p role="status">{entry.status === "running" ? "任务进行中" : entry.status === "failed" ? "任务失败" : "任务已完成"}{entry.message ? " · " + entry.message : ""}</p>
      <p className={muted + " break-all"}>请求 {entry.id} · 第 {Number(entry.chapter)} 章
        {entry.attempt != null ? " · 第 " + entry.attempt + " 次尝试" : ""}
        {entry.model ? " · 模型 " + entry.model : ""}
        {entry.elapsed_seconds != null ? " · 耗时 " + entry.elapsed_seconds + " 秒" : ""}
        {entry.error_code ? " · " + entry.error_code : ""}</p>
      {(entry.stale || !current) && <Problem message="本次结果的依据已变化，请重新发起分析。" />}
    </div>}
  </div>;
}

export function FieldSuggestion({ api, person, section, chapter, revision, ready, onUse }: JobProps & {
  section: Section; onUse: (suggestion: CharacterPreview) => void;
}) {
  const [question, setQuestion] = useState("");
  const job = useAssistant(api);
  const current = job.ticket?.input.expected_revision === revision;
  const suggestion = current && !job.entry?.stale && job.entry?.status === "completed" ? job.entry.suggestion : undefined;
  return <section className={box} aria-label="可选表达建议">
    <h4 className="font-medium">AI 表达建议</h4>
    <p className={muted}>{person.name} · {section.label} · {section.source_id} · 第 {Number(chapter)} 章。提交后会发起助手任务。</p>
    <label className="grid gap-1 text-sm">表达建议说明
      <textarea className={field} aria-label="表达建议说明" value={question} rows={2} maxLength={12000} disabled={job.busy || job.retryTransport}
        onChange={event => setQuestion(event.target.value)} placeholder="希望保留什么，表达上想试试什么？" />
    </label>
    <button className={button} disabled={!ready || job.busy || !question.trim()} onClick={() => job.start({
      purpose: "character_edit", chapter, character_id: person.id, section_id: section.id, question, expected_revision: revision,
    })}>{job.retryTransport ? "重查本次请求" : job.entry?.status === "failed" ? "重新请求表达建议" : "请求表达建议"}</button>
    <JobStatus entry={job.entry} busy={job.busy} error={job.error} current={current} />
    {suggestion && suggestion.character_id === person.id && suggestion.section_id === section.id && suggestion.source_id === section.source_id &&
      <div className="space-y-2"><Comparison before={suggestion.before} after={suggestion.after} afterLabel="助手建议" />
        <button className={button} disabled={!ready || job.busy} onClick={() => onUse(suggestion)}>采用为修改预览</button>
      </div>}
  </section>;
}

export function SceneTrial({ api, person, roster, chapter, revision, ready }: JobProps & { roster: Person[] }) {
  const [cast, setCast] = useState([person.id]);
  const [scene, setScene] = useState("");
  const [baseline, setBaseline] = useState("");
  const [question, setQuestion] = useState("");
  const [preferred, setPreferred] = useState<Preferred>("candidate");
  const [reason, setReason] = useState("");
  const [guidance, setGuidance] = useState("");
  const [preference, setPreference] = useState<Preference>();
  const [error, setError] = useState("");
  const job = useAssistant(api);
  const action = useAction();
  const candidates = [person, ...roster.filter(row => row.id !== person.id)].filter(row => row.status === "structured");
  const current = job.ticket?.input.expected_revision === revision;
  const selected = job.ticket?.input;
  const result = current && !job.entry?.stale && job.entry?.status === "completed" ? job.entry.trial : undefined;
  const trial = result && selected?.purpose === "dialogue_trial" && result.chapter === selected.chapter
    && result.scene === selected.scene.trim() && result.character_ids.length === selected.character_ids.length
    && selected.character_ids.every(id => result.character_ids.includes(id)) ? result : undefined;
  const names = (ids: string[]) => ids.map(id => candidates.find(row => row.id === id)?.name || id).join("、");
  const locked = job.busy || action.busy;
  const [blocked, setBlocked] = useState(false);
  const castRelations = candidates.filter(row => cast.includes(row.id)).flatMap(row =>
    row.relationships.filter(relation => relation.target_id && cast.includes(relation.target_id))
      .map(relation => ({ from: row.name, relation })));
  if (person.status !== "structured") return <p className={box}>此旧格式档案需要先明确人物范围，才能参加场景试读。</p>;
  function submit() {
    if (!job.retryTransport) {
      setPreference(undefined); setReason(""); setGuidance(""); setPreferred("candidate"); setBlocked(false); setError("");
    }
    job.start({ purpose: "dialogue_trial", chapter, scene, baseline, question, character_ids: cast, expected_revision: revision });
  }
  function accept() {
    if (!job.entry || !trial || blocked) return;
    const entry = job.entry;
    setError("");
    void action.run(async signal => {
      try {
        const result = await api.accept(entry.id, preferred, reason, guidance, signal);
        if (!signal.aborted) setPreference(result.preference);
      } catch (failure) {
        if (!signal.aborted) {
          setError(errorText(failure));
          if (failure instanceof CharacterCenterError && failure.status === 409) setBlocked(true);
        }
      }
    });
  }
  return <section className={box} aria-label="场景试读">
    <h3 className="font-semibold">场景试读</h3>
    <p className={muted}>第 {Number(chapter)} 章。选择出场人物和当前场景，用作者提供的原文进行对照。</p>
    <fieldset className="flex flex-wrap gap-3 text-sm" disabled={locked || job.retryTransport}>
      <legend className="pb-2">出场人物（最多六位）</legend>
      {candidates.map(row => <label key={row.id} className="flex items-center gap-1">
        <input type="checkbox" checked={cast.includes(row.id)} disabled={row.id === person.id || !cast.includes(row.id) && cast.length === 6}
          onChange={event => setCast(values => event.target.checked ? [...values, row.id] : values.filter(id => id !== row.id))} />{row.name}
      </label>)}
    </fieldset>
    {castRelations.length > 0 && <details className="space-y-2 text-sm">
      <summary className="cursor-pointer">所选人物的关系来源</summary>
      <ul>{castRelations.map(({ from, relation }, index) => <li key={index} className={muted}>
        {from} → {relation.target} · {relation.source_id}{relation.nature ? " · " + relation.nature : ""}
      </li>)}</ul>
    </details>}
    <div className="space-y-2">
      <label className="grid gap-1 text-sm">场景
        <input className={field} aria-label="场景" maxLength={4000} value={scene} disabled={locked || job.retryTransport} onChange={event => setScene(event.target.value)} placeholder="与章纲匹配时请使用完整场景名称" />
      </label>
      <label className="grid gap-1 text-sm">对照原文
        <textarea className={field} aria-label="对照原文" rows={5} maxLength={12000} value={baseline} disabled={locked || job.retryTransport} onChange={event => setBaseline(event.target.value)} />
      </label>
      <label className="grid gap-1 text-sm">试读说明
        <textarea className={field} aria-label="试读说明" rows={2} maxLength={12000} value={question} disabled={locked || job.retryTransport}
          onChange={event => setQuestion(event.target.value)} placeholder="想比较的表达，以及需要保留的事实和结果" />
      </label>
      <button className={primary} disabled={locked || !ready || !scene.trim() || !baseline.trim() || !question.trim()} onClick={submit}>
        {job.retryTransport ? "重查本次请求" : job.entry?.status === "failed" ? "重新请求场景试读" : "请求场景试读"}
      </button>
    </div>
    {selected?.purpose === "dialogue_trial" && <p className={muted}>已提交范围 · 第 {Number(selected.chapter)} 章 · {selected.scene} · {names(selected.character_ids)} · 对照来自本次填写的原文</p>}
    <JobStatus entry={job.entry} busy={job.busy} error={job.error} current={current} />
    {trial && <div className="space-y-3">
      <h4 className="font-medium">{trial.scene} · {names(trial.character_ids)}</h4>
      <Comparison before={trial.baseline} after={trial.candidate} afterLabel="试读候选" />
      <h4 className="font-medium">作者核对点</h4>
      <ul className="list-disc space-y-1 pl-5">{trial.checks.map((check, index) => <li key={index} className={prose}>{check}</li>)}</ul>
      {preference ? <div role="status" className={box}>
        <p>已保存{preference.preferred === "baseline" ? "原文" : "候选"}的表达偏好。</p>
        <p className={muted}>{preference.reason} · {preference.carry_forward}</p>
        {preference.production_match === true ? <p className={muted}>已匹配本章大纲中的场景和出场人物，后续生成可读取这条表达参考。</p>
          : preference.production_match === false ? <p className={muted}>已保存为后续同场景试读的参考。生成要读取这条偏好，请在本章大纲用「### 场景：场景名称」和同段「出场人物：姓名」精确标明场景和人物。</p>
          : <p className={muted}>这条记录的生成匹配情况待确认。</p>}
      </div> : <>
        <p className={muted}>保存你希望沿用的表达和理由。试读文本仍留在对照中。</p>
        <fieldset className="grid gap-2" disabled={locked || blocked}>
          <legend className="text-sm">偏好的版本</legend>
          <select aria-label="偏好的版本" className={field} value={preferred} onChange={event => setPreferred(event.target.value as Preferred)}>
            <option value="baseline">原文</option><option value="candidate">试读候选</option>
          </select>
          <textarea aria-label="采用理由" className={field} rows={2} maxLength={2000} value={reason} placeholder="采用理由" onChange={event => setReason(event.target.value)} />
          <textarea aria-label="保留的表达建议" className={field} rows={2} maxLength={2000} value={guidance} placeholder="保留的表达建议" onChange={event => setGuidance(event.target.value)} />
          <button className={primary} disabled={!ready || !reason.trim() || !guidance.trim()} onClick={accept}>确认并保存表达偏好</button>
        </fieldset>
        <Problem message={error} />
      </>}
    </div>}
  </section>;
}
