#!/usr/bin/env python3
"""
Humanware Engine 效果演示

展示使用 Humanware 系统前后的对比
"""

import sys
from pathlib import Path

# 添加路径
sys.path.insert(0, str(
    Path(__file__).parent / "data" / "plugins" / "checkouts" / "xs2-novel-flywheel" /
    "4eed8cb3aec88b182e60541b2e80c065612b08ff-e0fa97cde7e45dbc" / "resources" / "script-library"
))

from xs2.humanware_engine.authenticity_checker import EmotionalAuthenticityChecker, generate_authenticity_report_markdown


def demo_before_humanware():
    """没有 Humanware 的典型输出"""
    return """
主角看到这一幕，泪水模糊了眼睛。她顿时感到一阵巨大的失望涌上心头。

"为什么？"她大声喊道，声音颤抖着。

她的心里既难过又生气，同时还感到一丝绝望。她深吸一口气，试图整理思绪。

"我明白了，"她平静地说，"原来一切都是假的。"

她转身离开，背影显得无比孤独。
""".strip()


def demo_after_humanware():
    """使用 Humanware 优化后的输出"""
    return """
主角的目光也转向别处。

没有说话。

（手指在杯子上敲了一下——那是压力下的习惯动作。杯子的边缘有个小缺口，她的指甲卡在那里。）

几秒钟后，她开口："算了。"

声音很轻，带着那种"反正都一样"的逃避意味。对方听不出失望，只能听出冷漠。

她站起来时，椅子腿发出刺耳的声音。她没有回头。

走出门时，她的手在门把上停了一下，好像想说什么，但最后只是把门关上了。

不是用力摔门。只是...关上。那种"没什么好说的"的关法。
""".strip()


def analyze_text(text, label):
    """分析文本的真实性"""
    print(f"\n{'='*70}")
    print(f"{label}")
    print(f"{'='*70}\n")

    print(text)

    checker = EmotionalAuthenticityChecker()
    report = checker.check_text(
        text,
        character_name="主角",
        expected_emotional_state="失望与被背叛"
    )

    print(f"\n{'-'*70}")
    print(f"真实性评分：{report.authenticity_score:.1%}")
    print(f"等级：{report.overall_level.value}")
    print(f"{'-'*70}\n")

    if report.strengths:
        print("优点：")
        for strength in report.strengths:
            print(f"  ✅ {strength}")

    if report.issues:
        print("\n问题：")
        for issue in report.issues[:3]:  # 只显示前3个
            severity_icon = {"critical": "🔴", "warning": "🟡", "suggestion": "🔵"}.get(
                issue.severity, "⚪"
            )
            print(f"  {severity_icon} {issue.issue}")
            print(f"     建议：{issue.suggestion}")

    return report


def main():
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║              Humanware Engine 效果演示                               ║
║                                                                      ║
║        让 AI 生成的文字具有"人味" —— 真实、独特、有温度            ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
    """)

    # 分析"之前"
    report_before = analyze_text(demo_before_humanware(), "❌ 没有 Humanware 的输出")

    # 分析"之后"
    report_after = analyze_text(demo_after_humanware(), "✅ 使用 Humanware 优化后")

    # 对比
    print(f"\n{'='*70}")
    print("对比总结")
    print(f"{'='*70}\n")

    improvement = (report_after.authenticity_score - report_before.authenticity_score) * 100
    print(f"真实性提升：+{improvement:.1f}%")
    print(f"  之前：{report_before.authenticity_score:.1%}")
    print(f"  之后：{report_after.authenticity_score:.1%}")

    print(f"\n问题减少：-{len(report_before.issues) - len(report_after.issues)} 个")
    print(f"  之前：{len(report_before.issues)} 个问题")
    print(f"  之后：{len(report_after.issues)} 个问题")

    print("\n核心改进：")
    print("  1. 消除陈词滥调（'泪水模糊'、'涌上心头'）")
    print("  2. 用具体动作代替抽象情感（'手指敲杯子'而非'失望'）")
    print("  3. 增加真实的停顿和留白（'没有说话'、'停了一下'）")
    print("  4. 声音独特性（'算了'、'反正都一样'符合角色声音）")
    print("  5. 细节支撑情感（'杯子的小缺口'、'椅子腿的声音'）")

    print(f"\n{'='*70}")
    print("\n这就是 Humanware 的力量！\n")


if __name__ == "__main__":
    main()
