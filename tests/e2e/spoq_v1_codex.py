"""Opt-in live E2E: real Codex receives a SPOQ notification and replies via MCP.

Run with the package environment, e.g. uv run --extra codex python
../../../tests/e2e/spoq_v1_codex.py --out /tmp/spoq-live-e2e
Uses existing Codex authentication and two model turns. No repository edits.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
from pathlib import Path

from spoq_server.v1.board import Board
from spoq_server.v1.cli import init
from spoq_server.v1.codex import dispatch_once
from spoq_server.v1.migration import database_path
from spoq_server.v1.store import Store


async def run(out, runtime='codex-app-server', active=False):
    from websockets.asyncio.client import connect
    out.mkdir(parents=True,exist_ok=True)
    workspace=out/'workspace'
    init(workspace,agents='codex')
    store=Store(database_path(workspace))
    board=Board(store)
    board.run('live-e2e')
    board.register('live-e2e','orchestrator','orchestrator')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0))
        port=reservation.getsockname()[1]
    endpoint=f'ws://127.0.0.1:{port}'
    override=[
        '-c',f'mcp_servers.spoq.command={json.dumps(sys.executable)}',
        '-c','mcp_servers.spoq.args='+json.dumps(['-m','spoq_server','mcp','--root',str(workspace)]),
        '-c','mcp_servers.spoq.env='+('{ SPOQ_STORE="sqlite", SPOQ_PROJECT_ROOT='+json.dumps(str(workspace))+' }'),
        '-c','features.apps=false', '-c','features.plugins=false',
    ]
    # This opt-in test authorizes only these four local collaboration operations.
    for tool in ('spoq_ping','spoq_read_inbox','spoq_post_message','spoq_ack_message'):
        override += ['-c',f'mcp_servers.spoq.tools.{tool}.approval_mode="approve"']
    logs=(out/'app-server.log').open('wb')
    process=await asyncio.create_subprocess_exec('codex','app-server','--listen',endpoint,*override,
                                                stdout=logs,stderr=logs)
    messages=[]
    try:
        for _ in range(100):
            try:
                websocket=await connect(endpoint)
                break
            except OSError:
                if process.returncode is not None: raise RuntimeError('Codex app-server exited; inspect log')
                await asyncio.sleep(.1)
        else: raise TimeoutError('Codex app-server did not start')
        async with websocket:
            serial=0
            async def rpc(method,params):
                nonlocal serial
                serial+=1
                request_id=serial
                await websocket.send(json.dumps({'id':request_id,'method':method,'params':params}))
                while True:
                    value=json.loads(await asyncio.wait_for(websocket.recv(),45))
                    messages.append(value)
                    if value.get('id')==request_id:
                        if 'error' in value: raise RuntimeError(value['error'])
                        return value['result']
            async def finish():
                while True:
                    value=json.loads(await asyncio.wait_for(websocket.recv(),180))
                    messages.append(value)
                    if value.get('method')=='turn/completed':
                        turn=value['params']['turn']
                        if turn.get('status')!='completed': raise RuntimeError(turn)
                        return
            await rpc('initialize',{'clientInfo':{'name':'spoq-e2e','version':'1.0.0'}})
            await websocket.send(json.dumps({'method':'initialized','params':{}}))
            created=await rpc('thread/start',{'cwd':str(workspace),'approvalPolicy':'never','sandbox':'workspace-write'})
            thread_id=created['thread']['id']
            print('Created Codex worker thread',thread_id,flush=True)
            prompt=('You are the reviewer in an isolated SPOQ notification E2E test. Your run_id is live-e2e '
                    'and agent_id is reviewer. The user authorizes this test only. When a later SPOQ '
                    'notification arrives, use the SPOQ MCP inbox to read its full body, post the requested '
                    'reply to orchestrator with a stable request_key, and acknowledge the incoming message. '
                    'Use only SPOQ MCP tools; do not edit files, run shell commands, or contact external services. '
                    + ('For this first turn, read the inbox while waiting for a notification; handle it when it arrives.' if active
                       else 'For this first turn, reply READY and wait for the next notification.'))
            await rpc('turn/start',{'threadId':thread_id,'input':[{'type':'text','text':prompt,'text_elements':[]}]})
            if not active:
                await finish()
            board.register('live-e2e','reviewer','reviewer',runtime,thread_id,endpoint)
            marker='SPOQ-LIVE-ACK-7f3b2a'
            posted=board.post('live-e2e','orchestrator',['reviewer'],
                f'Notification test: reply to orchestrator with the exact token {marker}, then acknowledge this message.',
                kind='review',request_key='live-notification')
            result=await asyncio.to_thread(dispatch_once,board)
            if not result.get('delivered'): raise RuntimeError(result)
            print('Submitted notification',posted['id'],flush=True)
            await finish()
            replies=board.inbox('live-e2e','orchestrator')
            assert any(marker in reply['body'] for reply in replies),replies
            assert board.inbox('live-e2e','reviewer')==[], 'Recipient did not acknowledge notification'
            evidence={'passed':True,'thread_id':thread_id,'message_id':posted['id'],
                      'reply_ids':[r['id'] for r in replies],'marker':marker,'transport':runtime,'active':active,
                      'database':str(store.path)}
            (out/'result.json').write_text(json.dumps(evidence,indent=2)+'\n')
            print(json.dumps(evidence),flush=True)
            return evidence
    finally:
        (out/'events.json').write_text(json.dumps(messages,indent=2,default=str)+'\n')
        process.terminate()
        try: await asyncio.wait_for(process.wait(),10)
        except TimeoutError:
            process.kill()
            await process.wait()
        logs.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--runtime',choices=['codex-app-server','codex-cli'],default='codex-app-server')
    parser.add_argument('--active',action='store_true')
    args=parser.parse_args()
    asyncio.run(run(args.out.resolve(),args.runtime,args.active))
