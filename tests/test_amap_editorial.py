import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))
from import_manual_batch import import_batch, stable_id, validate_batch
from editorial_picks import load_editorial_picks

BATCH = ROOT / 'pipeline/manual_batches/2026-11-20-amap-data-agent.json'
URLS = ['https://mp.weixin.qq.com/s/FAGAjEXd-dggWfBR-A0LLg',
        'https://mp.weixin.qq.com/s/VEqScV_gXl5ZoOczul6nwA']

class AmapEditorialTests(unittest.TestCase):
    def test_exact_sources_honest_unknown_metadata_and_series_order(self):
        records = validate_batch(json.loads(BATCH.read_text()))
        self.assertEqual([r['source_url'] for r in records], URLS)
        for r in records:
            self.assertEqual(r['published'], '')
            self.assertEqual(r['source_date_label'], '原始发布日期未核验')
            self.assertIn('正文尚未核验', r['zh_summary'])
            self.assertEqual(r['content_mode'], 'editorial_excerpt')
        picks = {r['event_id']:r for r in load_editorial_picks()}
        ordered = sorted([picks[stable_id(url)] for url in URLS],
                         key=lambda r: (r['curated_at'], r['event_id']), reverse=True)
        self.assertEqual([r['source_url'] for r in ordered], URLS)

    def test_import_is_idempotent_and_preserves_existing_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'latest.json'
            existing = {'event_id':'existing', 'zh_title':'已有条目', 'items':[]}
            path.write_text(json.dumps({'events':[existing], 'generated_at':''}))
            self.assertEqual(import_batch(BATCH, path)['added'], 2)
            self.assertEqual(import_batch(BATCH, path)['added'], 0)
            events = json.loads(path.read_text())['events']
            self.assertEqual(len(events), 3)
            self.assertIn(existing, events)
            new = [e for e in events if e['event_id'] != 'existing']
            self.assertTrue(all(e['editorial_pick'] for e in new))
            self.assertEqual({e['items'][0]['link'] for e in new}, set(URLS))
