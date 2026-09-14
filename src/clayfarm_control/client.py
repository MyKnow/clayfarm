from __future__ import annotations
import time
from pathlib import Path
import httpx
from .common import CFError, secure_url, canonical, read_json, atomic_json
from .vault import Vault
from .device import sign_headers
from .auth import SupabaseAuth

class Client:
    def __init__(self,home,*,transport=None,vault=None):
        self.home=Path(home);self.config=read_json(self.home/"control.json",{})
        self.url=secure_url(self.config.get("server",""),loopback=True)
        self.http=httpx.Client(transport=transport,timeout=30,follow_redirects=False)
        self.vault=vault or Vault(str(self.home.resolve())+self.url)
    def auth(self):
        cfg=self.config.get("auth")
        if not cfg:
            cfg=self.call("GET","/v1/config",anonymous=True)
            self.config["auth"]=cfg;atomic_json(self.home/"control.json",self.config)
        return SupabaseAuth(cfg["supabase_url"],cfg["publishable_key"])
    def session(self):
        session=self.vault.get("human-session")
        if not session: raise CFError("login_required","Run clayfarm auth login",401)
        if session.get("expires_at",0)<time.time()+60:
            session=self.auth().refresh(session["refresh_token"])
            session["expires_at"]=session.get("expires_at",time.time()+session.get("expires_in",3600))
            self.vault.put("human-session",session)
        return session
    def call(self,method,path,payload=None,*,node=False,anonymous=False,raw=None,download=False):
        data=raw if raw is not None else canonical(payload) if payload is not None else b""
        headers={"Content-Type":"application/octet-stream" if raw is not None else "application/json"}
        if node:
            key=self.vault.get("node-key")
            if not key or not self.config.get("node_id"): raise CFError("node_not_registered","Register this device first")
            headers.update(sign_headers(self.config["node_id"],key["private"],method,path,data))
        elif not anonymous: headers["Authorization"]="Bearer "+self.session()["access_token"]
        try: reply=self.http.request(method,self.url+path,content=data,headers=headers)
        except httpx.HTTPError as e: raise CFError("offline","Server unavailable; local state retained",503) from e
        if reply.status_code>=400:
            try: error=reply.json().get("error",{})
            except ValueError: error={}
            raise CFError(error.get("code","api_error"),error.get("message",f"API request failed ({reply.status_code})"),reply.status_code)
        return reply.content if download else reply.json() if reply.content else {}
