import { useEffect, useState } from "react";
import { getProviderQueues, resumeProviderQueue, type ProviderQueueStatus } from "../lib/api";
import { parseApiError } from "../settings/parse-api-error";
import { Button } from "./ui/button";

export default function ProviderQueues() {
  const [groups, setGroups] = useState<Record<string, ProviderQueueStatus>>({});
  const [error, setError] = useState("");
  useEffect(() => {
    let mounted = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const { groups } = await getProviderQueues();
        if (mounted) { setGroups(groups); setError(""); }
      } catch (err) {
        if (mounted) setError(parseApiError(err, "无法读取供应商队列"));
      } finally {
        if (mounted) timer = setTimeout(poll, 3000);
      }
    }
    void poll();
    return () => { mounted = false; clearTimeout(timer); };
  }, []);

  return <>
    {error && <p role="alert">{error}</p>}
    {Object.entries(groups).filter(([, g]) => (g.state !== "ready" || g.waiting > 0)).map(([id, g]) => (
          <div key={id} role="status" className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm">
            <span>{g.provider_name} · {g.state === "active"
              ? g.first_word_overdue ? "等待首字已超过 2 分钟，仍在等待原请求" : g.first_word ? "正在生成" : "等待首字"
              : g.state === "cooldown" ? "冷却至 " + new Date(g.until * 1000).toLocaleTimeString()
              : g.reason || "等待调度"} · 排队 {g.waiting}</span>
            {g.state === "paused" && <Button variant="outline" onClick={async () => {
              try {
                await resumeProviderQueue(id);
                setGroups((await getProviderQueues()).groups);
              } catch (err) { setError(parseApiError(err, "恢复失败")); }
            }}>恢复分组</Button>}
          </div>
        ))}
  </>;
}
