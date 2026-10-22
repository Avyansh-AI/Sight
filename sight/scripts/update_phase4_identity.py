"""One-time phase identity update; original home UI is untouched."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for name in ('sight_core/api.py','sight_core/cli.py','scripts/verify.py','sight_core/mcp_bridge.py'):
    path=ROOT/name
    value=path.read_text(encoding='utf-8').replace('"phase": 3','"phase": 4').replace("'version':'0.3.0'","'version':'0.4.0'").replace('"version": "0.3.0"','"version": "0.4.0"')
    if name=='scripts/verify.py':
        value=value.replace('PHASE3_READINESS','PHASE4_READINESS').replace('live_phase3_latest','live_phase4_latest').replace('"Phase 4", ','')
        # The richer dependency SBOM is written by dependency_audit.py.
        value=value.replace('reports/sbom.cdx.json','reports/test_environment_sbom.cdx.json')
    path.write_text(value,encoding='utf-8')
