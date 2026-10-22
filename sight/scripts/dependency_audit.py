"""Query public OSV package versions and inventory installed distribution licenses."""
from datetime import datetime,timezone
import hashlib
from importlib.metadata import distributions
import json
from pathlib import Path
import uuid
import httpx

ROOT=Path(__file__).resolve().parents[1]

def main():
    stamp=datetime.now(timezone.utc).isoformat();rows=[]
    for dist in sorted(distributions(),key=lambda d:d.metadata.get('Name','').lower()):
        licenses=[]
        for file in dist.files or []:
            name=str(file)
            if '.dist-info/' in name and any(part.lower().startswith(('license','licence','copying','notice')) for part in Path(name).parts):
                path=Path(dist.locate_file(file))
                if path.is_file():licenses.append({'file':name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        rows.append({'name':dist.metadata['Name'],'version':dist.version,'license_expression':dist.metadata.get('License-Expression'),
                     'license_metadata':dist.metadata.get('License'),'license_classifiers':[v for v in dist.metadata.get_all('Classifier',[]) if v.startswith('License ::')],
                     'license_files':licenses,'project_urls':dist.metadata.get_all('Project-URL',[])})
    result={'timestamp_utc':stamp,'service':'https://api.osv.dev/v1/querybatch','request_scope':'Public PyPI package names and installed versions only',
            'dependencies':rows,'scan_complete':False,'vulnerabilities':[],'limitations':'Public advisory database coverage is not a security guarantee; model/runtime/browser binaries assessed separately.'}
    try:
        with httpx.Client(trust_env=False,timeout=45) as client:
            response=client.post(result['service'],json={'queries':[{'package':{'name':r['name'],'ecosystem':'PyPI'},'version':r['version']} for r in rows]})
            response.raise_for_status();findings=response.json()['results']
            if len(findings)!=len(rows):raise ValueError('Incomplete OSV response')
            for row,found in zip(rows,findings):
                row['advisory_ids']=[v['id'] for v in found.get('vulns',[])]
                for identifier in row['advisory_ids']:
                    detail=client.get('https://api.osv.dev/v1/vulns/'+identifier);detail.raise_for_status()
                    result['vulnerabilities'].append({'package':row['name'],'version':row['version'],'advisory':detail.json()})
            result['scan_complete']=True
    except (httpx.HTTPError,ValueError,KeyError,TypeError) as exc:
        result['scan_error']=type(exc).__name__
    (ROOT/'reports/dependency_audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    components=[]
    for row in rows:
        component={'type':'library','name':row['name'],'version':row['version'],'purl':'pkg:pypi/'+row['name'].lower().replace('_','-')+'@'+row['version']}
        if row['license_expression']:component['licenses']=[{'expression':row['license_expression']}]
        elif row['license_classifiers']:component['licenses']=[{'license':{'name':'; '.join(row['license_classifiers'])}}]
        elif row['license_metadata']:component['licenses']=[{'license':{'name':row['license_metadata'][:200]}}]
        components.append(component)
    sbom={'bomFormat':'CycloneDX','specVersion':'1.5','serialNumber':'urn:uuid:'+str(uuid.uuid4()),'version':1,
          'metadata':{'timestamp':stamp,'component':{'type':'application','name':'SIGHT','version':'0.4.0'}},'components':components}
    (ROOT/'reports/sbom.cdx.json').write_text(json.dumps(sbom,indent=2),encoding='utf-8')
    print(json.dumps({'packages':len(rows),'scan_complete':result['scan_complete'],'vulnerabilities':len(result['vulnerabilities']),'error':result.get('scan_error')}))

if __name__=='__main__':main()
