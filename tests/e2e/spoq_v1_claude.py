"""Claude Code configuration/skill/MCP checks without a model account."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spoq',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    project=out/'project';project.mkdir(exist_ok=True)
    claude=shutil.which('claude')
    if not claude: raise RuntimeError('Install Claude Code to run this optional client check')
    env={**os.environ,'PATH':str(args.spoq.resolve().parent)+os.pathsep+os.environ.get('PATH',''),
         'CLAUDE_CONFIG_DIR':str(out/'claude-profile'),'DISABLE_TELEMETRY':'1',
         'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC':'1','SPOQ_STORE':'sqlite'}
    results=[]
    def run(argv,label):
        result=subprocess.run(argv,cwd=project,env=env,capture_output=True,text=True,timeout=90)
        (out/(label+'.stdout')).write_text(result.stdout)
        (out/(label+'.stderr')).write_text(result.stderr)
        results.append({'label':label,'argv':argv,'exit_code':result.returncode})
        if result.returncode: raise RuntimeError(f'{label} failed; inspect {out}')
        return result.stdout
    value={'inference_tested':False,'reason':'No Claude account; user requested documentation-based validation.',
           'commands':results,'documentation':['https://code.claude.com/docs/en/skills','https://code.claude.com/docs/en/mcp']}
    try:
        value['claude_version']=run([claude,'--version'],'version').strip()
        run([str(args.spoq.resolve()),'init','--target',str(project),'--agents','claude','--with-mcp'],'init')
        run([claude,'plugin','validate',str(project/'.claude/skills')],'skills')
        # Explicit test-only approval is needed for health checks in an untrusted
        # temp folder. This never changes the user's profile or shipped settings.
        settings=out/'test-settings.json';settings.write_text(json.dumps({'enabledMcpjsonServers':['spoq']}))
        env['SPOQ_STORE']='fs'  # Generated registration must pin its intended backend.
        status=run([claude,'--settings',str(settings),'mcp','get','spoq'],'mcp')
        assert 'Connected' in status and 'Failed to connect' not in status,status
        value['passed']=True
    except Exception as exc:
        value['passed']=False;value['error']=str(exc)
        raise
    finally:
        (out/'result.json').write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps({'passed':True,'inference_tested':False,'report':str(out/'result.json')}))


if __name__=='__main__': main()
