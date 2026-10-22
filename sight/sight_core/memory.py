"""Owner-approved, project-scoped memory; no automatic capture of chat transcripts."""
import re
import time
import uuid
from typing import Literal

from pydantic import Field
from .tools import StrictModel
from .security import TOKEN_PATTERN

TABLES = {'profile':'profiles', 'episode':'episodes', 'document':'episodes'}


class MemoryInput(StrictModel):
    store: Literal['profile','episode','document'] = 'profile'
    project_id: str = Field(default='default',pattern=r'^[A-Za-z0-9_-]{1,80}$')
    key: str = Field(min_length=1,max_length=80,pattern=r'^[A-Za-z0-9_.-]+$')
    content: str = Field(min_length=1,max_length=12000)
    source_uri: str = Field(default='owner_statement',max_length=500)
    privacy_scope: Literal['local','cloud_allowed'] = 'local'
    ttl_days: int | None = Field(default=None,ge=1,le=3650)
    confidence: float = Field(default=1.0,ge=0,le=1,allow_inf_nan=False)


class MemoryDelete(StrictModel):
    id: str = Field(pattern=r'^[a-f0-9-]{36}$')


class MemoryEdit(MemoryInput):
    id: str = Field(pattern=r'^[a-f0-9-]{36}$')


class MemoryService:
    def __init__(self, store, clock=time.time): self.store,self.clock=store,clock

    def put(self, value: MemoryInput, identifier=None):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            now = self.clock()
            identifier = self._put(db, value, identifier, now)
            return self._get(db, identifier, now, {})

    def _put(self, db, value, identifier, now):
        """Write within the caller's transaction, including index and audit event."""
        if TOKEN_PATTERN.search(value.content) or TOKEN_PATTERN.search(value.source_uri):
            raise ValueError('Credentials belong in the OS vault, not learning memory')
        table=TABLES[value.store]
        old=db.execute(f'SELECT * FROM {table} WHERE id=?',(identifier,)).fetchone() if identifier else None
        if identifier and not old: raise ValueError('Memory record not found in this store')
        if not identifier and value.store=='profile':
            old=db.execute('SELECT * FROM profiles WHERE owner_id=? AND project_id=? AND key=?',(self.store.owner_id,value.project_id,value.key)).fetchone()
        identifier=old['id'] if old else identifier or str(uuid.uuid4())
        event_id='owner-'+str(uuid.uuid4())
        expiry=now+value.ttl_days*86400 if value.ttl_days else None
        record=(identifier,self.store.owner_id,value.project_id,value.key,value.content,old['created_at'] if old else now,
                now,event_id,value.source_uri,value.confidence,expiry,value.privacy_scope,(old['revision']+1) if old else 1)
        if old:
            self._remove_derived(db,identifier)
            db.execute(f'DELETE FROM {table} WHERE id=?',(identifier,))
        db.execute(f'INSERT INTO {table} VALUES({",".join("?" for _ in record)})',record)
        db.execute('DELETE FROM memory_fts WHERE id=?',(identifier,))
        db.execute('INSERT INTO memory_fts VALUES(?,?,?,?)',(identifier,value.store,value.project_id,value.content))
        self.store.event('memory.confirmed',identifier,{'store':value.store,'project':value.project_id,'revision':record[-1],'source_event_id':event_id},db)
        return identifier

    def get(self, identifier):
        with self.store.connect() as db:
            db.execute('BEGIN')
            return self._get(db, identifier, self.clock(), {})

    def _get(self, db, identifier, now, cache):
        """Validate lineage iteratively within one snapshot; cache shared ancestors."""
        pending = [(identifier, False)]
        visiting = set()
        nodes = {}
        while pending:
            current, finish = pending.pop()
            if finish:
                row, sources = nodes[current]
                visiting.remove(current)
                cache[current] = row if all(cache.get(source) for source in sources) else None
                continue
            if current in cache:
                continue
            if current in visiting:
                # Corrupt/restored cycles must fail closed, not exhaust recursion.
                cache[current] = None
                continue
            row = None
            for kind,table in (('profile','profiles'),('episode','episodes')):
                row=db.execute(f'SELECT * FROM {table} WHERE id=? AND (expiry IS NULL OR expiry>?)',(current,now)).fetchone()
                if row:
                    tag=db.execute('SELECT store FROM memory_fts WHERE id=?',(current,)).fetchone()
                    row=dict(row)|{'store':tag[0] if tag else kind,'source_link':'/api/learning/memory/'+current}
                    break
            if row is None:
                cache[current] = None
                continue
            sources = [s[0] for s in db.execute("SELECT source FROM graph_edges WHERE target=? AND relation='summarized_into'", (current,))]
            # Older interrupted compactions can contain a summary without links.
            # Preserve the stored bytes, but do not retrieve untraceable summaries.
            if row['source_uri'] == 'extractive_compaction' and not sources:
                cache[current] = None
                continue
            nodes[current] = (row, sources)
            visiting.add(current)
            pending.append((current, True))
            pending.extend((source, False) for source in reversed(sources))
        return cache[identifier]

    def export(self, project_id=None):
        with self.store.connect() as db:
            db.execute('BEGIN')
            now=self.clock();cache={}
            ids=[]
            for table in ('profiles','episodes'):
                ids += [r[0] for r in db.execute(f'SELECT id FROM {table} WHERE (? IS NULL OR project_id=?) AND (expiry IS NULL OR expiry>?)',(project_id,project_id,now))]
            return [r for ident in ids if (r:=self._get(db,ident,now,cache))]

    def search(self, query, project_id='default', limit=8, remote=False):
        words=re.findall(r'\w+',query,flags=re.UNICODE)[:12]
        if not words:return []
        fts=' OR '.join('"'+w.replace('"','""')+'"' for w in words)
        with self.store.connect() as db:
            db.execute('BEGIN')
            now=self.clock();cache={};rows=[]
            # The limit counts usable results, not expired/private FTS matches.
            ids=db.execute('SELECT id FROM memory_fts WHERE memory_fts MATCH ? AND project_id=? ORDER BY rank', (fts,project_id))
            for item in ids:
                row=self._get(db,item[0],now,cache)
                if row and (not remote or row['privacy_scope']=='cloud_allowed'):
                    rows.append(row)
                    if len(rows)>=max(1,min(limit,50)):break
            return rows

    def preferences(self, project_id='default', remote=False):
        return [r for r in self.export(project_id) if r['store']=='profile' and (not remote or r['privacy_scope']=='cloud_allowed')]

    def context(self, query, project_id='default', remote=False, max_bytes=500):
        rows={r['id']:r for r in self.preferences(project_id,remote)+self.search(query,project_id,remote=remote)}
        chunks=[];citations=[]
        for row in list(rows.values())[:6]:
            chunk=f"[{row['id']}] {row['key']}: {row['content']}\n"
            remaining=max_bytes-len(''.join(chunks).encode())
            if remaining < 60:break
            chunks.append(chunk.encode()[:remaining].decode('utf-8',errors='ignore'))
            citations.append({'id':row['id'],'revision':row['revision'],'source_link':row['source_link']})
        return {'text':''.join(chunks),'sources':citations}

    def _remove_derived(self,db,identifier):
        pending=[identifier];deleted=set()
        while pending:
            source=pending.pop()
            for row in db.execute("SELECT target FROM graph_edges WHERE source=? AND relation='summarized_into'",(source,)).fetchall():
                if row[0] not in deleted:
                    deleted.add(row[0]);pending.append(row[0])
        for derived in deleted:
            db.execute('DELETE FROM episodes WHERE id=?',(derived,));db.execute('DELETE FROM memory_fts WHERE id=?',(derived,))
            db.execute('DELETE FROM graph_edges WHERE source=? OR target=?',(derived,derived))
        return deleted

    def delete(self,identifier):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            derived=self._remove_derived(db,identifier)
            count=0
            for table in ('profiles','episodes'):count+=db.execute(f'DELETE FROM {table} WHERE id=?',(identifier,)).rowcount
            db.execute('DELETE FROM memory_fts WHERE id=?',(identifier,))
            db.execute('DELETE FROM graph_edges WHERE source=? OR target=?',(identifier,identifier))
            self.store.event('memory.deleted',identifier,{'derived_removed':len(derived)},db)
        return {'deleted':bool(count),'derived_removed':len(derived)}

    def purge_expired(self):
        with self.store.connect() as db:
            ids=[r[0] for table in ('profiles','episodes') for r in db.execute(f'SELECT id FROM {table} WHERE expiry<=?',(self.clock(),))]
        for ident in ids:self.delete(ident)
        with self.store.connect() as db:
            # FTS segments retain old terms until merged; optimize after secure deletion.
            db.execute("INSERT INTO memory_fts(memory_fts) VALUES('optimize')")
        return {'purged':len(ids)}

    def compact(self, identifiers, project_id='default'):
        if not 1 <= len(identifiers) <= 20:raise ValueError('Choose one to twenty source records')
        if len(set(identifiers)) != len(identifiers):raise ValueError('Choose distinct source records')
        with self.store.connect() as db:
            # Acquire the write lock before reading sources. Summary, index, event
            # and provenance commit together, or all roll back even on a crash.
            db.execute('BEGIN IMMEDIATE')
            now=self.clock();cache={}
            rows=[self._get(db,i,now,cache) for i in identifiers]
            if any(not r or r['project_id']!=project_id for r in rows):raise ValueError('Missing or cross-project source')
            content='\n'.join(f"[{r['id']}] {r['key']}: {r['content'][:180]}" for r in rows)
            value=MemoryInput(store='episode',project_id=project_id,key='compaction',content=content,
                              source_uri='extractive_compaction',privacy_scope='cloud_allowed' if all(r['privacy_scope']=='cloud_allowed' for r in rows) else 'local')
            identifier=self._put(db,value,None,now)
            for row in rows:db.execute('INSERT INTO graph_edges VALUES(?,?,?)',(row['id'],identifier,'summarized_into'))
            result=self._get(db,identifier,now,cache)
            return result|{'sources':[r['source_link'] for r in rows],'method':'bounded extractive summary, not model-generated'}
