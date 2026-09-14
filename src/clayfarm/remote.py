"""Supabase Auth / RPC / resumable Storage using Python's standard library."""
from __future__ import annotations
import base64
import hashlib
import http.client
import json
import mimetypes
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from .util import FarmError, OfflineError, digest, read_json, safe_key, write_json

CHUNK = 6 * 1024 * 1024  # Supabase TUS documented chunk size.


class ApiError(FarmError):
    def __init__(self, status, code="api_error"):
        self.status=status
        self.code=str(code)[:100]
        super().__init__(f"HTTP {status}: {self.code}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None  # Never forward bearer credentials to an arbitrary redirected host.


def base_url(value: str) -> str:
    p=urllib.parse.urlparse(value)
    if p.scheme!="https" or not p.netloc or p.username or p.password or p.query or p.fragment or p.path not in ("","/"):
        raise FarmError("Supabase URL must be an HTTPS origin without path, query, or credentials")
    return value.rstrip("/")


def request(url, method="GET", data=None, headers=None, *, stream=False):
    headers=dict(headers or {})
    if isinstance(data,(dict,list)):
        data=json.dumps(data,allow_nan=False).encode(); headers["Content-Type"]="application/json"
    req=urllib.request.Request(url,data=data,headers=headers,method=method)
    try:
        response=urllib.request.build_opener(NoRedirect).open(req,timeout=30)
        if stream: return response
        with response:
            body=response.read(2*1024*1024+1)
            if len(body)>2*1024*1024: raise FarmError("API response too large")
            return response.status,dict(response.headers),body
    except urllib.error.HTTPError as e:
        body=e.read(8192)
        try:
            detail=json.loads(body)
            code=detail.get("code") or detail.get("error_code") or detail.get("error") or detail.get("message") or "api_error"
        except (ValueError,AttributeError): code="api_error"
        if e.code in (408,429) or e.code>=500:
            raise OfflineError(f"Temporary service failure (HTTP {e.code}); retry retained locally") from None
        raise ApiError(e.code,code) from None
    except (urllib.error.URLError,TimeoutError,socket.timeout,ConnectionError,OSError,http.client.HTTPException) as e:
        if isinstance(e,FarmError): raise
        raise OfflineError("Connection unavailable; no task/result has been discarded") from None


class SupabaseBackend:
    def __init__(self, cfg: dict):
        self.cfg=cfg; self.url=base_url(cfg["url"]); self.key=cfg["publishable_key"]
        if self.key.startswith("sb_secret_"): raise FarmError("Worker must not use a secret/service_role key")
        if self.key.count(".")==2:
            try:
                claims=json.loads(base64.urlsafe_b64decode(self.key.split(".")[1]+"===") )
                if claims.get("role")=="service_role": raise FarmError("service_role must stay on the admin machine")
            except (ValueError,UnicodeDecodeError): pass
        self.user_id=cfg["user_id"]; self.farm_id=cfg["farm_id"]
        self.session={}; self.lock=threading.RLock()
        # Custom domain deployments can provide their direct storage HTTPS origin.
        self.storage=base_url(cfg.get("storage_url") or self.url)
        self.max_artifact=int(cfg.get("max_artifact_bytes",50*1024*1024))

    def _token(self):
        with self.lock:
            if self.session.get("expires_at",0)>time.time()+90: return self.session["access_token"]
            headers={"apikey":self.key}
            refresh=self.session.get("refresh_token")
            if refresh:
                try:
                    _,_,body=request(self.url+"/auth/v1/token?grant_type=refresh_token","POST",{"refresh_token":refresh},headers)
                    self.session=json.loads(body)
                    self.session.setdefault("expires_at",time.time()+self.session.get("expires_in",3600))
                    return self.session["access_token"]
                except ApiError:
                    self.session={}
            _,_,body=request(self.url+"/auth/v1/token?grant_type=password","POST",{"email":self.cfg["email"],"password":self.cfg["password"]},headers)
            self.session=json.loads(body)
            if self.session.get("user",{}).get("id")!=self.user_id: raise FarmError("Enrollment identity mismatch")
            self.session.setdefault("expires_at",time.time()+self.session.get("expires_in",3600))
            return self.session["access_token"]

    def http(self,url,method="GET",data=None,headers=None,**kwargs):
        head={"apikey":self.key,"Authorization":"Bearer "+self._token(),**(headers or {})}
        try:
            return request(url,method,data,head,**kwargs)
        except ApiError as e:
            if e.status!=401: raise
            with self.lock: self.session["expires_at"]=0
            head["Authorization"]="Bearer "+self._token()
            return request(url,method,data,head,**kwargs)

    def rpc(self,action,args=None):
        _,_,body=self.http(self.url+"/rest/v1/rpc/cf_rpc","POST",{"p_action":action,"p_args":args or {}})
        return json.loads(body)

    def _object_url(self,key):
        return self.storage+"/storage/v1/object/authenticated/clayfarm/"+urllib.parse.quote(safe_key(key),safe="/")

    def _exists(self,key,size):
        try:
            _,headers,_=self.http(self._object_url(key),"HEAD")
            return int({k.lower():v for k,v in headers.items()}.get("content-length",-1))==size
        except ApiError as e:
            if e.status not in (400,404): raise
            return False

    def upload(self,path: Path,key: str,state_dir: Path):
        safe_key(key); size=path.stat().st_size
        if not 0<size<=self.max_artifact: raise FarmError("Artifact exceeds configured upload limit or is empty")
        if self._exists(key,size): return
        state_dir.mkdir(parents=True,exist_ok=True)
        state=state_dir/(hashlib.sha256(key.encode()).hexdigest()+".tus.json")
        saved=read_json(state,{})
        sha=digest(path)
        if saved.get("sha256")!=sha: saved={}
        upload_url=saved.get("url")
        endpoint=self.storage+"/storage/v1/upload/resumable"
        if upload_url and not upload_url.startswith(endpoint+"/"):
            raise FarmError("Untrusted persisted TUS endpoint rejected")
        offset=0
        if upload_url:
            try:
                _,headers,_=self.http(upload_url,"HEAD",headers={"Tus-Resumable":"1.0.0"})
                offset=int({k.lower():v for k,v in headers.items()}["upload-offset"])
            except ApiError as e:
                if e.status not in (400,404,410): raise
                upload_url=None
        if not upload_url:
            mime=mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            meta={"bucketName":"clayfarm","objectName":key,"contentType":mime,"cacheControl":"3600"}
            metadata=",".join(k+" "+base64.b64encode(v.encode()).decode() for k,v in meta.items())
            _,headers,_=self.http(endpoint,"POST",b"",{"Tus-Resumable":"1.0.0","Upload-Length":str(size),"Upload-Metadata":metadata})
            location={k.lower():v for k,v in headers.items()}.get("location","")
            upload_url=urllib.parse.urljoin(endpoint,location)
            if not upload_url.startswith(endpoint+"/"): raise FarmError("Unexpected TUS upload location")
            write_json(state,{"url":upload_url,"sha256":sha,"size":size},secret=True)
        if not 0<=offset<=size: raise FarmError("Invalid TUS offset")
        with path.open("rb") as f:
            f.seek(offset)
            while offset<size:
                block=f.read(min(CHUNK,size-offset))
                if not block: raise FarmError("Input changed while uploading")
                _,headers,_=self.http(upload_url,"PATCH",block,{"Tus-Resumable":"1.0.0","Upload-Offset":str(offset),"Content-Type":"application/offset+octet-stream"})
                confirmed=int({k.lower():v for k,v in headers.items()}.get("upload-offset",-1))
                if confirmed!=offset+len(block): raise FarmError("TUS server returned unexpected offset")
                offset=confirmed
        # Preserve the completed fingerprint to survive upload-complete / DB-commit gaps.

    def download(self,blob: dict,dest: Path):
        size=blob.get("size")
        if type(size) is not int or not 0<size<=self.max_artifact: raise FarmError("Invalid/oversized artifact descriptor")
        if dest.is_file() and dest.stat().st_size==size and digest(dest)==blob["sha256"]: return
        part=dest.with_suffix(dest.suffix+".part"); dest.parent.mkdir(parents=True,exist_ok=True)
        offset=part.stat().st_size if part.exists() else 0
        if offset>size: part.unlink(); offset=0
        if offset<size:
            response=self.http(self._object_url(blob["path"]),headers={"Range":f"bytes={offset}-"} if offset else {},stream=True)
            with response:
                if response.status==206:
                    if not response.headers.get("Content-Range","").startswith(f"bytes {offset}-"): raise FarmError("Download range mismatch")
                elif response.status==200: offset=0
                else: raise FarmError("Unexpected download response")
                try:
                    with part.open("ab" if offset else "wb") as f:
                        total=offset
                        while True:
                            block=response.read(1024*1024)
                            if not block: break
                            total+=len(block)
                            if total>size: raise FarmError("Download exceeds declared length")
                            f.write(block)
                        f.flush()
                        import os
                        os.fsync(f.fileno())
                except (OSError,TimeoutError,ConnectionError,http.client.HTTPException): raise OfflineError("Download interrupted; partial bytes retained") from None
        if part.stat().st_size!=size: raise OfflineError("Incomplete download; partial bytes retained")
        if digest(part)!=blob["sha256"]:
            part.unlink(); raise FarmError("Artifact SHA-256 mismatch; corrupted content rejected")
        part.replace(dest)
