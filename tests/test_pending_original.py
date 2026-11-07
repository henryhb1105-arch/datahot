import copy
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
import run_update
from candidate_cache import CandidateCache
from lite_data import is_list_eligible, lite_event, rank_hot_events
from pending_original import is_pending_original

NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)

def item():
    return dict(id='pending-a', title='SQL analytics on a data platform',
                zh_title='SQL analytics on a data platform', summary='Original source summary',
                zh_summary='Original source summary', source='Databricks Blog',
                source_tier='official_high', link='https://www.databricks.com/blog/test',
                category='platform', category_label='AI 数据平台', reason='',
                published=NOW.isoformat(), ingested_at=NOW.isoformat(), _pub_dt=NOW,
                importance=50, heat=50, article_text='', vendors=['Databricks'])

def event():
    value=run_update.make_event(item())
    value['enrichment_status']='pending'
    return value

class PendingOriginalTests(unittest.TestCase):
    def test_failure_and_no_config_keep_source_without_fabricated_metadata(self):
        for cfg in [('', '', ''), ('key', 'base', 'model')]:
            with self.subTest(cfg=cfg), tempfile.TemporaryDirectory() as temp, patch.object(
                run_update, 'CANDIDATE_CACHE', CandidateCache(Path(temp)/'cache.json')
            ), patch.object(run_update, 'llm_chat', side_effect=RuntimeError('provider unavailable')):
                original=item()
                result=run_update.llm_enrich([original], cfg, generate_fulltext=False)
                self.assertEqual(len(result),1)
                output=run_update.make_event(result[0])
                self.assertTrue(is_pending_original(output))
                self.assertTrue(is_list_eligible(output))
                self.assertEqual(output['reason'],'')
                self.assertEqual(output['zh_summary'],original['summary'])
                self.assertEqual(output['published'], original['published'])
                self.assertEqual(lite_event(output)['enrichment_status'],'pending')

    def test_review_required_sources_still_fail_closed(self):
        for tier in ['low_precision','community_targeted','media_low']:
            with self.subTest(tier=tier):
                candidate=item();candidate['source_tier']=tier
                self.assertEqual(run_update.llm_enrich([candidate], ('','','')),[])

    def test_pending_cannot_bypass_source_url_or_quality_policy(self):
        for change in ['unknown','unsafe','release','rejected','empty']:
            e=event()
            if change=='unknown':e['items'][0]['source']='Unconfigured publisher'
            if change=='unsafe':e['items'][0]['link']='javascript:alert(1)'
            if change=='release':e['items'][0]['link']='https://www.databricks.com/release-notes/2026'
            if change=='rejected':e['enrichment_status']='rejected'
            if change=='empty':e['zh_summary']=''
            self.assertFalse(is_list_eligible(e), change)
            self.assertTrue(lite_event(e)['promotion_suppressed'], change)

    def test_pending_excluded_from_editorial_feeds(self):
        from agent_feed import build_agent_feed
        from feed import build_atom_feed
        e=event()
        self.assertEqual(build_agent_feed([e],NOW.isoformat(),site_base='https://datahot.xiahongbin.com')['events'],[])
        self.assertNotIn(b'<entry>',build_atom_feed([e],NOW.isoformat(),site_base='https://datahot.xiahongbin.com'))

    def test_pending_not_promoted_to_hot_rank(self):
        self.assertEqual(rank_hot_events([event()], reference_time=NOW),[])

    def test_legacy_migration_requires_evidence_and_preserves_data(self):
        e=event();e.pop('enrichment_status')
        self.assertFalse(is_pending_original(e))
        e['content_parse']={'metadata_translation':{'status':'provider_error'}}
        before=copy.deepcopy(e)
        self.assertTrue(is_pending_original(e));self.assertTrue(is_list_eligible(e))
        self.assertEqual(e,before)
        e['reason']='已审核';self.assertFalse(is_pending_original(e))

    def test_pending_chinese_metadata_is_retried_and_recovers(self):
        e=event();e['zh_title']='数据平台原文';e['zh_summary']='中文原文摘要'
        answer={'zh_title':'数据平台更新','zh_summary':'忠实中文摘要','reason':'已审核推荐理由','relevant':True}
        with patch.object(run_update,'llm_chat', return_value=answer), patch.object(run_update.LLM_USAGE,'can_call', return_value=True):
            result=run_update.backfill_event_metadata([e],('key','base','model'),now=NOW,limit=1)
        self.assertEqual(result['complete'],1)
        self.assertEqual(e['enrichment_status'],'complete')
        self.assertFalse(is_pending_original(e))
        self.assertEqual(e['reason'],'已审核推荐理由')

    def test_recovered_rejection_hides_without_deleting_original(self):
        e=event();before=copy.deepcopy(e)
        with patch.object(run_update,'llm_chat',return_value={'relevant':False}), patch.object(run_update.LLM_USAGE,'can_call',return_value=True):
            run_update.backfill_event_metadata([e],('key','base','model'),now=NOW,limit=1)
        self.assertEqual(e['enrichment_status'],'rejected')
        self.assertFalse(is_list_eligible(e))
        self.assertEqual(e['items'],before['items'])
        self.assertEqual(e['zh_summary'],before['zh_summary'])

    def test_empty_or_incomplete_model_responses_stay_pending(self):
        for answer in [{}, {'relevant': True}, {'zh_title': 'English', 'zh_summary': 'English summary'}]:
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as temp, patch.object(run_update, 'CANDIDATE_CACHE', CandidateCache(Path(temp)/'cache.json')), patch.object(run_update,'llm_chat',return_value=answer):
                result=run_update.llm_enrich([item()],('key','base','model'),generate_fulltext=False)
                self.assertEqual(result[0]['enrichment_status'],'pending')
                self.assertTrue(is_list_eligible(run_update.make_event(result[0])))

    def test_pending_merge_cannot_raise_reviewed_score(self):
        e=event();e.update(enrichment_status='complete',zh_title='已审核标题',zh_summary='已审核摘要',reason='理由',importance=20,quality_score=20)
        candidate=item();candidate['enrichment_status']='pending'
        run_update.merge_into(e,candidate)
        self.assertEqual(e['importance'],20)
        self.assertFalse(is_list_eligible(e))

    def test_failed_recovery_is_transactional(self):
        e=event();before=copy.deepcopy(e)
        answer={'zh_title':'数据平台更新','zh_summary':'忠实中文摘要','reason':'理由','vendors':7}
        with patch.object(run_update,'llm_chat',return_value=answer), patch.object(run_update.LLM_USAGE,'can_call',return_value=True):
            report=run_update.backfill_event_metadata([e],('key','base','model'),now=NOW,limit=1)
        self.assertEqual(report['failed'],1)
        for field in ['enrichment_status','zh_title','zh_summary','reason']:
            self.assertEqual(e[field],before[field])

    def test_merge_preserves_completed_metadata_and_upgrades_pending(self):
        e=event();e.update(enrichment_status='complete', zh_title='已审核标题', zh_summary='已审核摘要', reason='已审核理由')
        pending=item();pending.update(enrichment_status='pending',zh_summary='long raw source summary '*100)
        run_update.merge_into(e,pending)
        self.assertEqual(e['zh_summary'],'已审核摘要')
        e=event();complete=item();complete.update(enrichment_status='complete',zh_title='已审核标题',zh_summary='已审核摘要',reason='理由')
        run_update.merge_into(e,complete)
        self.assertEqual(e['enrichment_status'],'complete')
        self.assertEqual(e['zh_title'],'已审核标题')

    def test_unknown_pending_does_not_fall_through_chinese_editorial_gate(self):
        e=event();e['items'][0]['source']='Unknown';e['zh_title']='中文原文';e['zh_summary']='中文摘要'
        self.assertFalse(is_list_eligible(e))

    def test_old_pending_is_not_starved_by_recent_retries(self):
        old=event();old['event_id']='old';old['published']=(NOW-timedelta(days=40)).isoformat()
        recent=event();recent['content_parse']={'metadata_translation':{'attempted_at':(NOW-timedelta(hours=7)).isoformat(),'status':'provider_error','policy_version':run_update.METADATA_TRANSLATION_POLICY_VERSION}}
        answer={'zh_title':'数据平台更新','zh_summary':'忠实中文摘要','relevant':True}
        with patch.object(run_update,'llm_chat',return_value=answer) as call, patch.object(run_update.LLM_USAGE,'can_call',return_value=True):
            run_update.backfill_event_metadata([recent,old],('key','base','model'),now=NOW,limit=1)
        self.assertEqual(call.call_args.kwargs['item_id'],'old')

if __name__=='__main__':unittest.main()
