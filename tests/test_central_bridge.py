"""Real PostgreSQL queue tests; Auth identities and Storage service are fixtures."""
import json
import os
from pathlib import Path
import uuid
import copy

import pytest
from sqlalchemy import text

from clayfarm_control.common import CFError
from clayfarm_control.demo import ADMIN, USER, OTHER, FixtureVerifier, fixture_client
from clayfarm_control.db import Database
from clayfarm_control.registry import load_registry
from clayfarm_control.api import create_app
from test_security_api import request_access, register

FARM = 'e3374216-aea4-4c89-bca9-fcb6db3578ad'
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def central(tmp_path):
    dsn = os.environ.get('CLAYFARM_TEST_POSTGRES')
    if not dsn:
        pytest.skip('Set CLAYFARM_TEST_POSTGRES to a disposable PostgreSQL database')
    import psycopg
    from psycopg import sql
    from clayfarm_control.bridge import CentralBridge, FixtureStorage
    from sqlalchemy.engine import make_url
    name = 'cf_test_' + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    url = make_url(dsn).set(database=name)
    raw_url = url.render_as_string(hide_password=False)
    db = Database(url.set(drivername='postgresql+psycopg').render_as_string(hide_password=False))
    storage=None
    try:
        with psycopg.connect(raw_url, autocommit=True) as c:
            # Roles are cluster-wide and created once by the integration runner.
            fixture = (ROOT / 'tests_legacy/sql/00_fixture.sql').read_text()
            fixture = '\n'.join(l for l in fixture.splitlines() if not l.startswith(('\\', 'create role')))
            real_storage=bool(os.environ.get('CLAYFARM_TEST_STORAGE_IMAGE'))
            c.execute(fixture.split('create schema storage;')[0] if real_storage else fixture)
        if real_storage:
            from storage_service import RealStorage
            storage=RealStorage(raw_url,tmp_path)
        with psycopg.connect(raw_url,autocommit=True) as c:
            c.execute((ROOT / 'sql/bootstrap.sql').read_text())
            for identity in (ADMIN, USER, OTHER):
                c.execute('INSERT INTO auth.users(id) VALUES (%s)', (identity,))
            c.execute("INSERT INTO public.cf_members VALUES (%s,%s,'caller','legacy-caller',true)", (ADMIN, FARM))
        db.init()
        db.bootstrap_admin(ADMIN, 'admin@example.test')
        with psycopg.connect(raw_url, autocommit=True) as c:
            for migration in sorted((ROOT / 'supabase/migrations').glob('*.sql')):
                c.execute(migration.read_text())
        bridge = CentralBridge(db, FARM, storage or FixtureStorage(db, tmp_path / 'storage'))
        bridge.bind_farm()
        app = create_app(db, load_registry(), FixtureVerifier(), artifact_root=tmp_path / 'artifacts', bridge=bridge)
        clients = [fixture_client(tmp_path / n, app, 'fixture-' + n) for n in ('admin','user','other')]
        yield db, bridge, clients
        for client in clients:
            client.http.close()
    finally:
        if storage: storage.close()
        db.engine.dispose()
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def approve(admin, user):
    request = request_access(user)
    admin.call('POST', f'/v1/admin/requests/{request["id"]}/decision', {'approve': True})


def test_approved_caller_and_signed_node_share_legacy_queue(central, tmp_path):
    from clayfarm_control.bridge_client import BridgeBackend
    from clayfarm.cli import submit_job
    from clayfarm.png import encode
    db, bridge, (admin, user, other) = central
    approve(admin, user)
    nid, _ = register(admin, other)
    admin.call('PUT', f'/v1/admin/nodes/{nid}/engines', {'engines': ['triposr','blender']})
    caller = BridgeBackend(user)
    worker = BridgeBackend(other, node=True)
    concept = tmp_path / 'concept.png'
    concept.write_bytes(encode(16,16,bytes([180,90,40,255])*256))
    job = submit_job(caller, tmp_path / 'caller', {'name':'bridge-test'}, [concept], ['triposr'], {'agent':'test'})
    jid = job['job_id']
    with db.engine.connect() as c:
        assert c.execute(text('select count(*) from public.cf_jobs where id=:id'), {'id':jid}).scalar_one() == 1
        assert c.execute(text('select count(*) from cf_control.jobs')).scalar_one() == 0
    worker.rpc('heartbeat', {'capabilities':['triposr'], 'telemetry':{'on_battery':False}})
    task = worker.rpc('claim', {'slot':'gpu'})
    assert task['job_id'] == jid
    assert task['lease_owner'] == nid
    assert worker.rpc('claim', {'slot':'gpu'}) is None
    with pytest.raises(CFError):
        BridgeBackend(admin).rpc('get', {'id':jid})
    assert caller.rpc('get', {'id':jid})['tasks'][0]['job_id'] == jid


