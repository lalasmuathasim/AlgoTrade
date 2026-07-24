import math
import uuid
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import PaperTrade, PaperTradingSetting, TradingSignal
from backend.app.schemas import (
    ExecutionModeResponse,
    ExecutionRulesPayload,
    ExecutionRulesResponse,
    PaperTradingSettingsPayload,
    StrategySettingsPayload,
)
from backend.app.services.zerodha_sessions import get_current_zerodha_session


settings = get_settings()


def _coalesce(value, default):
    return default if value is None else value


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
        paper_trading_enabled=settings.paper_trading_enabled,
        live_trading_enabled=settings.zerodha_live_trading_enabled,
        require_candle_close_beyond_line=True,
        enable_breakout_quality=settings.enable_breakout_quality,
        minimum_close_position_percent=settings.minimum_close_position_percent,
        minimum_candle_body_percent=settings.minimum_candle_body_percent,
        maximum_rejection_wick_percent=settings.maximum_rejection_wick_percent,
        minimum_close_beyond_level_ticks=settings.minimum_close_beyond_level_ticks,
        require_volume_confirmation=settings.require_volume_confirmation,
        buy_volume_multiplier=settings.buy_volume_multiplier,
        sell_volume_multiplier=settings.sell_volume_multiplier,
        entry_buffer_ticks=settings.entry_buffer_ticks,
        stop_loss_buffer_ticks=settings.stop_buffer_ticks,
        target_mode="NEAREST_DAILY_SWING",
        fallback_risk_reward_ratio=2.0,
        use_nearest_daily_swing_target=True,
        minimum_reward_risk_ratio=1.0,
        order_type="LIMIT",
        product_type="MIS",
        reentry_cooldown_minutes=0,
        allow_repeat_entry_same_line=False,
        max_quantity_per_order=None,
        skip_zero_previous_volume=True,
        minimum_price=None,
        maximum_price=None,
        allowed_exchanges=["NSE", "BSE"],
        daily_candle_lookback=settings.daily_candle_lookback,
        swing_window=settings.swing_window,
        max_gap_percent=settings.max_gap_percent,
        min_swing_distance=max(int(settings.min_swing_distance), 1),
        daily_structure_rebuild_enabled=True,
        daily_structure_rebuild_time=settings.daily_scan_time,
        prediction_proximity_percent=2.0,
        max_open_positions=3,
        max_loss_per_symbol_per_day=2500.0,
        block_new_trades_after_max_daily_loss=True,
        no_trade_after_time="15:00",
        market_hours_guard=True,
        exchange_charges_estimate=0.0,
        use_cost_adjusted_pnl=True,
        enable_confidence_filter=False,
        minimum_confidence_score=0.6,
        confidence_source="RULES_ONLY",
        allow_low_confidence_paper_trades_only=True,
        block_live_trades_below_confidence_threshold=True,
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
        paper_trading_enabled=defaults.paper_trading_enabled,
        live_trading_enabled=defaults.live_trading_enabled,
        require_candle_close_beyond_line=defaults.require_candle_close_beyond_line,
        enable_breakout_quality=defaults.enable_breakout_quality,
        minimum_close_position_percent=defaults.minimum_close_position_percent,
        minimum_candle_body_percent=defaults.minimum_candle_body_percent,
        maximum_rejection_wick_percent=defaults.maximum_rejection_wick_percent,
        minimum_close_beyond_level_ticks=defaults.minimum_close_beyond_level_ticks,
        require_volume_confirmation=defaults.require_volume_confirmation,
        buy_volume_multiplier=defaults.buy_volume_multiplier,
        sell_volume_multiplier=defaults.sell_volume_multiplier,
        entry_buffer_ticks=defaults.entry_buffer_ticks,
        stop_loss_buffer_ticks=defaults.stop_loss_buffer_ticks,
        target_mode=defaults.target_mode,
        fallback_risk_reward_ratio=defaults.fallback_risk_reward_ratio,
        use_nearest_daily_swing_target=defaults.use_nearest_daily_swing_target,
        minimum_reward_risk_ratio=defaults.minimum_reward_risk_ratio,
        order_type=defaults.order_type,
        product_type=defaults.product_type,
        reentry_cooldown_minutes=defaults.reentry_cooldown_minutes,
        allow_repeat_entry_same_line=defaults.allow_repeat_entry_same_line,
        max_quantity_per_order=defaults.max_quantity_per_order,
        skip_zero_previous_volume=defaults.skip_zero_previous_volume,
        minimum_price=defaults.minimum_price,
        maximum_price=defaults.maximum_price,
        allowed_exchanges=defaults.allowed_exchanges,
        daily_candle_lookback=defaults.daily_candle_lookback,
        swing_window=defaults.swing_window,
        max_gap_percent=defaults.max_gap_percent,
        min_swing_distance=defaults.min_swing_distance,
        daily_structure_rebuild_enabled=defaults.daily_structure_rebuild_enabled,
        daily_structure_rebuild_time=defaults.daily_structure_rebuild_time,
        prediction_proximity_percent=defaults.prediction_proximity_percent,
        max_open_positions=defaults.max_open_positions,
        max_loss_per_symbol_per_day=defaults.max_loss_per_symbol_per_day,
        block_new_trades_after_max_daily_loss=defaults.block_new_trades_after_max_daily_loss,
        no_trade_after_time=defaults.no_trade_after_time,
        market_hours_guard=defaults.market_hours_guard,
        exchange_charges_estimate=defaults.exchange_charges_estimate,
        use_cost_adjusted_pnl=defaults.use_cost_adjusted_pnl,
        enable_confidence_filter=defaults.enable_confidence_filter,
        minimum_confidence_score=defaults.minimum_confidence_score,
        confidence_source=defaults.confidence_source,
        allow_low_confidence_paper_trades_only=defaults.allow_low_confidence_paper_trades_only,
        block_live_trades_below_confidence_threshold=defaults.block_live_trades_below_confidence_threshold,
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
    current.paper_trading_enabled = payload.paper_trading_enabled
    current.live_trading_enabled = payload.live_trading_enabled
    current.require_candle_close_beyond_line = payload.require_candle_close_beyond_line
    current.enable_breakout_quality = payload.enable_breakout_quality
    current.minimum_close_position_percent = payload.minimum_close_position_percent
    current.minimum_candle_body_percent = payload.minimum_candle_body_percent
    current.maximum_rejection_wick_percent = payload.maximum_rejection_wick_percent
    current.minimum_close_beyond_level_ticks = payload.minimum_close_beyond_level_ticks
    current.require_volume_confirmation = payload.require_volume_confirmation
    current.buy_volume_multiplier = payload.buy_volume_multiplier
    current.sell_volume_multiplier = payload.sell_volume_multiplier
    current.entry_buffer_ticks = payload.entry_buffer_ticks
    current.stop_loss_buffer_ticks = payload.stop_loss_buffer_ticks
    current.target_mode = payload.target_mode
    current.fallback_risk_reward_ratio = payload.fallback_risk_reward_ratio
    current.use_nearest_daily_swing_target = payload.use_nearest_daily_swing_target
    current.minimum_reward_risk_ratio = payload.minimum_reward_risk_ratio
    current.order_type = payload.order_type
    current.product_type = payload.product_type
    current.reentry_cooldown_minutes = payload.reentry_cooldown_minutes
    current.allow_repeat_entry_same_line = payload.allow_repeat_entry_same_line
    current.max_quantity_per_order = payload.max_quantity_per_order
    current.skip_zero_previous_volume = payload.skip_zero_previous_volume
    current.minimum_price = payload.minimum_price
    current.maximum_price = payload.maximum_price
    current.allowed_exchanges = payload.allowed_exchanges
    current.daily_candle_lookback = payload.daily_candle_lookback
    current.swing_window = payload.swing_window
    current.max_gap_percent = payload.max_gap_percent
    current.min_swing_distance = payload.min_swing_distance
    current.daily_structure_rebuild_enabled = payload.daily_structure_rebuild_enabled
    current.daily_structure_rebuild_time = payload.daily_structure_rebuild_time
    current.prediction_proximity_percent = payload.prediction_proximity_percent
    current.max_open_positions = payload.max_open_positions
    current.max_loss_per_symbol_per_day = payload.max_loss_per_symbol_per_day
    current.block_new_trades_after_max_daily_loss = payload.block_new_trades_after_max_daily_loss
    current.no_trade_after_time = payload.no_trade_after_time
    current.market_hours_guard = payload.market_hours_guard
    current.exchange_charges_estimate = payload.exchange_charges_estimate
    current.use_cost_adjusted_pnl = payload.use_cost_adjusted_pnl
    current.enable_confidence_filter = payload.enable_confidence_filter
    current.minimum_confidence_score = payload.minimum_confidence_score
    current.confidence_source = payload.confidence_source
    current.allow_low_confidence_paper_trades_only = payload.allow_low_confidence_paper_trades_only
    current.block_live_trades_below_confidence_threshold = payload.block_live_trades_below_confidence_threshold
    current.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(current)
    return current


