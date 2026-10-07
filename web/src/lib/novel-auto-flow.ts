export function readerRepairDecision(verdict: string, automatic: boolean, count: number, limit: number): { repair: boolean; pauseReason: string } {
  if (!["pass", "revise", "reject"].includes(verdict)) return { repair: false, pauseReason: "评估报告没有有效结论，已暂停推进。请重新执行读者评估。" };
  const repair = verdict !== "pass";
  if (repair && automatic && count >= limit) return { repair, pauseReason: `本章已自动返修 ${count} 次，读者仍提出问题。已暂停，请阅读建议后决定是否继续返修。` };
  return { repair, pauseReason: "" };
}

export function shouldAdvanceSerialChapter(mode: string, scope: string, started: number | null, limit: number, endingMode = "continue"): boolean {
  return mode === "serial" && scope === "serial_batch" && endingMode !== "book_final" && (started || 1) < limit;
}
