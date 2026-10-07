import type {NovelAssistantEntry} from './api';

// One durable step: reopening the page resumes the same request, never silently
// replaces a reader's issues with generic feedback or applies an unfinished plan.
export async function advanceRepairPlan(
  requestId: string,
  operations: {
    history: () => Promise<NovelAssistantEntry[]>;
    ask: () => Promise<NovelAssistantEntry>;
    apply: (entry: NovelAssistantEntry) => Promise<{feedback_path: string; model_id: string}>;
    active: () => boolean;
  },
): Promise<{feedback_path: string; model_id: string} | null> {
  const entries = await operations.history();
  if (!operations.active()) return null;
  let entry = entries.find(item => item.id === requestId);
  if (!entry) {
    if (entries.some(item => item.status === 'running')) return null;
    entry = await operations.ask();
  }
  if (!operations.active() || entry.id !== requestId || entry.status === 'running') return null;
  if (entry.status === 'failed') throw new Error(entry.message || 'AI 返修规划失败，请查看助手提示后重试。');
  if (entry.purpose !== 'reader_repair' || !entry.reply.trim()) throw new Error('返修方案不完整，尚未修改正文，请重新规划。');
  return operations.apply(entry);
}
