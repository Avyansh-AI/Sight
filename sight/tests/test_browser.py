from contextlib import contextmanager
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time

import httpx
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright, expect
import pytest

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get("SIGHT_TEST_ARTIFACTS", ROOT / "reports/ui_visual_diffs"))


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    data = tmp_path_factory.mktemp("sight-browser")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    log = (data / "server.log").open("w")
    process = subprocess.Popen([sys.executable, "-m", "sight_core.cli", "start", "--local-only"], cwd=ROOT, env=dict(os.environ, SIGHT_DATA_DIR=str(data), SIGHT_PORT=str(port), SIGHT_OLLAMA_MODEL=""), stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if process.poll() is not None:
                log.flush()
                raise AssertionError("SIGHT startup failed: " + (data / "server.log").read_text())
            try:
                if httpx.get(url, trust_env=False, timeout=.2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.05)
        else:
            raise AssertionError("SIGHT startup timed out")
        yield url, (data / "browser-token").read_text()
    finally:
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        executable = os.environ.get("SIGHT_CHROMIUM") or shutil.which("chromium") or shutil.which("google-chrome")
        browser = p.chromium.launch(**({"executable_path": executable} if executable else {}), headless=True)
        yield browser
        browser.close()


def test_original_ui_css_and_markup_are_preserved():
    source = (ROOT / "tests/fixtures/original.html").read_bytes()
    actual = (ROOT / "apps/ui/index.html").read_bytes()
    assert hashlib.sha256(source).hexdigest() == "3b5f03744446ebae2c85048a3f48df75987e3d338372ff18538f7e1033edb8db"
    for pattern in (rb"<style>[\s\S]*?</style>", rb"<body>[\s\S]*?(?=<script>)"):
        assert re.findall(pattern, source) == re.findall(pattern, actual)


def test_capabilities_page_actual_approval_artifact_and_mobile(browser,live_server):
    url,token=live_server
    context=browser.new_context(viewport={'width':1440,'height':1000});page=context.new_page();errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(url+'/#sight-session='+token)
    expect(page.locator('#hubChip')).to_have_class(re.compile(r'\bon\b'))
    page.goto(url+'/capabilities.html');expect(page.locator('#notice')).to_contain_text('Ready')
    page.locator('#tool').select_option('documents.markdown');expect(page.locator('#description')).to_contain_text('Markdown')
    page.locator('#arguments').fill(json.dumps({'title':'Browser test','text':'<img src=x onerror="window.xss=true">'}))
    page.locator('#review').click();expect(page.locator('#approval')).to_be_visible()
    page.locator('#confirm').click();expect(page.locator('#notice')).to_contain_text('Completed')
    expect(page.locator('#download a')).to_contain_text('MD')
    assert not page.evaluate('Boolean(window.xss)')
    page.locator('#query').fill('printer');page.locator('#search').click()
    expect(page.locator('#catalog')).to_contain_text('BLOCKED_HARDWARE')
    page.locator('#skillQuery').fill('docx');page.locator('#searchSkills').click()
    expect(page.locator('#skillCount')).to_contain_text('1 indexed matches')
    ARTIFACTS.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(ARTIFACTS/'capabilities-desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(ARTIFACTS/'capabilities-mobile.png'),full_page=True)
    assert errors==[];context.close()


def test_learning_page_real_memory_forge_and_task_flow(browser,live_server):
    url,token=live_server
    context=browser.new_context(viewport={'width':1440,'height':900})
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(url+'/#sight-session='+token)
    expect(page.locator('#hubChip')).to_have_class(re.compile(r'\bon\b'))
    page.goto(url+'/learning.html');expect(page.locator('#notice')).to_contain_text('Ready')
    page.locator('#memoryKey').fill('text.case');page.locator('#memoryContent').fill('upper')
    page.get_by_role('button',name='Review memory',exact=True).click()
    expect(page.locator('#approval')).to_be_visible();page.locator('#confirm').click()
    expect(page.locator('#memories')).to_contain_text('upper')
    page.locator('#memoryContent').fill('<img src=x onerror="window.xss=true">')
    page.get_by_role('button',name='Review memory',exact=True).click();page.locator('#confirm').click()
    expect(page.locator('#memories')).to_contain_text('<img src=x')
    assert page.locator('#memories img').count()==0
    page.locator('#memoryContent').fill('upper');page.get_by_role('button',name='Review memory',exact=True).click();page.locator('#confirm').click()
    page.get_by_text('Stage a declarative recipe',exact=True).click();page.locator('#stage').click();page.locator('#confirm').click()
    expect(page.locator('#skills')).to_contain_text('tested')
    page.get_by_role('button',name='Promote',exact=True).click();page.locator('#confirm').click()
    expect(page.locator('#skills')).to_contain_text('text.clean v1')
    page.locator('#jobOperation').select_option('skill.invoke');page.locator('#jobTarget').fill('text.clean');page.locator('#jobText').fill('b\na\nb')
    page.get_by_role('button',name='Review task',exact=True).click();page.locator('#confirm').click()
    expect(page.locator('#jobs')).to_contain_text('complete',timeout=10000)
    page.get_by_role('button',name='Inspect results',exact=True).first.click();expect(page.locator('#nodeDetail')).to_contain_text('text.clean')
    page.locator('#memories').get_by_role('button',name='Forget',exact=True).click();page.locator('#confirm').click()
    expect(page.locator('#memories')).to_be_empty()
    ARTIFACTS.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(ARTIFACTS/'learning_desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(ARTIFACTS/'learning_mobile.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not errors,errors
    context.close()


def test_actual_browser_chat_ring_consent_and_xss(browser, live_server):
    url, token = live_server
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script("""sessionStorage.setItem('maxGreeted','1');window.deviceRequests=0;
      if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=()=>{window.deviceRequests++;throw Error('Real device access is forbidden in this test');};""")
    page.goto(url + "/#sight-session=" + token)
    expect(page.locator("#hubChip")).to_have_class(re.compile(r"\bon\b"))
    expect(page.locator("#needBannerText")).to_contain_text("no model is configured")
    page.locator("#typeBtn").click()
    page.locator("#chatInput").fill("Hello SIGHT")
    page.locator("#chatForm").evaluate("form=>form.requestSubmit()")
    expect(page.locator("#chatLog")).to_contain_text("SIGHT_OLLAMA_MODEL")
    expect(page.locator("#ringWrap")).to_have_class(re.compile(r"\bstandby\b"))
    # Untrusted user text must render as text and never execute.
    page.locator("#chatInput").fill('<img src=x onerror="window.xssExecuted=true">')
    page.locator("#chatForm").evaluate("form=>form.requestSubmit()")
    expect(page.locator("#chatLog")).to_contain_text("<img src=x")
    assert page.evaluate("window.xssExecuted || false") is False
    assert page.locator("#chatLog img").count() == 0
    page.locator("#ringWrap").click()
    expect(page.locator("#statusLine")).to_contain_text("pending")
    page.locator("#wakeBtn").click()
    expect(page.locator("#wakeBtn")).to_have_attribute("aria-pressed", "false")
    assert page.evaluate("window.deviceRequests") == 0
    assert page.evaluate("WakeWord.match('hi').wake") is False
    assert page.evaluate("WakeWord.match('sight').wake") is False
    assert page.evaluate("WakeWord.match('Hey SIGHT').wake") is True
    assert page.evaluate("localStorage.getItem('max.token')") is None
    assert "sight-session" not in page.url
    assert not errors, errors
    context.close()


@pytest.mark.parametrize("viewport", [(1440, 900), (390, 844)])
def test_ui_visual_parity(browser, viewport):
    """Compare original and integrated CSS/DOM at deterministic state, clock and API fixtures."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, reduced_motion="reduce")
    context.add_init_script("""
      const NativeDate=Date;window.Date=class extends NativeDate{constructor(...a){super(...(a.length?a:['2026-10-17T12:00:00Z']));}static now(){return 1792238400000;}};
      sessionStorage.setItem('maxGreeted','1');
      window.WebSocket=class{constructor(){setTimeout(()=>{this.onopen?.({});this.onmessage?.({data:JSON.stringify({type:'hello'})});},10);}send(){}close(){this.onclose?.({});}};
    """)
    fixture = {"/api/session": {"csrf": "fixture"}, "/api/access/ticket": {"ticket": "fixture"}, "/api/status": {"needs": []}, "/api/health": {"ok": True}, "/api/weather": {"configured": False}, "/api/settings": {"features": {}}, "/api/proactive": [], "/api/speech": {"micEnabled": False, "stt": {"mode": "local", "configured": False}, "tts": {"mode": "local", "configured": False}}}
    def route(request):
        path = request.request.url.split("sight.test", 1)[-1].split("?", 1)[0]
        if path.startswith("/api/"):
            request.fulfill(status=200, json=fixture.get(path, {}))
        elif path in {"/original.html", "/integrated.html"}:
            source = ROOT / ("tests/fixtures/original.html" if path == "/original.html" else "apps/ui/index.html")
            request.fulfill(status=200, content_type="text/html; charset=utf-8", body=source.read_text(encoding="utf-8"))
        else:
            request.fulfill(status=404, body="")
    context.route("**/*", route)
    states = ("standby", "listening", "thinking", "speaking", "vision", "alert", "offline", "error")
    images = {}
    metrics = []
    for version in ("original", "integrated"):
        page = context.new_page()
        page.goto(f"http://sight.test/{version}.html")
        expect(page.locator("#hubChip")).to_have_class(re.compile(r"\bon\b"))
        page.add_style_tag(content='*,*::before,*::after{transition-duration:0s!important;transition-delay:0s!important;animation-play-state:paused!important;animation-delay:0s!important}')
        page.wait_for_timeout(100)
        # Freeze all animation phases identically; capture state CSS rather than timing jitter.
        page.evaluate("document.getAnimations().forEach(a=>{a.pause();a.currentTime=0;})")
        for state in states:
            page.evaluate("state=>{document.getElementById('ringWrap').className='ring-wrap '+state;document.getElementById('statusText').textContent=state.toUpperCase();document.getElementById('statusLine').textContent='Visual fixture';}", state)
            # Each class change creates fresh animations. Freeze those too before
            # rasterization, rather than relying on screenshot's finish/cancel cycle.
            page.evaluate("async()=>{document.getAnimations().forEach(a=>{a.pause();a.currentTime=0;});await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));}")
            image = page.screenshot(animations="allow")
            name = f"{version}_{state}_{viewport[0]}x{viewport[1]}.png"
            (ARTIFACTS / name).write_bytes(image)
            images[(version, state)] = image
        page.close()
    for state in states:
        baseline = Image.open(BytesIO(images[("original", state)])).convert("RGB")
        current = Image.open(BytesIO(images[("integrated", state)])).convert("RGB")
        diff = ImageChops.difference(baseline, current)
        changed = sum(any(pixel) for pixel in diff.get_flattened_data())
        diff.save(ARTIFACTS / f"diff_{state}_{viewport[0]}x{viewport[1]}.png")
        metrics.append({"state": state, "viewport": list(viewport), "changed_pixels": changed, "baseline_sha256": hashlib.sha256(images[("original", state)]).hexdigest(), "actual_sha256": hashlib.sha256(images[("integrated", state)]).hexdigest()})
        assert changed == 0, metrics[-1]
    (ARTIFACTS / f"metrics_{viewport[0]}x{viewport[1]}.json").write_text(json.dumps(metrics, indent=2)+"\n")
    context.close()


def test_actual_browser_websocket_reconnect(browser, live_server):
    url, token = live_server
    context = browser.new_context()
    page = context.new_page()
    page.add_init_script("""sessionStorage.setItem('maxGreeted','1');window.sockets=[];const NativeWS=WebSocket;window.WebSocket=class extends NativeWS{constructor(...args){super(...args);window.sockets.push(this);}};""")
    page.goto(url + "/#sight-session=" + token)
    expect(page.locator("#hubChip")).to_have_class(re.compile(r"\bon\b"))
    initial = page.evaluate("sockets.length")
    page.evaluate("sockets.forEach(s=>s.close())")
    expect(page.locator("#hubChipText")).to_have_text("offline")
    expect(page.locator("#hubChip")).to_have_class(re.compile(r"\bon\b"), timeout=10_000)
    assert page.evaluate("sockets.length") > initial
    context.close()


def test_each_lost_socket_request_gets_its_own_http_recovery(browser,live_server):
    url,token=live_server
    context=browser.new_context()
    page=context.new_page()
    page.add_init_script("""sessionStorage.setItem('maxGreeted','1');
      window.lostRequests=[];window.recoveryTimers=new Map();
      const originalTimer=window.setTimeout, originalClear=window.clearTimeout;
      window.setTimeout=(fn,ms,...args)=>{if(ms===15000){const id=100000+window.recoveryTimers.size;window.recoveryTimers.set(id,fn);return id;}return originalTimer(fn,ms,...args);};
      window.clearTimeout=id=>{window.recoveryTimers.delete(id);return originalClear(id);};
      const originalSend=WebSocket.prototype.send;
      WebSocket.prototype.send=function(data){const msg=JSON.parse(data);if(msg.type==='utterance'){window.lostRequests.push(msg);return;}return originalSend.call(this,data);};
    """)
    page.goto(url+'/#sight-session='+token)
    expect(page.locator('#hubChip')).to_have_class(re.compile(r'\bon\b'))
    page.locator('#typeBtn').click()
    for prompt in ['first lost request','second lost request']:
        page.locator('#chatInput').fill(prompt)
        page.locator('#chatForm').evaluate('form=>form.requestSubmit()')
    assert page.evaluate('window.lostRequests.length')==2
    assert page.evaluate('window.recoveryTimers.size')==2
    page.evaluate('Array.from(window.recoveryTimers.entries()).forEach(([id,fn])=>{window.recoveryTimers.delete(id);fn();})')
    expect(page.locator('#chatLog .bubble.max')).to_have_count(2)
    assert page.evaluate('window.recoveryTimers.size')==0
    expect(page.locator('.toast')).to_have_count(0)
    context.close()


def test_systems_page_review_and_decline_preserves_policy(browser,live_server):
    url,token=live_server
    context=browser.new_context();page=context.new_page()
    page.goto(url+'/#sight-session='+token)
    expect(page.locator('#hubChip')).to_have_class(re.compile(r'\bon\b'))
    page.goto(url+'/systems.html')
    expect(page.locator('#models')).to_contain_text('local_only')
    page.locator('#providerPolicy [name=model]').fill('fixture/model:free')
    page.locator('#providerPolicy [name=enabled]').check()
    page.locator('#providerPolicy [name=allow_remote_text]').check()
    page.on('dialog',lambda dialog:dialog.dismiss())
    page.locator('#providerPolicy button').click()
    policy=page.evaluate("fetch('/api/models').then(r=>r.json())")
    assert next(p for p in policy['cloud'] if p['id']=='openrouter')['status']=='disabled'
    context.close()
