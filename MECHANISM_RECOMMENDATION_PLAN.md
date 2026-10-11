# 写法机制智能推荐系统 - 完整方案分析

## 一、现状分析

### 1.1 当前数据流

```
用户进入小说顾问
  ↓
前端显示三种模式：
  ├─ "我已有想法" → 空白问题
  ├─ "从写法库找灵感" → 自动生成提示词（当 librarySize > 0）
  └─ "基于已采用写法优化" → 自动生成提示词（当 adoptedCount > 0）
  ↓
顾问收到请求，上下文包含：
  ├─ premise（故事创意）
  ├─ genre（题材）
  ├─ narrative_pov（视角）
  ├─ learning_context_file → learning/active_context.md（已确认写法）
  ├─ candidates_file → learning/candidates.json（当前作品的蒸馏候选）
  └─ recommendations_file → learning/recommendations.json（**尚不存在**）
  ↓
顾问输出 advisor_sections：
  ├─ direction（故事方向）
  ├─ hook（核心看点）
  ├─ writing（写法建议）
  ├─ risks（适配风险）
  └─ **机制推荐**（**尚未明确结构化**）
  ↓
用户采用方案
  ↓
保存到 values.advisor_guidance（纯文本）
  └─ **没有结构化的机制关联**
  ↓
后续创作流程（mvp）
  ├─ 读取 learning/active_context.md（用户已确认）
  ├─ 读取 meta/style_profile.md（本书风格）
  └─ **不知道顾问推荐了哪些机制**
```

### 1.2 当前的缺口

| 问题 | 现状 | 需求 |
|---|---|---|
| 写法库推荐 | 无 | 第一步就根据写法库推荐故事方向 |
| 故事-写法匹配 | 无结构化记录 | 顾问推荐→写法关联清晰 |
| 机制追踪 | 无 | 后续创作时知道"用了哪些"机制 |
| 机制协同 | 无分析 | 知道哪些机制组合效果好 |
| 库内容使用 | 写法库独立 | 写法库显示"被哪些作品采用" |

---

## 二、系统需求分解

### 2.1 **第一步：小说顾问中的推荐**

**现有逻辑：** 前端检查 `librarySize > 0`，显示"从写法库找灵感"按钮

**需要的新逻辑：**

```
按钮 1: "从写法库找灵感"
  ├─ 读取：/data/writing-library/*/candidates.json
  ├─ 分析：所有现有蒸馏写法中的机制
  ├─ 逻辑：统计机制频率、分类、适用题材
  └─ 输出：推荐清单（JSON）→ learning/recommendations.json
      {
        "story_recommendations": [
          {
            "story_type": "末日生存",
            "core_themes": ["生理限制", "道德困境"],
            "recommended_mechanisms": [
              {"id": "mechanism-1", "name": "生理限制收束目标", "frequency": 5, "reason": "在末日题材中高频出现"},
              {"id": "mechanism-2", "name": "即时压力重排代价", "frequency": 4, "reason": "强化决策压力"}
            ],
            "synergy": [
              {"a": "mechanism-1", "b": "mechanism-2", "effect": "强化紧张感和道德困局"}
            ],
            "similarity_score": 0.85,
            "source_works": ["晚钟飞生d"]
          }
        ]
      }

按钮 2: "基于已采用写法优化"
  ├─ 读取：learning/active_context.md（已确认的机制）
  ├─ 分析：这些机制最适合的故事类型
  ├─ 逻辑：从写法库找"包含相同机制"的作品
  └─ 输出：最佳故事方向 + 可补充的新机制
```

### 2.2 **第二步：顾问的推荐结构化**

**现在的输出：**
```json
{
  "direction": "...",
  "hook": "...", 
  "writing": "...",
  "risks": "..."
}
```

