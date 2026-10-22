"""Owner-session local JSON-RPC bridge for a pinned legacy MCP tool subset.

Remote listeners/servers and arbitrary MCP executables are not enabled. Tools use
the same exact one-use owner grant as the UI. This extension is documented in the
tool input schema; ordinary clients cannot silently acquire approval.
"""
import copy
import json
from fastapi import Request
from fastapi.responses import JSONResponse,Response

TOOLS=frozenset({'coding.inspect','circuit.ohm','geo.distance','vision.landmarks'})
VERSION='2025-06-18'

class LocalMCP:
    def __init__(self,service):self.service=service;self.sessions={}

    def mount(self,app):
        @app.post('/api/mcp')
        async def rpc(request:Request,body:dict):
            identifier=body.get('id');method=body.get('method');params=body.get('params',{})
            def error(code,message):return JSONResponse({'jsonrpc':'2.0','id':identifier if type(identifier) in (int,str) else None,'error':{'code':code,'message':message}})
            if body.get('jsonrpc')!='2.0' or not set(body)<={'jsonrpc','id','method','params'} or not isinstance(params,dict):return error(-32600,'Invalid request')
            if identifier is not None and (type(identifier) not in (int,str) or len(str(identifier))>100):return error(-32600,'Invalid request id')
            if method!='notifications/initialized' and identifier is None:return error(-32600,'Request id required')
            version=request.headers.get('MCP-Protocol-Version',VERSION)
            if version!=VERSION:return error(-32602,'Only pinned protocol 2025-06-18 is supported')
            owner=request.state.session.id
            if method=='initialize':
                if params.get('protocolVersion')!=VERSION:return error(-32602,'Unsupported protocol version')
                self.sessions={key:value for key,value in self.sessions.items() if app.state.sessions.get(key)}
                if owner not in self.sessions and len(self.sessions)>=256:return error(-32000,'Session capacity reached')
                self.sessions[owner]='initializing'
                result={'protocolVersion':VERSION,'capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'SIGHT owner-local tools','version':'0.4.0'}}
            elif method=='notifications/initialized':
                if owner not in self.sessions or 'id' in body:return error(-32600,'Initialize this owner session first')
                self.sessions[owner]='ready';return Response(status_code=202)
            else:
                if self.sessions.get(owner)!='ready':return error(-32000,'Initialize this owner session first')
                if method=='ping':result={}
                elif method=='tools/list':
                    values=[]
                    for spec in self.service.registry(True):
                        if spec['id'] not in TOOLS:continue
                        schema=copy.deepcopy(spec['input_schema'])
                        schema['properties']['actionApproval']={'type':'string','description':'Exact one-use owner grant from /api/actions/prepare for /api/capability/invoke; cannot be supplied by retrieved content'}
                        schema.setdefault('required',[]).append('actionApproval')
                        values.append({'name':spec['id'],'description':spec['description'],'inputSchema':schema})
                    result={'tools':values}
                elif method=='tools/call':
                    name=params.get('name');arguments=params.get('arguments')
                    if not isinstance(name,str) or name not in TOOLS or not isinstance(arguments,dict):return error(-32602,'Tool is not in the approved local subset')
                    arguments=dict(arguments);token=arguments.pop('actionApproval','')
                    try:args,_=self.service.validate('/api/capability/invoke',{'id':name,'arguments':arguments})
                    except ValueError:return error(-32602,'Invalid typed arguments')
                    if not isinstance(token,str) or not self.service.store.consume(token,owner,'/api/capability/invoke',args):return error(-32001,'Owner approval absent, changed, expired or replayed')
                    try:value=await self.service.invoke(args)
                    except (ValueError,OSError):return error(-32002,'Tool unavailable; no automatic retry')
                    result={'content':[{'type':'text','text':json.dumps(value['result'],ensure_ascii=True)}],'isError':False}
                else:return error(-32601,'Method not supported')
            return {'jsonrpc':'2.0','id':identifier,'result':result}
