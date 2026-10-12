#!/usr/bin/env python3
"""
Humanware Engine 快速启动脚本

这个脚本演示如何在实际工作流中使用 Humanware 系统。
可以直接运行或作为参考集成到现有的工作流脚本中。

使用方法：
  python humanware_quickstart.py --action init --workspace .
  python humanware_quickstart.py --action chapter --chapter 1 --workspace .
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(
    Path(__file__).parent / "data" / "plugins" / "checkouts" / "xs2-novel-flywheel" /
    "4eed8cb3aec88b182e60541b2e80c065612b08ff-e0fa97cde7e45dbc" / "resources" / "script-library"
))

from xs2.humanware_engine.integration import HumanwareIntegration


def action_init(workspace):
    """初始化 Humanware 系统"""
    print("\n" + "="*60)
    print("初始化 Humanware 系统")
    print("="*60)

    humanware = HumanwareIntegration(workspace)

    try:
        # 1. 初始化感受库和人物声音库
        print("\n[1/2] 初始化感受库和人物声音库...")
        result = humanware.post_distillation_init_humanware(
            "learning/candidates.json",
            "meta/character_profiles.json"
        )
        print(f"✓ {result['characters_initialized']} 个角色的声音档案已创建")

        # 2. 保存
        print("\n[2/2] 保存所有库...")
        humanware.save_all_libraries()
        print("✓ 所有库已保存")

        print("\n" + "="*60)
        print("初始化完成！")
        print("="*60)
        print("\n下一步：")
        print("  1. 运行参考资料蒸馏工作流")
        print("  2. LLM Agent 将自动：")
        print("     - 生成情感表现库 (learning/emotional_expressions.json)")
        print("     - 补充人物声音档案 (meta/character_voices.json)")
        print("  3. 执行 'humanware_quickstart.py --action chapter --chapter 1'")

    except FileNotFoundError as e:
        print(f"❌ 错误：找不到必要文件 - {e}")
        print("\n请确保以下文件存在：")
        print("  - learning/candidates.json")
        print("  - meta/character_profiles.json")
        return False

    return True


def action_chapter(workspace, chapter_num):
    """为单章准备和检查"""
    print("\n" + "="*60)
    print(f"为第 {chapter_num} 章准备和检查")
    print("="*60)

    humanware = HumanwareIntegration(workspace)

    try:
        # 1. 加载单章指导
        guide_path = Path(workspace) / f"story/{chapter_num:04d}/single_chapter_guide.md"
        if not guide_path.exists():
            # 尝试 JSON 格式
            guide_path = Path(workspace) / f"cache/guide_ch{chapter_num:04d}.json"
            if not guide_path.exists():
                print("❌ 未找到单章指导")
                return False

            with open(guide_path, 'r', encoding='utf-8') as f:
                guide = json.load(f)
        else:
            print("ℹ️  说明：暂时不支持直接从 MD 加载，需要 JSON 格式")
            return False

        # 2. 增强 active_context
        print(f"\n[1/3] 增强 active_context.md...")
        active_context_path = Path(workspace) / "learning" / "active_context.md"
        if active_context_path.exists():
            with open(active_context_path, 'r', encoding='utf-8') as f:
                context = f.read()

            # 获取主要角色（从人物档案）
            profiles_path = Path(workspace) / "meta" / "character_profiles.json"
            if profiles_path.exists():
                with open(profiles_path, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)
                    main_characters = list(profiles.keys())[:5]  # 前5个

                enhanced = humanware.enhance_active_context(context, chapter_num, main_characters)

                enhanced_path = Path(workspace) / "learning" / "active_context_humanware.md"
                with open(enhanced_path, 'w', encoding='utf-8') as f:
                    f.write(enhanced)

                print(f"✓ active_context 已增强并保存到 active_context_humanware.md")
        else:
            print("⚠️  未找到 active_context.md（可能还未生成）")

        # 3. 提示下一步
        print(f"\n[2/3] 等待写手 Agent 生成粗稿...")
        print("  → 保存为 story/{:04d}/content_draft.md".format(chapter_num))

        print(f"\n[3/3] 写手完成后，执行真实性检测...")

        print("\n" + "="*60)
        print("章节准备完成！")
        print("="*60)
        print("\n下一步：")
        print("  1. 写手 Agent (agent_sw) 生成粗稿")
        print("  2. 粗稿保存为 story/{:04d}/content_draft.md".format(chapter_num))
        print("  3. 执行 'humanware_quickstart.py --action verify --chapter {} --content story/{:04d}/content.md'".format(chapter_num, chapter_num))

    except Exception as e:
        print(f"❌ 错误：{e}")
        return False

    return True


def action_verify(workspace, chapter_num, content_path):
    """检查文本的情感真实性"""
    print("\n" + "="*60)
    print(f"检查第 {chapter_num} 章的情感真实性")
    print("="*60)

    humanware = HumanwareIntegration(workspace)

    try:
        # 加载内容
        full_path = Path(workspace) / content_path
        if not full_path.exists():
            print(f"❌ 找不到文件：{content_path}")
            return False

        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 获取主要角色
        profiles_path = Path(workspace) / "meta" / "character_profiles.json"
        main_characters = []
        if profiles_path.exists():
            with open(profiles_path, 'r', encoding='utf-8') as f:
                profiles = json.load(f)
                main_characters = list(profiles.keys())[:5]

        # 执行检查
        print("\n执行真实性检测...")
        result = humanware.check_authenticity(
            content,
            chapter_num,
            main_characters,
            main_character=main_characters[0] if main_characters else None
        )

        # 输出报告
        print("\n" + result['markdown'])

        # 保存报告
        report_path = Path(workspace) / "cache" / f"authenticity_ch{chapter_num:04d}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(result['report'], f, ensure_ascii=False, indent=2)

        print("\n✓ 报告已保存到", report_path)

        if result['pass']:
            print("\n✅ 审核通过！可以进行下一章创作。")
        else:
            print("\n⚠️  需要改进以下问题：")
            for issue in result['report']['issues'][:3]:
                print(f"  - {issue['issue']}: {issue['suggestion']}")

    except Exception as e:
        print(f"❌ 错误：{e}")
        import traceback
        traceback.print_exc()
        return False

    return True


def action_status(workspace):
    """显示系统状态"""
    print("\n" + "="*60)
    print("Humanware 系统状态")
    print("="*60)

    workspace_path = Path(workspace)

    # 检查各个库文件
    libraries = {
        "人物声音库": "meta/character_voices.json",
        "情感表现库": "learning/emotional_expressions.json",
        "人物轨迹库": "meta/character_trajectories.json",
        "情感触发点": "meta/emotional_triggers.json",
    }

    print("\n库文件状态：")
    for name, path in libraries.items():
        full_path = workspace_path / path
        if full_path.exists():
            size_kb = full_path.stat().st_size / 1024
            print(f"  ✓ {name} ({size_kb:.1f} KB)")
        else:
            print(f"  ✗ {name} (未创建)")

    # 检查章节数据
    print("\n章节数据：")
    story_path = workspace_path / "story"
    if story_path.exists():
        chapters = [d for d in story_path.iterdir() if d.is_dir()]
        print(f"  总章节数：{len(chapters)}")
        for chapter_dir in sorted(chapters)[-3:]:  # 最后3章
            content_path = chapter_dir / "content.md"
            if content_path.exists():
                print(f"  ✓ {chapter_dir.name}/content.md")

    print("\n" + "="*60)


def main():
    parser = argparse.ArgumentParser(
        description="Humanware Engine 快速启动脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 初始化系统
  python humanware_quickstart.py --action init --workspace .

  # 为第1章准备
  python humanware_quickstart.py --action chapter --chapter 1 --workspace .

  # 检查第1章
  python humanware_quickstart.py --action verify --chapter 1 --content story/0001/content.md --workspace .

  # 查看系统状态
  python humanware_quickstart.py --action status --workspace .
        """
    )

    parser.add_argument(
        "--action",
        choices=["init", "chapter", "verify", "status"],
        default="status",
        help="执行的操作"
    )
    parser.add_argument("--workspace", type=str, default=".", help="工作目录")
    parser.add_argument("--chapter", type=int, help="章节号")
    parser.add_argument("--content", type=str, help="内容文件路径")

    args = parser.parse_args()

    if args.action == "init":
        success = action_init(args.workspace)
        sys.exit(0 if success else 1)

    elif args.action == "chapter":
        if not args.chapter:
            print("❌ 需要指定 --chapter")
            sys.exit(1)
        success = action_chapter(args.workspace, args.chapter)
        sys.exit(0 if success else 1)

    elif args.action == "verify":
        if not args.chapter or not args.content:
            print("❌ 需要指定 --chapter 和 --content")
            sys.exit(1)
        success = action_verify(args.workspace, args.chapter, args.content)
        sys.exit(0 if success else 1)

    elif args.action == "status":
        action_status(args.workspace)
        sys.exit(0)


if __name__ == "__main__":
    main()
