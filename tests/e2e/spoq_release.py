"""Verify an installed wheel or sdist in an isolated environment (requires uv)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact',type=Path,required=True)
    parser.add_argument('--python',default='3.12')
    parser.add_argument('--extras',default='')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    artifact=args.artifact.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    root=Path(__file__).resolve().parents[2]
    env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','SPOQ_STORE','SPOQ_PROJECT_ROOT','VIRTUAL_ENV'}}
    results=[]
    def run(argv,label):
        started=time.monotonic()
        result=subprocess.run(argv,cwd=out,env=env,capture_output=True,text=True,timeout=600)
        (out/(label+'.stdout')).write_text(result.stdout)
        (out/(label+'.stderr')).write_text(result.stderr)
        results.append({'label':label,'argv':argv,'exit_code':result.returncode,'seconds':round(time.monotonic()-started,3)})
        if result.returncode:
            raise RuntimeError(f'{label} failed; inspect {out}')
        return result.stdout
    report={'artifact':str(artifact),'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),
            'python':args.python,'extras':args.extras,'commands':results}
    try:
        run(['uv','venv','--python',args.python,str(out/'venv')],'venv')
        python=str(out/('venv/Scripts/python.exe' if os.name=='nt' else 'venv/bin/python'))
        requirement='spoq'+('['+args.extras+']' if args.extras else '')+' @ '+artifact.as_uri()
        run(['uv','pip','install','--python',python,requirement,'pytest'],'install')
        observed=run([python,'-c','import spoq_server,sys,json;print(json.dumps({"module":spoq_server.__file__,"version":spoq_server.__version__,"python":sys.version}))'],'origin')
        report['installed']=json.loads(observed)
        assert Path(report['installed']['module']).is_relative_to(out/'venv')
        run(['uv','pip','check','--python',python],'dependency-check')
        run([python,'-m','compileall','-q',str(Path(report['installed']['module']).parent)],'compile')
        run([python,'-m','pytest',str(root/'code/mcp/spoq-server/tests'),'-q','-ra',f'--junitxml={out/"junit.xml"}'],'pytest')
        report['passed']=True
    except Exception as exc:
        report['passed']=False;report['error']=str(exc)
        raise
    finally:
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'report':str(out/'result.json'),'tests':(out/'pytest.stdout').read_text().splitlines()[-1]}))


if __name__=='__main__': main()
