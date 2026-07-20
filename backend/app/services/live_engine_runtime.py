from __future__ import annotations

from datetime import UTC, datetime


def watchlist_summary(selected_watchlist) -> dict | None:
    if selected_watchlist is None:
        return None
    return {
        "id": str(selected_watchlist.id),
        "name": selected_watchlist.name,
        "exchange": selected_watchlist.exchange,
    }


def build_live_engine_runtime_snapshot(
    *,
    status: str,
    message: str,
    selected_watchlist=None,
    subscriptions: list[dict] | None = None,
    transport: str = "placeholder",
    credentials_configured: bool = False,
    access_token_configured: bool = False,
    last_tick_at: datetime | None = None,
    last_tick_symbol: str | None = None,
) -> dict:
    return {
        "status": status,
        "message": message,
        "transport": transport,
        "selected_watchlist": watchlist_summary(selected_watchlist),
        "subscription_count": len(subscriptions or []),
        "subscriptions": subscriptions or [],
        "credentials_configured": credentials_configured,
        "access_token_configured": access_token_configured,
        "last_tick_at": last_tick_at.astimezone(UTC).isoformat() if last_tick_at else None,
        "last_tick_symbol": last_tick_symbol,
    }
