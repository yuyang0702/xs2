import json

from src.workflow.json_output import (
    detect_output_format,
    get_json_policy,
    get_json_retry_count,
    safe_repair_json_text,
    validate_and_format_json,
)


def test_detect_json_output_defaults_from_file_extension():
    assert detect_output_format("cache/character/skeleton.json", {}) == "json"
    assert get_json_policy("cache/character/skeleton.json", {}) == "safe_repair_then_retry"
    assert get_json_retry_count({}) == 1


def test_strip_markdown_fence_and_format_json():
    raw = '```json\n{"a": 1}\n```'
    result = validate_and_format_json(raw)

    assert result.success
    assert json.loads(result.formatted) == {"a": 1}
    assert "strip_markdown_fence" in result.repairs


def test_extract_json_body_from_prefixed_text():
    raw = '以下是结果：\n{"a": 1}\n请查收'
    result = validate_and_format_json(raw)

    assert result.success
    assert json.loads(result.formatted) == {"a": 1}
    assert "extract_json_body" in result.repairs


def test_valid_json_with_chinese_dialogue_quotes_is_not_repaired():
    raw = json.dumps(
        {
            "body": "驼铃声从浓雾中传来。\n\n“你那伤，再拖就废了。”小贩说，“用这个。”",
        },
        ensure_ascii=False,
        indent=2,
    )
    result = validate_and_format_json(raw, repair=True)

    assert result.success
    assert result.repairs == []
    body = json.loads(result.formatted)["body"]
    assert body.count("“") == 2
    assert body.count("”") == 2


def test_fenced_novel_json_preserves_dialogue_and_apostrophes():
    body = '“别跟着我。”他说。她没接话，袋上还有‘东岸’的字样。'
    raw = "```json\n" + json.dumps({"body": body}, ensure_ascii=False) + "\n```"

    result = validate_and_format_json(raw)

    assert result.success
    assert result.data == {"body": body}
    assert result.repairs == ["strip_markdown_fence"]


def test_prefixed_novel_json_preserves_dialogue():
    body = '“你看见了？”他问，“还是听别人说的？”'
    raw = "下面是正文：\n" + json.dumps({"body": body}, ensure_ascii=False) + "\n完毕"

    result = validate_and_format_json(raw)

    assert result.success
    assert result.data == {"body": body}
    assert result.repairs == ["extract_json_body"]


def test_literal_controls_in_novel_json_preserve_body_and_other_fields():
    body = '“你跟着我。”\n\n袋口\t贴着手，标签\x00还在。'
    raw = '{"body": "' + body + '", "meta": {"chapter": "0002", "notes": ["原句"]}}'

    result = validate_and_format_json("```json\n" + raw + "\n```")

    assert result.success
    assert result.data == {
        "body": body,
        "meta": {"chapter": "0002", "notes": ["原句"]},
    }
    assert result.repairs == ["strip_markdown_fence", "escape_string_control_characters"]
    assert json.loads(result.formatted) == result.data


def test_literal_controls_are_rejected_when_repairs_are_disabled():
    result = validate_and_format_json('{"body": "第一段\n第二段"}', repair=False)

    assert not result.success
    assert result.repairs == []


def test_control_repair_does_not_guess_unescaped_dialogue_quotes():
    raw = '{"body": "第一段\n"你跟着我。"他说。", "chapter": "0002"}'

    result = validate_and_format_json(raw)

    assert not result.success
    assert "escape_string_control_characters" not in result.repairs


def test_trailing_comma_repair_preserves_string_content():
    body = '“别动。”纸上写着 , }，还有 , ] 和‘原文’。'
    raw = json.dumps({"body": body}, ensure_ascii=False)[:-1] + ",}"

    result = validate_and_format_json(raw)

    assert result.success
    assert result.data == {"body": body}
    assert result.repairs == ["remove_trailing_commas"]


def test_smart_quote_keys_preserve_ascii_delimited_prose():
    body = '“我没跟。”他说，“我就是路过。”'
    raw = '{“body”: ' + json.dumps(body, ensure_ascii=False) + ",}"

    result = validate_and_format_json(raw)

    assert result.success
    assert result.data == {"body": body}
    assert result.repairs == ["normalize_quotes", "remove_trailing_commas"]


def test_normalize_smart_quote_keys_and_remove_trailing_commas():
    raw = '{“a”: 1, “b”: [2,],}'
    result = validate_and_format_json(raw)

    assert result.success
    assert json.loads(result.formatted) == {"a": 1, "b": [2]}
    assert "normalize_quotes" in result.repairs
    assert "remove_trailing_commas" in result.repairs


def test_remove_obvious_orphan_line_without_semantic_merge():
    raw = '''{
  "world_position": {
    "origin_class": "流放者，原为灰烬平原某聚落的猎手",
    "affiliation": "无固定势力",
    "social_role": "独行流放者",
寻者",
    "stance_on_core_conflict": "中立但寻求真相"
  }
}'''
    result = validate_and_format_json(raw)

    assert result.success
    parsed = json.loads(result.formatted)
    assert parsed["world_position"]["social_role"] == "独行流放者"
    assert parsed["world_position"]["stance_on_core_conflict"] == "中立但寻求真相"
    assert "remove_orphan_lines" in result.repairs


def test_unrepairable_json_stays_failed():
    raw = '{"a": }'
    result = validate_and_format_json(raw)

    assert not result.success
    assert result.error


def test_safe_repair_does_not_remove_key_like_lines():
    raw = '{\n  "a": 1,\n  broken: value\n}'
    repaired, repairs = safe_repair_json_text(raw)

    assert "broken: value" in repaired
    assert "remove_orphan_lines" not in repairs
