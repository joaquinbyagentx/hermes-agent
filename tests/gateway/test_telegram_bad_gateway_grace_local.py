"""Local patch (Jose 2026-11-06): a transient Telegram 502 waits for PTB's own retry loop
(5/10/20 s) before stopping the Updater / rebuilding the adapter."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config import PlatformConfig
from plugins.platforms.telegram.adapter import TelegramAdapter


@pytest.fixture(autouse=True)
def _no_auto_discovery(monkeypatch):
    async def _noop():
        return []
    monkeypatch.setattr("plugins.platforms.telegram.adapter.discover_fallback_ips", _noop)


def _adapter_with_running_updater():
    adapter = TelegramAdapter(PlatformConfig(enabled=True, token="test-token"))
    updater = MagicMock()
    updater.running = True
    updater.stop = AsyncMock()
    updater.start_polling = AsyncMock()
    app = MagicMock()
    app.updater = updater
    adapter._app = app
    return adapter, updater


@pytest.mark.asyncio
async def test_bad_gateway_that_clears_does_not_stop_updater():
    adapter, updater = _adapter_with_running_updater()
    calls = []

    async def fake_sleep(s):
        calls.append(s)
        if len(calls) == 2:  # PTB got a good getUpdates during the 10 s step
            adapter._polling_last_progress_monotonic = time.monotonic() + 1

    with patch("asyncio.sleep", side_effect=fake_sleep):
        await adapter._handle_polling_network_error(Exception("Bad Gateway"))

    assert calls == [5, 10]
    updater.stop.assert_not_called()
    updater.start_polling.assert_not_called()
    assert adapter._polling_network_error_count == 0
    assert not adapter.has_fatal_error


@pytest.mark.asyncio
async def test_bad_gateway_that_persists_falls_back_to_normal_reconnect():
    adapter, updater = _adapter_with_running_updater()
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    with patch("asyncio.sleep", side_effect=fake_sleep), \
         patch.object(adapter, "_drain_polling_connections", AsyncMock()), \
         patch.object(adapter, "_start_polling_once", AsyncMock()) as start:
        await adapter._handle_polling_network_error(Exception("Bad Gateway"))

    assert sleeps[:3] == [5, 10, 20]  # grace first, then the normal ladder
    assert adapter._polling_network_error_count == 1
    updater.stop.assert_called()
    start.assert_called_once()


@pytest.mark.asyncio
async def test_non_502_errors_skip_the_grace():
    adapter, updater = _adapter_with_running_updater()
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    with patch("asyncio.sleep", side_effect=fake_sleep), \
         patch.object(adapter, "_drain_polling_connections", AsyncMock()), \
         patch.object(adapter, "_start_polling_once", AsyncMock()):
        await adapter._handle_polling_network_error(Exception("Timed out"))

    assert sleeps[0] == 5 and 10 not in sleeps[:1]
    assert adapter._polling_network_error_count == 1