**需要的新输出：**
```json
{
  "direction": "...",
  "hook": "...",
  "writing": "...",
  "risks": "...",
  "mechanism_recommendations": {
    "adopted_from_library": [
      {
        "mechanism_id": "mechanism-xxx",
        "name": "身份线索触发分层信息解锁",
        "usage_in_story": "开篇通过XXX设置认知缺口，当主角发现XXX时触发信息释放",
        "priority": "HIGH",
        "chapter_placement": "0001中段"
      }
    ],
    "new_mechanisms": [
      {
        "mechanism_id": "mechanism-yyy",
        "name": "生理限制收束目标",
        "reason": "写法库中这个题材频繁使用，能强化你的故事压力",
        "synergy_with": ["mechanism-xxx"],
        "priority": "MEDIUM"
      }
    ],
    "avoid_combinations": [
      {
        "a": "xxx",
        "b": "yyy",
        "reason": "不适合短篇"
      }
    ]
  }
}
```

### 2.3 **第三步：创作流程中的自动集成**

**现在的 mvp 流程：**
- 读取 `learning/active_context.md` → 已确认的全部机制
- 读取 `meta/style_profile.md` → 风格基线

**需要的新流程：**
```
mvp 创作前
  ↓
新脚本：mechanism_injector
  ├─ 输入：本章号、故事类型
  ├─ 读取：
  │   ├─ values.advisor_guidance（顾问的建议）
  │   ├─ 解析其中的 mechanism_recommendations
  │   └─ 筛选本章应该重点使用的机制
  ├─ 输出：mechanism_brief.json
  │   {
  │     "chapter": "0001",
  │     "primary_mechanisms": [...],
  │     "supporting_mechanisms": [...],
  │     "implementation_hints": {...}
  │   }
  └─ 注入到系统提示
      "==== 本章推荐关键机制 ====" + mechanism_brief.json
```

### 2.4 **第四步：追踪与显示**

**新增结构：**
```
learning/
├─ active_context.md          （已确认的全部机制）
├─ advisor_recommendations.json （最新顾问推荐）
├─ mechanism_usage_log.json    （本书使用记录）
│   {
│     "chapters": {
│       "0001": {
│         "mechanisms_used": [
│           {"id": "xxx", "name": "...", "placement": "开篇", "effectiveness": 0.85}
│         ],
│         "synergies_activated": ["xxx-yyy"],
│         "timestamp": "2026-10-07T..."
│       }
│     }
│   }
└─ mechanism_synergy_report.json （协同效果分析）
    {
      "total_mechanisms": 3,
      "active_synergies": [
        {
          "a": "生理限制",
          "b": "即时压力",
          "chapters": ["0001"],
          "combined_effectiveness": 0.92,
          "notes": "强化了道德困局的紧张感"
        }
      ]
    }
```

**写法库中显示：**
```
/library/d (晚钟飞生d)
  └─ usage_across_works: [
       {
         "work_id": "short-1791276162734-23rfm",
         "work_title": "末日丧尸短篇",
         "mechanisms_adopted": [
           "身份线索触发分层信息解锁",
           "生理限制收束目标",
           "即时压力重排代价偏好"
         ],
         "synergies_detected": [
           "生理限制 + 即时压力 → 强化紧张感"
         ],
         "adoption_date": "2026-10-07"
       }
     ]
```

---

## 三、具体实现路径

### 3.1 优先级排序

**优先级 1（核心）：** 
- [ ] 生成 `recommendations.json`（从写法库统计）
- [ ] 修改顾问系统提示，明确要求机制推荐
- [ ] 修改顾问返回格式，包含 `mechanism_recommendations`

**优先级 2（集成）：**
- [ ] 创建 `mechanism_injector` 脚本
- [ ] 修改 mvp definition.json，添加注入步骤
- [ ] 创建 `mechanism_usage_log.json` 记录格式

**优先级 3（可视化）：**
- [ ] 前端显示本章推荐机制
- [ ] 写法库中显示"被采用情况"
- [ ] 创建协同效果分析报告

### 3.2 数据流图

