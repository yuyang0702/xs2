# 章节生产管线错误修复

## 问题描述

用户在执行章节生产管线时遇到报错，导致无法启动章节生产流程。

## 问题根因

当点击章节生产管线按钮时，后端会调用 `ensure_idle()` 函数检查是否有任务正在运行。如果检测到有未完成的任务（状态为 `pending`、`running`、`preparing`、`pre_running`、`retry_waiting` 或 `resume_pending`），就会抛出错误：

```
"本书仍有创作或评估任务正在处理，请完成后再规划或启动返修。"
```

**问题出现在以下调用链：**

1. 前端调用 `openChapterProduction(chapter, action)`
2. 前端调用后端 API `getNovelChapterContext()`
3. 后端 `chapter_context()` 函数调用 `ensure_idle()`（`novel_chapters.py:59`）
4. `ensure_idle()` 检测到有运行中的任务，抛出 `ValueError`（`novel_repair.py:13-18`）

类似地，在创作流程页面点击"开始"按钮时：
1. 前端调用 `launch()` 函数
2. 前端调用后端 API `createTask()`
3. 如果有任务冲突，也会抛出相同错误

## 问题分析

原有的前端错误处理（`NovelWorkbenchPage.tsx`）虽然捕获了错误，但：
1. 错误提示不够清晰，用户不知道是什么任务在运行
2. 没有提供解决方案或下一步操作指引
3. 错误信息直接显示后端原始错误，不够友好

## 修复内容

### 1. 改进 `openChapterProduction` 的错误处理（第461-473行）

**修改前：**
```typescript
} catch (failure) {
  setPageFeedback(`章节操作未开始：${failure instanceof Error ? failure.message : String(failure)}。原有正文和进度保留。`);
  setProject(current => ({...current, autoNext:false, autoScope:"manual", autoLaunchStage:""}));
}
```

**修改后：**
```typescript
} catch (failure) {
  const errorMsg = failure instanceof Error ? failure.message : String(failure);
  const isBusy = errorMsg.includes('仍有创作或评估任务正在处理') || errorMsg.includes('正在处理');

  if (isBusy) {
    setPageFeedback(`⚠️ 章节操作暂时无法启动：当前有其他任务正在执行中。请等待任务完成后再试，或在创作流程页面查看任务状态。原有正文和进度保留。`);
  } else {
    setPageFeedback(`章节操作未开始：${errorMsg}。原有正文和进度保留。`);
  }

  setProject(current => ({...current, autoNext:false, autoScope:"manual", autoLaunchStage:""}));
}
```

### 2. 改进 `launch` 函数的错误处理（第1029行）

**修改前：**
```typescript
} catch (failure) {
  if (currentStage.id === "outline") outlineConfirmed.current = false;
  setError(failure instanceof Error ? failure.message : "启动失败");
  setActionFeedback("启动没有完成，请查看下方提示后重试。");
  setProject(current => ({
    ...current,
    autoNext: false,
    autoScope: "manual",
    autoLaunchStage: "",
    autoPauseReason: current.autoNext || current.autoLaunchStage
      ? "自动启动失败，请处理错误后重新启用。"
      : ""
  }));
}
```

**修改后：**
```typescript
} catch (failure) {
  if (currentStage.id === "outline") outlineConfirmed.current = false;
  const errorMsg = failure instanceof Error ? failure.message : "启动失败";
  const isBusy = errorMsg.includes('仍有创作或评估任务正在处理') || errorMsg.includes('正在处理');
  
  setError(isBusy
    ? "⚠️ 当前有其他任务正在运行，请等待完成后再启动新任务。可以刷新工作流查看任务状态。"
    : errorMsg);
  setActionFeedback(isBusy
    ? "启动被阻止：有任务正在执行。等待完成或停止该任务后重试。"
    : "启动没有完成，请查看下方提示后重试。");
  setProject(current => ({
    ...current,
    autoNext: false,
    autoScope: "manual",
    autoLaunchStage: "",
    autoPauseReason: current.autoNext || current.autoLaunchStage
      ? (isBusy ? "有其他任务正在运行，自动流程已暂停。" : "自动启动失败，请处理错误后重新启用。")
      : ""
  }));
}
```

## 改进效果

1. **更清晰的错误提示**：明确告知用户是"有其他任务正在运行"导致的冲突
2. **可操作的指引**：提示用户"等待任务完成"或"查看任务状态"
3. **友好的用户体验**：使用警告图标（⚠️）突出显示冲突状态
4. **自动流程暂停**：当检测到任务冲突时，自动暂停自动流程并给出清晰的原因

## 用户操作建议

当遇到此错误时，用户应该：

1. **等待当前任务完成**
   - 在创作流程页面查看任务执行状态
   - 等待"正在执行"状态变为"已完成"

2. **检查任务状态**
   - 点击页面右上角的"刷新工作流"按钮
   - 查看是否有卡住的任务

3. **如果任务卡住**
   - 联系管理员检查后端工作流服务
   - 检查任务日志确认是否有错误

## 后端逻辑说明

后端的 `ensure_idle()` 检查逻辑（`novel_repair.py:13-18`）：

```python
def ensure_idle(root: Path, workflows_dir: Path) -> None:
    for stage in ('build', 'character', 'story-plan', 'outline', 'mvp', 'polish', 'reader-sim', 'post-hoc', 'export'):
        for file in (workflows_dir / f'xs2-novel-flywheel-{stage}/tasks').glob('*.json'):
            task = json.loads(file.read_text(encoding='utf-8'))
            if task.get('status') in {'pending', 'running', 'preparing', 'pre_running', 'retry_waiting', 'resume_pending'} \
               and task.get('workspace_override') \
               and Path(task['workspace_override']).resolve() == root.resolve():
                raise ValueError('本书仍有创作或评估任务正在处理，请完成后再规划或启动返修。')
```

这个检查是**有意为之的安全机制**，防止：
- 同一本书同时运行多个冲突的任务
- 并发修改导致数据不一致
- 章节重新生成时覆盖正在生产的内容

## 测试验证

修复后的行为：

1. **正常情况**：没有任务运行时，章节生产正常启动
2. **任务冲突**：有任务运行时，显示友好的错误提示
3. **自动流程**：检测到冲突时自动暂停，并给出明确原因

## 相关文件

- **前端**: `web/src/pages/NovelWorkbenchPage.tsx`（第461-473行，第1029行）
- **后端**: `src/web/novel_repair.py`（第13-18行）
- **后端**: `src/web/novel_chapters.py`（第57-59行）
