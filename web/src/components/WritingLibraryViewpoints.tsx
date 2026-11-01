import type { WritingLibraryItem } from "../lib/api";

const labels: Record<string, string> = { first_person: "第一人称", second_person: "第二人称", third_person: "第三人称" };

export default function WritingLibraryViewpoints({ metadata }: { metadata: WritingLibraryItem["pov_metadata"] }) {
  const source = metadata?.source_pov.map(value => labels[value] || "待判断").join("、");
  const target = metadata?.target_pov.map(value => labels[value] || "待核对").join("、");
  return <div className="mt-3 space-y-1 text-xs leading-6 text-muted-foreground">
    <p aria-label="原作叙事视角">原作叙事：{metadata?.source_status === "mixed" ? `混合视角${source ? `（${source}）` : ""}` : metadata?.source_status === "known" && source ? source : "待判断"}</p>
    <p aria-label="写法适用视角">写法适用：{target || "待核对"}{metadata?.target_status === "partial" ? "；部分写法视角待核对" : ""}{target ? "；需逐条确认适配" : ""}</p>
  </div>;
}
