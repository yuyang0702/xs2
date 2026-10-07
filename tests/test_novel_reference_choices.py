import json
import tempfile
import unittest
from pathlib import Path
from src.web.novel_reference_choices import reference_choices
from src.web.novel_library import usage, fingerprint, enrich_candidates


class ReferenceChoiceTests(unittest.TestCase):
    def test_ids_survive_new_evidence_but_distinguish_sources(self):
        first = {'source': {'text_sha256': 'first'}, 'style_observations': [{'rule': '以动作表现情绪', 'transfer_guidance': '用本书人物的动作表现迟疑'}]}
        original = reference_choices(first)['style_choices'][0]['choice_id']
        first['style_observations'][0]['evidence'] = [{'window_id': 'new'}]
        self.assertEqual(original, reference_choices(first)['style_choices'][0]['choice_id'])
        second = {**first, 'source': {'text_sha256': 'second'}}
        self.assertNotEqual(original, reference_choices(second)['style_choices'][0]['choice_id'])
        merged = enrich_candidates(first, second)
        self.assertEqual(len(merged['style_choices']), 2)
        self.assertEqual(merged['style_choices'][0]['choice_id'], original)

    def test_source_plot_is_not_inferred_as_transfer_instruction(self):
        data = {'conflict_patterns': [{'name': '原作专属事件', 'goal': '原作人物寻找某个物品', 'causal_link': '原作机关失控'}]}
        conflict = reference_choices(data)['conflict_choices'][0]
        self.assertTrue(conflict['requires_adaptation'])
        self.assertEqual(conflict['transfer_guidance'], '')
        self.assertEqual(reference_choices({})['style_choices'], [])

    def test_style_only_adoption_has_honest_category_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'book'; folder = Path(directory)/'library'
            (root/'learning/blueprints').mkdir(parents=True); folder.mkdir()
            data = {'source': {'text_sha256': 'hash'}, 'candidates': [], 'style_observations': [{'rule': '克制表达', 'transfer_guidance': '关键处以行动表现情绪'}]}
            choice = reference_choices(data)['style_choices'][0]['choice_id']
            def save(path, value): path.write_text(json.dumps(value), encoding='utf-8')
            save(folder/'candidates.json', data); save(root/'learning/candidates.json', data)
            save(root/'learning/library_refs.json', {'items': ['library']})
            self.assertEqual(usage(root, folder)['style_count'], 0)
            blueprint = {'sources': [data['source']], 'selected_candidate_ids': [], 'selected_style_ids': [choice]}
            save(root/'learning/blueprints/v0001.json', blueprint)
            save(root/'learning/active.json', {'version': 1, 'blueprint_path': 'learning/blueprints/v0001.json', 'blueprint_sha256': fingerprint(blueprint)})
            actual = usage(root, folder)
            self.assertEqual(actual['status'], 'adopted')
            self.assertEqual((actual['selected_count'], actual['style_count'], actual['conflict_count']), (0,1,0))
            self.assertEqual(actual['selected_style_ids'], [choice])


if __name__ == '__main__': unittest.main()
