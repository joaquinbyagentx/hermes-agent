"""Local (Jose 2026-10-25): a cron job may only fire if it is documented and current in the wiki.

Before any run, the job must appear in Agent-Shared/Knowledge/CRONS.md under "## Activos" with the
same profile, id and schedule. Otherwise the job is paused and Jose is told to authorize it.
Fails closed for undocumented jobs; fails open (logs) only if the wiki file itself cannot be read,
so an iCloud hiccup does not stop guards like the GX10 power watchdog.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

VAULT = os.environ.get("OBSIDIAN_VAULT_PATH") or os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs/Joaquins Vault")
CRONS_MD = Path(VAULT) / "Agent-Shared" / "Knowledge" / "CRONS.md"
JOSE_CHAT = "6360918947"


def _profile() -> str:
    home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
    m = re.search(r"/profiles/([^/]+)/?$", home.rstrip("/"))
    return m.group(1) if m else "default"


def schedule_str(job: dict) -> str:
    s = job.get("schedule")
    if isinstance(s, dict):
        s = s.get("expr") or s.get("display")
    return str(s or "").strip()


def _documented(profile: str, job_id: str):
    text = CRONS_MD.read_text(encoding="utf-8")
    part = text.split("## Activos", 1)[-1].split("\n## ", 1)[0]
    for line in part.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] == profile and cells[1].strip("`") == job_id:
            return cells[2]
    return None


def _notify(msg: str) -> None:
    try:
        env = {}
        for p in (Path(os.path.expanduser("~/.hermes/.env")),):
            for ln in p.read_text().splitlines():
                if "=" in ln and not ln.lstrip().startswith("#"):
                    k, v = ln.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
        tok = os.environ.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_BOT_TOKEN")
        if not tok:
            return
        proxy = os.environ.get("TELEGRAM_PROXY") or env.get("TELEGRAM_PROXY")
        handlers = [urllib.request.ProxyHandler({"https": proxy, "http": proxy})] if proxy else []
        opener = urllib.request.build_opener(*handlers)
        body = json.dumps({"chat_id": JOSE_CHAT, "text": msg}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=body,
                                     headers={"Content-Type": "application/json"})
        opener.open(req, timeout=15).read()
    except Exception:  # noqa: BLE001 - best effort notice
        logger.warning("cron wiki gate: telegram notice failed", exc_info=True)


def check(job: dict):
    """Return None if the job may run, else a short reason (job already paused)."""
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("HERMES_CRON_WIKI_GATE") == "0":
        return None
    job_id = str(job.get("id") or "")
    profile = _profile()
    try:
        documented = _documented(profile, job_id)
    except Exception:  # noqa: BLE001
        logger.warning("cron wiki gate: CRONS.md unreadable, allowing %s", job_id, exc_info=True)
        return None
    sched = schedule_str(job)
    if documented is not None and documented == sched:
        return None
    why = ("no está documentado en CRONS.md" if documented is None
           else f"el horario real ({sched}) no coincide con el wiki ({documented})")
    reason = f"wiki-gate: {why}; requiere autorización de Jose"
    try:
        from cron.jobs import pause_job
        pause_job(job_id, reason=reason)
    except Exception:  # noqa: BLE001
        logger.error("cron wiki gate: pause failed for %s", job_id, exc_info=True)
    _notify(f"⛔ Cron pausado ({profile} {job_id} «{job.get('name') or ''}»): {why}. "
            "No corre hasta que lo autorices y quede actualizado en el wiki.")
    logger.warning("cron wiki gate blocked %s/%s: %s", profile, job_id, why)
    return reason
