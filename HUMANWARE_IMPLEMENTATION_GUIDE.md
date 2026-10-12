# Humanware Engine 完整实现指南

**目标**：让 AI 生成的小说内容具有"人味"——不像 AI，而像有真实困境和独特声音的人。

**实现日期**：2026-10-12  
**版本**：1.0  
**作者**：xs2-humanware-team

---

## 📋 快速概览

### 核心系统（8 层）

```
1. 人物声音库       → 每个角色的独特表达方式
2. 情感触发点系统   → 细粒度的情感表现机会
3. 感受库           → 情感表现模式（替代技巧库）
4. 人物轨迹库       → 动态的心理状态跟踪
5. 双轮生成流程     → 粗稿 + 人物化优化
6. 变异策略         → 避免同类场景重复
7. 情感一致性检测   → 真实性审核
8. 工作流集成       → 与现有系统无缝衔接
```

### 文件结构

```
DeterminFlow/data/plugins/checkouts/xs2-novel-flywheel/.../
resources/script-library/xs2/humanware_engine/
├── __init__.py                          # 包初始化
├── character_voice_library.py           # 人物声音库
├── emotional_trigger_system.py          # 情感触发点
├── emotional_expression_library.py      # 感受库
├── character_trajectory.py              # 人物轨迹库
├── authenticity_checker.py              # 真实性检测
├── voice_injection_engine.py            # 声音注入引擎
└── integration.py                       # 集成接口

resources/prompts/
└── humanware_system_prompts.md          # LLM 提示词集合
```

---

## 🚀 集成步骤

### 第一步：初始化（参考资料蒸馏后）

**时机**：执行完 `reference-distillation` workflow 后

**步骤**：

1. **导入 Humanware 系统**
   ```python
   from xs2.humanware_engine.integration import HumanwareIntegration
   
   humanware = HumanwareIntegration(workspace_root=".")
   ```

2. **初始化感受库和人物声音库**
   ```python
   result = humanware.post_distillation_init_humanware(
       candidates_path="learning/candidates.json",
       character_profiles_path="meta/character_profiles.json"
   )
   # 输出示例：
   # {
   #   "characters_initialized": 5,
   #   "emotional_expressions_created": 0,  # 待 Agent 填充
   #   "status": "ready_for_novel_creation"
   # }
   ```

3. **执行 Agent：情感表现库初始化**
   - Agent：`agent_express_init`
   - 输入：候选库 + 参考小说文本
   - 输出：`learning/emotional_expressions.json`
   - 提示词：见 `humanware_system_prompts.md`

4. **执行 Agent：人物声音初始化**
   - Agent：`agent_voice_init`
   - 输入：人物档案 + 参考小说对话样本
   - 输出：`meta/character_voices.json`
   - 提示词：见 `humanware_system_prompts.md`

5. **保存**
   ```python
   humanware.save_all_libraries()
   ```

**输出文件**：
- `meta/character_voices.json` - 角色声音档案
- `meta/character_voices_variations.json` - 情境下的声音变异
- `learning/emotional_expressions.json` - 情感表现库
- `learning/character_emotional_profiles.json` - 角色情感特征

---

### 第二步：章节准备（每章创作前）

**时机**：生成单章指导后，执行 `mvp` workflow 前

**步骤**：

1. **注入情感触发点**
   ```python
   guide_json = {...}  # 从大纲导演产出
   chapter_num = 1
   
   enhanced_guide = humanware.inject_emotional_triggers_to_guide(
       guide_json,
       chapter_num
   )
   ```

2. **执行 Agent：触发点标注**
   - Agent：`agent_trigger_inject`
   - 输入：单章指导 + 情节摘要 + 角色状态
   - 输出：补充了情感触发点的单章指导
   - 提示词：见 `humanware_system_prompts.md`

3. **保存触发点**
   ```python
   humanware.trigger_library.save_library()
   ```

**输出文件**：
- `meta/emotional_triggers.json` - 所有章节的触发点
- `meta/emotional_rhythms.json` - 各章的情感节奏

---

### 第三步：智能上下文生成（script_smart_context 节点后）

**时机**：`mvp` workflow 中的 `script_smart_context` 生成后

**步骤**：

1. **增强 active_context**
   ```python
   with open("learning/active_context.md", 'r') as f:
       context = f.read()
   
   enhanced_context = humanware.enhance_active_context(
       context,
       chapter_num=1,
       main_characters=["主角", "配角A", "配角B"]
   )
   
   with open("learning/active_context_enhanced.md", 'w') as f:
       f.write(enhanced_context)
   ```

2. **文件说明**

   增强后的 `active_context_enhanced.md` 包含：
   - 原有的 8 条技巧推荐
   - 【人物声音指引】：每个角色该如何说话
   - 【人物心理状态】：当前的内心状态和脆弱点
   - 【情感触发点】：本章关键的情感表现时机

---

### 第四步：写手生成（agent_sw 后）

**时机**：`agent_sw` (写手) 完成粗稿生成后

**步骤**：

