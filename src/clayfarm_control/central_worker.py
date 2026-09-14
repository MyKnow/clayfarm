"""Run existing real 3D executors with node signatures and durable journals."""
from pathlib import Path

from clayfarm.worker import Worker
from clayfarm.resources import capabilities, telemetry, can_run
from clayfarm.util import ProcessLock
from .bridge_client import BridgeBackend
from .common import CFError, read_json, atomic_json, canonical, sha, file_sha

RUNTIME_FIELDS = {'engines','engine_limits','blender','blender_selftest','cpu_threads','lease_seconds',
                  'min_free_vram_mb','max_external_gpu_util','max_gpu_temperature',
                  'gpu_min_ram_mb','cpu_min_ram_mb','min_disk_free_mb','max_pending_results'}


def runtime_config(home):
    runtime=read_json(Path(home)/'execution.json',{})
    if not isinstance(runtime,dict) or set(runtime)-RUNTIME_FIELDS:
        raise CFError('invalid_runtime_config','Only local executor settings belong in execution.json')
    limits=runtime.get('engine_limits',{})
    if not isinstance(limits,dict) or set(limits)-{'triposr','sf3d'}:
        raise CFError('invalid_runtime_config','Invalid engine resource limits')
    for values in limits.values():
        if (not isinstance(values,dict) or set(values)-{'min_free_vram_mb','gpu_min_ram_mb'}
                or any(type(v) is not int or v<=0 for v in values.values())):
            raise CFError('invalid_runtime_config','Invalid engine memory requirement')
    policy=read_json(Path(home)/'policy.json',{})
    return {**runtime,'home':str(Path(home)/'central-worker'), 'prefetch':0,
            'allow_mock':False,'offline_speculation':False,'allow_battery':bool(policy.get('allow_battery',False))}


class CentralWorker(Worker):
    def engine_can_run(self,engine):
        # Unknown host memory is not permission to dispatch a measured model.
        if self.stats.get('memory_available_mb') is None: return False
        limits=self.cfg.get('engine_limits',{}).get(engine,{})
        return can_run('gpu',{**self.cfg,**limits},self.stats)

    def can_run_slot(self,slot):
        if slot!='gpu': return super().can_run_slot(slot)
        return any(cap in ('triposr','sf3d') and self.engine_can_run(cap) for cap in self.caps)

    def step(self,slot):
        # Refresh both telemetry and server capabilities immediately before
        # claiming, so a low-memory policy never enables a heavier engine.
        self.refresh()
        return super().step(slot)

    def refresh(self):
        # Approval is a maximum allowed set; local executor readiness must still
        # pass the existing actual Blender selftest / engine warm contract.
        self.stats=telemetry(self.cfg)
        self.stats['allow_battery']=self.cfg.get('allow_battery',False)
        self.caps=[cap for cap in capabilities(self.cfg)
                   if cap=='blender' or (engine_verified(self.cfg,cap) and self.engine_can_run(cap))]
        import os,time
        self.journal.put('status',{**self.stats,'capabilities':self.caps,'pid':os.getpid(),'updated':time.time()})
        self.backend.rpc('heartbeat',{'capabilities':self.caps,'telemetry':self.stats})


def run(home, client, once=False):
    cfg=runtime_config(home)
    worker=CentralWorker(cfg,BridgeBackend(client,node=True))
    if once:
        with ProcessLock(worker.home/'worker.lock'):
            worker.refresh(); worker.flush()
            ran=worker.step('gpu') or worker.step('cpu')
            worker.flush()
            return {'status':'worked' if ran else 'idle','capabilities':worker.caps,
                    'queue_backend':'public.cf_jobs/cf_tasks','journal':str(worker.home/'worker.sqlite')}
    worker.run_forever()
    return {'stopped':True,'queue_backend':'public.cf_jobs/cf_tasks'}


def engine_signature(settings):
    from clayfarm import executors,setup,resources,mesh_coordinates
    return sha(canonical(settings)+b''.join(Path(m.__file__).read_bytes() for m in (executors,setup,resources,mesh_coordinates)))


def engine_verified(cfg,engine):
    settings=cfg.get('engines',{}).get(engine,{})
    receipt=read_json(Path(cfg['home'])/'engines'/engine/'control-verification.json',{})
    try:
        artifact=Path(receipt['artifact'])
        return bool(settings.get('ready') and settings.get('offline_ready')
                    and receipt['signature']==engine_signature(settings)
                    and artifact.is_file() and file_sha(artifact)==settings['smoke_sha256'])
    except (OSError,KeyError,TypeError,ValueError): return False


def warm_engine(home,args):
    """Reuse the real CUDA warm path without a legacy human enrollment file."""
    import re
    from clayfarm.setup import warm
    if args.install and any(not re.fullmatch(r'[0-9a-f]{40}',v or '') for v in (args.ref,args.model_revision)):
        raise CFError('pinned_revision_required','Installation requires full source and model commit hashes')
    home=Path(home);cfg=runtime_config(home)
    with ProcessLock(Path(cfg['home'])/'worker.lock'):
        runtime=read_json(home/'execution.json',{})
        runtime.setdefault('engines',{}).setdefault(args.engine,{})['ready']=False
        atomic_json(home/'execution.json',runtime)
        result=warm(cfg,args.engine,args.repo,args.python,args.test_image,args.install,args.ref,args.model_revision,args.accept_model_license)
        settings=cfg['engines'][args.engine]
        smoke=read_json(Path(cfg['home'])/'engines'/args.engine/'latest-smoke.json')
        atomic_json(Path(cfg['home'])/'engines'/args.engine/'control-verification.json',
                    {'signature':engine_signature(settings),'artifact':smoke['artifact'],'fixture':False,'backend':'cuda'})
        runtime['engines'][args.engine]=settings
        atomic_json(home/'execution.json',runtime)
        return result