def get_execution_mode_payload(db: Session) -> ExecutionModeResponse:
    current = ensure_settings(db)
    zerodha_session = get_current_zerodha_session(db)
    return ExecutionModeResponse(
        paper_trading_enabled=current.paper_trading_enabled,
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


def get_execution_rules_payload(db: Session) -> ExecutionRulesResponse:
    current = ensure_settings(db)
    return ExecutionRulesResponse.model_validate(current, from_attributes=True)


def update_execution_rules(db: Session, payload: ExecutionRulesPayload) -> PaperTradingSetting:
    current = ensure_settings(db)
    current.paper_trading_enabled = payload.paper_trading_enabled
    current.live_trading_enabled = payload.live_trading_enabled
    current.require_candle_close_beyond_line = payload.require_candle_close_beyond_line
    current.enable_breakout_quality = payload.enable_breakout_quality
    current.minimum_close_position_percent = payload.minimum_close_position_percent
    current.minimum_candle_body_percent = payload.minimum_candle_body_percent
    current.maximum_rejection_wick_percent = payload.maximum_rejection_wick_percent
    current.minimum_close_beyond_level_ticks = payload.minimum_close_beyond_level_ticks
    current.require_volume_confirmation = payload.require_volume_confirmation
    current.entry_buffer_ticks = payload.entry_buffer_ticks
    current.stop_loss_buffer_ticks = payload.stop_loss_buffer_ticks
    current.target_mode = payload.target_mode
    current.fallback_risk_reward_ratio = payload.fallback_risk_reward_ratio
    current.use_nearest_daily_swing_target = payload.use_nearest_daily_swing_target
    current.minimum_reward_risk_ratio = payload.minimum_reward_risk_ratio
    current.order_type = payload.order_type
    current.product_type = payload.product_type
    current.reentry_cooldown_minutes = payload.reentry_cooldown_minutes
    current.allow_repeat_entry_same_line = payload.allow_repeat_entry_same_line
    current.default_quantity_mode = payload.default_quantity_mode
    current.fixed_quantity = payload.fixed_quantity
    current.capital_per_trade = payload.capital_per_trade
    current.risk_per_trade = payload.risk_per_trade
    current.max_quantity_per_order = payload.max_quantity_per_order
    current.buy_volume_multiplier = payload.buy_volume_multiplier
    current.sell_volume_multiplier = payload.sell_volume_multiplier
    current.skip_zero_previous_volume = payload.skip_zero_previous_volume
    current.minimum_price = payload.minimum_price
    current.maximum_price = payload.maximum_price
    current.allowed_exchanges = payload.allowed_exchanges
    current.max_trades_per_day = payload.max_trades_per_day
    current.max_open_positions = payload.max_open_positions
    current.max_daily_loss = payload.max_daily_loss
    current.max_loss_per_symbol_per_day = payload.max_loss_per_symbol_per_day
    current.block_new_trades_after_max_daily_loss = payload.block_new_trades_after_max_daily_loss
    current.no_trade_after_time = payload.no_trade_after_time
    current.market_hours_guard = payload.market_hours_guard
    current.brokerage_estimate = payload.brokerage_estimate
    current.slippage_estimate = payload.slippage_estimate
    current.exchange_charges_estimate = payload.exchange_charges_estimate
    current.use_cost_adjusted_pnl = payload.use_cost_adjusted_pnl
    current.enable_confidence_filter = payload.enable_confidence_filter
    current.minimum_confidence_score = payload.minimum_confidence_score
    current.confidence_source = payload.confidence_source
    current.allow_low_confidence_paper_trades_only = payload.allow_low_confidence_paper_trades_only
    current.block_live_trades_below_confidence_threshold = payload.block_live_trades_below_confidence_threshold
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
        daily_structure_rebuild_enabled=current.daily_structure_rebuild_enabled,
        daily_structure_rebuild_time=current.daily_structure_rebuild_time,
        prediction_proximity_percent=current.prediction_proximity_percent,
        entry_buffer_ticks=current.entry_buffer_ticks,
        stop_loss_buffer_ticks=current.stop_loss_buffer_ticks,
    )


