"""Quota-only pools must not spend backup credentials for concurrency or auth errors."""
import time
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from agent.credential_pool import CredentialPool, PooledCredential, STATUS_EXHAUSTED, STATUS_DEAD


def pool():
    entries = [PooledCredential(provider='test', id=name, label=name,
                auth_type='api_key', priority=i, source='manual', access_token='synthetic-'+name)
               for i, name in enumerate(['primary', 'backup'])]
    p = CredentialPool('test', entries)
    p._strategy = 'quota_fallback'
    return p


def test_parallel_leases_and_explicit_backup_stay_primary():
    p = pool()
    with ThreadPoolExecutor(max_workers=8) as workers:
        assert set(workers.map(lambda _: p.acquire_lease(), range(32))) == {'primary'}
    assert p.acquire_lease('backup') is None
    assert p.select().id == 'primary'


def test_only_quota_exhaustion_unlocks_backup_and_recovery_returns_primary():
    p = pool()
    original = p._entries[0]
    for status, reason in [(STATUS_DEAD, 'invalid_grant'), (STATUS_EXHAUSTED, 'rate_limit_exceeded')]:
        p._entries[0] = replace(original, last_status=status, last_status_at=time.time(),
                                last_error_code=429, last_error_reason=reason,
                                last_error_reset_at=time.time()+3600)
        assert p.acquire_lease() is None
        assert p.select() is None
    p._entries[0] = replace(original, last_status=STATUS_EXHAUSTED, last_status_at=time.time(),
                            last_error_code=429, last_error_reason='usage_limit_reached',
                            last_error_reset_at=time.time()+3600)
    assert p.acquire_lease() == 'backup'
    assert p.select().id == 'backup'
    p._entries[0] = original
    assert p.acquire_lease() == 'primary'
    assert p.select().id == 'primary'
