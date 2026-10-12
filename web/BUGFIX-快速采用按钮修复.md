# Bug 修复：小说顾问快速采用和手动选择按钮无效

## 问题描述
在创作流程的第一步"小说顾问"中，点击"快速采用"和"手动选择"按钮时没有任何反应。

## 问题原因
在 `NovelWorkbenchPage.tsx` 中，`FlowView` 组件内部定义了一个空的 `openReference` 函数（第862-865行），这个空函数被传递给了 `AssistantPanel` 组件的 `onManualSelect` 回调。

真正负责页面跳转的 `openReference` 函数定义在父组件 `NovelWorkbenchContent` 中（第375行）：
```typescript
const openReference = (advisor = false) => {
  setReferenceStage(advisor ? "style-compatibility-advisor" : "adopt-reference"); 
  setView("reference");
};
```

但由于 `FlowView` 内部的同名空函数遮蔽了父组件的函数，导致点击按钮时无法触发页面跳转。

## 修复方案

### 1. 修改 FlowView 函数签名
在 `FlowView` 的 props 中添加 `onOpenReference` 参数，并移除内部的空 `openReference` 函数：

```typescript
function FlowView({ 
  // ... 其他 props
  onOpenReference 
}: { 
  // ... 其他类型
  onOpenReference?: (advisor?: boolean) => void 
}) {
  // 移除了内部的空 openReference 函数
```

### 2. 修改 AssistantPanel 的 onManualSelect 回调
将空函数调用改为使用从父组件传递的 `onOpenReference`：

```typescript
<AssistantPanel 
  // ... 其他 props
  onManualSelect={onOpenReference ? () => onOpenReference() : undefined} 
/>
```

### 3. 在 FlowView 调用处传递 openReference
在两处调用 `FlowView` 的地方添加 `onOpenReference={openReference}` prop：

- `view === "reference"` 时的 FlowView
- `view === "flow"` 时的 FlowView

## 影响范围
- 文件：`DeterminFlow/web/src/pages/NovelWorkbenchPage.tsx`
- 受影响功能：小说顾问的"快速采用"和"手动选择"按钮

## 测试建议
1. 进入小说工作台，开始新作品
2. 在"小说顾问"步骤与 AI 讨论故事方向
3. 点击"快速采用推荐写法"按钮，验证能否弹出对话框
4. 在对话框中点击"手动选择"按钮，验证能否跳转到"本书参考写法"页面
5. 点击"确认快速采用"按钮，验证能否成功引用写法库并跳转

## 修复日期
2026-10-12
