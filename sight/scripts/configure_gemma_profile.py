"""Create a separate Ollama profile from already installed weights, never download."""
import json
from pathlib import Path
import httpx
from gemma_diagnose import BASE, SYSTEM_PROMPT

ROOT=Path(__file__).resolve().parents[1]
ALIAS='sight-gemma4-e4b:uncensored'

def main():
    with httpx.Client(base_url='http://127.0.0.1:11434',trust_env=False,timeout=60) as client:
        tags=client.get('/api/tags').json()['models']
        if not any(m['name']==BASE for m in tags):raise ValueError('Required source weights are not installed; no download attempted')
        if any(m['name']==ALIAS for m in tags):raise ValueError('Profile already exists; refusing to overwrite it')
        source=client.post('/api/show',json={'model':BASE}).json()
        request={'model':ALIAS,'from':BASE,'stream':False,'renderer':'gemma4','parser':'gemma4',
                 'system':SYSTEM_PROMPT,'parameters':{'temperature':0.7,'top_p':0.9,'top_k':40,'repeat_penalty':1.1,'num_ctx':4096,'num_predict':1536,'num_batch':128,'use_mmap':True}}
        response=client.post('/api/create',json=request);response.raise_for_status()
        created=client.post('/api/show',json={'model':ALIAS}).json()
        result={'source_model':BASE,'profile_model':ALIAS,'request':request,'response':response.json(),
                'source_metadata':{k:source.get(k) for k in ('capabilities','thinking','renderer','parser','parameters')},
                'profile_metadata':{k:created.get(k) for k in ('capabilities','thinking','renderer','parser','parameters')},
                'weights_downloaded':False,'original_model_modified':False}
        (ROOT.parent/'evidence/gemma_uncensored_profile_creation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        model_file='FROM '+BASE+'\nRENDERER gemma4\nPARSER gemma4\nSYSTEM """'+SYSTEM_PROMPT+'"""\nPARAMETER temperature 0.7\nPARAMETER top_p 0.9\nPARAMETER top_k 40\nPARAMETER repeat_penalty 1.1\nPARAMETER num_ctx 4096\nPARAMETER num_predict 1536\nPARAMETER num_batch 128\nPARAMETER use_mmap true\n'
        (ROOT/'docs/Gemma.Modelfile').write_text(model_file,encoding='utf-8')
        print(json.dumps(result,indent=2))

if __name__=='__main__':main()
