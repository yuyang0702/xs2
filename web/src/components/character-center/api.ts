export type Scope = { workspace: string; workflowId: string };

export type Section = {
  id: string; source_id: string; source_revision: string; group: string; label: string;
  text: string; editable: boolean; ai_editable: boolean; line: number;
};
type Evidence = { source_chapter: string; source_id: string; evidence: string | string[] };
type Fields = Record<string, string | string[]>;
export type CharacterState = Evidence & {
  chapter: string; snapshot: Fields; drives: Fields; knowledge: string | string[];
  beliefs: string | string[]; relationships: Fields[];
};
export type Relation = {
  target: string; target_id: string | null; nature: string; meaning: string; tension: string;
  attitude: string; text: string; source_id: string; section_id: string | null; provenance: string;
};
export type Person = {
  id: string; name: string; title: string; status: "structured" | "legacy"; warnings: string[];
  sections: Section[]; relationships: Relation[]; states: CharacterState[]; planned_arcs: Section[];
  raw: { source_id: string; title: string; text: string }[];
};
export type Inventory = {
  revision: string; chapter: string; chapters: string[]; stale_chapters: string[];
  characters: Person[]; world_facts: (Evidence & { description: string })[]; warnings: string[];
  sources: { source_id: string; kind: string; status: "present" | "missing"; revision: string | null; raw: string }[];
};
export type CharacterPreview = {
  preview_id: string; revision: string; source_revision: string; source_id: string;
  character_id: string; section_id: string; before: string; after: string;
  line: number; impact: string; history_id: string | null; assistant_source?: unknown;
};
export type HistoryEntry = {
  id: string; created_at: string; character_id: string; section_id: string; source_id: string;
  before: string; after: string; revision_before: string; revision_after: string;
  source_revision_before: string; source_revision_after: string; restored_from: string | null;
};
export type PolicyMode = "inherit" | "narrative_led";
export type Override = {
  preview_id: string; revision: string; source_id: string; source_sha256: string;
  source_category: string; quote: string; replacement: string; start: number; end: number;
  before: string; after: string;
};
type StaleOverride = { preview_id: string; source_id: string; quote: string; reason: string };
export type Policy = { mode: PolicyMode; revision: string; overrides: Override[]; stale_overrides: StaleOverride[] };
export type Finding = {
  source_id: string; source_kind: string; source_sha256: string; source_category: string;
  provenance: string; review_status: string; quote: string; start: number; end: number;
  line: number; rule: string; reason: string; override_eligible: boolean; suggestion: string;
};
export type Audit = {
  chapter: string; revision: string; findings: Finding[]; stale_overrides: StaleOverride[];
  sources: { source_id: string; source_kind: string; status: string; provenance: string }[];
};
type Trial = { chapter: string; character_ids: string[]; scene: string; baseline: string; candidate: string; checks: string[] };
export type Preferred = "baseline" | "candidate";
export type Preference = {
  entry_id: string; chapter: string; character_ids: string[]; scene: string; preferred: Preferred;
  reason: string; carry_forward: string; created_at: string; production_match?: boolean;
};
export type JobInput = {
  chapter: string; expected_revision: string; question: string;
} & ({ purpose: "character_edit"; character_id: string; section_id: string }
  | { purpose: "dialogue_trial"; character_ids: string[]; baseline: string; scene: string });
export type JobSource = {
  chapter: string; revision: string; character_ids: string[];
  character_id?: string; section_id?: string; source_id?: string; scene?: string;
};
export type Job = {
  id: string; purpose: JobInput["purpose"]; chapter: string; status: "running" | "completed" | "failed";
  created_at: string; finished_at?: string; attempt?: number; message?: string; error_code?: string;
  model?: string; elapsed_seconds?: number; stale?: boolean; suggestion?: CharacterPreview; trial?: Trial;
  character_source?: JobSource;
};

export class CharacterCenterError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}
export function errorText(error: unknown) {
  return error instanceof Error ? error.message : "请求失败，请重试。";
}

export function characterApi({ workspace, workflowId }: Scope) {
  const scope = { workspace, workflow_id: workflowId };
  async function send<T>(route: string, params: Record<string, string>, signal: AbortSignal, body?: object): Promise<T> {
    const suffix = body ? "" : "?" + new URLSearchParams({ ...scope, ...params });
    const response = await fetch("/api/" + route + suffix, body ? {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...scope, ...body }), signal,
    } : { signal });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new CharacterCenterError(response.status, typeof data?.detail === "string" ? data.detail : "请求失败（HTTP " + response.status + "）。");
    }
    if (data == null) throw new Error("服务没有返回有效结果。");
    return data as T;
  }
  const get = <T,>(path: string, signal: AbortSignal, params: Record<string, string> = {}) => send<T>(path, params, signal);
  const post = <T,>(path: string, signal: AbortSignal, body: object) => send<T>(path, {}, signal, body);
  return {
    inventory: (chapter: string, q: string, signal: AbortSignal) =>
      get<Inventory>("humanware/characters", signal, { ...(chapter && { chapter }), ...(q && { q }) }),
    history: (character_id: string, signal: AbortSignal) =>
      get<{ entries: HistoryEntry[] }>("humanware/character-history", signal, { character_id }),
    preview: (character_id: string, expected_revision: string, input: { history_id: string } | { section_id: string; source_id: string; replacement: string }, signal: AbortSignal) =>
      post<CharacterPreview>("humanware/character-preview", signal, { character_id, expected_revision, ...input }),
    apply: (expected_revision: string, preview: CharacterPreview, signal: AbortSignal) =>
      post<{ revision: string; entry: HistoryEntry }>("humanware/character-apply", signal, { expected_revision, preview }),
    policy: (signal: AbortSignal) => get<Policy>("humanware/prose-policy", signal),
    audit: (chapter: string, signal: AbortSignal) => get<Audit>("humanware/rule-audit", signal, { chapter }),
    savePolicy: (expected_revision: string, values: { mode?: PolicyMode; overrides?: Override[] }, signal: AbortSignal) =>
      post<Policy>("humanware/prose-policy", signal, { expected_revision, ...values }),
    previewRule: (expected_revision: string, finding: Finding, replacement: string, signal: AbortSignal) =>
      post<Override>("humanware/rule-audit", signal, { expected_revision, source_id: finding.source_id, quote: finding.quote, replacement }),
    start: (request_id: string, input: JobInput, signal: AbortSignal) =>
      post<{ entry: Job }>("novel-console/assistant", signal, { request_id, ...input }),
    jobs: (signal: AbortSignal) => get<{ entries: Job[] }>("novel-console/assistant/history", signal),
    accept: (entry_id: string, preferred: Preferred, reason: string, carry_forward: string, signal: AbortSignal) =>
      post<{ preference: Preference }>("novel-console/assistant/trial-accept", signal, { entry_id, preferred, reason, carry_forward }),
  };
}
export type CharacterApi = ReturnType<typeof characterApi>;
