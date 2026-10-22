from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from dataclasses import asdict
import hashlib
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import secrets
import time
import uuid
import subprocess
import sqlite3

import httpx

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import Field, ValidationError

from .config import Config
from .models import OllamaProvider, cloud_status
from .routing import ModelRouter, ProviderPolicy
from .security import Sessions, Vault, redact, atomic_private_write, safe_file, redact_transport_logs
from .store import Store
from .tools import StrictModel, FileWrite, DesktopAction, LocalFiles, desktop_invoke, registry
from .learning_api import Learning, ACTIONS
from .capabilities import Capabilities
from .chatgpt import ChatGPT, ChatGPTPolicy, Connect

UI = Path(__file__).resolve().parents[1] / "apps/ui"


class Utterance(StrictModel):
    text: str = Field(min_length=1, max_length=8000)
    user: str = Field(default="default", pattern="^default$")
    requestId: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class Prepare(StrictModel):
    path: str
    args: dict


class Claim(StrictModel):
    token: str = Field(min_length=1, max_length=128)


class SessionRequest(StrictModel):
    user: str = Field(default="default", pattern="^default$")


class Preferences(StrictModel):
    textOnly: bool = True
    notifications: bool = False
    startupBriefing: bool = False


class AudioInput(StrictModel):
    audio: str = Field(max_length=5_592_408)
    mimeType: str = Field(pattern=r"^audio/(webm|ogg|mp4|wav)(;codecs=opus)?$")
    user: str = Field(default="default", pattern="^default$")


