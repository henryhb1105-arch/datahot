import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
from content_metadata import repair_content_metadata


class ContentMetadataTests(unittest.TestCase):
    def setUp(self):
        self.event = json.loads((Path(__file__).parent / 'fixtures/period-metadata.json').read_text())

    def test_historical_merge_repaired_without_changing_body_or_sources(self):
        before = copy.deepcopy(self.event)
        self.assertEqual(repair_content_metadata([self.event]), 1)
        self.assertIn('历史记录关联', self.event['zh_summary'])
        self.assertNotIn('10.32', self.event['zh_summary'])
        self.assertNotIn('版本说明', self.event['reason'])
        for key in before.keys() - {'zh_summary', 'reason'}:
            self.assertEqual(self.event[key], before[key], key)
        self.assertEqual(repair_content_metadata([self.event]), 0)

    def test_new_body_source_or_editorial_summary_is_not_overridden(self):
        for field, value in [('event_id', 'different'), ('source_content_hash', 'new'),
                             ('full_zh', 'Revised body'), ('zh_summary', 'Reviewed new summary')]:
            with self.subTest(field=field):
                event = {**copy.deepcopy(self.event), field: value}
                before = copy.deepcopy(event)
                self.assertEqual(repair_content_metadata([event]), 0)
                self.assertEqual(event, before)
        self.event['items'][0]['link'] = 'https://docs.snowflake.com/en/release-notes/2026/10_32'
        self.assertEqual(repair_content_metadata([self.event]), 0)

    def test_remerged_stale_metadata_is_repaired_again(self):
        stale = {key: self.event[key] for key in ('zh_summary', 'reason')}
        repair_content_metadata([self.event])
        corrected = copy.deepcopy(self.event)
        self.event.update(stale)
        self.assertEqual(repair_content_metadata([self.event]), 1)
        self.assertEqual(self.event, corrected)

    def test_missing_data_is_safe(self):
        self.assertEqual(repair_content_metadata([{}, {'event_id': '113da8bd65f9'}]), 0)


if __name__ == '__main__':
    unittest.main()
