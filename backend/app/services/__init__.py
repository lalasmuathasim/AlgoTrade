"""Service layer exports for the backend application."""

from backend.app.services.paper_trading_service import generate_paper_trade_from_signal

__all__ = ["generate_paper_trade_from_signal"]
