"""Predeclared local-only paired prompt comparison; never changes a model profile."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sight_core.models import SYSTEM_PROMPT

MODEL = 'sight-gemma4-e4b:uncensored'
PROMPTS = {
    'selected': SYSTEM_PROMPT,
    'publisher_minimal': "You are an AI language model. Respond to the user's input.",
    'professional_minimal': 'You are SIGHT. Answer accurately in clear, professional English.',
}
CASES = [
    ('discount', 'calibration', 'A price of 250 is reduced by 20%, then 10% tax is applied to the reduced price. What is the final price? Reply with only the number.', '220'),
    ('schedule', 'calibration', 'I have 35 minutes. Downloading takes 10 minutes, installation takes 15 minutes after the download, and testing takes 12 minutes after installation. Can I finish all three? Reply only YES or NO.', 'NO'),
    ('printers', 'held_out', 'Three printers each make one part every four minutes. How many parts do they make in total in twelve minutes? Reply with only the number.', '9'),
    ('reverse_discount', 'held_out', 'A 25% discount makes a price 75. What was the original price? Reply with only the number.', '100'),
    ('non_entailment', 'held_out', 'Every red block is heavy. Some heavy blocks are wooden. Must some red blocks be wooden? Reply only YES or NO.', 'NO'),
    ('entailment', 'held_out', 'Every sparrow is a bird. Every bird is warm-blooded. Must every sparrow be warm-blooded? Reply only YES or NO.', 'YES'),
    ('sorted_copy', 'held_out', 'Give one Python expression that returns a sorted copy of the list items without changing items. Reply with only the expression.', 'sorted(items)'),
    ('unit_conversion', 'held_out', 'A container holds 1.5 litres. How many millilitres is that? Reply with only the number.', '1500'),
]
TONE = 'Explain in three sentences why a laptop slows down when its RAM is full.'
SEEDS = (17, 42)
OPTIONS = {'num_ctx': 4096, 'num_predict': 128, 'num_batch': 128, 'use_mmap': True,
           'temperature': 0.7, 'top_p': 0.9, 'top_k': 40, 'repeat_penalty': 1.1}


def exact_answer(answer, expected):
    value = answer.strip()
    fenced = re.fullmatch(r'```(?:python)?\s*\n?(.*?)\n?```', value, re.S)
    if fenced:
        value = fenced.group(1).strip()
    value = value.strip('`').strip()
    if expected in ('YES', 'NO'):
        return value.upper().rstrip('.') == expected
    if expected == 'sorted(items)':
        return re.sub(r'\s', '', value) == expected
    try:
        return Decimal(value) == Decimal(expected)
    except InvalidOperation:
        return False


def main():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    destination = ROOT.parent / 'evidence' / ('gemma-prompt-eval-' + stamp + '.json')
    result = {'timestamp_utc': stamp, 'model': MODEL, 'thinking': False,
              'cloud_requests': 0, 'profile_modified': False, 'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'prompts': PROMPTS, 'options': OPTIONS, 'seeds': SEEDS, 'cases': CASES,
              'grading': 'Exact answer plus requested format. Numeric decimals accepted; explanations fail exact format. Style screen is not a factual-quality score.',
              'promotion_rule': 'All calibration and held-out answers must pass both seeds, with both style screens passing, before any separate confirmation run. No automatic configuration change.',
              'rows': [], 'complete': False}
    def save():
        destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
    save()  # Freeze the cases and decision rule before requesting any answers.
    with httpx.Client(base_url='http://127.0.0.1:11434', timeout=120, trust_env=False) as client:
        info = client.post('/api/show', json={'model': MODEL})
        info.raise_for_status()
        result['runtime_version'] = client.get('/api/version').json()['version']
        for variant, system in PROMPTS.items():
            for seed in SEEDS:
                cases = [*CASES, ('tone', 'style', TONE, None)]
                for case, split, prompt, expected in cases:
                    started = time.monotonic()
                    payload = {'model': MODEL, 'think': False, 'stream': False, 'keep_alive': '5m',
                               'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}],
                               'options': OPTIONS | {'seed': seed}}
                    response = client.post('/api/chat', json=payload)
                    response.raise_for_status()
                    data = response.json()
                    answer = data.get('message', {}).get('content', '')
                    finished = data.get('done') is True and data.get('done_reason') == 'stop'
                    row = {'variant': variant, 'seed': seed, 'case': case, 'split': split,
                           'answer': answer, 'seconds': round(time.monotonic() - started, 3),
                           'finished': finished, 'done_reason': data.get('done_reason'),
                           'thinking_characters': len(data.get('message', {}).get('thinking', ''))}
                    if expected is not None:
                        row['expected'] = expected
                        row['passed'] = finished and exact_answer(answer, expected)
                    else:
                        row['style_screen_passed'] = finished and bool(answer.strip()) and not re.search(
                            r'\b(?:bruh|no cap|fr fr|lit|slay|yeet|rizz|vibes|vibing|lowkey|bestie|lol|lmao)\b|[\U0001F300-\U0001FAFF]', answer, re.I)
                    result['rows'].append(row)
                    save()
                print(json.dumps({'variant': variant, 'seed': seed, 'completed_requests': len(result['rows'])}), flush=True)
    result['summary'] = {}
    for variant in PROMPTS:
        rows = [row for row in result['rows'] if row['variant'] == variant]
        summary = {split: {'passed': sum(row.get('passed', False) for row in rows if row['split'] == split),
                           'total': sum(row['split'] == split for row in rows)} for split in ('calibration', 'held_out')}
        summary['style_screen_passes'] = sum(row.get('style_screen_passed', False) for row in rows)
        summary['eligible_for_confirmation'] = all(row.get('passed', row.get('style_screen_passed', False)) for row in rows)
        result['summary'][variant] = summary
    result['complete'] = True
    save()
    (ROOT / 'reports/gemma_prompt_eval.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'evidence': str(destination), 'summary': result['summary']}, indent=2))


if __name__ == '__main__':
    main()
