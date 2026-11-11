import hashlib
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from spoq_server import __version__
from spoq_server.v1.workflows.recovery import WorkflowEngine
from spoq_server.v1.workflows.viewer import create_server, load_assets
from spoq_server.v1.workflows.artifacts import ArtifactRepository


@pytest.fixture
def assets(tmp_path):
    root = tmp_path / 'assets'
    root.mkdir()
    (root / 'index.html').write_text('<main>Packaged fixture UI</main>')
    (root / 'app.js').write_text('document.title="Fixture";')
    (root / 'manifest.json').write_text(json.dumps({'format': 'spoq-ui-assets-1', 'version': __version__,
        'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}}))
    return root


@pytest.fixture
def service(store, assets):
    engine = WorkflowEngine(store)
    engine.start('r', 'feature', {'uncertainty': 'low'}, strategy='classic')
    server = create_server(store.path.parent.parent, port=0, assets=assets)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, engine
    server.shutdown()
    server.server_close()
    thread.join(3)


def request(server, path='/', method='GET', headers=None):
    return urlopen(Request(server.url + path, method=method, headers=headers or {}), timeout=5)


def test_real_http_serves_verified_assets_and_the_same_committed_snapshot(service):
    server, engine = service
    with request(server) as response:
        assert b'Packaged fixture' in response.read()
        assert "script-src 'self'" in response.headers['Content-Security-Policy']
        assert response.headers['X-Frame-Options'] == 'DENY'
    with request(server, '/app.js') as response:
        assert 'javascript' in response.headers['Content-Type']
    with request(server, '/api/runs/r') as response:
        before = json.load(response)
    call = engine.next('r', 'orchestrator', key='next')
    with request(server, '/api/runs/r/events?after=' + str(before['cursor'])) as response:
        events = json.load(response)
    with request(server, '/api/runs/r') as response:
        after = json.load(response)
    assert events['events'] and after['cursor'] >= events['cursor']
    assert after['phases'][0]['attempt_id'] == call['attempt_id']
    assert 'token' not in json.dumps(after)


@pytest.mark.parametrize('headers', [{'Host': 'evil.example'}, {'Origin': 'https://evil.example'},
                                      {'Origin': 'null'}, {'Origin': 'http://localhost:1'}])
def test_unknown_host_or_origin_cannot_read_workspace(service, headers):
    with pytest.raises(HTTPError) as exc:
        request(service[0], '/api/runs', headers=headers)
    assert exc.value.code == 403


@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
def test_no_browser_write_endpoint_exists(service, method):
    before = service[1].get('r')['revision']
    with pytest.raises(HTTPError) as exc:
        request(service[0], '/api/runs/r', method=method)
    assert exc.value.code == 405 and service[1].get('r')['revision'] == before


@pytest.mark.parametrize('path', ['/%2e%2e/secret', '/%5c..%5csecret', '/api/runs/r?limit=1000',
                                   '/api/runs/r?limit=1&limit=2', '/api/runs/r?file=/etc/passwd',
                                   '/api/runs/r/artifacts/not-registered', '/not-declared.js'])
def test_paths_parameters_and_arbitrary_files_are_rejected(service, path):
    with pytest.raises(HTTPError) as exc:
        request(service[0], path)
    assert exc.value.code in {400, 403, 404}
    assert b'Traceback' not in exc.value.read()


@pytest.mark.parametrize('host', ['0.0.0.0', '192.0.2.1', 'example.com'])
def test_external_bind_is_rejected_before_start(store, assets, host):
    with pytest.raises(ValueError, match='loopback'):
        create_server(store.path.parent.parent, host=host, port=0, assets=assets)


def test_stale_missing_or_outside_assets_fail_without_serving_project_files(tmp_path, assets):
    with pytest.raises(ValueError, match='missing'):
        load_assets(tmp_path / 'missing')
    (assets / 'app.js').write_text('changed')
    with pytest.raises(ValueError, match='checksum mismatch'):
        load_assets(assets)


def test_registered_html_is_data_and_unregistered_files_are_never_rendered(service):
    server, engine = service
    call = engine.next('r', 'orchestrator', key='claim')
    content = '<script>window.spoq_attack=true</script><img src=x onerror=alert(1)>'
    artifact = ArtifactRepository(engine.repository).register('r', call['attempt_id'], 'note', content,
        'orchestrator', key='note', expected_revision=engine.get('r')['revision'])
    with request(server, '/api/runs/r/artifacts/' + artifact['id']) as response:
        assert response.headers['Content-Type'].startswith('application/json')
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        result = json.load(response)
        assert result['content'] == content and result['render_as'] == 'text'


def test_asset_replacement_after_start_requires_restart_instead_of_mixed_bundle(service, assets):
    (assets / 'app.js').write_text('replaced after startup')
    with pytest.raises(HTTPError) as exc:
        request(service[0], '/app.js')
    assert exc.value.code == 400
    assert b'restart' in exc.value.read()


def test_head_returns_headers_without_body(service):
    with request(service[0], '/', method='HEAD') as response:
        assert int(response.headers['Content-Length']) > 0 and response.read() == b''


def test_ui_can_show_an_empty_workspace_without_initializing_a_database(tmp_path, assets):
    workspace = tmp_path / 'empty'
    server = create_server(workspace, port=0, assets=assets)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with request(server, '/api/runs') as response:
            assert json.load(response)['runs'] == []
        assert not workspace.exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
