import NovelArchiveContent from './NovelArchiveContent';

export default function NovelConflictPatterns({patterns, collapsible = false}: {patterns: unknown[]; collapsible?: boolean}) {
  const content = <NovelArchiveContent content={JSON.stringify({conflict_chain: patterns})} structured />;
  return collapsible ? <details className="mt-3"><summary className="cursor-pointer text-sm text-primary">查看冲突递进链（共 {patterns.length} 组）</summary><div className="mt-4">{content}</div></details> : content;
}
