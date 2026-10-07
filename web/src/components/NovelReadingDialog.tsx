import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

export default function NovelReadingDialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog ref={ref} aria-labelledby={titleId} onClose={onClose} className="m-auto h-[90vh] w-[min(960px,95vw)] max-w-none overflow-hidden rounded-2xl border border-border bg-card p-0 text-foreground shadow-2xl backdrop:bg-black/60"><div className="flex h-full flex-col"><header className="flex shrink-0 items-center justify-between gap-4 border-b border-border px-5 py-4"><h2 id={titleId} className="text-lg font-semibold">{title}</h2><button autoFocus onClick={onClose} aria-label="关闭阅读" className="rounded-lg p-2 text-muted-foreground hover:bg-secondary"><X className="h-5 w-5" /></button></header><div className="min-h-0 flex-1 overflow-auto px-5 py-6 sm:px-10"><div className="mx-auto max-w-[76ch]">{children}</div></div></div></dialog>;
}
