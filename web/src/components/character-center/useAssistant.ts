import { useEffect, useRef, useState } from "react";
import { CharacterCenterError, errorText, type CharacterApi, type Job, type JobInput, type JobSource } from "./api";
import { useAction } from "./useAction";

export type JobScope = { chapter: string; personId: string } & (
  { purpose: "character_edit"; sectionId: string; sourceId: string } | { purpose: "dialogue_trial" }
);
type Ticket = { id: string; input: JobInput };
type Selection = { id: string; running: boolean; source?: JobSource; ticket?: Ticket };

export function sameCast(left: string[], right: string[]) {
  return left.length === right.length && left.every(id => right.includes(id)) && right.every(id => left.includes(id));
}

function matchesScope(job: Job, scope: JobScope) {
  const source = job.character_source;
  if (job.purpose !== scope.purpose || job.chapter !== scope.chapter || source?.chapter !== scope.chapter
    || typeof source.revision !== "string" || !Array.isArray(source.character_ids) || !source.character_ids.includes(scope.personId)) return false;
  if (scope.purpose === "character_edit") {
    return source.character_id === scope.personId && source.section_id === scope.sectionId && source.source_id === scope.sourceId;
  }
  return typeof source.scene === "string" && !!source.scene.trim();
}

function matchesRequest(job: Job, ticket: Ticket, scope: JobScope) {
  const source = job.character_source;
  const input = ticket.input;
  return job.id === ticket.id && job.purpose === input.purpose && job.chapter === input.chapter
    && (!source || matchesScope(job, scope) && source.revision === input.expected_revision
      && (input.purpose !== "dialogue_trial" || source.scene === input.scene.trim() && sameCast(source.character_ids, input.character_ids)));
}

export function useAssistant(api: CharacterApi, scope: JobScope) {
  const action = useAction();
  const [history, setHistory] = useState<Job[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [historyLoading, setHistoryLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [selection, setSelection] = useState<Selection>();
  const [entry, setEntry] = useState<Job>();
  const [error, setError] = useState("");
  const unresolved = useRef<Ticket>();
  const status = entry?.status;

  useEffect(() => {
    const controller = new AbortController();
    let timer: number;
    let delay = 750;
    setHistoryLoading(true);
    setHistoryError("");

    async function read() {
      let pollAgain = selection?.running;
      try {
        const { entries } = await api.jobs(controller.signal);
        if (controller.signal.aborted) return;
        const records = entries.filter(job => matchesScope(job, scope));
        setHistory(records);
        const next = selection && records.find(job => {
          if (job.id !== selection.id) return false;
          if (selection.ticket) return matchesRequest(job, selection.ticket, scope);
          const source = job.character_source;
          const previous = selection.source;
          return source && previous && source.revision === previous.revision
            && source.scene === previous.scene && sameCast(source.character_ids, previous.character_ids);
        });
        if (next) {
          setEntry(current => current?.id === selection?.id ? next : current);
          setHistoryError("");
          pollAgain = next.status === "running";
        } else if (pollAgain) setHistoryError("还未读取到本次请求，正在等待该任务记录。");
      } catch (failure) {
        if (!controller.signal.aborted) setHistoryError("读取助手记录失败。 " + errorText(failure));
      } finally {
        if (!controller.signal.aborted) {
          setHistoryLoading(false);
          if (pollAgain) {
            timer = window.setTimeout(() => void read(), delay);
            delay = 1500;
          }
        }
      }
    }

    void read();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [api, scope, selection, refresh]);

  function select(id: string) {
    if (action.busy || unresolved.current || id === selection?.id) return;
    const saved = history.find(job => job.id === id && matchesScope(job, scope));
    setSelection(saved ? { id: saved.id, running: saved.status === "running", source: saved.character_source } : undefined);
    setEntry(saved);
    setError("");
  }

  const busy = action.busy || status === "running" || (!unresolved.current && history.some(job => job.status === "running"));
  function start(input: JobInput) {
    if (busy) return;
    const current = unresolved.current || { id: globalThis.crypto.randomUUID(), input };
    unresolved.current = current;
    setSelection(undefined);
    setEntry(undefined);
    setError("");
    void action.run(async signal => {
      try {
        const { entry: response } = await api.start(current.id, current.input, signal);
        if (signal.aborted) return;
        if (!matchesRequest(response, current, scope)) throw new Error("助手返回的请求编号不符。");
        unresolved.current = undefined;
        setSelection({ id: response.id, running: response.status === "running", ticket: current, source: response.character_source });
        setEntry(response);
        if (matchesScope(response, scope)) {
          setHistory(rows => [response, ...rows.filter(row => row.id !== response.id)]);
        }
      } catch (failure) {
        if (signal.aborted) return;
        // Transport failures can arrive after the server accepted the UUID.
        if (failure instanceof CharacterCenterError && failure.status < 500) unresolved.current = undefined;
        setError(errorText(failure));
      }
    });
  }

  return {
    entry, selection, error, start, busy, submitting: action.busy, select,
    history: entry && !history.some(row => row.id === entry.id) ? [entry, ...history] : history,
    historyLoading, historyError, refreshHistory: () => setRefresh(value => value + 1),
    retryTransport: !!unresolved.current && !!error && !action.busy,
  };
}
