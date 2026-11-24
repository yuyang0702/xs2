import { useState, type ReactNode } from "react";

/** Render a bounded page while preserving access to every imported chapter or library entry. */
export default function ReferencePages<T>({ items, pageSize = 20, children }: {
  items: T[]; pageSize?: number; children: (page: T[]) => ReactNode;
}) {
  const [requestedPage, setPage] = useState(0);
  const pageCount = Math.ceil(items.length / pageSize);
  const page = Math.min(requestedPage, Math.max(0, pageCount - 1));
  const buttonClass = "rounded-lg border border-border px-3 py-1.5 disabled:opacity-40";
  return <>
    {children(items.slice(page * pageSize, (page + 1) * pageSize))}
    {pageCount > 1 && <nav aria-label="分页" className="mt-3 flex flex-wrap items-center gap-3 text-xs">
      <button type="button" className={buttonClass} disabled={!page} onClick={() => setPage(page - 1)}>上一页</button>
      <label>第 <select aria-label="选择页码" className="rounded border border-border bg-background px-1 py-1" value={page} onChange={event => setPage(Number(event.target.value))}>
        {Array.from({length: pageCount}, (_, index) => <option key={index} value={index}>{index + 1}</option>)}
      </select> / {pageCount} 页</label>
      <button type="button" className={buttonClass} disabled={page + 1 >= pageCount} onClick={() => setPage(page + 1)}>下一页</button>
    </nav>}
  </>;
}
