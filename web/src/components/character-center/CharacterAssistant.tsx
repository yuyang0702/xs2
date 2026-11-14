import { useMemo, useState } from "react";
import { CharacterCenterError, errorText, type CharacterApi, type CharacterPreview, type Job, type Person, type Preference, type Preferred, type Rehearsal, type Section } from "./api";
import { box, button, Comparison, field, muted, primary, Problem, prose } from "./ui";
import { useAction } from "./useAction";
import { sameCast, useAssistant, type JobScope } from "./useAssistant";

type JobProps = { api: CharacterApi; person: Person; chapter: string; revision: string; ready: boolean };
const statusLabels: Record<Job["status"], string> = { running: "进行中", completed: "已完成", failed: "失败" };

function SavedJobs({ job, ready, describe, onSelectionChange }: {
  job: ReturnType<typeof useAssistant>; ready: boolean; describe?: (entry: Job) => string; onSelectionChange?: () => void;
}) {
  return <div className="space-y-2">
    <div className="flex flex-wrap items-end gap-2">
      <label className="grid min-w-0 gap-1 text-sm">已保存的助手任务
        <select aria-label="已保存的助手任务" className={field + " max-w-full"} value={job.entry?.id || ""}
          disabled={!ready || job.submitting || job.retryTransport}
          onChange={event => { onSelectionChange?.(); job.select(event.target.value); }}>
          <option value="">{job.historyLoading ? "正在读取任务记录…" : job.history.length ? "选择一项任务查看" : "当前范围暂无任务"}</option>
          {job.history.map(entry => <option value={entry.id} key={entry.id}>
            {statusLabels[entry.status]}{entry.stale ? " · 依据已失效" : ""}{describe ? " · " + describe(entry) : ""}
            {entry.created_at ? " · " + new Date(entry.created_at).toLocaleString() : ""}
          </option>)}
        </select>
      </label>
      <button className={button} disabled={!ready || job.submitting || job.historyLoading} onClick={job.refreshHistory}>刷新助手记录</button>
    </div>
    <Problem message={job.historyError} />
  </div>;
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

export function FieldSuggestion({ api, person, section, chapter, revision, ready, onUse, onSelectionChange }: JobProps & {
  section: Section; onUse: (suggestion: CharacterPreview) => void; onSelectionChange: () => void;
}) {
  const [question, setQuestion] = useState("");
  const scope = useMemo<JobScope>(() => ({ purpose: "character_edit", chapter, personId: person.id,
    sectionId: section.id, sourceId: section.source_id }), [chapter, person.id, section.id, section.source_id]);
  const job = useAssistant(api, scope);
  const current = (job.selection?.source?.revision ?? job.selection?.ticket?.input.expected_revision) === revision;
  const suggestion = current && !job.entry?.stale && job.entry?.status === "completed" ? job.entry.suggestion : undefined;
  return <section className={box} aria-label="可选表达建议">
    <h4 className="font-medium">AI 表达建议</h4>
    <p className={muted}>{person.name} · {section.label} · {section.source_id} · 第 {Number(chapter)} 章。提交后会发起助手任务。</p>
    <SavedJobs job={job} ready={ready} onSelectionChange={onSelectionChange} />
    <label className="grid gap-1 text-sm">表达建议说明
      <textarea className={field} aria-label="表达建议说明" value={question} rows={2} maxLength={12000} disabled={job.busy || job.retryTransport}
        onChange={event => setQuestion(event.target.value)} placeholder="希望保留什么，表达上想试试什么？" />
    </label>
    <button className={button} disabled={!ready || job.busy || !question.trim()} onClick={() => {
      onSelectionChange();
      job.start({ purpose: "character_edit", chapter, character_id: person.id, section_id: section.id, question, expected_revision: revision });
    }}>{job.retryTransport ? "重查本次请求" : job.entry?.status === "failed" ? "重新请求表达建议" : "请求表达建议"}</button>
    <JobStatus entry={job.entry} busy={job.submitting} error={job.error} current={current} />
    {suggestion && suggestion.revision === revision && suggestion.character_id === person.id && suggestion.section_id === section.id && suggestion.source_id === section.source_id &&
      <div className="space-y-2"><Comparison before={suggestion.before} after={suggestion.after} afterLabel="助手建议" />
        <button className={button} disabled={!ready || job.busy} onClick={() => onUse(suggestion)}>采用为修改预览</button>
      </div>}
  </section>;
}

export function SceneTrial({ api, person, roster, chapter, revision, ready }: JobProps & { roster: Person[] }) {
  const [cast, setCast] = useState([person.id]);
  const [rehearse, setRehearse] = useState(false);
  const [sceneCard, setSceneCard] = useState("");
  const [ending, setEnding] = useState("");
  const [scene, setScene] = useState("");
  const [baseline, setBaseline] = useState("");
  const [question, setQuestion] = useState("");
  const [preferred, setPreferred] = useState<Preferred>("candidate");
  const [reason, setReason] = useState("");
  const [guidance, setGuidance] = useState("");
  const [preference, setPreference] = useState<Preference>();
  const [error, setError] = useState("");
  const scope = useMemo<JobScope>(() => ({ purpose: "dialogue_trial", chapter, personId: person.id }), [chapter, person.id]);
  const job = useAssistant(api, scope);
  const action = useAction();
  const people = [person, ...roster.filter(row => row.id !== person.id)];
  const candidates = people.filter(row => row.status === "structured");
  const current = (job.selection?.source?.revision ?? job.selection?.ticket?.input.expected_revision) === revision;
  const input = job.selection?.ticket?.input;
  const binding = job.selection?.source ?? (input?.purpose === "dialogue_trial" ? input : undefined);
  const result = current && !job.entry?.stale && job.entry?.status === "completed" ? job.entry.trial : undefined;
  const trial = result && binding?.scene && result.chapter === binding.chapter && result.scene === binding.scene.trim()
    && sameCast(result.character_ids, binding.character_ids) ? result : undefined;
  const names = (ids: string[]) => ids.map(id => people.find(row => row.id === id)?.name || id).join("、");
  const locked = job.busy || action.busy;
  const castLimit = rehearse ? 2 : 6;
  const validTrial = rehearse ? cast.length === 2 && sceneCard.trim() && ending.trim() : baseline.trim();
  const rehearsal = trial?.rehearsal;
  const beforeLabel = rehearsal ? "A 版 · 现有分场写手" : "原文";
  const afterLabel = rehearsal ? "B 版 · 试演后成稿" : "试读候选";
  const [blocked, setBlocked] = useState(false);
  const castRelations = candidates.filter(row => cast.includes(row.id)).flatMap(row =>
    row.relationships.filter(relation => relation.target_id && cast.includes(relation.target_id))
      .map(relation => ({ from: row.name, relation })));
  if (person.status !== "structured") return <p className={box}>此旧格式档案需要先明确人物范围，才能参加场景试读。</p>;
  function resetPreference() {
    setPreference(undefined); setReason(""); setGuidance(""); setPreferred("candidate"); setBlocked(false); setError("");
  }
  function submit() {
    if (!job.retryTransport) resetPreference();
    const common = { purpose: "dialogue_trial" as const, chapter, scene, question, character_ids: cast, expected_revision: revision };
    job.start(rehearse ? { ...common, trial_mode: "role_rehearsal", scene_card: sceneCard, ending } : { ...common, baseline });
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
    <p className={muted}>第 {Number(chapter)} 章</p>
    <SavedJobs job={job} ready={ready && !action.busy} onSelectionChange={resetPreference}
      describe={entry => entry.character_source?.scene
        ? entry.character_source.scene + " · " + names(entry.character_source.character_ids)
          + (entry.character_source.trial_mode === "role_rehearsal" ? " · 分角色试演" : "") : "本次提交"} />
    <label className="grid gap-1 text-sm">试读方式
      <select className={field} value={rehearse ? "roles" : "rewrite"} disabled={locked || job.retryTransport} onChange={event => {
        const enabled = event.target.value === "roles";
        setRehearse(enabled);
        if (enabled) setCast(values => values.slice(0, 2));
      }}>
        <option value="rewrite">原文改写</option><option value="roles">分角色试演对比</option>
      </select>
    </label>
    <fieldset className="flex flex-wrap gap-3 text-sm" disabled={locked || job.retryTransport}>
      <legend className="pb-2">{rehearse ? "出场人物（选两位，当前人物先开口）" : "出场人物（最多六位）"}</legend>
      {candidates.map(row => <label key={row.id} className="flex items-center gap-1">
        <input type="checkbox" checked={cast.includes(row.id)} disabled={row.id === person.id || !cast.includes(row.id) && cast.length >= castLimit}
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
      {rehearse ? <>
        <label className="grid gap-1 text-sm">共用场景卡
          <textarea className={field} rows={4} maxLength={6000} value={sceneCard} disabled={locked || job.retryTransport}
            onChange={event => setSceneCard(event.target.value)} placeholder="场景从哪里开始、人物要做什么、必须发生什么" />
        </label>
        <label className="grid gap-1 text-sm">共用结局
          <textarea className={field} rows={2} maxLength={2000} value={ending} disabled={locked || job.retryTransport}
            onChange={event => setEnding(event.target.value)} placeholder="写到哪一个决定或结果为止" />
        </label>
      </> : <label className="grid gap-1 text-sm">对照原文
        <textarea className={field} aria-label="对照原文" rows={5} maxLength={12000} value={baseline} disabled={locked || job.retryTransport} onChange={event => setBaseline(event.target.value)} />
      </label>}
      <label className="grid gap-1 text-sm">试读说明
        <textarea className={field} aria-label="试读说明" rows={2} maxLength={12000} value={question} disabled={locked || job.retryTransport}
          onChange={event => setQuestion(event.target.value)} placeholder={rehearse ? "共同的篇幅、视角或想比较的表达" : "想比较的表达，以及需要保留的事实和结果"} />
      </label>
      <button className={primary} disabled={locked || !ready || !job.retryTransport && (!scene.trim() || !validTrial || !question.trim())} onClick={submit}>
        {job.retryTransport ? "重查本次请求" : job.entry?.status === "failed" ? "重新请求场景试读" : "请求场景试读"}
      </button>
    </div>
    {binding?.scene && <p className={muted}>任务范围 · 第 {Number(binding.chapter)} 章 · {binding.scene} · {names(binding.character_ids)}</p>}
    <JobStatus entry={job.entry} busy={job.submitting} error={job.error} current={current} />
    {trial && <div className="space-y-3">
      <h4 className="font-medium">{trial.scene} · {names(trial.character_ids)}</h4>
      <Comparison before={trial.baseline} after={trial.candidate} beforeLabel={beforeLabel} afterLabel={afterLabel} />
      {rehearsal ? <RehearsalDetails record={rehearsal} sceneCard={binding?.trial_mode === "role_rehearsal" ? binding.scene_card : undefined}
        ending={binding?.trial_mode === "role_rehearsal" ? binding.ending : undefined} /> : <>
        <h4 className="font-medium">作者核对点</h4>
        <ul className="list-disc space-y-1 pl-5">{trial.checks.map((check, index) => <li key={index} className={prose}>{check}</li>)}</ul>
      </>}
      {preference ? <div role="status" className={box}>
        <p>已保存「{preference.preferred === "baseline" ? beforeLabel : afterLabel}」的表达偏好。</p>
        <p className={muted}>{preference.reason} · {preference.carry_forward}</p>
        {(preference.preferred !== preferred || preference.reason !== reason.trim() || preference.carry_forward !== guidance.trim()) &&
          <p className={muted}>此任务已有保存记录，以上为原记录。</p>}
        {preference.production_match === true ? <p className={muted}>已匹配本章大纲中的场景和出场人物，后续生成可读取这条表达参考。</p>
          : preference.production_match === false ? <p className={muted}>已保存为后续同场景试读的参考。生成要读取这条偏好，请在本章大纲用「### 场景：场景名称」和同段「出场人物：姓名」精确标明场景和人物。</p>
          : <p className={muted}>这条记录的生成匹配情况待确认。</p>}
      </div> : <>
        <p className={muted}>保存你希望沿用的表达和理由。试读文本仍留在对照中。</p>
        <fieldset className="grid gap-2" disabled={locked || blocked}>
          <legend className="text-sm">偏好的版本</legend>
          <select aria-label="偏好的版本" className={field} value={preferred} onChange={event => setPreferred(event.target.value as Preferred)}>
            <option value="baseline">{beforeLabel}</option><option value="candidate">{afterLabel}</option>
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

function RehearsalDetails({ record, sceneCard, ending }: { record: Rehearsal; sceneCard?: string; ending?: string }) {
  const { blind, timings } = record;
  const label = (key: string) => `${key}（${blind.labels[key] === "baseline" ? "A 版" : "B 版"}）`;
  const turnSeconds = record.turns.reduce((total, turn) => total + turn.seconds, 0);
  return <div className="space-y-3">
    <p className={muted}>{record.writer} · A 版 {timings.direct} 秒 · B 版 {(timings.director + turnSeconds + timings.write).toFixed(1)} 秒{timings.precision != null && ` · 确数验收 ${timings.precision} 秒`} · 盲读 {timings.blind} 秒</p>
    <details className={box}>
      <summary className="cursor-pointer font-medium">共用场景与角色试演</summary>
      {sceneCard && <p className={prose}>场景卡　{sceneCard}</p>}
      {ending && <p className={prose}>结局　{ending}</p>}
      <p className={prose}>导演开场（{timings.director} 秒）　{record.public_start}</p>
      {record.roles.map(role => <div key={role.name} className={prose}>
        <h5 className="font-medium">{role.name}的试演资料</h5>
        <p>所知　{role.knowledge}</p><p>目的　{role.goal}</p><p>口气　{role.voice}</p>
      </div>)}
      <ol className="list-decimal space-y-2 pl-5">{record.turns.map((turn, index) => <li key={index} className={prose}>
        <strong>{turn.name}</strong>（{turn.seconds} 秒）{turn.action && `　${turn.action}`}{turn.speech && `　「${turn.speech}」`}
      </li>)}</ol>
      <p className={muted}>主写手成稿 {timings.write} 秒</p>
    </details>
    <div className={box}>
      <h4 className="font-medium">独立盲读 · {blind.preferred === "tie" ? "两版并列" : `偏好${label(blind.preferred)}`}</h4>
      <p className={prose}>{blind.reason}</p><p className={prose}>{blind.endings}</p>
      {Object.entries(blind.readings).map(([key, reading]) => <div key={key} className="space-y-1">
        <h5 className="font-medium">{label(key)}</h5>
        <p className={prose}>{reading.voice}</p><p className={prose}>{reading.exchange}</p>
        {reading.strengths.map((item, index) => <p key={index} className={prose}>自然处　「{item.quote}」　{item.comment}</p>)}
        {reading.stiffness.map((item, index) => <p key={index} className={prose}>生硬处　「{item.quote}」　{item.comment}</p>)}
      </div>)}
    </div>
  </div>;
}
