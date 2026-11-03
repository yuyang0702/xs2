import asyncio
import json

import pytest

from src.workflow.output_repair import prepare_json_file_output


def prepare(raw, **params):
    return asyncio.run(prepare_json_file_output(raw_output=raw,
        node_params={'json_single_string_field': 'body', **params}, output_file_path='candidate.json'))


def test_known_payload_quotes_newlines_and_existing_escapes_preserve_text():
    raw = r'{"body":"她说:"别走。"\n\n\"我等你。\"\\旧路"}'
    result = prepare(raw)
    assert result['success']
    assert json.loads(result['text']) == {'body': '她说:"别走。"\n\n"我等你。"\\旧路'}
    assert result['meta'].get('_json_repair_applied')


@pytest.mark.parametrize('raw', [
    '{"body":"先","body":"后"}',
    '{"body":"原文","summary":"不是正文"}',
    '{"body":"甲"}{"body":"乙"}',
    '{"body":"她说:"好。"',
    r'{"body":"她说:"好。"\q"}',
    '{"body":"她说:"好。", "other":"旁路"}',
    '说明：{"body":"她说:"好。"}',
])
def test_ambiguous_or_changed_document_shape_is_not_recovered(raw):
    assert not prepare(raw)['success']


def test_optin_does_not_relax_validate_only_or_default_policy():
    raw = '{"body":"她说:"好。""}'
    assert not prepare(raw, json_repair_policy='validate_only')['success']
    result = asyncio.run(prepare_json_file_output(raw_output=raw, node_params={}, output_file_path='candidate.json'))
    assert not result['success']


def test_already_valid_single_string_allows_literal_braces_without_repair():
    text = '她翻到 {旧页}，看见"先别走"。\n第二行。'
    result = prepare(json.dumps({'body': text}, ensure_ascii=False))
    assert result['success'] and json.loads(result['text'])['body'] == text
