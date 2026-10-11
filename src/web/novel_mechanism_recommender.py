"""智能写法机制推荐系统 - 根据写法库推荐故事和机制"""
from pathlib import Path
from typing import Any
import json
from collections import defaultdict, Counter
from .novel_library import read_json, fingerprint


def extract_mechanisms_from_library(library_root: Path) -> dict[str, dict[str, Any]]:
    """
    从写法库中提取所有机制及其元数据
    返回: {机制名: {出现次数, 包含的作品, 题材偏好, ...}}
    """
    mechanism_stats = defaultdict(lambda: {
        'count': 0,
        'works': [],
        'genres': [],
        'pov': [],
        'candidate_ids': [],
        'source_hashes': set()
    })

    library_items = []
    if not library_root.exists():
        return {}

    for item_folder in library_root.iterdir():
        if not item_folder.is_dir():
            continue

        manifest_path = item_folder / "manifest.json"
        candidates_path = item_folder / "candidates.json"

        if not manifest_path.is_file() or not candidates_path.is_file():
            continue

        manifest = read_json(manifest_path, {})
        candidates_data = read_json(candidates_path, {})

        if not manifest.get("id"):
            continue

        work_info = {
            'id': manifest['id'],
            'name': manifest.get('name', ''),
            'genres': manifest.get('genres', []),
            'pov': manifest.get('pov', []),
            'created_at': manifest.get('created_at', '')
        }

        library_items.append(work_info)

        # 提取机制
        for candidate in candidates_data.get('candidates', []):
            if not candidate.get('mechanism'):
                continue

            mechanism = candidate['mechanism']
            stats = mechanism_stats[mechanism]
            stats['count'] += 1

            if work_info['id'] not in stats['works']:
                stats['works'].append(work_info['id'])

            stats['genres'].extend(work_info['genres'])
            stats['pov'].extend(work_info['pov'])

            candidate_id = candidate.get('candidate_id', '')
            if candidate_id:
                stats['candidate_ids'].append(candidate_id)

            source_hash = candidate.get('source', {}).get('text_sha256', '')
            if source_hash:
                stats['source_hashes'].add(source_hash)

    # 转换为序列化格式
    result = {}
    for mechanism, stats in mechanism_stats.items():
        result[mechanism] = {
            'count': stats['count'],
            'works': stats['works'],
            'genres': Counter(stats['genres']).most_common(),
            'pov': Counter(stats['pov']).most_common(),
            'candidate_count': len(set(stats['candidate_ids'])),
            'unique_sources': len(stats['source_hashes'])
        }

    return result


def find_mechanism_combinations(library_root: Path) -> list[dict[str, Any]]:
    """
    分析最常见的机制组合（在同一作品中同时出现的机制）
    返回按频率排序的组合列表
    """
    combinations = defaultdict(lambda: {
        'count': 0,
        'works': [],
        'genres': [],
        'effectiveness_score': 0
    })

    if not library_root.exists():
        return []

    for item_folder in library_root.iterdir():
        if not item_folder.is_dir():
            continue

        candidates_path = item_folder / "candidates.json"
        manifest_path = item_folder / "manifest.json"

        if not candidates_path.is_file():
            continue

        manifest = read_json(manifest_path, {})
        candidates_data = read_json(candidates_path, {})

        mechanisms = tuple(sorted(set(
            c.get('mechanism', '')
            for c in candidates_data.get('candidates', [])
            if c.get('mechanism')
        )))

        if len(mechanisms) < 2:
            continue

        combo = combinations[mechanisms]
        combo['count'] += 1
        combo['works'].append(manifest.get('id', ''))
        combo['genres'].extend(manifest.get('genres', []))

    # 转换为列表并排序
    result = []
    for mechanisms, data in combinations.items():
        result.append({
            'mechanisms': list(mechanisms),
            'frequency': data['count'],
            'works': data['works'],
            'top_genres': Counter(data['genres']).most_common(3),
            'synergy_score': calculate_synergy_score(mechanisms, data['count'])
        })

    return sorted(result, key=lambda x: x['frequency'], reverse=True)


def calculate_synergy_score(mechanisms: tuple, co_occurrence: int) -> float:
    """
    计算机制组合的协同分数
    基于：共同出现频率、机制类型多样性、理论协同潜力
    """
    # 基础分：出现次数
    base_score = min(co_occurrence / 5, 1.0)  # 最多5分

    # 多样性分：不同机制的数量
    diversity_bonus = len(set(mechanisms)) / 5  # 最多2分

    # 理论协同分：根据机制类型
    synergy_bonus = 0
    mechanism_types = categorize_mechanisms(mechanisms)
    if len(mechanism_types) >= 2:
        synergy_bonus = 0.2  # 有不同类型的机制，协同潜力高

    return min(base_score + diversity_bonus + synergy_bonus, 1.0)


def categorize_mechanisms(mechanisms: tuple) -> set[str]:
    """
    将机制分类为几个大类
    用于评估多样性和协同潜力
    """
    info_mechanisms = {
        '身份线索触发分层信息解锁',
        '相互冲突的认知模型制造解释悬念',
        '撤回披露诱发追问',
        '以保密障碍放大信息需求'
    }

    pressure_mechanisms = {
        '生理限制收束目标',
        '量化反馈与惩罚阈值绑定生存压力',
        '即时生存压力重排代价偏好'
    }

    action_mechanisms = {
        '观察—假设—干预驱动主体获得能动性',
        '行动后的可观察反馈促成规则学习',
        '异常规则从局部物件扩展为退路剥夺'
    }

    types = set()
    for mechanism in mechanisms:
        if mechanism in info_mechanisms:
            types.add('信息类')
        elif mechanism in pressure_mechanisms:
            types.add('压力类')
        elif mechanism in action_mechanisms:
            types.add('行动类')
        else:
            types.add('其他类')

    return types


