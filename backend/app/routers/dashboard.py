from collections import defaultdict
from datetime import UTC, date, datetime
from statistics import mean
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.dependencies import require_approved_user
from backend.app.database import get_db
from backend.app.models import BreakoutEvent, PaperTrade, TradingSignal, TriggerLine, Watchlist, WatchlistSymbol


router = APIRouter(tags=["dashboard"], dependencies=[Depends(require_approved_user)])


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _serialize_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _paper_trade_summary(trades: list[PaperTrade]) -> dict:
    total_trades = len(trades)
    open_trades = sum(1 for trade in trades if trade.status == "OPEN")
    closed_trades_list = [trade for trade in trades if trade.status != "OPEN"]
    closed_trades = len(closed_trades_list)
    winners = [trade for trade in closed_trades_list if (trade.pnl or 0.0) > 0]
    losers = [trade for trade in closed_trades_list if (trade.pnl or 0.0) < 0]
    total_pnl = round(sum(trade.pnl or 0.0 for trade in trades), 2)
    average_profit = round(mean([trade.pnl for trade in winners]), 2) if winners else 0.0
    average_loss = round(mean([trade.pnl for trade in losers]), 2) if losers else 0.0
    gross_profit = sum(trade.pnl or 0.0 for trade in winners)
    gross_loss = abs(sum(trade.pnl or 0.0 for trade in losers))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss else None
    win_rate = round((len(winners) / closed_trades) * 100, 2) if closed_trades else 0.0

    return {
        "total_trades": total_trades,
        "open_trades": open_trades,
        "closed_trades": closed_trades,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "average_profit": average_profit,
        "average_loss": average_loss,
        "profit_factor": profit_factor,
    }


def _serialize_trigger_line(line: TriggerLine) -> dict:
    return {
        "id": str(line.id),
        "watchlist_id": str(line.watchlist_id) if line.watchlist_id else None,
        "exchange": line.exchange,
        "symbol": line.symbol,
        "line_type": line.line_type,
        "line_price": line.line_price,
        "line_status": line.line_status,
        "line_drawn_date": _serialize_date(line.line_drawn_date),
        "source_timeframe": line.source_timeframe,
        "lookback_candles": line.lookback_candles,
        "max_gap_percent_used": line.max_gap_percent_used,
        "min_swing_distance_used": line.min_swing_distance_used,
        "swing_high_1_price": line.swing_high_1_price,
        "swing_high_1_date": _serialize_date(line.swing_high_1_date),
        "swing_high_2_price": line.swing_high_2_price,
        "swing_high_2_date": _serialize_date(line.swing_high_2_date),
        "higher_swing_high_price": line.higher_swing_high_price,
        "lower_swing_high_price": line.lower_swing_high_price,
        "swing_low_1_price": line.swing_low_1_price,
        "swing_low_1_date": _serialize_date(line.swing_low_1_date),
        "swing_low_2_price": line.swing_low_2_price,
        "swing_low_2_date": _serialize_date(line.swing_low_2_date),
        "lower_swing_low_price": line.lower_swing_low_price,
        "higher_swing_low_price": line.higher_swing_low_price,
        "swing_gap_percent": line.swing_gap_percent,
        "nearest_daily_swing_high_target": line.nearest_daily_swing_high_target,
        "nearest_daily_swing_low_target": line.nearest_daily_swing_low_target,
        "created_at": _serialize_datetime(line.created_at),
        "updated_at": _serialize_datetime(line.updated_at),
    }


def _serialize_breakout_event(event: BreakoutEvent) -> dict:
    return {
        "id": str(event.id),
        "trigger_line_id": str(event.trigger_line_id) if event.trigger_line_id else None,
        "exchange": event.exchange,
        "symbol": event.symbol,
        "event_type": event.event_type,
        "event_time": _serialize_datetime(event.event_time),
        "breakout_or_breakdown_price": event.breakout_or_breakdown_price,
        "breakout_candle_high": event.breakout_candle_high,
        "breakout_candle_low": event.breakout_candle_low,
        "breakout_candle_volume": event.breakout_candle_volume,
        "previous_candle_volume": event.previous_candle_volume,
        "volume_ratio": event.volume_ratio,
        "volume_condition_required": event.volume_condition_required,
        "volume_condition_passed": event.volume_condition_passed,
        "entry_price": event.entry_price,
        "stop_loss": event.stop_loss,
        "target": event.target,
        "status": event.status,
        "created_at": _serialize_datetime(event.created_at),
    }