```
用户选择"从写法库找灵感"
  ↓
前端调用 /api/novel-console/library
  ↓
后端生成 learning/recommendations.json
  ├─ 统计 writing-library/*/ 中的 candidates.json
  ├─ 分类机制、计算频率
  ├─ 推荐适合的故事方向
  └─ 推荐机制组合
  ↓
顾问收到:
  ├─ recommendations_file（推荐库）
  ├─ candidates_file（当前作品候选）
  └─ premise 为空
  ↓
顾问分析 + 输出
  ├─ direction（推荐的故事）
  ├─ mechanism_recommendations（推荐的机制）
  └─ 说明理由
  ↓
用户采用
  ↓
保存 advisor_sections 包含 mechanism_recommendations
  ↓
后续创作
  ├─ mechanism_injector 读取 mechanism_recommendations
  ├─ 生成 mechanism_brief.json
  ├─ 注入到 mvp 系统提示
  └─ 创作时重点使用推荐机制
  ↓
完成后
  ├─ 记录到 mechanism_usage_log.json
  ├─ 更新 mechanism_synergy_report.json
  └─ 更新写法库中的 usage_across_works
```

---

## 四、代码实现要点

### 4.1 需要新建的文件

```
src/web/
├─ novel_mechanism_analyzer.py     # 从写法库生成推荐
├─ novel_mechanism_recommender.py  # 故事-机制匹配逻辑
└─ novel_mechanism_tracker.py      # 使用追踪

src/core/defaults/skills/
└─ mechanism-recommendation/       # 可作为 skill
    ├─ analyze_library.py
    ├─ generate_recommendations.py
    └─ track_synergies.py
```

### 4.2 需要修改的文件

```
src/web/novel_assistant.py
  ├─ 增加 mechanism_recommendations 到 context
  └─ 保存时记录到日志

src/web/novel_configuration.py
  ├─ 修改 ADVISOR_PROMPT 的机制推荐要求
  └─ 修改 parse_advisor 接收新格式

src/web/novel_routes.py
  ├─ 新增 GET /api/novel-console/mechanism-recommendations
  └─ 修改 GET /library/{library_id} 返回 usage_across_works

web/src/components/NovelAdvisorConversation.tsx
  ├─ 显示推荐的机制
  └─ 让用户可见如何选择应用

data/plugins/checkouts/xs2-novel-flywheel/.../workflows/
  ├─ novel-advisor/definition.json
  │   └─ 支持 recommendations_file 变量
  └─ mvp/definition.json
      └─ 添加 mechanism_injector 脚本节点
```

---

## 五、关键算法

### 5.1 "推荐故事方向"算法

```python
def recommend_story_directions(library_items, count=3):
    """
    从写法库中推荐 count 个故事方向
    """
    mechanisms_frequency = {}
    story_combinations = {}
    
    for item in library_items:
        candidates = parse_candidates(item.candidates_json)
        for candidate in candidates:
            mechanism = candidate['mechanism']
            mechanisms_frequency[mechanism] += 1
        
        # 记录这个作品的机制组合
        combo = tuple(sorted(set(c['mechanism'] for c in candidates)))
        if combo not in story_combinations:
            story_combinations[combo] = {
                'count': 0, 'works': [], 'genre': item.manifest['genres']
            }
        story_combinations[combo]['count'] += 1
        story_combinations[combo]['works'].append(item.manifest['name'])
    
    # 按频率排序，推荐最常见的组合
    top_combos = sorted(
        story_combinations.items(),
        key=lambda x: x[1]['count'],
        reverse=True
    )[:count]
    
    return [
        {
            'story_type': infer_story_type(combo[0], combo[1]['genre']),
            'mechanisms': combo[0],
            'frequency': combo[1]['count'],
            'source_works': combo[1]['works'],
            'synergy_score': calculate_synergy(combo[0])
        }
        for combo in top_combos
    ]
```

### 5.2 "匹配已采用写法"算法

