import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  BookOpen,
  BookOpenText,
  Boxes,
  Check,
  ChevronRight,
  CircleAlert,
  FileText,
  FlaskConical,
  FolderOpen,
  Loader2,
  Play,
  RefreshCw,
  Sparkles,
  Trophy,
  WandSparkles,
} from "lucide-react";
import { createTask, getTask, getWorkflow, listWorkflows, readWorkflowWorkspaceFile, runTask } from "../lib/api";

type StageId = string;

type Stage = {
  id: StageId;
  workflowId: string;
  title: string;
  eyebrow: string;
  description: string;
  group: "learn" | "plan" | "write" | "extensions";
  accent: string;
};

const CORE_PREFIX = "xs2-novel-flywheel-";
const stages: Stage[] = [
  { id: "market-ranking", workflowId: `${CORE_PREFIX}market-ranking`, title: "知乎榜单", eyebrow: "市场观察", description: "抓取知乎盐选公开榜单，保存作品、排名、题材和热度快照。", group: "learn", accent: "from-amber-500/30 to-yellow-500/10" },
  { id: "reference-distillation", workflowId: `${CORE_PREFIX}reference-distillation`, title: "参考资料蒸馏", eyebrow: "资料学习", description: "从参考文本提炼可迁移的叙事机制，保留证据与边界。", group: "learn", accent: "from-violet-500/30 to-fuchsia-500/10" },
  { id: "adopt-reference", workflowId: `${CORE_PREFIX}adopt-reference`, title: "采用写法", eyebrow: "资料学习", description: "从候选机制中选择本次创作真正要使用的写法。", group: "learn", accent: "from-fuchsia-500/30 to-rose-500/10" },
  { id: "build", workflowId: `${CORE_PREFIX}build`, title: "世界观构建", eyebrow: "创作前置", description: "建立世界运行规则、时空、社会、历史与存在基础。", group: "plan", accent: "from-sky-500/30 to-cyan-500/10" },
  { id: "character", workflowId: `${CORE_PREFIX}character`, title: "角色创建", eyebrow: "创作前置", description: "从角色骨架推进到信念、深层维度和可写声音。", group: "plan", accent: "from-cyan-500/30 to-teal-500/10" },
  { id: "story-plan", workflowId: `${CORE_PREFIX}story-plan`, title: "故事规划", eyebrow: "创作前置", description: "把创意、世界和人物汇总为可执行的故事规划。", group: "plan", accent: "from-teal-500/30 to-emerald-500/10" },
  { id: "outline", workflowId: `${CORE_PREFIX}outline`, title: "卷纲与近纲", eyebrow: "创作前置", description: "将故事规划拆成卷级目标和近期章节推进。", group: "plan", accent: "from-emerald-500/30 to-lime-500/10" },
  { id: "mvp", workflowId: `${CORE_PREFIX}mvp`, title: "章节生产", eyebrow: "正文生产", description: "沿着当前连续性状态生成章节正文并落盘。", group: "write", accent: "from-amber-500/30 to-orange-500/10" },
  { id: "polish", workflowId: `${CORE_PREFIX}polish`, title: "章节润色", eyebrow: "正文生产", description: "完成自审、人文化处理和专业润色。", group: "write", accent: "from-orange-500/30 to-red-500/10" },
  { id: "post-hoc", workflowId: `${CORE_PREFIX}post-hoc`, title: "章节后验", eyebrow: "正文生产", description: "把本章事实回写到世界、角色、伏笔和叙事债务。", group: "write", accent: "from-red-500/30 to-pink-500/10" },
];

const defaultValues: Record<string, string> = {
  reference_path: "references/source.txt",
  window_size: "4200",
  top_n: "100",
  selection_path: "learning/selection.json",
  premise: "",
  genre: "都市情感",
  language: "中文",
  volume_number: "1",
  estimated_length: "中",
  words_per_chapter: "2000-2500",
  latest_chapter: "0000",
  chapter_number: "0001",
  prev_chapter: "0000",
  human_intent: "",
  world_intent: "",
  target_word_count: "3000-4000",
  writer_type: "single",
};

const labels: Record<string, string> = {
  reference_path: "参考资料路径",
  window_size: "窗口长度",
  top_n: "抓取作品数",
  selection_path: "选择文件路径",
  premise: "题材创意",
  genre: "题材类型",
  language: "输出语言",
  volume_number: "目标卷号",
  estimated_length: "预计篇幅",
  words_per_chapter: "每章字数",
  latest_chapter: "最新章节号",
  chapter_number: "章节号",
  prev_chapter: "上一章节号",
  human_intent: "人类意图",
  world_intent: "世界意图",
  target_word_count: "目标字数",
  writer_type: "写手模式",
};

