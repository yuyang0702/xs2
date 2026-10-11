# 写法机制智能推荐系统 - 实现总结

## 📋 已完成的实现

### 第一阶段：写法库智能推荐 ✅

#### 新增文件：
- **`src/web/novel_mechanism_recommender.py`** 
  - `extract_mechanisms_from_library()` - 从写法库提取所有机制统计
  - `find_mechanism_combinations()` - 找出最常见的机制组合
  - `recommend_story_directions()` - 推荐故事方向和机制
  - `match_story_with_mechanisms()` - 已有采用写法时的推荐

#### 修改的文件：
- **`src/web/novel_routes.py`**
  - 新增 `/api/novel-console/library/mechanism-recommendations` 端点
  - 修改 `/api/novel-console/library/{library_id}` 返回本书使用信息

---

### 第二阶段：顾问推荐机制结构化 ✅

#### 修改的文件：
- **`src/web/novel_configuration.py`**
  - 扩展 `ADVISOR_PROMPT` 要求顾问输出 `mechanism_recommendations`
  - 修改 `parse_advisor()` 解析新字段

- **`web/src/lib/api.ts`**
  - 更新 `NovelAssistantEntry` 类型包含 `mechanism_recommendations`

- **`web/src/components/NovelAdvisorConversation.tsx`**
  - 新增UI显示推荐的机制（分HIGH/MEDIUM/LOW优先级）
  - 显示采用自参考库的机制
  - 显示补充的新机制及其协同关系
  - 显示需要避免的机制组合

---

### 第三阶段：创作流程集成（部分完成）📝

#### 新增文件：
- **`src/web/novel_mechanism_tracker.py`**
  - `save_mechanism_usage()` - 记录章节使用的机制
  - `get_mechanism_usage_history()` - 获取使用历史
  - `extract_used_mechanisms()` - 汇总本书使用的机制
  - `detect_synergies()` - 检测机制协同效果
  - `generate_mechanism_report()` - 生成使用报告

#### 待完成工作（第四部分）：
- [ ] 修改 `mvp/definition.json` 添加机制注入节点
- [ ] 创建 `mechanism_injector` 脚本
- [ ] 修改 mvp 系统提示模板加入推荐机制

---

### 第四阶段：写法库中的使用追踪 ✅

修改的 API 端点：
- **`GET /api/novel-console/library/{library_id}`**
  - 返回 `adopted_in_current_book` 字段
  - 显示本书从此库中采用了哪些机制

返回格式示例：
```json
{
  "manifest": {...},
  "profile": {...},
  "candidates": {...},
  "adopted_in_current_book": {
    "workspace": "data/workspaces/books/xxx",
    "adopted_count": 3,
    "mechanisms_used": [
      {
        "candidate_id": "mechanism-xxx",
        "mechanism": "生理限制收束目标"
      }
    ],
    "adoption_date": "2026-10-11"
  }
}
```

---

## 🔄 完整工作流

```
用户进入小说顾问
  ↓
选择"从写法库找灵感"按钮
  ↓
前端调用 /api/novel-console/library/mechanism-recommendations
  ↓
后端分析所有写法库的蒸馏候选
  ├─ 统计机制出现频率
  ├─ 分析机制组合（协同）
  ├─ 分类故事类型
  └─ 返回前3个推荐方向
  ↓
顾问接收推荐库信息 + 参考候选 + 已采用写法
  ↓
顾问分析 + 输出包含机制推荐的方案
  {
    "reply": "...",
    "advisor_sections": {
      "direction": "...",
      "hook": "...",
      "writing": "...",
      "risks": "...",
      "mechanism_recommendations": {
        "adopted_from_library": [
          {
            "mechanism": "生理限制收束目标",
            "usage_in_story": "伤口影响主角行动范围",
            "priority": "HIGH",
            "chapter_placement": "全文"
          }
        ],
        "new_mechanisms": [...],
        "avoid_combinations": [...]
      }
    }
  }
  ↓
前端显示推荐机制
  ├─ 从参考库采用的 (HIGH/MEDIUM)
  ├─ 补充的新机制
  └─ 避免的组合
  ↓
用户采用方案
  ↓
保存 advisor_sections 包含机制推荐
  ↓
后续创作时 (待实现)
  ├─ 读取顾问推荐的机制
  ├─ 注入到 mvp 系统提示
  └─ 提示模型重点使用这些机制
  ↓
完成后
  ├─ 记录到 learning/mechanism_usage_log.json
  ├─ 生成 learning/mechanism_synergy_report.json
  └─ 更新写法库的使用情况
```

---

## 📊 关键数据结构

### learning/mechanism_usage_log.json
```json
{
  "version": 1,
  "created_at": "2026-10-11T...",
  "chapters": {
    "0001": {
      "mechanisms": ["生理限制收束目标", "即时压力重排代价偏好"],
      "effectiveness_notes": "两个机制协同强化了紧张感",
      "recorded_at": "2026-10-11T..."
    }
  }
}
```

