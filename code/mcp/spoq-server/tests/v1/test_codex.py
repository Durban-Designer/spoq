import subprocess
from unittest.mock import patch
import pytest
from spoq_server.v1.codex import queue_cli


def test_cli_queue_passes_message_as_literal_argument_and_warns_on_failed_resume():
    delivery={'message_id':'m','recipient':'worker','run_id':'run','target':'uuid','endpoint':''}
    result=subprocess.CompletedProcess([],0,'','Warning: failed to resume thread')
    with patch('subprocess.run',return_value=result) as run:
        with pytest.raises(RuntimeError,match='resume'): queue_cli(delivery)
        args=run.call_args.args[0]
        assert args[:4]==['codex','queue','--thread','uuid']
        assert '--resume' in args and 'shell' not in run.call_args.kwargs


def test_registration_rejects_deceptive_remote_endpoint(board):
    with pytest.raises(ValueError,match='local'):
        board.register('run','qa','reviewer','codex-app-server','uuid','ws://localhost:80@evil.example:80')


# Fake the optional transport dependency, not the dispatcher. These regressions
# also run in core-only installations where websockets is intentionally absent.
@pytest.fixture
def codex_socket(monkeypatch):
    import json
    import sys
    import types
    class Socket:
        def __init__(self):
            self.requests = []
            self.responses = []
            self.active = False
            self.failure_method = None
            self.error = {'code':-32601,'message':'list_turns is not supported yet'}
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def send(self, raw):
            request = json.loads(raw)
            if 'id' not in request or 'method' not in request:return
            self.requests.append(request)
            method = request['method']
            if method == self.failure_method:
                response = {'id':request['id'],'error':self.error}
            else:
                value = {'thread':{'turns':[{'id':'in-flight','status':'inProgress'}] if self.active else []}} if method=='thread/resume' else {}
                response = {'id':request['id'],'result':value}
            self.responses.append(response)
        async def recv(self):return json.dumps(self.responses.pop(0))
    socket = Socket()
    root = types.ModuleType('websockets');root.__path__=[]
    namespace = types.ModuleType('websockets.asyncio');namespace.__path__=[]
    client = types.ModuleType('websockets.asyncio.client')
    client.connect = lambda *a,**k: socket
    client.unix_connect = lambda *a,**k: socket
    monkeypatch.setitem(sys.modules,'websockets',root)
    monkeypatch.setitem(sys.modules,'websockets.asyncio',namespace)
    monkeypatch.setitem(sys.modules,'websockets.asyncio.client',client)
    return socket


def notification_delivery():
    return {'message_id':'m','recipient':'qa','run_id':'run','target':'uuid',
            'endpoint':'ws://127.0.0.1:8765','runtime':'codex-app-server'}


@pytest.mark.anyio
@pytest.mark.parametrize('active', [False, True])
async def test_supported_history_preserves_idle_start_and_exact_active_steer(codex_socket, monkeypatch, active):
    from spoq_server.v1 import codex
    codex_socket.active = active
    queued = [];monkeypatch.setattr(codex,'queue_cli',queued.append)
    result = await codex.app_server(notification_delivery())
    assert result == {'delivery_mode':'steered' if active else 'started'}
    assert queued == []
    request = codex_socket.requests[-1]
    assert request['method'] == ('turn/steer' if active else 'turn/start')
    if active:assert request['params']['expectedTurnId'] == 'in-flight'
    else:assert 'expectedTurnId' not in request['params']


@pytest.mark.anyio
async def test_exact_unsupported_history_queues_once_before_any_notification_input(codex_socket, monkeypatch):
    from spoq_server.v1 import codex
    codex_socket.failure_method = 'thread/resume'
    queued = [];monkeypatch.setattr(codex,'queue_cli',queued.append)
    delivery = notification_delivery()
    assert await codex.app_server(delivery) == {'delivery_mode':'queued_fallback'}
    assert queued == [delivery]
    assert [r['method'] for r in codex_socket.requests] == ['initialize','thread/resume']


@pytest.mark.anyio
@pytest.mark.parametrize('error', [
    {'code':-32601,'message':'Unknown thread'},
    {'code':-32602,'message':'list_turns is not supported yet'},
    {'code':-32001,'message':'list_turns is not supported yet'},
    {'code':-32601.0,'message':'list_turns is not supported yet'},
    'list_turns is not supported yet',
])
async def test_other_resume_failures_do_not_fallback(codex_socket, monkeypatch, error):
    from spoq_server.v1 import codex
    codex_socket.failure_method = 'thread/resume';codex_socket.error = error
    queued = [];monkeypatch.setattr(codex,'queue_cli',queued.append)
    with pytest.raises(codex.CodexRPCError):await codex.app_server(notification_delivery())
    assert queued == []


@pytest.mark.anyio
@pytest.mark.parametrize('active', [False, True])
async def test_submission_error_is_never_replayed_through_queue(codex_socket, monkeypatch, active):
    from spoq_server.v1 import codex
    codex_socket.active = active
    codex_socket.failure_method = 'turn/steer' if active else 'turn/start'
    queued = [];monkeypatch.setattr(codex,'queue_cli',queued.append)
    with pytest.raises(codex.CodexRPCError):await codex.app_server(notification_delivery())
    assert queued == []
    assert len([r for r in codex_socket.requests if r['method'].startswith('turn/')]) == 1


def test_fallback_failure_keeps_durable_delivery_retryable(board, codex_socket, monkeypatch):
    from spoq_server.v1 import codex
    codex_socket.failure_method = 'thread/resume'
    board.register('run','qa','reviewer','codex-app-server','uuid','ws://127.0.0.1:8765')
    posted = board.post('run','orchestrator',['qa'],'Review current work',request_key='fallback-retry')
    def fail(delivery):raise RuntimeError('Queue failed; no acceptance')
    monkeypatch.setattr(codex,'queue_cli',fail)
    result = codex.dispatch_once(board)
    assert not result['delivered'] and 'Queue failed' in result['error']
    assert board.inbox('run','qa')[0]['id'] == posted['id']


def test_successful_fallback_reports_queue_mode_without_claiming_ack(board, codex_socket, monkeypatch):
    from spoq_server.v1 import codex
    codex_socket.failure_method = 'thread/resume'
    board.register('run','qa','reviewer','codex-app-server','uuid','ws://127.0.0.1:8765')
    posted = board.post('run','orchestrator',['qa'],'Review current work',request_key='fallback-success')
    queued = [];monkeypatch.setattr(codex,'queue_cli',queued.append)
    result = codex.dispatch_once(board)
    assert result == {'delivered':True,'message_id':posted['id'],'state':'submitted','delivery_mode':'queued_fallback'}
    assert len(queued) == 1
    assert board.inbox('run','qa')[0]['id'] == posted['id']
