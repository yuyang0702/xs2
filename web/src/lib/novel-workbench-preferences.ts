export const NOVEL_UI_KEY = "xs2-novel-workbench-ui-v1";
export type NovelPreferences = {
  theme: "eva" | "quiet" | "paper"; motion: "off" | "light" | "full";
  fontSize: number; lineHeight: number; readingWidth: number;
};
export const defaultNovelPreferences: NovelPreferences = { theme: "eva", motion: "light", fontSize: 17, lineHeight: 1.9, readingWidth: 76 };
export function normalizeNovelPreferences(raw: unknown): NovelPreferences {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  return {
    theme: ["eva", "quiet", "paper"].includes(String(value.theme)) ? value.theme as NovelPreferences["theme"] : "eva",
    motion: ["off", "light", "full"].includes(String(value.motion)) ? value.motion as NovelPreferences["motion"] : "light",
    fontSize: [16, 17, 18, 20, 22].includes(Number(value.fontSize)) ? Number(value.fontSize) : 17,
    lineHeight: [1.7, 1.9, 2.1, 2.3].includes(Number(value.lineHeight)) ? Number(value.lineHeight) : 1.9,
    readingWidth: [62, 76, 94].includes(Number(value.readingWidth)) ? Number(value.readingWidth) : 76,
  };
}
export function readNovelPreferences(storage: Pick<Storage, "getItem">): NovelPreferences {
  try { return normalizeNovelPreferences(JSON.parse(storage.getItem(NOVEL_UI_KEY) || "null")); }
  catch { return { ...defaultNovelPreferences }; }
}
export function effectiveNovelMotion(motion: NovelPreferences["motion"], reduced: boolean) { return reduced ? "off" : motion; }
