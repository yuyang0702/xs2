import type { NovelAssistantEntry } from './api';

export type ConfigurationReceipt = { applied: string[]; preserved: string[]; at: string };
type ConfigurableProject = {
  mode: string; values: Record<string, string>; configuredFields?: string[];
  assistantConfigurations?: Record<string, ConfigurationReceipt>;
  refs: Record<string, unknown>; completed: string[];
};
const allowed = new Set(['premise', 'genre', 'narrative_pov', 'target_word_count', 'words_per_chapter',
  'estimated_length', 'world_direction', 'conflict_plan_mode', 'conflict_point_count',
  'foreshadowing_count', 'human_intent', 'world_intent']);
const storyFacts = new Set(['premise', 'genre', 'narrative_pov', 'world_direction', 'estimated_length',
  'conflict_plan_mode', 'conflict_point_count', 'foreshadowing_count']);

export function applyAssistantConfiguration<T extends ConfigurableProject>(
  project: T, entry: NovelAssistantEntry, defaults: Record<string, string>, hasStoryFacts = false,
): T & { assistantConfigurations?: Record<string, ConfigurationReceipt> } {
  if (entry.status !== 'completed' || entry.purpose !== 'configure' || !entry.configuration_base ||
      project.assistantConfigurations?.[entry.id]) return project;
  const baseline: Record<string, string> = { ...defaults, ...(project.mode === 'serial' ? {
    conflict_plan_mode: 'serial_opening', conflict_point_count: '4', foreshadowing_count: '3',
  } : {}) };
  const established = hasStoryFacts || entry.configuration_base.has_story_facts || !!project.refs.build || project.completed.includes('build');
  const values = { ...project.values };
  const applied: string[] = [], preserved: string[] = [];
  for (const item of entry.suggestions || []) {
    if (!allowed.has(item.key)) continue;
    const current = values[item.key] || '';
    const requested = entry.configuration_base.values[item.key] || '';
    if ((established && storyFacts.has(item.key)) || project.mode !== entry.configuration_base.mode || current !== requested ||
        project.configuredFields?.includes(item.key) || (current.trim() && current !== (baseline[item.key] || ''))) {
      preserved.push(item.key);
      continue;
    }
    values[item.key] = item.value;
    applied.push(item.key);
  }
  return { ...project, values, assistantConfigurations: { ...project.assistantConfigurations,
    [entry.id]: { applied, preserved, at: new Date().toISOString() } } };
}

export function configurationDisplay(key: string, value: string): string {
  const enums: Record<string, string> = { first_person: '第一人称', third_person: '第三人称',
    short_full: '短篇全文', serial_opening: '长篇开局', serial_arc: '长篇当前卷', serial_chapter: '长篇当前章节' };
  return ['narrative_pov', 'conflict_plan_mode'].includes(key) ? enums[value] || value : value;
}

export function premiseWithWorldDirection(values: Record<string, string>): string {
  return [values.premise || '', values.world_direction?.trim() ? `世界观方向（规划草稿）：\n${values.world_direction.trim()}` : '',
    values.source_idea?.trim() ? `用户原始设定（保留细节，矛盾处按已采用的顾问建议澄清）：\n${values.source_idea.trim()}` : '',
    values.advisor_guidance?.trim() ? `已采用的小说顾问建议：\n${values.advisor_guidance.trim()}` : '',
  ].filter(Boolean).join('\n\n');
}
