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
