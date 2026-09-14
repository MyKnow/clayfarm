"""Resumable MFA setup; pending seeds stay in the native credential store."""
import time

from .common import CFError


def prepare_enrollment(client, *, restart=False):
    client.vault.check_writable()
    auth = client.auth()
    token = client.session()['access_token']
    user = auth.user(token)
    cache_key = 'mfa-enrollment:' + user['id']
    factors = [f for f in user.get('factors', [])
               if f.get('factor_type') == 'totp' and f.get('friendly_name') == 'ClayFarm CLI']
    verified = next((f for f in factors if f.get('status') == 'verified'), None)
    if verified:
        return {'status': 'already_enrolled', 'factor_id': verified['id'], 'secret': None}
    pending = next((f for f in factors if f.get('status') == 'unverified'), None)
    if pending and not restart:
        saved = client.vault.get(cache_key)
        secret = saved.get('secret') if isinstance(saved, dict) and saved.get('factor_id') == pending['id'] else None
        return {'status': 'pending', 'factor_id': pending['id'], 'secret': secret}
    # Supabase enrollment handles replacement of unverified setup. Never
    # unenroll a verified factor to make a repeated command succeed.
    factor = auth.factor_enroll(token)
    secret = factor.get('totp', {}).get('secret')
    if not factor.get('id') or not isinstance(secret, str) or not secret:
        raise CFError('mfa_setup_missing', 'Authentication service did not return enrollment information')
    client.vault.put(cache_key, {'factor_id': factor['id'], 'secret': secret})
    return {'status': 'pending', 'factor_id': factor['id'], 'secret': secret}


def verify_factor(client, factor_id, code):
    client.vault.check_writable()
    auth = client.auth()
    token = client.session()['access_token']
    user = auth.user(token)
    session = auth.factor_verify(token, factor_id, code)
    if 'access_token' not in session:
        raise CFError('mfa_session_missing', 'MFA did not return a session')
    session['expires_at'] = session.get('expires_at', time.time() + session.get('expires_in', 3600))
    client.vault.put('human-session', session)
    cache_key = 'mfa-enrollment:' + user['id']
    pending = client.vault.get(cache_key)
    if isinstance(pending, dict) and pending.get('factor_id') == factor_id:
        client.vault.delete(cache_key)
    return {'status': 'mfa_verified'}
