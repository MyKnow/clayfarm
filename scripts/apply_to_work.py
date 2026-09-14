#!/usr/bin/env python3
"""Add an isolated extension folder to an explicitly selected Git root; never overwrite."""
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess, sys
from pathlib import Path

EXCLUDED = {'.git', '.venv', '__pycache__', '.pytest_cache', 'build', 'dist', '.temp', 'work'}
TOP_LEVEL = {'src', 'tests', 'tests_legacy', 'docs', 'examples', 'scripts', 'evidence', 'sql', 'supabase', 'locks', 'deploy'}
TOP_FILES = {'README.md', 'WORK_HANDOFF.md', 'TEST_REPORT.md', 'AGENTS.md', 'LICENSE', '.gitignore', '.dockerignore', 'pyproject.toml', 'install.sh', 'install.ps1'}

def files(source: Path):
    selected=[]
    for child in source.iterdir():
        if child.name in TOP_LEVEL:
            selected.append(child)
            if not child.is_symlink(): selected.extend(child.rglob('*'))
        elif child.name in TOP_FILES: selected.append(child)
    for path in sorted(selected):
        rel=path.relative_to(source)
        if any(x in EXCLUDED or x.endswith('.egg-info') for x in rel.parts): continue
        if path.is_symlink(): raise ValueError('Symlinks in the source package are not accepted')
        if not path.is_file(): continue
        if rel.parts[0] not in TOP_LEVEL and str(rel) not in TOP_FILES: continue
        if path.suffix in {'.pyc', '.db', '.sqlite', '.pem'} or 'enrollment' in path.name.lower(): continue
        yield rel,path

def apply(target: Path, source: Path, enabled=False):
    target=target.expanduser().resolve(); source=source.resolve()
    if not target.is_dir(): raise ValueError('Target must be an existing Git working tree root')
    result=subprocess.run(['git','-C',str(target),'rev-parse','--show-toplevel'],capture_output=True,text=True,timeout=10)
    if result.returncode or Path(result.stdout.strip()).resolve()!=target:
        raise ValueError('Use the exact current Work Git repository root; a subdirectory is not accepted')
    dest=target/'tools'/'clayfarm-control'
    if dest.exists() or dest.is_symlink(): raise ValueError('Destination already exists; no existing files will be overwritten')
    if (target/'tools').is_symlink(): raise ValueError('A symlinked tools directory is not accepted')
    if source.is_relative_to(dest) or dest.is_relative_to(source): raise ValueError('Source and target must be separate working trees')
    planned=list(files(source))
    state=subprocess.run(['git','-C',str(target),'status','--porcelain=v1'],capture_output=True,text=True,timeout=10,check=True).stdout
    head=subprocess.run(['git','-C',str(target),'rev-parse','--verify','HEAD'],capture_output=True,text=True,timeout=10)
    report={'mode':'apply' if enabled else 'dry_run','target':str(target),'destination':str(dest),'head':head.stdout.strip() if head.returncode==0 else None,'existing_changes_preserved':True,'existing_status':state.splitlines(),'file_count':len(planned),'files':[str(r) for r,_ in planned],'git_commit_or_push':False,'server_changed':False}
    if enabled:
        dest.mkdir(parents=True,exist_ok=False)
        for rel,path in planned:
            output=dest/rel;output.parent.mkdir(parents=True,exist_ok=True)
            with output.open('xb') as handle: handle.write(path.read_bytes())
            shutil.copymode(path,output)
    return report

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--target',type=Path,required=True)
    flags=p.add_mutually_exclusive_group();flags.add_argument('--apply',action='store_true');flags.add_argument('--dry-run',action='store_true')
    a=p.parse_args(argv)
    try:
        result=apply(a.target,Path(__file__).resolve().parents[1],a.apply)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr);return 2

if __name__=='__main__': raise SystemExit(main())
