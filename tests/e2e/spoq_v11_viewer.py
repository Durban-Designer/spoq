"""Exercise the installed viewer with real workflow writes and a real browser.

The separate loopback control server belongs to this test harness. Browser
requests go directly to the packaged read-only viewer without interception.
Human/skill fixtures are scripted adapters, never live model evaluations.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import platform
import queue
import statistics
import subprocess
import sys
import threading
import time
import unittest
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / 'code/apps/spoq-ui'
SENTINEL = '<img src=x onerror="globalThis.__spoqUnsafeArtifact=true">'


def driver_module():
    path = Path(__file__).with_name('spoq_v11_workflows.py')
    spec = importlib.util.spec_from_file_location('spoq_installed_workflows', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hardware():
    model = platform.processor()
    memory = None
    cpuinfo, meminfo = Path('/proc/cpuinfo'), Path('/proc/meminfo')
    if cpuinfo.exists():
        model = next((line.split(':', 1)[1].strip() for line in cpuinfo.read_text().splitlines()
                      if line.startswith('model name')), model)
    if meminfo.exists():
        memory = int(next(line.split()[1] for line in meminfo.read_text().splitlines()
                          if line.startswith('MemTotal:'))) * 1024
    return {'platform': platform.platform(), 'cpu_model': model, 'logical_cpus': os.cpu_count(),
            'memory_bytes': memory, 'outer_python': sys.version}


def unique_page(items, seen, *, limit=100):
    """Fail on duplicate identities, an oversized page, or changed page ordering."""
    if len(items) > limit:
        raise AssertionError('Response exceeded the requested page limit')
    ids = [item['id'] for item in items]
    if len(set(ids)) != len(ids) or seen.intersection(ids):
        raise AssertionError('Duplicate attempt identity across history pages')
    cursors = [item['cursor'] for item in items]
    if cursors != sorted(cursors):
        raise AssertionError('History page is not chronological')
    seen.update(ids)


def browser_verdict(stats, evidence):
    return (stats.get('expected') == 1 and stats.get('unexpected') == 0
            and stats.get('skipped') == 0 and stats.get('flaky') == 0
            and evidence.get('passed') is True and evidence.get('api_interception') is False)


class PageChecks(unittest.TestCase):
    def test_browser_gate_requires_one_actual_pass(self):
        stats = {'expected': 1, 'unexpected': 0, 'skipped': 0, 'flaky': 0}
        evidence = {'passed': True, 'api_interception': False}
        self.assertTrue(browser_verdict(stats, evidence))
        for key, value in [('expected', 0), ('unexpected', 1), ('skipped', 1), ('flaky', 1)]:
            self.assertFalse(browser_verdict({**stats, key: value}, evidence))

    def test_missing_or_intercepted_browser_evidence_is_not_success(self):
        stats = {'expected': 1, 'unexpected': 0, 'skipped': 0, 'flaky': 0}
        self.assertFalse(browser_verdict(stats, {}))
        self.assertFalse(browser_verdict(stats, {'passed': True, 'api_interception': True}))

    def test_valid_disjoint_pages(self):
        seen = set()
        unique_page([{'id': 'a', 'cursor': 4}, {'id': 'b', 'cursor': 8}], seen)
        unique_page([{'id': 'c', 'cursor': 1}], seen)
        self.assertEqual(seen, {'a', 'b', 'c'})

    def test_duplicate_in_page_or_prior_page_fails(self):
        with self.assertRaisesRegex(AssertionError, 'Duplicate'):
            unique_page([{'id': 'a', 'cursor': 1}, {'id': 'a', 'cursor': 2}], set())
        with self.assertRaisesRegex(AssertionError, 'Duplicate'):
            unique_page([{'id': 'a', 'cursor': 1}], {'a'})

    def test_page_bound_and_order_are_enforced(self):
        with self.assertRaisesRegex(AssertionError, 'limit'):
            unique_page([{'id': 'a', 'cursor': 1}], set(), limit=0)
        with self.assertRaisesRegex(AssertionError, 'chronological'):
            unique_page([{'id': 'a', 'cursor': 3}, {'id': 'b', 'cursor': 2}], set())


class ViewerProcess:
    def __init__(self, python, workspace, out, env):
        self.python, self.workspace, self.out, self.env = python, workspace, out, env
        self.port = 0
        self.process = None
        self.url = None
        self.starts = 0

    def start(self):
        self.starts += 1
        self.stderr = (self.out / f'viewer-{self.starts}.stderr').open('w')
        self.process = subprocess.Popen(
            [str(self.python), '-I', '-m', 'spoq_server', 'ui', '--root', str(self.workspace),
             '--port', str(self.port), '--no-open'], cwd=self.workspace,
            env={**self.env, 'PATH': ''}, stdout=subprocess.PIPE, stderr=self.stderr, text=True)
        messages = queue.Queue()
        threading.Thread(target=lambda: messages.put(self.process.stdout.readline()), daemon=True).start()
        try:
            line = messages.get(timeout=20)
            if not line:
                raise RuntimeError('Installed viewer did not print its launch envelope')
            launch = json.loads(line)
            self.port = urlsplit(launch['url']).port
            previous = self.url
            self.url = launch['url'].rstrip('/')
            if previous is not None and previous != self.url:
                raise AssertionError('Restart changed the viewer URL')
            return launch
        except BaseException:
            self.stop()
            raise

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            self.process.communicate(timeout=15)
            self.process = None
            self.stderr.close()


LOAD_FIXTURE = '''
import json,sys
from pathlib import Path
from spoq_server.v1.store import Store
from spoq_server.v1.db import transaction,now
from spoq_server.v1.workflows.recovery import WorkflowEngine
from spoq_server.v1.workflows.definitions import get_strategy
root=Path(sys.argv[1]);store=Store(root/'.spoq/spoq.db')
store.create('project_plan','load-plan','Artificial read-load fixture; not execution evidence')
store.create('feature','load-feature','Synthetic history only','load-plan')
definition=get_strategy('piqard').to_dict()
for phase in definition['phases']:phase['max_attempts']=100
engine=WorkflowEngine(store)
engine.start('load-run','load-feature',{'uncertainty':'high'},strategy='piqard',definition=definition)
phases=[p['id'] for p in definition['phases'] if p['kind']!='join']
with transaction(store.path,write=True) as db:
    spec=engine.repository._get(db,'load-run')['specification_hash']
    # Deliberately synthetic read-load rows, not claimed genuine transitions.
    for n in range(1000):
        db.execute('INSERT INTO workflow_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            ('load-attempt-'+str(n),'load-run',phases[n%len(phases)],n//len(phases)+1,'failed',
             'synthetic-read-fixture','synthetic-unused-lease',0,spec,
             json.dumps({'provenance':'artificial read-load; not execution evidence','padding':'x'*2000}),now(),now()))
    db.executemany('INSERT INTO events(node_id,kind,actor,payload,created_at) VALUES(?,?,?,?,?)',
        [('load-feature','workflow.fixture','synthetic-read-fixture',
          json.dumps({'run_id':'load-run','reason':'synthetic '+('x'*1000)}),now()) for _ in range(10000)])
    attempts=db.execute('SELECT COUNT(*) FROM workflow_attempts WHERE run_id=?',('load-run',)).fetchone()[0]
    events=db.execute("SELECT COUNT(*) FROM events WHERE kind='workflow.fixture'").fetchone()[0]
print(json.dumps({'synthetic_attempts':attempts,'synthetic_events':events,'execution_evidence':False}))
'''


class Controller:
    def __init__(self, artifact, out, python):
        self.out, self.lock = out, threading.Lock()
        self.driver = driver_module()
        self.python, self.prefix, origin = self.driver.install(artifact, out, python)
        self.runtime = self.driver.InstalledRuntime(self.python, out / 'workspace', out / 'commands',
                                                  expected_prefix=self.prefix)
        sentinel = SENTINEL

        class BrowserFixture(self.driver.WorkflowFixture):
            def revise(self):
                self.draft_revision += 1
                call = self.next('draft-' + str(self.draft_revision))
                assert call['phase_id'] == 'narrative'
                narrative = {name: ['Scripted ' + name + ' revision ' + str(self.draft_revision)]
                             for name in ('scope', 'decisions', 'assumptions', 'risks', 'acceptance_criteria')}
                narrative['scope'].append(sentinel)
                self.complete(call, 'drafted-' + str(self.draft_revision),
                              {'narrative_plan': {'content': narrative, 'source': 'scripted_browser_adapter'}})
                self.review = self.next('review-' + str(self.draft_revision))
                assert self.review['status'] == 'waiting_human'
                return self.review

        self.fixture = BrowserFixture(self.runtime, run_id='viewer', strategy='piqard')
        self.fixture.prepare()
        self.viewer = ViewerProcess(self.python, self.runtime.workspace, out, self.driver.clean_env())
        self.viewer.start()
        self.load_viewer = None
        self.report = {'artifact': str(artifact), 'artifact_sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
                       'installed_origin': origin, 'hardware': hardware(), 'actions': [],
                       'adapter': 'scripted skill and user fixtures; no live model inference',
                       'api_interception': False, 'viewer_server_PATH_empty': True}

    def capture(self, action):
        view = self.fixture.view()
        self.report['actions'].append({'action': action, 'cursor': view['snapshot']['cursor'],
                                       'status': view['snapshot']['run']['status'],
                                       'attempt_ids': [a['id'] for a in view['snapshot']['attempts']]})
        (self.out / (action + '-snapshot.json')).write_text(json.dumps(view, indent=2))
        return view

    def action(self, action):
        with self.lock:
            started = time.perf_counter()
            if action == 'view':
                result = self.capture(action)
            elif action == 'to_review':
                self.fixture.to_review()
                result = self.capture(action)
            elif action == 'reject':
                self.runtime.transport = 'mcp'
                self.fixture.reject_and_revise()
                result = self.capture(action)
            elif action == 'approve':
                self.fixture.approve()
                self.runtime.transport = 'cli'
                result = self.capture(action)
            elif action == 'deliver':
                self.report['delivery'] = self.fixture.deliver()
                result = self.capture(action)
            elif action == 'stop':
                self.viewer.stop()
                result = {'stopped': True, 'url': self.viewer.url}
            elif action == 'restart':
                self.viewer.start()
                result = {'url': self.viewer.url}
            elif action == 'load':
                result = self.read_load()
            else:
                raise ValueError('Unknown fixture action')
            self.report.setdefault('action_seconds', {})[action] = round(time.perf_counter() - started, 4)
            self.save()
            return result

    def fetch(self, url, budget):
        started = time.perf_counter()
        with urlopen(url, timeout=20) as response:
            body = response.read()
            assert len(body) == int(response.headers['Content-Length'])
        assert len(body) <= budget, 'HTTP response exceeded its test byte budget'
        return json.loads(body), {'bytes': len(body), 'seconds': round(time.perf_counter() - started, 6)}

    def read_load(self):
        workspace = self.out / 'artificial-read-load'
        workspace.mkdir()
        runtime = self.driver.InstalledRuntime(self.python, workspace, self.out / 'load-commands',
                                               expected_prefix=self.prefix)
        counts = runtime.installed(LOAD_FIXTURE, str(workspace), label='synthetic-read-load')
        assert counts['synthetic_attempts'] == 1000 and counts['synthetic_events'] == 10000
        self.load_viewer = ViewerProcess(self.python, workspace, self.out / 'load-commands', self.driver.clean_env())
        self.load_viewer.start()
        base = self.load_viewer.url + '/api/runs/load-run'
        snapshot, timing = self.fetch(base, 1_000_000)
        seen = set()
        unique_page(snapshot['attempts'], seen)
        history_timings = [timing]
        before = snapshot['attempt_cursor']
        while before is not None:
            page, timing = self.fetch(base + '/attempts?' + urlencode({'limit': 100, 'before': before}), 1_000_000)
            unique_page(page['items'], seen)
            history_timings.append(timing)
            next_cursor = page['pagination']['cursor']
            assert next_cursor is None or next_cursor < before
            before = next_cursor
        assert len(seen) == 1000
        after, sequences, synthetic_events, event_timings = 0, set(), 0, []
        while True:
            page, timing = self.fetch(base + '/events?' + urlencode({'limit': 100, 'after': after}), 150_000)
            assert not page['reset'] and len(page['events']) <= 100
            ids = [event['sequence'] for event in page['events']]
            assert ids == sorted(ids) and not sequences.intersection(ids)
            sequences.update(ids)
            synthetic_events += sum(event['kind'] == 'workflow.fixture' for event in page['events'])
            event_timings.append(timing)
            assert page['cursor'] >= after
            if not page['has_more']:
                break
            assert page['cursor'] > after
            after = page['cursor']
        assert synthetic_events == 10000

        def metrics(pages):
            return {'pages': len(pages), 'max_bytes': max(p['bytes'] for p in pages),
                    'median_seconds': statistics.median(p['seconds'] for p in pages),
                    'max_seconds': max(p['seconds'] for p in pages)}

        result = {**counts, 'viewer_url': self.load_viewer.url, 'cursor': snapshot['cursor'],
                  'initial_attempts': len(snapshot['attempts']), 'unique_attempts': len(seen),
                  'unique_event_ids': len(sequences), 'observed_synthetic_events': synthetic_events,
                  'history_http': metrics(history_timings), 'events_http': metrics(event_timings),
                  'interpretation': 'Artificial local read-load observations; not a production capacity benchmark.'}
        self.report['artificial_read_load'] = result
        return result

    def save(self):
        self.report['commands'] = self.runtime.commands
        (self.out / 'report.json').write_text(json.dumps(self.report, indent=2))

    def close(self):
        self.viewer.stop()
        if self.load_viewer:
            self.load_viewer.stop()
        self.save()


def control_server(controller):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024:
                    raise ValueError('Invalid test-control request size')
                action = json.loads(self.rfile.read(length))['action']
                value, status = controller.action(action), 200
            except Exception as exc:
                value, status = {'error': type(exc).__name__ + ': ' + str(exc)}, 500
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer(('127.0.0.1', 0), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--python', default='3.12')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(PageChecks)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if args.artifact is None or args.out is None:
        parser.error('--artifact and --out are required')
    artifact = args.artifact.resolve()
    out = args.out.resolve() / ('session-' + str(time.time_ns()))
    out.mkdir(parents=True)
    controller = Controller(artifact, out, args.python)
    server = control_server(controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {**os.environ, 'SPOQ_VIEWER_CONTROL_URL': 'http://127.0.0.1:' + str(server.server_port),
           'SPOQ_VIEWER_REAL_URL': controller.viewer.url, 'SPOQ_VIEWER_OUT': str(out)}
    started = time.perf_counter()
    try:
        result = subprocess.run(['node', str(FRONTEND / 'node_modules/@playwright/test/cli.js'),
                                 'test', 'strategy-viewer.test.ts'], cwd=FRONTEND, env=env,
                                capture_output=True, text=True, timeout=180)
        (out / 'playwright.stdout').write_text(result.stdout)
        (out / 'playwright.stderr').write_text(result.stderr)
        browser_evidence = {}
        stats = {}
        if (out / 'browser-evidence.json').is_file():
            browser_evidence = json.loads((out / 'browser-evidence.json').read_text())
        if (out / 'playwright-results.json').is_file():
            stats = json.loads((out / 'playwright-results.json').read_text())['stats']
        passed = result.returncode == 0 and browser_verdict(stats, browser_evidence)
        controller.report.update(passed=passed, browser_seconds=round(time.perf_counter() - started, 3),
                                 browser_evidence=browser_evidence, playwright_stats=stats)
        if not passed:
            print(result.stdout, file=sys.stderr)
            print(result.stderr, file=sys.stderr)
        print(json.dumps({'passed': passed, 'report': str(out / 'report.json'),
                          'artifact_sha256': controller.report['artifact_sha256'],
                          'browser_seconds': controller.report['browser_seconds']}))
        return 0 if passed else result.returncode or 1
    finally:
        server.shutdown()
        server.server_close()
        controller.close()


if __name__ == '__main__':
    raise SystemExit(main())
