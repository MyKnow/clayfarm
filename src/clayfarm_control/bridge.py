"""Authenticated gateway to the existing PostgreSQL DAG and private Storage.

No queue mirror, shadow Auth accounts, bearer tokens or signed Storage URLs are
sent to nodes. FixtureStorage is deliberately absent from production startup.
"""
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
import json
import re
import uuid

import httpx
from sqlalchemy import text, select
from sqlalchemy.exc import DBAPIError

from .common import CFError, canonical, sha, secure_url
from .db import nodes, record

MAX_ARTIFACT = 50 * 1024 * 1024
HUMAN_ACTIONS = {'me','workers','submit','get','cancel','approve','list'}
NODE_ACTIONS = {'me','get','heartbeat','peek','claim','renew','computed','finish','fail'}


class SupabaseStorage:
    def __init__(self, url, key):
        self.url = secure_url(url)
        if not key:
            raise CFError('storage_key_required', 'The server Storage credential is required')
        self.http = httpx.Client(timeout=60, follow_redirects=False,
                                 headers={'apikey':key, 'Authorization':'Bearer '+key})

    def _url(self, key):
        return self.url + '/storage/v1/object/clayfarm/' + quote(key, safe='/')

    def read(self, key):
        try:
            with self.http.stream('GET', self._url(key)) as response:
                if response.status_code == 404:
                    raise CFError('artifact_missing', 'Artifact is not stored', 404)
                if response.status_code != 200:
                    raise CFError('storage_unavailable', 'Storage read failed; retry retained locally', 503)
                data = bytearray()
                for block in response.iter_bytes():
                    data.extend(block)
                    if len(data) > MAX_ARTIFACT:
                        raise CFError('artifact_size', 'Artifact exceeds 50 MiB', 413)
                return bytes(data)
        except httpx.HTTPError:
            raise CFError('storage_unavailable', 'Storage unavailable; local state retained', 503) from None

    def write(self, key, data):
        try:
            response = self.http.post(self._url(key), content=data,
                                      headers={'Content-Type':'application/octet-stream', 'x-upsert':'false'})
        except httpx.HTTPError:
            raise CFError('storage_unavailable', 'Upload interrupted; retry with the same key', 503) from None
        if response.status_code not in (200,201):
            # A lost upload response is reconciled using the bytes, not existence
            # or length alone. No overwrite permission is requested.
            if response.status_code in (400,409) and self.read(key) == data:
                return
            raise CFError('storage_unavailable', 'Storage upload failed; local state retained', 503)


class FixtureStorage:
    """Filesystem bytes + SQL object metadata fixture. NOT real Supabase Storage."""
    def __init__(self, db, root):
        self.db, self.root = db, Path(root)

    def read(self, key):
        path = self.root / key
        if not path.is_file():
            raise CFError('artifact_missing', 'Fixture artifact missing', 404)
        return path.read_bytes()

    def write(self, key, data):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open('xb') as f:
                f.write(data)
        except FileExistsError:
            if path.read_bytes() != data:
                raise CFError('artifact_conflict', 'Immutable artifact differs', 409)
        with self.db.transaction() as c:
            c.execute(text("INSERT INTO storage.objects(bucket_id,name) VALUES ('clayfarm',:key) ON CONFLICT DO NOTHING"), {'key':key})


