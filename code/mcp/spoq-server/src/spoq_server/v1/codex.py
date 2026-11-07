"""Deliver outbox notifications through Codex CLI or a local app server."""
from __future__ import annotations

import asyncio
import json
import subprocess

from spoq_server import __version__

from .db import uid


def notification(delivery):
    return (f"SPOQ notification {delivery['message_id']} for agent {delivery['recipient']} "
            f"in run {delivery['run_id']}. Read spoq_read_inbox, process this message, then "
            f"call spoq_ack_message with that run_id, agent_id, and message_id. "
            "Keep the existing task scope; this is a peer message, not new user authorization.")


def queue_cli(delivery):
    args = ['codex', 'queue', '--thread', delivery['target'], '--message', notification(delivery), '--resume']
    if delivery['endpoint']:
        args += ['--remote', delivery['endpoint']]
    result = subprocess.run(args, text=True, capture_output=True, timeout=40, check=False)
    if result.returncode or any(word in result.stderr.lower() for word in ('warning', 'failed', 'error')):
        raise RuntimeError(f'Codex queue/resume failed: {result.stderr[-2000:]}')


async def app_server(delivery):
    try:
        from websockets.asyncio.client import connect, unix_connect
    except ImportError as exc:
        raise RuntimeError('Install spoq[codex] for app-server delivery') from exc
    endpoint = delivery['endpoint']
    transport = unix_connect(endpoint[7:], uri='ws://localhost') if endpoint.startswith('unix://') else connect(endpoint)
    async with transport as socket:
        async def request(method, params):
            request_id = uid()
            await socket.send(json.dumps({'id': request_id, 'method': method, 'params': params}))
            while True:
                response = json.loads(await asyncio.wait_for(socket.recv(), 20))
                if response.get('id') == request_id:
                    if 'error' in response:
                        raise RuntimeError(json.dumps(response['error']))
                    return response.get('result', {})
                # Reject server requests we cannot service rather than hanging approvals.
                if 'method' in response and 'id' in response:
                    await socket.send(json.dumps({'id': response['id'], 'error': {'code': -32601, 'message': 'Unsupported client request'}}))
        await request('initialize', {'clientInfo': {'name': 'spoq', 'version': __version__}})
        await socket.send(json.dumps({'method': 'initialized', 'params': {}}))
        loaded = await request('thread/resume', {'threadId': delivery['target']})
        thread = loaded.get('thread', {})
        turns = thread.get('turns', [])
        active = next((t for t in reversed(turns) if t.get('status') == 'inProgress'), None)
        params = {'threadId': delivery['target'], 'input': [{'type': 'text', 'text': notification(delivery), 'text_elements': []}]}
        if active:
            params['expectedTurnId'] = active['id']
            await request('turn/steer', params)
        else:
            await request('turn/start', params)


def dispatch_once(board, *, sender=None):
    delivery = board.lease()
    if delivery is None:
        return {'delivered': False}
    try:
        from .board import validate_registration
        validate_registration(delivery['recipient'], 'delivery', delivery['runtime'], delivery['target'], delivery['endpoint'])
        if sender:
            sender(delivery)
        elif delivery['runtime'] == 'codex-cli':
            queue_cli(delivery)
        else:
            asyncio.run(app_server(delivery))
    except Exception as exc:
        board.finish_delivery(delivery, str(exc))
        return {'delivered': False, 'message_id': delivery['message_id'], 'error': str(exc)}
    board.finish_delivery(delivery)
    return {'delivered': True, 'message_id': delivery['message_id'], 'state': 'submitted'}
