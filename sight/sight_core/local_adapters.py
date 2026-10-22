"""Independent, bounded local transformations. Never execute source supplied as data."""
import ast
from datetime import datetime, timezone
import difflib
import html
import io
import math
import struct
import uuid
import zipfile
from typing import Literal
from pydantic import Field, model_validator
from .tools import StrictModel

class Empty(StrictModel):pass
class Text(StrictModel):
    text:str=Field(min_length=1,max_length=16000)
class Document(Text):
    title:str=Field(default='SIGHT document',min_length=1,max_length=200)
class Search(StrictModel):
    query:str=Field(default='',max_length=100)
class Diff(StrictModel):
    before:str=Field(max_length=16000)
    after:str=Field(max_length=16000)
class Calendar(StrictModel):
    title:str=Field(min_length=1,max_length=200)
    start:datetime
    end:datetime
    description:str=Field(default='',max_length=2000)
    @model_validator(mode='after')
    def dates(self):
        if self.start.tzinfo is None or self.end.tzinfo is None or self.end<=self.start:raise ValueError('Explicit timezone and increasing dates required')
        if (self.end-self.start).total_seconds()>366*86400:raise ValueError('Event too long')
        return self
class Box(StrictModel):
    x:float=Field(gt=0,le=1000,allow_inf_nan=False)
    y:float=Field(gt=0,le=1000,allow_inf_nan=False)
    z:float=Field(gt=0,le=1000,allow_inf_nan=False)
class Circuit(StrictModel):
    volts:float=Field(gt=0,le=24,allow_inf_nan=False)
    ohms:float=Field(ge=1,le=10000000,allow_inf_nan=False)
class Geo(StrictModel):
    lat1:float=Field(ge=-90,le=90,allow_inf_nan=False)
    lon1:float=Field(ge=-180,le=180,allow_inf_nan=False)
    lat2:float=Field(ge=-90,le=90,allow_inf_nan=False)
    lon2:float=Field(ge=-180,le=180,allow_inf_nan=False)
class Gesture(StrictModel):
    thumb:tuple[float,float]
    index:tuple[float,float]
    @model_validator(mode='after')
    def normalized(self):
        if any(not math.isfinite(v) or not 0<=v<=1 for v in (*self.thumb,*self.index)):raise ValueError('Normalized landmarks required')
        return self
class BrowserHTML(StrictModel):
    html:str=Field(min_length=1,max_length=32000)
    fields:dict[str,str]=Field(default_factory=dict,max_length=8)
    @model_validator(mode='after')
    def bounded(self):
        import re
        if any(not re.fullmatch('[a-zA-Z][a-zA-Z0-9_-]{0,49}',k) or len(v)>500 for k,v in self.fields.items()):raise ValueError('Use simple element IDs and short values')
        return self
class Speech(StrictModel):
    text:str=Field(min_length=1,max_length=500)

def docx(value:Document):
    # Minimal valid OOXML; strings are escaped, never treated as macros or markup.
    xml=lambda s:html.escape(''.join(c for c in s if c in '\n\t\r' or ord(c)>=32))
    paragraphs=[value.title,*value.text.splitlines()]
    body=''.join('<w:p><w:r><w:t xml:space="preserve">'+xml(p)+'</w:t></w:r></w:p>' for p in paragraphs)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/document.xml','<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+body+'<w:sectPr/></w:body></w:document>')
    return out.getvalue()

def calendar(value:Calendar):
    def escape(s):return s.replace('\\','\\\\').replace('\r\n','\n').replace('\r','\n').replace('\n','\\n').replace(';','\\;').replace(',','\\,')
    def fold(s):
        lines=[];line=''
        for char in s:
            if len((line+char).encode())>75:lines.append(line);line=' '
            line+=char
        return '\r\n'.join([*lines,line])
    stamp=lambda dt:dt.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//SIGHT//Local Calendar//EN','BEGIN:VEVENT','UID:'+uuid.uuid4().hex+'@sight.local',
           'DTSTAMP:'+stamp(datetime.now(timezone.utc)),'DTSTART:'+stamp(value.start),'DTEND:'+stamp(value.end),
           'SUMMARY:'+escape(value.title),'DESCRIPTION:'+escape(value.description),'END:VEVENT','END:VCALENDAR']
    return '\r\n'.join(fold(s) for s in lines)+'\r\n'

def box_stl(value:Box):
    x,y,z=value.x,value.y,value.z
    vertices=[(0,0,0),(x,0,0),(x,y,0),(0,y,0),(0,0,z),(x,0,z),(x,y,z),(0,y,z)]
    faces=[(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    result=bytearray(b'SIGHT cuboid in millimetres'.ljust(80,b'\0')+struct.pack('<I',len(faces)))
    for indices in faces:
        a,b,c=[vertices[i] for i in indices];u=[b[i]-a[i] for i in range(3)];v=[c[i]-a[i] for i in range(3)]
        n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]];length=math.sqrt(sum(t*t for t in n))
        result.extend(struct.pack('<12fH',*[t/length for t in n],*a,*b,*c,0))
    return bytes(result)

def inspect_python(text):
    try:tree=ast.parse(text)
    except (SyntaxError,ValueError,RecursionError) as exc:return {'valid_syntax':False,'line':getattr(exc,'lineno',None),'executed':False}
    symbols=[{'name':n.name,'line':n.lineno,'kind':type(n).__name__} for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))]
    calls=[n.lineno for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in {'exec','eval','compile','__import__'}]
    return {'valid_syntax':True,'symbols':symbols[:100],'dynamic_execution_lines':calls[:100],'executed':False,'security_certified':False}

def static_site(value:Document):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+html.escape(value.title)+'</title><body><h1>'+html.escape(value.title)+'</h1><main><p>'+html.escape(value.text).replace('\n','</p><p>')+'</p></main></body></html>'

def distance(v:Geo):
    a,b=math.radians(v.lat1),math.radians(v.lat2);dlat=b-a;dlon=math.radians(v.lon2-v.lon1)
    h=math.sin(dlat/2)**2+math.cos(a)*math.cos(b)*math.sin(dlon/2)**2
    return {'kilometres':6371.0088*2*math.asin(math.sqrt(min(1,max(0,h)))),'method':'great-circle on mean-radius sphere','live_location':False,'route_guidance':False}

def diff(v:Diff):return ''.join(difflib.unified_diff(v.before.splitlines(True),v.after.splitlines(True),fromfile='before',tofile='after'))
