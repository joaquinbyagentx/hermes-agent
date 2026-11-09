"""hermes-local: implicit per-profile/conversation browser session + pkill multi -f guard."""
import re

from tools import browser_use_cli as b
from tools.approval_detection import DANGEROUS_PATTERNS


def test_implicit_session_distinct_per_task(monkeypatch):
    monkeypatch.setattr("hermes_cli.profiles.get_active_profile_name", lambda: "oracle")
    a = b._implicit_session_name("abc12345-xyz")
    c = b._implicit_session_name("zzz99999-xyz")
    assert a == "oracle-abc12345" and c == "oracle-zzz99999" and a != c
    assert b._SESSION_RE.match(a)


def test_implicit_session_empty_without_task(monkeypatch):
    monkeypatch.setattr("hermes_cli.profiles.get_active_profile_name", lambda: "oracle")
    assert b._implicit_session_name(None) == ""
    assert b._implicit_session_name("---") == ""


def _flagged(cmd):
    return any(re.search(p, cmd) for p, _ in DANGEROUS_PATTERNS)


def test_pkill_multiple_f_flagged():
    assert _flagged('pkill -f "J271_ATTEMPT=b0" -f "proc_d030e15b4565"')
    assert _flagged('pkill -f "-something"')


def test_single_pkill_f_not_flagged_by_new_rule():
    assert not _flagged('pkill -f "my-worker-script.py"')