def _serialize_signal(signal: TradingSignal) -> dict:
    return {
        "id": str(signal.id),
        "exchange": signal.exchange,
        "symbol": signal.symbol,
        "action": signal.action,
        "source": signal.source,
        "watchlist_id": str(signal.watchlist_id) if signal.watchlist_id else None,
        "trigger_line_id": str(signal.trigger_line_id) if signal.trigger_line_id else None,
        "breakout_event_id": str(signal.breakout_event_id) if signal.breakout_event_id else None,
        "scan_execution_id": str(signal.scan_execution_id) if signal.scan_execution_id else None,
        "trigger_price": signal.trigger_price,
        "entry_price": signal.entry_price,
        "stop_loss": signal.stop_loss,
        "target": signal.target,
        "quantity": signal.quantity,
        "capital_used": signal.capital_used,
        "risk_amount": signal.risk_amount,
        "volume_ratio": signal.volume_ratio,
        "timeframe": signal.timeframe,
        "strategy": signal.strategy,
        "dedupe_key": signal.dedupe_key,
        "status": signal.status,
        "notification_status": signal.notification_status,
        "processed_at": _serialize_datetime(signal.processed_at),
        "created_at": _serialize_datetime(signal.created_at),
    }


def _serialize_paper_trade(trade: PaperTrade) -> dict:
    return {
        "id": str(trade.id),
        "signal_id": str(trade.signal_id) if trade.signal_id else None,
        "trigger_line_id": str(trade.trigger_line_id) if trade.trigger_line_id else None,
        "exchange": trade.exchange,
        "symbol": trade.symbol,
        "action": trade.action,
        "simulated_entry_price": trade.simulated_entry_price,
        "simulated_stop_loss": trade.simulated_stop_loss,
        "simulated_target": trade.simulated_target,
        "quantity": trade.quantity,
        "capital_used": trade.capital_used,
        "risk_amount": trade.risk_amount,
        "status": trade.status,
        "simulated_exit_price": trade.simulated_exit_price,
        "pnl": trade.pnl,
        "pnl_percent": trade.pnl_percent,
        "entry_time": _serialize_datetime(trade.entry_time),
        "exit_time": _serialize_datetime(trade.exit_time),
        "created_at": _serialize_datetime(trade.created_at),
    }


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_home() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Qubitx Dashboard</title>
  <style>
    :root {
      --bg: #f3efe5;
      --panel: rgba(255,255,255,0.72);
      --line: #1e3a34;
      --muted: #52625e;
      --accent: #ad5c2b;
      --ok: #0f766e;
      --warn: #b45309;
      --danger: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(173,92,43,0.18), transparent 28%),
        linear-gradient(135deg, #ede4d3 0%, #f6f1e8 42%, #ecf4ef 100%);
      color: var(--line);
      min-height: 100vh;
    }
    .wrap { max-width: 1280px; margin: 0 auto; padding: 28px 20px 48px; }
    .hero {
      background: linear-gradient(135deg, rgba(30,58,52,0.94), rgba(18,25,24,0.94));
      color: #f7f1e7;
      padding: 28px;
      border-radius: 22px;
      box-shadow: 0 20px 50px rgba(30,58,52,0.18);
    }
    .hero h1 {
      margin: 0 0 10px;
      font-size: clamp(2rem, 3vw, 3rem);
      font-family: "Baskerville", "Palatino Linotype", serif;
    }
    .hero p { margin: 0; color: rgba(247,241,231,0.84); max-width: 760px; line-height: 1.5; }
    .hero-top {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      flex-wrap: wrap;
    }
    .hero-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }
    .hero-actions button, .hero-actions a, .action-button {
      border: none;
      text-decoration: none;
      cursor: pointer;
      border-radius: 999px;
      padding: 10px 14px;
      font-weight: 700;
      font-size: 0.92rem;
      transition: opacity 0.16s ease, transform 0.16s ease;
    }
    .hero-actions a {
      background: rgba(255,255,255,0.09);
      color: #f7f1e7;
    }
    .hero-actions button, .action-button.primary {
      background: #f7f1e7;
      color: #16332f;
    }
    .action-button.ghost {
      background: rgba(22,51,47,0.08);
      color: var(--line);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin: 22px 0;
    }
    .card, .panel {
      background: var(--panel);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(30,58,52,0.12);
      border-radius: 18px;
      box-shadow: 0 10px 24px rgba(44,54,49,0.08);
    }
    .card { padding: 18px; }
    .card .label { font-size: 0.85rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }
    .card .value { font-size: 2rem; margin-top: 10px; }
    .layout {
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 18px;
    }
    .security-grid {
      display: grid;
      grid-template-columns: 0.95fr 1.05fr;
      gap: 18px;
      margin-bottom: 18px;
    }
    .panel { padding: 18px; overflow: auto; }
    .panel h2 { margin: 0 0 12px; font-size: 1.2rem; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid rgba(30,58,52,0.1); font-size: 0.95rem; }
    th { color: var(--muted); font-weight: 600; }
    .badge {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      background: rgba(15,118,110,0.12);
      color: var(--ok);
      font-size: 0.8rem;
    }
    .badge.warn {
      background: rgba(180,83,9,0.12);
      color: var(--warn);
    }
    .badge.danger {
      background: rgba(180,35,24,0.12);
      color: var(--danger);
    }
    .links { margin-top: 16px; display: flex; flex-wrap: wrap; gap: 10px; }
    .links a {
      color: var(--accent);
      text-decoration: none;
      border-bottom: 1px solid rgba(173,92,43,0.3);
    }
    .status-box {
      min-height: 52px;
      border-radius: 16px;
      border: 1px solid rgba(30,58,52,0.1);
      background: rgba(255,255,255,0.62);
      padding: 12px 14px;
      color: var(--muted);
      margin-bottom: 12px;
    }
    .status-box.success { color: var(--ok); }
    .status-box.error { color: var(--danger); }
    .field { margin-bottom: 12px; }
    label {
      display: block;
      font-size: 0.84rem;
      color: var(--muted);
      margin-bottom: 6px;
      font-weight: 600;
    }
    input {
      width: 100%;
      border-radius: 12px;
      border: 1px solid rgba(30,58,52,0.14);
      padding: 12px 13px;
      font-size: 0.95rem;
      background: rgba(255,255,255,0.85);
      color: var(--line);
    }
    .stack { display: grid; gap: 10px; }
    .inline { display: flex; flex-wrap: wrap; gap: 10px; }
    .hidden { display: none; }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      word-break: break-all;
    }
    .pending-empty {
      color: var(--muted);
      font-style: italic;
      padding: 10px 0 2px;
    }
    @media (max-width: 900px) {
      .layout, .security-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="hero-top">
        <div>
          <h1>Qubitx Trading Dashboard</h1>
          <p>Study watchlists, Zerodha-native trigger structures, market breakouts, generated signals, and paper-trading performance from a protected control center built for staged live execution.</p>
        </div>
        <div class="hero-actions">
          <a href="/">Landing Page</a>
          <button id="logoutButton" type="button">Log Out</button>
        </div>
      </div>
      <div class="links">
        <a href="/dashboard/watchlists">Watchlist Summary API</a>
        <a href="/dashboard/trigger-lines">Trigger Lines API</a>
        <a href="/dashboard/breakout-events">Breakout Events API</a>
        <a href="/dashboard/paper-trades">Paper Trades API</a>
        <a href="/paper-trading/settings">Paper Settings API</a>
      </div>
    </section>
    <section class="grid" id="summaryCards"></section>
    <section class="security-grid">
      <div class="panel">
        <h2>Account Security</h2>
        <div id="accountStatus" class="status-box">Loading account details...</div>
        <div class="stack">
          <div id="twoFactorStatus"></div>
          <div class="inline">
            <button id="setup2faButton" class="action-button primary" type="button">Generate 2FA Secret</button>
            <button id="disable2faButton" class="action-button ghost" type="button">Disable 2FA</button>
          </div>
        </div>
        <div id="twoFactorSetupPanel" class="hidden" style="margin-top: 14px;">
          <div class="field">
            <label>Authenticator secret</label>
            <div id="twoFactorSecret" class="status-box mono"></div>
          </div>
          <div class="field">
            <label>Provisioning URI</label>
            <div id="twoFactorUri" class="status-box mono"></div>
          </div>
          <div class="field">
            <label for="enable2faCode">Verification code</label>
            <input id="enable2faCode" type="text" inputmode="numeric" maxlength="6" placeholder="123456" />
          </div>
          <button id="enable2faButton" class="action-button primary" type="button">Enable 2FA</button>
        </div>
        <div id="disable2faPanel" class="hidden" style="margin-top: 14px;">
          <div class="field">
            <label for="disablePassword">Password</label>
            <input id="disablePassword" type="password" autocomplete="current-password" />
          </div>
          <div class="field">
            <label for="disableCode">Current 2FA code</label>
            <input id="disableCode" type="text" inputmode="numeric" maxlength="6" placeholder="123456" />
          </div>
          <button id="confirmDisable2faButton" class="action-button ghost" type="button">Confirm Disable</button>
        </div>
      </div>
      <div class="panel">
        <h2>Admin Approvals</h2>
        <div id="adminStatus" class="status-box">Loading role-specific tools...</div>
        <div id="pendingUsersContainer" class="hidden">
          <table id="pendingUsersTable"></table>
          <div id="pendingUsersEmpty" class="pending-empty hidden">No pending signups right now.</div>
        </div>
      </div>
    </section>
    <section class="layout">
      <div class="panel">
        <h2>Watchlists</h2>
        <table id="watchlistsTable"></table>
      </div>
      <div class="panel">
        <h2>Paper Trading Summary</h2>
        <table id="paperTable"></table>
      </div>
    </section>
    <section class="panel" style="margin-top: 18px;">
      <h2>Active Trigger Lines</h2>
      <table id="linesTable"></table>
    </section>
  </div>
  <script>
    async function loadJson(url) {
      const res = await fetch(url);
      if (!res.ok) {
        throw new Error((await res.json()).detail || "Request failed");
      }
      return res.json();
    }
    async function sendJson(url, method, payload) {
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: payload ? JSON.stringify(payload) : undefined,
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || data.message || "Request failed");
      }
      return data;
    }
    function renderCards(stats) {
      const cards = [
        ["Watchlists", stats.watchlists],
        ["Active Lines", stats.activeLines],
        ["Triggered Lines", stats.triggeredLines],
        ["Paper PnL", stats.totalPnl.toFixed(2)],
      ];
      document.getElementById("summaryCards").innerHTML = cards.map(([label, value]) => `
        <article class="card">
          <div class="label">${label}</div>
          <div class="value">${value}</div>
        </article>
      `).join("");
    }
    function renderTable(el, headers, rows) {
      const head = `<tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr>`;
      const body = rows.map(row => `<tr>${row.map(cell => `<td>${cell ?? ""}</td>`).join("")}</tr>`).join("");
      el.innerHTML = `<thead>${head}</thead><tbody>${body}</tbody>`;
    }
    function setBox(id, message, tone = "") {
      const el = document.getElementById(id);
      el.textContent = message;
      el.className = `status-box ${tone}`;
    }
    function setTwoFactorState(user, setup) {
      const tone = user.two_factor_enabled ? "success" : "";
      const badgeClass = user.two_factor_enabled ? "badge" : "badge warn";
      document.getElementById("twoFactorStatus").innerHTML = `
        <span class="${badgeClass}">${user.two_factor_enabled ? "2FA ENABLED" : "2FA OPTIONAL"}</span>
      `;
      if (setup) {
        document.getElementById("twoFactorSetupPanel").classList.remove("hidden");
        document.getElementById("twoFactorSecret").textContent = setup.secret;
        document.getElementById("twoFactorUri").textContent = setup.provisioning_uri;
      }
      setBox("accountStatus", `${user.email} · role ${user.role} · approval ${user.approval_status}`, tone);
    }
    async function loadPendingUsers() {
      try {
        const users = await loadJson("/admin/users/pending");
        document.getElementById("pendingUsersContainer").classList.remove("hidden");
        if (!users.length) {
          document.getElementById("pendingUsersTable").innerHTML = "";
          document.getElementById("pendingUsersEmpty").classList.remove("hidden");
          setBox("adminStatus", "Admin access active. No pending approvals at the moment.", "success");
          return;
        }
        document.getElementById("pendingUsersEmpty").classList.add("hidden");
        renderTable(
          document.getElementById("pendingUsersTable"),
          ["Email", "Name", "Requested", "Actions"],
          users.map(user => [
            user.email,
            user.full_name || "N/A",
            new Date(user.created_at).toLocaleString(),
            `
              <div class="inline">
                <button class="action-button primary" type="button" onclick="approveUser('${user.id}')">Approve</button>
                <button class="action-button ghost" type="button" onclick="rejectUser('${user.id}')">Reject</button>
              </div>
            `,
          ]),
        );
        setBox("adminStatus", `Admin access active. ${users.length} signup request(s) awaiting review.`, "success");
      } catch (error) {
        document.getElementById("pendingUsersContainer").classList.add("hidden");
        setBox("adminStatus", "This account does not have admin approval tools.", "");
      }
    }
    async function approveUser(id) {
      try {
        await sendJson(`/admin/users/${id}/approve`, "POST");
        await loadPendingUsers();
      } catch (error) {
        setBox("adminStatus", error.message, "error");
      }
    }
    async function rejectUser(id) {
      try {
        await sendJson(`/admin/users/${id}/reject`, "POST");
        await loadPendingUsers();
      } catch (error) {
        setBox("adminStatus", error.message, "error");
      }
    }
    window.approveUser = approveUser;
    window.rejectUser = rejectUser;
    async function init() {
      const [user, watchlists, paper, lines] = await Promise.all([
        loadJson("/auth/me"),
        loadJson("/dashboard/watchlists"),
        loadJson("/dashboard/paper-trades"),
        loadJson("/dashboard/trigger-lines?line_status=ACTIVE"),
      ]);
      setTwoFactorState(user);
      loadPendingUsers();
      renderCards({
        watchlists: watchlists.length,
        activeLines: watchlists.reduce((sum, item) => sum + item.active_trigger_lines, 0),
        triggeredLines: watchlists.reduce((sum, item) => sum + item.triggered_lines, 0),
        totalPnl: watchlists.reduce((sum, item) => sum + item.total_paper_pnl, 0),
      });
      renderTable(
        document.getElementById("watchlistsTable"),
        ["Name", "Symbols", "Active Buy", "Active Sell", "Active Lines", "Paper Trades", "Paper PnL"],
        watchlists.map(item => [
          item.name,
          item.symbol_count,
          item.symbols_with_active_buy_lines,
          item.symbols_with_active_sell_lines,
          item.active_trigger_lines,
          item.paper_trades,
          item.total_paper_pnl.toFixed(2),
        ]),
      );
      renderTable(
        document.getElementById("paperTable"),
        ["Total", "Open", "Closed", "Win Rate", "PnL", "Avg Profit", "Avg Loss", "Profit Factor"],
        [[
          paper.summary.total_trades,
          paper.summary.open_trades,
          paper.summary.closed_trades,
          `${paper.summary.win_rate}%`,
          paper.summary.total_pnl.toFixed(2),
          paper.summary.average_profit.toFixed(2),
          paper.summary.average_loss.toFixed(2),
          paper.summary.profit_factor ?? "N/A",
        ]],
      );
      renderTable(
        document.getElementById("linesTable"),
        ["Symbol", "Type", "Price", "Status", "Gap %", "Target", "Drawn Date"],
        lines.map(item => [
          `${item.exchange}:${item.symbol}`,
          `<span class="badge">${item.line_type}</span>`,
          item.line_price,
          item.line_status,
          item.swing_gap_percent ?? "N/A",
          item.nearest_daily_swing_high_target ?? item.nearest_daily_swing_low_target ?? "N/A",
          item.line_drawn_date ?? "N/A",
        ]),
      );
    }
    document.getElementById("logoutButton").addEventListener("click", async () => {
      await sendJson("/auth/logout", "POST");
      window.location.href = "/";
    });
    document.getElementById("setup2faButton").addEventListener("click", async () => {
      try {
        const setup = await sendJson("/auth/2fa/setup", "POST");
        const user = await loadJson("/auth/me");
        setTwoFactorState(user, setup);
        setBox("accountStatus", "Authenticator secret generated. Verify with your app, then enable 2FA.", "");
      } catch (error) {
        setBox("accountStatus", error.message, "error");
      }
    });
    document.getElementById("enable2faButton").addEventListener("click", async () => {
      try {
        await sendJson("/auth/2fa/enable", "POST", {
          code: document.getElementById("enable2faCode").value,
        });
        const user = await loadJson("/auth/me");
        setTwoFactorState(user);
        setBox("accountStatus", "Two-factor authentication is now enabled.", "success");
      } catch (error) {
        setBox("accountStatus", error.message, "error");
      }
    });
    document.getElementById("disable2faButton").addEventListener("click", async () => {
      document.getElementById("disable2faPanel").classList.toggle("hidden");
    });
    document.getElementById("confirmDisable2faButton").addEventListener("click", async () => {
      try {
        await sendJson("/auth/2fa/disable", "POST", {
          password: document.getElementById("disablePassword").value,
          code: document.getElementById("disableCode").value || null,
        });
        const user = await loadJson("/auth/me");
        document.getElementById("twoFactorSetupPanel").classList.add("hidden");
        document.getElementById("disable2faPanel").classList.add("hidden");
        setTwoFactorState(user);
        setBox("accountStatus", "Two-factor authentication has been disabled.", "success");
      } catch (error) {
        setBox("accountStatus", error.message, "error");
      }
    });
    init().catch((error) => {
      setBox("accountStatus", error.message, "error");
      setBox("adminStatus", "Dashboard initialization failed.", "error");
    });
  </script>
