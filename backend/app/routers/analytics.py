from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from backend.app.dependencies import require_approved_user
from backend.app.ui import render_app_shell


router = APIRouter(tags=["analytics"], dependencies=[Depends(require_approved_user)])


@router.get("/analytics", response_class=HTMLResponse)
def analytics_page() -> str:
    body_html = """
    <section class="grid">
      <article class="card">
        <div class="label">Phase</div>
        <div class="value">Next</div>
        <div class="subvalue">Analytics is intentionally scaffolded now so we can plug in performance and quality studies without redesigning navigation later.</div>
      </article>
      <article class="card">
        <div class="label">Planned Focus</div>
        <div class="value">5 Areas</div>
        <div class="subvalue">Signal quality, line-conversion performance, paper PnL analytics, scan coverage, and future live-order reconciliation.</div>
      </article>
      <article class="card">
        <div class="label">Current State</div>
        <div class="value">Placeholder</div>
        <div class="subvalue">Use Dashboard for today’s reports and Configuration for watchlist and readiness setup.</div>
      </article>
    </section>
    <section class="two-col">
      <div class="panel">
        <h2>Planned Analytics Modules</h2>
        <ul class="list">
          <li class="pill">Trigger-line conversion from draw to breakout</li>
          <li class="pill">Breakout volume quality by symbol and sector</li>
          <li class="pill">Paper trade expectancy, win rate, and drawdown</li>
          <li class="pill">Daily scan coverage and unmapped symbol gaps</li>
          <li class="pill">Future broker-order and reconciliation analytics</li>
        </ul>
      </div>
      <div class="panel">
        <h2>Data Foundations Already Available</h2>
        <table id="analyticsReadyTable"></table>
      </div>
    </section>
    """
    script = """
    renderTable(
      document.getElementById("analyticsReadyTable"),
      ["Domain", "Status", "Notes"],
      [
        ["Watchlists", '<span class="badge">READY</span>', "Saved symbol groups already exist."],
        ["Trigger lines", '<span class="badge">READY</span>', "Daily structures and statuses are persisted."],
        ["Breakout events", '<span class="badge">READY</span>', "3-minute breakout and breakdown events are stored."],
        ["Trading signals", '<span class="badge">READY</span>', "Signal lineage is available for future performance views."],
        ["Paper trades", '<span class="badge">READY</span>', "PnL and trade lifecycle are available for analytics."],
        ["Live orders", '<span class="badge warn">LATER</span>', "Still feature-gated and placeholder-only."],
      ],
    );
    """
    return render_app_shell(
        title="Qubitx Analytics",
        heading="Analytics",
        subtitle="Prepare the next phase of performance, signal-quality, and execution-analysis views without coupling them to the operational configuration screens.",
        active_nav="analytics",
        body_html=body_html,
        script=script,
    )

