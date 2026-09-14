from unittest.mock import Mock

import pytest

from clayfarm.cli import collect_result
from clayfarm.util import new_id


@pytest.mark.parametrize('mock_parent,hard_pass,ready', [(True, True, False), (False, False, False), (False, True, True)])
def test_report_separates_diagnostics_from_real_mechanical_candidates(tmp_path, monkeypatch, mock_parent, hard_pass, ready):
    monkeypatch.setattr('clayfarm.cli.contact_sheet', lambda *args, **kwargs: None)
    jid, parent_id, task_id = new_id(), new_id(), new_id()
    tasks = [
        {'id': parent_id, 'kind': 'reconstruct', 'status': 'done', 'parent_id': None, 'output': {'mock': mock_parent}},
        {'id': task_id, 'parent_id': parent_id, 'kind': 'process', 'status': 'done',
         'payload': {'candidate': 'one'}, 'output': {'mock': False, 'metrics': {'hard_pass': hard_pass}, 'files': []}}]
    # Old executors may have lost the mock flag; the committed ancestry still wins.
    client = Mock(); client.rpc.return_value = {'job': {'spec': {'name': 'fixture', 'views': []}, 'status': 'open'}, 'tasks': tasks}
    result = collect_result(client, jid, tmp_path)
    assert bool(result['ready_candidates']) == ready
    assert bool(result['diagnostic_candidates']) != ready
    assert result['status'] == ('review_ready' if ready else 'diagnostic_only')
    if mock_parent: assert result['diagnostic_candidates'][0]['mock'] is True