def test_pending_user_cannot_submit_or_read_storage(central):
    from clayfarm_control.bridge_client import BridgeBackend
    _, _, (admin,user,other) = central
    with pytest.raises(CFError) as err:
        BridgeBackend(user)
    assert err.value.status == 403


def test_central_mode_rejects_parallel_development_queue(central):
    _, _, (admin,user,other) = central
    approve(admin,user)
    with pytest.raises(CFError) as err:
        user.call('POST','/v1/jobs', {'profile_id':'procedural-sfx','spec':{'effect':'beep'},'idempotency_key':'second-queue-job'})
    assert err.value.code == 'central_queue_required'


def test_node_revocation_blocks_queue_and_storage(central):
    from clayfarm_control.bridge_client import BridgeBackend
    _, _, (admin,user,other) = central
    nid, _ = register(admin,user)
    worker = BridgeBackend(user,node=True)
    user.call('PATCH',f'/v1/nodes/{nid}/status',{'status':'revoked'})
    with pytest.raises(CFError) as err:
        worker.rpc('heartbeat',{'capabilities':[],'telemetry':{}})
    assert err.value.status == 403


def test_new_nodes_have_no_auth_password_identity(central):
    db, _, (admin,user,other) = central
    nid, _ = register(admin,user)
    from clayfarm_control.bridge_client import BridgeBackend
    BridgeBackend(user,node=True).rpc('heartbeat',{'capabilities':[],'telemetry':{}})
    with db.engine.connect() as c:
        assert c.execute(text('select count(*) from auth.users where id=:id'),{'id':nid}).scalar_one()==0
        assert c.execute(text('select count(*) from public.cf_workers where user_id=:id'),{'id':nid}).scalar_one()==1


def submitted(central,tmp_path):
    from clayfarm_control.bridge_client import BridgeBackend
    from clayfarm.cli import submit_job
    from clayfarm.png import encode
    db,bridge,(admin,user,other)=central
    approve(admin,user)
    nid,_=register(admin,other)
    admin.call('PUT',f'/v1/admin/nodes/{nid}/engines',{'engines':['triposr','blender']})
    caller,worker=BridgeBackend(user),BridgeBackend(other,node=True)
    concept=tmp_path/'fixture.png';concept.write_bytes(encode(16,16,bytes([90,150,70,255])*256))
    jid=submit_job(caller,tmp_path/'caller',{'name':'fixture'},[concept],['triposr'],{'agent':'test'})['job_id']
    worker.rpc('heartbeat',{'capabilities':['triposr','blender'],'telemetry':{'on_battery':False}})
    return caller,worker,jid,nid


def complete_fixture(worker,task,tmp_path):
    from clayfarm.executors import mock_glb
    from clayfarm.util import digest
    path=tmp_path/'mesh.glb';path.write_bytes(mock_glb())
    key=f'{worker.farm_id}/{worker.user_id}/{task["id"]}/{task["attempt_id"]}/{digest(path)}-mesh.glb'
    worker.upload(path,key,tmp_path/'upload')
    output={'mock':True,'metrics':{'hard_pass':False},'files':[{'path':key,'sha256':digest(path),'size':path.stat().st_size,'name':'mesh.glb','role':'mesh'}]}
    args={'task_id':task['id'],'attempt_id':task['attempt_id'],'output':output}
    assert worker.rpc('finish',args)['accepted']
    return args


