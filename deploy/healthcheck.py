"""Read-only local API + production queue readiness; never print credentials."""
import json
import os
import sys
from urllib.request import urlopen

from sqlalchemy import create_engine, text


def main():
    try:
        with urlopen("http://127.0.0.1:8765/health", timeout=4) as response:
            health = json.load(response)
        if (health.get("status") != "ok"
                or health.get("queue_backend") != "public.cf_jobs/cf_tasks"
                or health.get("parallel_queue_enabled") is not False):
            return 1
        engine = create_engine(os.environ["CLAYFARM_DATABASE_URL"], connect_args={
            "connect_timeout": 4, "options": "-c statement_timeout=4000"})
        try:
            with engine.connect() as connection:
                farm = connection.execute(text(
                    "SELECT farm_id::text FROM cf_control.farm_binding WHERE singleton"
                )).scalar_one()
                rpc = connection.execute(text(
                    "SELECT has_function_privilege(current_user, "
                    "'clayfarm_private.control_rpc(uuid,text,text,jsonb,text)', 'EXECUTE')"
                )).scalar_one()
                return 0 if farm == os.environ["CLAYFARM_FARM_ID"] and rpc else 1
        finally:
            engine.dispose()
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