function stageIcon(stage: Stage) {
  if (stage.id === "market-ranking") return <Trophy className="h-4 w-4" />;
  if (stage.group === "learn") return <FlaskConical className="h-4 w-4" />;
  if (stage.group === "plan") return <Sparkles className="h-4 w-4" />;
  return <WandSparkles className="h-4 w-4" />;
}

function statusLabel(status: string) {
  return ({ pending: "等待启动", pre_running: "准备中", running: "运行中", completed: "已完成", failed: "失败", stopped: "已停止", cancelled: "已取消" } as Record<string, string>)[status] || status || "未运行";
}

export default function NovelWorkbenchPage() {
  const [workspace, setWorkspace] = useState(() => localStorage.getItem("xs2-novel-workspace") || "C:\\xs2\\DeterminFlow\\data\\workspaces\\xs2-novel-workbench");
  const [activeStageId, setActiveStageId] = useState<StageId>("market-ranking");
  const [values, setValues] = useState<Record<string, string>>(defaultValues);
  const [task, setTask] = useState<any>(null);
  const [taskError, setTaskError] = useState("");
  const [launching, setLaunching] = useState(false);
  const [candidates, setCandidates] = useState<any[]>([]);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [rankingSnapshot, setRankingSnapshot] = useState<any>(null);
  const [loadingRankings, setLoadingRankings] = useState(false);
  const [extensionStages, setExtensionStages] = useState<Stage[]>([]);
  const [dynamicFields, setDynamicFields] = useState<string[]>([]);
  const activeStage = [...stages, ...extensionStages].find((stage) => stage.id === activeStageId) || stages[0];

  useEffect(() => {
    let active = true;
    void listWorkflows().then((items) => {
      if (!active) return;
      const known = new Set(stages.map((stage) => stage.workflowId));
      setExtensionStages(items.filter((item) => !known.has(item.workflow_id)).map((item) => ({
        id: item.workflow_id,
        workflowId: item.workflow_id,
        title: item.name,
        eyebrow: "扩展插件",
        description: `来自插件的工作流 · ${item.node_count} 个节点`,
        group: "extensions",
        accent: "from-slate-500/30 to-indigo-500/10",
      })));
    }).catch(() => setExtensionStages([]));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (stages.some((stage) => stage.id === activeStageId)) {
      setDynamicFields([]);
      return;
    }
    const extension = extensionStages.find((stage) => stage.id === activeStageId);
    if (!extension) return;
    void getWorkflow(extension.workflowId).then((result) => {
      const fields = (result.definition.variables || []).filter((variable: any) => !variable.hidden).map((variable: any) => variable.key);
      setDynamicFields(fields);
      setValues((current) => ({ ...current, ...Object.fromEntries((result.definition.variables || []).map((variable: any) => [variable.key, current[variable.key] || variable.default || ""])) }));
    }).catch(() => setDynamicFields([]));
  }, [activeStageId, extensionStages]);

  const refreshTask = useCallback(async () => {
    if (!task?.workflow_id || !task?.task_id) return;
    try {
      const result = await getTask(task.workflow_id, task.task_id);
      setTask({ ...result.task, definition: result.definition });
    } catch (error) {
      setTaskError(error instanceof Error ? error.message : "读取任务状态失败");
    }
  }, [task?.task_id, task?.workflow_id]);

  useEffect(() => {
    if (!task || ["completed", "failed", "stopped", "cancelled"].includes(task.status)) return;
    const timer = window.setInterval(refreshTask, 3000);
    return () => window.clearInterval(timer);
  }, [task, refreshTask]);

  const loadCandidates = useCallback(async () => {
    if (!task?.workflow_id || !task?.task_id) return;
    setLoadingCandidates(true);
    try {
      const result = await readWorkflowWorkspaceFile(task.workflow_id, task.task_id, "learning/candidates.json");
      const parsed = JSON.parse(result.content);
      setCandidates(Array.isArray(parsed.candidates) ? parsed.candidates : []);
    } catch {
      setCandidates([]);
    } finally {
      setLoadingCandidates(false);
    }
  }, [task?.task_id, task?.workflow_id]);

  const loadRankings = useCallback(async () => {
    if (!task?.workflow_id || !task?.task_id) return;
    setLoadingRankings(true);
    try {
      const result = await readWorkflowWorkspaceFile(task.workflow_id, task.task_id, "market/zhihu-ranking.json");
      setRankingSnapshot(JSON.parse(result.content));
    } catch {
      setRankingSnapshot(null);
    } finally {
      setLoadingRankings(false);
    }
  }, [task?.task_id, task?.workflow_id]);

  useEffect(() => {
    if (task?.status === "completed" && activeStageId === "reference-distillation") void loadCandidates();
  }, [activeStageId, loadCandidates, task?.status]);

  useEffect(() => {
    if (task?.status === "completed" && activeStageId === "market-ranking") void loadRankings();
  }, [activeStageId, loadRankings, task?.status]);

  const visibleFields = useMemo(() => {
    const fieldMap: Record<StageId, string[]> = {
      "market-ranking": ["top_n"],
      "reference-distillation": ["reference_path", "window_size"],
      "adopt-reference": ["selection_path"],
      build: ["premise", "genre", "language"],
      character: ["premise", "genre", "language"],
      "story-plan": ["premise", "genre", "language"],
      outline: ["volume_number", "estimated_length", "words_per_chapter", "latest_chapter"],
      mvp: ["chapter_number", "prev_chapter", "human_intent", "world_intent", "target_word_count", "writer_type", "language"],
      polish: ["chapter_number", "language"],
      "post-hoc": ["chapter_number", "language"],
    };
    return fieldMap[activeStageId] || dynamicFields;
  }, [activeStageId, dynamicFields]);

  const launch = async () => {
    setLaunching(true);
    setTaskError("");
    setCandidates([]);
    try {
      const created = await createTask(activeStage.workflowId, Object.fromEntries(visibleFields.map((key) => [key, values[key] || ""])), undefined, undefined, workspace);
      await runTask(activeStage.workflowId, created.task_id);
      setTask({ task_id: created.task_id, workflow_id: activeStage.workflowId, status: "running", name: activeStage.title });
    } catch (error) {
      setTaskError(error instanceof Error ? error.message : "启动流程失败");
    } finally {
      setLaunching(false);
    }
  };

  const grouped = [
    { key: "learn", title: "资料学习", note: "先提炼，再选择", icon: <BookOpen className="h-4 w-4" /> },
    { key: "plan", title: "创作前置", note: "把想法变成结构", icon: <Sparkles className="h-4 w-4" /> },
    { key: "write", title: "正文生产", note: "章节、润色与后验", icon: <WandSparkles className="h-4 w-4" /> },
    { key: "extensions", title: "扩展插件", note: "自动发现新工作流", icon: <Boxes className="h-4 w-4" /> },
  ] as const;
  const allStages = [...stages, ...extensionStages];

  return (
    <div className="h-full overflow-y-auto bg-background px-5 py-6 lg:px-8">
      <div className="mx-auto max-w-[1500px] space-y-6">
        <section className="relative overflow-hidden rounded-3xl border border-indigo-300/20 bg-gradient-to-br from-[#18285d] via-[#1d2450] to-[#29133b] p-7 shadow-2xl shadow-indigo-950/20">
          <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-fuchsia-400/15 blur-3xl" />
          <div className="relative flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <div className="mb-4 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-indigo-200"><BookOpenText className="h-4 w-4" /> XS2 NOVEL FLYWHEEL</div>
              <h2 className="text-3xl font-semibold tracking-tight text-white lg:text-4xl">把灵感变成可执行的长篇流程</h2>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-indigo-100/75">从榜单和参考资料开始，沿着同一个作品工作区推进世界观、角色、卷纲、章节和质量回写。每一次调度都直接调用 Core 的真实 Workflow。</p>
            </div>
            <div className="min-w-[280px] rounded-2xl border border-white/10 bg-black/15 p-4 backdrop-blur">
              <label className="mb-2 block text-xs font-medium text-indigo-100/70">当前作品工作区</label>
              <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2">
                <FolderOpen className="h-4 w-4 shrink-0 text-indigo-200" />
                <input value={workspace} onChange={(event) => { const next = event.target.value; setWorkspace(next); localStorage.setItem("xs2-novel-workspace", next); }} className="min-w-0 flex-1 bg-transparent text-xs text-white outline-none" aria-label="当前作品工作区" />
              </div>
              <p className="mt-2 text-[11px] text-indigo-100/50">同一本书的所有流程使用同一个目录。</p>
            </div>
          </div>
        </section>

        <div className="grid gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
          <section className="space-y-5">
            <div className="flex items-end justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">Workflow map</p><h3 className="mt-1 text-xl font-semibold text-foreground">创作流程</h3></div><span className="text-xs text-muted-foreground">选择一个阶段开始</span></div>
            <div className="grid gap-4">
              {grouped.map((group) => (
                <div key={group.key} className="space-y-3">
                  <div className="flex items-center gap-2 px-1 text-sm font-semibold text-foreground">{group.icon}<span>{group.title}</span><span className="ml-auto text-[11px] font-normal text-muted-foreground">{group.note}</span></div>
                  {allStages.filter((stage) => stage.group === group.key).map((stage, index) => {
                    const selected = stage.id === activeStageId;
                    return <button key={stage.id} type="button" onClick={() => setActiveStageId(stage.id)} className={`group w-full rounded-2xl border p-4 text-left transition ${selected ? "border-primary/60 bg-primary/10 shadow-lg shadow-primary/5" : "border-border bg-card/70 hover:border-primary/30 hover:bg-card"}`}>
                      <div className="flex items-start gap-3"><div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${stage.accent} text-foreground`}>{stageIcon(stage)}</div><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><span className="text-sm font-semibold text-foreground">{stage.title}</span>{selected && <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] text-primary">当前</span>}</div><p className="mt-1 text-xs leading-5 text-muted-foreground">{stage.description}</p></div><ChevronRight className={`mt-1 h-4 w-4 shrink-0 transition ${selected ? "text-primary" : "text-muted-foreground/50 group-hover:translate-x-0.5"}`} /></div>
                      {index < allStages.filter((item) => item.group === group.key).length - 1 && <div className="ml-4 mt-3 h-3 border-l border-dashed border-border" />}
                    </button>;
                  })}
                </div>
              ))}
            </div>

            {activeStageId === "market-ranking" && rankingSnapshot && <section className="rounded-2xl border border-amber-400/20 bg-amber-400/5 p-5"><div className="flex items-center justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-amber-300">Market snapshot</p><h3 className="mt-1 text-lg font-semibold text-foreground">知乎盐选榜单 · {rankingSnapshot.work_count} 部作品</h3><p className="mt-1 text-xs text-muted-foreground">抓取时间 {new Date(rankingSnapshot.captured_at).toLocaleString()}</p></div><button type="button" onClick={loadRankings} disabled={loadingRankings} className="rounded-lg border border-border p-2 text-muted-foreground hover:text-foreground" title="刷新榜单"><RefreshCw className={`h-4 w-4 ${loadingRankings ? "animate-spin" : ""}`} /></button></div><div className="mt-4 grid gap-3 md:grid-cols-2">{(rankingSnapshot.works || []).slice(0, 10).map((work: any) => <article key={`${work.ranking_name}-${work.rank}-${work.platform_work_id}`} className="rounded-xl border border-border bg-card/70 p-4"><div className="flex items-start gap-3"><div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-400/15 text-xs font-bold text-amber-200">{work.rank}</div><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><h4 className="truncate text-sm font-semibold text-foreground">{work.title}</h4><span className="shrink-0 rounded-full bg-secondary px-2 py-0.5 text-[10px] text-secondary-foreground">{work.ranking_name}</span></div><p className="mt-1 text-xs text-muted-foreground">{work.category} · {work.likes ? `${Number(work.likes).toLocaleString()} 赞` : "热度未提供"}</p><p className="mt-2 line-clamp-2 text-xs leading-5 text-muted-foreground">{work.summary || "暂无简介"}</p></div></div></article>)}</div><p className="mt-3 text-xs text-muted-foreground">{rankingSnapshot.boundary}</p></section>}
            {activeStageId === "reference-distillation" && candidates.length > 0 && <section className="rounded-2xl border border-emerald-400/20 bg-emerald-400/5 p-5"><div className="flex items-center justify-between"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-300">Learning output</p><h3 className="mt-1 text-lg font-semibold text-foreground">已提炼的写法 · {candidates.length} 条</h3></div><button type="button" onClick={loadCandidates} className="rounded-lg border border-border p-2 text-muted-foreground hover:text-foreground" title="刷新候选"><RefreshCw className="h-4 w-4" /></button></div><div className="mt-4 grid gap-3 md:grid-cols-2">{candidates.slice(0, 6).map((candidate) => <article key={candidate.candidate_id} className="rounded-xl border border-border bg-card/70 p-4"><h4 className="text-sm font-semibold text-foreground">{candidate.mechanism}</h4><p className="mt-2 text-xs leading-5 text-muted-foreground">{candidate.transfer_guidance}</p><div className="mt-3 flex flex-wrap gap-1.5">{(candidate.scopes || []).map((scope: string) => <span key={scope} className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-secondary-foreground">{scope}</span>)}</div></article>)}</div><p className="mt-3 text-xs text-muted-foreground">候选已生成，下一步在工作区的 `learning/selection.html` 中选择后运行“采用写法”。</p></section>}
          </section>

          <aside className="space-y-5">
            <section className="rounded-2xl border border-border bg-card p-5 shadow-sm"><div className="flex items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Configure stage</p><h3 className="mt-1 text-xl font-semibold text-foreground">{activeStage.title}</h3></div><div className="rounded-xl bg-primary/10 p-2 text-primary">{stageIcon(activeStage)}</div></div><p className="mt-3 text-xs leading-5 text-muted-foreground">{activeStage.description}</p><div className="mt-5 space-y-3">{visibleFields.map((key) => <label key={key} className="block"><span className="mb-1.5 block text-xs font-medium text-foreground">{labels[key] || key}</span>{key.includes("intent") || key === "premise" ? <textarea value={values[key] || ""} onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))} rows={3} className="w-full resize-y rounded-xl border border-border bg-background px-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20" placeholder={key === "premise" ? "例如：一个已经知道原著结局的人，试图改变自己和家人的命运。" : "可选，写下这次调度的重点"} /> : <input value={values[key] || ""} onChange={(event) => setValues((current) => ({ ...current, [key]: event.target.value }))} className="w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20" />}</label>)}</div><button type="button" disabled={launching} onClick={launch} className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground shadow-lg shadow-primary/20 transition hover:brightness-110 disabled:cursor-wait disabled:opacity-60">{launching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}{launching ? "正在创建任务" : `运行${activeStage.title}`}</button>{taskError && <div className="mt-3 flex gap-2 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-xs leading-5 text-destructive"><CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />{taskError}</div>}</section>

            <section className="rounded-2xl border border-border bg-card p-5"><div className="flex items-center gap-2"><Activity className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold text-foreground">当前执行</h3>{task && <span className={`ml-auto rounded-full px-2 py-1 text-[10px] ${task.status === "completed" ? "bg-emerald-400/10 text-emerald-300" : task.status === "failed" ? "bg-destructive/10 text-destructive" : "bg-primary/10 text-primary"}`}>{statusLabel(task.status)}</span>}</div>{task ? <div className="mt-4 space-y-3"><div className="rounded-xl bg-secondary/60 p-3"><p className="text-xs font-medium text-foreground">{task.name || activeStage.title}</p><p className="mt-1 break-all font-mono text-[10px] text-muted-foreground">{task.task_id}</p></div><div className="space-y-2">{["创建任务", "读取工作区", "执行 Agent 与脚本", "写入结果"].map((label, index) => <div key={label} className="flex items-center gap-2 text-xs"><span className={`flex h-5 w-5 items-center justify-center rounded-full ${task.status === "completed" || index < 2 ? "bg-emerald-400/15 text-emerald-300" : "bg-secondary text-muted-foreground"}`}>{task.status === "completed" || index < 2 ? <Check className="h-3 w-3" /> : index + 1}</span><span className={task.status === "completed" || index < 2 ? "text-foreground" : "text-muted-foreground"}>{label}</span></div>)}</div>{task.status === "completed" && <div className="flex items-center gap-2 text-xs text-emerald-300"><Check className="h-4 w-4" />流程已完成，可查看工作区产物</div>}{task.status === "failed" && <div className="flex items-start gap-2 text-xs text-destructive"><CircleAlert className="mt-0.5 h-4 w-4" />{(Object.values(task.node_states || {}) as any[]).find((node) => node.status === "failed")?.error || "流程执行失败"}</div>}<button type="button" onClick={refreshTask} className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground"><RefreshCw className="h-3 w-3" />刷新状态</button></div> : <div className="mt-4 rounded-xl border border-dashed border-border p-5 text-center"><FileText className="mx-auto h-6 w-6 text-muted-foreground/60" /><p className="mt-2 text-xs text-muted-foreground">选择一个阶段并运行，执行状态会显示在这里。</p></div>}</section>

            <section className="rounded-2xl border border-border bg-card p-5"><div className="flex items-center gap-2"><ArrowUpRight className="h-4 w-4 text-primary" /><h3 className="text-sm font-semibold text-foreground">建议顺序</h3></div><div className="mt-4 space-y-2 text-xs text-muted-foreground"><p><span className="mr-2 text-primary">01</span>知乎榜单 → 参考资料蒸馏 → 选择写法</p><p><span className="mr-2 text-primary">02</span>世界观 → 角色 → 故事规划</p><p><span className="mr-2 text-primary">03</span>卷纲 → 章节 → 润色 → 后验</p></div></section>
          </aside>
        </div>
        <footer className="flex items-center gap-2 border-t border-border pt-4 text-xs text-muted-foreground"><Check className="h-3.5 w-3.5 text-emerald-300" />本地运行 · 页面调用 DeterminFlow Core · 结果保存在当前工作区</footer>
      </div>
    </div>
  );
}
