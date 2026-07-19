import logging
import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models import BrokerOrder, PaperTradingSetting, PositionSnapshot, TradingSignal


logger = logging.getLogger(__name__)
settings = get_settings()


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
                buy_volume_multiplier=settings.buy_volume_multiplier,
                sell_volume_multiplier=settings.sell_volume_multiplier,
                entry_buffer_ticks=settings.entry_buffer_ticks,
                stop_loss_buffer_ticks=settings.stop_buffer_ticks,
                daily_candle_lookback=settings.daily_candle_lookback,
                swing_window=settings.swing_window,
                max_gap_percent=settings.max_gap_percent,
                min_swing_distance=max(int(settings.min_swing_distance), 1),
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

        capital_used = quantity * entry_price
        risk_amount = (risk_per_share * quantity) + current_settings.brokerage_estimate
        return quantity, capital_used, risk_amount


class LiveExecutionService:
    def execute(self, db: Session, signal: TradingSignal) -> BrokerOrder:
        order = BrokerOrder(
            signal_id=signal.id,
            exchange=signal.exchange,
            symbol=signal.symbol,
            action=signal.action,
            quantity=signal.quantity,
            average_price=signal.entry_price,
            mode="LIVE" if settings.zerodha_live_trading_enabled else "PAPER",
            status="SKIPPED",
            request_payload={"reason": "live_trading_disabled_or_placeholder"},
            response_payload={"detail": "Zerodha live execution is feature-gated and intentionally not placing orders"},
        )
        db.add(order)
        db.flush()
        logger.info("Live execution placeholder recorded for signal %s", signal.id)
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
