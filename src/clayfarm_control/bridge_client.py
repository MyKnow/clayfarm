"""Keep the proven 3D caller/worker/journal contracts, replace only transport."""
from pathlib import Path
from urllib.parse import urlencode

from clayfarm.util import FarmError, OfflineError, atomic_bytes, digest
from .common import CFError, sha
from .bridge import MAX_ARTIFACT


class BridgeError(CFError, FarmError):
    """Safe transport error understood by both CLI generations."""


class BridgeBackend:
    def __init__(self, client, *, node=False):
        self.client, self.node = client, node
        self.prefix = '/v1/node/central' if node else '/v1/central'
        member=self.rpc('me')
        self.farm_id, self.user_id = member['farm_id'], member['user_id']

    def _call(self, method, path, payload=None, **kwargs):
        try:
            return self.client.call(method,path,payload,node=self.node,**kwargs)
        except CFError as exc:
            if exc.status==503:
                raise OfflineError('Central transport unavailable; journal and outbox retained') from None
            raise BridgeError(exc.code,exc.message,exc.status) from None

    def rpc(self, action, args=None):
        return self._call('POST',self.prefix+'/rpc',{'action':action,'args':args or {}})

    def upload(self, path, key, state_dir):
        path=Path(path)
        if not 0<path.stat().st_size<=MAX_ARTIFACT:
            raise CFError('artifact_size','Artifact exceeds the 50 MiB central limit',413)
        data=path.read_bytes()
        result=self._call('PUT',self.prefix+'/artifacts?'+urlencode({'key':key}),raw=data)
        if result.get('sha256')!=sha(data) or result.get('size')!=len(data):
            raise CFError('artifact_hash_mismatch','Upload receipt does not match local bytes',409)

    def download(self, blob, dest):
        dest=Path(dest)
        if type(blob.get('size')) is not int or not 0<blob['size']<=MAX_ARTIFACT:
            raise CFError('artifact_size','Invalid artifact descriptor',413)
        if dest.is_file() and dest.stat().st_size==blob['size'] and digest(dest)==blob['sha256']:
            return
        data=self._call('GET',self.prefix+'/artifacts?'+urlencode({'key':blob['path']}),download=True)
        if len(data)!=blob['size'] or sha(data)!=blob['sha256']:
            raise CFError('artifact_hash_mismatch','Downloaded artifact failed integrity verification',409)
        atomic_bytes(dest,data)
