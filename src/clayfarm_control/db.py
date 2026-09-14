from __future__ import annotations
from contextlib import contextmanager
from sqlalchemy import (create_engine, MetaData, Table, Column, String, Integer, Float, JSON, Text, UniqueConstraint, select, event)
from sqlalchemy.pool import StaticPool
from .common import now, uid

metadata=MetaData()
users=Table("users",metadata,Column("id",String,primary_key=True),Column("email",String,nullable=False),Column("role",String,nullable=False),Column("status",String,nullable=False),Column("grants",JSON,nullable=False),Column("created_at",Float,nullable=False))
requests=Table("requests",metadata,Column("id",String,primary_key=True),Column("owner",String,nullable=False),Column("kind",String,nullable=False),Column("payload",JSON,nullable=False),Column("payload_hash",String,nullable=False),Column("idempotency_key",String,nullable=False),Column("state",String,nullable=False),Column("decision",JSON),Column("created_at",Float,nullable=False),UniqueConstraint("owner","idempotency_key"))
nodes=Table("nodes",metadata,Column("id",String,primary_key=True),Column("owner",String,nullable=False),Column("name",String,nullable=False),Column("public_key",String,unique=True,nullable=False),Column("status",String,nullable=False),Column("inventory",JSON,nullable=False),Column("capabilities",JSON,nullable=False),Column("desired",JSON,nullable=False),Column("last_seen",Float),Column("created_at",Float,nullable=False))
events=Table("events",metadata,Column("id",Integer,primary_key=True,autoincrement=True),Column("audience",String,nullable=False),Column("kind",String,nullable=False),Column("payload",JSON,nullable=False),Column("created_at",Float,nullable=False),Column("delivered_at",Float))
audit=Table("audit",metadata,Column("id",Integer,primary_key=True,autoincrement=True),Column("actor",String,nullable=False),Column("action",String,nullable=False),Column("target",String,nullable=False),Column("details",JSON,nullable=False),Column("created_at",Float,nullable=False))
nonces=Table("nonces",metadata,Column("node_id",String,primary_key=True),Column("nonce",String,primary_key=True),Column("created_at",Float,nullable=False))
revocations=Table("revocations",metadata,Column("session_id",String,primary_key=True),Column("expires_at",Float,nullable=False))
jobs=Table("jobs",metadata,Column("id",String,primary_key=True),Column("owner",String,nullable=False),Column("profile_id",String,nullable=False),Column("profile_digest",String,nullable=False),Column("release_id",String,nullable=False),Column("spec",JSON,nullable=False),Column("request_hash",String,nullable=False),Column("idempotency_key",String,nullable=False),Column("state",String,nullable=False),Column("node_id",String),Column("attempt_id",String),Column("lease_until",Float),Column("attempt_count",Integer,nullable=False),Column("output",JSON),Column("error",JSON),Column("created_at",Float,nullable=False),UniqueConstraint("owner","idempotency_key"))
releases=Table("releases",metadata,Column("id",String,primary_key=True),Column("envelope",JSON,nullable=False),Column("published_by",String,nullable=False),Column("created_at",Float,nullable=False))

class Database:
    def __init__(self,url):
        opts={"future":True,"pool_pre_ping":True}
        if url in ("sqlite://","sqlite:///:memory:"): opts.update(poolclass=StaticPool,connect_args={"check_same_thread":False})
        elif url.startswith("sqlite:"): opts["connect_args"]={"check_same_thread":False,"timeout":30}
        self.engine=create_engine(url,**opts)
        self.sqlite=url.startswith("sqlite:")
        if self.sqlite:
            @event.listens_for(self.engine,"connect")
            def config(conn,_):
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA busy_timeout=30000")
        else:
            @event.listens_for(self.engine,"connect")
            def config(conn,_):
                # The dedicated schema must be explicitly initialized by the operator.
                with conn.cursor() as cur: cur.execute("SET search_path TO cf_control")
                conn.commit()
    def init(self):
        if not self.sqlite:
            with self.engine.begin() as c:
                c.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS cf_control")
                c.exec_driver_sql("REVOKE ALL ON SCHEMA cf_control FROM PUBLIC")
        metadata.create_all(self.engine)
    @contextmanager
    def transaction(self):
        # BEGIN IMMEDIATE also makes approval idempotency robust on SQLite.
        with self.engine.connect() as c:
            if self.sqlite: c.exec_driver_sql("BEGIN IMMEDIATE")
            else: c.begin()
            try: yield c; c.commit()
            except BaseException: c.rollback(); raise
    def read(self,table,**where):
        with self.engine.connect() as c:
            q=select(table)
            for k,v in where.items(): q=q.where(table.c[k]==v)
            return c.execute(q).mappings().first()
    def bootstrap_admin(self,user_id,email):
        from .common import CFError
        import uuid
        try: uuid.UUID(user_id)
        except ValueError: raise CFError("invalid_user","Bootstrap requires the verified Auth user UUID")
        with self.transaction() as c:
            existing=c.execute(select(users).where(users.c.role=="admin")).first()
            current=c.execute(select(users).where(users.c.id==user_id)).mappings().first()
            if existing and (not current or current["role"]!="admin"): raise CFError("already_bootstrapped","First administrator already exists")
            values={"email":email,"role":"admin","status":"active","grants":["creator-basic","experimental","release-manager"]}
            if current: c.execute(users.update().where(users.c.id==user_id).values(**values))
            else: c.execute(users.insert().values(id=user_id,created_at=now(),**values))
            record(c,user_id,"bootstrap_admin",user_id)
        return {"admin_id":user_id,"status":"active"}

def record(c,actor,action,target,details=None,audience=None):
    value=details or {}
    c.execute(audit.insert().values(actor=actor,action=action,target=target,details=value,created_at=now()))
    if audience:
        c.execute(events.insert().values(audience=audience,kind=action,payload={"target":target,**value},created_at=now()))
