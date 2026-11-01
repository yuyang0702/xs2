/**
 * 角色声音编辑器组件
 *
 * 功能：
 * 1. 显示和编辑 character_voice.md
 * 2. 从角色档案标题创建待填写模板
 * 3. 保存用户编辑，保留已有角色档案
 */

import React, { useState, useEffect } from 'react';
import { Users, Wand2, FileText, CheckCircle, AlertCircle, Save, RefreshCw } from 'lucide-react';

interface HumanwareStatus {
  voice_file_exists: boolean;
  profiles_file_exists: boolean;
  humanware_enabled: boolean;
  character_count: number;
}

interface CharacterVoiceEditorProps {
  workspaceId: string;
  workflowId: string;
  onClose?: () => void;
}

async function responseJson(response: Response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === 'string' ? detail : detail?.message || data.message || `请求失败（${response.status}）`);
  }
  return data;
}

export default function CharacterVoiceEditor({ workspaceId, workflowId }: CharacterVoiceEditorProps) {
  const [content, setContent] = useState('');
  const [status, setStatus] = useState<HumanwareStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null);
  const query = new URLSearchParams({ workflow_id: workflowId, workspace: workspaceId }).toString();

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setStatus(null);
    setContent('');
    setMessage(null);
    Promise.all([
      fetch(`/api/humanware/status?${query}`, { signal: controller.signal }).then(responseJson),
      fetch(`/api/humanware/voice-file?${query}`, { signal: controller.signal }).then(responseJson),
    ]).then(([nextStatus, document]) => {
      if (!controller.signal.aborted) {
        setStatus(nextStatus);
        setContent(document.content || '');
      }
    }).catch(error => {
      if (!controller.signal.aborted) setMessage({ type: 'error', text: error.message });
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [query]);

  const saveContent = async () => {
    setSaving(true);
    setMessage(null);
    try {
      await fetch('/api/humanware/voice-file', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow_id: workflowId, workspace: workspaceId, content }),
      }).then(responseJson);
      setStatus(await fetch(`/api/humanware/status?${query}`).then(responseJson));
      setMessage({ type: 'success', text: '保存成功' });
    } catch (error) {
      setMessage({ type: 'error', text: error instanceof Error ? error.message : '保存失败，请重试' });
    } finally { setSaving(false); }
  };

  const generateFromProfiles = async () => {
    setGenerating(true);
    setMessage(null);
    try {
      const result = await fetch('/api/humanware/generate-voice-file', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow_id: workflowId, workspace: workspaceId }),
      }).then(responseJson);
      const [nextStatus, document] = await Promise.all([
        fetch(`/api/humanware/status?${query}`).then(responseJson),
        fetch(`/api/humanware/voice-file?${query}`).then(responseJson),
      ]);
      setStatus(nextStatus);
      setContent(document.content || '');
      setMessage({ type: 'success', text: result.message });
    } catch (error) {
      setMessage({ type: 'error', text: error instanceof Error ? error.message : '生成失败，请重试' });
    } finally { setGenerating(false); }
  };

  const cardClass = 'rounded-2xl border border-border bg-card shadow-sm';
  const buttonClass = 'inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition-colors';
  const primaryButtonClass = `${buttonClass} bg-primary text-primary-foreground hover:bg-primary/90`;
  const secondaryButtonClass = `${buttonClass} border border-border bg-background hover:bg-accent`;

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
        <span className="ml-2 text-sm text-muted-foreground">加载中...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 消息提示 */}
      {message && (
        <div className={`rounded-xl border p-4 ${
          message.type === 'success' ? 'border-green-500/20 bg-green-500/10 text-green-600' :
          message.type === 'error' ? 'border-red-500/20 bg-red-500/10 text-red-600' :
          'border-blue-500/20 bg-blue-500/10 text-blue-600'
        }`}>
          <div className="flex items-center gap-2">
            {message.type === 'success' ? <CheckCircle className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
            <span className="text-sm">{message.text}</span>
          </div>
        </div>
      )}

      {/* 状态卡片 */}
      <section className={`${cardClass} p-5`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Users className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">角色声音锚点</h2>
          </div>
          <div className="flex gap-2">
            <button
              onClick={generateFromProfiles}
              disabled={saving || generating || !status?.profiles_file_exists || status?.voice_file_exists || !!content.trim()}
              className={secondaryButtonClass}
            >
              <Wand2 className="h-4 w-4" />
              {generating ? '创建中...' : '创建待填写模板'}
            </button>
            <button
              onClick={saveContent}
              disabled={saving || generating || !status}
              className={primaryButtonClass}
            >
              <Save className="h-4 w-4" />
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </div>

        <div className="mt-4 flex gap-6 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4" />
            <span>状态: {status?.voice_file_exists ? '已创建' : '未创建'}</span>
          </div>
          {status?.voice_file_exists && (
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4" />
              <span>角色数量: {status.character_count}</span>
            </div>
          )}
        </div>

        <p className="mt-3 text-sm leading-6 text-muted-foreground">
          角色声音锚点定义每个角色的独特说话方式、认知模式和情绪表达，确保AI生成的对话和内心独白具有人味。
        </p>
      </section>

      {/* 编辑器 */}
      <section className={`${cardClass} p-5`}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold">编辑内容</h3>
          <div className="flex gap-2 text-xs text-muted-foreground">
            <span>{content.length} 字符</span>
            <span>·</span>
            <span>{content.split('\n').length} 行</span>
          </div>
        </div>

        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          className="w-full rounded-xl border border-border bg-background p-4 font-mono text-sm leading-6 focus:outline-none focus:ring-2 focus:ring-primary/20"
          rows={30}
          placeholder="# 角色声音锚点&#10;&#10;## 角色名&#10;&#10;### 核心声音定位&#10;- **表达方式**: ...&#10;&#10;### 句法指纹&#10;- **平均句长**: ...&#10;&#10;..."
        />

        <div className="mt-4 text-xs text-muted-foreground">
          <p>提示：</p>
          <ul className="mt-2 ml-4 list-disc space-y-1">
            <li>为每个主要角色定义独特的说话方式</li>
            <li>包含句法指纹、口头禅、停顿模式、认知偏差等</li>
            <li>列出该角色绝不会使用的表达方式</li>
            <li>保存后，写作agent会自动遵守这些定义</li>
          </ul>
        </div>
      </section>

      {/* 使用说明 */}
      <section className={`${cardClass} p-5 text-sm leading-7`}>
        <h2 className="font-semibold">如何使用角色声音功能？</h2>
        <div className="mt-3 space-y-3 text-muted-foreground">
          <p>
            <strong>1. 首次创建：</strong>
            点击“创建待填写模板”，按角色档案中的二级标题生成空白条目，不调用模型、不推断人物声音，也不覆盖已有文件。AI 声音生成沿用角色创建工作流。
          </p>
          <p>
            <strong>2. 完善内容：</strong>
            编辑生成的模板，为每个角色补充认知偏差、情绪表达模式、禁止说的话等细节。
          </p>
          <p>
            <strong>3. 自动生效：</strong>
            保存后，后续写作任务会读取角色声音文件作为创作约束。请通过模拟读者报告检查正文是否落实这些约定。
          </p>
          <p>
            <strong>4. 持续迭代：</strong>
            根据生成的章节反馈，不断完善角色声音定义，提升人味质量。
          </p>
        </div>
      </section>
    </div>
  );
}
