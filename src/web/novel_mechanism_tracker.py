"""追踪本书使用的写法机制，记录和分析协同效果"""
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
import json
import hashlib


def save_mechanism_usage(
    root: Path,
    chapter: str,
    mechanisms_used: list[str],
    effectiveness_notes: str = ""
) -> bool:
    """
    记录本章使用的写法机制
    """
    log_path = root / "learning/mechanism_usage_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # 读取已有记录
    if log_path.exists():
        try:
            log_data = json.loads(log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            log_data = {"version": 1, "chapters": {}, "created_at": datetime.now(timezone.utc).isoformat()}
    else:
        log_data = {
            "version": 1,
            "chapters": {},
            "created_at": datetime.now(timezone.utc).isoformat()
        }

    # 更新本章记录
    log_data["chapters"][chapter] = {
        "mechanisms": mechanisms_used,
        "effectiveness_notes": effectiveness_notes,
        "recorded_at": datetime.now(timezone.utc).isoformat()
    }

    # 保存
    log_path.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def get_mechanism_usage_history(root: Path) -> dict[str, Any]:
    """
    获取本书的机制使用历史
    """
    log_path = root / "learning/mechanism_usage_log.json"

    if not log_path.exists():
        return {"version": 0, "chapters": {}}

    try:
        return json.loads(log_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return {"version": 0, "chapters": {}}


def extract_used_mechanisms(root: Path) -> dict[str, dict[str, Any]]:
    """
    汇总本书所有章节使用的机制
    """
    history = get_mechanism_usage_history(root)
    mechanism_stats = {}

    for chapter, data in history.get("chapters", {}).items():
        mechanisms = data.get("mechanisms", [])
        for mechanism in mechanisms:
            if mechanism not in mechanism_stats:
                mechanism_stats[mechanism] = {
                    "chapters": [],
                    "usage_count": 0
                }
            mechanism_stats[mechanism]["chapters"].append(chapter)
            mechanism_stats[mechanism]["usage_count"] += 1

    return mechanism_stats


def detect_synergies(root: Path) -> list[dict[str, Any]]:
    """
    检测本书中同时使用的机制组合（协同）
    """
    history = get_mechanism_usage_history(root)
    synergy_pairs = {}

    for chapter, data in history.get("chapters", {}).items():
        mechanisms = set(data.get("mechanisms", []))

        # 检查所有两两组合
        mechanisms_list = sorted(list(mechanisms))
        for i, m1 in enumerate(mechanisms_list):
            for m2 in mechanisms_list[i+1:]:
                pair_key = f"{m1}|{m2}"
                if pair_key not in synergy_pairs:
                    synergy_pairs[pair_key] = {
                        "mechanism_a": m1,
                        "mechanism_b": m2,
                        "chapters": [],
                        "co_occurrences": 0
                    }
                synergy_pairs[pair_key]["chapters"].append(chapter)
                synergy_pairs[pair_key]["co_occurrences"] += 1

    # 转换为列表并排序
    synergies = sorted(
        synergy_pairs.values(),
        key=lambda x: x["co_occurrences"],
        reverse=True
    )

    return synergies


def generate_mechanism_report(root: Path) -> dict[str, Any]:
    """
    生成本书的写法机制使用报告
    """
    used = extract_used_mechanisms(root)
    synergies = detect_synergies(root)
    history = get_mechanism_usage_history(root)

    report = {
        "total_chapters": len(history.get("chapters", {})),
        "unique_mechanisms": len(used),
        "mechanisms": [
            {
                "name": mechanism,
                "usage_count": stats["usage_count"],
                "chapters_used": stats["chapters"]
            }
            for mechanism, stats in sorted(
                used.items(),
                key=lambda x: x[1]["usage_count"],
                reverse=True
            )
        ],
        "synergies": [
            {
                "mechanism_a": s["mechanism_a"],
                "mechanism_b": s["mechanism_b"],
                "co_occurrences": s["co_occurrences"],
                "chapters": s["chapters"]
            }
            for s in synergies
        ],
        "generated_at": datetime.now(timezone.utc).isoformat()
    }

    return report


def save_mechanism_report(root: Path) -> bool:
    """
    保存本书的机制使用报告
    """
    report = generate_mechanism_report(root)
    report_path = root / "learning/mechanism_synergy_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return True
