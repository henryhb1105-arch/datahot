"""One-off, bounded read-only research. Never emits credentials or retries X calls."""
import base64
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlencode, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

REPO = 'henryhb1105-arch/datahot'
BRANCH = 'codex/issue-204-x-review-2026'
LEDGER = 'research/x-review-2026/budget.json'
ROOT = Path(__file__).parent
OUT = ROOT / 'output'
MAX_RESERVED = 300  # This run is limited to $1.50 at $0.005/post.

class Stop(Exception):
    pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def request(method, url, headers, data=None):
    try:
        req = Request(url, data=data, headers=headers, method=method)
        with build_opener(NoRedirect).open(req, timeout=30) as r:
            body = r.read(4_000_001)
            if len(body) > 4_000_000:
                raise Stop('oversize_response')
            return json.loads(body)
    except HTTPError as e:
        raise Stop('http_' + str(e.code)) from None
    except Stop:
        raise
    except Exception:
        raise Stop('uncertain_network_or_response') from None

class Ledger:
    def __init__(self):
        token = os.environ.get('GITHUB_TOKEN')
        if not token:
            raise Stop('missing_github_token')
        self.headers = {'Authorization': 'Bearer ' + token,
                        'Accept': 'application/vnd.github+json',
                        'Content-Type': 'application/json'}
        self.url = 'https://api.github.com/repos/' + REPO + '/contents/' + LEDGER

    def load(self):
        r = request('GET', self.url + '?ref=' + quote(BRANCH, safe='') + '&request_id=' + str(time.time_ns()),
                    {**self.headers, 'Cache-Control': 'no-cache'})
        return json.loads(base64.b64decode(r['content'])), r['sha']

    def save(self, state, sha):
        payload = {'branch': BRANCH, 'sha': sha,
                   'message': 'Record bounded X research request',
                   'content': base64.b64encode(json.dumps(state, indent=2).encode()).decode()}
        request('PUT', self.url, self.headers, json.dumps(payload).encode())

    def reserve(self, query_id):
        state, sha = self.load()
        if state['closed'] or query_id in state['requests']:
            raise Stop('closed_or_previously_reserved')
        reserved = sum(v['reserved_posts'] for v in state['requests'].values())
        if reserved + 10 > MAX_RESERVED:
            raise Stop('budget_limit')
        state['requests'][query_id] = {'reserved_posts': 10, 'status': 'reserved',
                                      'run_id': os.environ.get('GITHUB_RUN_ID')}
        self.save(state, sha)
        time.sleep(2)  # Allow the branch ref read to observe its preceding commit.

    def finish(self, query_id, result):
        state, sha = self.load()
        state['requests'][query_id].update(result)
        self.save(state, sha)
        time.sleep(2)

def search_params(q):
    if not q['start_time'].startswith('2026-') or q['end_time'] > '2026-09-12T04:50:00Z':
        raise Stop('invalid_time_window')
    return {'query': q['query'], 'start_time': q['start_time'], 'end_time': q['end_time'],
            'max_results': 10, 'sort_order': 'relevancy',
            'tweet.fields': 'created_at,entities,author_id,public_metrics,note_tweet'}

def app_token():
    existing = os.environ.get('X_BEARER_TOKEN')
    if existing:
        return existing
    key, secret = os.environ.get('X_API_KEY'), os.environ.get('X_API_SECRET')
    if not key or not secret:
        raise Stop('missing_x_app_credentials')
    basic = base64.b64encode((quote(key, safe='') + ':' + quote(secret, safe='')).encode()).decode()
    r = request('POST', 'https://api.x.com/oauth2/token',
                {'Authorization': 'Basic ' + basic, 'Content-Type': 'application/x-www-form-urlencoded'},
                b'grant_type=client_credentials')
    if r.get('token_type') != 'bearer' or not r.get('access_token'):
        raise Stop('invalid_app_token_response')
    return r['access_token']

def main():
    OUT.mkdir(exist_ok=True)
    report = {'status': 'starting', 'responses': [], 'actual_invoice_verified': False,
              'price_usd_per_returned_post': 0.005, 'attempted_post_capacity': 0}
    try:
        if os.environ.get('GITHUB_REF') != 'refs/heads/' + BRANCH:
            raise Stop('wrong_branch')
        if os.environ.get('GITHUB_RUN_ATTEMPT') != '1':
            raise Stop('reruns_disabled')
        queries = json.loads((ROOT / 'queries.json').read_text())
        if len(queries) > 30 or len({q['id'] for q in queries}) != len(queries):
            raise Stop('invalid_query_plan')
        for q in queries:
            search_params(q)
        ledger = Ledger()
        state, _ = ledger.load()
        if state['closed'] or any(v['status'] != 'complete' for v in state['requests'].values()):
            raise Stop('closed_or_uncertain_previous_request')
        queries = [q for q in queries if q['id'] not in state['requests']]
        token = app_token()
        for q in queries:
            ledger.reserve(q['id'])
            report['attempted_post_capacity'] += 10
            try:
                r = request('GET', 'https://api.x.com/2/tweets/search/all?' + urlencode(search_params(q)),
                            {'Authorization': 'Bearer ' + token})
                posts = r.get('data', [])
                if r.get('errors') or not isinstance(posts, list) or len(posts) > 10 or r.get('includes'):
                    raise Stop('invalid_or_partial_response')
                (OUT / (q['id'] + '.json')).write_text(json.dumps({'query': q, 'response': r}, ensure_ascii=False, indent=2))
                result = {'status': 'complete', 'returned_posts': len(posts),
                          'more_results': bool(r.get('meta', {}).get('next_token'))}
                ledger.finish(q['id'], result)
                report['responses'].append({'query_id': q['id'], **result})
                print(json.dumps(report['responses'][-1]), flush=True)
            except Stop as e:
                ledger.finish(q['id'], {'status': 'stopped', 'reason': str(e)})
                raise
        report['status'] = 'complete'
    except Stop as e:
        report['status'] = 'stopped'
        report['reason'] = str(e)
    except Exception:
        report['status'] = 'stopped'
        report['reason'] = 'unexpected_failure_no_retry'
    finally:
        report['returned_posts'] = sum(r['returned_posts'] for r in report['responses'])
        report['estimated_usd'] = round(report['returned_posts'] * 0.005, 3)
        report['reserved_usd'] = round(report['attempted_post_capacity'] * 0.005, 3)
        (OUT / 'summary.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)

if __name__ == '__main__':
    main()