</body>
</html>
"""


@router.get("/dashboard/watchlists")
def get_watchlist_summary(db: Session = Depends(get_db)) -> list[dict]:
    watchlists = db.scalars(select(Watchlist).order_by(Watchlist.name)).all()
    symbols = db.scalars(select(WatchlistSymbol)).all()
    lines = db.scalars(select(TriggerLine)).all()
    trades = db.scalars(select(PaperTrade)).all()

    symbols_by_watchlist: dict[UUID, list[WatchlistSymbol]] = defaultdict(list)
    for symbol in symbols:
        symbols_by_watchlist[symbol.watchlist_id].append(symbol)

    lines_by_watchlist: dict[UUID, list[TriggerLine]] = defaultdict(list)
    for line in lines:
        if line.watchlist_id:
            lines_by_watchlist[line.watchlist_id].append(line)

    response = []
    for watchlist in watchlists:
        watchlist_symbols = symbols_by_watchlist.get(watchlist.id, [])
        watchlist_symbol_keys = {(item.exchange, item.symbol) for item in watchlist_symbols}
        watchlist_lines = lines_by_watchlist.get(watchlist.id, [])
        watchlist_trades = [trade for trade in trades if (trade.exchange, trade.symbol) in watchlist_symbol_keys]

        active_buy_symbols = {
            line.symbol for line in watchlist_lines if line.line_status == "ACTIVE" and line.line_type == "BUY"
        }
        active_sell_symbols = {
            line.symbol for line in watchlist_lines if line.line_status == "ACTIVE" and line.line_type == "SELL"
        }

        response.append(
            {
                "id": str(watchlist.id),
                "name": watchlist.name,
                "description": watchlist.description,
                "exchange": watchlist.exchange,
                "symbol_count": len(watchlist_symbols),
                "symbols_with_active_buy_lines": len(active_buy_symbols),
                "symbols_with_active_sell_lines": len(active_sell_symbols),
                "active_trigger_lines": sum(1 for line in watchlist_lines if line.line_status == "ACTIVE"),
                "triggered_lines": sum(1 for line in watchlist_lines if line.line_status == "TRIGGERED"),
                "paper_trades": len(watchlist_trades),
                "total_paper_pnl": round(sum(trade.pnl or 0.0 for trade in watchlist_trades), 2),
            }
        )
    return response


@router.get("/dashboard/watchlists/{watchlist_id}")
def get_watchlist_detail(watchlist_id: UUID, db: Session = Depends(get_db)) -> dict:
    watchlist = db.get(Watchlist, watchlist_id)
    if watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    symbols = db.scalars(
        select(WatchlistSymbol).where(WatchlistSymbol.watchlist_id == watchlist_id).order_by(WatchlistSymbol.symbol)
    ).all()
    lines = db.scalars(select(TriggerLine).where(TriggerLine.watchlist_id == watchlist_id)).all()
    signals = db.scalars(
        select(TradingSignal)
        .where(TradingSignal.watchlist_id == watchlist_id)
        .order_by(desc(TradingSignal.created_at))
    ).all()
    symbol_keys = {(item.exchange, item.symbol) for item in symbols}
    trades = [
        trade
        for trade in db.scalars(select(PaperTrade).order_by(desc(PaperTrade.created_at))).all()
        if (trade.exchange, trade.symbol) in symbol_keys
    ]

    latest_signal_by_symbol: dict[tuple[str, str], TradingSignal] = {}
    for signal in signals:
        latest_signal_by_symbol.setdefault((signal.exchange, signal.symbol), signal)

    symbol_payload = []
    for symbol in symbols:
        symbol_lines = [line for line in lines if line.symbol == symbol.symbol and line.exchange == symbol.exchange]
        symbol_trades = [trade for trade in trades if trade.symbol == symbol.symbol and trade.exchange == symbol.exchange]
        symbol_payload.append(
            {
                "id": str(symbol.id),
                "exchange": symbol.exchange,
                "symbol": symbol.symbol,
                "company_name": symbol.company_name,
                "is_active": symbol.is_active,
                "active_buy_lines": [_serialize_trigger_line(line) for line in symbol_lines if line.line_status == "ACTIVE" and line.line_type == "BUY"],
                "active_sell_lines": [_serialize_trigger_line(line) for line in symbol_lines if line.line_status == "ACTIVE" and line.line_type == "SELL"],
                "latest_signal": _serialize_signal(latest_signal_by_symbol[(symbol.exchange, symbol.symbol)]) if (symbol.exchange, symbol.symbol) in latest_signal_by_symbol else None,
                "paper_trade_summary": _paper_trade_summary(symbol_trades),
            }
        )

    return {
        "watchlist": {
            "id": str(watchlist.id),
            "name": watchlist.name,
            "description": watchlist.description,
            "exchange": watchlist.exchange,
            "created_at": _serialize_datetime(watchlist.created_at),
            "updated_at": _serialize_datetime(watchlist.updated_at),
        },
        "symbols": symbol_payload,
    }


@router.get("/dashboard/symbols/{exchange}/{symbol}")
def get_symbol_dashboard(exchange: str, symbol: str, db: Session = Depends(get_db)) -> dict:
    memberships = db.scalars(
        select(WatchlistSymbol).where(WatchlistSymbol.exchange == exchange, WatchlistSymbol.symbol == symbol)
    ).all()
    lines = db.scalars(
        select(TriggerLine)
        .where(TriggerLine.exchange == exchange, TriggerLine.symbol == symbol)
        .order_by(desc(TriggerLine.created_at))
    ).all()
    breakouts = db.scalars(
        select(BreakoutEvent)
        .where(BreakoutEvent.exchange == exchange, BreakoutEvent.symbol == symbol)
        .order_by(desc(BreakoutEvent.event_time))
    ).all()
    signals = db.scalars(
        select(TradingSignal)
        .where(TradingSignal.exchange == exchange, TradingSignal.symbol == symbol)
        .order_by(desc(TradingSignal.created_at))
    ).all()
    trades = db.scalars(
        select(PaperTrade)
        .where(PaperTrade.exchange == exchange, PaperTrade.symbol == symbol)
        .order_by(desc(PaperTrade.created_at))
    ).all()

    if not memberships and not lines and not breakouts and not signals and not trades:
        raise HTTPException(status_code=404, detail="Symbol not found")

    active_lines = [line for line in lines if line.line_status == "ACTIVE"]
    historical_lines = [line for line in lines if line.line_status != "ACTIVE"]
    return {
        "exchange": exchange,
        "symbol": symbol,
        "watchlists": [
            {
                "watchlist_id": str(membership.watchlist_id),
                "exchange": membership.exchange,
                "symbol": membership.symbol,
                "company_name": membership.company_name,
            }
            for membership in memberships
        ],
        "active_trigger_lines": [_serialize_trigger_line(line) for line in active_lines],
        "historical_trigger_lines": [_serialize_trigger_line(line) for line in historical_lines],
        "latest_signals": [_serialize_signal(signal) for signal in signals[:10]],
        "breakout_history": [_serialize_breakout_event(event) for event in breakouts],
        "paper_trades": [_serialize_paper_trade(trade) for trade in trades],
        "paper_trade_summary": _paper_trade_summary(trades),
    }


@router.get("/dashboard/trigger-lines")
def get_trigger_lines(
    watchlist_id: UUID | None = None,
    exchange: str | None = None,
    symbol: str | None = None,
    line_type: str | None = None,
    line_status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    lines = db.scalars(select(TriggerLine).order_by(desc(TriggerLine.created_at))).all()
    filtered = []
    for line in lines:
        if watchlist_id and line.watchlist_id != watchlist_id:
            continue
        if exchange and line.exchange != exchange:
            continue
        if symbol and line.symbol != symbol:
            continue
        if line_type and line.line_type != line_type:
            continue
        if line_status and line.line_status != line_status:
            continue
        if date_from and line.line_drawn_date and line.line_drawn_date < date_from:
            continue
        if date_to and line.line_drawn_date and line.line_drawn_date > date_to:
            continue
        filtered.append(_serialize_trigger_line(line))
    return filtered


@router.get("/dashboard/breakout-events")
def get_breakout_events(
    exchange: str | None = None,
    symbol: str | None = None,
    event_type: str | None = None,
    volume_condition_passed: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    events = db.scalars(select(BreakoutEvent).order_by(desc(BreakoutEvent.event_time))).all()
    filtered = []
    for event in events:
        event_date = event.event_time.astimezone(UTC).date()
        if exchange and event.exchange != exchange:
            continue
        if symbol and event.symbol != symbol:
            continue
        if event_type and event.event_type != event_type:
            continue
        if volume_condition_passed is not None and event.volume_condition_passed != volume_condition_passed:
            continue
        if date_from and event_date < date_from:
            continue
        if date_to and event_date > date_to:
            continue
        filtered.append(_serialize_breakout_event(event))
    return filtered


@router.get("/dashboard/paper-trades")
def get_paper_trades(
    watchlist_id: UUID | None = None,
    exchange: str | None = None,
    symbol: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
) -> dict:
    trades = db.scalars(select(PaperTrade).order_by(desc(PaperTrade.created_at))).all()
    watchlist_symbols: set[tuple[str, str]] = set()
    if watchlist_id:
        watchlist_symbols = {
            (item.exchange, item.symbol)
            for item in db.scalars(select(WatchlistSymbol).where(WatchlistSymbol.watchlist_id == watchlist_id)).all()
        }

    filtered = []
    for trade in trades:
        trade_date = (trade.entry_time or trade.created_at).astimezone(UTC).date()
        if watchlist_id and (trade.exchange, trade.symbol) not in watchlist_symbols:
            continue
        if exchange and trade.exchange != exchange:
            continue
        if symbol and trade.symbol != symbol:
            continue
        if status and trade.status != status:
            continue
        if date_from and trade_date < date_from:
            continue
        if date_to and trade_date > date_to:
            continue
        filtered.append(trade)

    return {
        "summary": _paper_trade_summary(filtered),
        "trades": [_serialize_paper_trade(trade) for trade in filtered],
    }
