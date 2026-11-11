"""Loopback-only, read-only delivery of packaged assets and committed projections.

Requests never select project files. Artifact content comes from registered rows
and is rendered by the frontend as escaped text, without active Markdown/HTML.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import mimetypes
import re
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from spoq_server import __version__
from ..migration import database_path
from .queries import ReadModel


def _asset_path(root, relative):
    if (not isinstance(relative, str) or not relative or '\\' in relative or '\x00' in relative
            or any(p in {'', '.', '..'} for p in relative.split('/'))):
        raise ValueError('Invalid static asset path')
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Static asset is outside the declared package')
    return path


def load_assets(root=None):
    root = Path(root) if root is not None else Path(str(files('spoq_server') / 'data/ui'))
    root = root.resolve()
    manifest_path = root / 'manifest.json'
    if not manifest_path.is_file() or manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError('Packaged UI assets are missing. Install a built wheel, or run the contributor UI build.')
    manifest = json.loads(manifest_path.read_text())
    if (not isinstance(manifest, dict) or manifest.get('format') != 'spoq-ui-assets-1'
            or manifest.get('version') != __version__ or not isinstance(manifest.get('files'), dict)
            or 'index.html' not in manifest['files']):
        raise ValueError('UI asset manifest does not match this SPOQ version')
    for name, digest in manifest['files'].items():
        if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
            raise ValueError('Invalid UI asset checksum')
        path = _asset_path(root, name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Packaged UI asset checksum mismatch: ' + name)
    return root, manifest


def create_server(root, *, host='127.0.0.1', port=8765, assets=None):
    root = Path(root).expanduser().resolve()
    if not isinstance(host, str) or '%' in host or type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('A loopback host and valid port are required')
    address = None
    if host != 'localhost':
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError('Viewer binds only to loopback addresses') from exc
        if not address.is_loopback:
            raise ValueError('Viewer binds only to loopback addresses')
    assets_root, manifest = load_assets(assets)
    model = ReadModel(database_path(root))

    class Handler(BaseHTTPRequestHandler):
        server_version = 'SPOQ-local'
        sys_version = ''

        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def _reply(self, status, body, content_type='application/json; charset=utf-8', *, head=False, cache=False):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            try:
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'public, max-age=31536000, immutable' if cache else 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('X-Frame-Options', 'DENY')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
                self.end_headers()
                if not head and self.command != 'HEAD':
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                return  # A disconnected browser is not a new domain event or failed transition.

        def _trusted(self):
            host_header = self.headers.get('Host', '').lower()
            origin = self.headers.get('Origin')
            allowed = self.server.allowed_hosts
            if host_header not in allowed or origin is not None and origin.lower() not in {'http://' + h for h in allowed}:
                self._reply(403, {'error': 'Unknown host or origin'})
                return False
            return True

        def do_GET(self, *, head=False):
            if not self._trusted():
                return
            try:
                if len(self.path) > 8192:
                    self._reply(414, {'error': 'Request URL is too long'}, head=head)
                    return
                url = urlsplit(self.path)
                if url.scheme or url.netloc or '\\' in url.path:
                    raise ValueError('Only local origin-form paths are supported')
                parts = [unquote(p, errors='strict') for p in url.path.split('/')[1:]]
                if any(p in {'.', '..'} or '\x00' in p or '\\' in p for p in parts):
                    self._reply(403, {'error': 'Path traversal is not allowed'}, head=head)
                    return
                parameters = parse_qs(url.query, keep_blank_values=True)
                if any(len(value) != 1 for value in parameters.values()):
                    raise ValueError('Duplicate query parameters are not supported')

                def params(allowed):
                    if set(parameters) - set(allowed):
                        raise ValueError('Unknown query parameter')
                    return {k: v[0] for k, v in parameters.items()}

                def integer(value, default):
                    return default if value is None else int(value)

                if parts == ['api', 'health']:
                    params(())
                    self._reply(200, {'status': 'ok', 'version': __version__, 'project_root': str(root),
                                      'read_only': True, 'engine_launches_models': False}, head=head)
                    return
                if parts == ['api', 'runs']:
                    p = params(('scope', 'limit', 'after'))
                    result = model.runs(p.get('scope', ''), integer(p.get('limit'), 100), p.get('after', ''))
                elif len(parts) >= 3 and parts[:2] == ['api', 'runs']:
                    run = parts[2]
                    if len(parts) == 3:
                        p = params(('limit', 'before'))
                        result = model.snapshot(run, integer(p.get('limit'), 100), integer(p.get('before'), None))
                    elif len(parts) == 4 and parts[3] == 'events':
                        p = params(('after', 'limit'))
                        result = model.events(run, integer(p.get('after'), 0), integer(p.get('limit'), 100))
                    elif len(parts) == 4 and parts[3] == 'work':
                        p = params(('after', 'limit'))
                        result = model.work(run, p.get('after', ''), integer(p.get('limit'), 500))
                    elif len(parts) == 4 and parts[3] in {'attempts', 'artifacts', 'decisions', 'participants'}:
                        p = params(('before', 'limit'))
                        result = model.history(run, parts[3], integer(p.get('before'), None), integer(p.get('limit'), 100))
                    elif len(parts) == 5 and parts[3] in {'artifacts', 'attempts', 'nodes'}:
                        params(())
                        getter = {'artifacts': model.artifact, 'attempts': model.attempt, 'nodes': model.node}[parts[3]]
                        result = getter(run, parts[4])
                    else:
                        self._reply(404, {'error': 'Unknown read endpoint'}, head=head)
                        return
                elif parts and parts[0] == 'api':
                    self._reply(404, {'error': 'Unknown read endpoint'}, head=head)
                    return
                else:
                    params(('run',))
                    relative = 'index.html' if parts == [''] else '/'.join(parts)
                    if relative != 'manifest.json' and relative not in manifest['files']:
                        self._reply(404, {'error': 'Unknown static asset'}, head=head)
                        return
                    path = _asset_path(assets_root, relative)
                    body = json.dumps(manifest).encode() if relative == 'manifest.json' else path.read_bytes()
                    if relative != 'manifest.json' and hashlib.sha256(body).hexdigest() != manifest['files'][relative]:
                        raise ValueError('Packaged UI assets changed; restart the viewer')
                    mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
                    if path.suffix in {'.js', '.mjs'}:
                        mime = 'text/javascript'
                    if mime.startswith('text/') or mime == 'application/json':
                        mime += '; charset=utf-8'
                    self._reply(200, body, mime, head=head, cache=relative.startswith('assets/'))
                    return
                self._reply(200, result, head=head)
            except (ValueError, OSError) as exc:
                self._reply(400, {'error': str(exc)}, head=head)
            except Exception:
                self._reply(500, {'error': 'Unable to read committed workspace state'}, head=head)

        def do_HEAD(self):
            self.do_GET(head=True)

        def _write_refused(self):
            if self._trusted():
                self._reply(405, {'error': 'The local viewer is read-only'})
        do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _write_refused

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        if address is not None and address.version == 6:
            address_family = socket.AF_INET6

    server = Server((host, port), Handler)
    actual_port = server.server_address[1]
    server.allowed_hosts = {f'127.0.0.1:{actual_port}', f'localhost:{actual_port}', f'[::1]:{actual_port}'}
    server.allowed_hosts.add(('[' + host + ']' if ':' in host else host) + ':' + str(actual_port))
    server.url = 'http://' + ('[' + host + ']' if ':' in host else host) + ':' + str(actual_port)
    return server


def serve(root, *, host='127.0.0.1', port=8765, open_browser=True, run_id=None):
    from urllib.parse import quote
    server = create_server(root, host=host, port=port)
    url = server.url + ('/?run=' + quote(run_id, safe='') if run_id else '/')
    print(json.dumps({'url': url, 'project_root': str(Path(root).resolve()), 'read_only': True}), flush=True)
    if open_browser:
        opener = threading.Timer(.1, webbrowser.open, args=(url,))
        opener.daemon = True
        opener.start()
    try:
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