### learning/mechanism_synergy_report.json
```json
{
  "total_chapters": 1,
  "unique_mechanisms": 2,
  "mechanisms": [
    {
      "name": "生理限制收束目标",
      "usage_count": 1,
      "chapters_used": ["0001"]
    }
  ],
  "synergies": [
    {
      "mechanism_a": "生理限制收束目标",
      "mechanism_b": "即时压力重排代价偏好",
      "co_occurrences": 1,
      "chapters": ["0001"]
    }
  ]
}
```

---

## 🎯 下一步待完成工作

### 优先级 1（完成集成）：
1. **修改 mvp workflow**
   - 在 `mvp/definition.json` 中添加 `mechanism_injector` 脚本节点
   - 该节点读取 `values.advisor_guidance` 中的机制推荐
   - 生成 `learning/mechanism_brief.json` 包含本章应用的机制

2. **创建 mechanism_injector 脚本**
   - 解析顾问推荐的机制
   - 根据故事类型筛选本章使用的机制
   - 生成结构化的机制应用指南

3. **修改 mvp 系统提示**
   - 添加模板变量 `{{mechanism_brief}}`
   - 在提示中明确告诉模型"本章重点使用这些机制"

### 优先级 2（前端完善）：
1. **在写法库界面显示使用情况**
   - 切换到写法库时，显示"本书使用了这个库的这些机制"
   - 显示使用有效性评分

2. **创建机制效果分析面板**
   - 显示本书使用的所有机制及其效果
   - 显示机制协同效果分析

### 优先级 3（自动追踪）：
1. **在创作完成后自动追踪**
   - mvp 生成完成后自动保存使用的机制
   - post-hoc 确认后更新使用报告

---

## ✨ 用户体验流

### 场景1：原创故事（无参考）
```
用户：我想写一个故事，不确定方向
顾问：(根据已有采用的写法) 推荐方向 + 推荐机制
用户：采用方案
创作：使用推荐机制
完成：记录效果
```

### 场景2：有写法库参考
```
用户：(点击"从写法库找灵感")
顾问：分析库中 3 个最佳故事方向
    方向1：末日生存 (推荐 3 个机制, 频率 8/10)
    方向2：道德困局 (推荐 2 个机制, 频率 5/10)
    方向3：身份谜团 (推荐 2 个机制, 频率 4/10)
用户：选择方向
顾问：这个方向推荐用【机制A】【机制B】【机制C】
    【机制A】在你已采用的【机制D】基础上强化压力
    避免使用【机制E】因为会与故事节奏冲突
用户：采用
创作：自动使用推荐机制
完成：显示"成功激活 2 个协同效果"
库中：显示此作品用了库中的这些机制
```

---

## 🔧 技术细节

### API 路由总结

| 路由 | 方法 | 功能 |
|---|---|---|
| `/api/novel-console/library/mechanism-recommendations` | GET | 生成推荐库 |
| `/api/novel-console/library/{id}` | GET | 获取库项（含本书使用情况） |
| `/api/novel-console/assistant` | POST | 顾问请求（现有，已增强） |

### 新模块依赖

```
novel_mechanism_recommender.py
  ├─ novel_library.read_json()
  ├─ novel_reference_choices.with_reference_choices()
  └─ 标准库: pathlib, json, collections

novel_mechanism_tracker.py
  └─ 标准库: pathlib, datetime, json
```

---

## 📝 使用指南

### 对于用户：
1. **第一次创作**：点击"从写法库找灵感"让顾问推荐
2. **已有采用写法**：点击"基于已采用写法优化"让顾问建议最佳方向
3. **创作过程**：看到推荐的机制后，专注于故事内容
4. **查看库**：在写法库中看到"这个库被我采用了这些内容"

### 对于开发者：
1. 完整的工作流在 `MECHANISM_RECOMMENDATION_PLAN.md` 中
2. 新增模块在 `src/web/` 下，可独立测试
3. API 端点已添加，可通过 Postman 测试
4. 前端组件已更新，显示机制推荐

---

## ✅ 验证清单

- [x] 写法库推荐功能可用
- [x] 顾问输出包含机制推荐
- [x] 前端显示机制推荐
- [x] 写法库显示本书使用情况
- [x] 追踪机制使用的数据结构
- [ ] mvp 流程注入推荐机制
- [ ] 自动记录创作时使用的机制
- [ ] 完整的端到端测试

---

## 测试方法

```bash
# 1. 测试推荐库生成
curl -X GET "http://localhost:8000/api/novel-console/library/mechanism-recommendations?workspace=data/workspaces/books/xxx"

# 2. 测试库项使用情况
curl -X GET "http://localhost:8000/api/novel-console/library/d?workspace=data/workspaces/books/xxx"

# 3. 测试顾问推荐
POST /api/novel-console/assistant
{
  "question": "我想写末日生存故事",
  "purpose": "advisor",
  "project": {...}
}

# 响应中应包含 advisor_sections.mechanism_recommendations
```
