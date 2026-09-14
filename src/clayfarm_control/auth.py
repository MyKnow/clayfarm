from __future__ import annotations
import base64, json, time
import httpx
from .common import CFError, secure_url

_SAFE_AUTH_ERRORS = {
    'mfa_factor_name_conflict': 'An authenticator with this name already exists; rerun MFA enrollment to resume it',
    'mfa_max_enrolled_factors': 'The authenticator limit has been reached; use an existing verified authenticator',
    'mfa_verification_failed': 'Authenticator code was not accepted; use the current code from the matching authenticator',
    'mfa_challenge_expired': 'Authenticator challenge expired; retry MFA verification with a current code',
    'mfa_ip_address_mismatch': 'Complete authenticator setup using the same network connection',
}

class SupabaseAuth:
    def __init__(self,url,key,client=None):
        self.url=secure_url(url); self.key=key
        if not key or key.startswith("sb_secret_"): raise CFError("invalid_public_key","A publishable key, not an admin secret, is required")
        if key.count(".")==2:
            try:
                claims=json.loads(base64.urlsafe_b64decode(key.split(".")[1]+"===") )
                if claims.get("role")=="service_role": raise CFError("privileged_key_rejected","Do not configure service_role in a client")
            except (ValueError,TypeError): raise CFError("invalid_public_key","Malformed public key")
        self.client=client or httpx.Client(timeout=20,follow_redirects=False)
    def call(self,method,path,body=None,token=None):
        headers={"apikey":self.key}
        if token: headers["Authorization"]="Bearer "+token
        try: r=self.client.request(method,self.url+"/auth/v1"+path,json=body,headers=headers)
        except httpx.HTTPError as e: raise CFError("auth_unreachable","Authentication service unreachable",503) from e
        if r.status_code>=400:
            try: details=r.json()
            except ValueError: details={}
            code=details.get('error_code') if isinstance(details,dict) else None
            if isinstance(code,str) and code in _SAFE_AUTH_ERRORS:
                raise CFError(code,_SAFE_AUTH_ERRORS[code],r.status_code)
            raise CFError("auth_rejected",f"Authentication request rejected ({r.status_code})",401 if r.status_code in (400,401,403) else r.status_code if r.status_code in (422,429) else 503)
        return r.json() if r.content else {}
    def otp(self,email,signup=False):
        return self.call("POST","/otp",{"email":email,"create_user":signup})
    def verify(self,email,code): return self.call("POST","/verify",{"email":email,"token":code,"type":"email"})
    def refresh(self,refresh_token): return self.call("POST","/token?grant_type=refresh_token",{"refresh_token":refresh_token})
    def user(self,access): return self.call("GET","/user",token=access)
    def logout(self,access): return self.call("POST","/logout?scope=local",token=access)
    def factor_enroll(self,access): return self.call("POST","/factors",{"factor_type":"totp","friendly_name":"ClayFarm CLI"},access)
    def factor_verify(self,access,factor,code):
        import uuid
        try: uuid.UUID(factor)
        except ValueError: raise CFError("invalid_factor","Invalid factor ID")
        c=self.call("POST",f"/factors/{factor}/challenge",{},access)
        return self.call("POST",f"/factors/{factor}/verify",{"challenge_id":c["id"],"code":code},access)

class SupabaseVerifier:
    def __init__(self,auth): self.auth=auth
    def __call__(self,token):
        # Never authorize from a locally decoded unverified JWT. GoTrue validates first.
        user=self.auth.user(token)
        try: claims=json.loads(base64.urlsafe_b64decode(token.split(".")[1]+"==="))
        except (IndexError,ValueError) as e: raise CFError("invalid_session","Invalid user token",401) from e
        if not user.get("id") or claims.get("sub")!=user["id"] or claims.get("exp",0)<=time.time() or user.get("is_anonymous"):
            raise CFError("invalid_session","Verified non-anonymous session required",401)
        if not user.get("email_confirmed_at"): raise CFError("email_unverified","Email verification required",403)
        return {"id":user["id"],"email":user["email"],"aal":claims.get("aal","aal1"),"session_id":claims.get("session_id"),"expires_at":claims["exp"]}
