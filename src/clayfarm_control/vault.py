"""OS credential vault. No plaintext fallback, including on headless machines."""
from __future__ import annotations
import json, uuid
from .common import CFError, sha

_UNLOCK_HINT = "Unlock your OS credential store in your desktop session, then retry"

class Vault:
    def __init__(self, namespace: str): self.service="clayfarm:"+sha(namespace.encode())[:24]
    def _backend(self):
        try:
            import keyring
            backend=keyring.get_keyring()
            module=type(backend).__module__.lower()
            if not any(x in module for x in ("macos","windows","secretservice","kwallet")):
                raise CFError("secure_vault_unavailable","A native OS keychain is required; plaintext/chained/unknown backends are refused")
            return keyring
        except ImportError as e: raise CFError("secure_vault_unavailable","Install keyring; no secret was stored") from e
    def get(self,name):
        try:
            value=self._backend().get_password(self.service,name)
            return json.loads(value) if value else None
        except CFError: raise
        except Exception as e: raise CFError("vault_locked",_UNLOCK_HINT) from e
    def put(self,name,value):
        try: self._backend().set_password(self.service,name,json.dumps(value))
        except CFError: raise
        except Exception as e: raise CFError("vault_locked",_UNLOCK_HINT) from e
    def delete(self,name):
        try:
            backend=self._backend()
            if backend.get_password(self.service,name) is not None: backend.delete_password(self.service,name)
        except CFError: raise
        except Exception as e: raise CFError("vault_locked",_UNLOCK_HINT) from e

    def check_writable(self):
        """Check storage before consuming an OTP; only touch a disposable non-secret item."""
        backend = self._backend()
        name = "store-check-" + uuid.uuid4().hex
        marker = uuid.uuid4().hex
        try:
            backend.set_password(self.service, name, marker)
            try:
                if backend.get_password(self.service, name) != marker:
                    raise CFError("vault_locked", _UNLOCK_HINT)
            finally:
                backend.delete_password(self.service, name)
        except CFError:
            raise
        except Exception as e:
            raise CFError("vault_locked", _UNLOCK_HINT) from e

class MemoryVault:
    """Explicit in-process test fixture; never selected by the CLI."""
    def __init__(self): self.data={}
    def get(self,n): return self.data.get(n)
    def put(self,n,v): self.data[n]=v
    def delete(self,n): self.data.pop(n,None)
    def check_writable(self): pass