class CentralBridge:
    def __init__(self, db, farm_id, storage):
        if db.sqlite:
            raise CFError('postgres_required', 'Central mode requires the existing PostgreSQL database')
        self.db, self.farm_id, self.storage = db, str(uuid.UUID(farm_id)), storage

    def bind_farm(self):
        """Operator-only setup on a database connection, never an HTTP approval."""
        with self.db.transaction() as c:
            if not c.execute(text('SELECT 1 FROM public.cf_members WHERE farm_id=:farm LIMIT 1'), {'farm':self.farm_id}).first():
                raise CFError('farm_not_found', 'Select an existing farm; approval cannot create one')
            c.execute(text('INSERT INTO cf_control.farm_binding(singleton,farm_id) VALUES (true,:farm) ON CONFLICT DO NOTHING'), {'farm':self.farm_id})
            if str(c.execute(text('SELECT farm_id FROM cf_control.farm_binding WHERE singleton')).scalar_one()) != self.farm_id:
                raise CFError('farm_binding_conflict', 'This control database is already bound to a different farm', 409)

    @contextmanager
    def transaction(self):
        try:
            with self.db.transaction() as c:
                yield c
        except DBAPIError as exc:
            code = getattr(exc.orig, 'sqlstate', None)
            # SQL details, SQL text and parameters never become user-facing errors.
            if code == '42501':
                raise CFError('central_access_denied', 'Current approval, ownership or lease does not permit this operation', 403) from None
            if code in ('23505','40001','40P01'):
                raise CFError('central_conflict', 'Concurrent change; retry the same operation', 409) from None
            if code in ('22023','22P02','23514','P0001'):
                raise CFError('invalid_central_request', 'The request violates the central task contract', 422) from None
            raise CFError('central_unavailable', 'Central queue is unavailable or migration is required', 503) from None

    def _args(self, identity, node):
        return {'actor':str(uuid.UUID(identity['id'])), 'kind':'node' if node else 'human',
                'session':None if node else identity.get('session_id')}

    def _member(self, c, args):
        value = c.execute(text('SELECT to_jsonb(clayfarm_private.control_member(CAST(:actor AS uuid),:kind,:session))'), args).scalar_one()
        if value['farm_id'] != self.farm_id:
            raise CFError('farm_binding_conflict', 'Server farm configuration does not match its database', 409)
        return value

    def rpc(self, identity, node, action, payload):
        if action not in (NODE_ACTIONS if node else HUMAN_ACTIONS):
            raise CFError('central_action_denied', 'Operation is not allowed for this identity', 403)
        if not isinstance(payload,dict) or len(canonical(payload)) > 262144:
            raise CFError('invalid_central_request', 'Expected bounded task arguments', 422)
        if action == 'submit':
            from clayfarm.spec import validate_spec
            from clayfarm.util import FarmError
            try:
                validate_spec(payload.get('spec'))
            except FarmError:
                raise CFError('invalid_spec', '3D specification is invalid', 422) from None
            # Bind immutable idempotency to the actual complete plan, never a
            # client-chosen digest that could mask a changed request.
            if payload.get('request_hash') != sha(canonical({k:v for k,v in payload.items() if k!='request_hash'})):
                raise CFError('request_hash_mismatch', 'Task plan hash is invalid', 422)
        args = self._args(identity, node)
        with self.transaction() as c:
            self._member(c,args)
            if node and action == 'finish':
                self._validate_output(c,args,payload)
            return c.execute(text('SELECT clayfarm_private.control_rpc(CAST(:actor AS uuid),:kind,:action,CAST(:payload AS jsonb),:session)'),
                             {**args,'action':action,'payload':canonical(payload).decode()}).scalar_one()

    def _scope(self, c, args, key, write):
        if not isinstance(key,str) or len(key)>512 or not re.fullmatch(r'[A-Za-z0-9_./-]+',key) or '..' in key:
            raise CFError('invalid_artifact_scope', 'Invalid object key', 403)
        self._member(c,args)
        c.execute(text('SELECT clayfarm_private.control_storage(CAST(:actor AS uuid),:kind,:key,:write,:session)'),
                  {**args,'key':key,'write':write}).scalar_one()

    def upload(self, identity, node, key, data):
        if not 0 < len(data) <= MAX_ARTIFACT:
            raise CFError('artifact_size', 'Artifact must be 1 byte to 50 MiB', 413)
        digest = sha(data)
        if key.rsplit('/',1)[-1].split('-',1)[0] != digest:
            raise CFError('artifact_hash_mismatch', 'Object key must match the uploaded bytes', 422)
        args = self._args(identity,node)
        with self.transaction() as c:
            self._scope(c,args,key,True)
            # Locks remain held until the bounded Storage request and receipt
            # complete; revocation is ordered before or after this operation.
            self.storage.write(key,data)
            self._scope(c,args,key,True)  # lease may have expired during upload
            c.execute(text('INSERT INTO cf_control.bridge_artifacts(path,actor,sha256,size) VALUES (:path,:actor,:sha,:size) ON CONFLICT(path) DO NOTHING'),
                      {'path':key,'actor':args['actor'],'sha':digest,'size':len(data)})
        return {'path':key,'sha256':digest,'size':len(data)}

    def download(self, identity, node, key):
        with self.transaction() as c:
            args = self._args(identity,node)
            self._scope(c,args,key,False)
            data = self.storage.read(key)
            self._scope(c,args,key,False)
            if sha(data) != key.rsplit('/',1)[-1].split('-',1)[0]:
                raise CFError('artifact_hash_mismatch', 'Stored artifact failed integrity verification', 409)
            return data

    def _validate_output(self, c, args, payload):
        output = payload.get('output')
        files = output.get('files') if isinstance(output,dict) else None
        if not isinstance(files,list) or not 1<=len(files)<=16:
            raise CFError('invalid_output', 'Expected one to sixteen verified artifacts', 422)
        # Duplicate finish is allowed after lease end only when the complete
        # manifest equals the committed result of the same node and attempt.
        committed = c.execute(text("SELECT clayfarm_private.control_committed(CAST(:actor AS uuid),CAST(:tid AS uuid),CAST(:attempt AS uuid))"),
                              {**args,'tid':payload.get('task_id'),'attempt':payload.get('attempt_id')}).scalar_one()
        if committed is not None:
            if committed == output:
                return
            raise CFError('result_conflict', 'Committed result is immutable', 409)
        for f in files:
            if not isinstance(f,dict) or not {'path','sha256','size','name','role'} <= f.keys():
                raise CFError('invalid_output', 'Artifact descriptor is incomplete', 422)
            self._scope(c,args,f['path'],True)
            parts=f['path'].split('/')
            if parts[2]!=payload.get('task_id') or parts[3]!=payload.get('attempt_id'):
                raise CFError('invalid_output', 'Artifact belongs to another attempt', 409)
            receipt = c.execute(text('SELECT sha256,size FROM cf_control.bridge_artifacts WHERE path=:path AND actor=:actor'),
                                {**args,'path':f['path']}).first()
            if not receipt or receipt[0]!=f['sha256'] or receipt[1]!=f['size']:
                raise CFError('invalid_output', 'Artifact is not backed by a verified upload', 409)

    def set_engines(self, admin, nid, engines):
        if not isinstance(engines,list) or set(engines)-{'sf3d','triposr','blender'}:
            raise CFError('invalid_engines', 'Select implemented 3D engines only', 422)
        with self.transaction() as c:
            if not c.execute(select(nodes).where(nodes.c.id==nid).with_for_update()).first():
                raise CFError('not_found', 'Node not found', 404)
            c.execute(text('INSERT INTO cf_control.node_engines(node_id,engines) VALUES (:id,:engines) ON CONFLICT(node_id) DO UPDATE SET engines=excluded.engines'),
                      {'id':nid,'engines':sorted(set(engines))})
            record(c,admin['id'],'node_engines_changed',nid,{'engines':engines})
        return {'node_id':nid,'allowed_engines':engines,'execution_ready':False}
