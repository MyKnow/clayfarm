from types import SimpleNamespace
import sys

import pytest

from clayfarm_control import cli
from clayfarm_control.common import CFError
from clayfarm_control.vault import Vault


@pytest.fixture
def native_store(monkeypatch):
    backend = type('Keyring', (), {})()
    type(backend).__module__ = 'keyring.backends.macOS'
    entries = {}
    api = SimpleNamespace(
        get_keyring=lambda: backend,
        get_password=lambda service, name: entries.get((service, name)),
        set_password=lambda service, name, value: entries.__setitem__((service, name), value),
        delete_password=lambda service, name: entries.pop((service, name)),
    )
    monkeypatch.setitem(sys.modules, 'keyring', api)
    return api, entries


def test_probe_preserves_credentials_and_cleans_up(native_store):
    _, entries = native_store
    vault = Vault('fixture')
    vault.put('human-session', {'fixture': 'session'})
    vault.put('node-key', {'fixture': 'node'})
    before = dict(entries)
    vault.check_writable()
    assert entries == before


@pytest.mark.parametrize('failure', ['write', 'read', 'delete'])
def test_probe_fails_closed_without_backend_error_details(native_store, failure):
    api, _ = native_store
    def reject(*args):
        raise RuntimeError('private backend detail')
    setattr(api, {'write': 'set_password', 'read': 'get_password', 'delete': 'delete_password'}[failure], reject)
    with pytest.raises(CFError) as error:
        Vault('fixture').check_writable()
    assert error.value.code == 'vault_locked'
    assert 'private backend detail' not in error.value.message
    assert 'unlock' in error.value.message.lower()


def test_probe_rejects_silent_write_failure(native_store):
    api, _ = native_store
    api.set_password = lambda *args: None
    with pytest.raises(CFError) as error:
        Vault('fixture').check_writable()
    assert error.value.code == 'vault_locked'


@pytest.mark.parametrize('action', ['signup', 'login', 'verify', 'mfa-verify'])
def test_locked_store_stops_before_auth_or_code_input(tmp_path, monkeypatch, action):
    def locked():
        raise CFError('vault_locked', 'Unlock the credential store')
    def unexpected(*args, **kwargs):
        pytest.fail('Authentication or code input happened before the vault check')
    client = SimpleNamespace(vault=SimpleNamespace(check_writable=locked), auth=unexpected, session=unexpected)
    monkeypatch.setattr(cli, 'Client', lambda _: client)
    monkeypatch.setattr(cli, 'ask', unexpected)
    args = SimpleNamespace(home=tmp_path, group='auth', action=action,
                           email='user@example.test', send_only=False, code_stdin=False)
    with pytest.raises(CFError) as error:
        cli.dispatch(args)
    assert error.value.code == 'vault_locked'
    assert not (tmp_path / 'pending-login.json').exists()


def test_check_vault_does_not_contact_auth(tmp_path, monkeypatch, native_store):
    def unexpected(*args, **kwargs):
        pytest.fail('A local vault check must not contact the server')
    monkeypatch.setattr(cli, 'Client', lambda _: SimpleNamespace(vault=Vault('fixture'), auth=unexpected))
    args = SimpleNamespace(home=tmp_path, group='auth', action='check-vault')
    assert cli.dispatch(args) == {'status': 'credential_store_ready'}
    assert cli.parser().parse_args(['auth', 'check-vault']).action == 'check-vault'


def test_login_stores_session_after_successful_probe(tmp_path, monkeypatch, native_store):
    vault = Vault('fixture')
    calls = []
    auth = SimpleNamespace(
        otp=lambda email, signup: calls.append(('otp', signup)),
        verify=lambda email, code: {'access_token': 'fixture', 'expires_in': 3600, 'user': {'id': 'fixture-user'}},
    )
    monkeypatch.setattr(cli, 'ask', lambda *args: 'fixture-code')
    client = SimpleNamespace(home=tmp_path, vault=vault, auth=lambda: auth)
    args = SimpleNamespace(email='user@example.test')
    assert cli.login(client, args, signup=True)['user_id'] == 'fixture-user'
    assert calls == [('otp', True)]
    assert vault.get('human-session')['access_token'] == 'fixture'
