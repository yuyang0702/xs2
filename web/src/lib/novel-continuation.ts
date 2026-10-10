export type NovelContinuationCheck = {
  ready: boolean;
  action: string;
  chapter: string;
  message: string;
  next_step?: string;
  reason_code?: string;
  changed_sources?: string[];
};

const SETUP_STAGES = ["build", "character", "story-plan", "outline"];
const PRODUCTION_STAGES = ["mvp", "polish", "reader-sim", "post-hoc", "export"];

export function nextNovelStageAfterReferenceAdoption(
  completed: string[],
  currentStageId: string,
  check?: NovelContinuationCheck | null,
) {
  const firstMissingSetup = SETUP_STAGES.find((stage) => !completed.includes(stage));
  if (firstMissingSetup) return firstMissingSetup;

  const currentProductionStage = PRODUCTION_STAGES.includes(currentStageId) ? currentStageId : "";
  const nextProductionStage = currentProductionStage && !completed.includes(currentProductionStage)
    ? currentProductionStage
    : PRODUCTION_STAGES.find((stage) => !completed.includes(stage)) || "export";

  if (nextProductionStage === "mvp" && check && !check.ready) {
    return check.action || "outline";
  }
  return nextProductionStage;
}
