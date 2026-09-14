import importlib.util,subprocess
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('work_import',ROOT/'scripts/apply_to_work.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def repo(tmp_path):
    root=tmp_path/'Work repo';root.mkdir();subprocess.run(['git','init',str(root)],capture_output=True,check=True)
    (root/'user-change.txt').write_text('preserve me')
    return root

def test_work_plan_no_write(tmp_path):
    root=repo(tmp_path);report=module.apply(root,ROOT)
    assert report['mode']=='dry_run' and report['file_count']>20
    assert not (root/'tools').exists()
    assert (root/'user-change.txt').read_text()=='preserve me'

def test_work_apply_additive_and_repeat_refused(tmp_path):
    root=repo(tmp_path);report=module.apply(root,ROOT,True)
    assert Path(report['destination'],'src/clayfarm_control/cli.py').is_file()
    assert (root/'user-change.txt').read_text()=='preserve me'
    with pytest.raises(ValueError,match='already exists'):module.apply(root,ROOT,True)

def test_work_subdirectory_refused(tmp_path):
    root=repo(tmp_path);child=root/'nested';child.mkdir()
    with pytest.raises(ValueError,match='exact'):module.apply(child,ROOT)

def test_work_credential_exclusion(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'src').mkdir()
    (source/'src/worker.enrollment.json').write_text('{"password":"test-only"}')
    (source/'src/good.py').write_text('value = 1')
    paths=[str(rel) for rel,_ in module.files(source)]
    assert paths==['src/good.py']

def test_work_import_includes_queue_migrations_and_legacy_sql(tmp_path):
    paths={str(rel) for rel,_ in module.files(ROOT)}
    assert 'sql/bootstrap.sql' in paths
    assert 'supabase/migrations/20260912101300_control_queue_bridge.sql' in paths
    assert 'deploy/Dockerfile' in paths
    assert '.dockerignore' in paths
    assert 'locks/server-linux-amd64-py312.lock' in paths
    assert not any('/.temp/' in p or p.startswith('work/') for p in paths)

def test_top_level_source_symlink_is_refused(tmp_path):
    source=tmp_path/'source';source.mkdir()
    outside=tmp_path/'outside';outside.mkdir();(outside/'private.py').write_text('private = True')
    (source/'src').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError,match='Symlinks'):list(module.files(source))
