import json
from pathlib import Path
import tempfile
import unittest

from src.web.novel_library import adopted_writing, enrich_candidates, fingerprint, usage


class NovelLibraryTests(unittest.TestCase):
    def test_multiple_library_sources_remain_adopted_after_new_attachment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'book'
            folder = Path(directory) / 'first'
            folder.mkdir(); (root / 'learning/blueprints').mkdir(parents=True)
            old = {'source': {'text_sha256': 'first'}, 'candidates': [{'candidate_id': 'old', 'mechanism': 'old'}]}
            new = {'source': {'text_sha256': 'second'}, 'candidates': [{'candidate_id': 'new', 'mechanism': 'new'}]}
            merged = enrich_candidates(old, new)
            self.assertEqual(len(merged['candidates']), 2)
            def save(path, value):
                path.write_text(json.dumps(value), encoding='utf-8')
            save(folder / 'candidates.json', old)
            save(root / 'learning/candidates.json', merged)
            save(root / 'learning/library_refs.json', {'items': ['first', 'second']})
            blueprint = {'source': new['source'], 'sources': [old['source'], new['source']], 'selected_candidate_ids': ['old', 'new']}
            save(root / 'learning/blueprints/v0002.json', blueprint)
            save(root / 'learning/active.json', {'version': 2, 'blueprint_path': 'learning/blueprints/v0002.json', 'blueprint_sha256': fingerprint(blueprint)})
            self.assertEqual(usage(root, folder)['status'], 'adopted')
            self.assertEqual(usage(root, folder)['selected_candidate_ids'], ['old'])
            save(root / 'learning/blueprints/v0002.json', {})
            with self.assertRaises(ValueError):
                adopted_writing(root)

    def test_upgrade_keeps_existing_candidate_ids_and_adds_analysis(self):
        old = {'candidates': [{'candidate_id': 'old-id', 'mechanism': '以代价引出新阻碍'}]}
        new = {'candidates': [{'candidate_id': 'new-id', 'mechanism': '以代价引出新阻碍'}], 'conflict_patterns': [{'name': '资源递进'}], 'style_observations': [{'rule': '短句推进'}]}
        upgraded = enrich_candidates(old, new)
        self.assertEqual(upgraded['candidates'][0]['candidate_id'], 'old-id')
        self.assertEqual(len(upgraded['candidates']), 1)
        self.assertEqual(upgraded['candidates_sha256'], fingerprint(upgraded['candidates']))
        self.assertEqual(upgraded['conflict_patterns'][0]['name'], new['conflict_patterns'][0]['name'])

    def test_usage_requires_real_valid_adoption_and_distinguishes_empty_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'book'
            folder = Path(directory) / 'library' / 'example'
            root.mkdir(); folder.mkdir(parents=True)
            def save(relative, value):
                file = root / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(json.dumps(value), encoding='utf-8')
            candidate = {'source': {'text_sha256': 'hash'}, 'candidates': [{'candidate_id': 'one'}]}
            (folder/'candidates.json').write_text(json.dumps(candidate), encoding='utf-8')
            self.assertEqual(usage(root, folder)['status'], 'available')
            save('learning/candidates.json', candidate)
            save('learning/library_refs.json', {'items': ['example']})
            self.assertEqual(usage(root, folder)['status'], 'attached')
            upgraded = {**candidate, 'candidates': candidate['candidates'] + [{'candidate_id': 'two'}]}
            (folder/'candidates.json').write_text(json.dumps(upgraded), encoding='utf-8')
            self.assertTrue(usage(root, folder)['update_available'])
            self.assertEqual(usage(root, folder)['status'], 'attached')
            blueprint = {'source': candidate['source'], 'selected_candidate_ids': ['one']}
            save('learning/blueprints/v0001.json', blueprint)
            save('learning/active.json', {'blueprint_path': 'learning/blueprints/v0001.json', 'blueprint_sha256': fingerprint(blueprint)})
            self.assertEqual(usage(root, folder)['status'], 'adopted')
            self.assertEqual(usage(root, folder)['selected_count'], 1)
            self.assertTrue(usage(root, folder)['update_available'])
            blueprint['selected_candidate_ids'] = []
            save('learning/blueprints/v0001.json', blueprint)
            save('learning/active.json', {'blueprint_path': 'learning/blueprints/v0001.json', 'blueprint_sha256': fingerprint(blueprint)})
            self.assertEqual(usage(root, folder)['status'], 'attached')


if __name__ == '__main__':
    unittest.main()
