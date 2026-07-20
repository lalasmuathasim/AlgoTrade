import math
import uuid
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import PaperTrade, PaperTradingSetting, TradingSignal
from backend.app.schemas import ExecutionModeResponse, PaperTradingSettingsPayload, StrategySettingsPayload
from backend.app.services.zerodha_sessions import get_current_zerodha_session


settings = get_settings()


def get_default_settings_payload() -> PaperTradingSettingsPayload:
    return PaperTradingSettingsPayload(
        starting_capital=200000.0,
        capital_per_trade=25000.0,
        fixed_quantity=None,
        risk_per_trade=2500.0,
        brokerage_estimate=20.0,
        slippage_estimate=0.2,
        max_trades_per_day=3,
        max_daily_loss=5000.0,
        default_quantity_mode="RISK_BASED",
        buy_volume_multiplier=settings.buy_volume_multiplier,
        sell_volume_multiplier=settings.sell_volume_multiplier,
        entry_buffer_ticks=settings.entry_buffer_ticks,
        stop_loss_buffer_ticks=settings.stop_buffer_ticks,
        daily_candle_lookback=settings.daily_candle_lookback,
        swing_window=settings.swing_window,
        max_gap_percent=settings.max_gap_percent,
        min_swing_distance=max(int(settings.min_swing_distance), 1),
    )


def ensure_settings(db: Session) -> PaperTradingSetting:
    current = db.scalar(select(PaperTradingSetting).order_by(desc(PaperTradingSetting.updated_at)).limit(1))
    if current is not None:
        return current

    defaults = get_default_settings_payload()
    current = PaperTradingSetting(
        starting_capital=defaults.starting_capital,
        capital_per_trade=defaults.capital_per_trade,
        fixed_quantity=defaults.fixed_quantity,
        risk_per_trade=defaults.risk_per_trade,
        brokerage_estimate=defaults.brokerage_estimate,
        slippage_estimate=defaults.slippage_estimate,
        max_trades_per_day=defaults.max_trades_per_day,
        max_daily_loss=defaults.max_daily_loss,
        default_quantity_mode=defaults.default_quantity_mode,
        live_trading_enabled=settings.zerodha_live_trading_enabled,
        buy_volume_multiplier=defaults.buy_volume_multiplier,
        sell_volume_multiplier=defaults.sell_volume_multiplier,
        entry_buffer_ticks=defaults.entry_buffer_ticks,
        stop_loss_buffer_ticks=defaults.stop_loss_buffer_ticks,
        daily_candle_lookback=defaults.daily_candle_lookback,
        swing_window=defaults.swing_window,
        max_gap_percent=defaults.max_gap_percent,
        min_swing_distance=defaults.min_swing_distance,
    )
    db.add(current)
    db.commit()
    db.refresh(current)
    return current


def update_settings(db: Session, payload: PaperTradingSettingsPayload) -> PaperTradingSetting:
    current = ensure_settings(db)
    current.starting_capital = payload.starting_capital
    current.capital_per_trade = payload.capital_per_trade
    current.fixed_quantity = payload.fixed_quantity
    current.risk_per_trade = payload.risk_per_trade
    current.brokerage_estimate = payload.brokerage_estimate
    current.slippage_estimate = payload.slippage_estimate
    current.max_trades_per_day = payload.max_trades_per_day
    current.max_daily_loss = payload.max_daily_loss
    current.default_quantity_mode = payload.default_quantity_mode
    current.live_trading_enabled = getattr(payload, "live_trading_enabled", current.live_trading_enabled)
    current.buy_volume_multiplier = payload.buy_volume_multiplier
    current.sell_volume_multiplier = payload.sell_volume_multiplier
    current.entry_buffer_ticks = payload.entry_buffer_ticks
    current.stop_loss_buffer_ticks = payload.stop_loss_buffer_ticks
    current.daily_candle_lookback = payload.daily_candle_lookback
    current.swing_window = payload.swing_window
    current.max_gap_percent = payload.max_gap_percent
    current.min_swing_distance = payload.min_swing_distance
    current.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(current)
    return current


def get_execution_mode_payload(db: Session) -> ExecutionModeResponse:
    current = ensure_settings(db)
    zerodha_session = get_current_zerodha_session(db)
    return ExecutionModeResponse(
        paper_trading_enabled=settings.paper_trading_enabled,
        live_trading_enabled=current.live_trading_enabled,
        effective_mode="PAPER_AND_LIVE" if current.live_trading_enabled else "PAPER_ONLY",
        zerodha_credentials_configured=bool(
            settings.zerodha_api_key and settings.zerodha_api_secret and settings.zerodha_redirect_url
        ),
        zerodha_session_present=zerodha_session is not None,
        zerodha_access_token_expires_at=zerodha_session.access_token_expires_at if zerodha_session else None,
    )


def update_live_trading_enabled(db: Session, enabled: bool) -> PaperTradingSetting:
    current = ensure_settings(db)
    current.live_trading_enabled = enabled
    current.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(current)
    return current


def get_strategy_settings_payload(db: Session) -> StrategySettingsPayload:
    current = ensure_settings(db)
    return StrategySettingsPayload(
        daily_candle_lookback=current.daily_candle_lookback,
        swing_window=current.swing_window,
        max_gap_percent=current.max_gap_percent,
        min_swing_distance=current.min_swing_distance,
        buy_volume_multiplier=current.buy_volume_multiplier,
        sell_volume_multiplier=current.sell_volume_multiplier,
        entry_buffer_ticks=current.entry_buffer_ticks,
        stop_loss_buffer_ticks=current.stop_loss_buffer_ticks,
    )


