export function retainAdoptedWriting(selected: string[], adopted: string[]) {
  return [...new Set([...adopted, ...selected])];
}

export function toggleWriting(selected: string[], adopted: string[], id: string, checked: boolean) {
  const retained = retainAdoptedWriting(selected, adopted);
  return checked ? retainAdoptedWriting(retained, [id]) : retained.filter(item => item !== id || adopted.includes(item));
}

export function resumeProductionStage(stages: Array<{id: string}>, refs: Record<string, unknown>) {
  // Reference-module navigation must not send an existing book back to build.
  return [...stages].reverse().find(stage => !!refs[stage.id])?.id || 'build';
}

export function validateReferenceAdaptations(choices: Array<{choice_id: string; requires_adaptation: boolean; title: string}>, selected: string[], adopted: string[], adaptations: Record<string, string>) {
  const missing = choices.find(item => selected.includes(item.choice_id) && !adopted.includes(item.choice_id) && item.requires_adaptation && !adaptations[item.choice_id]?.trim());
  return missing ? `请先填写「${missing.title}」的本书适配说明，也可以先让 AI 检查适配。` : "";
}
