"""Small local-only configuration comparison; no owner conversations or weights changed."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import httpx
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sight_core.models import SYSTEM_PROMPT
BASE = 'hf.co/OBLITERATUS/gemma-4-E4B-it-OBLITERATED:Q4_K_M'
SYSTEM = ('You are SIGHT, a calm and capable assistant. Use clear, natural, professional language. '
          'Avoid slang, memes, emojis, hype and exaggerated praise unless the user requests that style. '
          'Answer the actual question. Check arithmetic, logic and assumptions before answering. '
          'For difficult questions, reason carefully and give the conclusion with a brief useful explanation. '
          'If information is missing or uncertain, say so instead of inventing facts. '
          'Do not claim to browse, run code or perform actions you have not performed.')
CASES = [
    ('tone', 'Explain in three sentences why my laptop gets slower when its RAM is full.'),
    ('arithmetic', 'A shop reduces a price of 250 by 20%, then applies 10% tax to the reduced price. What is the final price? Give the number and one sentence.'),
    ('logic', 'All red blocks are heavy. Some heavy blocks are wooden. Does it follow that some red blocks are wooden? Explain briefly.'),
    ('planning', 'I have 35 minutes. Downloading takes 10 minutes, installation takes 15 minutes after the download, and a test takes 12 minutes after installation. Can I finish everything? Explain briefly.'),
    ('code', 'In Python, why does items.sort() return None? Give a one-line way to get a sorted copy while keeping items unchanged.'),
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default=BASE)
    parser.add_argument('--profile', choices=['original','controlled','thinking'], required=True)
    parser.add_argument('--temperature', type=float, default=0)
    parser.add_argument('--tokens', type=int, default=1536)
    parser.add_argument('--updated-prompt', action='store_true')
    parser.add_argument('--minimal-prompt', action='store_true')
    parser.add_argument('--repeat-penalty', type=float, default=1.0)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    evidence = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'model': args.model, 'profile': args.profile, 'temperature':args.temperature, 'output_tokens':args.tokens, 'updated_prompt':args.updated_prompt, 'minimal_prompt':args.minimal_prompt,'repeat_penalty':args.repeat_penalty,'seed':args.seed, 'cloud_requests': 0, 'rows': [], 'completed': False}
    destination = ROOT.parent / 'evidence' / ('gemma-' + args.profile + '-' + str(int(time.time())) + '.json')
    with httpx.Client(base_url='http://127.0.0.1:11434', trust_env=False, timeout=180) as client:
        info = client.post('/api/show', json={'model': args.model}).json()
        evidence['metadata'] = {k:info.get(k) for k in ('capabilities','thinking','parameters','details')}
        for name, prompt in CASES:
            payload = {'model':args.model, 'stream':False, 'keep_alive':'2m', 'messages':[]}
            system = "You are SIGHT, an AI assistant. Answer the user's question accurately and directly, using their language. Use clear, professional language without slang, memes or emojis. Tools are unavailable in this chat." if args.minimal_prompt else SYSTEM_PROMPT if args.updated_prompt else SYSTEM
            if args.profile != 'original':payload['messages'].append({'role':'system','content':system})
            payload['messages'].append({'role':'user','content':prompt})
            payload['options'] = {'num_ctx':4096,'num_predict':args.tokens,'num_batch':128,'seed':args.seed,'use_mmap':True,'top_p':0.9,'top_k':40,'repeat_penalty':args.repeat_penalty}
            if args.profile != 'original':payload['options']['temperature']=args.temperature
            if args.profile == 'controlled':payload['think']=False
            if args.profile == 'thinking':payload['think']=True
            start = time.perf_counter()
            try:
                response = client.post('/api/chat', json=payload)
                data = response.json()
                message = data.get('message', {})
                row = {'case':name,'prompt':prompt,'http_status':response.status_code,'seconds':round(time.perf_counter()-start,3),
                       'answer':message.get('content',''),'thinking_characters':len(message.get('thinking','')),'done_reason':data.get('done_reason'),
                       'prompt_tokens':data.get('prompt_eval_count'),'generated_tokens':data.get('eval_count'),'error':data.get('error')}
            except httpx.HTTPError as exc:
                row = {'case':name,'error_type':type(exc).__name__,'seconds':round(time.perf_counter()-start,3)}
            evidence['rows'].append(row)
            destination.write_text(json.dumps(evidence,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in row.items() if k not in ('prompt','answer')}),flush=True)
            if row.get('http_status',0) != 200:break
        evidence['completed'] = len(evidence['rows']) == len(CASES)
        evidence['resident_models'] = [{k:m.get(k) for k in ('name','size_vram','context_length')} for m in client.get('/api/ps').json()['models']]
    destination.write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print(str(destination))

if __name__ == '__main__':main()
