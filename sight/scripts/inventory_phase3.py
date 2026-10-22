"""Reconcile supplied archives and enumerate source candidates without executing them.

Python uses AST; JS/TS and other languages retain file-level reference dispositions
plus lexical declarations. Lexical indexing is not a complete semantic audit.
"""
import ast
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1];WORKSPACE=ROOT.parents[1]
sys.path.insert(0,str(ROOT))
from sight_core.security import redact
from sight_core.capabilities import SPECS,BLOCKED
from audit_inputs import LICENSES,safe_entries,SECRET,SENSITIVE

def write_csv(path,rows):
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

# Specific semantic correspondences are narrower than the source components.
MAPPING={1:'memory.py; learning_api.py',2:'memory.py',3:'jobs.py',4:'forge.py',6:'memory.py; routing.py',7:'memory.py',8:'memory.py',9:'forge.py',10:'capabilities.py',11:'capabilities.py',12:'memory.py',13:'jobs.py',14:'jobs.py',15:'jobs.py',16:'proactive.py',17:'releases.py',18:'capability_worker.py',20:'tools.py',22:'connector_contracts.py',23:'jobs.py',24:'routing.py',27:'jobs.py',28:'forge.py',29:'jobs.py',30:'forge.py',31:'forge.py',32:'learning_api.py',33:'forge.py',34:'proactive.py',35:'routing.py',36:'skill_worker.py',37:'tools.py',38:'jobs.py',40:'capability_worker.py',41:'models.py',42:'local_adapters.py',43:'memory.py',44:'proactive.py',46:'local_adapters.py',48:'connector_contracts.py',49:'connector_contracts.py',51:'memory.py',52:'models.py',53:'releases.py',56:'local_adapters.py',57:'local_adapters.py',59:'connector_contracts.py',60:'proactive.py',61:'local_adapters.py',62:'capabilities.py',64:'brain_store.py',65:'local_adapters.py',66:'connector_contracts.py',68:'memory.py',70:'capability_worker.py',71:'models.py',72:'models.py',74:'capability_worker.py',75:'proactive.py',76:'proactive.py',77:'connector_contracts.py'}
LIMITS={16:'Fixed UTC intervals only; local timezone/DST cron expressions not implemented',18:'Offline owner-supplied HTML, field fill and screenshot only; no external browsing',19:'CDP endpoint unconfigured; no live session attachment',20:'Allowlisted app launch/clipboard only; input/screenshot pending',21:'External connector transport unconfigured',22:'Pinned MCP 2025-06-18 contract only; no production transport',34:'Local disk change monitor only',37:'Allowlisted app launch/clipboard only',39:'Active application adapter pending',40:'Installed SAPI WAV render only; no microphone/STT/barge-in',42:'Supplied landmark calculation only; no camera control',44:'Local disk checks only; device monitors unavailable',45:'No recording pipeline or participant consent',46:'Plain DOCX/Markdown only; spreadsheet/presentation/PDF engines pending',47:'Safe file workspace only; folder organization/undo pending',48:'Ephemeral simulator pairing only; no QR or network gateway',49:'Simulator scope/revoke checks only',50:'In-app reminders only; no OS notification ingestion',55:'Existing explicit clipboard read only; no sentry monitoring',56:'Ideal low-voltage resistor arithmetic only; no circuit assembly or energizing',57:'Supplied-coordinate spherical distance only; live feeds disabled',58:'Call transport and participant consent absent',59:'Trust simulator only; no mobile action transport',60:'Opt-in local disk state alerts and quiet hours only',61:'Escaped static HTML draft only; no publish',62:'Actual local reminders; online feeds explicitly unavailable',63:'No authorized game updater or download policy',65:'Analytic cuboid STL only; no arbitrary generated Python or iterative CAD kernel',66:'No real slicer or printer; build/profile contracts simulated',67:'No face capture/recognition; never sole authorization',69:'No paired Kasa device',70:'Isolated offline HTML only',73:'No STT model/microphone pipeline; wake enrollment later',74:'Offline WAV output only; end-to-end microphone command unverified',75:'Durable in-app reminders only; no light control',76:'UTC once/interval reminders; local DST alarms pending',77:'No paired Kasa device; trust contract only'}

