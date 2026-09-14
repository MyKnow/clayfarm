"""Diagnostic execution of pinned weights; never activates a model or release.

Run with the ClayFarm control environment. --python selects an isolated runtime.
The supplied manifest contains repository, full revision and SHA256 file map.
This is evidence collection, not a substitute for an authorized signed recipe.
"""
import argparse
import json
from pathlib import Path

from clayfarm_control.common import CFError, atomic_json, read_json
from clayfarm_control.inventory import probe
from clayfarm_control.models import Models
from clayfarm_control.registry import load_registry, get_profile, profile_digest, ADAPTERS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',required=True)
    parser.add_argument('--python',type=Path,required=True)
    parser.add_argument('--model-dir',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve()
    if out.exists(): parser.error('Use a new output directory for each run')
    out.mkdir(parents=True)
    registry=load_registry();profile=get_profile(registry,args.profile)
    manifest=read_json(args.manifest)
    if args.profile not in ADAPTERS: raise CFError('adapter_not_implemented','No executable adapter')
    if manifest['repository']!=registry['models'][profile['model_id']]['repository']:
        raise CFError('model_mismatch','Weights repository differs from the profile')
    manager=Models(out/'diagnostic-home',registry)
    python=str(args.python.absolute())
    state={'profile_id':args.profile,'profile_digest':profile_digest(registry,profile),
           'status':'installed_unverified','backend':profile['backend'],'python':python,
           'model_dir':str(args.model_dir.resolve()),'model_files':manifest['files'],
           'model_revision':manifest['revision'],'adapter_digest':manager.adapter_digest(args.profile),
           'environment_fingerprint':manager.environment_fingerprint(python),
           'release_id':'unsigned-hardware-diagnostic'}
    report={'profile':args.profile,'state':state,'before':probe(python=python,deep=True),
            'activated':False,'ready':False,'scope':'actual model diagnostic; no production release approval'}
    try:
        report['execution']=manager._run(args.profile,{'prompt':'one matte clay cube on a plain neutral background','seed':0},out/'run',state)
        report['status']='execution_passed_unsigned'
    except CFError as exc:
        report.update(status='failed',error={'code':exc.code,'message':exc.message})
    report['after']=probe(python=python,deep=True)
    atomic_json(out/'hardware-report.json',report)
    print(json.dumps({'status':report['status'],'profile':args.profile,'ready':False,'report':str(out/'hardware-report.json')}))
    return 0 if report['status']=='execution_passed_unsigned' else 1


if __name__=='__main__': raise SystemExit(main())
