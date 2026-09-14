import shlex
from types import SimpleNamespace

import httpx
import pytest

from clayfarm_control import cli
from clayfarm_control.auth import SupabaseAuth
from clayfarm_control.common import CFError
from clayfarm_control.vault import MemoryVault


@pytest.fixture
def client(tmp_path):
    class Auth:
        factors = []
        enroll_calls = 0

        def user(self, token):
            return {'id': 'fixture-user', 'factors': self.factors}

        def factor_enroll(self, token):
            self.enroll_calls += 1
            self.factors = [{'id': 'fixture-factor', 'friendly_name': 'ClayFarm CLI',
                             'factor_type': 'totp', 'status': 'unverified'}]
            return {'id': 'fixture-factor', 'totp': {'secret': 'FIXTURE-SECRET'}}

        def factor_verify(self, token, factor, code):
            assert factor == 'fixture-factor' and code == 'fixture-code'
            return {'access_token': 'fixture-aal2', 'expires_in': 3600,
                    'user': {'id': 'fixture-user'}}

    auth = Auth()
    return SimpleNamespace(home=tmp_path, vault=MemoryVault(), auth=lambda: auth,
                           session=lambda: {'access_token': 'fixture-aal1'})


def pending(client):
    client.auth().factors = [{'id': 'fixture-factor', 'friendly_name': 'ClayFarm CLI',
                             'factor_type': 'totp', 'status': 'unverified'}]


def test_repeated_enrollment_reuses_native_vault_seed(client):
    from clayfarm_control.mfa import prepare_enrollment
    first = prepare_enrollment(client)
    second = prepare_enrollment(client)
    assert first == second
    assert client.auth().enroll_calls == 1
    assert second['secret'] == 'FIXTURE-SECRET'


def test_uncached_pending_factor_is_preserved(client):
    from clayfarm_control.mfa import prepare_enrollment
    pending(client)
    result = prepare_enrollment(client)
    assert result['factor_id'] == 'fixture-factor'
    assert result['secret'] is None
    assert client.auth().enroll_calls == 0


def test_stale_cache_cannot_reveal_a_different_factor_seed(client):
    from clayfarm_control.mfa import prepare_enrollment
    pending(client)
    client.vault.put('mfa-enrollment:fixture-user', {'factor_id': 'old-factor', 'secret': 'OLD-SECRET'})
    assert prepare_enrollment(client)['secret'] is None


def test_explicit_restart_replaces_only_pending_setup(client):
    from clayfarm_control.mfa import prepare_enrollment
    pending(client)
    result = prepare_enrollment(client, restart=True)
    assert result['secret'] == 'FIXTURE-SECRET'
    assert client.auth().enroll_calls == 1


@pytest.mark.parametrize('restart', [False, True])
def test_verified_factor_never_replaced(client, restart):
    from clayfarm_control.mfa import prepare_enrollment
    pending(client)
    client.auth().factors[0]['status'] = 'verified'
    result = prepare_enrollment(client, restart=restart)
    assert result['status'] == 'already_enrolled' and result['secret'] is None
    assert client.auth().enroll_calls == 0


def test_locked_store_stops_enrollment(client):
    from clayfarm_control.mfa import prepare_enrollment
    def locked():
        raise CFError('vault_locked', 'Unlock store')
    client.vault.check_writable = locked
    with pytest.raises(CFError, match='Unlock store'):
        prepare_enrollment(client)
    assert client.auth().enroll_calls == 0


def test_verified_session_saved_and_pending_seed_removed(client):
    from clayfarm_control.mfa import prepare_enrollment, verify_factor
    prepare_enrollment(client)
    result = verify_factor(client, 'fixture-factor', 'fixture-code')
    assert result == {'status': 'mfa_verified'}
    assert client.vault.get('human-session')['access_token'] == 'fixture-aal2'
    assert client.vault.get('mfa-enrollment:fixture-user') is None


def test_rejected_code_keeps_setup_for_retry(client):
    from clayfarm_control.mfa import prepare_enrollment, verify_factor
    prepare_enrollment(client)
    def reject(*args):
        raise CFError('mfa_verification_failed', 'Retry the current code', 422)
    client.auth().factor_verify = reject
    with pytest.raises(CFError):
        verify_factor(client, 'fixture-factor', 'wrong-code')
    assert client.vault.get('mfa-enrollment:fixture-user')['secret'] == 'FIXTURE-SECRET'
    assert client.vault.get('human-session') is None


