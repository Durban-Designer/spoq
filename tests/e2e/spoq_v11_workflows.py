"""Installed SPOQ 1.1 CLI/MCP and crash E2E; skill/human adapters are scripted.

The outer installer uses only the standard library. Application imports happen
only in isolated child interpreters and are checked against the installed prefix.
Transaction fault hooks exist only in this test driver, never in production.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

SCRIPT = Path(__file__).resolve()
IDENTITIES = ('run_id','scope_id','phase_id','attempt_id','definition_hash','specification_hash','artifact_hashes')
ACTIONS = {
 'start':('start','spoq_start_workflow',('run_id',),{'scope_id':'scope','inputs':'inputs','strategy':'strategy','key':'key','actor':'agent'}),
 'next':('next','spoq_next_workflow_phase',('run_id',),{'key':'key','actor':'agent','ttl':'ttl','recover':'recover','phase_id':'phase'}),
 'complete':('complete','spoq_complete_workflow_phase',('run_id','attempt_id'),{'key':'key','actor':'agent','token':'token','evidence':'evidence','outputs':'outputs','outcome':'outcome','refresh_spec':'refresh-spec'}),
 'respond':('respond','spoq_respond_workflow',('run_id','attempt_id'),{'key':'key','artifact_id':'artifact','artifact_hash':'hash','decision':'decision','author':'author','source':'source','user_confirmed':'user-confirmed','reason':'reason'}),
 'show':('show','spoq_get_workflow',('run_id',),{'limit':'limit','before':'before'}),
 'inspect':('inspect','spoq_inspect_workflow',('run_id',),{}),
 'history':('history','spoq_workflow_history',('run_id',),{'resource':'resource','limit':'limit','before':'before'}),
 'pause':('pause','spoq_pause_workflow',('run_id',),{'key':'key','reason':'reason'}),
 'resume':('resume','spoq_resume_workflow',('run_id',),{'key':'key','refresh_spec':'refresh-spec'}),
}


def clean_env():
    return {**{k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','VIRTUAL_ENV','SPOQ_STORE','SPOQ_PROJECT_ROOT'}},'SPOQ_STORE':'sqlite'}


def check_origin(expected_prefix=None, expected_origin=None):
    import spoq_server
    origin=Path(spoq_server.__file__).resolve()
    if expected_prefix is not None and not origin.is_relative_to(Path(expected_prefix).resolve()):
        raise AssertionError('Application import escaped installed prefix: '+str(origin))
    if expected_origin is not None and origin!=Path(expected_origin).resolve():
        raise AssertionError('Fault worker loaded a different application: '+str(origin))
    return {'module':str(origin),'version':spoq_server.__version__,'python':sys.version,'platform':platform.platform()}


def evidence(envelope, checks=None, *, stage=None, passed=True):
    value={k:envelope[k] for k in IDENTITIES}
    value.update(reviewer={'agent':'scripted-e2e-adapter','review_type':'scripted_adapter'},checks_passed=passed,
        observed_checks=checks or [{'check_type':'review','name':'Scripted protocol fixture assertion',
                                   'source':'test adapter; not model inference','observed':True,'passed':passed}],
        acceptance_results=[{'criterion':'Declared scripted fixture outcome verified','passed':passed}])
    if stage:
        # Metric names are package-owned, not copied implementation arithmetic.
        from importlib.util import spec_from_file_location,module_from_spec
        import spoq_server
        helper=Path(spoq_server.__file__).parent/'data/v1_skills/spoq/scripts/score_gate.py'
        spec=spec_from_file_location('_fixture_scores',helper);module=module_from_spec(spec);spec.loader.exec_module(module)
        value['scores']={name:96 for name in module.METRICS[stage]}
    return value



class InstalledRuntime:
    def __init__(self, python, workspace, out, *, expected_prefix=None, transport='cli', expected_origin=None):
        self.python=str(Path(python).expanduser().absolute());self.workspace=Path(workspace).resolve();self.out=Path(out).resolve()
        self.out.mkdir(parents=True,exist_ok=True)
        self.expected_prefix=str(Path(expected_prefix).resolve()) if expected_prefix else None
        self.expected_origin=expected_origin;self.transport=transport;self.commands=[];self.serial=0;self.tokens=set()

    def _redact(self,value):
        if isinstance(value,dict):return {k:('[redacted]' if k in {'token','claim_token'} else self._redact(v)) for k,v in value.items()}
        if isinstance(value,list):return [self._redact(v) for v in value]
        if isinstance(value,str):
            for token in self.tokens:value=value.replace(token,'[redacted]')
        return value

    def run(self,argv,label,*,cwd=None,expect=0):
        self.serial+=1;started=time.monotonic()
        p=subprocess.run(list(map(str,argv)),cwd=cwd or self.workspace,env=clean_env(),capture_output=True,text=True,timeout=90)
        try: parsed=json.loads(p.stdout)
        except ValueError:parsed=None
        def tokens(value):
            if isinstance(value,dict):
                for k,v in value.items():
                    if k=='token' and isinstance(v,str):self.tokens.add(v)
                    else:tokens(v)
            elif isinstance(value,list):
                for v in value:tokens(v)
        tokens(parsed)
        stem=self.out/(str(self.serial).zfill(3)+'-'+label)
        stem.with_suffix('.stdout').write_text(json.dumps(self._redact(parsed),indent=2) if parsed is not None else self._redact(p.stdout))
        stem.with_suffix('.stderr').write_text(self._redact(p.stderr))
        command=self._redact(list(map(str,argv)))
        for n,arg in enumerate(command[:-1]):
            if arg=='--token':command[n+1]='[redacted]'
        self.commands.append({'label':label,'argv':command,'exit_code':p.returncode,'seconds':round(time.monotonic()-started,3)})
        if expect==0 and p.returncode:raise RuntimeError(label+' failed: '+p.stderr[-1500:])
        if expect!=0 and not p.returncode:raise AssertionError(label+' unexpectedly succeeded')
        return parsed if parsed is not None else p.stdout

    def cli(self,*args,expect=0):
        return self.run([self.python,'-I','-m','spoq_server',*args,'--root',self.workspace],str(args[0]),expect=expect)

    def call(self,action,*,expect=0,**arguments):
        name,tool,positions,flags=ACTIONS[action]
        if self.transport=='mcp':
            payload={'root':str(self.workspace),'tool':tool,'arguments':arguments,'expected_prefix':self.expected_prefix,'expected_origin':self.expected_origin}
            path=self.out/('mcp-'+str(self.serial)+'.json');path.write_text(json.dumps(payload))
            response=self.run([self.python,'-I',SCRIPT,'--mcp',path],action,cwd=self.out)
            path.unlink()
            if response['ok'] != (expect==0):raise AssertionError('Unexpected MCP outcome: '+str(response))
            return response['value']
        argv=['workflow',name,*[arguments.pop(key) for key in positions]]
        if set(arguments)-set(flags):raise ValueError('Unknown fixture arguments '+str(set(arguments)-set(flags)))
        for key,value in arguments.items():
            if value is None:continue
            if isinstance(value,bool):
                if value:argv+=['--'+flags[key]]
            else:argv+=['--'+flags[key],json.dumps(value) if isinstance(value,(dict,list)) else str(value)]
        return self.cli(*argv,expect=expect)

    def installed(self,code,*arguments,label='installed-fixture',cwd=None):
        prelude=''
        if self.expected_prefix:
            prelude='from pathlib import Path;import spoq_server;assert Path(spoq_server.__file__).resolve().is_relative_to(Path('+repr(self.expected_prefix)+'));'
        return self.run([self.python,'-I','-c',prelude+code,*arguments],label,cwd=cwd)

    def report(self,envelope,checks=None,*,stage=None,passed=True):
        path=self.out/('evidence-input-'+str(self.serial)+'.json')
        path.write_text(json.dumps({'envelope':envelope,'checks':checks,'stage':stage,'passed':passed,
                                    'expected_prefix':self.expected_prefix,'expected_origin':self.expected_origin}))
        value=self.run([self.python,'-I',SCRIPT,'--evidence',path],'evidence',cwd=self.out);path.unlink()
        return value


class WorkflowFixture:
    """Reusable CLI/MCP driver; browser fixtures may stop at each human revision."""
    def __init__(self,runtime,run_id='fixture',strategy='piqard'):
        self.runtime=runtime;self.run_id=run_id;self.strategy=strategy;self.review=None;self.draft_revision=0;self.checks=[]

    def prepare(self):
        rt=self.runtime;rt.workspace.mkdir(parents=True,exist_ok=True)
        rt.cli('init','--agents','codex')
        rt.cli('create','project_plan','plan','Scripted E2E Project Plan')
        rt.cli('create','feature','feature','Scripted clamp fixture','--parent','plan',
               '--data',json.dumps({'goal':'Implement the declared clamp fixture with actual local checks'}))
        return rt.call('start',run_id=self.run_id,scope_id='feature',strategy=self.strategy,key='start',inputs={'uncertainty':'high' if self.strategy=='piqard' else 'low'})

    def view(self):
        value={'run_id':self.run_id,'workspace':str(self.runtime.workspace),'snapshot':self.runtime.call('show',run_id=self.run_id)}
        if self.review:
            artifact=self.review['inputs']['narrative_plan'];value['review']={'attempt_id':self.review['attempt_id'],'artifact_id':artifact['id'],'artifact_hash':artifact['sha256']}
        return value

    def next(self,key):return self.runtime.call('next',run_id=self.run_id,key=key)
    def complete(self,call,key,outputs=None,*,stage=None,checks=None,passed=True,refresh=False):
        return self.runtime.call('complete',run_id=self.run_id,attempt_id=call['attempt_id'],token=call['token'],key=key,
            evidence=self.runtime.report(call,checks,stage=stage,passed=passed),outputs=outputs or {},refresh_spec=refresh)

    def to_review(self):
        call=self.next('discover');assert call['phase_id']=='discover'
        self.complete(call,'discovered',{'discovery':{'content':'Scripted constraints: clamp finite numeric values; explicit tests and bounds.'}})
        return self.revise()

    def revise(self):
        self.draft_revision+=1;call=self.next('draft-'+str(self.draft_revision));assert call['phase_id']=='narrative'
        narrative={k:['Scripted '+k+' revision '+str(self.draft_revision)] for k in ('scope','decisions','assumptions','risks','acceptance_criteria')}
        self.complete(call,'drafted-'+str(self.draft_revision),{'narrative_plan':{'content':narrative,'source':'scripted_adapter'}})
        self.review=self.next('review-'+str(self.draft_revision));assert self.review['status']=='waiting_human'
        return self.review

    def response(self,decision,key,*,review=None,confirmed=True,source='user',expect=0):
        review=review or self.review;artifact=review['inputs']['narrative_plan']
        return self.runtime.call('respond',run_id=self.run_id,attempt_id=review['attempt_id'],artifact_id=artifact['id'],
            artifact_hash=artifact['sha256'],decision=decision,author='Scripted User Fixture',key=key,source=source,
            user_confirmed=confirmed,reason='Scripted fixture requests explicit rollback criteria.' if decision=='reject' else '',expect=expect)

    def reject_and_revise(self):
        first=self.review;self.response('reject','human-reject');self.revise()
        self.response('approve','stale-human-approve',review=first,expect=1)
        return self.review

    def approve(self):return self.response('approve','human-approve')

    def deliver(self):
        rt=self.runtime;call=self.next('decompose');assert call['phase_id']=='plan'
        # Deliberately omit max_retries, then persist its default during work.
        rt.cli('create','task','implementation','Implement clamp','--parent','feature','--data',json.dumps({'acceptance_criteria':['Clamp boundaries and invalid inputs behave correctly']}))
        rt.cli('create','task','integration','Compile and run clamp example','--parent','feature','--data',json.dumps({'acceptance_criteria':['Tests, compilation and example pass']}))
        rt.cli('depend','integration','implementation')
        fresh=rt.call('inspect',run_id=self.run_id)['current_specification_hash'];call['specification_hash']=fresh
        self.complete(call,'decomposed',{'project_plan':{'content':{'scope_id':'feature','specification_hash':fresh}}},refresh=True)
        gate=self.next('plan-gate');assert gate['phase_id']=='plan-validation';self.complete(gate,'plan-gated',stage='plan')
        execute=self.next('execute');assert execute['phase_id']=='execute'
        for task_id in ('implementation','integration'):
            claim=rt.cli('claim',task_id,'--run',self.run_id,'--agent','orchestrator','--ttl','1200')
            node=rt.cli('get',task_id)
            rt.cli('edit',task_id,'--revision',str(node['revision']),'--data',json.dumps({'retry_count':1,'max_retries':3}))
            if task_id=='implementation':write_utility(rt.workspace)
            checks=run_utility(rt);self.checks=checks
            rt.cli('update',task_id,'completed','--claim-token',claim['token'],'--evidence',json.dumps({'adapter':'scripted fixture; not live model QA','observed_checks':checks}))
        assert rt.call('inspect',run_id=self.run_id)['current_specification_hash']==execute['specification_hash'],'Default Task budget changed semantic hash'
        self.complete(execute,'executed',{'implementation':{'content':{'scope_id':'feature','specification_hash':fresh}}},checks=self.checks)
        gate=self.next('code-gate');assert gate['phase_id']=='implementation-validation';self.complete(gate,'code-gated',stage='implementation',checks=self.checks)
        snapshot=rt.call('show',run_id=self.run_id);assert snapshot['run']['status']=='passed'
        rt.cli('update','feature','completed','--evidence',json.dumps({'workflow_run':self.run_id,'checks':self.checks}))
        rt.cli('update','plan','completed','--evidence',json.dumps({'workflow_run':self.run_id,'checks':self.checks}))
        return {'run_id':self.run_id,'status':'passed','checks':self.checks,'snapshot_cursor':snapshot['cursor'],
                'phase_attempts':len(snapshot['attempts']),'work_complete':True,'default_budget_regression':'passed',
                'adapter':'scripted_adapter','human':'scripted_user_fixture' if self.strategy=='piqard' else None,'live_model_test':False}


def write_utility(root):
    (root/'clamp.py').write_text('''import math\ndef clamp(value, lower, upper):\n    values=(value,lower,upper)\n    if any(type(x) not in (int,float) for x in values):\n        raise TypeError("finite numbers required")\n    if any(type(x) is float and not math.isfinite(x) for x in values):\n        raise ValueError("finite numbers required")\n    if lower>upper:\n        raise ValueError("lower must not exceed upper")\n    return min(max(value,lower),upper)\n''')
    (root/'test_clamp.py').write_text('''import pytest\nfrom clamp import clamp\n@pytest.mark.parametrize("value,lo,hi,expected",[(-2,0,5,0),(2,0,5,2),(8,0,5,5),(3,3,3,3),(0.5,0.,1.,0.5)])\ndef test_boundaries(value,lo,hi,expected):\n    assert clamp(value,lo,hi)==expected\n@pytest.mark.parametrize("invalid",[True,None,"1",[],{}])\ndef test_invalid_types(invalid):\n    with pytest.raises(TypeError):clamp(invalid,0,1)\ndef test_nonfinite_and_reversed():\n    for bad in [float("nan"),float("inf"),-float("inf")]:\n        with pytest.raises(ValueError):clamp(bad,0,1)\n    with pytest.raises(ValueError):clamp(1,3,2)\ndef test_range_matrix():\n    for low in range(-3,4):\n        for high in range(low,5):\n            for value in range(-5,7):\n                result=clamp(value,low,high)\n                assert low<=result<=high\n                if low<=value<=high:assert result==value\n''')


def run_utility(rt):
    checks=[]
    for label,argv in [('pytest',[rt.python,'-m','pytest','test_clamp.py','-q']),
                       ('compile',[rt.python,'-m','compileall','-q','clamp.py']),
                       ('example',[rt.python,'-c','from clamp import clamp; assert clamp(12,0,9)==9; print("example passed")'])]:
        rt.run(argv,label)
        checks.append({'command':argv,'exit_code':0,'source':'actual isolated fixture subprocess','observed':True,'required':True})
    return checks


async def mcp_once(payload):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    params=StdioServerParameters(command=sys.executable,args=['-I','-m','spoq_server','mcp','--root',payload['root']],env=clean_env())
    async with stdio_client(params) as (r,w):
        async with ClientSession(r,w) as session:
            await session.initialize();response=await session.call_tool(payload['tool'],payload['arguments'])
            value=response.structuredContent
            if value is None:
                try:value=json.loads(response.content[0].text)
                except ValueError:value=response.content[0].text
            elif set(value)=={'result'}:value=value['result']
            return {'ok':not response.isError,'value':value}


def fault_worker(payload):
    """Pause real installed engine transactions; parent terminates this process."""
    from spoq_server.v1.store import Store
    from spoq_server.v1.workflows.recovery import WorkflowEngine
    from spoq_server.v1.workflows.artifacts import ArtifactRepository
    import spoq_server.v1.workflows.repository as repository
    store=Store(Path(payload['root'])/'.spoq/spoq.db');engine=WorkflowEngine(store)
    original=repository.transaction
    def marker(db=None):
        data={'pid':os.getpid(),'stage':payload['stage'],'action':payload['action']}
        path=Path(payload['marker']);temp=path.with_suffix('.temporary');temp.write_text(json.dumps(data));os.replace(temp,path)
        while True:time.sleep(.02)
    @contextmanager
    def stopped(path,*,write=False):
        with original(path,write=write) as db:
            yield db
            if write and payload['stage']=='before_commit':marker(db)
        if write and payload['stage']=='after_commit':marker()
    repository.transaction=stopped
    action=payload['action'];args=payload['arguments']
    if action=='claim':engine.next(**args)
    elif action=='artifact':ArtifactRepository(engine.repository).register(**args)
    elif action=='decision':engine.respond(**args)
    elif action=='completion':engine.complete(**args)
    else:raise ValueError('Unknown fault action')
    raise AssertionError('Fault marker was not reached')


def kill_at_boundary(python,payload,out,*,expected_prefix=None,expected_origin=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    payload={**payload,'marker':str(out/'ready.json'),'expected_prefix':expected_prefix,'expected_origin':expected_origin}
    config=out/'fault.json';config.write_text(json.dumps(payload));Path(payload['marker']).unlink(missing_ok=True)
    process=subprocess.Popen([str(python),'-I',str(SCRIPT),'--fault',str(config)],cwd=out,env=clean_env(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    started=time.monotonic()
    try:
        deadline=started+20
        while not Path(payload['marker']).is_file():
            if process.poll() is not None:
                stdout,stderr=process.communicate();raise RuntimeError('Fault worker exited before marker: '+stderr[-2000:])
            if time.monotonic()>deadline:raise TimeoutError('Fault boundary was not reached')
            time.sleep(.02)
        marker=json.loads(Path(payload['marker']).read_text());assert marker['pid']==process.pid
        process.kill();stdout,stderr=process.communicate(timeout=10)
        assert process.returncode!=0
        return {'action':payload['action'],'stage':payload['stage'],'exit_code':process.returncode,
                'seconds':round(time.monotonic()-started,3),'instrumentation':'test-only transaction boundary wrapper'}
    finally:
        if process.poll() is None:process.kill();process.communicate(timeout=10)


def negative_checks(rt):
    fixture=WorkflowFixture(rt,run_id='negative',strategy='classic');fixture.prepare()
    failure=[{'command':[rt.python,'-c','raise SystemExit(7)'],'exit_code':7,'source':'actual negative fixture subprocess','observed':True,'required':True}]
    rt.run(failure[0]['command'],'required-negative',expect=1)
    for number in range(1,4):
        call=fixture.next('plan-'+str(number));assert call['phase_id']=='plan'
        fixture.complete(call,'planned-'+str(number),{'project_plan':{'content':{'scope_id':'feature','specification_hash':call['specification_hash']}}})
        gate=fixture.next('gate-'+str(number));result=fixture.complete(gate,'failed-'+str(number),stage='plan',checks=failure,passed=False)
        assert result['outcome']=='fail'
        assert fixture.complete(gate,'failed-'+str(number),stage='plan',checks=failure,passed=False)==result
    stopped=fixture.next('exhausted');assert stopped['status']=='blocked'
    assert fixture.next('exhausted')==stopped
    attempts=rt.call('history',run_id='negative')['items'];assert len(attempts)==6
    return {'status':'expected_blocked','attempts':len(attempts),'required_exit_code':7,'live_model_test':False}


def install(artifact,out,python='3.12'):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True);prefix=out/'venv'
    for argv in [['uv','venv','--python',python,str(prefix)],['uv','pip','install','--python',str(prefix/('Scripts/python.exe' if os.name=='nt' else 'bin/python')),'spoq @ '+Path(artifact).resolve().as_uri(),'pytest']]:
        p=subprocess.run(argv,cwd=out,env=clean_env(),capture_output=True,text=True,timeout=180)
        if p.returncode:raise RuntimeError(p.stderr[-2000:])
    executable=prefix/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    rt=InstalledRuntime(executable,out,out/'setup',expected_prefix=prefix)
    origin=rt.run([executable,'-I',SCRIPT,'--origin',str(prefix)],'origin',cwd=out)
    # Artifact selection is release metadata; strategy schema versions remain pinned.
    expected = Path(artifact).name.removeprefix('spoq-').removesuffix('-py3-none-any.whl').removesuffix('.tar.gz')
    assert origin['version'] == expected
    rt.run(['uv','pip','check','--python',executable],'dependencies',cwd=out)
    return executable,prefix,origin



def fault_fixture(root,action):
    """Construct honest, scripted preconditions via the installed public API."""
    from spoq_server.v1.store import Store
    from spoq_server.v1.workflows.recovery import WorkflowEngine
    root=Path(root);store=Store(root/'.spoq/spoq.db');store.create('project_plan','plan','Fault fixture plan')
    store.create('feature','feature','Fault fixture feature','plan')
    engine=WorkflowEngine(store);engine.start('fault','feature',{'uncertainty':'high' if action=='decision' else 'low'},
                                            strategy='piqard' if action=='decision' else 'classic')
    if action=='claim':return store,engine,{'run_id':'fault','actor':'orchestrator','key':'fault-claim','ttl':1}
    call=engine.next('fault','orchestrator',key='initial',ttl=1)
    if action=='decision':
        engine.complete('fault',call['attempt_id'],call['token'],'orchestrator',key='discovered',evidence=evidence(call),
                        outputs={'discovery':{'content':'Scripted fault-test discovery'}})
        draft=engine.next('fault','orchestrator',key='draft',ttl=1200)
        narrative={k:['Recorded scripted '+k] for k in ('scope','decisions','assumptions','risks','acceptance_criteria')}
        engine.complete('fault',draft['attempt_id'],draft['token'],'orchestrator',key='drafted',evidence=evidence(draft),outputs={'narrative_plan':{'content':narrative}})
        review=engine.next('fault','orchestrator',key='review');artifact=review['inputs']['narrative_plan']
        return store,engine,{'run_id':'fault','attempt_id':review['attempt_id'],'artifact_id':artifact['id'],
            'artifact_hash':artifact['sha256'],'decision':'approve','author':'Scripted User Fixture','key':'fault-decision',
            'source':'user','user_confirmed':True,'reason':''}
    content={'scope_id':'feature','specification_hash':call['specification_hash']}
    if action=='artifact':return store,engine,{'run_id':'fault','attempt_id':call['attempt_id'],'kind':'project_plan',
        'content':json.dumps(content),'author':'orchestrator','key':'fault-artifact','expected_revision':engine.get('fault')['revision']}
    return store,engine,{'run_id':'fault','attempt_id':call['attempt_id'],'token':call['token'],'actor':'orchestrator',
        'key':'fault-completion','evidence':evidence(call),'outputs':{'project_plan':{'content':content}}}


def wait_expiry(engine):
    active=engine.inspect('fault')['active_attempts']
    expiry=next(row['lease_until'] for row in active if row['status']=='running')
    delay=max(0,expiry-time.time()+.05)
    if delay>2:raise AssertionError('Fault fixture accidentally used a long lease')
    time.sleep(delay)
    return engine.next('fault','orchestrator',key='recover-after-kill',recover=True,ttl=1200)


def run_fault_case(out,action,stage,*,expected_prefix=None,expected_origin=None):
    from spoq_server.v1.workflows.artifacts import ArtifactRepository
    out=Path(out);root=out/'workspace';store,engine,arguments=fault_fixture(root,action)
    before=store.snapshot()
    result=kill_at_boundary(sys.executable,{'root':str(root),'action':action,'stage':stage,'arguments':arguments},out/'worker',
                            expected_prefix=expected_prefix,expected_origin=expected_origin)
    if stage=='before_commit':assert store.snapshot()==before,'Uncommitted crash published partial state'
    if action=='claim':
        original=engine.next(**arguments)
        recovered=wait_expiry(engine)
        assert recovered['attempt_id']==original['attempt_id'] and recovered['token']!=original['token']
        try:
            engine.complete('fault',original['attempt_id'],original['token'],'orchestrator',key='stale-after-kill',evidence=evidence(original),
                            outputs={'project_plan':{'content':{'scope_id':'feature','specification_hash':original['specification_hash']}}})
        except ValueError:pass
        else:raise AssertionError('A stale receipt token advanced the phase')
        assert len(engine.inspect('fault')['active_attempts'])==1
        result['stale_receipt_refused']=True
    elif action=='artifact':
        artifact=ArtifactRepository(engine.repository).register(**arguments)
        assert ArtifactRepository(engine.repository).register(**arguments)==artifact
        recovered=wait_expiry(engine)
        assert any(row['id']==artifact['id'] for row in recovered['prior_artifacts'])
        engine.complete('fault',recovered['attempt_id'],recovered['token'],'orchestrator',key='complete-inspected-artifact',
                        evidence=evidence(recovered),outputs={'project_plan':{'artifact_id':artifact['id']}})
        rows=ArtifactRepository(engine.repository).list('fault');assert len(rows)==1
        result['registered_artifact_inspected_and_reused']=True
    elif action=='decision':
        response=engine.respond(**arguments);assert engine.respond(**arguments)==response
        assert engine.get('fault')['state']['phases']['plan']['ready']
        assert len(store.snapshot()['tables']['workflow_decisions'])==1
        try:engine.respond(**{**arguments,'key':'stale-decision','decision':'reject'})
        except ValueError:pass
        else:raise AssertionError('A stale human checkpoint advanced again')
        result['committed_human_fixture_replayed_once']=True
    else:
        if stage=='before_commit':
            recovered=wait_expiry(engine);arguments={**arguments,'token':recovered['token'],'evidence':evidence(recovered)}
        response=engine.complete(**arguments);assert engine.complete(**arguments)==response
        snapshot=store.snapshot()
        assert sum(row['phase_id']=='plan' for row in snapshot['tables']['workflow_attempts'])==1
        assert len(snapshot['tables']['workflow_artifacts'])==1 and len(snapshot['tables']['journal_entries'])==1
        assert engine.next('fault','orchestrator',key='advance-after-restart')['phase_id']=='plan-validation'
        result['completed_work_not_reinvoked']=True
    result.update(passed=True,adapter='scripted_adapter',human='scripted_user_fixture' if action=='decision' else None)
    return result


def fault_suite(out,*,expected_prefix=None,expected_origin=None):
    cases=[]
    for action in ('claim','artifact','decision','completion'):
        for stage in ('before_commit','after_commit'):
            cases.append(run_fault_case(Path(out)/(action+'-'+stage),action,stage,
                                        expected_prefix=expected_prefix,expected_origin=expected_origin))
    return {'passed':all(case['passed'] for case in cases),'cases':cases,
            'boundary':'Decision/artifact/journal/state/event/receipt writes share atomic transactions; no independent model or human execution.',
            'external_effects':'No general exactly-once guarantee is claimed for external side effects.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact',type=Path);parser.add_argument('--out',type=Path);parser.add_argument('--python',default='3.12')
    for mode in ('mcp','evidence','fault','origin','fault_suite'):parser.add_argument('--'+mode.replace('_','-'))
    args=parser.parse_args()
    if args.origin:print(json.dumps(check_origin(args.origin)));return
    for mode in ('mcp','evidence','fault','fault_suite'):
        value=getattr(args,mode)
        if value:
            payload=json.loads(Path(value).read_text());check_origin(payload.get('expected_prefix'),payload.get('expected_origin'))
            if mode=='mcp':result=asyncio.run(mcp_once(payload))
            elif mode=='evidence':result=evidence(payload['envelope'],payload.get('checks'),stage=payload.get('stage'),passed=payload.get('passed',True))
            elif mode=='fault_suite':result=fault_suite(payload['out'],expected_prefix=payload.get('expected_prefix'),expected_origin=payload.get('expected_origin'))
            else:result=fault_worker(payload)
            print(json.dumps(result));return
    if args.artifact is None or args.out is None:parser.error('--artifact and --out are required')
    out=args.out.resolve();artifact=args.artifact.resolve();started=time.monotonic()
    report={'artifact':str(artifact),'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),
            'adapter':'scripted_adapter','human':'scripted_user_fixture','live_model_test':False,'cases':{},'passed':False}
    try:
        session=out/('session-'+str(time.time_ns()));session.mkdir(parents=True);report['session']=str(session)
        python,prefix,origin=install(artifact,session,args.python);report['installed']=origin;report['installed']['prefix']=str(prefix)
        for strategy,transport in [('classic','cli'),('piqard','mcp')]:
            rt=InstalledRuntime(python,session/strategy,session/(strategy+'-logs'),expected_prefix=prefix,transport=transport)
            fixture=WorkflowFixture(rt,run_id=strategy,strategy=strategy);fixture.prepare()
            if strategy=='piqard':
                fixture.to_review();fixture.response('approve','unattested',confirmed=False,expect=1)
                fixture.response('approve','peer-refusal',source='peer',expect=1)
                fixture.reject_and_revise();fixture.approve()
            report['cases'][strategy]=fixture.deliver();report['cases'][strategy]['commands']=rt.commands
        rt=InstalledRuntime(python,session/'negative',session/'negative-logs',expected_prefix=prefix)
        report['cases']['negative']=negative_checks(rt);report['cases']['negative']['commands']=rt.commands
        config=session/'fault-suite.json';config.write_text(json.dumps({'out':str(session/'faults'),'expected_prefix':str(prefix)}))
        report['cases']['faults']=rt.run([python,'-I',SCRIPT,'--fault-suite',config],'fault-suite',cwd=session)
        assert len(report['cases']['faults']['cases'])==8
        report['passed']=True
    except Exception as exc:
        report['error']=str(exc);raise
    finally:
        out.mkdir(parents=True,exist_ok=True);report['seconds']=round(time.monotonic()-started,3)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'report':str(out/'result.json')}))


if __name__=='__main__':main()
