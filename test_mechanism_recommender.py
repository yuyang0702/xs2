#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试写法机制智能推荐系统
"""
import sys
import io
from pathlib import Path

# 处理编码
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.web.novel_mechanism_recommender import (
    extract_mechanisms_from_library,
    find_mechanism_combinations,
    recommend_story_directions,
    match_story_with_mechanisms
)

def test_mechanism_extraction():
    """测试机制提取"""
    library_root = project_root / "data" / "writing-library"

    print("=" * 60)
    print("测试1：从写法库提取机制")
    print("=" * 60)

    if not library_root.exists():
        print(f"❌ 写法库路径不存在：{library_root}")
        return False

    mechanisms = extract_mechanisms_from_library(library_root)

    if not mechanisms:
        print("❌ 没有提取到任何机制")
        return False

    print(f"✓ 成功提取 {len(mechanisms)} 个唯一机制：")
    for mechanism, stats in sorted(mechanisms.items(), key=lambda x: x[1]['count'], reverse=True):
        print(f"  - {mechanism}: {stats['count']} 部作品, {stats['candidate_count']} 个候选")

    return True


def test_combination_finding():
    """测试机制组合查找"""
    library_root = project_root / "data" / "writing-library"

    print("\n" + "=" * 60)
    print("测试2：发现最常见的机制组合")
    print("=" * 60)

    combinations = find_mechanism_combinations(library_root)

    if not combinations:
        print("⚠ 没有发现机制组合（可能只有单个机制的作品）")
        return True

    print(f"✓ 发现 {len(combinations)} 个机制组合：")
    for combo in combinations[:5]:  # 显示前5个
        print(f"  - 组合: {' + '.join(combo['mechanisms'][:2])}... ({combo['frequency']} 次共现)")
        print(f"    来源: {', '.join(combo['works'][:2])}")
        print(f"    题材: {combo['top_genres']}")
        print()

    return True


def test_story_recommendations():
    """测试故事方向推荐"""
    library_root = project_root / "data" / "writing-library"

    print("\n" + "=" * 60)
    print("测试3：推荐故事方向")
    print("=" * 60)

    recommendations = recommend_story_directions(library_root, count=3)

    if not recommendations.get('story_recommendations'):
        print("⚠ 没有推荐（可能库中数据不足）")
        return True

    print(f"✓ 生成 {len(recommendations['story_recommendations'])} 个故事推荐：")
    for i, rec in enumerate(recommendations['story_recommendations'], 1):
        print(f"\n  推荐 {i}: {rec['title']}")
        print(f"  机制: {', '.join(rec['mechanisms'][:3])}...")
        print(f"  频率: {rec['frequency']} 部作品")
        print(f"  题材: {', '.join(rec['genres'])}")
        print(f"  理由: {rec['reasoning']}")
        print(f"  协同分数: {rec['synergy_score']:.2f}")

    return True


def test_adopted_mechanisms_matching():
    """测试已采用写法的匹配"""
    library_root = project_root / "data" / "writing-library"

    print("\n" + "=" * 60)
    print("测试4：基于已采用写法推荐")
    print("=" * 60)

    # 模拟已采用的机制
    adopted = [
        "生理限制收束目标",
        "即时生存压力重排代价偏好",
        "认知错位生成行动冲突"
    ]

    matching = match_story_with_mechanisms(adopted, library_root)

    if not matching.get('best_match'):
        print("⚠ 没有找到匹配的故事方向（可能库中数据不足）")
        return True

    best = matching['best_match']
    print(f"✓ 找到最佳匹配：")
    print(f"  故事类型: {best['story_type']}")
    print(f"  相似度: {best['similarity_score']:.2%}")
    print(f"  共同机制: {', '.join(best['shared_mechanisms'])}")
    print(f"  补充机制: {', '.join(best['complementary_mechanisms'])}")
    print(f"  理由: {best['reasoning']}")

    if matching.get('all_matches'):
        print(f"\n  其他匹配选项 ({len(matching['all_matches'])} 个):")
        for m in matching['all_matches'][:3]:
            print(f"    - {m['story_type']} (相似度: {m['similarity']:.2%})")

    return True


def main():
    print("\n🚀 开始测试写法机制智能推荐系统\n")

    tests = [
        ("机制提取", test_mechanism_extraction),
        ("组合发现", test_combination_finding),
        ("故事推荐", test_story_recommendations),
        ("已采用匹配", test_adopted_mechanisms_matching),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    print("\n" + "=" * 60)
    print("📊 测试结果总结")
    print("=" * 60)
    for name, result in results:
        status = "✓ 通过" if result else "❌ 失败"
        print(f"{name}: {status}")

    passed = sum(1 for _, r in results if r)
    total = len(results)
    print(f"\n总计: {passed}/{total} 个测试通过")

    return all(r for _, r in results)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