def update_strategy_settings(db: Session, payload: StrategySettingsPayload) -> PaperTradingSetting:
    current = ensure_settings(db)
    current.daily_candle_lookback = payload.daily_candle_lookback
    current.swing_window = payload.swing_window
    current.max_gap_percent = payload.max_gap_percent
    current.min_swing_distance = payload.min_swing_distance
    current.daily_structure_rebuild_enabled = payload.daily_structure_rebuild_enabled
    current.daily_structure_rebuild_time = payload.daily_structure_rebuild_time
    current.prediction_proximity_percent = payload.prediction_proximity_percent
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
    if not bool(_coalesce(getattr(current_settings, "paper_trading_enabled", None), True)):
        return None

    required_volume_ratio = (
        current_settings.buy_volume_multiplier if signal.action == "BUY" else current_settings.sell_volume_multiplier
    )
    if bool(_coalesce(getattr(current_settings, "require_volume_confirmation", None), True)) and signal.volume_ratio is not None and signal.volume_ratio < required_volume_ratio:
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
    open_trades = [trade for trade in day_trades if trade.status == "OPEN"]

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

    if len(open_trades) >= max(int(_coalesce(getattr(current_settings, "max_open_positions", None), 3)), 1):
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
    block_daily_loss = bool(_coalesce(getattr(current_settings, "block_new_trades_after_max_daily_loss", None), True))
    if block_daily_loss and realized_loss >= current_settings.max_daily_loss:
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

    symbol_realized_loss = sum(
        abs(trade.pnl or 0.0)
        for trade in day_trades
        if trade.symbol == signal.symbol and (trade.pnl or 0.0) < 0
    )
    symbol_loss_cap = float(_coalesce(getattr(current_settings, "max_loss_per_symbol_per_day", None), current_settings.risk_per_trade))
    if symbol_realized_loss >= symbol_loss_cap:
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

    max_quantity_per_order = _coalesce(getattr(current_settings, "max_quantity_per_order", None), None)
    if max_quantity_per_order:
        quantity = min(quantity, max_quantity_per_order)

    if quantity <= 0:
        return None

    capital_used = quantity * entry_buffered
    total_costs = current_settings.brokerage_estimate
    if bool(_coalesce(getattr(current_settings, "use_cost_adjusted_pnl", None), True)):
        total_costs += float(_coalesce(getattr(current_settings, "exchange_charges_estimate", None), 0.0))
    risk_amount = (risk_per_share * quantity) + total_costs

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
        execution_mode="PAPER",
        status="OPEN",
        entry_time=signal.created_at,
    )