def test_storage_hash_fencing_duplicate_finish_and_result_download(central,tmp_path):
    caller,worker,jid,nid=submitted(central,tmp_path)
    task=worker.rpc('claim',{'slot':'gpu'})
    worker.download(task['payload']['input'],tmp_path/'download.png')
    args=complete_fixture(worker,task,tmp_path)
    assert worker.rpc('finish',args)['already_committed']
    changed=copy.deepcopy(args);changed['output']['mock']=False
    with pytest.raises(CFError) as err:worker.rpc('finish',changed)
    assert err.value.code=='result_conflict'
    caller.download(args['output']['files'][0],tmp_path/'result.glb')
    assert (tmp_path/'result.glb').read_bytes()==(tmp_path/'mesh.glb').read_bytes()
    process=worker.rpc('claim',{'slot':'cpu'})
    assert process['parent_output']==args['output']
    with pytest.raises(CFError):worker.download(task['payload']['input'],tmp_path/'no-longer-leased.png')


def test_cancel_and_lease_expiry_block_upload(central,tmp_path):
    from clayfarm.util import digest
    db,bridge,clients=central
    caller,worker,jid,nid=submitted(central,tmp_path)
    task=worker.rpc('claim',{'slot':'gpu'})
    f=tmp_path/'asset.glb';f.write_bytes(b'fixture only')
    key=f'{worker.farm_id}/{nid}/{task["id"]}/{task["attempt_id"]}/{digest(f)}-asset.glb'
    with db.transaction() as c:
        c.execute(text("UPDATE public.cf_tasks SET lease_until=clock_timestamp()-interval '1 second' WHERE id=:id"),{'id':task['id']})
    with pytest.raises(CFError):worker.upload(f,key,tmp_path/'upload')
    task2=worker.rpc('claim',{'slot':'gpu'})
    assert task2['attempt_id']!=task['attempt_id']
    assert not worker.rpc('renew',{'task_id':task['id'],'attempt_id':task['attempt_id']})['accepted']
    caller.rpc('cancel',{'id':jid})
    key=key.replace(task['attempt_id'],task2['attempt_id'])
    with pytest.raises(CFError):worker.upload(f,key,tmp_path/'upload')


def test_legacy_worker_claims_new_job_from_same_queue(central,tmp_path):
    db,bridge,(admin,user,other)=central
    caller,worker,jid,nid=submitted(central,tmp_path)
    with db.transaction() as c:
        c.execute(text("INSERT INTO public.cf_members VALUES (:id,:farm,'worker','legacy',true)"),{'id':OTHER,'farm':FARM})
        c.execute(text("SELECT set_config('request.jwt.claim.sub',:id,true)"),{'id':OTHER})
        c.execute(text('SET LOCAL ROLE authenticated'))
        c.execute(text("SELECT public.cf_rpc('heartbeat', '{\"capabilities\":[\"triposr\"]}')"))
        task=c.execute(text("SELECT public.cf_rpc('claim','{\"slot\":\"gpu\"}')")).scalar_one()
        assert task['job_id']==jid and task['lease_owner']==OTHER
    assert worker.rpc('claim',{'slot':'gpu'}) is None


def test_new_node_claims_existing_legacy_job(central,tmp_path):
    from clayfarm.spec import validate_spec,plan
    from clayfarm_control.common import canonical,sha
    from clayfarm_control.bridge_client import BridgeBackend
    db,bridge,(admin,user,other)=central
    nid,_=register(admin,user)
    admin.call('PUT',f'/v1/admin/nodes/{nid}/engines',{'engines':['triposr']})
    jid=str(uuid.uuid4());spec=validate_spec({'name':'legacy'})
    key=f'{FARM}/{ADMIN}/{jid}/inputs/'+('a'*64)+'-concept.png'
    blob={'path':key,'sha256':'a'*64,'name':'concept.png','size':100,'role':'input'}
    request={'id':jid,'spec':spec,'tasks':plan(jid,spec,[blob],['triposr']),'caller':{},'parent_job':None}
    request['request_hash']=sha(canonical(request))
    with db.transaction() as c:
        c.execute(text("INSERT INTO storage.objects(bucket_id,name) VALUES ('clayfarm',:key)"),{'key':key})
        c.execute(text("SELECT set_config('request.jwt.claim.sub',:id,true)"),{'id':ADMIN})
        c.execute(text('SET LOCAL ROLE authenticated'))
        c.execute(text("SELECT public.cf_rpc('submit',CAST(:request AS jsonb))"),{'request':json.dumps(request)})
    worker=BridgeBackend(user,node=True)
    worker.rpc('heartbeat',{'capabilities':['triposr'],'telemetry':{}})
    assert worker.rpc('claim',{'slot':'gpu'})['job_id']==jid


