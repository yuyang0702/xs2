import React, { useEffect, useState } from "react";
import type { WorkflowTask } from "../types";
import { buildNovelTaskProgress, type NovelNodeCounts } from "../lib/novel-task-progress";

type Props = { task: WorkflowTask | null; now?: number };
const statusLabels: Record<string, string> = {
  idle: "尚未启动", pending: "待执行", pre_running: "准备执行", resume_pending: "等待恢复",
  running: "执行中", retry_waiting: "等待重试", completed: "已完成", failed: "执行失败", stopped: "已停止",
  waiting_approval: "等待确认", skipped: "已跳过",
};

function duration(seconds: number | null): string {
  if (seconds === null) return "待确认";
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60), remainder = seconds % 60;
  if (minutes < 60) return `${minutes} 分${remainder ? ` ${remainder} 秒` : ""}`;
  return `${Math.floor(minutes / 60)} 小时${minutes % 60 ? ` ${minutes % 60} 分` : ""}${remainder ? ` ${remainder} 秒` : ""}`;
}

function countsText(counts: NovelNodeCounts): string {
  return `已完成 ${counts.completed} · 已跳过 ${counts.skipped} · 执行中 ${counts.running} · 待执行 ${counts.pending} · 失败 ${counts.failed}`
    + (counts.retryWaiting ? ` · 等待重试 ${counts.retryWaiting}` : "")
    + (counts.waitingApproval ? ` · 等待确认 ${counts.waitingApproval}` : "")
    + (counts.unknown ? ` · 状态待确认 ${counts.unknown}` : "");
}

export default function NovelTaskProgress({ task, now }: Props) {
  const [clock, setClock] = useState(() => Date.now());
  const taskId = task?.task_id, taskStatus = task?.status;
  useEffect(() => {
    if (now !== undefined || !taskId || ["completed", "failed", "stopped"].includes(taskStatus || "")) return;
    setClock(Date.now());
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [now, taskId, taskStatus]);
  const progress = buildNovelTaskProgress(task, now ?? clock);
  const children = Object.values(progress.childCounts).reduce((sum, value) => sum + value, 0);
  const focused = [...progress.activeNodes, ...progress.failedNodes];
  return <section aria-label="阶段执行进度" className="space-y-3 rounded-xl border border-border bg-background/40 p-4">
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
      <span className="font-medium">{statusLabels[progress.status] || "状态待确认"}</span>
      <span className="text-muted-foreground">阶段耗时 {duration(progress.elapsedSeconds)}</span>
    </div>
    {progress.percent !== null ? <div>
      <div className="mb-1 flex justify-between gap-2 text-xs text-muted-foreground"><span>节点处理进度{progress.total !== null ? ` · ${progress.total} 个启用节点` : ""}</span><span>{progress.percent}%</span></div>
      <div role="progressbar" aria-label="节点处理进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.percent} className="h-2 overflow-hidden rounded-full bg-secondary"><div className="h-full bg-primary transition-[width]" style={{ width: `${progress.percent}%` }} /></div>
    </div> : <p className="text-xs text-muted-foreground">{progress.total !== null && progress.total > 0 ? "节点记录已处理，任务结果待确认" : "节点总数待确认"}</p>}
    <p className="text-xs leading-6 text-muted-foreground">主流程：{countsText(progress.counts)}{progress.disabledCount > 0 ? `；未启用 ${progress.disabledCount} 个节点` : ""}</p>
    {progress.counts.skipped > 0 && <p className="text-xs text-muted-foreground">跳过单独记录，可能来自分支条件、执行方案或失败策略。</p>}
    {children > 0 && <p className="text-xs leading-6 text-muted-foreground">子任务：{countsText(progress.childCounts)}</p>}
    {focused.length > 0 && <ul aria-label="当前节点" className="space-y-2">{focused.map((node, index) => <li key={`${node.path}:${index}`} className="rounded-lg border border-border px-3 py-2">
      <p className="break-words text-sm">{node.path}<span className="ml-2 text-xs text-muted-foreground">{statusLabels[node.status] || "状态待确认"}</span></p>
      <p className="mt-1 text-xs leading-6 text-muted-foreground">节点耗时 {duration(node.elapsedSeconds)}{node.attemptCount !== null ? ` · 尝试 ${node.attemptCount} 次` : ""}{node.automaticRetryCount > 0 ? ` · 自动重试 ${node.automaticRetryCount} 次` : ""}{node.status === "retry_waiting" ? ` · ${node.retryInSeconds === null ? "下次重试时间待确认" : `${duration(node.retryInSeconds)}后重试`}` : ""}</p>
      {node.reason && <p className="break-words text-xs text-destructive">{node.reason}</p>}
    </li>)}</ul>}
  </section>;
}
