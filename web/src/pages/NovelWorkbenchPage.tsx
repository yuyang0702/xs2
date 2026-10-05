import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, BookOpenText, Check, ChevronRight, CircleAlert, FileText, Loader2, Play, RefreshCw } from "lucide-react";
import { createTask, getTask, getWorkflow, listWorkflows, readWorkflowWorkspaceFile, runTask } from "../lib/api";
import type { WorkflowVariable } from "../types";

const PREFIX = "xs2-novel-flywheel-";
const steps = [
  { id: "reference-distillation", title: "蒸馏参考资料", group: "资料学习", description: "提炼参考资料中的写法，保留来源依据。", fields: ["reference_path", "window_size"], artifact: "learning/candidates.json" },
  { id: "adopt-reference", title: "选择要采用的写法", group: "资料学习", description: "勾选适合这本书的写法。也可以不选，保持原创设定。", fields: [], artifact: "learning/active_context.md" },
  { id: "build", title: "建立世界观", group: "创作规划", description: "填写故事创意，建立世界运行规则。后续步骤会沿用这些设置。", fields: ["premise", "genre", "language"], artifact: "meta/world_foundation.md" },
  { id: "character", title: "创建角色", group: "创作规划", description: "根据故事创意和世界观创建角色档案与声音。", fields: [], artifact: "meta/character_profiles.md" },
  { id: "story-plan", title: "规划故事", group: "创作规划", description: "把世界和角色汇总为故事规划与风格档案。", fields: [], artifact: "meta/story_plan.md" },
  { id: "outline", title: "生成卷纲与近纲", group: "创作规划", description: "设置作品规模，把故事拆成卷和近期章节。", fields: ["volume_number", "estimated_length", "words_per_chapter"], artifact: "outline/near_term_outline.md" },
  { id: "mvp", title: "生成章节正文", group: "正文生产", description: "写下这一章的重点，系统沿用设定、已选写法和叙事视角。", fields: ["human_intent", "world_intent", "target_word_count", "writer_type"], artifact: "story/{chapter}/chapter.md" },
  { id: "polish", title: "润色本章", group: "正文生产", description: "改善语言与阅读节奏，保持既定视角。", fields: [], artifact: "story/{chapter}/chapter.md" },
  { id: "post-hoc", title: "质量审核与后验", group: "质量审核", description: "核查章节事实和连续性，将变化回写到作品档案。", fields: [], artifact: "story/{chapter}/diff_story_confirmed.md" },
  { id: "export", title: "导出成品", group: "导出成品", description: "按章节顺序合并正文，保存成品和导出清单。", fields: [], artifact: "export/manuscript.md" },
];
const defaults: Record<string, string> = {
  reference_path: "references/source.txt", window_size: "4200", premise: "", genre: "都市情感", language: "中文",
  volume_number: "1", estimated_length: "中", words_per_chapter: "2000-2500", latest_chapter: "0000",
  chapter_number: "0001", prev_chapter: "0000", human_intent: "", world_intent: "", target_word_count: "3000-4000",
  writer_type: "single", narrative_pov: "third_person", output_path: "export/manuscript.md", manifest_path: "export/manifest.json",
};
const labels: Record<string, string> = { reference_path: "参考资料路径", window_size: "每个分析窗口的长度", premise: "故事创意", genre: "题材类型", language: "输出语言", volume_number: "目标卷号", estimated_length: "预计篇幅", words_per_chapter: "每章字数", human_intent: "本章想写什么", world_intent: "世界发生的变化（可选）", target_word_count: "目标字数", writer_type: "写手模式" };
type TaskRef = { workflow_id: string; task_id: string };
type Project = { index: number; values: Record<string, string>; refs: Record<string, TaskRef>; completed: string[]; selected: string[]; autoNext: boolean };
type Candidate = { candidate_id: string; mechanism: string; transfer_guidance: string; constraints: string[]; evidence?: Array<{ excerpt: string }> };
type Extension = { workflow_id: string; name: string; node_count: number };
const terminal = ["completed", "failed", "stopped", "cancelled"];
const storageKey = (workspace: string) => `xs2-novel-wizard-v1:${workspace.replace(/\//g, "\\").replace(/\\+$/, "").toLowerCase()}`;
function restore(workspace: string): Project {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey(workspace)) || "null");
    if (saved && Number.isInteger(saved.index) && saved.index >= 0 && saved.index < steps.length) {
      return { index: saved.index, values: { ...defaults, ...saved.values }, refs: saved.refs || {}, completed: saved.completed || [], selected: saved.selected || [], autoNext: saved.autoNext === true };
    }
  } catch { /* Invalid browser draft starts at the first step. */ }
  return { index: 0, values: { ...defaults }, refs: {}, completed: [], selected: [], autoNext: false };
}
function statusLabel(status: string) {
  return ({ pending: "等待启动", running: "运行中", pre_running: "准备中", completed: "已完成", failed: "执行失败", stopped: "已停止", cancelled: "已取消" } as Record<string, string>)[status] || status;
}
const fieldClass = "w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:opacity-60";

