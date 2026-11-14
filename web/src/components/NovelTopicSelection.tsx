import type { NovelTopicSelection as Selection } from '../lib/api';

const verdictLabels = { fits: '篇幅合适', too_thin: '中段支撑不足', too_broad: '故事范围过大' };

export default function NovelTopicSelection({ selection, onChoose }: {
  selection: Selection;
  onChoose?: (idea: string) => void;
}) {
  const assessments = new Map(selection.assessments.map(item => [item.id, item]));
  const candidates = new Map(selection.candidates.map(item => [item.id, item]));
  return <section className="space-y-5" aria-label="选题盲读结果">
    <p className="text-sm text-muted-foreground">正文目标 {selection.target_words} 字 · 按盲读追读意愿排列</p>
    {selection.ranking.map((reading, index) => {
      const candidate = candidates.get(reading.id);
      const assessment = assessments.get(reading.id);
      if (!candidate || !assessment) return null;
      return <article key={candidate.id} className="space-y-4 rounded-xl border border-border p-5">
        <div>
          <h4 className="font-semibold">{candidate.title}</h4>
          <p className="mt-1 text-sm text-muted-foreground">{candidate.genre}
            {index === 0 && ' · 盲读首选'}{selection.recommended_id === candidate.id && ' · 综合推荐'}</p>
        </div>
        <blockquote className="whitespace-pre-wrap border-l-2 border-primary/40 pl-4 text-sm leading-7">{candidate.opening}</blockquote>
        <div className="space-y-2 text-sm leading-6">
          <p><strong>盲读感受</strong>　{reading.reason}</p>
          <p className="text-muted-foreground">「{reading.excerpt}」</p>
          <p><strong>想追问</strong>　{reading.question}</p>
          <p><strong>{verdictLabels[assessment.verdict]}</strong>　{assessment.reason}</p>
          <p><strong>节奏风险</strong>　{assessment.risk}</p>
        </div>
        <details className="text-sm leading-6">
          <summary className="cursor-pointer font-medium">查看情节走向与篇幅依据</summary>
          <div className="mt-3 space-y-2">
            <p>{candidate.premise}</p>
            <p><strong>选择</strong>　{candidate.choice}</p>
            <p><strong>代价</strong>　{candidate.cost}</p>
            <p><strong>中段</strong>　{candidate.middle}</p>
            <p><strong>结尾</strong>　{candidate.ending}</p>
            <p><strong>编辑意见</strong>　{assessment.development}</p>
          </div>
        </details>
        {onChoose && <button type="button" className="rounded-lg border border-border px-3 py-2 text-sm"
          onClick={() => onChoose(`我想继续讨论《${candidate.title}》，题材是${candidate.genre}。\n${candidate.premise}\n主角的选择和代价：${candidate.choice} ${candidate.cost}\n中段：${candidate.middle}\n结尾：${candidate.ending}\n正文字数目标为 ${selection.target_words} 字。请根据这个方向给出完整顾问方案、适配写法和设置建议。`)}>
          继续讨论这个题材
        </button>}
      </article>;
    })}
  </section>;
}
