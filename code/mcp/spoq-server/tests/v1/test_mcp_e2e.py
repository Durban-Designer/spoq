"""Real subprocess MCP clients exercise the SQLite-native wire surface."""
import json
import os
import sys
from datetime import timedelta

import anyio
import pytest
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client


def parameters(root):
    env={k:v for k,v in os.environ.items() if k!='SPOQ_STORE'}
    return StdioServerParameters(command=sys.executable,args=['-m','spoq_server','mcp','--root',str(root)],env=env)


async def call(client,name,**args):
    response=await client.call_tool(name,args)
    assert not response.isError, response.content
    if response.structuredContent is not None:
        value=response.structuredContent
        return value['result'] if set(value)=={'result'} else value
    return json.loads(response.content[0].text)


@pytest.mark.anyio
async def test_real_mcp_planning_and_peer_collaboration(tmp_path):
    with anyio.fail_after(30):
        async with stdio_client(parameters(tmp_path)) as (r,w):
            async with ClientSession(r,w,read_timeout_seconds=timedelta(seconds=10)) as first:
                await first.initialize()
                ping=await call(first,'spoq_ping')
                assert ping['active_backend']=='sqlite' and ping['version'].startswith('1.')
                names={t.name for t in (await first.list_tools()).tools}
                assert 'spoq_create_feature' in names and 'spoq_parse_epic' not in names
                await call(first,'spoq_create_project_plan',plan_id='plan',title='Checkout')
                await call(first,'spoq_create_feature',feature_id='api',title='API',plan_id='plan')
                await call(first,'spoq_create_feature',feature_id='ui',title='UI',plan_id='plan')
                await call(first,'spoq_add_dependency',node_id='ui',dependency_id='api')
                await call(first,'spoq_create_task',task_id='task',title='API contract',feature_id='api')
                assert (await call(first,'spoq_compute_dag',scope_id='plan'))['waves']==[['api'],['ui']]
                await call(first,'spoq_create_run',run_id='run',scope_id='plan')
                await call(first,'spoq_register_agent',run_id='run',agent_id='worker',role='worker')
                await call(first,'spoq_register_agent',run_id='run',agent_id='reviewer',role='reviewer')
                msg=await call(first,'spoq_post_message',run_id='run',sender='worker',recipients=['reviewer'],body='Please review contract',request_key='review')
                assert not (await call(first,'spoq_dispatch_notification'))['delivered']
                async with stdio_client(parameters(tmp_path)) as (r2,w2):
                    async with ClientSession(r2,w2) as second:
                        await second.initialize()
                        inbox=await call(second,'spoq_read_inbox',run_id='run',agent_id='reviewer')
                        assert inbox[0]['id']==msg['id']
                        await call(second,'spoq_ack_message',run_id='run',agent_id='reviewer',message_id=msg['id'])
                        await call(second,'spoq_post_message',run_id='run',sender='reviewer',recipients=['worker'],body='Accepted',request_key='reply',reply_to=msg['id'])
                assert len((await call(first,'spoq_get_thread',run_id='run',thread_id=msg['thread_id']))['messages'])==2
                await call(first,'spoq_append_journal',body='Contract reviewed with unit tests',agent='worker',node_id='task')
                assert await call(first,'spoq_search',query='contract',kind='journal')


@pytest.mark.anyio
async def test_upgrade_prompt_and_conversion_through_real_mcp(legacy):
    with anyio.fail_after(30):
        async with stdio_client(parameters(legacy)) as (r,w):
            async with ClientSession(r,w) as client:
                initialized=await client.initialize()
                assert 'confirmation' in initialized.instructions
                assert (await call(client,'spoq_ping'))['migration_required']
                assert (await call(client,'spoq_migrate'))['confirmation_required']
                response=await client.call_tool('spoq_list_nodes',{})
                assert response.isError
                assert (await call(client,'spoq_migrate',confirmed=True))['converted']
                assert not (await call(client,'spoq_ping'))['migration_required']
                assert len(await call(client,'spoq_list_nodes',kind='feature'))==2
