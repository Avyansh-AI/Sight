"""Durable in-app reminders and opt-in local health checks; no external delivery."""
import asyncio
from datetime import datetime, timezone
import json
import shutil
import sqlite3
import time
from pydantic import Field, model_validator
from .tools import StrictModel
from .security import canonical

class Reminder(StrictModel):
    id:str=Field(pattern=r'^[a-zA-Z0-9_-]{8,80}$')
    title:str=Field(min_length=1,max_length=200)
    due:datetime
    interval_seconds:int=Field(default=0,ge=0,le=30*86400)
    @model_validator(mode='after')
    def valid(self):
        if self.due.tzinfo is None:raise ValueError('Timezone required')
        if 0<self.interval_seconds<60:raise ValueError('Minimum recurrence is 60 seconds')
        return self
class Select(StrictModel):
    id:str=Field(pattern=r'^[a-zA-Z0-9_-]{8,80}$')
class Monitor(StrictModel):
    enabled:bool=False
    minimum_free_mb:int=Field(default=1024,ge=100,le=100000)
    quiet_enabled:bool=False
    quiet_start_utc:int=Field(default=22,ge=0,le=23)
    quiet_end_utc:int=Field(default=7,ge=0,le=23)

class Proactive:
    def __init__(self,store,clock=time.time):
        self.store=store;self.clock=clock;self.task=None;self.error=None
        with store.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS reminders(id TEXT PRIMARY KEY, definition TEXT NOT NULL, due REAL NOT NULL, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, source TEXT NOT NULL, occurrence REAL NOT NULL, title TEXT NOT NULL, created REAL NOT NULL, read INTEGER NOT NULL DEFAULT 0, UNIQUE(source,occurrence));''')

    def add(self,value):
        definition=canonical(value.model_dump(mode='json'))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT definition FROM reminders WHERE id=?',(value.id,)).fetchone()
            if row:
                if row['definition']!=definition:raise ValueError('Reminder ID already used')
                return {'id':value.id,'created':False}
            if db.execute("SELECT COUNT(*) FROM reminders WHERE state='scheduled'").fetchone()[0]>=100:raise ValueError('Reminder limit reached')
            db.execute("INSERT INTO reminders VALUES(?,?,?,'scheduled')",(value.id,definition,value.due.timestamp()))
        return {'id':value.id,'created':True,'delivery':'in-app only'}

    def cancel(self,identifier):
        with self.store.connect() as db:
            changed=db.execute("UPDATE reminders SET state='cancelled' WHERE id=? AND state='scheduled'",(identifier,)).rowcount
        return {'cancelled':bool(changed)}

    def list(self):
        with self.store.connect() as db:
            return [dict(r)|{'definition':json.loads(r['definition'])} for r in db.execute('SELECT * FROM reminders ORDER BY due LIMIT 200')]

    def notifications(self):
        with self.store.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM notifications ORDER BY id DESC LIMIT 100')]

    def configure(self,value):self.store.set_setting('phase3.monitor',value.model_dump());return value.model_dump()

    @staticmethod
    def quiet(policy,now):
        hour=datetime.fromtimestamp(now,timezone.utc).hour;a=policy.quiet_start_utc;b=policy.quiet_end_utc
        return policy.quiet_enabled and (a<=hour<b if a<b else hour>=a or hour<b)

    def tick(self):
        now=self.clock();policy=Monitor.model_validate(self.store.setting('phase3.monitor',{}));emitted=0
        # Quiet hours defer notifications and advance nothing, so they are not lost.
        if self.quiet(policy,now):return {'emitted':0,'quiet':True}
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute("SELECT * FROM reminders WHERE state='scheduled' AND due<=? ORDER BY due LIMIT 100",(now,)).fetchall():
                value=json.loads(row['definition']);interval=value['interval_seconds']
                emitted+=db.execute('INSERT OR IGNORE INTO notifications(source,occurrence,title,created) VALUES(?,?,?,?)',(row['id'],row['due'],value['title'],now)).rowcount
                # Coalesce missed recurrences after downtime, preserving fixed UTC cadence.
                due=row['due']+(int((now-row['due'])//interval)+1)*interval if interval else row['due']
                db.execute('UPDATE reminders SET due=?,state=? WHERE id=?',(due,'scheduled' if interval else 'delivered',row['id']))
            db.execute('DELETE FROM notifications WHERE id NOT IN (SELECT id FROM notifications ORDER BY id DESC LIMIT 200)')
        return {'emitted':emitted,'quiet':False}

    def health_tick(self):
        policy=Monitor.model_validate(self.store.setting('phase3.monitor',{}))
        if not policy.enabled:return {'enabled':False}
        now=self.clock()
        if self.quiet(policy,now):return {'enabled':True,'quiet':True}
        free=shutil.disk_usage(self.store.path.parent).free//(1024**2);state='low_disk' if free<policy.minimum_free_mb else 'ok'
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT value FROM settings WHERE key='phase3.health_state'").fetchone()
            previous=json.loads(row[0]) if row else None
            if previous!=state and (state!='ok' or previous is not None):
                db.execute('INSERT OR IGNORE INTO notifications(source,occurrence,title,created) VALUES(?,?,?,?)',('health',now,'Local workspace disk: '+state,now))
            db.execute("INSERT INTO settings VALUES('phase3.health_state',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(canonical(state),))
        return {'enabled':True,'state':state,'free_mb':free,'measured_at':now}

    async def start(self):
        async def run():
            ticks=0
            while True:
                try:
                    self.tick()
                    if ticks%60==0:self.health_tick()
                    self.error=None
                except (ValueError,OSError,sqlite3.Error):self.error='Scheduler storage or configuration unavailable'
                ticks+=1;await asyncio.sleep(1)
        self.task=asyncio.create_task(run())

    async def stop(self):
        if self.task:
            self.task.cancel();await asyncio.gather(self.task,return_exceptions=True);self.task=None
