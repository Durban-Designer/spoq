from concurrent.futures import ThreadPoolExecutor
import pytest
from spoq_server.v1.board import Board
from spoq_server.v1.codex import dispatch_once
from spoq_server.v1.db import transaction


def post(board,**kwargs):
    return board.post('run','backend',['qa'],'Please review',request_key='key',**kwargs)


def test_direct_reply_and_resolution(board):
    msg=post(board)
    reply=board.post('run','qa',['backend'],'Tests pass',reply_to=msg['id'],request_key='reply')
    assert reply['thread_id']==msg['thread_id']
    assert len(board.thread('run',msg['thread_id'])['messages'])==2
    board.acknowledge('run','qa',msg['id'])
    assert board.inbox('run','qa')==[]
    assert board.thread('run',msg['thread_id'])['state']=='open'
    board.resolve('run',msg['thread_id'],'Accepted')


def test_broadcast_ack_is_per_recipient(board):
    msg=board.post('run','orchestrator',['*'],'Contract update',request_key='broadcast')
    board.acknowledge('run','backend',msg['id'])
    assert board.inbox('run','backend')==[]
    assert len(board.inbox('run','frontend'))==1
    assert len(board.inbox('run','qa'))==1


def test_role_routing_and_retry_dedup(board):
    first=board.post('run','backend',['role:reviewer'],'Review',request_key='review')
    second=board.post('run','backend',['role:reviewer'],'Review',request_key='review')
    assert first['id']==second['id']
    assert len(board.inbox('run','qa'))==1
    with pytest.raises(ValueError,match='different'): board.post('run','backend',['qa'],'Changed',request_key='review')


def test_run_and_reply_isolation(board):
    msg=post(board)
    board.run('other')
    board.register('other','qa','reviewer')
    assert board.inbox('other','qa')==[]
    with pytest.raises(ValueError): board.acknowledge('other','qa',msg['id'])
    with pytest.raises(ValueError): board.post('other','qa',['qa'],'Wrong run',reply_to=msg['id'],request_key='bad')


def test_invalid_fanout_leaves_no_partial_message(board):
    with pytest.raises(ValueError): board.post('run','backend',['qa','missing'],'Review',request_key='invalid')
    assert board.inbox('run','qa')==[]


def test_outbox_failure_retries_and_ack_is_separate(board):
    board.register('run','qa','reviewer','codex-cli','thread-uuid')
    msg=post(board)
    def failing(delivery): raise RuntimeError('daemon unavailable')
    assert 'error' in dispatch_once(board,sender=failing)
    with transaction(board.path,write=True) as db: db.execute('UPDATE deliveries SET next_attempt=0')
    delivered=[]
    assert dispatch_once(board,sender=delivered.append)['state']=='submitted'
    assert board.inbox('run','qa')[0]['state']=='submitted'
    board.acknowledge('run','qa',msg['id'])
    assert board.inbox('run','qa')==[]


def test_expired_sender_cannot_overwrite_new_lease_or_ack(board):
    board.register('run','qa','reviewer','codex-cli','uuid')
    msg=post(board)
    old=board.lease()
    with transaction(board.path,write=True) as db: db.execute('UPDATE deliveries SET lease_until=0')
    current=board.lease()
    board.finish_delivery(old)
    assert board.inbox('run','qa')[0]['state']=='sending'
    board.acknowledge('run','qa',msg['id'])
    board.finish_delivery(current)
    assert board.inbox('run','qa')==[]


def test_concurrent_outbox_leases_do_not_duplicate_delivery(board):
    board.register('run','qa','reviewer','codex-cli','uuid')
    post(board)
    with ThreadPoolExecutor(max_workers=2) as pool: leases=list(pool.map(lambda _:board.lease(),range(2)))
    assert sum(l is not None for l in leases)==1


def test_unacknowledged_submission_redelivers_same_message_after_timeout(board):
    board.register('run','qa','reviewer','codex-cli','uuid')
    msg=post(board)
    delivered=[]
    dispatch_once(board,sender=delivered.append)
    assert board.lease() is None
    with transaction(board.path,write=True) as db: db.execute('UPDATE deliveries SET next_attempt=0')
    dispatch_once(board,sender=delivered.append)
    assert [d['message_id'] for d in delivered]==[msg['id'],msg['id']]
