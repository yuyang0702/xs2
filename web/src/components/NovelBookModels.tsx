import { useEffect, useState } from "react";
import { getAllModels } from "../lib/api";

export type BookModels = { analysisModel: string; writerModel: string; polishModel: string };
const fields = [
  ["analysisModel", "资料与规划模型"],
  ["writerModel", "正文写手模型"],
  ["polishModel", "润色模型"],
] as const;

export default function NovelBookModels({ value, onChange }: {
  value: BookModels; onChange: (next: BookModels) => void;
}) {
  const [options, setOptions] = useState<Array<{ value: string; label: string }>>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void getAllModels().then(result => {
      if (active) setOptions(result.models);
    }).catch(failure => { if (active) setError(String(failure)); });
    return () => { active = false; };
  }, []);
  return <div className="space-y-4">
    {fields.map(([key, label]) => <label key={key} className="block text-sm">{label}
      <select aria-label={label} value={value[key]} onChange={event => onChange({ ...value, [key]: event.target.value })}
        className="mt-2 w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm">
        <option value="">沿用对应步骤的模型设置</option>
        {value[key] && !options.some(option => option.value === value[key]) &&
          <option value={value[key]}>已保存 · {value[key]}</option>}
        {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>)}
    {error && <p role="alert" className="text-sm text-destructive">读取可用模型失败，已保存的分工仍保留。{error}</p>}
  </div>;
}
