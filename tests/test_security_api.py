import time,json,concurrent.futures
import pytest
from clayfarm_control.common import CFError,canonical
from clayfarm_control.device import new_key,sign_headers
from clayfarm_control.demo import ADMIN,USER,fixture_client
from clayfarm_control.inventory import probe

def request_access(c,key="request-access-1"):
    return c.call("POST","/v1/requests",{"kind":"access","payload":{"requested_grant":"creator-basic"},"idempotency_key":key})
def register(admin,user):
    key=new_key();user.vault.put("node-key",key)
    req=user.call("POST","/v1/requests",{"kind":"node","payload":{"name":"fixture","public_key":key["public"],"inventory":probe()},"idempotency_key":"node-req-001"})
    user.config["node_id"]=req["id"]
    admin.call("POST",f'/v1/admin/requests/{req["id"]}/decision',{"approve":True})
    return req["id"],key

def test_no_unauthenticated_requests(system):
    _,app,_,_,_=system
    from fastapi.testclient import TestClient
    assert TestClient(app).get("/v1/admin/users").status_code==401

def test_member_cannot_self_approve(system):
    _,_,_,user,_=system;r=request_access(user)
    with pytest.raises(CFError) as e:user.call("POST",f'/v1/admin/requests/{r["id"]}/decision',{"approve":True})
    assert e.value.code=="admin_required"

def test_admin_requires_mfa(system,tmp_path):
    _,app,admin,user,_=system;r=request_access(user)
    weak=fixture_client(tmp_path/"weak",app,"fixture-admin-aal1")
    with pytest.raises(CFError) as e:weak.call("POST",f'/v1/admin/requests/{r["id"]}/decision',{"approve":True})
    assert e.value.code=="mfa_required";weak.http.close()

def test_signup_not_generation_permission(system):
    *_,user,other=system
    with pytest.raises(CFError) as e:user.call("POST","/v1/jobs",{"profile_id":"procedural-sfx","spec":{},"idempotency_key":"job-00001"})
    assert e.value.code=="approval_required"

def test_duplicate_join_and_approval(system):
    _,_,admin,user,_=system;r=request_access(user);again=request_access(user)
    assert r["id"]==again["id"]
    path=f'/v1/admin/requests/{r["id"]}/decision'
    admin.call("POST",path,{"approve":True})
    assert admin.call("POST",path,{"approve":True})["replayed"]
    assert user.call("GET","/v1/me")["grants"]==["creator-basic"]

def test_idempotency_conflict(system):
    _,_,_,user,_=system;request_access(user)
    with pytest.raises(CFError) as e:user.call("POST","/v1/requests",{"kind":"access","payload":{"requested_grant":"experimental"},"idempotency_key":"request-access-1"})
    assert e.value.code=="idempotency_conflict"

def test_request_notifications_private(system):
    _,_,admin,user,other=system;request_access(user)
    assert admin.call("GET","/v1/notifications")
    assert other.call("GET","/v1/notifications")==[]

def test_node_approval_not_readiness(system):
    _,_,admin,user,_=system;nid,key=register(admin,user)
    state=user.call("GET","/v1/node/status",node=True)
    assert state["status"]=="active" and state["desired"]["profiles"]==[]

def test_node_pending_cannot_resume_around_approval(system):
    _,_,admin,user,_=system;key=new_key()
    req=user.call("POST","/v1/requests",{"kind":"node","payload":{"name":"pending","public_key":key["public"],"inventory":{}},"idempotency_key":"pending-node"})
    with pytest.raises(CFError) as e:user.call("PATCH",f'/v1/nodes/{req["id"]}/status',{"status":"active"})
    assert e.value.code=="invalid_transition"

def test_device_signatures_replay_tamper(system):
    _,app,admin,user,_=system;nid,key=register(admin,user)
    path="/v1/node/status";headers=sign_headers(nid,key["private"],"GET",path)
    assert user.http.get(path,headers=headers).status_code==200
    assert user.http.get(path,headers=headers).status_code==401
    bad=sign_headers(nid,key["private"],"GET","/wrong/path")
    assert user.http.get(path,headers=bad).status_code==401

def test_revoked_node_rejected_immediately(system):
    _,_,admin,user,_=system;nid,_=register(admin,user)
    user.call("PATCH",f"/v1/nodes/{nid}/status",{"status":"revoked"})
    with pytest.raises(CFError) as e:user.call("GET","/v1/node/status",node=True)
    assert e.value.code=="device_revoked"

def test_node_cannot_access_user_admin_api(system):
    _,_,admin,user,_=system;register(admin,user)
    with pytest.raises(CFError) as e:user.call("GET","/v1/admin/users",node=True)
    assert e.value.code=="login_required"

def test_suspended_owner_blocks_node(system):
    _,_,admin,user,_=system;register(admin,user)
    admin.call("PATCH",f"/v1/admin/users/{USER}",{"status":"suspended"})
    with pytest.raises(CFError) as e:user.call("GET","/v1/node/status",node=True)
    assert e.value.code=="owner_suspended"

def test_desired_revision_cas(system):
    _,_,admin,user,_=system;nid,_=register(admin,user)
    path=f"/v1/admin/nodes/{nid}/desired";body={"profiles":["procedural-sfx"],"expected_revision":0}
    assert admin.call("PUT",path,body)["revision"]==1
    with pytest.raises(CFError) as e:admin.call("PUT",path,body)
    assert e.value.code=="revision_conflict"

def test_session_logout_revoked_at_control_plane(system):
    _,_,admin,user,_=system;user.call("POST","/v1/sessions/revoke",{})
    with pytest.raises(CFError) as e:user.call("GET","/v1/me")
    assert e.value.code=="session_revoked"
