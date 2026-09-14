import base64,json,sys,time,threading,subprocess,os
from pathlib import Path
import httpx,pytest
from sqlalchemy import select
from clayfarm_control.auth import SupabaseAuth,SupabaseVerifier
from clayfarm_control.common import CFError,atomic_json
from clayfarm_control.db import jobs
from clayfarm_control.registry import load_registry,get_profile,profile_digest
from clayfarm_control.inventory import probe
from clayfarm_control.demo import USER
from clayfarm_control import __version__
from test_security_api import request_access,register


def ready_node(admin,user):
    nid,key=register(admin,user)
    admin.call('PUT',f'/v1/admin/nodes/{nid}/desired',{'profiles':['procedural-sfx'],'expected_revision':0})
    p=get_profile(load_registry(),'procedural-sfx')
    # Synthetic capability used only to isolate queue tests; not a GPU/quality claim.
    cap={'profile_id':p['id'],'status':'verified','backend':'cpu','profile_digest':profile_digest(load_registry(),p),'peak_host_bytes':1024,'peak_device_bytes':0,'artifact_sha256':'a'*64,'adapter_digest':'b'*64,'tested_at':time.time(),'release_id':f'bundled-{__version__}'}
    user.call('POST','/v1/node/heartbeat',{'inventory':probe(),'capabilities':[cap]},node=True)
    return nid


def submit(admin,user,key='job-request-0001'):
    r=request_access(user);admin.call('POST',f'/v1/admin/requests/{r["id"]}/decision',{'approve':True})
    return user.call('POST','/v1/jobs',{'profile_id':'procedural-sfx','spec':{'effect':'beep'},'idempotency_key':key})


def test_job_idempotency(system):
    _,_,admin,user,_=system
    first=submit(admin,user);second=submit(admin,user)
    assert first['id']==second['id']


def test_job_read_isolation(system):
    _,_,admin,user,other=system;job=submit(admin,user)
    with pytest.raises(CFError) as e:other.call('GET',f'/v1/jobs/{job["id"]}')
    assert e.value.status==404


def test_unimplemented_model_rejected(system):
    _,_,admin,user,_=system;submit(admin,user)
    with pytest.raises(CFError) as e:user.call('POST','/v1/jobs',{'profile_id':'hymotion-cuda','spec':{},'idempotency_key':'new-motion-job'})
    assert e.value.code=='adapter_not_implemented'


def test_expired_attempt_cannot_renew(system):
    db,_,admin,user,_=system;ready_node(admin,user);submit(admin,user)
    claim=user.call('POST','/v1/node/jobs/claim',{},node=True)['job']
    with db.transaction() as c:c.execute(jobs.update().where(jobs.c.id==claim['id']).values(lease_until=time.time()-10))
    with pytest.raises(CFError) as e:user.call('POST',f'/v1/node/jobs/{claim["id"]}/renew',{'attempt_id':claim['attempt_id']},node=True)
    assert e.value.code=='stale_attempt'


def test_retry_fencing_after_node_loss(system):
    db,_,admin,user,other=system;ready_node(admin,user);submit(admin,user)
    first=user.call('POST','/v1/node/jobs/claim',{},node=True)['job']
    with db.transaction() as c:c.execute(jobs.update().where(jobs.c.id==first['id']).values(lease_until=time.time()-10))
    ready_node(admin,other)
    second=other.call('POST','/v1/node/jobs/claim',{},node=True)['job']
    assert first['id']==second['id'] and first['attempt_id']!=second['attempt_id']
    with pytest.raises(CFError) as e:user.call('POST',f'/v1/node/jobs/{first["id"]}/finish',{'attempt_id':first['attempt_id'],'error':{'code':'late'}},node=True)
    assert e.value.code=='stale_attempt'


def test_only_one_compute_job_per_node(system):
    _,_,admin,user,_=system;ready_node(admin,user);submit(admin,user);submit(admin,user,'another-job-0002')
    assert user.call('POST','/v1/node/jobs/claim',{},node=True)['job']
    assert user.call('POST','/v1/node/jobs/claim',{},node=True)['reason']=='compute_slot_occupied'


