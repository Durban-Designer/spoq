"""Actual MCP stdio tests use scripted skill adapters, never live model inference."""
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import timedelta

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from spoq_server.v1.db import BASE_SCHEMA
from spoq_server.v1.store import Store
from spoq_server.v1.board import Board
from spoq_server.v1.workflows.mcp import READ_ONLY_TOOLS, MUTATING_TOOLS
from workflow_support import evidence_for, outputs_for


@asynccontextmanager
async def client(root):
    env = {**os.environ, 'SPOQ_STORE':'sqlite'}
    parameters = StdioServerParameters(command=sys.executable,
        args=['-m','spoq_server','mcp','--root',str(root)],env=env)
    async with stdio_client(parameters) as (r,w):
        async with ClientSession(r,w,read_timeout_seconds=timedelta(seconds=15)) as session:
            await session.initialize()
            yield session


async def call(session, name, **args):
    response = await session.call_tool(name, args)
    assert not response.isError, response.content
    if response.structuredContent is not None:
        value = response.structuredContent
        return value['result'] if set(value) == {'result'} else value
    return json.loads(response.content[0].text)


async def refused(session,name,**args):
    result = await session.call_tool(name,args)
    assert result.isError,result
    return result


async def scope(session):
    await call(session,'spoq_create_project_plan',plan_id='p',title='Protocol fixture plan')
    await call(session,'spoq_create_feature',feature_id='f',title='Protocol fixture feature',plan_id='p')


async def complete(session,run,envelope,key,*,outputs=None,stage=None):
    return await call(session,'spoq_complete_workflow_phase',run_id=run,attempt_id=envelope['attempt_id'],token=envelope['token'],
                      key=key,evidence=evidence_for(envelope,stage=stage),outputs=outputs)


@pytest.mark.anyio
async def test_discovery_annotations_and_readonly_calls_never_initialize_or_start_models(tmp_path):
    with anyio.fail_after(45):
        async with client(tmp_path) as session:
            tools = {tool.name:tool for tool in (await session.list_tools()).tools}
            assert set(READ_ONLY_TOOLS+MUTATING_TOOLS) <= tools.keys()
            for name in READ_ONLY_TOOLS:
                assert tools[name].annotations.readOnlyHint is True
                assert tools[name].annotations.openWorldHint is False
            for name in MUTATING_TOOLS:
                assert tools[name].annotations.readOnlyHint is False
            assert set(tools['spoq_create_task'].inputSchema['required']) == {'task_id','title','feature_id'}
            assert 'definition' not in tools['spoq_start_workflow'].inputSchema['properties']
            assert 'root' not in tools['spoq_start_workflow'].inputSchema['properties']
            capabilities = await call(session,'spoq_workflow_capabilities')
            assert {s['id'] for s in capabilities['strategies']} == {'classic','piqard'}
            assert capabilities['execution']['client_driven'] and not capabilities['execution']['engine_launches_models']
            assert not capabilities['progress_delivery']['universal_client_push_required']
            assert 'relay' in capabilities['progress_delivery']['agent_messages']
            assert (await call(session,'spoq_ping'))['workflow']['tools']['read_only'] == list(READ_ONLY_TOOLS)
            assert (await call(session,'spoq_list_workflows'))['runs'] == []
            routed = await call(session,'spoq_route_workflow',inputs={'uncertainty':'high'})
            assert routed['strategy'] == 'piqard'
            p = subprocess.run([sys.executable,'-m','spoq_server','workflow','route','--inputs','{"uncertainty":"high"}',
                                '--root',str(tmp_path)],text=True,capture_output=True,env={**os.environ,'SPOQ_STORE':'sqlite'},timeout=20)
            assert p.returncode == 0 and json.loads(p.stdout) == routed
            await refused(session,'spoq_start_workflow',run_id='r',scope_id='unknown',key='start')
            assert not (tmp_path/'.spoq').exists()