def recommend_story_directions(library_root: Path, count: int = 3) -> dict[str, Any]:
    """
    根据写法库推荐故事方向

    返回结构:
    {
      'story_recommendations': [
        {
          'title': '...',
          'mechanisms': [...],
          'frequency': int,
          'genres': [...],
          'pov': [...],
          'source_works': [...],
          'synergy_score': float,
          'reasoning': '...'
        }
      ],
      'mechanism_stats': {...}
    }
    """
    mechanisms = extract_mechanisms_from_library(library_root)
    combinations = find_mechanism_combinations(library_root)

    # 选择前 count 个组合作为推荐
    recommendations = []
    for combo in combinations[:count]:
        title = infer_story_title(combo['mechanisms'])
        recommendations.append({
            'title': title,
            'mechanisms': combo['mechanisms'],
            'frequency': combo['frequency'],
            'genres': [genre[0] for genre in combo['top_genres']],
            'source_works': combo['works'],
            'synergy_score': combo['synergy_score'],
            'reasoning': generate_recommendation_reason(
                combo['mechanisms'], combo['frequency'], combo['top_genres']
            )
        })

    return {
        'story_recommendations': recommendations,
        'mechanism_stats': {
            m: {'frequency': stats['count'], 'genres': dict(stats['genres'])}
            for m, stats in mechanisms.items()
        },
        'total_mechanisms': len(mechanisms),
        'total_combinations': len(combinations)
    }


def infer_story_title(mechanisms: list[str]) -> str:
    """
    根据机制组合推断故事类型
    """
    mechanism_keywords = {
        '生理限制收束目标': '生存压力',
        '即时生存压力重排代价偏好': '道德困局',
        '身份线索触发分层信息解锁': '身份谜团',
        '相互冲突的认知模型制造解释悬念': '认知冲突',
        '观察—假设—干预驱动主体获得能动性': '推理悬念',
        '以可见材料耐受性建立威胁标尺': '恐怖压力',
        '熟悉诉求与异常行为的语义错位': '惊悚感'
    }

    keywords = [mechanism_keywords.get(m, '故事') for m in mechanisms[:3]]
    return ' + '.join(keywords) or '综合故事'


def generate_recommendation_reason(mechanisms: list[str], frequency: int, genres: list) -> str:
    """
    为推荐生成人类可读的解释
    """
    genre_str = '、'.join([g[0] for g in genres[:2]]) if genres else '多种'

    reason_parts = [
        f"在写法库中{genre_str}题材作品中高频出现（{frequency}部作品使用）",
    ]

    if len(mechanisms) >= 2:
        reason_parts.append(f"机制组合具有良好的协同效果")

    return '；'.join(reason_parts)


def match_story_with_mechanisms(
    adopted_mechanisms: list[str],
    library_root: Path
) -> dict[str, Any]:
    """
    已有采用的写法时，推荐最佳匹配的故事方向和补充机制
    """
    if not adopted_mechanisms:
        return {}

    mechanisms = extract_mechanisms_from_library(library_root)
    combinations = find_mechanism_combinations(library_root)

    adopted_set = set(adopted_mechanisms)

    # 找到包含已采用机制的最佳组合
    matching_combos = []
    for combo in combinations:
        combo_set = set(combo['mechanisms'])
        intersection = adopted_set & combo_set

        if len(intersection) >= len(adopted_set) * 0.5:  # 至少一半的已采用机制
            similarity = len(intersection) / len(adopted_set | combo_set)
            complementary = combo_set - adopted_set

            matching_combos.append({
                'combo': combo,
                'similarity': similarity,
                'shared': list(intersection),
                'complementary': list(complementary)
            })

    # 按相似度排序
    matching_combos.sort(key=lambda x: x['similarity'], reverse=True)

    best_match = matching_combos[0] if matching_combos else None

    return {
        'best_match': {
            'story_type': infer_story_title(best_match['combo']['mechanisms']),
            'similarity_score': best_match['similarity'],
            'shared_mechanisms': best_match['shared'],
            'complementary_mechanisms': best_match['complementary'],
            'source_works': best_match['combo']['works'],
            'reasoning': f"此故事方向与你已确认的{len(best_match['shared'])}个机制完全匹配，"
                        f"补充{len(best_match['complementary'])}个新机制能强化协同效果"
        } if best_match else None,
        'all_matches': [
            {
                'story_type': infer_story_title(m['combo']['mechanisms']),
                'similarity': m['similarity'],
                'shared': m['shared'],
                'complementary': m['complementary']
            }
            for m in matching_combos[:5]
        ]
    }


def generate_recommendations_file(
    library_root: Path,
    adopted_mechanisms: list[str] | None = None
) -> dict[str, Any]:
    """
    生成完整的推荐文件内容，用于传给顾问
    """
    if adopted_mechanisms:
        return match_story_with_mechanisms(adopted_mechanisms, library_root)
    else:
        return recommend_story_directions(library_root)