def main():
    reports=ROOT/'reports';reports.mkdir(exist_ok=True)
    files=[];matrix=[];skills=[];archives=[];parse_gaps=[];known={};source_functions=0;declarations=0
    lookup={}
    for archive in sorted(LICENSES):
        path=WORKSPACE/'references/archives'/archive
        with zipfile.ZipFile(path) as z:
            members=safe_entries(z);count=0
            for member in members:
                if member.is_dir():continue
                relative=PurePosixPath(*PurePosixPath(member.filename).parts[1:]).as_posix()
                content=z.read(member);digest=hashlib.sha256(content).hexdigest();count+=1
                disk=WORKSPACE/'references/repos'/archive.removesuffix('.zip')/relative
                matching=disk.is_file() and hashlib.sha256(disk.read_bytes()).hexdigest()==digest
                sensitive=bool(SECRET.search(content) or SENSITIVE.search(relative));license=LICENSES[archive]
                disposition='RESTRICTED' if sensitive or license!='MIT' else 'REFERENCE_ONLY'
                files.append({'archive':archive,'path':relative,'sha256':digest,'bytes':len(content),'extracted_matches':matching,'rights':license,'sensitive':sensitive,'disposition':disposition,'execution':'never executed'})
                lookup[(archive,relative)]={'sha256':digest,'matches':matching}
                suffix=PurePosixPath(relative).suffix.lower()
                def row(symbol,line,kind,signature,status=disposition,reason='Unintegrated reference; semantic review and acceptance tests required before activation'):
                    key=hashlib.sha256(signature.encode()).hexdigest();duplicate=known.get(key,'')
                    identifier='source.'+hashlib.sha256((archive+relative+symbol+str(line)).encode()).hexdigest()[:20]
                    if not sensitive:known.setdefault(key,identifier)
                    matrix.append({'capability_id':identifier,'archive':archive,'source_path':relative,'symbol':symbol,'line':line,'kind':kind,'sha256':key,'capability':symbol or relative,'phase':'3','status':'DUPLICATE' if duplicate else status,'duplicate_of':duplicate,'permission_scope':'none; not executable','required_tests':'Semantic review; typed permission and family acceptance tests before activation','active_implementation':'none','reason':reason,'rights':license})
                if suffix in {'.py','.js','.jsx','.ts','.tsx','.ps1','.sh','.java','.kt','.rs','.c','.cpp'}:
                    row('',0,'source-file',digest)
                if sensitive or len(content)>2_000_000:continue
                text=content.decode('utf-8-sig',errors='replace')
                if suffix=='.py':
                    try:tree=ast.parse(text)
                    except (SyntaxError,ValueError,RecursionError):parse_gaps.append({'archive':archive,'path':relative,'reason':'Python parse failed; file retained reference-only'});continue
                    def walk(node,prefix=''):
                        nonlocal source_functions
                        for child in ast.iter_child_nodes(node):
                            label=prefix
                            if isinstance(child,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
                                label=prefix+child.name+'.'
                                if not isinstance(child,ast.ClassDef):
                                    source_functions+=1;row(label[:-1],child.lineno,'python-function',ast.dump(child,include_attributes=False))
                            walk(child,label)
                    walk(tree)
                elif suffix in {'.js','.jsx','.ts','.tsx','.ps1','.sh','.java','.kt','.rs','.c','.cpp'}:
                    pattern=r'(?:\b(?:function|def|fn|fun)\s+([A-Za-z_$][\w$]*)|\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^\n]{0,300}\)|\w+)\s*=>)'
                    for match in re.finditer(pattern,text):
                        declarations+=1;row(next(v for v in match.groups() if v),text.count('\n',0,match.start())+1,'lexical-declaration',digest+':'+str(match.start()),reason='Lexical declaration only; full language semantic audit pending. Duplicate only when the entire source file and declaration offset match')
                if PurePosixPath(relative).name=='SKILL.md':
                    front=text.split('---',2)[1] if text.startswith('---') and len(text.split('---',2))==3 else ''
                    field=lambda name:next(iter(re.findall(r'^'+name+r':\s*(.*)$',front,re.M)),'').strip().strip('"\'')
                    commands=sorted(set(re.findall(r'\b(?:pip(?:3)? install|uv pip install|npm install|npx|brew install|apt install|cargo install)\s+([\w@./-]+)',text)))
                    prerequisites=re.findall(r'^\s*(?:commands|bins|tools|required_tools|env|requires):\s*(.+)$',front,re.M)
                    network=bool(re.search(r'https?://|\bAPI\b|internet|OAuth',text,re.I))
                    secrets=sorted(set(re.findall(r'\b[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)\b',text)))
                    unsafe=sorted(name for name,pattern in {'shell':'```(?:bash|sh|powershell)|subprocess|os.system','install':'pip install|npm install|brew install','delete':'rm -rf|Remove-Item|delete files','remote-write':'send message|publish|git push|upload','credentials':'password|credentials|api.key'}.items() if re.search(pattern,text,re.I))
                    skills.append({'archive':archive,'path':relative,'name':field('name') or PurePosixPath(relative).parent.name,'sha256':digest,
                        'catalog':'built-in' if relative.startswith('skills/') else 'optional' if relative.startswith('optional-skills/') else 'plugin/other',
                        'platforms':field('platforms') or 'unspecified; review required','rights':field('license') or 'root '+license+'; inspect bundled terms',
                        'prerequisites':prerequisites,'install_indicators':commands,'network_indicated':network,'secret_names':secrets,'unsafe_indicators':unsafe,
                        'status':'REFERENCE_ONLY','applicability':'Indexed guidance only; no imported executable adapter. Independent SIGHT tools may cover a narrower behavior.',
                        'activation':'disabled','classification':'Static conservative indicators; absence is not safety evidence','execution':'never executed'})
            archives.append({'archive':archive,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'files':count})
    manual=list(csv.DictReader((ROOT.parent/'evidence/manual_capability_references.csv').open(encoding='utf-8-sig')))
    for old in manual:
        number=int(old['capability_id'].split('.')[1]);found=lookup.get((old['archive'],old['source_path']))
        reason=LIMITS.get(number,'Independent bounded Phase 1/2 behavior; source component is broader; see prior acceptance evidence')
        status='PARTIAL' if number in MAPPING else 'REFERENCE_ONLY'
        if number in {45,48,49,58,59,66,67,69,73,74,77}:status='BLOCKED_HARDWARE'
        if number in {19,21,55,63}:status='DISABLED_SECURITY'
        if old['phase']=='4':status='REFERENCE_ONLY';reason='Phase 4 work is outside this implementation pass'
        if not found:status='REFERENCE_ONLY';reason='Manual path absent from current supplied archive; no implementation inferred'
        matrix.insert(number-1,{'capability_id':old['capability_id'],'archive':old['archive'],'source_path':old['source_path'],'symbol':'','line':0,'kind':'manual-reference','sha256':found['sha256'] if found else '',
            'capability':old['capability'],'phase':old['phase'],'status':status,'duplicate_of':'','permission_scope':'Owner-reviewed typed operations only; broader behavior disabled',
            'required_tests':old['required_tests'],'active_implementation':MAPPING.get(number,'none'),'reason':reason,'rights':old['rights']})
    write_csv(reports/'source_inventory.csv',files);write_csv(reports/'capability_matrix.csv',matrix)
    write_csv(reports/'skill_inventory.csv',[{k:json.dumps(v) if isinstance(v,list) else v for k,v in row.items()} for row in skills])
    (reports/'hermes_skill_inventory.json').write_text(json.dumps(redact(skills),indent=2),encoding='utf-8')
    (reports/'source_archives_current.json').write_text(json.dumps(archives,indent=2))
    hermes=[s for s in skills if s['archive']=='hermes-agent-main.zip'];counts=Counter(s['catalog'] for s in hermes)
    evidence={'archive_count':len(archives),'files':len(files),'extracted_matches':sum(r['extracted_matches'] for r in files),'manual_references':len(manual),
              'manual_paths_found':sum(bool(lookup.get((r['archive'],r['source_path']))) for r in manual),'python_function_candidates':source_functions,'lexical_declarations':declarations,
              'matrix_rows':len(matrix),'duplicate_rows':sum(r['status']=='DUPLICATE' for r in matrix),'hermes_catalogs':dict(counts),
              'hermes_expected_211':counts['built-in']+counts['optional']==211,'additional_plugin_manifests':counts['plugin/other'],
              'python_parse_gaps':parse_gaps,'semantic_coverage_complete':False,'executed_reference_code':False,
              'limits':['Sensitive source is hashed/classified but not parsed into function names','Other-language method/function coverage is lexical and incomplete; every source file is retained with a reference-only disposition','All skill metadata is conservative static classification; no automatic installation/activation','Nine ZIP files exist in references/archives; rea-main.zip is outside the eight-repository manual and remains untouched','Historical hermes_provenance.json describes a prior clone, not this supplied archive audit']}
    (reports/'phase3_inventory.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps({k:v for k,v in evidence.items() if k!='python_parse_gaps'},indent=2))

if __name__=='__main__':main()
