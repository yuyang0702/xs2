let workflows: Record<string, string> = {};
type BookDefaults = {analysisModel?:string;writerModel?:string;polishModel?:string;values?:Record<string,string>};
let bookDefaults: BookDefaults = {};

// The workbench renders all these stage controls, even when a stage is optional
// for a particular book. Validate their identities before mounting that UI.
const requiredWorkflows = ['reference-distillation', 'novel-advisor', 'style-compatibility-advisor',
  'adopt-reference', 'build', 'character', 'story-plan', 'outline', 'mvp', 'polish',
  'reader-sim', 'post-hoc', 'export'];

export function validateNovelResources(value: unknown): asserts value is Record<string, string> {
  const resources = value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
  const missing = requiredWorkflows.filter(id => typeof resources[id] !== 'string' || !String(resources[id]).trim());
  if (missing.length) throw new Error(`小说插件缺少可用工作流：${missing.join('、')}。请更新或重新启用插件后重试。`);
}

export function setNovelResources(value: Record<string, string>, defaults:BookDefaults={}) {
  workflows = {...value};
  bookDefaults = structuredClone(defaults);
}

export function novelNewBookDefaults(allowDefaults=true):BookDefaults {
  return allowDefaults ? structuredClone(bookDefaults) : {};
}

export function novelWorkflowId(localId: string): string {
  const id = workflows[localId];
  if (!id) throw new Error(`小说插件没有提供「${localId}」工作流，请检查插件状态。`);
  return id;
}

export function novelStageId(workflowId: string): string | undefined {
  return Object.entries(workflows).find(([, id]) => id === workflowId)?.[0];
}
