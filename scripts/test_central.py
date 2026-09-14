"""Run queue integration in disposable, loopback-only PostgreSQL/Storage containers."""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import psycopg


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real-storage',action='store_true')
    parser.add_argument('--blender',type=Path)
    parser.add_argument('--evidence',type=Path)
    args=parser.parse_args()
    name='clayfarm-test-'+secrets.token_hex(6)
    root=Path(__file__).resolve().parents[1]
    run=lambda argv:subprocess.run(argv,check=True,capture_output=True,text=True)
    run(['docker','network','create',name])
    try:
        run(['docker','run','-d','--name',name,'--network',name,'--memory','1g',
             '-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=clayfarm_test',
             '-p','127.0.0.1::5432','postgres:17-alpine'])
        address=run(['docker','port',name,'5432/tcp']).stdout.strip()
        dsn='postgresql://postgres@'+address+'/clayfarm_test'
        for _ in range(100):
            try:
                with psycopg.connect(dsn,autocommit=True) as conn:
                    conn.execute('CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN BYPASSRLS;')
                break
            except psycopg.OperationalError:time.sleep(.2)
        else:raise RuntimeError('Disposable PostgreSQL failed to start')
        env={**os.environ,'CLAYFARM_TEST_POSTGRES':dsn}
        if args.real_storage:
            env.update(CLAYFARM_TEST_STORAGE_IMAGE='supabase/storage-api:v1.60.4',
                       CLAYFARM_TEST_DOCKER_DB_HOST=name,CLAYFARM_TEST_DOCKER_NETWORK=name)
        else:env.pop('CLAYFARM_TEST_STORAGE_IMAGE',None)
        if args.blender:env['CLAYFARM_TEST_BLENDER']=str(args.blender.resolve())
        if args.evidence:env['CLAYFARM_TEST_EVIDENCE']=str(args.evidence.resolve())
        return subprocess.run([sys.executable,'-m','pytest','-q','tests/test_central_bridge.py'],cwd=root,env=env).returncode
    finally:
        subprocess.run(['docker','rm','-f','-v',name],capture_output=True)
        subprocess.run(['docker','network','rm',name],capture_output=True)


if __name__=='__main__':raise SystemExit(main())