def test_rpc_privilege_prevents_identity_spoofing(central):
    import sqlalchemy.exc
    db,bridge,_=central
    with db.engine.connect() as c:
        assert not c.execute(text("SELECT has_table_privilege('clayfarm_gateway','cf_control.farm_binding','UPDATE')")).scalar_one()
    for role in ('authenticated','anon'):
        with pytest.raises(sqlalchemy.exc.DBAPIError):
            with db.transaction() as c:
                c.execute(text('SET LOCAL ROLE '+role))
                c.execute(text("SELECT clayfarm_private.control_member(CAST(:id AS uuid),'human',null)"),{'id':ADMIN})
        with pytest.raises(sqlalchemy.exc.DBAPIError):
            with db.transaction() as c:
                c.execute(text('SET LOCAL ROLE '+role))
                c.execute(text("SELECT clayfarm_private.queue_dispatch(null,'me','{}')"))


def test_engine_removal_takes_effect_before_next_heartbeat(central,tmp_path):
    caller,worker,jid,nid=submitted(central,tmp_path)
    admin=central[2][0]
    admin.call('PUT',f'/v1/admin/nodes/{nid}/engines',{'engines':[]})
    assert worker.rpc('claim',{'slot':'gpu'}) is None


def test_suspended_owner_and_revoked_human_session_fail_sql_recheck(central,tmp_path):
    caller,worker,jid,nid=submitted(central,tmp_path)
    db,bridge,(admin,user,other)=central
    identity=user.call('GET','/v1/me')
    admin.call('PATCH',f'/v1/admin/users/{USER}',{'status':'suspended'})
    with pytest.raises(CFError):bridge.rpc(identity,False,'get',{'id':jid})
    admin.call('PATCH',f'/v1/admin/users/{OTHER}',{'status':'suspended'})
    with pytest.raises(CFError):bridge.rpc({'id':nid},True,'me',{})


def test_gateway_role_can_complete_without_direct_queue_access(central,tmp_path):
    from sqlalchemy import event
    caller,worker,jid,nid=submitted(central,tmp_path)
    db=central[0]
    storage_db=Database(db.engine.url.render_as_string(hide_password=False))
    central[1].storage.db=storage_db
    def role(conn):conn.exec_driver_sql('SET LOCAL ROLE clayfarm_gateway')
    event.listen(db.engine,'begin',role)
    try:
        task=worker.rpc('claim',{'slot':'gpu'})
        complete_fixture(worker,task,tmp_path)
    finally:
        event.remove(db.engine,'begin',role)
        storage_db.engine.dispose()