def create_app(config: Config | None = None, provider=None, *, local_only=False):
    redact_transport_logs()
    config = config or Config.from_env()
    store = Store(config.data_dir)
    files = LocalFiles(config.data_dir / "files")
    sessions = Sessions()
    bootstrap_token = secrets.token_urlsafe(32)
    bootstrap_expires = time.monotonic() + 8 * 3600
    token_file = config.data_dir / "browser-token"
    # Owner-only file; the launch helper passes it in a URL fragment, never a query/log.
    atomic_private_write(token_file, bootstrap_token.encode('ascii'))
    local = provider or OllamaProvider(config)
    router = ModelRouter(local, store, local_only=local_only)
    chatgpt = ChatGPT(store,config)
    router.chatgpt = chatgpt
    learning_service = Learning(config, files, router)
    capability_service = Capabilities(store, files)
    active = {}
    active_inputs = {}
    sockets = {}
    logger = logging.getLogger("sight." + hashlib.sha256(str(config.data_dir).encode()).hexdigest()[:12])
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        for suffix in ('', '.1', '.2', '.3'):
            safe_file(config.data_dir / ('events.log' + suffix))
        handler = RotatingFileHandler(config.data_dir / "events.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    def audit(kind, payload=None, task=None):
        safe = redact(payload or {})
        store.event(kind, safe, task)
        logger.info(json.dumps({"type": kind, "task": task, "data": safe}))

    @asynccontextmanager
    async def lifespan(app):
        store.recover_interrupted()
        if learning_service.jobs:await learning_service.jobs.start()
        await capability_service.proactive.start()
        audit("service.started", {"phase": 4, "release": "partial"})
        yield
        if learning_service.jobs:await learning_service.jobs.stop()
        await capability_service.proactive.stop()
        for task in list(active.values()):
            task.cancel()
        if active:
            await asyncio.gather(*active.values(), return_exceptions=True)
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    app = FastAPI(title="SIGHT", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store, app.state.sessions, app.state.provider, app.state.config = store, sessions, local, config
    app.state.bootstrap_token = bootstrap_token
    app.state.router = router
    app.state.learning = learning_service
    app.state.chatgpt = chatgpt
    learning_service.mount(app)
    app.state.capabilities = capability_service
    capability_service.mount(app)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"error": "Invalid request fields or payload", "fields": [list(e["loc"]) for e in exc.errors()]}, status_code=422)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        logger.error(json.dumps({"type": "database.unavailable", "error_type": type(exc).__name__}))
        return JSONResponse({"error": "The local database is busy or unavailable. Retry after checking the data directory."}, status_code=503)

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        host = request.headers.get("host", "")
        origin = request.headers.get("origin")
        oauth_callback = request.url.path == '/auth/callback' and request.method == 'GET'
        if host not in config.hosts:
            return JSONResponse({"error": "Untrusted Host"}, status_code=403)
        if origin and origin != "http://" + host and not oauth_callback:
            return JSONResponse({"error": "Cross-origin access denied"}, status_code=403)
        if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"} and not oauth_callback:
            return JSONResponse({"error": "Same-origin access required"}, status_code=403)
        session = sessions.get(request.cookies.get("sight_session"))
        request.state.session = session
        claim = request.url.path == "/api/session/claim" and request.method == "POST"
        if claim and origin != "http://" + host:
            return JSONResponse({"error": "Owner browser origin required"}, status_code=403)
        if request.url.path.startswith("/api/"):
            if not session and not claim:
                return JSONResponse({"error": "Open SIGHT locally to establish an owner session"}, status_code=401)
            if request.method not in {"GET", "HEAD"}:
                if not claim and not secrets.compare_digest(request.headers.get("x-sight-csrf", ""), session.csrf):
                    return JSONResponse({"error": "Missing or invalid session action proof"}, status_code=403)
                if "application/json" not in request.headers.get("content-type", ""):
                    return JSONResponse({"error": "JSON content type required"}, status_code=415)
                limit = 6 * 1024**2 if request.url.path == "/api/speech/transcribe" else 100_000
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > limit:
                        return JSONResponse({"error": "Payload too large"}, status_code=413)
                request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path in {"/", "/index.html", "/systems.html", "/tasks.html", "/vision.html", "/learning.html", "/capabilities.html"}:
            page = UI / ("index.html" if request.url.path == "/" else request.url.path.lstrip("/"))
            hashes = []
            if page.is_file():
                for script in re.findall(r"<script[^>]*>([\s\S]*?)</script>", page.read_text(encoding="utf-8")):
                    hashes.append("'sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + "'")
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' " + " ".join(hashes) + "; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.get("/")
    @app.get("/index.html")
    async def index():
        return FileResponse(UI / "index.html", media_type="text/html")

    @app.get("/systems.html")
    @app.get("/tasks.html")
    @app.get("/vision.html")
    @app.get("/learning.html")
    @app.get("/capabilities.html")
    async def support_page(request: Request):
        return FileResponse(UI / request.url.path.lstrip("/"), media_type="text/html")

    @app.get("/sw.js")
    async def worker():
        return Response("self.addEventListener('install',()=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(self.registration.unregister()));", media_type="text/javascript")

    @app.get("/api/session")
    async def session(request: Request):
        return {"csrf": request.state.session.csrf, "owner": "local", "expiresIn": 8*3600}

    @app.get('/auth/callback')
    async def oauth_callback(request: Request):
        from fastapi.responses import RedirectResponse
        try:
            if len(request.url.query)>12000 or len(request.query_params)!=len(request.query_params.multi_items()):raise ValueError('Invalid callback')
            await chatgpt.callback(dict(request.query_params),sessions.get)
            return RedirectResponse('/systems.html',status_code=303)
        except Exception:
            chatgpt.last_error='Sign-in did not complete. Start a new attempt from Systems.'
            return RedirectResponse('/systems.html',status_code=303)

    @app.get('/api/chatgpt/status')
    async def chatgpt_status():return chatgpt.status()

    @app.get('/api/chatgpt/models')
    async def chatgpt_models():
        try:return await chatgpt.models()
        except Exception:raise HTTPException(409,'Connect ChatGPT before listing account models')

    @app.post("/api/session/claim")
    async def claim_session(body: Claim):
        supplied = body.token
        if not isinstance(supplied, str) or time.monotonic() > bootstrap_expires or not secrets.compare_digest(supplied, bootstrap_token):
            raise HTTPException(403, "Owner launch proof is invalid or expired. Use sight open from the local OS session.")
        try:
            session = sessions.create()
        except ValueError:
            raise HTTPException(429, "Local session limit reached")
        result = JSONResponse({"ok": True})
        result.set_cookie("sight_session", session.id, httponly=True, samesite="strict", max_age=8*3600, path="/")
        return result

    @app.get("/api/health")
    async def health():
        with store.connect() as db:
            integrity = db.execute("PRAGMA quick_check").fetchone()[0]
        enabled = not local_only and any(router.provider(p).policy.enabled for p in ("groq", "gemini", "openrouter"))
        return {"ok": integrity == "ok", "database": integrity, "phase": 4, "release": "PARTIAL", "cloud_enabled": enabled}

    @app.get("/api/status")
    async def status():
        model = await local.health()
        cloud_ready = not local_only and any(row["status"] == "ready" for row in await router.statuses())
        needs = []
        if model.status != "ready":
            needs.append({"severity": "blocked", "what": model.message, "fix": "See Systems and docs/START_HERE.md."})
        needs.append({"severity": "warn", "what": "Build verification is incomplete; microphone, camera and remote tools are disabled.", "fix": "Complete the phase gates before enrollment."})
        return {"ok": True, "hub": "ready", "model": asdict(model), "needs": needs, "online": cloud_ready, "release": "PARTIAL", "phase": 4}

    @app.get("/api/ready")
    async def ready():
        model = await local.health()
        cloud_ready = not local_only and any(row["status"] == "ready" for row in await router.statuses())
        inference_ready = model.status == "ready" or cloud_ready
        return JSONResponse({"api_ready": True, "inference_ready": inference_ready, "status": "cloud_ready" if cloud_ready and model.status != "ready" else model.status, "release_ready": False}, status_code=200 if inference_ready else 503)

    @app.get("/api/models")
    async def models():
        return {"local": asdict(await local.health()), "limits": local.limits(), "cloud": await router.statuses(), "vault": Vault().status(), "routing": "local first; only explicitly enabled text providers may receive fallback requests", "local_only": local_only}

    @app.get("/api/capabilities")
    async def capabilities():
        return {"items": registry()+capability_service.registry(), "complete": False, "phase": 4}

    @app.get("/api/learning/status")
    async def learning():
        return learning_service.status()

    @app.get("/api/settings")
    async def settings():
        cloud = not local_only and any(router.provider(p).policy.enabled and router.provider(p).policy.allow_remote_text for p in ("groq", "gemini", "openrouter"))
        return {"preferences": store.setting("preferences", Preferences().model_dump()), "features": {"startupBriefing": False}, "privacy": {"microphone": False, "camera": False, "cloud": cloud}}

    @app.post("/api/settings")
    async def save_settings(body: Preferences):
        if body.startupBriefing:
            raise HTTPException(409, "Startup briefings are not implemented")
        store.set_setting("preferences", body.model_dump())
        return {"ok": True}

    @app.get("/api/weather")
    async def weather():
        return {"configured": False, "available": False, "status": "not_connected"}

    @app.get("/api/home/devices")
    async def devices():
        return {"configured": False, "devices": [], "status": "not_paired"}

    @app.get("/api/proactive")
    async def proactive():
        return [{'id':r['id'],'text':r['title'],'message':r['title'],'localOnly':True,'ts':r['created']*1000} for r in capability_service.proactive.notifications()]

    @app.get("/api/activity")
    async def activity(n: int = 8):
        return {"items": [{"id": r["seq"], "ts": r["ts"], "type": r["type"], "message": r["type"]} for r in store.events(max(1, min(n, 100)))]}

    @app.post("/api/schedule/snooze")
    async def snooze():
        raise HTTPException(409, "No scheduler or reminders are configured; nothing was snoozed")

    @app.get("/api/speech")
    async def speech():
        return {"micEnabled": False, "reason": "Local speech and owner enrollment are pending the required engineering phase gates.", "stt": {"mode": "local", "configured": False}, "tts": {"mode": "local", "configured": False}, "supportedMimeTypes": ["audio/webm", "audio/ogg", "audio/mp4", "audio/wav"], "maxAudioBytes": 4*1024**2, "wake": {"enrolled": False, "enabled": False}}

    @app.post("/api/speech/transcribe")
    async def transcribe(body: AudioInput):
        try:
            decoded = base64.b64decode(body.audio, validate=True)
        except ValueError:
            raise HTTPException(422, "Invalid base64 audio")
        if len(decoded) > 4*1024**2:
            raise HTTPException(413, "Audio exceeds the 4 MiB limit")
        raise HTTPException(503, "Local STT is not installed; microphone input remains disabled")

    @app.post("/api/speech/synthesize")
    async def synthesize():
        raise HTTPException(503, "Local TTS is not installed; no cloud fallback is authorized")

    @app.get("/api/voiceprint/{operation}")
    @app.post("/api/voiceprint/{operation}")
    async def voiceprint(operation: str):
        raise HTTPException(409, "No voiceprint enrolled. Voice is never sufficient authority for privileged actions.")

    @app.post("/api/brain/jobs/{job_id}/verify")
    async def verify(job_id: str):
        raise HTTPException(403, "Biometric-only action authorization is disabled")

    @app.post("/api/access/ticket")
    async def ticket(request: Request, body: SessionRequest):
        try:
            return {"ticket": sessions.ticket(request.state.session), "expiresIn": 30}
        except ValueError:
            raise HTTPException(429, "Ticket limit reached")

    async def utterance_work(body):
        existing, created = store.begin(body.requestId, body.text)
        if not created:
            if existing.get("response"):
                return json.loads(existing["response"])
            return {"requestId": body.requestId, "taskId": existing["task"], "status": existing["state"], "say": "The previous request was interrupted; review its status before submitting a new request.", "offline": True}
        audit("task.started", {"requestId": body.requestId}, existing["task"])
        try:
            if body.text.strip().lower() == "cancel the sos":
                store.set_setting("sos", False)
                output = {"status": "ok", "say": "Local alert stopped. No emergency contacts were notified.", "offline": True}
            elif body.text.strip().lower() in {"help", "what can you do", "status"}:
                output = {"status": "ok", "say": "SIGHT's local core is running. Systems shows model readiness and capability status. File tools are limited to the SIGHT workspace. Other phases are pending verification.", "offline": True}
            else:
                if not learning_service.error:
                    context=learning_service.memory.context(body.text)
                    remote=learning_service.memory.context(body.text,remote=True)
                    output = await router.generate(body.text,local_context=context['text'],remote_context=remote['text'],recover_empty=True)
                    output['memory_sources']=context['sources'] if output.get('offline',True) else remote['sources']
                else:
                    output = await router.generate(body.text,recover_empty=True)
            output.update({"requestId": body.requestId, "taskId": existing["task"], "type": "response"})
            output = redact(output)
            store.finish(body.requestId, output, "complete" if output["status"] == "ok" else "failed")
            audit("task.finished", {"status": output["status"]}, existing["task"])
            return output
        except asyncio.CancelledError:
            output = {"type": "response", "status": "cancelled", "say": "Request cancelled. No external action was performed.", "requestId": body.requestId, "taskId": existing["task"], "offline": True}
            store.finish(body.requestId, output, "cancelled")
            audit("task.cancelled", task=existing["task"])
            return output
        except Exception as exc:
            output = {"type": "response", "status": "failed", "say": "The request failed safely. No external action was performed.", "requestId": body.requestId, "taskId": existing["task"], "offline": True}
            store.finish(body.requestId, output, "failed")
            audit("task.failed", {"error_type": type(exc).__name__}, existing["task"])
            return output

    async def handle_utterance(body):
        existing = active.get(body.requestId)
        if existing:
            if active_inputs.get(body.requestId) != hashlib.sha256(body.text.encode()).hexdigest():
                raise ValueError("requestId already used for different input")
            return await asyncio.shield(existing)
        if len(active) >= 8:
            raise HTTPException(429, "Request queue is full")
        task = asyncio.create_task(utterance_work(body))
        active[body.requestId] = task
        active_inputs[body.requestId] = hashlib.sha256(body.text.encode()).hexdigest()
        def cleanup(completed):
            if active.get(body.requestId) is completed:
                active.pop(body.requestId, None)
                active_inputs.pop(body.requestId, None)
        task.add_done_callback(cleanup)
        try:
            return await asyncio.shield(task)
        finally:
            if task.done() and active.get(body.requestId) is task:
                active.pop(body.requestId, None)
                active_inputs.pop(body.requestId, None)

    @app.post("/api/utterance")
    async def utterance(body: Utterance):
        try:
            return await handle_utterance(body)
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.get("/api/brain/jobs")
    async def jobs():
        return {"items": store.tasks(), "durable_planner": not bool(learning_service.error), "durable_jobs_url":"/api/learning/jobs"}

    @app.post("/api/brain/jobs/{request_id}/cancel")
    async def cancel(request_id: str):
        if task := active.get(request_id):
            task.cancel()
            return {"ok": True, "status": "cancelling"}
        raise HTTPException(404, "No running request with this id")

    @app.websocket("/ws/app")
    async def websocket(ws: WebSocket):
        session = sessions.get(ws.cookies.get("sight_session"))
        if (ws.headers.get("host") not in config.hosts or ws.headers.get("origin") != "http://" + ws.headers.get("host", "")
                or not session or not sessions.consume(ws.query_params.get("ticket", ""), session)):
            await ws.close(code=1008)
            return
        if len(sockets) >= 16:
            await ws.close(code=1013)
            return
        await ws.accept()
        sockets[id(ws)] = ws
        send_lock = asyncio.Lock()
        workers = set()

        async def send(message):
            async with send_lock:
                await ws.send_json(message)

        async def process(message):
            try:
                kind = message.pop("type", None)
                if kind == "utterance":
                    body = Utterance.model_validate(message)
                    await send({"type": "state", "state": "thinking", "requestId": body.requestId})
                    await send(await handle_utterance(body))
                elif kind == "cancel":
                    request_id = message.get("requestId")
                    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id):
                        raise ValueError("Invalid cancellation request")
                    task = active.get(request_id)
                    if task:
                        task.cancel()
                elif kind == "ping":
                    await send({"type": "pong"})
                else:
                    await send({"type": "error", "error": "Unknown message type"})
            except (ValidationError, ValueError, HTTPException):
                error = {"type": "error", "error": "Invalid or conflicting request"}
                request_id = message.get("requestId")
                if isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id):
                    error["requestId"] = request_id
                await send(error)
            except (WebSocketDisconnect, RuntimeError):
                pass
            except sqlite3.Error:
                await send({"type": "error", "error": "The local database is busy or unavailable. Retry after checking the data directory."})

        await send({"type": "hello", "phase": 4, "release": "PARTIAL"})
        try:
            while sessions.get(session.id):
                frame = await ws.receive()
                if frame["type"] == "websocket.disconnect":
                    break
                raw = frame.get("text")
                if raw is None:
                    await ws.close(code=1003)
                    break
                if not sessions.get(session.id):
                    await ws.close(code=1008)
                    break
                if len(raw.encode()) > 40_000:
                    await ws.close(code=1009)
                    break
                try:
                    message = json.loads(raw)
                    if not isinstance(message, dict):
                        raise ValueError()
                except ValueError:
                    await send({"type": "error", "error": "Invalid JSON message"})
                    continue
                if len(workers) >= 8:
                    await send({"type": "error", "error": "Connection queue full"})
                    continue
                worker = asyncio.create_task(process(message))
                workers.add(worker)
                worker.add_done_callback(workers.discard)
        except WebSocketDisconnect:
            pass
        finally:
            sockets.pop(id(ws), None)
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    def validate_action(path, args):
        try:
            validated = capability_service.validate(path,args)
            if validated is not None:return validated
            validated = learning_service.validate(path,args)
            if validated is not None:return validated
            if path in ('/api/chatgpt/connect','/api/chatgpt/disconnect'):
                return Connect.model_validate(args).model_dump(),'Open the official ChatGPT sign-in in your system browser.' if path.endswith('/connect') else 'Revoke this ChatGPT session and clear its local tokens.'
            if path == '/api/chatgpt/configure':
                policy=ChatGPTPolicy.model_validate(args)
                if policy.enabled and not (policy.allow_remote_text and policy.plan_only_confirmed and policy.model):raise ValueError('Plan-only confirmation and model required')
                return policy.model_dump(),'Set ChatGPT plan usage. Confirm SIGHT credit use is disabled in ChatGPT Settings. Daily cap: '+str(policy.daily_request_limit)+'.'
            if path == "/api/tools/files/write":
                parsed = FileWrite.model_validate(args)
                files.path(parsed.name)
                return parsed.model_dump(), f"Create {parsed.name} in SIGHT's private workspace. Existing files cannot be overwritten."
            if path == "/api/tools/desktop":
                parsed = DesktopAction.model_validate(args)
                return parsed.model_dump(), "Allow this one Windows desktop action: " + parsed.action + ". Clipboard text will not be stored."
            if path == "/api/models/unload" and args == {}:
                return {}, "Unload the configured local model from Ollama."
            if path == "/api/models/configure":
                policy = ProviderPolicy.model_validate(args)
                return policy.model_dump(), f"Set {policy.provider} policy. Enabled: {policy.enabled}; send typed chat text externally: {policy.allow_remote_text}; daily requests: {policy.daily_request_limit}; daily estimated budget: ${policy.daily_budget_usd}. Prices must match your account. Local-only startup overrides this policy."
        except (ValueError, ValidationError):
            raise HTTPException(422, "Invalid action arguments")
        raise HTTPException(403, "Action is not in the permitted capability registry")

    @app.post("/api/actions/prepare")
    async def prepare(body: Prepare, request: Request):
        args, summary = validate_action(body.path, body.args)
        token = store.prepare(request.state.session.id, body.path, args)
        audit("action.prepared", {"path": body.path})
        return {"approvalId": token, "args": args, "summary": summary, "expiresIn": 60}

    @app.post("/api/tools/files/write")
    @app.post("/api/tools/desktop")
    @app.post("/api/models/unload")
    @app.post("/api/models/configure")
    @app.post('/api/chatgpt/connect')
    @app.post('/api/chatgpt/disconnect')
    @app.post('/api/chatgpt/configure')
    @app.post('/api/capability/invoke')
    async def execute(request: Request, body: dict):
        token = body.pop("actionApproval", "")
        if not isinstance(token, str):
            raise HTTPException(422, "Invalid approval")
        args, _ = validate_action(request.url.path, body)
        if not store.consume(token, request.state.session.id, request.url.path, args):
            raise HTTPException(403, "Approval is absent, changed, expired, already used, or belongs to another session")
        audit("action.executing", {"path": request.url.path})
        try:
            if request.url.path == '/api/capability/invoke':return await capability_service.invoke(args)
            if request.url.path.startswith('/api/learning/'):
                return await learning_service.execute(request.url.path,args)
            if request.url.path == '/api/chatgpt/connect':return chatgpt.begin(request.state.session.id,args['account'])
            if request.url.path == '/api/chatgpt/disconnect':return await chatgpt.disconnect(args['account'])
            if request.url.path == '/api/chatgpt/configure':
                if args['enabled'] and args['model'] not in {m['slug'] for m in (await chatgpt.models())['items']}:raise ValueError('Select an account model')
                store.set_setting('chatgpt.policy',args);return {'saved':True,'local_only':local_only}
            if request.url.path == "/api/tools/files/write":
                return files.write_new(**args)
            if request.url.path == "/api/tools/desktop":
                return await asyncio.to_thread(desktop_invoke, DesktopAction.model_validate(args))
            if request.url.path == "/api/models/configure":
                store.set_setting("provider." + args["provider"], args)
                return {"ok": True, "policy": args, "local_only": local_only}
            return await local.unload()
        except (ValueError, OSError, asyncio.TimeoutError, httpx.HTTPError, subprocess.SubprocessError):
            audit("action.failed", {"path": request.url.path})
            raise HTTPException(409, "Action unavailable or failed; inspect the capability requirements. Nothing is automatically retried.")

    for action in ACTIONS:
        app.add_api_route('/api/learning/'+action,execute,methods=['POST'])

    @app.get("/api/tools/files")
    async def list_files():
        return {"items": files.list(), "scope": "SIGHT private workspace"}

    @app.get("/api/tools/files/read")
    async def read_file(name: str):
        try:
            return {"name": name, "content": files.read(name)}
        except (ValueError, OSError, UnicodeError):
            raise HTTPException(404, "File is unavailable in the permitted workspace")

    @app.post("/api/sos")
    async def sos():
        store.set_setting("sos", True)
        audit("sos.local_alert")
        return {"ok": True, "localOnly": True, "contactsNotified": False, "message": "Local SOS alert active. No call or message has been sent. Contact emergency services directly if you need help."}

    return app
