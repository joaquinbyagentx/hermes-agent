"""LOCAL: recurring cron runs must not hold the gateway restart wait (Jose 3-nov-2026)."""
from cron import scheduler


def _jobs(monkeypatch, jobs):
    monkeypatch.setattr("cron.jobs.load_jobs", lambda: jobs)
    scheduler._recurring_key_cache.clear()


def test_recurring_run_is_not_awaitable(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _jobs(monkeypatch, [
        {"id": "audit15", "schedule": {"kind": "interval", "minutes": 15}},
        {"id": "oneshot", "schedule": {"kind": "once", "run_at": "2026-11-04T00:00:00"}},
    ])
    for j in ("audit15", "oneshot"):
        assert scheduler.try_register_running_job(j)
    try:
        c = scheduler.get_restart_wait_cron_counts()
        assert c == {"awaitable": 1, "wedged": 1, "restart_safe": 0}
    finally:
        for j in ("audit15", "oneshot"):
            scheduler.release_running_job(j)


def test_opt_out_keeps_waiting(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_CRON_RESTART_WAIT_SKIP_RECURRING", "0")
    monkeypatch.setattr(scheduler, "load_config", lambda: {})
    _jobs(monkeypatch, [{"id": "audit15", "schedule": {"kind": "interval", "minutes": 15}}])
    assert scheduler.try_register_running_job("audit15")
    try:
        assert scheduler.get_restart_wait_cron_counts()["awaitable"] == 1
    finally:
        scheduler.release_running_job("audit15")
