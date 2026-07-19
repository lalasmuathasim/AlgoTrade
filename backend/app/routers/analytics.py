from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from backend.app.dependencies import require_approved_user
from backend.app.ui import render_app_shell


router = APIRouter(tags=["analytics"], dependencies=[Depends(require_approved_user)])


@router.get("/analytics", response_class=HTMLResponse)
def analytics_page() -> str:
    body_html = """
    <section id="analyticsStrip" class="metric-strip"></section>
    <section class="layout-main-aside">
      <div class="panel">
        <div class="panel-header">
          <div>
            <h2>Planned Analytics Modules</h2>
            <p class="panel-copy">This area is intentionally staged for the next build phase so we can add deeper studies without reworking the portal structure again.</p>
          </div>
        </div>
        <ul class="list">
          <li class="pill">Trigger-line conversion from draw to breakout</li>
          <li class="pill">Breakout volume quality by symbol and sector</li>
          <li class="pill">Paper trade expectancy, win rate, and drawdown</li>
          <li class="pill">Daily scan coverage and unmapped symbol gaps</li>
          <li class="pill">Future broker-order and reconciliation analytics</li>
        </ul>
      </div>
      <div class="rail-stack">
        <div class="panel">
          <div class="panel-header">
            <div>
              <h2>Data Foundations Already Available</h2>
              <p class="panel-copy">Core entities are already persisted and ready to power deeper performance views once we start this phase.</p>
            </div>
          </div>
          <table id="analyticsReadyTable"></table>
        </div>
        <div class="panel">
          <div class="panel-header">
            <div>
              <h2>Next Build Notes</h2>
              <p class="panel-copy">Keep Dashboard for exports and Configuration for setup. Analytics stays focused on interpretation and optimization only.</p>
            </div>
          </div>
          <ul class="list">
            <li class="pill">No live execution UI here yet</li>
            <li class="pill">No settings duplication from Configuration</li>
            <li class="pill">Add charting only when signal studies begin</li>
          </ul>
        </div>
      </div>
    </section>
    """
    script = """
    renderMetricStrip(document.getElementById("analyticsStrip"), [
      { label: "Phase", value: "Next", meta: "Analytics is scaffolded and waiting for deeper signal-quality and performance work." },
      { label: "Planned Focus", value: "5 Areas", meta: "Signal quality, conversion performance, paper PnL, scan coverage, and reconciliation." },
      { label: "Current State", value: "Placeholder", meta: "Use Dashboard for reports and Configuration for runtime setup today." },
    ]);
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
