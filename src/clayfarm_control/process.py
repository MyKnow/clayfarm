from __future__ import annotations
import os, signal, subprocess, time
from .common import CFError

def run_isolated(argv,cwd,log,timeout,env,cancel=None,*,memory_reserve_bytes=0):
    """Explicit env; no inherited API/DB credentials. Not an OS security sandbox."""
    options={"start_new_session":True} if os.name!="nt" else {"creationflags":subprocess.CREATE_NEW_PROCESS_GROUP}
    with log.open("ab") as stream:
        p=subprocess.Popen(argv,cwd=cwd,stdout=stream,stderr=stream,env=env,**options)
        deadline=time.monotonic()+timeout
        try:
            while p.poll() is None:
                if memory_reserve_bytes:
                    import psutil
                    if psutil.virtual_memory().available < memory_reserve_bytes:
                        raise CFError("memory_pressure","Runtime stopped to preserve available host memory; retry when memory is available")
                if (cancel and cancel.is_set()) or time.monotonic()>deadline:
                    raise CFError("cancelled" if cancel and cancel.is_set() else "runtime_timeout","Runtime stopped before completion")
                time.sleep(.1)
            if p.returncode:raise CFError("runtime_failed",f"Runtime exited with status {p.returncode}")
        finally:
            if p.poll() is None:
                if os.name=="nt":subprocess.run(["taskkill","/PID",str(p.pid),"/T","/F"],capture_output=True,timeout=15)
                else:
                    try:os.killpg(p.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name!="nt":
                        try:os.killpg(p.pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                    else:p.kill()
                    p.wait(timeout=5)
