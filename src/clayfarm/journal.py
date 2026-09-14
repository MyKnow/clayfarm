from __future__ import annotations
import json
import contextlib
import sqlite3
import time
from pathlib import Path
from .util import canonical, sqlite_path


class Journal:
    """Local durable state. One connection per operation supports CPU/GPU threads."""
    def __init__(self, path: Path):
        # Worker artifacts use extended Windows paths; status uses ordinary paths.
        # Give SQLite one spelling for the database and its WAL/shared-memory files.
        self.path=sqlite_path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute("pragma journal_mode=WAL")
            db.execute("create table if not exists work (id text primary key, task text not null, state text not null, result text, updated real not null)")
            db.execute("create table if not exists kv (key text primary key,value text not null)")

    @contextlib.contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=15)
        try:
            db.row_factory=sqlite3.Row
            db.execute("pragma synchronous=FULL")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def save(self, task, state, result=None):
        with self.connect() as db:
            db.execute("insert into work values (?,?,?,?,?) on conflict(id) do update set task=excluded.task,state=excluded.state,result=excluded.result,updated=excluded.updated",
                       (task["id"],canonical(task),state,canonical(result) if result is not None else None,time.time()))

    def entries(self, states):
        with self.connect() as db:
            rows=db.execute(f"select * from work where state in ({','.join('?' for _ in states)}) order by updated",states).fetchall()
        return [{**dict(r),"task":json.loads(r["task"]),"result":json.loads(r["result"]) if r["result"] else None} for r in rows]

    def entry(self, task_id):
        with self.connect() as db:
            r=db.execute("select * from work where id=?",(task_id,)).fetchone()
        if r is None: return None
        return {**dict(r),"task":json.loads(r["task"]),"result":json.loads(r["result"]) if r["result"] else None}

    def state(self, task_id):
        with self.connect() as db:
            r=db.execute("select state from work where id=?",(task_id,)).fetchone()
            return r[0] if r else None

    def put(self, key, value):
        with self.connect() as db:
            db.execute("insert into kv values (?,?) on conflict(key) do update set value=excluded.value",(key,canonical(value)))

    def get(self,key,default=None):
        with self.connect() as db:
            r=db.execute("select value from kv where key=?",(key,)).fetchone()
            return json.loads(r[0]) if r else default

    def cache_if_safe(self, task):
        with self.connect() as db:
            db.execute("insert into work values (?,?, 'cached',NULL,?) on conflict(id) do update set task=excluded.task,updated=excluded.updated where work.state='cached'",
                       (task["id"],canonical(task),time.time()))