export default function NovelWorkbenchPage() {
  const [workspace, setWorkspace] = useState(() => localStorage.getItem("xs2-novel-workspace") || "C:\\xs2\\DeterminFlow\\data\\workspaces\\xs2-novel-workbench");
  return <NovelWizard key={storageKey(workspace)} workspace={workspace} onWorkspaceChange={(next) => { localStorage.setItem("xs2-novel-workspace", next); setWorkspace(next); }} />;
}

function NovelWizard({ workspace, onWorkspaceChange }: { workspace: string; onWorkspaceChange: (next: string) => void }) {
  const [project, setProject] = useState(() => restore(workspace));
  const [workspaceDraft, setWorkspaceDraft] = useState(workspace);
  const [extensions, setExtensions] = useState<Extension[]>([]);
  const [extensionId, setExtensionId] = useState("");
  const [extensionFields, setExtensionFields] = useState<WorkflowVariable[]>([]);
  const [extensionValues, setExtensionValues] = useState<Record<string, string>>({});
  const [extensionRef, setExtensionRef] = useState<TaskRef | null>(null);
  const [task, setTask] = useState<any>(null);
  const [verified, setVerified] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState("");
  const [candidateSet, setCandidateSet] = useState<{ candidates: Candidate[]; candidates_sha256: string } | null>(null);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [preview, setPreview] = useState("");
  const requestEpoch = useRef(0);
  const launchGuard = useRef(false);
  const autoAdvancedKey = useRef("");
  const autoStartedKey = useRef("");
  const autoStartIndex = useRef<number | null>(null);
  const step = steps[project.index];
  const workflowId = extensionId || PREFIX + step.id;
  const ref = extensionId ? extensionRef : project.refs[step.id];
  const title = extensions.find((item) => item.workflow_id === extensionId)?.name || step.title;
  const busy = launching || (!!task && !terminal.includes(task.status));
  const done = verified && task?.status === "completed" && task.workflow_id === workflowId && task.task_id === ref?.task_id;
  const artifact = step.artifact.replace("{chapter}", project.values.chapter_number);
  const setValue = (key: string, value: string) => setProject((current) => ({ ...current, values: { ...current.values, [key]: value } }));

  useEffect(() => { localStorage.setItem(storageKey(workspace), JSON.stringify(project)); }, [workspace, project]);
  useEffect(() => {
    let active = true;
    const discover = () => void listWorkflows().then((items) => { if (active) setExtensions(items.filter((item) => !steps.some((step) => PREFIX + step.id === item.workflow_id) && item.workflow_id !== PREFIX + "market-ranking")); }).catch(() => {});
    discover();
    const timer = window.setInterval(discover, 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  useEffect(() => {
    let active = true;
    setExtensionFields([]);
    if (extensionId) void getWorkflow(extensionId).then(({ definition }) => {
      if (!active) return;
      const fields = (definition.variables || []).filter((field) => !field.hidden && field.source_type !== "output");
      setExtensionFields(fields);
      setExtensionValues(Object.fromEntries(fields.map((field) => [field.key, field.default || ""])));
    }).catch((failure) => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, [extensionId]);

  const refreshTask = useCallback(async () => {
    if (!ref) return;
    const epoch = requestEpoch.current;
    try {
      const result = await getTask(ref.workflow_id, ref.task_id);
      if (epoch !== requestEpoch.current) return;
      setTask(result.task);
      setVerified(false);
      if (result.task.status === "completed") {
        if (!extensionId) {
          const output = await readWorkflowWorkspaceFile(ref.workflow_id, ref.task_id, artifact);
          if (epoch !== requestEpoch.current) return;
          if (!output.content.trim()) throw new Error("任务已结束，但预期产物为空，请检查任务结果后重试。");
          setPreview(output.content);
        }
        if (epoch === requestEpoch.current) { setVerified(true); setError(""); }
      }
    } catch (failure) { if (epoch === requestEpoch.current) setError(failure instanceof Error ? failure.message : "读取任务失败"); }
  }, [ref?.workflow_id, ref?.task_id, artifact, extensionId]);
  useEffect(() => {
    requestEpoch.current += 1;
    setTask(null); setVerified(false); setError(""); setPreview("");
    if (!ref) return;
    void refreshTask();
    const timer = window.setInterval(refreshTask, 3000);
    return () => { requestEpoch.current += 1; window.clearInterval(timer); };
  }, [refreshTask]);

  useEffect(() => {
    let active = true;
    const source = project.refs["reference-distillation"];
    if (extensionId || !source || !["reference-distillation", "adopt-reference"].includes(step.id)) return;
    setLoadingCandidates(true);
    void readWorkflowWorkspaceFile(source.workflow_id, source.task_id, "learning/candidates.json").then((output) => {
      if (active) setCandidateSet(JSON.parse(output.content));
    }).catch(() => { if (active) setCandidateSet(null); }).finally(() => { if (active) setLoadingCandidates(false); });
    return () => { active = false; };
  }, [project.refs["reference-distillation"]?.task_id, step.id, extensionId, done]);

  const launch = async () => {
    if (launchGuard.current || busy || done) return;
    launchGuard.current = true; setLaunching(true); setError("");
    try {
      if (!workspace.trim()) throw new Error("请先填写作品工作区。");
      const parameters: Record<string, string> = extensionId ? { ...extensionValues } : { ...project.values };
      if (!extensionId && step.id === "adopt-reference") {
        if (!candidateSet) throw new Error("尚未读取到蒸馏结果，请刷新结果后再采用写法。");
        parameters.selection_json = JSON.stringify({ candidates_sha256: candidateSet.candidates_sha256, selected_candidate_ids: project.selected });
      }
      const { definition } = await getWorkflow(workflowId);
      const inputs = Object.fromEntries((definition.variables || []).filter((field) => field.source_type !== "output" && field.type !== "file" && parameters[field.key] !== undefined).map((field) => [field.key, parameters[field.key]]));
      const missing = (definition.variables || []).find((field) => field.required && !field.hidden && field.type !== "file" && !(inputs[field.key] ?? field.default)?.trim());
      if (missing) throw new Error(`请填写${missing.name || missing.key}。`);
      const created = await createTask(workflowId, inputs, undefined, undefined, workspace);
      const nextRef = { workflow_id: workflowId, task_id: created.task_id };
      if (extensionId) setExtensionRef(nextRef);
      else setProject((current) => ({ ...current, refs: { ...current.refs, [step.id]: nextRef } }));
      await runTask(workflowId, created.task_id);
      setTask({ ...nextRef, status: "running", name: title });
    } catch (failure) { setError(failure instanceof Error ? failure.message : "启动失败"); }
    finally { launchGuard.current = false; setLaunching(false); }
  };
  useEffect(() => {
    if (extensionId || !project.autoNext || !done || project.index >= steps.length - 1) return;
    const key = `${step.id}:${ref?.task_id || ""}`;
    if (autoAdvancedKey.current === key) return;
    autoAdvancedKey.current = key;
    autoStartIndex.current = project.index + 1;
    setProject((current) => ({ ...current, index: current.index + 1, completed: [...new Set([...current.completed, step.id])] }));
  }, [done, extensionId, project.autoNext, project.index, ref?.task_id, step.id]);
  useEffect(() => {
    if (extensionId || !project.autoNext || autoStartIndex.current !== project.index || project.refs[step.id] || launching || task || (step.id === "adopt-reference" && !candidateSet)) return;
    const key = `${step.id}:${project.index}`;
    if (autoStartedKey.current === key) return;
    autoStartedKey.current = key;
    autoStartIndex.current = null;
    void launch();
  }, [candidateSet, extensionId, launching, project.autoNext, project.index, project.refs, step.id, task]);
  const next = () => {
    if (!done || extensionId || project.index >= steps.length - 1) return;
    setProject((current) => ({ ...current, index: current.index + 1, completed: [...new Set([...current.completed, step.id])] }));
  };
  const nextChapter = () => {
    if (!done || extensionId || !["post-hoc", "export"].includes(step.id)) return;
    setProject((current) => ({ ...current, index: 6, completed: current.completed.filter((id) => !["mvp", "polish", "post-hoc", "export"].includes(id)),
      refs: Object.fromEntries(Object.entries(current.refs).filter(([id]) => !["mvp", "polish", "post-hoc", "export"].includes(id))),
      values: { ...current.values, latest_chapter: current.values.chapter_number, prev_chapter: current.values.chapter_number, chapter_number: String(Number(current.values.chapter_number) + 1).padStart(4, "0"), human_intent: "", world_intent: "" },
    }));
  };
  const renderField = (key: string, field?: WorkflowVariable) => {
    const value = extensionId ? extensionValues[key] || "" : project.values[key] || "";
    const update = (next: string) => extensionId ? setExtensionValues((current) => ({ ...current, [key]: next })) : setValue(key, next);
    const options = field?.options?.length ? field.options : key === "writer_type" ? [{ name: "单写手", value: "single" }, { name: "多写手", value: "muti" }] : [];
    return <label key={key} className="block"><span className="mb-2 block text-sm font-medium">{field?.name || labels[key] || key}</span>
      {options.length ? <select disabled={busy || done} value={value} onChange={(event) => update(event.target.value)} className={fieldClass}>{options.map((item) => <option key={item.value} value={item.value}>{item.name}</option>)}</select>
        : field?.type === "textarea" || key.includes("intent") || key === "premise" ? <textarea disabled={busy || done} value={value} onChange={(event) => update(event.target.value)} rows={4} className={fieldClass} />
        : <input disabled={busy || done} value={value} onChange={(event) => update(event.target.value)} className={fieldClass} />}
      {field?.description && <span className="mt-1 block text-xs text-muted-foreground">{field.description}</span>}
    </label>;
  };

  return <div className="h-full overflow-y-auto bg-background px-5 py-6 lg:px-8"><div className="mx-auto max-w-[1400px] space-y-6">
    <section className="rounded-3xl border border-indigo-300/20 bg-gradient-to-br from-[#18285d] to-[#29133b] p-7 text-white">
      <p className="flex items-center gap-2 text-xs tracking-widest text-indigo-200"><BookOpenText className="h-4 w-4" /> XS2 小说创作</p>
      <h2 className="mt-3 text-3xl font-semibold">一步一步，写完你的故事</h2>
      <p className="mt-3 text-sm text-indigo-100/75">从参考资料开始，完成当前步骤后点击下一步。创意、写法和视角会沿用到后续创作。</p>
      <details className="mt-4"><summary className="cursor-pointer text-xs text-indigo-200">作品工作区 · {workspace}</summary><div className="mt-3 flex gap-2"><input aria-label="作品工作区" disabled={busy} value={workspaceDraft} onChange={(event) => setWorkspaceDraft(event.target.value)} className="min-w-0 flex-1 rounded-lg border border-white/20 bg-black/20 p-2 text-xs" /><button disabled={busy || !workspaceDraft.trim()} onClick={() => onWorkspaceChange(workspaceDraft.trim())} className="rounded-lg bg-white/10 px-3 text-xs">切换作品</button></div><div className="mt-3 flex items-start gap-2 text-xs text-indigo-100"><input id="novel-auto-next" type="checkbox" checked={project.autoNext} disabled={busy} onChange={(event) => setProject((current) => ({ ...current, autoNext: event.target.checked }))} className="mt-0.5" /><label htmlFor="novel-auto-next"><span className="font-medium">完成后自动执行下一步</span><span className="mt-1 block text-indigo-200">当前步骤产物验证通过后自动进入并启动下一步；需要创意或章节输入时会停下来等你填写。</span></label></div><p className="mt-2 text-xs text-indigo-200">每个作品目录分别保存进度。新作品从第一步开始。</p></details>
    </section>
    <div className="grid gap-6 lg:grid-cols-[250px_minmax(0,1fr)]">
      <aside className="space-y-4"><h3 className="text-sm font-semibold">创作进度</h3><ol className="space-y-2">{steps.map((item, index) => <li key={item.id} aria-current={!extensionId && project.index === index ? "step" : undefined} className={`flex gap-3 rounded-xl border p-3 ${project.index === index && !extensionId ? "border-primary/50 bg-primary/10" : "border-border bg-card/60"}`}><span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs ${project.completed.includes(item.id) || (index === project.index && done && !extensionId) ? "bg-emerald-400/15 text-emerald-300" : "bg-secondary text-muted-foreground"}`}>{project.completed.includes(item.id) ? <Check className="h-3 w-3" /> : index + 1}</span><div><p className="text-sm">{item.title}</p><p className="mt-1 text-[11px] text-muted-foreground">{item.group}{project.index === index ? " · 当前步骤" : ""}</p></div></li>)}</ol>
        {extensions.length > 0 && <details><summary className="cursor-pointer text-sm text-muted-foreground">可选插件 · {extensions.length}</summary><div className="mt-2 space-y-2">{extensions.map((item) => <button key={item.workflow_id} disabled={busy} onClick={() => { setExtensionId(item.workflow_id); setExtensionRef(null); }} className="w-full rounded-lg border border-border p-3 text-left text-xs">{item.name}</button>)}</div></details>}
      </aside>
      <main className="space-y-5">
        <section className="rounded-2xl border border-border bg-card p-6">
          {extensionId && <button disabled={busy} onClick={() => setExtensionId("")} className="mb-4 text-sm text-primary">返回创作流程</button>}
          <p className="text-xs text-primary">{extensionId ? "可选插件" : `第 ${project.index + 1} 步 / 共 ${steps.length} 步${project.index >= 6 && project.index < 9 ? ` · 第 ${project.values.chapter_number} 章` : ""}`}</p>
          <h3 className="mt-2 text-2xl font-semibold">{title}</h3><p className="mt-3 text-sm leading-6 text-muted-foreground">{extensionId ? "独立运行这个插件，完成后可以返回当前创作步骤。" : step.description}</p>
          {!extensionId && <div className="mt-5 rounded-xl bg-secondary/50 p-4"><label className="block text-sm font-medium">这本书的叙事视角<select aria-label="叙事视角" disabled={busy || !!project.refs.build} value={project.values.narrative_pov} onChange={(event) => setValue("narrative_pov", event.target.value)} className={`${fieldClass} mt-2`}><option value="first_person">第一人称（我）</option><option value="third_person">第三人称（他 / 她）</option></select></label><p className="mt-2 text-xs leading-5 text-muted-foreground">{project.values.narrative_pov === "first_person" ? "以“我”的经历和认知讲述，只呈现叙述者能感知或推断的内容。" : "以“他 / 她”叙述，保持场景焦点清晰。"} 开始世界观规划后锁定本书视角。</p></div>}
          <div className="mt-5 space-y-4">{extensionId ? extensionFields.map((field) => renderField(field.key, field)) : step.fields.map((key) => renderField(key))}</div>
          {!extensionId && step.id === "adopt-reference" && <div className="mt-5 space-y-3">{loadingCandidates ? <p className="text-sm text-muted-foreground">正在读取写法…</p> : candidateSet ? <>{candidateSet.candidates.length === 0 && <p className="text-sm text-muted-foreground">没有提炼出适合迁移的写法，可以按原创设定继续。</p>}{candidateSet.candidates.map((candidate) => <label key={candidate.candidate_id} className="block rounded-xl border border-border p-4"><div className="flex items-start gap-3"><input type="checkbox" disabled={busy || done} checked={project.selected.includes(candidate.candidate_id)} onChange={(event) => setProject((current) => ({ ...current, selected: event.target.checked ? [...current.selected, candidate.candidate_id] : current.selected.filter((id) => id !== candidate.candidate_id) }))} /><div><span className="text-sm font-semibold">{candidate.mechanism}</span><p className="mt-2 text-xs leading-5 text-muted-foreground">{candidate.transfer_guidance}</p><p className="mt-2 text-xs text-muted-foreground">使用边界：{candidate.constraints.join("；")}</p>{candidate.evidence?.length ? <details className="mt-2 text-xs"><summary className="cursor-pointer text-primary">查看原文依据</summary>{candidate.evidence.map((proof, index) => <p key={index} className="mt-2 text-muted-foreground">{proof.excerpt}</p>)}</details> : null}</div></div></label>)}<p className="text-xs text-muted-foreground">已选 {project.selected.length} 条。未勾选的写法不会带入创作。</p></> : <p className="text-sm text-destructive">无法读取候选写法，请检查蒸馏结果。</p>}</div>}
          {error && <p role="alert" className="mt-4 flex gap-2 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"><CircleAlert className="h-4 w-4 shrink-0" />{error}</p>}
          <div className="mt-6 flex flex-wrap gap-3">{!done && <button disabled={busy || (!extensionId && step.id === "adopt-reference" && !candidateSet)} onClick={launch} className="flex items-center gap-2 rounded-xl bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground disabled:opacity-50">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}{busy ? "正在执行，请稍候" : task?.status === "failed" ? "重新执行当前步骤" : step.id === "adopt-reference" && !extensionId ? "确认选中写法" : "开始当前步骤"}</button>}
            {done && !extensionId && project.index < steps.length - 1 && <button onClick={next} className="flex items-center gap-2 rounded-xl bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground">{step.id === "post-hoc" ? "导出成品" : "下一步"}<ChevronRight className="h-4 w-4" /></button>}
            {done && !extensionId && ["post-hoc", "export"].includes(step.id) && <button onClick={nextChapter} className="rounded-xl border border-primary/40 px-6 py-3 text-sm font-semibold text-primary">继续写下一章</button>}
          </div>
        </section>
        {ref && <section className="rounded-2xl border border-border bg-card p-5"><div className="flex items-center gap-2"><Activity className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold">当前执行</h3><span className="ml-auto text-xs text-muted-foreground">{task ? statusLabel(task.status) : "正在恢复任务状态"}</span></div><p className="mt-3 font-mono text-xs text-muted-foreground">{ref.task_id}</p>{task?.status === "failed" && <p className="mt-3 text-sm text-destructive">{(Object.values(task.node_states || {}) as any[]).find((node) => node.status === "failed")?.error || "流程失败，请查看工作流中的节点详情。"}</p>}{done && <p className="mt-3 flex items-center gap-2 text-sm text-emerald-400"><Check className="h-4 w-4" />{extensionId ? "插件执行完成" : "当前步骤完成，产物已保存"}</p>}<button onClick={refreshTask} className="mt-3 flex items-center gap-2 text-xs text-primary"><RefreshCw className="h-3 w-3" />刷新结果</button>{preview && <details className="mt-4"><summary className="flex cursor-pointer items-center gap-2 text-sm"><FileText className="h-4 w-4" />查看产物 · {artifact}</summary><pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap rounded-xl bg-secondary/40 p-4 text-xs leading-6">{preview}</pre></details>}</section>}
      </main>
    </div>
  </div></div>;
}
