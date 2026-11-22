import { useEffect, useState } from "react";
import { getNovelZhuqueOptions, saveNovelZhuqueOptions, type ZhuqueOptions } from "../lib/api";

type Props = {
  workflowId: string;
  workspace: string;
  disabled: boolean;
  onPendingChange: (pending: boolean) => void;
};

export default function NovelZhuqueOptions({ workflowId, workspace, disabled, onPendingChange }: Props) {
  const [saved, setSaved] = useState<ZhuqueOptions | null>(null);
  const [reference, setReference] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const dirty = !!saved && reference !== saved.reference_text;
  const locked = disabled || saving || !saved;

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    void getNovelZhuqueOptions(workflowId, workspace, controller.signal).then(options => {
      if (controller.signal.aborted) return;
      setSaved(options);
      setReference(options.reference_text);
    }).catch(failure => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "读取朱雀设置失败");
    });
    return () => controller.abort();
  }, [workflowId, workspace, reload]);

  useEffect(() => {
    onPendingChange(dirty || saving);
    return () => onPendingChange(false);
  }, [dirty, saving, onPendingChange]);

  async function save(changes: Partial<ZhuqueOptions>) {
    if (locked) return;
    setSaving(true);
    setError("");
    try {
      const options = await saveNovelZhuqueOptions(workflowId, workspace, changes);
      setSaved(options);
      setReference(options.reference_text);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "保存朱雀设置失败");
    } finally {
      setSaving(false);
    }
  }

  return <section aria-label="本书朱雀检测设置" aria-busy={saving} className="rounded-xl border border-border bg-card p-4">
    <label className="flex items-center gap-2 text-sm font-medium">
      <input type="checkbox" checked={saved?.enabled ?? false} disabled={locked}
        onChange={event => void save({ enabled: event.target.checked, ...(dirty && { reference_text: reference }) })} />
      启用朱雀全文检测
    </label>
    <p className="mt-2 text-xs leading-5 text-muted-foreground">启用后，整章润色会将全文提交给腾讯朱雀，消耗检测额度。每轮改完所有标记处后，再提交全文复测。</p>
    {saved?.enabled && <div className="mt-3 space-y-2">
      <label className="block text-sm">同篇已通过的参考稿（选填）
        <textarea value={reference} rows={3} maxLength={10_000_000} disabled={locked}
          onChange={event => setReference(event.target.value)} placeholder="粘贴同篇已通过朱雀检测的版本或段落"
          className="mt-1 block w-full rounded-lg border border-border bg-background px-3 py-2 text-sm" />
      </label>
      {dirty && <div className="flex items-center gap-3 text-xs">
        <button type="button" disabled={locked} onClick={() => void save({ reference_text: reference })} className="rounded-lg bg-primary px-3 py-2 text-primary-foreground">保存参考稿</button>
        <button type="button" disabled={locked} onClick={() => setReference(saved.reference_text)}>撤销修改</button>
      </div>}
    </div>}
    {!saved && !error && <p role="status" className="mt-2 text-xs">正在读取本书的朱雀设置…</p>}
    {saving && <p role="status" className="mt-2 text-xs">正在保存朱雀设置…</p>}
    {error && <p role="alert" className="mt-2 text-xs text-destructive">{error}
      {!saved && <button type="button" className="ml-2 underline" onClick={() => setReload(value => value + 1)}>重新读取</button>}
    </p>}
  </section>;
}
