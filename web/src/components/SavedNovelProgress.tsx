import { useEffect, useState } from "react";
import { getNovelProgress, type NovelProgress } from "../lib/api";
import type { ChapterLifecycle } from "../lib/novel-progress-types";

const labels: Record<string, string> = {
  completed: "已完成", failed: "失败", running: "进行中", stopped: "已停止", skipped: "已跳过",
  pending: "待执行", retry_waiting: "等待重试", resume_pending: "等待恢复", interrupted: "已中断",
  waiting_approval: "等待确认", preparing: "准备中", pre_running: "准备中", cancelled: "已取消",
};
const lifecycleLabels: Array<[keyof Omit<ChapterLifecycle, "chapter">, string, Record<string, string>]> = [
  ["plan", "规划", { planned: "已有计划", stale: "依据失效", missing: "暂无计划" }],
  ["draft", "正文", { present: "已有正文", missing: "暂无正文" }],
  ["assessment", "读者评估", { pass: "通过", revise: "建议返修", reject: "未通过", missing: "暂无评估", unverified: "报告待复核" }],
  ["confirmation", "确认档案", { verified: "证据有效", stale: "证据失效", missing: "尚无确认记录" }],
  ["export", "导出", { recorded: "本章已列入导出", stale: "导出已过期", missing: "暂无本章导出", unknown: "导出范围待确认" }],
];

export function ChapterLifecycleSummary({ lifecycle }: { lifecycle: ChapterLifecycle }) {
  return <section aria-label="章节实际产物" className="space-y-2 text-xs">
    <p className="font-medium">第 {Number(lifecycle.chapter)} 章 · 实际产物与记录</p>
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {lifecycleLabels.map(([key, name, values]) => <div className="rounded-md border border-border px-2 py-1.5" key={key}>
        <dt className="text-muted-foreground">{name}</dt><dd>{values[lifecycle[key]] || "状态待确认"}</dd>
      </div>)}
    </dl>
  </section>;
}

export function SelectedChapterLifecycle({ workflowId, workspace, chapter }: { workflowId: string; workspace: string; chapter: string }) {
  const [result, setResult] = useState<NovelProgress>();
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void getNovelProgress(workflowId, workspace, chapter, controller.signal).then(progress => {
      if (!controller.signal.aborted) setResult(progress);
    }).catch(() => {
      if (!controller.signal.aborted) setError("暂时无法读取本章产物状态。");
    });
    return () => controller.abort();
  }, [workflowId, workspace, chapter]);
  return result ? <SavedNovelProgress progress={result} />
    : <p className="text-xs text-muted-foreground">{error || "正在读取章节产物…"}</p>;
}

export default function SavedNovelProgress({ progress }: { progress: NovelProgress }) {
  const stages = progress.stages?.filter(stage => stage.task) || [];
  return <div className="space-y-4">
    {progress.lifecycle && <ChapterLifecycleSummary lifecycle={progress.lifecycle} />}
    {progress.pause_reason && <p className="break-words text-xs text-muted-foreground">自动创作 · {progress.pause_reason}</p>}
    {stages.length > 0 && <details className="space-y-2 text-xs">
      <summary className="cursor-pointer font-medium">任务与节点记录 · {stages.length} 个步骤</summary>
      {stages.map(({ task, label, id }) => task && <article className="space-y-2 rounded-lg border border-border p-3" key={id}>
        <h4 className="font-medium">{label} · {labels[task.status] || "状态待确认"}{task.elapsed_seconds != null ? " · 耗时 " + task.elapsed_seconds + " 秒" : ""}</h4>
        <p className="break-all text-muted-foreground">任务 {task.task_id}</p>
        {task.reason && <p className="break-words text-destructive">{task.reason}</p>}
        {task.usage && <p className="break-words text-muted-foreground">
          {task.usage.basis === "ledger" ? "调用日志" : "任务用量汇总"}
          {task.usage.models.length ? " · 模型 " + task.usage.models.join("、") : ""}
          {task.usage.call_count != null ? " · 记录 " + task.usage.call_count + " 次调用" : ""}
          {task.usage.total_tokens != null ? " · " + task.usage.total_tokens.toLocaleString() + " token" : ""}
        </p>}
        {task.current_node_id && <p>当前节点 · {task.nodes.find(node => node.id === task.current_node_id)?.label || task.current_node_id}</p>}
        {task.nodes.length > 0 && <ul className="space-y-1">
          {task.nodes.map(node => <li className="break-words text-muted-foreground" key={node.id}>
            {node.label} · {labels[node.status] || "状态待确认"}
            {node.elapsed_seconds != null ? " · " + node.elapsed_seconds + " 秒" : ""}
            {node.attempt_count != null ? " · 尝试 " + node.attempt_count + " 次" : ""}
            {node.automatic_retry_count != null ? " · 自动重试 " + node.automatic_retry_count + " 次" : ""}
            {node.next_retry_at ? " · 下次重试 " + new Date(node.next_retry_at).toLocaleString() : ""}
            {node.reason && <span className="block text-destructive">{node.reason}</span>}
          </li>)}
        </ul>}
      </article>)}
    </details>}
  </div>;
}