def test_cancellation_blocks_running_commit(system):
    _,_,admin,user,_=system;ready_node(admin,user);job=submit(admin,user)
    claim=user.call('POST','/v1/node/jobs/claim',{},node=True)['job']
    user.call('POST',f'/v1/jobs/{job["id"]}/cancel',{})
    with pytest.raises(CFError) as e:user.call('POST',f'/v1/node/jobs/{job["id"]}/finish',{'attempt_id':claim['attempt_id'],'error':{'code':'late'}},node=True)
    assert e.value.code=='stale_attempt'


def test_forged_capability_not_accepted(system):
    _,_,admin,user,_=system;ready_node(admin,user)
    result=user.call('POST','/v1/node/heartbeat',{'inventory':probe(),'capabilities':[{'profile_id':'procedural-sfx','status':'verified','profile_digest':'fake','backend':'cpu'}]},node=True)
    assert result['accepted_capabilities']==0


def test_join_is_concurrently_idempotent(system):
    import concurrent.futures
    _,_,_,user,_=system
    user.call('GET','/v1/me')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        answers=list(pool.map(lambda _:request_access(user,'concurrent-join-01'),range(4)))
    assert len({x['id'] for x in answers})==1


def test_otp_signup_login_contracts():
    calls=[]
    def handler(r):calls.append((r.url.path,json.loads(r.content)));return httpx.Response(200,json={})
    auth=SupabaseAuth('https://example.supabase.co','sb_publishable_fixture',httpx.Client(transport=httpx.MockTransport(handler)))
    auth.otp('user@example.test',True);auth.otp('user@example.test',False);auth.verify('user@example.test','123456')
    assert calls[0][1]['create_user'] is True
    assert calls[1][1]['create_user'] is False
    assert calls[2][1]['type']=='email'


def test_jwt_not_used_if_auth_service_rejects():
    class RejectAuth:
        def user(self,token):raise CFError('auth_rejected','Rejected',401)
    with pytest.raises(CFError):SupabaseVerifier(RejectAuth())('forged.admin.token')


def test_service_key_not_accepted_in_client():
    with pytest.raises(CFError):SupabaseAuth('https://example.supabase.co','sb_secret_fixture')


def test_plaintext_vault_backend_refused(monkeypatch):
    from types import SimpleNamespace
    from clayfarm_control.vault import Vault
    Fake=type('PlaintextKeyring',(),{});Fake.__module__='keyrings.alt.file'
    monkeypatch.setitem(sys.modules,'keyring',SimpleNamespace(get_keyring=lambda:Fake()))
    with pytest.raises(CFError) as e:Vault('test').get('human-session')
    assert e.value.code=='secure_vault_unavailable'


def test_runtime_does_not_inherit_secrets(tmp_path,monkeypatch):
    from clayfarm_control.process import run_isolated
    monkeypatch.setenv('CLAYFARM_TEST_SECRET','not-a-real-secret')
    output=tmp_path/'env.json'
    env={k:v for k,v in os.environ.items() if k in ('PATH','SYSTEMROOT','WINDIR')}
    script='import os,json,sys; open(sys.argv[1],"w").write(json.dumps(os.getenv("CLAYFARM_TEST_SECRET")))'
    run_isolated([sys.executable,'-c',script,str(output)],tmp_path,tmp_path/'log.txt',10,env)
    assert json.loads(output.read_text()) is None


def test_runtime_timeout(tmp_path):
    from clayfarm_control.process import run_isolated
    env={k:v for k,v in os.environ.items() if k in ('PATH','SYSTEMROOT','WINDIR')}
    with pytest.raises(CFError) as e:run_isolated([sys.executable,'-c','import time;time.sleep(30)'],tmp_path,tmp_path/'log.txt',.1,env)
    assert e.value.code=='runtime_timeout'

def test_runtime_stops_under_host_memory_pressure(tmp_path):
    import sys,os
    from clayfarm_control.process import run_isolated
    with pytest.raises(CFError) as error:
        run_isolated([sys.executable,'-c','import time; time.sleep(30)'],tmp_path,tmp_path/'pressure.log',10,dict(os.environ),memory_reserve_bytes=2**60)
    assert error.value.code=='memory_pressure'
