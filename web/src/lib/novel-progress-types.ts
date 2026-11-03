export type ChapterLifecycle = {
  chapter: string; plan: string; draft: string; assessment: string; confirmation: string; export: string;
};
type Usage = { basis: "ledger" | "summary"; models: string[]; total_tokens?: number; call_count?: number };
type SavedNode = {
  id: string; label: string; status: string; elapsed_seconds: number | null;
  attempt_count?: number; automatic_retry_count?: number; next_retry_at?: string; reason?: string;
};
type SavedTask = {
  task_id: string; status: string; current_node_id: string | null; elapsed_seconds: number | null;
  reason: string; nodes: SavedNode[]; usage: Usage | null;
};
export type NovelProgress = {
  percent: number; completed_count: number; total_count: number; label: string; chapter_count: number;
  can_download: boolean; export_current: boolean; reader_verdict: string; lifecycle?: ChapterLifecycle; pause_reason?: string;
  stages?: { id: string; label: string; completed: boolean; status: string; task?: SavedTask }[];
};
