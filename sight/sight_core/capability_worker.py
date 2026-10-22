"""Fixed worker entry point. JSON input is data, never source code or shell text."""
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import wave

def browser(value):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,chromium_sandbox=True)
        try:
            context=browser.new_context(java_script_enabled=False,service_workers='block',accept_downloads=False,offline=True,viewport={'width':1024,'height':768})
            blocked=[]
            def reject(route):blocked.append(route.request.resource_type);route.abort()
            context.route('**/*',reject)
            page=context.new_page();page.set_default_timeout(2000)
            page.set_content(value['html'],wait_until='domcontentloaded',timeout=5000)
            for identifier,text in value['fields'].items():page.locator('#'+identifier).fill(text)
            result={'title':page.title()[:200],'text':page.locator('body').inner_text()[:16000],
                    'fields':{identifier:page.locator('#'+identifier).input_value() for identifier in value['fields']},
                    'screenshot':base64.b64encode(page.screenshot(timeout=5000)).decode(),
                    'blocked_requests':len(blocked),'untrusted_content':True,'network_allowed':False,'scripts_enabled':False,'submitted':False}
            context.close();return result
        finally:browser.close()

def speech(value):
    if os.name!='nt':raise ValueError('Windows SAPI required')
    executable=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    # No interpolation of user text into commands; fixed script reads UTF-8 JSON.
    script="$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Speech; $sightInput=[Console]::In.ReadToEnd() | ConvertFrom-Json; $sightVoice=New-Object System.Speech.Synthesis.SpeechSynthesizer; try { $sightVoice.SetOutputToWaveFile([string]$sightInput.path); $sightVoice.Speak([string]$sightInput.text) } finally { $sightVoice.Dispose() }"
    with tempfile.TemporaryDirectory(prefix='sight-speech-') as directory:
        path=Path(directory)/'voice.wav'
        subprocess.run([str(executable),'-NoProfile','-NonInteractive','-Command',script],input=json.dumps({'path':str(path),'text':value['text']}),text=True,capture_output=True,check=True,timeout=15,shell=False)
        if path.stat().st_size>8*1024**2:raise ValueError('Speech output too large')
        data=path.read_bytes()
        with wave.open(io.BytesIO(data)) as audio:duration=audio.getnframes()/audio.getframerate()
        return {'wav':base64.b64encode(data).decode(),'duration_seconds':duration,'engine':'Windows System.Speech','network_allowed':False,'played':False}

def main():
    raw=sys.stdin.buffer.read(100001)
    if len(raw)>100000:raise ValueError('Worker payload too large')
    value=json.loads(raw)
    handler={'browser.inspect':browser,'speech.render':speech}[value['id']]
    print(json.dumps(handler(value['arguments']),ensure_ascii=True))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'error':'Adapter failed','kind':type(exc).__name__}));sys.exit(1)