1. **应用人物声音注入**
   ```python
   draft_text = """{粗稿文本}"""
   
   refined_text = humanware.apply_voice_injection_to_draft(
       draft_text,
       chapter_num=1,
       main_characters=["主角", "配角A"]
   )
   
   # 保存中间结果
   with open("story/0001/content_draft_humanware.md", 'w') as f:
       f.write(refined_text)
   ```

2. **声音注入的作用**
   - 替换禁用词汇
   - 注入停顿和填充词
   - 应用角色特有的身体语言
   - 调整句式复杂度
   - 根据心理状态改变语调

---

### 第五步：意图审核（agent_si 前）

**时机**：`agent_si` (意图审核) 执行前或后

**步骤**：

1. **执行真实性检测**
   ```python
   with open("story/0001/content.md", 'r') as f:
       content = f.read()
   
   authenticity_result = humanware.check_authenticity(
       content,
       chapter_num=1,
       main_characters=["主角", "配角A"],
       main_character="主角"
   )
   
   # 输出：
   # {
   #   "report": {...},              # 详细报告
   #   "markdown": "...",            # Markdown 版本
   #   "pass": true/false            # 是否通过
   # }
   ```

2. **检测的维度**
   - ✅ 陈词滥调识别与削弱
   - ✅ 情感强度与行为匹配
   - ✅ 人物工具化检测
   - ✅ 情绪突变是否有因果支撑
   - ✅ 细节是否支撑情感
   - ✅ 真实性标记计数

3. **报告示例**

   ```
   # 情感真实性检测报告
   
   ## 总体评分
   - 真实性等级：**authentic**
   - 得分：92.5%
   
   ## 优点
   - ✅ 使用了 8 个真实性细节标记
   - ✅ 情感强度与冲突程度匹配良好
   
   ## 问题清单
   🟡 **cliche** (warning)
   - 位置：第 3 段
   - 问题：陈词滥调：'泪水模糊了眼睛'
   - 建议：改为更具体的身体反应，如'眼睛酸胀'
   
   ## 修改优先级
   1. 替换陈词滥调
   2. 增加停顿标记
   ```

4. **保存报告**
   ```python
   with open("cache/authenticity_ch0001.json", 'w') as f:
       json.dump(authenticity_result['report'], f, ensure_ascii=False, indent=2)
   
   with open("cache/authenticity_ch0001.md", 'w') as f:
       f.write(authenticity_result['markdown'])
   ```

---

### 第六步：后验更新（章节完成后）

**时机**：章节最终定稿后

**步骤**：

1. **更新人物轨迹**
   ```python
   # 由 agent_trajectory_update (后验 agent) 执行详细分析
   # 然后调用此方法记录
   
   humanware.update_character_trajectory(
       chapter_num=1,
       character_name="主角",
       content_text=final_content,
       context={...}  # 可选
   )
   ```

2. **记录的内容**
   - 心理层的创伤和驱动力变化
   - 信念系统的转变
   - 与其他角色关系温度的变化
   - 新增的脆弱点和防御机制

3. **下一章使用**
   - 下一章的触发点标注时参考这些信息
   - 下一章的人物声音可能会因为心理变化而调整
   - 人物的反应方式会因为新的伤口而改变

---

## 📚 数据结构

### 1. character_voices.json

```json
{
  "主角": {
    "character_name": "主角",
    "vocabulary_profile": {
      "preferred_words": ["反正", "算了"],
      "high_frequency": ["嗯", "那个"],
      "unique_expressions": []
    },
    "vocabulary_avoid": ["顿时", "只见", "仅仅"],
    "sentence_structure": {
      "description": "短句为主，尤其压力下更短",
      "average_length": 12,
      "complexity": "simple"
    },
    "tone_profile": {
      "temperature": "cold",
      "directness": "direct"
    },
    "speech_habits": [...],
    "body_language_preference": ["转身避开", "目光飘移"],
    "thinking_pattern": "scattered",
    "silence_tendency": "frequent",
    "filler_words": ["呃", "那个"],
    "forbidden_patterns": [...]
  }
}
```

### 2. emotional_expressions.json

```json
{
  "孤独与自我怀疑": {
    "brief_description": "个体感到被孤立、怀疑自己价值",
    "expression_patterns": [
      {
        "name": "身体退缩",
        "category": "body",
        "manifestations": ["蜷缩", "变小", "躲在角落"],
        "reference_examples": [...],
        "applicable_emotions": ["孤独", "自我怀疑"],
        "scene_context": "独处或被指责时",
        "contraindications": ["不要过度拟人化"],
        "intensity_variations": {
          "subtle": "手指微微抖动",
          "moderate": "肩膀向内缩",
          "intense": "整个身体蜷缩"
        }
      }
    ],
    "avoid_patterns": ["过度宏大的描写"],
    "physiological_responses": ["胸口发紧", "脑子一片空白"]
  }
}
```

### 3. emotional_triggers.json

```json
{
  "ch_0001": [
    {
      "trigger_id": "tg_0001_01",
      "scene_position": "本章中段",
      "character_name": "主角",
      "emotional_core": "被背叛后的自我怀疑",
      "intensity": "moderate",
      "trigger_type": "micro_action",
      "trigger_description": "对方看向别的地方时，主角注意到了",
      "expected_effect": "让读者感到主角的被忽视感",
      "suggested_expressions": ["目光也转向别处，试图证明无所谓"],
      "anti_patterns": ["不要立刻生气或反驳"]
    }
  ]
}
```

