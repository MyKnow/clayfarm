from __future__ import annotations
import base64, time, secrets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption
from .common import CFError, sha

def new_key():
    key=Ed25519PrivateKey.generate()
    return {"private":base64.b64encode(key.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption())).decode(),"public":base64.b64encode(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)).decode()}

def public_key_valid(value):
    try:
        raw=base64.b64decode(value,validate=True)
        if len(raw)!=32: raise ValueError()
        Ed25519PublicKey.from_public_bytes(raw)
    except Exception as e: raise CFError("invalid_device_key","An Ed25519 public key is required") from e
    return value

def signing_bytes(method,path,body,timestamp,nonce):
    return f"CFNODE1\n{method.upper()}\n{path}\n{sha(body)}\n{timestamp}\n{nonce}".encode()

def sign_headers(node_id,private_key,method,path,body=b"",timestamp=None,nonce=None):
    stamp=str(int(timestamp or time.time())); nonce=nonce or secrets.token_hex(16)
    key=Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key))
    signature=base64.b64encode(key.sign(signing_bytes(method,path,body,stamp,nonce))).decode()
    return {"X-CF-Node":node_id,"X-CF-Time":stamp,"X-CF-Nonce":nonce,"X-CF-Signature":signature}

def verify_headers(public_key,method,path,body,headers,clock=None):
    import re
    stamp=headers.get("x-cf-time",""); nonce=headers.get("x-cf-nonce","")
    try:
        if not re.fullmatch(r"[0-9a-f]{32}",nonce) or abs((clock or time.time())-int(stamp))>180: raise ValueError()
        key=Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key,validate=True))
        key.verify(base64.b64decode(headers.get("x-cf-signature",""),validate=True),signing_bytes(method,path,body,stamp,nonce))
    except Exception as e: raise CFError("invalid_device_proof","Invalid, expired, or mismatched device proof",401) from e
    return nonce
