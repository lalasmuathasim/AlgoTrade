import logging
import math
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import BrokerOrder, PaperTradingSetting, PositionSnapshot, TradingSignal
from backend.app.services.paper_trading_service import ensure_settings
from backend.app.services.zerodha import ZerodhaApiClient, ZerodhaAuthService
from backend.app.services.zerodha_sessions import get_current_zerodha_access_token


logger = logging.getLogger(__name__)
settings = get_settings()


def _coalesce(value, default):
    return default if value is None else value


class RiskEngine:
    def compute(self, db: Session, action: str, entry_price: float, stop_loss: float) -> tuple[int, float, float]:
        current_settings = db.scalar(select(PaperTradingSetting).order_by(desc(PaperTradingSetting.updated_at)).limit(1))
        if current_settings is None:
            current_settings = PaperTradingSetting(
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
                trading_timezone=settings.market_timezone,
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
            db.add(current_settings)
            db.flush()

        risk_per_share = abs(entry_price - stop_loss) + current_settings.slippage_estimate
        if risk_per_share <= 0:
            return 0, 0.0, 0.0

        if current_settings.default_quantity_mode == "FIXED" and current_settings.fixed_quantity:
            quantity = current_settings.fixed_quantity
        else:
            capital_cap = math.floor(current_settings.capital_per_trade / max(entry_price, 1))
            risk_cap = math.floor(current_settings.risk_per_trade / risk_per_share)
            positive_caps = [value for value in [capital_cap, risk_cap] if value > 0]
            quantity = min(positive_caps) if positive_caps else 0

        max_quantity_per_order = _coalesce(getattr(current_settings, "max_quantity_per_order", None), None)
        if max_quantity_per_order:
            quantity = min(quantity, max_quantity_per_order)

        capital_used = quantity * entry_price
        total_costs = current_settings.brokerage_estimate
        if bool(_coalesce(getattr(current_settings, "use_cost_adjusted_pnl", None), True)):
            total_costs += float(_coalesce(getattr(current_settings, "exchange_charges_estimate", None), 0.0))
        risk_amount = (risk_per_share * quantity) + total_costs
        return quantity, capital_used, risk_amount


class LiveExecutionService:
    def execute(self, db: Session, signal: TradingSignal) -> BrokerOrder:
        runtime_settings = ensure_settings(db)
        if not runtime_settings.live_trading_enabled:
            order = BrokerOrder(
                signal_id=signal.id,
                exchange=signal.exchange,
                symbol=signal.symbol,
                action=signal.action,
                quantity=signal.quantity,
                average_price=signal.entry_price,
                mode="PAPER",
                status="SKIPPED",
                request_payload={"reason": "runtime_live_trading_disabled"},
                response_payload={"detail": "Live Zerodha execution is disabled in configuration"},
            )
            db.add(order)
            db.flush()
            return order

        confidence_score = None
        if isinstance(signal.raw_payload, dict):
            confidence_score = signal.raw_payload.get("confidence_score")
        if (
            bool(getattr(runtime_settings, "enable_confidence_filter", False))
            and bool(_coalesce(getattr(runtime_settings, "block_live_trades_below_confidence_threshold", None), True))
            and confidence_score is not None
            and float(confidence_score) < float(_coalesce(getattr(runtime_settings, "minimum_confidence_score", None), 0.6))
        ):
            order = BrokerOrder(
                signal_id=signal.id,
                exchange=signal.exchange,
                symbol=signal.symbol,
                action=signal.action,
                quantity=signal.quantity,
                average_price=signal.entry_price,
                mode="LIVE",
                status="REJECTED",
                request_payload={"reason": "confidence_threshold_blocked"},
                response_payload={"detail": "Live order blocked by confidence threshold"},
            )
            db.add(order)
            db.flush()
            return order

        if signal.quantity is None or signal.quantity <= 0 or signal.entry_price is None:
            order = BrokerOrder(
                signal_id=signal.id,
                exchange=signal.exchange,
                symbol=signal.symbol,
                action=signal.action,
                quantity=signal.quantity,
                average_price=signal.entry_price,
                mode="LIVE",
                status="REJECTED",
                request_payload={"reason": "invalid_signal_payload"},
                response_payload={"detail": "Signal is missing quantity or entry price for live order placement"},
            )
            db.add(order)
            db.flush()
            return order

        access_token = get_current_zerodha_access_token(db)
        if not access_token:
            order = BrokerOrder(
                signal_id=signal.id,
                exchange=signal.exchange,
                symbol=signal.symbol,
                action=signal.action,
                quantity=signal.quantity,
                average_price=signal.entry_price,
                mode="LIVE",
                status="REJECTED",
                request_payload={"reason": "missing_zerodha_access_token"},
                response_payload={"detail": "No active Zerodha access token is available for live order placement"},
            )
            db.add(order)
            db.flush()
            return order

        request_payload = {
            "exchange": signal.exchange,
            "tradingsymbol": signal.symbol,
            "transaction_type": signal.action,
            "quantity": signal.quantity,
            "order_type": _coalesce(getattr(runtime_settings, "order_type", None), "LIMIT"),
            "product": _coalesce(getattr(runtime_settings, "product_type", None), "MIS"),
            "price": signal.entry_price,
            "validity": "DAY",
            "tag": "QUBITX",
            "trigger_price": signal.trigger_price,
            "stop_loss": signal.stop_loss,
            "target": signal.target,
        }

        try:
            response_payload = ZerodhaApiClient(
                auth_service=ZerodhaAuthService(),
                access_token=access_token,
            ).place_regular_order(
                exchange=signal.exchange,
                tradingsymbol=signal.symbol,
                transaction_type=signal.action,
                quantity=signal.quantity,
                order_type=_coalesce(getattr(runtime_settings, "order_type", None), "LIMIT"),
                product=_coalesce(getattr(runtime_settings, "product_type", None), "MIS"),
                price=signal.entry_price,
                validity="DAY",
                tag="QUBITX",
            )
        except httpx.HTTPError as exc:
            logger.exception("Zerodha live order placement failed for signal %s", signal.id)
            raise RuntimeError("Zerodha live order placement failed") from exc

        order = BrokerOrder(
            signal_id=signal.id,
            broker_order_id=response_payload.get("order_id"),
            exchange=signal.exchange,
            symbol=signal.symbol,
            action=signal.action,
            quantity=signal.quantity,
            average_price=signal.entry_price,
            mode="LIVE",
            status="PLACED",
            request_payload=request_payload,
            response_payload=response_payload,
        )
        db.add(order)
        db.flush()
        logger.info("Placed Zerodha live order %s for signal %s", order.broker_order_id, signal.id)
        return order


class OrderReconciliationService:
    def reconcile(
        self,
        db: Session,
        orders: list[dict[str, Any]] | None = None,
        positions: list[dict[str, Any]] | None = None,
    ) -> tuple[int, int]:
        order_count = 0
        position_count = 0

        for row in orders or []:
            db.add(
                BrokerOrder(
                    signal_id=row.get("signal_id"),
                    broker_order_id=row.get("broker_order_id"),
                    exchange=row.get("exchange", "NSE"),
                    symbol=row["symbol"],
                    action=row["action"],
                    quantity=row.get("quantity"),
                    average_price=row.get("average_price"),
                    mode=row.get("mode", "LIVE"),
                    status=row.get("status", "UNKNOWN"),
                    request_payload=row.get("request_payload"),
                    response_payload=row.get("response_payload"),
                )
            )
            order_count += 1

        for row in positions or []:
            db.add(
                PositionSnapshot(
                    source=row.get("source", "ZERODHA"),
                    exchange=row.get("exchange", "NSE"),
                    symbol=row["symbol"],
                    quantity=row.get("quantity", 0),
                    average_price=row.get("average_price"),
                    pnl=row.get("pnl"),
                    raw_payload=row,
                    captured_at=row.get("captured_at", datetime.now(UTC)),
                )
            )
            position_count += 1

        db.flush()
        return order_count, position_count
