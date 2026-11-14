export const box = "space-y-3 rounded-xl border border-border bg-card/60 p-4";
export const button = "rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50";
export const primary = button + " border-primary/40 text-primary";
export const field = "rounded-lg border border-border bg-background px-3 py-2 text-sm";
export const muted = "text-sm text-muted-foreground";
export const prose = "whitespace-pre-wrap break-words text-sm leading-relaxed";

export function Problem({ message }: { message: string }) {
  return message ? <p role="alert" className="rounded-lg border border-destructive/30 p-2 text-sm text-destructive">{message}</p> : null;
}
export function Comparison({ before, after, beforeLabel = "原文", afterLabel = "修改后" }: { before: string; after: string; beforeLabel?: string; afterLabel?: string }) {
  return <div className="grid gap-3 md:grid-cols-2">
    <div className={box}><h4 className="font-medium">{beforeLabel}</h4><p className={prose}>{before || "空白"}</p></div>
    <div className={box}><h4 className="font-medium">{afterLabel}</h4><p className={prose}>{after || "空白"}</p></div>
  </div>;
}