@pytest.mark.anyio
async def test_actual_stdio_classic_lifecycle_retains_old_task_contract_and_matches_cli_snapshot(tmp_path):
    with anyio.fail_after(60):
        async with client(tmp_path) as session:
            await scope(session)
            await call(session,'spoq_create_task',task_id='t',title='Scripted adapter task',feature_id='f',
                       data={'acceptance_criteria':['Protocol fixture asserts the state transition']})
            started = await call(session,'spoq_start_workflow',run_id='r',scope_id='f',key='start',inputs={'uncertainty':'low'},strategy='classic')
            assert started['scope_id'] == 'f'
            assert await call(session,'spoq_start_workflow',run_id='r',scope_id='f',key='start',inputs={'uncertainty':'low'},strategy='classic') == started
            plan = await call(session,'spoq_next_workflow_phase',run_id='r',key='plan')
            assert plan['skill'] == 'spoq-plan'
            renewed = await call(session,'spoq_renew_workflow_phase',run_id='r',attempt_id=plan['attempt_id'],token=plan['token'],key='renew',ttl=1200)
            assert renewed['lease_until'] > plan['lease_until']
            result = await complete(session,'r',plan,'planned',outputs=outputs_for(plan))
            assert (await call(session,'spoq_workflow_attempt',run_id='r',attempt_id=plan['attempt_id']))['evidence']['verdict'] == 'PASS'
            artifact = await call(session,'spoq_workflow_artifact',run_id='r',artifact_id=result['outputs']['project_plan'])
            assert artifact['render_as'] == 'text'
            assert (await call(session,'spoq_workflow_node',run_id='r',node_id='t'))['data']['acceptance_criteria']
            gate = await call(session,'spoq_next_workflow_phase',run_id='r',key='planning-gate')
            assert (await complete(session,'r',gate,'planning-gate-done',stage='plan'))['outcome'] == 'pass'
            execute = await call(session,'spoq_next_workflow_phase',run_id='r',key='execute')
            assert execute['work']['ready_tasks'] == ['t']
            # These are explicitly simulated software/check adapters. Existing 1.0
            # claims/tools remain usable; strict new phase reports are separate.
            task = await call(session,'spoq_claim_task',task_id='t',run_id='r',agent_id='orchestrator')
            await call(session,'spoq_update_node',node_id='t',status='completed',claim_token=task['token'],
                       evidence={'adapter':'scripted protocol fixture, not model implementation'})
            await complete(session,'r',execute,'executed',outputs=outputs_for(execute))
            final = await call(session,'spoq_next_workflow_phase',run_id='r',key='implementation-gate')
            assert (await complete(session,'r',final,'implementation-gate-done',stage='implementation'))['status'] == 'passed'
            snapshot = await call(session,'spoq_get_workflow',run_id='r')
            assert snapshot['run']['status'] == 'passed'
            assert len((await call(session,'spoq_workflow_history',run_id='r'))['items']) == 4
            assert (await call(session,'spoq_workflow_work',run_id='r'))['nodes']
            assert (await call(session,'spoq_workflow_events',run_id='r',after=0))['events']
            p = subprocess.run([sys.executable,'-m','spoq_server','workflow','show','r','--root',str(tmp_path)],
                               text=True,capture_output=True,env={**os.environ,'SPOQ_STORE':'sqlite'},timeout=20)
            assert p.returncode == 0 and json.loads(p.stdout) == snapshot
            assert not (tmp_path/'.spoq/models').exists()


@pytest.mark.anyio
async def test_actual_stdio_piqard_rejection_revision_attestation_pause_resume_and_proposal(tmp_path):
    with anyio.fail_after(60):
        async with client(tmp_path) as session:
            await scope(session)
            await call(session,'spoq_start_workflow',run_id='r',scope_id='f',key='start',strategy='piqard')
            discover = await call(session,'spoq_next_workflow_phase',run_id='r',key='discover')
            await complete(session,'r',discover,'discovered',outputs=outputs_for(discover))
            narrative = {name:['Recorded '+name] for name in ['scope','decisions','assumptions','risks','acceptance_criteria']}
            draft = await call(session,'spoq_next_workflow_phase',run_id='r',key='draft')
            await complete(session,'r',draft,'drafted',outputs={'narrative_plan':{'content':narrative}})
            review = await call(session,'spoq_next_workflow_phase',run_id='r',key='review')
            first = review['inputs']['narrative_plan']
            proposal = await call(session,'spoq_propose_workflow_route',run_id='r',inputs={'uncertainty':'low'},key='proposal',
                                  reason='Scripted fixture resolved uncertainty')
            assert proposal['requires_explicit_adoption']
            reply = dict(run_id='r',attempt_id=review['attempt_id'],artifact_id=first['id'],artifact_hash=first['sha256'],
                         decision='reject',author='Simulated User',key='rejected',source='user',reason='Clarify rollback acceptance.')
            await refused(session,'spoq_respond_workflow',**reply,user_confirmed=False)
            assert (await call(session,'spoq_respond_workflow',**reply,user_confirmed=True))['outcome'] == 'fail'
            draft2 = await call(session,'spoq_next_workflow_phase',run_id='r',key='draft2')
            narrative['acceptance_criteria'].append('Rollback requirement now explicit')
            await complete(session,'r',draft2,'drafted2',outputs={'narrative_plan':{'content':narrative}})
            review2 = await call(session,'spoq_next_workflow_phase',run_id='r',key='review2')
            current = review2['inputs']['narrative_plan']
            await refused(session,'spoq_respond_workflow',**{**reply,'key':'stale','decision':'approve'},user_confirmed=True)
            args = {**reply,'attempt_id':review2['attempt_id'],'artifact_id':current['id'],'artifact_hash':current['sha256'],
                    'key':'approved','decision':'approve','reason':'','user_confirmed':True}
            approved = await call(session,'spoq_respond_workflow',**args)
            assert await call(session,'spoq_respond_workflow',**args) == approved
            assert (await call(session,'spoq_pause_workflow',run_id='r',key='pause'))['status'] == 'paused'
            assert (await call(session,'spoq_next_workflow_phase',run_id='r',key='paused-next'))['status'] == 'paused'
            assert (await call(session,'spoq_resume_workflow',run_id='r',key='resume'))['status'] == 'running'
            assert (await call(session,'spoq_next_workflow_phase',run_id='r',key='decompose'))['phase_id'] == 'plan'
            assert (await call(session,'spoq_inspect_workflow',run_id='r'))['client_mode'] == 'client_driven'
            decisions = (await call(session,'spoq_workflow_history',run_id='r',resource='decisions'))['items']
            assert [row['decision'] for row in decisions] == ['reject','approve']


