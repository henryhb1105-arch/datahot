'use strict';
const assert = require('node:assert/strict');
const forMe = require('../pipeline/assets/for-me.js');
const reading = require('../pipeline/assets/reading-profile.js');
const affinity = require('../pipeline/assets/content-affinity.js');

const PRIMARY_CARDS = '#fmMustList .fm-signal:visible, #fmFeedList .fm-signal:visible, #fmWorkList .fm-signal:visible';
const UNREAD_CARDS = PRIMARY_CARDS + ', #fmDiscoveryList .fm-signal:visible';

function priorityExpectation(events, snapshot) {
  const now = snapshot.now;
  const state = forMe.normalizeState(snapshot.state || {});
  state.reading = reading.normalize(snapshot.reading || {}, now);
  state.favorites = snapshot.favorites || [];
  state.feedback = forMe.normalizeFeedbackStore(snapshot.feedback || {});
  state.affinity = affinity.profile(events, state, now);
  const personalized = state.tasks.length || state.topics.length || state.vendors.length
    || state.products.length || Object.keys(state.affinity.matches).length;
  // Check the eligibility contract independently of sections(): a live-data
  // drought must not be "fixed" by promoting pending, unverified or read items.
  const candidates = forMe.rankEvents(events, state, now, false).filter(event => {
    const inferred = affinity.match(event, state.affinity).length > 0;
    return (!personalized || inferred || forMe.matchReasons(event, state).length > 0)
      && !forMe.isRead(event, state) && event.enrichment_status !== 'pending'
      && event.enrichment_status !== 'rejected' && !event.promotion_suppressed
      && event.body_review_required !== true && String(event.zh_summary || '').trim()
      && (Date.parse(event.published || event.first_seen) >= now - 7 * 86400000 || inferred);
  });
  const grouped = forMe.sections(events, state, now, snapshot.baseline === 'first' ? '' : snapshot.baseline);
  const feed = personalized ? grouped.updates : grouped.ranked.filter(event => !forMe.isRead(event,state)
    && !candidates.slice(0,3).some(candidate => candidate.event_id === event.event_id)).slice(0,12);
  return {candidateIds:candidates.map(event => event.event_id), mustIds:candidates.slice(0,3).map(event => event.event_id),
    feed:feed.length, work:personalized ? grouped.work.length : 0, discovery:grouped.discovery.length};
}

async function assertPriorityState(page, events) {
  const snapshot = await page.evaluate(() => {
    const read = key => JSON.parse(localStorage.getItem(key) || 'null');
    return {now:Date.now(), state:read('dh_for_me_v1'), reading:read('dh_reading_v1'),
      feedback:read('dh_content_feedback_v1'), favorites:window.DataHotFavorites
        ? window.DataHotFavorites.readRecords(localStorage).map(record => record.event_id)
        : read('dh_favs') || [],
      baseline:sessionStorage.getItem('dh_for_me_session_baseline_v1')};
  });
  const expected = priorityExpectation(events, snapshot);
  const actual = await page.locator('#fmMustList .fm-signal').evaluateAll(nodes => nodes.map(node => node.dataset.eventId));
  assert.deepEqual(actual, expected.mustIds, 'Priority cards must match eligible unread reviewed candidates');
  assert.equal(await page.locator('#fmMust').isVisible(), expected.mustIds.length > 0,
    'No reviewed candidates means an honestly hidden priority section');
  return expected;
}

module.exports = {PRIMARY_CARDS, UNREAD_CARDS, priorityExpectation, assertPriorityState};
