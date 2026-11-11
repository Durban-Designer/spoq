"""JSON workflow commands; every invocation supports an explicit workspace root."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from ..db import encode
from ..migration import database_path, get_store
from .definitions import list_strategies
from .queries import ReadModel
from .recovery import WorkflowEngine
from .routing import route
from .schema import upgrade, require_workflow_schema


def _unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('Duplicate JSON key')
        result[name] = value
    return result


def json_argument(value):
    """Use @file for reviewable payloads without fragile shell interpolation."""
    try:
        if value.startswith('@'):
            with Path(value[1:]).expanduser().open('rb') as handle:
                data = handle.read(1024 * 1024 + 1)
        else:
            data = value.encode()
        if len(data) > 1024 * 1024:
            raise ValueError('JSON input exceeds one MiB')
        def nonfinite(_):
            raise ValueError('JSON numbers must be finite')
        return json.loads(data, object_pairs_hook=_unique, parse_constant=nonfinite)
    except (ValueError, OSError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--root', default=argparse.SUPPRESS, help='Explicit project workspace')
    result = argparse.ArgumentParser(prog='spoq workflow', parents=[common],
        description='Run versioned Classic/PIQARD strategies. A connected coding client executes returned skills.')
    commands = result.add_subparsers(dest='action', required=True)
    def command(name, help):
        return commands.add_parser(name, help=help, parents=[common])
    def mutation(p, *, agent=True):
        p.add_argument('--key', required=True, help='Stable operation key; reuse only for the identical request')
        p.add_argument('--revision', type=int, help='Expected workflow revision')
        if agent: p.add_argument('--agent', default='orchestrator')
    def query(p):
        p.add_argument('--limit', type=int, default=100)
        p.add_argument('--before', type=int)
    p = command('list', 'List saved runs or bundled strategies')
    p.add_argument('--strategies', action='store_true');p.add_argument('--scope', default='')
    p.add_argument('--limit', type=int, default=100);p.add_argument('--after', default='')
    p = command('show', 'Read an authoritative graph snapshot and committed event cursor');p.add_argument('run_id');query(p)
    p = command('inspect', 'Read interruption diagnostics without starting work');p.add_argument('run_id')
    p = command('route', 'Explain deterministic routing without starting a run')
    p.add_argument('--inputs', type=json_argument, default={});p.add_argument('--strategy', choices=['classic','piqard'])
    p = command('start', 'Pin a strategy and routing inputs for a scope')
    p.add_argument('run_id');p.add_argument('--scope', required=True);p.add_argument('--inputs', type=json_argument, default={})
    p.add_argument('--strategy', choices=['classic','piqard']);p.add_argument('--key', required=True);p.add_argument('--agent', default='orchestrator')
    p = command('next', 'Claim a ready phase or inspect an existing invocation')
    p.add_argument('run_id');mutation(p);p.add_argument('--phase');p.add_argument('--ttl',type=int,default=300);p.add_argument('--recover',action='store_true')
    p = command('renew', 'Renew a current phase lease')
    p.add_argument('run_id');p.add_argument('attempt_id');p.add_argument('--token', required=True);mutation(p);p.add_argument('--ttl',type=int,default=300)
    p = command('complete', 'Submit observed evidence and declared outputs; gates compute their own artifact')
    p.add_argument('run_id');p.add_argument('attempt_id');p.add_argument('--token',required=True);mutation(p)
    p.add_argument('--evidence',type=json_argument,required=True);p.add_argument('--outputs',type=json_argument,default={})
    p.add_argument('--outcome',choices=['pass','fail'],default='pass');p.add_argument('--refresh-spec',action='store_true',help='Accept generated planning output when original scope inputs are unchanged')
    p = command('respond', 'Relay an actual user response for an exact reviewed artifact revision')
    p.add_argument('run_id');p.add_argument('attempt_id');mutation(p,agent=False)
    p.add_argument('--artifact',required=True);p.add_argument('--hash',required=True,dest='artifact_hash')
    p.add_argument('--decision',choices=['approve','reject'],required=True);p.add_argument('--author',required=True)
    p.add_argument('--source',choices=['user'],required=True);p.add_argument('--user-confirmed',action='store_true')
    p.add_argument('--reason',default='')
    p = command('pause', 'Stop new dispatch while preserving in-flight work')
    p.add_argument('run_id');mutation(p);p.add_argument('--reason',default='')
    p = command('resume', 'Resume persisted work without resetting exhausted budgets')
    p.add_argument('run_id');mutation(p);p.add_argument('--refresh-spec',action='store_true',help='Invalidate changed criteria; changed goals require successor routing')
    p.add_argument('--retry-phase')
    p = command('propose', 'Record a safe-boundary successor strategy proposal without adopting it')
    p.add_argument('run_id');mutation(p);p.add_argument('--inputs',type=json_argument,required=True)
    p.add_argument('--strategy',choices=['classic','piqard']);p.add_argument('--reason',required=True)
    p = command('events', 'Read ordered bounded event replay; global sequence gaps are normal')
    p.add_argument('run_id');p.add_argument('--after',type=int,default=0);p.add_argument('--limit',type=int,default=100)
    p = command('history', 'Read bounded attempt, artifact, decision or participant history')
    p.add_argument('run_id');query(p);p.add_argument('--resource',choices=['attempts','artifacts','decisions','participants'],default='attempts')
    p = command('work', 'Read a page of linked Feature/Task work DAGs')
    p.add_argument('run_id');p.add_argument('--after',default='');p.add_argument('--limit',type=int,default=500)
    p = command('artifact', 'Read one registered text artifact')
    p.add_argument('run_id');p.add_argument('artifact_id')
    p = command('attempt', 'Read one attempt and its evidence')
    p.add_argument('run_id');p.add_argument('attempt_id')
    p = command('node', 'Read one scoped work node and its acceptance criteria')
    p.add_argument('run_id');p.add_argument('node_id')
    p = command('upgrade', 'Preview or explicitly confirm the backed-up schema 1→2 upgrade')
    p.add_argument('--yes',action='store_true');p.add_argument('--dry-run',action='store_true')
    return result


def dispatch(argv):
    from ..cli import resolve_root
    args = parser().parse_args(argv)
    root = resolve_root(getattr(args, 'root', None))
    path = database_path(root)
    query = ReadModel(path)
    try:
        action = args.action
        if action == 'route': result = route(args.inputs,args.strategy)
        elif action == 'list': result = list_strategies() if args.strategies else query.runs(args.scope,args.limit,args.after)
        elif action == 'upgrade': result = upgrade(path,confirmed=args.yes and not args.dry_run)
        elif action == 'show': result = query.snapshot(args.run_id,args.limit,args.before)
        elif action == 'events': result = query.events(args.run_id,args.after,args.limit)
        elif action == 'history': result = query.history(args.run_id,args.resource,args.before,args.limit)
        elif action == 'work': result = query.work(args.run_id,args.after,args.limit)
        elif action == 'artifact': result = query.artifact(args.run_id,args.artifact_id)
        elif action == 'attempt': result = query.attempt(args.run_id,args.attempt_id)
        elif action == 'node': result = query.node(args.run_id,args.node_id)
        elif action == 'inspect': result = query.inspect(args.run_id)
        else:
            if not path.is_file():
                raise ValueError('Initialize and create the scope before workflow mutations; legacy work needs a reviewed `spoq migrate --dry-run` conversion first')
            require_workflow_schema(path)
            engine = WorkflowEngine(get_store(root))
            if action == 'start': result = engine.start(args.run_id,args.scope,args.inputs,strategy=args.strategy,key=args.key,actor=args.agent)
            elif action == 'next': result = engine.next(args.run_id,args.agent,key=args.key,expected_revision=args.revision,phase_id=args.phase,ttl=args.ttl,recover=args.recover)
            elif action == 'renew': result = engine.renew(args.run_id,args.attempt_id,args.token,args.agent,key=args.key,expected_revision=args.revision,ttl=args.ttl)
            elif action == 'complete': result = engine.complete(args.run_id,args.attempt_id,args.token,args.agent,key=args.key,evidence=args.evidence,outputs=args.outputs,outcome=args.outcome,expected_revision=args.revision,refresh_spec=args.refresh_spec)
            elif action == 'respond': result = engine.respond(args.run_id,args.attempt_id,args.artifact,args.artifact_hash,args.decision,args.author,key=args.key,source=args.source,user_confirmed=args.user_confirmed,expected_revision=args.revision,reason=args.reason)
            elif action == 'pause': result = engine.pause(args.run_id,args.agent,key=args.key,expected_revision=args.revision,reason=args.reason)
            elif action == 'resume': result = engine.resume(args.run_id,args.agent,key=args.key,expected_revision=args.revision,refresh_spec=args.refresh_spec,retry_phase=args.retry_phase)
            elif action == 'propose': result = engine.propose_route(args.run_id,args.inputs,key=args.key,actor=args.agent,reason=args.reason,preference=args.strategy,expected_revision=args.revision)
        print(encode(result))
        return True
    except (ValueError,OSError,sqlite3.Error) as exc:
        print('Error: '+str(exc),file=sys.stderr)
        raise SystemExit(1) from exc


def dispatch_ui(argv):
    from ..cli import resolve_root
    from .viewer import serve
    p=argparse.ArgumentParser(prog='spoq ui',description='Open the local read-only workflow viewer; no Node runtime or hosted service')
    p.add_argument('--root');p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=0,help='Port, or 0 to choose an available port (default)')
    p.add_argument('--run',dest='run_id');p.add_argument('--no-open',action='store_true')
    args=p.parse_args(argv)
    try:
        serve(resolve_root(args.root),host=args.host,port=args.port,open_browser=not args.no_open,run_id=args.run_id)
        return True
    except (ValueError,OSError) as exc:
        print('Error: '+str(exc),file=sys.stderr);raise SystemExit(1) from exc
