"""Official model sampling and direct launcher selection; no live inference."""
import asyncio
import json
import os
from pathlib import Path
import subprocess

import httpx
import pytest

from sight_core.config import Config
from sight_core.models import ModelStatus, OllamaProvider


@pytest.mark.parametrize('model,expected', [
    ('gemma4:e4b-it-qat', (1.0, .95, 64, 1.0)),
    ('sight-gemma4-e4b:uncensored', (.7, .9, 40, 1.1)),
])
def test_official_model_does_not_inherit_derivative_sampling(tmp_path, model, expected):
    sent = []
    def respond(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={'message': {'content': '4'}, 'done': True, 'done_reason': 'stop'})
    provider = OllamaProvider(Config(tmp_path, model=model, thinking=False), transport=httpx.MockTransport(respond))
    async def health():return ModelStatus('ready', 'fixture', supports_thinking=True)
    provider._metadata_health = health
    assert asyncio.run(provider.generate('2 plus 2'))['status'] == 'ok'
    options = sent[0]['options']
    assert tuple(options[k] for k in ('temperature', 'top_p', 'top_k', 'repeat_penalty')) == expected
    assert sent[0]['model'] == model and sent[0]['think'] is False
    assert options['num_ctx'] == 4096 and options['num_predict'] == 512


@pytest.mark.parametrize('thinking', [False, True])
def test_direct_helper_selects_normal_gemma(tmp_path, thinking):
    if os.name != 'nt':pytest.skip('Windows launcher')
    launcher = str(Path(__file__).resolve().parents[2]/'Run-Gemma.ps1').replace("'", "''")
    fake = tmp_path/'fake-ollama.ps1'
    fake.write_text("ConvertTo-Json -InputObject @($args) -Compress\nexit 0\n", encoding='utf-8')
    wrapper = tmp_path/'wrapper.ps1'
    wrapper.write_text("""$ErrorActionPreference='Stop'
function Invoke-RestMethod { return [pscustomobject]@{models=@([pscustomobject]@{name='gemma4:e4b-it-qat'})} }
& 'LAUNCHER' -OllamaExecutable 'FAKE' -Prompt '2 plus 2' THINKING
""".replace('LAUNCHER',launcher).replace('FAKE',str(fake).replace("'","''"))
       .replace('THINKING','-Thinking' if thinking else ''),encoding='utf-8')
    exe=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    result=subprocess.run([str(exe),'-NoProfile','-NonInteractive','-File',str(wrapper)],
                          capture_output=True,text=True,timeout=15,creationflags=0x08000000)
    assert result.returncode==0,result.stdout+result.stderr
    assert json.loads(result.stdout)==['run','gemma4:e4b-it-qat','--think=true' if thinking else '--think=false','2 plus 2']
