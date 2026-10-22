"""Test-only server: real SIGHT and Ollama with scoped transport fault injection."""
import asyncio
import os
from pathlib import Path
import sys
import httpx
import uvicorn
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sight_core.api import create_app
from sight_core.cli import single_instance
from sight_core.config import Config
from sight_core.models import OllamaProvider

class FaultTransport(httpx.AsyncBaseTransport):
    def __init__(self,control):self.control=control;self.real=httpx.AsyncHTTPTransport()
    async def handle_async_request(self,request):
        mode=self.control.read_text() if self.control.exists() else ''
        if request.url.host!='127.0.0.1':raise AssertionError('External HTTP denied in soak')
        if mode=='disconnect':raise httpx.ConnectError('Injected local-runtime disconnection',request=request)
        if mode=='delay' and request.url.path=='/api/chat':await asyncio.sleep(30)
        return await self.real.handle_async_request(request)
    async def aclose(self):await self.real.aclose()

class Local(OllamaProvider):
    def client(self,timeout=None):
        return httpx.AsyncClient(base_url=self.config.ollama_url,timeout=timeout or self.config.model_timeout,trust_env=False,follow_redirects=False,
                                 transport=FaultTransport(self.config.data_dir/'test-transport-fault'))

if __name__=='__main__':
    config=Config.from_env()
    with single_instance(config.data_dir):
        (config.data_dir/'soak-server.pid').write_text(str(os.getpid()))
        uvicorn.run(create_app(config,Local(config),local_only=True),host='127.0.0.1',port=config.port,access_log=False,server_header=False,ws_max_size=40000)