### 4. character_trajectories.json

```json
{
  "主角": {
    "character_name": "主角",
    "core_identity": {...},
    "snapshots": [
      {
        "chapter_num": 1,
        "timestamp": "2026-10-12T10:30:00",
        "trauma_layer": {
          "core_wound": "被父亲忽视"
        },
        "driving_layer": {
          "wants": "被看见、被认可"
        },
        "current_layer": {
          "mood": "压抑、不安"
        },
        "worldview_shifts": ["开始怀疑自己的价值"],
        "current_vulnerabilities": ["被忽视", "自我怀疑"],
        "emotional_baseline_shift": "descending",
        "emotional_reservoir": "moderate"
      }
    ],
    "relationships": {
      "配角A": [
        {
          "character_name": "配角A",
          "temperature": 0.5,
          "trust_level": 0.6,
          "dependency_level": 0.3,
          "recent_interaction": "有过一次冷战",
          "power_dynamic": "equal"
        }
      ]
    }
  }
}
```

---

## 🔧 集成到工作流

### 选项 A：作为 script 节点集成

在 `mvp` workflow 中添加新的脚本节点：

```json
{
  "id": "script_voice_inject",
  "label": "人物声音注入",
  "node_type": "script",
  "script_source": "library",
  "script_type": "python",
  "script_group": "xs2-novel-flywheel-xs2",
  "script_name": "voice_injection_script",
  "script_args": "inject --chapter {{chapter_number}} --input story/{{chapter_number}}/content_draft.md --output story/{{chapter_number}}/content.md",
  "position": {"x": 400, "y": 300},
  "auto_flow": false,
  "fail_auto_skip": true
}
```

### 选项 B：作为后处理集成

在 `si_post` (意图审核后处理) 中调用：

```python
# si_post.py 末尾添加

from xs2.humanware_engine.integration import HumanwareIntegration

def post_authenticity_check(content_path, chapter_num):
    humanware = HumanwareIntegration()
    
    with open(content_path, 'r') as f:
        content = f.read()
    
    result = humanware.check_authenticity(
        content,
        chapter_num,
        main_characters=[...],
        main_character="main_char"
    )
    
    # 保存报告
    report_path = f"cache/authenticity_ch{chapter_num:04d}.md"
    with open(report_path, 'w') as f:
        f.write(result['markdown'])
    
    return result['pass']
```

---

## ✅ 检查清单

### 初始化时

- [ ] 人物声音库创建完成
- [ ] 情感表现库初始化完成
- [ ] 人物轨迹库初始化完成

### 每章创作时

- [ ] 情感触发点已标注
- [ ] active_context 已增强
- [ ] 人物声音指引已注入
- [ ] 真实性检测已执行
- [ ] 报告已保存

### 质量检查

- [ ] 陈词滥调 < 2 个
- [ ] 真实性得分 ≥ 0.7
- [ ] 人物工具化问题 = 0
- [ ] 至少 3 个真实性标记
- [ ] 角色间声音差异明显

---

## 🎯 预期效果

### 没有 Humanware 之前

```
# 粗稿
主角看到这一幕，泪水模糊了眼睛。她顿时感到一阵巨大的失望涌上心头。
她深吸一口气，试图整理思绪。
```

### 有 Humanware 之后

```
# 优化后
主角的目光也转向别处。没有说话。

（手指在杯子上敲了一下——那是压力下的习惯动作。）

几秒钟后，她开口："算了。"

（声音很轻，带着逃避意味。对方听不出失望，只能听出冷漠。）
```

### 差异

- 原：用陈词滥调表达情感，显得虚假
- 改：用具体的细节和动作展现内心，读者能感受到真实的失望

---

## 📖 参考资源

- `humanware_system_prompts.md` - 详细的 LLM 提示词
- `character_voice_library.py` - 声音库实现
- `emotional_expression_library.py` - 感受库实现
- `authenticity_checker.py` - 真实性检测实现
- `integration.py` - 集成接口

---

## 🚨 常见问题

### Q: 这会让创作变慢吗？
A: 初始化需要时间（2-3 小时用于 Agent 分析）。但后续创作会更快，因为系统自动处理很多"人味"的细节。

### Q: 可以跳过某些步骤吗？
A: 可以。最小化的流程是：初始化 → 增强 active_context → 真实性检测。

### Q: 生成的内容会重复吗？
A: 变异策略会避免同类场景的重复表现。系统会记录使用过的表现方式。

### Q: 如何处理不适配的建议？
A: 系统的建议是参考，不是强制。作者可以选择接受或忽略。

---

## 📞 支持和反馈

遇到问题？

1. 检查 `cache/authenticity_*.md` 中的详细报告
2. 查看 `meta/character_*.json` 中的人物档案是否准确
3. 验证 `learning/active_context_enhanced.md` 中的推荐是否合理

---

**祝你的小说更有人味！** ✨