def update_strategy_settings(db: Session, payload: StrategySettingsPayload) -> PaperTradingSetting:
    current = ensure_settings(db)
    current.daily_candle_lookback = payload.daily_candle_lookback
    current.swing_window = payload.swing_window
    current.max_gap_percent = payload.max_gap_percent
    current.min_swing_distance = payload.min_swing_distance
    current.buy_volume_multiplier = payload.buy_volume_multiplier
    current.sell_volume_multiplier = payload.sell_volume_multiplier
    current.entry_buffer_ticks = payload.entry_buffer_ticks
    current.stop_loss_buffer_ticks = payload.stop_loss_buffer_ticks
    current.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(current)
    return current


def generate_paper_trade_from_signal(db: Session, signal: TradingSignal) -> PaperTrade | None:
    existing = db.scalar(select(PaperTrade).where(PaperTrade.signal_id == signal.id).limit(1))
    if existing is not None:
        return existing

    if signal.entry_price is None or signal.stop_loss is None or signal.target is None:
        return None

    current_settings = ensure_settings(db)

    required_volume_ratio = (
        current_settings.buy_volume_multiplier if signal.action == "BUY" else current_settings.sell_volume_multiplier
    )
    if signal.volume_ratio is not None and signal.volume_ratio < required_volume_ratio:
        return PaperTrade(
            id=uuid.uuid4(),
            signal_id=signal.id,
            trigger_line_id=signal.trigger_line_id,
            exchange=signal.exchange,
            symbol=signal.symbol,
            action=signal.action,
            simulated_entry_price=signal.entry_price,
            simulated_stop_loss=signal.stop_loss,
            simulated_target=signal.target,
            quantity=0,
            capital_used=0.0,
            risk_amount=0.0,
            status="CANCELLED",
            entry_time=signal.created_at,
        )

    start_of_day = signal.created_at.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = signal.created_at.replace(hour=23, minute=59, second=59, microsecond=999999)
    day_trades = db.scalars(
        select(PaperTrade).where(PaperTrade.entry_time >= start_of_day, PaperTrade.entry_time <= end_of_day)
    ).all()

    if len(day_trades) >= current_settings.max_trades_per_day:
        return PaperTrade(
            id=uuid.uuid4(),
            signal_id=signal.id,
            trigger_line_id=signal.trigger_line_id,
            exchange=signal.exchange,
            symbol=signal.symbol,
            action=signal.action,
            simulated_entry_price=signal.entry_price,
            simulated_stop_loss=signal.stop_loss,
            simulated_target=signal.target,
            quantity=0,
            capital_used=0.0,
            risk_amount=0.0,
            status="CANCELLED",
            entry_time=signal.created_at,
        )

    realized_loss = sum(abs(trade.pnl or 0.0) for trade in day_trades if (trade.pnl or 0.0) < 0)
    if realized_loss >= current_settings.max_daily_loss:
        return PaperTrade(
            id=uuid.uuid4(),
            signal_id=signal.id,
            trigger_line_id=signal.trigger_line_id,
            exchange=signal.exchange,
            symbol=signal.symbol,
            action=signal.action,
            simulated_entry_price=signal.entry_price,
            simulated_stop_loss=signal.stop_loss,
            simulated_target=signal.target,
            quantity=0,
            capital_used=0.0,
            risk_amount=0.0,
            status="CANCELLED",
            entry_time=signal.created_at,
        )

    entry_buffered = signal.entry_price + current_settings.entry_buffer_ticks if signal.action == "BUY" else signal.entry_price - current_settings.entry_buffer_ticks
    stop_buffered = signal.stop_loss - current_settings.stop_loss_buffer_ticks if signal.action == "BUY" else signal.stop_loss + current_settings.stop_loss_buffer_ticks
    risk_per_share = abs(entry_buffered - stop_buffered) + current_settings.slippage_estimate
    if risk_per_share <= 0:
        return None

    quantity = 0
    if current_settings.default_quantity_mode == "FIXED" and current_settings.fixed_quantity:
        quantity = current_settings.fixed_quantity
    else:
        capital_cap = math.floor(current_settings.capital_per_trade / max(entry_buffered, 1))
        risk_cap = math.floor(current_settings.risk_per_trade / risk_per_share)
        positive_caps = [value for value in [capital_cap, risk_cap] if value > 0]
        quantity = min(positive_caps) if positive_caps else 0

    if quantity <= 0:
        return None

    capital_used = quantity * entry_buffered
    risk_amount = (risk_per_share * quantity) + current_settings.brokerage_estimate

    return PaperTrade(
        id=uuid.uuid4(),
        signal_id=signal.id,
        trigger_line_id=signal.trigger_line_id,
        exchange=signal.exchange,
        symbol=signal.symbol,
        action=signal.action,
        simulated_entry_price=entry_buffered,
        simulated_stop_loss=stop_buffered,
        simulated_target=signal.target,
        quantity=quantity,
        capital_used=capital_used,
        risk_amount=risk_amount,
        status="OPEN",
        entry_time=signal.created_at,
    )
