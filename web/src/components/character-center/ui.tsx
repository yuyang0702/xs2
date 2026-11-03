import { useEffect, useRef, useState } from "react";

export const box = "space-y-3 rounded-xl border border-border bg-card/60 p-4";
export const button = "rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50";
export const primary = button + " border-primary/40 text-primary";
export const field = "rounded-lg border border-border bg-background px-3 py-2 text-sm";
export const muted = "text-sm text-muted-foreground";
export const prose = "whitespace-pre-wrap break-words text-sm leading-relaxed";

export function Problem({ message }: { message: string }) {
  return message ? <p role="alert" className="rounded-lg border border-destructive/30 p-2 text-sm text-destructive">{message}</p> : null;
}
export function Comparison({ before, after, afterLabel = "修改后" }: { before: string; after: string; afterLabel?: string }) {
  return <div className="grid gap-3 md:grid-cols-2">
    <div className={box}><h4 className="font-medium">原文</h4><p className={prose}>{before || "空白"}</p></div>
    <div className={box}><h4 className="font-medium">{afterLabel}</h4><p className={prose}>{after || "空白"}</p></div>
  </div>;
}

/** Serialize author actions and invalidate results on an unmounted scope. */
export function useAction() {
  const inFlight = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => () => inFlight.current?.abort(), []);
  async function run(action: (signal: AbortSignal) => Promise<void>) {
    if (inFlight.current) return;
    const controller = new AbortController();
    inFlight.current = controller;
    setBusy(true);
    try { await action(controller.signal); }
    finally {
      inFlight.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return { busy, run };
}
