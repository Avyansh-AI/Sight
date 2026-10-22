"""Fixed declarative interpreter run with Python -I -S; never evaluates generated code."""
import json
import sys

OPS = {'trim','lower','upper','normalize_spaces','sort_lines','dedupe_lines','replace_literal','prefix','suffix'}


def transform(text, operations):
    if not isinstance(text,str) or len(text.encode('utf-8'))>16384 or not isinstance(operations,list) or not 1<=len(operations)<=12:
        raise ValueError('Input or operation limit exceeded')
    for operation in operations:
        if not isinstance(operation,dict) or set(operation)-{'op','value','old','new'} or operation.get('op') not in OPS:
            raise ValueError('Unknown operation or authority')
        for key in ('value','old','new'):
            if not isinstance(operation.get(key,''),str) or len(operation.get(key,''))>128:raise ValueError('Literal limit exceeded')
        op=operation['op']
        if op=='trim':text=text.strip()
        elif op=='lower':text=text.lower()
        elif op=='upper':text=text.upper()
        elif op=='normalize_spaces':text=' '.join(text.split())
        elif op=='sort_lines':text='\n'.join(sorted(text.splitlines()))
        elif op=='dedupe_lines':text='\n'.join(dict.fromkeys(text.splitlines()))
        elif op=='replace_literal':
            if not operation.get('old'):raise ValueError('Empty replacement pattern')
            text=text.replace(operation['old'],operation.get('new',''))
        elif op=='prefix':text=operation.get('value','')+text
        elif op=='suffix':text+=operation.get('value','')
        if len(text.encode('utf-8'))>32768:raise ValueError('Output limit exceeded')
    return text


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(65537)
        if len(raw)>65536:raise ValueError('Payload limit exceeded')
        data=json.loads(raw)
        if set(data)!={'text','operations'}:raise ValueError('Invalid worker request')
        print(json.dumps({'ok':True,'result':transform(data['text'],data['operations'])},ensure_ascii=True))
    except (ValueError,TypeError,KeyError):
        print(json.dumps({'ok':False,'error':'Rejected declarative operation or resource limit'}))
        raise SystemExit(1)