```python
def find_similar_stories(adopted_mechanisms, library_items):
    """
    找到包含相同机制的故事，推荐补充新机制
    """
    adopted_set = set(adopted_mechanisms)
    recommendations = []
    
    for item in library_items:
        candidates = parse_candidates(item.candidates_json)
        item_mechanisms = set(c['mechanism'] for c in candidates)
        
        # 计算相似度
        intersection = adopted_set & item_mechanisms
        union = adopted_set | item_mechanisms
        similarity = len(intersection) / len(union)
        
        if similarity > 0.5:  # 阈值
            complementary = item_mechanisms - adopted_set
            recommendations.append({
                'source_work': item.manifest['name'],
                'similarity': similarity,
                'shared_mechanisms': intersection,
                'complementary_mechanisms': complementary
            })
    
    return sorted(recommendations, key=lambda x: x['similarity'], reverse=True)
```

### 5.3 "检测机制协同"算法

```python
def detect_synergies(mechanisms_list, library_data):
    """
    从写法库中提取"这些机制一起用的效果如何"的记录
    """
    synergies = []
    
    for pair in combinations(mechanisms_list, 2):
        co_occurrence = 0
        co_works = []
        
        for item in library_data:
            candidates = parse_candidates(item.candidates_json)
            mech_set = set(c['mechanism'] for c in candidates)
            if all(m in mech_set for m in pair):
                co_occurrence += 1
                co_works.append(item.manifest['name'])
        
        if co_occurrence > 0:
            synergies.append({
                'mechanism_a': pair[0],
                'mechanism_b': pair[1],
                'co_occurrence': co_occurrence,
                'works': co_works,
                'recommendation': infer_synergy_effect(pair[0], pair[1], co_works)
            })
    
    return synergies
```

---

## 六、前端界面变化

### 6.1 小说顾问界面

现在：
```
[我已有想法] [从写法库找灵感] [基于已采用写法优化]
```

改为：
```
[我已有想法]
[从写法库找灵感]
  └─ 显示：推荐 3 个故事方向 + 各自的推荐机制（分HIGH/MEDIUM）
[基于已采用写法优化]  
  └─ 显示：最佳匹配 + 可补充的新机制
```

### 6.2 采用方案后

显示：
```
推荐的故事方向：末日生存
核心看点：道德困局 + 紧张压力
推荐的写法机制：
  ├─ [HIGH] 生理限制收束目标
  ├─ [HIGH] 即时压力重排代价偏好
  └─ [MEDIUM] 认知冲突
```

### 6.3 创作时（mvp 开始前）

显示：
```
本章推荐关键机制：
├─ 主要 (HIGH): 生理限制收束目标、即时压力重排代价偏好
├─ 辅助 (MEDIUM): 认知冲突
└─ 协同提示：这两个机制结合会强化道德困局的紧张感
```

### 6.4 完成后（完成页面）

显示：
```
本章使用情况：
├─ 实际使用机制: [3 个]
├─ 协同激活: 生理限制 ↔ 即时压力 (效果: 0.92)
└─ 效果评分：与写法库中相似作品对比...
```

---

## 七、集成检查清单

- [ ] 是否能从写法库正确解析 `candidates.json`
- [ ] 是否能生成有意义的 `recommendations.json`
- [ ] 顾问是否理解新的机制推荐格式
- [ ] 是否正确记录到 `mechanism_usage_log.json`
- [ ] 创作流程是否正确读取并应用推荐
- [ ] 写法库是否正确显示"被采用"的记录
- [ ] 前端是否能清晰展示所有推荐
- [ ] 是否有后续章节推荐机制的逻辑

---

## 总结

**核心改进：** 从"用户自主选择故事→顾问被动分析"转变为"顾问主动推荐故事→自动关联最佳写法→创作自动应用→持续追踪效果"

**三个关键创新点：**
1. **智能推荐库** - 根据写法库统计，推荐最佳故事方向
2. **机制关联追踪** - 故事和机制的对应关系明确记录
3. **创作流程集成** - 推荐的机制自动注入到创作提示中
