export function shouldAdvanceSerialChapter(mode: string, scope: string, started: number | null, limit: number, endingMode = "continue"): boolean {
  return mode === "serial" && scope === "serial_batch" && endingMode !== "book_final" && (started || 1) < limit;
}
