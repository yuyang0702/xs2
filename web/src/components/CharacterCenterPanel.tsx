import { useEffect, useMemo, useState } from "react";
import CharacterVoiceEditor from "./CharacterVoiceEditor";
import { SelectedChapterLifecycle } from "./SavedNovelProgress";
import { characterApi, errorText, type Inventory, type Person, type Scope } from "./character-center/api";
import CharacterDetail from "./character-center/CharacterDetail";
import BookPolicy from "./character-center/BookPolicy";
import { box, button, field, muted, primary, Problem, prose } from "./character-center/ui";

type Props = Scope & {
  currentChapter?: string; knownChapters?: string[]; progressWorkflowId?: string;
  onHome?: () => void; onWrite?: (chapter: string) => void; onReview?: (chapter: string) => void;
};
function chapterNumber(value: string) {
  return /^[0-9]{1,4}$/.test(value) && Number(value) > 0 ? value.padStart(4, "0") : "";
}

export default function CharacterCenterPanel(props: Props) {
  return <CharacterCenter key={JSON.stringify([props.workflowId, props.workspace])} {...props} />;
}

function CharacterCenter({ workspace, workflowId, progressWorkflowId, currentChapter = "", knownChapters = [], onHome, onWrite, onReview }: Props) {
  const api = useMemo(() => characterApi({ workspace, workflowId }), [workspace, workflowId]);
  const [chapter, setChapter] = useState("");
  const [chapterInput, setChapterInput] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState("");
  const [view, setView] = useState<"people" | "policy" | "legacy">("people");
  const [inventory, setInventory] = useState<Inventory>();
  const [inventoryChapter, setInventoryChapter] = useState("");
  const [roster, setRoster] = useState<Person[]>([]);
  const [refresh, setRefresh] = useState(0);
  const [loaded, setLoaded] = useState("");
  const [error, setError] = useState("");
  const [chapterError, setChapterError] = useState("");
  const identity = JSON.stringify([chapter, query, refresh]);
  const active = loaded === identity;
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    void api.inventory(chapter, query, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      setInventory(value);
      setInventoryChapter(chapter);
      if (!query) setRoster(value.characters);
      setSelected(id => value.characters.some(person => person.id === id) ? id : value.characters[0]?.id || "");
      setLoaded(identity);
    }).catch(failure => {
      if (!controller.signal.aborted) setError(errorText(failure));
    });
    return () => controller.abort();
  }, [api, chapter, query, identity]);

  const person = inventoryChapter === chapter ? inventory?.characters.find(row => row.id === selected) : undefined;
  const shownChapter = chapter || inventory?.chapter || "";
  const actionChapter = shownChapter || chapterNumber(currentChapter) || "0001";
  const options = Array.from(new Set([currentChapter, ...knownChapters, ...inventory?.chapters || [],
    ...inventory?.stale_chapters || [], shownChapter].map(chapterNumber).filter(Boolean))).sort();
  const loadChapter = (value: string) => {
    setChapterError("");
    setChapterInput(value);
    setChapter(value);
  };
  return <div className="space-y-5">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div><h1 className="text-2xl font-bold">人物中心</h1><p className={muted}>从档案、关系和正文证据回看人物，或为当前场景准备表达建议。</p></div>
      <div className="flex flex-wrap gap-2">
        {onHome && <button className={button} onClick={onHome}>返回首页</button>}
        <button className={button} onClick={() => setRefresh(value => value + 1)}>刷新人物资料</button>
      </div>
    </header>
    <nav aria-label="人物中心功能" className="flex flex-wrap gap-2">
      <button className={view === "people" ? primary : button} aria-pressed={view === "people"} onClick={() => setView("people")}>人物档案</button>
      <button className={view === "policy" ? primary : button} aria-pressed={view === "policy"} onClick={() => setView("policy")}>叙述偏好与规则体检</button>
      <button className={view === "legacy" ? primary : button} aria-pressed={view === "legacy"} onClick={() => setView("legacy")}>旧版声音编辑</button>
    </nav>
    {view !== "legacy" && <section className={box} aria-label="查看章节">
      <div className="flex flex-wrap items-end gap-2">
        <form className="flex flex-wrap items-end gap-2" onSubmit={event => {
          event.preventDefault();
          const value = chapterNumber(chapterInput);
          if (value) loadChapter(value);
          else setChapterError("请输入 1 到 9999 之间的章节号。");
        }}>
          <label className="grid gap-1 text-sm">章节号
            <input aria-label="章节号" className={field + " w-28"} inputMode="numeric" maxLength={4}
              value={chapterInput} placeholder={shownChapter || "0001"} onChange={event => setChapterInput(event.target.value)} />
          </label>
          <button className={primary} type="submit">查看章节</button>
        </form>
        {options.length > 0 && <select aria-label="已知章节" className={field} value={chapter}
          onChange={event => loadChapter(event.target.value)}>
          <option value="">最近已确认章节</option>
          {options.map(value => <option key={value} value={value}>第 {Number(value)} 章{inventory?.chapters.includes(value)
            ? " · 已确认" : inventory?.stale_chapters.includes(value) ? " · 证据失效" : ""}</option>)}
        </select>}
        {onWrite && <button className={button} onClick={() => onWrite(actionChapter)}>进入创作流程</button>}
        {onReview && <button className={button} onClick={() => onReview(actionChapter)}>查看读者评估与返修</button>}
      </div>
      <Problem message={chapterError} />
      <p className={muted} role="status">{shownChapter ? "查看第 " + Number(shownChapter) + " 章" : "尚无已确认章节，可输入规划中的章节。"}</p>
    </section>}
    {view === "legacy" && <CharacterVoiceEditor workspaceId={workspace} workflowId={workflowId} />}
    {view === "policy" && <BookPolicy key={actionChapter} chapter={actionChapter} api={api} onSaved={() => setRefresh(value => value + 1)} />}
    {view === "people" && <div className="grid min-w-0 gap-4 xl:grid-cols-[250px_minmax(0,1fr)]">
      <aside className={box} aria-label="选择人物">
        <form className="space-y-2" onSubmit={event => { event.preventDefault(); setQuery(search.trim()); }}>
          <label className="grid gap-1 text-sm">搜索姓名或原文
            <input aria-label="搜索人物" className={field + " min-w-0 w-full"} value={search} maxLength={200}
              onChange={event => setSearch(event.target.value)} />
          </label>
          <div className="flex gap-2"><button className={button} type="submit">搜索</button>
            {query && <button className={button} type="button" onClick={() => { setSearch(""); setQuery(""); }}>清除搜索</button>}</div>
        </form>
        <Problem message={error} />
        {!active && !error && <p className={muted} role="status">正在读取人物资料…</p>}
        {active && inventory?.characters.length === 0 && <p className={muted}>{query ? "没有匹配的人物或原文。" : "尚未识别到人物。可查看原始资料或打开旧版声音编辑。"}</p>}
        <ul className="space-y-1">{inventory?.characters.map(row => <li key={row.id}>
          <button className={(row.id === selected ? primary : button) + " w-full break-words text-left"}
            aria-pressed={row.id === selected} disabled={!active} title={row.title} onClick={() => setSelected(row.id)}>{row.name}</button>
        </li>)}</ul>
        {inventory?.warnings.map(warning => <p className={muted} key={warning}>{warning}</p>)}
        {inventory && <details className="space-y-2"><summary className="cursor-pointer text-sm">本书资料原件</summary>
          {inventory.sources.map(source => <details className="pl-2" key={source.source_id}>
            <summary className="cursor-pointer break-all text-xs">{source.source_id} · {source.status === "missing" ? "缺失" : "已有原件"}</summary>
            <SourceRaw text={source.raw} />
          </details>)}
        </details>}
      </aside>
      {person && inventory && <CharacterDetail key={JSON.stringify([person.id, shownChapter])} person={person} inventory={inventory}
        ready={active} api={api} actionChapter={actionChapter} roster={roster}
        lifecycle={progressWorkflowId && <SelectedChapterLifecycle key={actionChapter + ":" + refresh} workflowId={progressWorkflowId}
          workspace={workspace} chapter={actionChapter} />}
        onSelect={id => {
          if (!inventory.characters.some(row => row.id === id)) { setSearch(""); setQuery(""); }
          setSelected(id);
        }}
        onChanged={() => setRefresh(value => value + 1)} onLegacy={() => setView("legacy")} />}
    </div>}
  </div>;
}

function SourceRaw({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return <div className="my-2">
    <button className={button} onClick={() => setOpen(value => !value)} aria-expanded={open}>{open ? "收起全文" : "展开全文"}</button>
    {open && <pre className={prose + " mt-2 max-h-96 overflow-auto"}>{text || "没有原文。"}</pre>}
  </div>;
}