@pytest.mark.anyio
async def test_readonly_old_schema_and_explicit_upgrade_through_actual_stdio_preserve_journal_mode(tmp_path):
    path = tmp_path/'.spoq/spoq.db';path.parent.mkdir()
    db = sqlite3.connect(path);db.executescript(BASE_SCHEMA+';PRAGMA user_version=1;');db.close()
    store = Store(path);store.create('project_plan','p','Old plan');store.create('feature','f','Old feature','p');Board(store).run('old','f')
    db = sqlite3.connect(path,isolation_level=None);assert db.execute('PRAGMA journal_mode=DELETE').fetchone()[0] == 'delete';db.close()
    before = path.read_bytes()
    with anyio.fail_after(45):
        async with client(tmp_path) as session:
            assert (await call(session,'spoq_workflow_capabilities'))['schema']['from_version'] == 1
            assert (await call(session,'spoq_ping'))['workflow']['schema']['from_version'] == 1
            assert (await call(session,'spoq_list_workflows'))['runs'][0]['status'] == 'legacy_unclassified'
            assert (await call(session,'spoq_get_workflow',run_id='old'))['phases'] == []
            assert (await call(session,'spoq_inspect_workflow',run_id='old'))['status'] == 'legacy_unclassified'
            preview = await call(session,'spoq_upgrade_workflow')
            assert preview['upgrade_required'] and not preview['upgraded']
            assert not (path.parent/'backups').exists()
            await refused(session,'spoq_start_workflow',run_id='r',scope_id='f',key='blocked')
            assert path.read_bytes() == before
            db = sqlite3.connect(path)
            try:
                assert db.execute('PRAGMA user_version').fetchone()[0] == 1
                assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
            finally:db.close()
            upgraded = await call(session,'spoq_upgrade_workflow',confirmed=True)
            assert upgraded['upgraded'] and upgraded['backup']
            assert (await call(session,'spoq_start_workflow',run_id='r',scope_id='f',key='start'))['scope_id'] == 'f'


@pytest.mark.anyio
async def test_invalid_evidence_scope_and_operation_keys_are_refused_over_stdio(tmp_path):
    with anyio.fail_after(45):
        async with client(tmp_path) as session:
            await scope(session)
            await call(session,'spoq_start_workflow',run_id='r',scope_id='f',key='start',strategy='classic')
            await refused(session,'spoq_next_workflow_phase',run_id='r',key='stale',expected_revision=999)
            plan = await call(session,'spoq_next_workflow_phase',run_id='r',key='plan')
            await refused(session,'spoq_complete_workflow_phase',run_id='r',attempt_id=plan['attempt_id'],token=plan['token'],key='bad',evidence={'passed':True})
            await refused(session,'spoq_workflow_node',run_id='r',node_id='p')
            await refused(session,'spoq_workflow_events',run_id='r',limit=501)
            await refused(session,'spoq_next_workflow_phase',run_id='r',key='plan',ttl=1)
            assert (await call(session,'spoq_inspect_workflow',run_id='r'))['state']['phases']['plan']['status'] == 'running'


@pytest.mark.anyio
async def test_mcp_preserves_strict_json_scalar_types_for_engine_and_readonly_guards(tmp_path):
    with anyio.fail_after(45):
        async with client(tmp_path) as session:
            await scope(session)
            await call(session,'spoq_start_workflow',run_id='r',scope_id='f',key='start',strategy='classic')
            # MCP's argument model must not turn True into limit=1 or a string
            # into an affirmative human/upgrade attestation before core checks.
            await refused(session,'spoq_workflow_events',run_id='r',limit=True)
            await refused(session,'spoq_next_workflow_phase',run_id='r',key='bad-ttl',ttl=True)
            await refused(session,'spoq_next_workflow_phase',run_id='r',key='bad-recover',recover='true')
            await refused(session,'spoq_upgrade_workflow',confirmed='true')
            assert (await call(session,'spoq_workflow_history',run_id='r'))['items'] == []
