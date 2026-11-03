import { useEffect, useState } from "react";
import { errorText, type Audit, type CharacterApi, type Finding, type Override, type Policy, type PolicyMode } from "./api";
import { box, button, Comparison, field, muted, primary, Problem, prose, useAction } from "./ui";

const status: Record<string, string> = { present: "可读", missing: "缺失", unavailable: "无法读取", candidate: "待作者核对" };
const categories: Record<string, string> = { expression_advice: "表达建议", protected: "受保护内容", unknown: "类别待核对" };
type Props = { api: CharacterApi; chapter: string; onSaved: () => void };

export default function BookPolicy({ api, chapter, onSaved }: Props) {
  const [policy, setPolicy] = useState<Policy>();
  const [audit, setAudit] = useState<Audit>();
  const [mode, setMode] = useState<PolicyMode>();
  const [finding, setFinding] = useState<Finding>();
  const [replacement, setReplacement] = useState("");
  const [preview, setPreview] = useState<Override>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [version, setVersion] = useState(0);
  const [loaded, setLoaded] = useState(-1);
  const [retract, setRetract] = useState(false);
  const action = useAction();
  const ready = version === loaded && !action.busy;
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    void Promise.all([api.policy(controller.signal), api.audit(chapter, controller.signal)]).then(([read, inspection]) => {
      if (controller.signal.aborted) return;
      setPolicy(read); setAudit(inspection); setMode(value => value ?? read.mode); setLoaded(version);
    }).catch(failure => { if (!controller.signal.aborted) setError(errorText(failure)); });
    return () => controller.abort();
  }, [api, chapter, version]);

  const matching = policy && audit?.revision === policy.revision;
  const stale = policy?.stale_overrides || [];
  const savedHere = finding && policy?.overrides.find(row => row.source_id === finding.source_id && row.quote === finding.quote && row.start === finding.start);
  const staleIds = new Set(stale.map(row => row.preview_id));
  const existing = (policy?.overrides || []).filter(row => !staleIds.has(row.preview_id) && row !== savedHere);
  function refresh() {
    setPreview(undefined);
    setVersion(value => value + 1);
  }
  function save(values: Parameters<CharacterApi["savePolicy"]>[1], message: string) {
    if (!ready || !policy) return;
    setError("");
    setNotice("");
    void action.run(async signal => {
      try {
        const value = await api.savePolicy(policy.revision, values, signal);
        if (signal.aborted) return;
        setPolicy(value); setMode(value.mode); setPreview(undefined); setFinding(undefined); setRetract(false);
        setNotice(message);
        refresh();
        onSaved();
      } catch (failure) {
        if (!signal.aborted) { setPreview(undefined); setError(errorText(failure) + " 请刷新体检后重新预览。"); }
      }
    });
  }

  function previewOverride() {
    if (!ready || !policy || !finding || !matching || !finding.override_eligible) return;
    setError(""); setPreview(undefined);
    void action.run(async signal => {
      try {
        const value = await api.previewRule(policy.revision, finding, replacement, signal);
        if (!signal.aborted) setPreview(value);
      } catch (failure) { if (!signal.aborted) setError(errorText(failure)); }
    });
  }

  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-xl font-semibold">本书叙述偏好与规则体检</h2>
      <button className={button} onClick={refresh} disabled={action.busy}>刷新规则体检</button>
    </div>
    <Problem message={error} />
    {notice && <p role="status" className={muted}>{notice}</p>}
    {!ready && !action.busy && !error && <p className={muted} role="status">正在读取偏好与第 {Number(chapter)} 章规则…</p>}
    {policy && <section className={box} aria-label="本书叙述偏好">
      <p className={muted}>已保存模式 · {policy.mode === "inherit" ? "继承原规则" : "叙述优先"}</p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-sm">本书模式<select aria-label="本书模式" className={field} value={mode ?? policy.mode}
          disabled={!ready} onChange={event => setMode(event.target.value as PolicyMode)}>
          <option value="inherit">继承原规则</option><option value="narrative_led">叙述优先</option>
        </select></label>
        <button className={primary} disabled={!ready || !mode || mode === policy.mode} onClick={() => save({ mode }, "本书模式已保存。")}>保存本书模式</button>
      </div>
      <p className={muted}>叙述优先让行动、感知和取舍承担更多叙事。可确认表达覆盖以供后续生成使用。</p>
      {policy.overrides.length > 0 && <details className="space-y-2">
        <summary className="cursor-pointer">已保存覆盖 · {policy.overrides.length} 条</summary>
        <ul className="space-y-2">{policy.overrides.map(row => <li key={row.preview_id} className="break-words text-sm">{row.source_id} · {row.quote} → {row.replacement}</li>)}</ul>
        {retract ? <div className="flex flex-wrap gap-2">
          <button className={primary} disabled={!ready} onClick={() => save({ overrides: [] }, "已撤回本书的全部表达覆盖。")}>确认撤回全部覆盖</button>
          <button className={button} onClick={() => setRetract(false)}>取消撤回</button>
        </div> : <button className={button} disabled={!ready} onClick={() => setRetract(true)}>撤回全部覆盖</button>}
      </details>}
      {(stale.length ? stale : audit?.stale_overrides || []).map(row => <p className={muted} key={row.preview_id}>
        已失效 · {row.source_id} · {row.quote} · {row.reason}
      </p>)}
    </section>}
    {audit && <section className={box} aria-label="规则体检">
      <h3 className="font-semibold">第 {Number(audit.chapter)} 章规则体检</h3>
      {!matching && <Problem message="偏好和体检来自不同修订，请刷新后再预览。" />}
      <details className="space-y-2"><summary className="cursor-pointer text-sm">本次核对的资料</summary>
        <ul>{audit.sources.map(source => <li className={muted + " break-all"} key={source.source_id}>
          {source.source_id} · {status[source.status] || "状态待确认"} · {source.provenance === "unknown" ? "来源归属待核对" : source.provenance}
        </li>)}</ul>
      </details>
      {audit.findings.length === 0 && <p className={muted}>没有发现需要核对的表达线索。</p>}
      {audit.findings.map(row => <article key={row.source_id + ":" + row.start} className={box}>
        <p className={muted}>{row.source_id} · 第 {row.line} 行 · {categories[row.source_category] || "类别待核对"} · {status[row.review_status] || "状态待确认"}</p>
        <p className={muted}>{row.provenance === "unknown" ? "来源归属待核对" : row.provenance}</p>
        <blockquote className={prose + " border-l-2 border-primary/30 pl-3"}>{row.quote}</blockquote>
        <p className={muted}>{row.reason}</p>
        {row.suggestion && <p className={prose}>{row.suggestion}</p>}
        {row.override_eligible ? <button className={button} disabled={!ready || !matching} onClick={() => {
          setFinding(row); setReplacement(row.suggestion); setPreview(undefined); setError(""); setNotice("");
        }}>选择表达建议</button> : <p className={muted}>仅供作者核对。</p>}
        {finding?.source_id === row.source_id && finding.start === row.start && <div className="space-y-3">
          <label className="grid gap-1 text-sm">替代表达
            <textarea aria-label="替代表达" className={field} rows={2} value={replacement} disabled={action.busy}
              onChange={event => { setReplacement(event.target.value); setPreview(undefined); }} />
          </label>
          <button className={primary} disabled={!ready || !matching || !replacement.trim() || /[\r\n]/.test(replacement)} onClick={previewOverride}>预览覆盖</button>
          {preview && <section className={box} aria-label="表达覆盖比较">
            <p className={muted}>{preview.source_id} · 第 {row.line} 行 · 用于后续生成时的有效表达</p>
            <Comparison before={preview.before} after={preview.after} />
            {stale.length > 0 && <p className={muted}>确认本次覆盖会从保存列表中清除已失效的覆盖。</p>}
            <div className="flex flex-wrap gap-2">
              <button className={primary} disabled={!ready || !matching || preview.revision !== policy?.revision}
                onClick={() => save({ mode: "narrative_led", overrides: [...existing, preview] }, "表达覆盖已保存，本书采用叙述优先。")}>确认覆盖并采用叙述优先</button>
              <button className={button} disabled={action.busy} onClick={() => setPreview(undefined)}>取消覆盖预览</button>
            </div>
          </section>}
        </div>}
      </article>)}
    </section>}
  </div>;
}
