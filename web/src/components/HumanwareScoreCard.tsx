/**
 * 人味评分卡片组件
 *
 * 显示章节内容的人味评分，包括：
 * - 声音一致性
 * - 对话自然度
 * - 情感真实度
 * - 行为一致性
 */

import React from 'react';
import { Heart, TrendingUp, AlertCircle, CheckCircle, XCircle } from 'lucide-react';

interface HumanwareScore {
  total_score: number;
  grade: string;
  summary: string;
  detailed_scores: {
    声音一致性: number;
    对话自然度: number;
    情感真实度: number;
    行为一致性: number;
  };
  issues: Array<{
    dimension: string;
    type: string;
    severity?: string;
    message: string;
  }>;
  recommendation: string;
}

interface HumanwareScoreCardProps {
  score: HumanwareScore;
  className?: string;
}

export default function HumanwareScoreCard({ score, className = '' }: HumanwareScoreCardProps) {
  const getScoreColor = (scoreValue: number) => {
    if (scoreValue >= 90) return 'text-green-600';
    if (scoreValue >= 80) return 'text-blue-600';
    if (scoreValue >= 70) return 'text-yellow-600';
    if (scoreValue >= 60) return 'text-orange-600';
    return 'text-red-600';
  };

  const getGradeColor = (grade: string) => {
    if (grade.startsWith('A')) return 'bg-green-500/10 text-green-600 border-green-500/20';
    if (grade.startsWith('B')) return 'bg-blue-500/10 text-blue-600 border-blue-500/20';
    if (grade.startsWith('C')) return 'bg-yellow-500/10 text-yellow-600 border-yellow-500/20';
    if (grade.startsWith('D')) return 'bg-orange-500/10 text-orange-600 border-orange-500/20';
    return 'bg-red-500/10 text-red-600 border-red-500/20';
  };

  const getSeverityIcon = (severity?: string) => {
    if (severity === 'high') return <XCircle className="h-4 w-4 text-red-500" />;
    if (severity === 'medium') return <AlertCircle className="h-4 w-4 text-yellow-500" />;
    return <AlertCircle className="h-4 w-4 text-blue-500" />;
  };

  const cardClass = 'rounded-2xl border border-border bg-card shadow-sm';

  return (
    <div className={`${cardClass} p-5 ${className}`}>
      {/* 头部 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Heart className="h-5 w-5 text-rose-500" />
          <h3 className="text-lg font-semibold">人味评分</h3>
        </div>
        <div className={`rounded-full border px-3 py-1 text-sm font-semibold ${getGradeColor(score.grade)}`}>
          {score.grade}
        </div>
      </div>

      {/* 总分 */}
      <div className="mt-4 flex items-baseline gap-2">
        <span className={`text-4xl font-bold ${getScoreColor(score.total_score)}`}>
          {score.total_score}
        </span>
        <span className="text-sm text-muted-foreground">/ 100</span>
      </div>

      <p className="mt-2 text-sm text-muted-foreground">{score.summary}</p>

      {/* 详细分数 */}
      <div className="mt-6 space-y-3">
        <h4 className="text-sm font-semibold">各维度得分</h4>
        {Object.entries(score.detailed_scores).map(([dimension, value]) => (
          <div key={dimension} className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">{dimension}</span>
            <div className="flex items-center gap-3">
              <div className="h-2 w-32 rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full transition-all ${
                    value >= 90 ? 'bg-green-500' :
                    value >= 80 ? 'bg-blue-500' :
                    value >= 70 ? 'bg-yellow-500' :
                    value >= 60 ? 'bg-orange-500' :
                    'bg-red-500'
                  }`}
                  style={{ width: `${value}%` }}
                />
              </div>
              <span className={`text-sm font-semibold ${getScoreColor(value)}`}>
                {value}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* 问题列表 */}
      {score.issues.length > 0 && (
        <div className="mt-6">
          <h4 className="text-sm font-semibold">发现的问题</h4>
          <div className="mt-3 space-y-2">
            {score.issues.slice(0, 5).map((issue, index) => (
              <div key={index} className="flex items-start gap-2 rounded-lg bg-muted/50 p-3">
                {getSeverityIcon(issue.severity)}
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-semibold text-muted-foreground">
                    {issue.dimension}
                  </div>
                  <div className="mt-1 text-sm">{issue.message}</div>
                </div>
              </div>
            ))}
            {score.issues.length > 5 && (
              <p className="text-xs text-muted-foreground text-center">
                还有 {score.issues.length - 5} 个问题未显示
              </p>
            )}
          </div>
        </div>
      )}

      {/* 改进建议 */}
      {score.recommendation && (
        <div className="mt-6 rounded-lg border border-blue-500/20 bg-blue-500/5 p-4">
          <div className="flex items-start gap-2">
            <TrendingUp className="h-4 w-4 text-blue-600 mt-0.5 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <h4 className="text-sm font-semibold text-blue-600">改进建议</h4>
              <p className="mt-1 text-sm text-blue-600/80">{score.recommendation}</p>
            </div>
          </div>
        </div>
      )}

      {/* 说明 */}
      <div className="mt-6 pt-4 border-t border-border">
        <p className="text-xs text-muted-foreground leading-5">
          人味评分综合评估角色声音一致性、对话自然度、情感真实度和行为一致性。
          得分越高，内容越具有真实感和人性化。
        </p>
      </div>
    </div>
  );
}

/**
 * 简化版人味评分徽章
 */
export function HumanwareScoreBadge({ score, onClick }: { score: number; onClick?: () => void }) {
  const getColor = () => {
    if (score >= 90) return 'bg-green-500/10 text-green-600 border-green-500/20';
    if (score >= 80) return 'bg-blue-500/10 text-blue-600 border-blue-500/20';
    if (score >= 70) return 'bg-yellow-500/10 text-yellow-600 border-yellow-500/20';
    if (score >= 60) return 'bg-orange-500/10 text-orange-600 border-orange-500/20';
    return 'bg-red-500/10 text-red-600 border-red-500/20';
  };

  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold transition-colors hover:opacity-80 ${getColor()}`}
    >
      <Heart className="h-3 w-3" />
      <span>人味 {score}</span>
    </button>
  );
}
