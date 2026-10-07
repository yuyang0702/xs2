import type { NovelAssistantEntry } from './api';
import { applyAssistantConfiguration, type ConfigurationReceipt } from './novel-assistant-configuration';
import { resumeProductionStage } from './novel-writing-selection';

export function advisorMarkdown(content: string) {
  // CommonMark needs a boundary after punctuation-ending emphasis in CJK text.
  return content.replace(/\*\*([^*\n]+)\*\*(?=[\p{L}\p{N}])/gu, '**$1** ');
}

type AdviserProject = {
  mode: string; values: Record<string, string>; refs: Record<string, unknown>; completed: string[];
  configuredFields?: string[]; assistantConfigurations?: Record<string, ConfigurationReceipt>;
  stageId?: string; index: number; directionConfirmed: boolean; advisorAccepted: boolean;
  autoNext: boolean; autoLaunchStage?: string; autoPauseReason?: string;
};

export function adoptNovelAdvisor<T extends AdviserProject>(project: T, entry: NovelAssistantEntry,
  defaults: Record<string, string>, stages: Array<{id: string}>, hasStoryFacts = false,
): {project: T; success: boolean; message: string} {
  const fail = (message: string) => ({project, success:false, message});
  if (entry.status !== 'completed' || entry.purpose !== 'advisor' || !entry.configuration_base)
    return fail('本次顾问方案尚未完成，请等分析结束后采用。');
  if (project.assistantConfigurations?.[entry.id]) return fail('这套方案已经采用，设置保留当前修改。');
  if (project.mode !== entry.configuration_base.mode) return fail('作品类型已变化，请让顾问按当前类型重新分析。');
  const updated = applyAssistantConfiguration(project, {...entry, purpose:'configure'}, defaults, hasStoryFacts);
  if (!updated.values.premise?.trim()) return fail('这套方案还没有明确故事创意，请继续讨论，或在手动设置中补充。');
  const production = stages.filter(stage => stage.id !== 'novel-advisor');
  const resume = resumeProductionStage(production, project.refs);
  const established = hasStoryFacts || entry.configuration_base.has_story_facts || !!project.refs.build;
  const target = established && !Object.keys(project.refs).some(key => production.some(stage=>stage.id===key))
    ? project.stageId : resume;
  const index = stages.findIndex(stage => stage.id === target);
  if (index < 0) return fail('没有找到后续创作步骤，请刷新工作流目录后再采用。');
  return {project: {...updated, values:{...updated.values,
    source_idea:entry.configuration_base.advisor_brief || entry.question,
    advisor_guidance:[entry.reply, ...Object.values(entry.advisor_sections || {})].join('\n\n')},
    stageId:target, index, directionConfirmed:true, advisorAccepted:true,
    autoNext:false, autoLaunchStage:'', autoPauseReason:''}, success:true,
    message: established ? '顾问建议已采用，原有故事事实与创作进度持续保留。' : '顾问方案已采用，设置已填写；接下来建立世界观。'};
}