@pytest.mark.parametrize('mode', ['json', 'no_input'])
def test_noninteractive_enrollment_never_exposes_seed(client, monkeypatch, mode, capsys):
    args = SimpleNamespace(home=client.home, group='auth', action='mfa-enroll',
                           json=mode == 'json', no_input=mode == 'no_input')
    monkeypatch.setattr(cli, 'Client', lambda _: client)
    with pytest.raises(CFError) as error:
        cli.dispatch(args)
    assert error.value.code == 'interactive_secret_required'
    assert client.auth().enroll_calls == 0
    assert 'FIXTURE-SECRET' not in capsys.readouterr().err


def test_enroll_and_verify_in_one_interactive_command(client, monkeypatch, capsys):
    args = SimpleNamespace(home=client.home, group='auth', action='mfa-enroll',
                           json=False, no_input=False, restart=True, verify_now=True)
    monkeypatch.setattr(cli, 'Client', lambda _: client)
    monkeypatch.setattr(cli, 'ask', lambda *a: 'fixture-code')
    monkeypatch.setattr(cli.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(cli.sys.stderr, 'isatty', lambda: True)
    assert cli.dispatch(args) == {'status': 'mfa_verified'}
    output = capsys.readouterr()
    assert 'FIXTURE-SECRET' in output.err and 'FIXTURE-SECRET' not in output.out
    assert client.vault.get('human-session')['access_token'] == 'fixture-aal2'


def test_manual_next_command_keeps_custom_home(client, monkeypatch):
    args = SimpleNamespace(home=client.home / 'space dir', group='auth', action='mfa-enroll',
                           json=False, no_input=False, restart=False, verify_now=False)
    monkeypatch.setattr(cli, 'Client', lambda _: client)
    monkeypatch.setattr(cli.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(cli.sys.stderr, 'isatty', lambda: True)
    result = cli.dispatch(args)
    parts = shlex.split(result['next'])
    assert parts[parts.index('--home') + 1] == str(args.home.resolve())
    assert 'secret' not in result
    assert cli.parser().parse_args(['auth', 'mfa-enroll', '--restart', '--verify-now']).verify_now


def test_redirected_terminal_cannot_emit_setup_seed(client, monkeypatch, capsys):
    args = SimpleNamespace(home=client.home, group='auth', action='mfa-enroll',
                           json=False, no_input=False, restart=False, verify_now=False)
    monkeypatch.setattr(cli, 'Client', lambda _: client)
    monkeypatch.setattr(cli.sys.stderr, 'isatty', lambda: False)
    with pytest.raises(CFError) as error:
        cli.dispatch(args)
    assert error.value.code == 'interactive_secret_required'
    assert client.auth().enroll_calls == 0
    assert 'FIXTURE-SECRET' not in capsys.readouterr().err


def test_known_mfa_error_is_actionable_without_provider_details():
    transport = httpx.MockTransport(lambda r: httpx.Response(422, json={
        'error_code': 'mfa_factor_name_conflict', 'msg': 'PRIVATE-PROVIDER-DETAIL'}))
    auth = SupabaseAuth('https://example.supabase.co', 'sb_publishable_fixture', httpx.Client(transport=transport))
    with pytest.raises(CFError) as error:
        auth.factor_enroll('fixture-token')
    assert error.value.code == 'mfa_factor_name_conflict'
    assert error.value.status == 422
    assert 'PRIVATE-PROVIDER-DETAIL' not in error.value.message


@pytest.mark.parametrize('code', [['unexpected'], {'unexpected': True}, 'unknown_error'])
def test_unknown_provider_error_is_sanitized(code):
    transport = httpx.MockTransport(lambda r: httpx.Response(422, json={
        'error_code': code, 'msg': 'PRIVATE-PROVIDER-DETAIL'}))
    auth = SupabaseAuth('https://example.supabase.co', 'sb_publishable_fixture', httpx.Client(transport=transport))
    with pytest.raises(CFError) as error:
        auth.factor_enroll('fixture-token')
    assert error.value.code == 'auth_rejected' and error.value.status == 422
    assert 'PRIVATE-PROVIDER-DETAIL' not in error.value.message