def test_concurrent_claims_do_not_duplicate_a_task(central,tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    caller,worker,jid,nid=submitted(central,tmp_path)
    bridge=central[1];barrier=threading.Barrier(2)
    def claim():
        barrier.wait(timeout=5)
        return bridge.rpc({'id':nid},True,'claim',{'slot':'gpu'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:claim(),range(2)))
    assert len([x for x in results if x])==1
    assert [x for x in results if x][0]['job_id']==jid


def test_direct_sql_rechecks_revoked_session(central,tmp_path):
    caller,worker,jid,nid=submitted(central,tmp_path)
    user=central[2][1];identity=user.call('GET','/v1/me')
    user.call('POST','/v1/sessions/revoke',{})
    with pytest.raises(CFError) as error:central[1].rpc(identity,False,'get',{'id':jid})
    assert error.value.status==403


def test_signed_storage_query_cannot_be_tampered_or_replayed(central,tmp_path):
    from urllib.parse import urlencode
    from clayfarm_control.device import sign_headers
    caller,worker,jid,nid=submitted(central,tmp_path)
    task=worker.rpc('claim',{'slot':'gpu'})
    path='/v1/node/central/artifacts?'+urlencode({'key':task['payload']['input']['path']})
    client=central[2][2]
    headers=sign_headers(nid,client.vault.get('node-key')['private'],'GET',path,b'')
    assert client.http.get(client.url+path+'-tampered',headers=headers).status_code==401
    assert client.http.get(client.url+path,headers=headers).status_code==200
    assert client.http.get(client.url+path,headers=headers).status_code==401


def test_migration_stops_before_overwriting_changed_dispatcher(central):
    import sqlalchemy.exc
    db=central[0]
    migration=(ROOT/'supabase/migrations/20260912101300_control_queue_bridge.sql').read_text()
    guard=migration.split('begin;',1)[1].split('create table clayfarm_private.worker_identities',1)[0]
    with pytest.raises(sqlalchemy.exc.DBAPIError,match='queue_source_changed'):
        with db.transaction() as c:
            c.exec_driver_sql("CREATE OR REPLACE FUNCTION clayfarm_private.dispatch(p_action text,p_args jsonb) RETURNS jsonb LANGUAGE sql AS $$ select '{\"newer\":true}'::jsonb $$")
            c.exec_driver_sql(guard)

def test_signed_node_real_blender_and_storage_preserve_fixture_provenance(central,tmp_path):
    blender=os.environ.get('CLAYFARM_TEST_BLENDER')
    if not blender:pytest.skip('Set CLAYFARM_TEST_BLENDER to run the real Blender DAG')
    from clayfarm.cli import selftest_blender,collect_result
    from clayfarm_control.central_worker import CentralWorker
    caller,backend,jid,nid=submitted(central,tmp_path)
    task=backend.rpc('claim',{'slot':'gpu'})
    complete_fixture(backend,task,tmp_path) # Explicitly synthetic reconstruction input.
    cfg={'home':str(tmp_path/'blender-node'),'blender':blender,'cpu_threads':2,'allow_battery':True,'cpu_min_ram_mb':1000,'min_disk_free_mb':0}
    selftest_blender(cfg) # Actual process/export and all six camera renders.
    worker=CentralWorker(cfg,backend)
    for _ in range(7):
        worker.refresh();assert worker.step('cpu');worker.flush()
    result=collect_result(caller,jid,tmp_path/'review',artifacts=True)
    assert result['all_terminal'] and result['ready_candidates']==[]
    assert len(result['diagnostic_candidates'])==1
    assert len(result['diagnostic_candidates'][0]['previews'])==6
    assert Path(result['contact_sheet']).is_file()
    assert result['diagnostic_candidates'][0]['mock'] is True
    assert all(t['output'].get('mock') for t in caller.rpc('get',{'id':jid})['tasks'])
    with pytest.raises(CFError):caller.rpc('approve',{'id':jid,'task_id':result['diagnostic_candidates'][0]['process_task']})
    if os.environ.get('CLAYFARM_TEST_EVIDENCE'):
        import shutil
        dest=Path(os.environ['CLAYFARM_TEST_EVIDENCE']);dest.mkdir(parents=True,exist_ok=True)
        shutil.copytree(tmp_path/'review',dest/'blender-review',dirs_exist_ok=True)

def test_mock_output_cannot_be_laundered_through_revision(central,tmp_path):
    from clayfarm.cli import submit_job
    caller,worker,jid,nid=submitted(central,tmp_path)
    task=worker.rpc('claim',{'slot':'gpu'})
    output=complete_fixture(worker,task,tmp_path)['output']
    with pytest.raises(CFError):
        submit_job(caller,tmp_path/'caller',{'name':'bad_revision'},[],['triposr'],{'agent':'test'},parent=jid,raw_mesh=output['files'][0])

def test_original_sql_queue_contract_after_bridge_migration(central):
    import subprocess
    host=os.environ.get('CLAYFARM_TEST_DOCKER_DB_HOST')
    if not host:pytest.skip('Run through scripts/test_central.py --real-storage for the original psql contract')
    db=central[0]
    with db.transaction() as c:
        c.execute(text("CREATE OR REPLACE FUNCTION public.cf_test_assert(value boolean,message text) RETURNS void LANGUAGE plpgsql AS $$ BEGIN IF value IS DISTINCT FROM true THEN RAISE EXCEPTION 'TEST FAILED: %',message; END IF; END $$;"))
    result=subprocess.run(['docker','exec','-i',host,'psql','-X','-v','ON_ERROR_STOP=1','-U','postgres','-d',db.engine.url.database],input=(ROOT/'tests_legacy/sql/01_smoke.sql').read_text(),text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert 'PostgreSQL stub smoke tests passed' in result.stdout
