"""Disposable real Storage API for explicit Docker integration runs only."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

import httpx
from sqlalchemy.engine import make_url
from clayfarm_control.bridge import SupabaseStorage


class RealStorage(SupabaseStorage):
    def __init__(self,dsn,root):
        self.container='cf-storage-'+secrets.token_hex(6)
        secret=secrets.token_urlsafe(40)
        def token(role):
            enc=lambda x:base64.urlsafe_b64encode(json.dumps(x).encode()).rstrip(b'=')
            data=enc({'alg':'HS256','typ':'JWT'})+b'.'+enc({'role':role,'exp':int(time.time())+3600,'iat':int(time.time())})
            return (data+b'.'+base64.urlsafe_b64encode(hmac.new(secret.encode(),data,hashlib.sha256).digest()).rstrip(b'=')).decode()
        service=token('service_role')
        dburl=make_url(dsn).set(host=os.environ['CLAYFARM_TEST_DOCKER_DB_HOST'],port=5432)
        variables={'DATABASE_URL':dburl.render_as_string(hide_password=False),'AUTH_JWT_SECRET':secret,
                   'ANON_KEY':token('anon'),'SERVICE_KEY':service,'POSTGREST_URL':'http://127.0.0.1:1',
                   'STORAGE_BACKEND':'file','FILE_STORAGE_BACKEND_PATH':'/tmp/storage','GLOBAL_S3_BUCKET':'local',
                   'TENANT_ID':'local','REGION':'local','ENABLE_IMAGE_TRANSFORMATION':'false','DB_INSTALL_ROLES':'true'}
        envfile=Path(root)/'storage.env';envfile.write_text(''.join(f'{k}={v}\n' for k,v in variables.items()));envfile.chmod(0o600)
        subprocess.run(['docker','run','-d','--memory','256m','--name',self.container,
                        '--network',os.environ['CLAYFARM_TEST_DOCKER_NETWORK'],'-p','127.0.0.1::5000',
                        '--env-file',str(envfile),os.environ['CLAYFARM_TEST_STORAGE_IMAGE']],check=True,capture_output=True)
        envfile.unlink()
        address=subprocess.check_output(['docker','port',self.container,'5000/tcp'],text=True).strip()
        self.url='http://'+address
        self.http=httpx.Client(timeout=60,follow_redirects=False,headers={'apikey':service,'Authorization':'Bearer '+service})
        for _ in range(100):
            try:
                if self.http.get(self.url+'/status').status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.2)
        else:
            subprocess.run(['docker','logs',self.container],stdout=(Path(root)/'storage-startup.log').open('w'),stderr=subprocess.STDOUT)
            self.close()
            raise RuntimeError('Disposable Storage failed to start; inspect local test log')
        response=self.http.post(self.url+'/bucket',json={'id':'clayfarm','name':'clayfarm','public':False})
        response.raise_for_status()

    def _url(self,key):
        return super()._url(key).replace('/storage/v1/object/','/object/')

    def close(self):
        self.http.close()
        subprocess.run(['docker','rm','-f',self.container],capture_output=True,check=True)
