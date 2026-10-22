"""Launch a verified selected snapshot with the installed, matching environment."""
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sight_core.config import Config
from sight_core.releases import Releases

def main():
    config=Config.from_env()
    try:target=Releases(config.data_dir,ROOT).selected()
    except (ValueError,OSError,KeyError):
        print('Selected code snapshot failed verification; starting the installed baseline. Learning and task data are preserved.',file=sys.stderr)
        target=ROOT
    if '--check' in sys.argv:
        print(str(target));return 0
    environment=dict(os.environ)
    environment.pop('PYTHONPATH',None)
    return subprocess.run([sys.executable,'-B','-m','sight_core.cli','start']+sys.argv[1:],cwd=target,env=environment,shell=False).returncode

if __name__=='__main__':raise SystemExit(main())
