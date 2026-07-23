from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.dependencies import require_admin_user, require_approved_user
from backend.app.models import User
from backend.app.schemas import (
    AuthStatusResponse,
    LoginPayload,
    MessageResponse,
    SignupPayload,
    TwoFactorDisablePayload,
    TwoFactorEnablePayload,
    TwoFactorSetupResponse,
    UserResponse,
)
from backend.app.security import (
    build_totp_uri,
    create_access_token,
    generate_totp_secret,
    verify_password,
    verify_totp_code,
)
from backend.app.services.auth_service import (
    approve_user,
    create_pending_user,
    get_user_by_email,
    list_pending_users,
    reject_user,
)


router = APIRouter(tags=["auth"])
settings = get_settings()


def _set_session_cookie(response: Response, user: User) -> None:
    token = create_access_token(str(user.id), user.role)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


@router.get("/", response_class=HTMLResponse)
def landing_page() -> str:
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Qubitx Control Center</title>
  <style>
    :root {
      --bg: #f5f7fb;
      --ink: #122033;
      --muted: #60738b;
      --panel: rgba(255, 255, 255, 0.92);
      --panel-soft: rgba(248, 251, 255, 0.98);
      --accent: #0f9b8e;
      --accent-alt: #3d7ef0;
      --accent-soft: rgba(15, 155, 142, 0.1);
      --ok: #0b8f63;
      --danger: #cf4545;
      --warn: #b8731d;
      --line: rgba(75, 102, 138, 0.14);
      --line-strong: rgba(75, 102, 138, 0.22);
      --shadow: 0 24px 55px rgba(20, 34, 56, 0.1);
    }
    * { box-sizing: border-box; }
    html { color-scheme: light; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 8% 12%, rgba(61, 126, 240, 0.12), transparent 26%),
        radial-gradient(circle at 92% 18%, rgba(15, 155, 142, 0.1), transparent 28%),
        linear-gradient(145deg, #f8fafc 0%, #eef3f8 46%, #edf5f3 100%);
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      background-image:
        linear-gradient(rgba(61, 126, 240, 0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(61, 126, 240, 0.03) 1px, transparent 1px);
      background-size: 32px 32px;
      pointer-events: none;
    }
    a { color: inherit; }
    .wrap { max-width: 1380px; margin: 0 auto; padding: 24px 20px 56px; position: relative; }
    .masthead {
      display: grid;
      grid-template-columns: minmax(260px, 420px) 1fr;
      gap: 28px;
      margin-bottom: 18px;
      align-items: center;
      padding: 18px 8px 10px;
    }
    .brand {
      display: grid;
      gap: 4px;
    }
    .workspace-nav {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
      min-width: 0;
      align-items: center;
    }
    .workspace-nav-spacer {
      flex: 1 1 auto;
    }
    .workspace-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 58px;
      padding: 0 20px;
      border-radius: 18px;
      border: 1px solid transparent;
      color: #26405f;
      text-decoration: none;
      font-family: "Space Grotesk", "Avenir Next", sans-serif;
      font-size: clamp(0.94rem, 1.15vw, 1.15rem);
      font-weight: 600;
      letter-spacing: -0.02em;
      transition: transform 0.16s ease, background 0.16s ease, border-color 0.16s ease, color 0.16s ease, box-shadow 0.16s ease;
    }
    .workspace-link:hover {
      transform: translateY(-1px);
      background: rgba(61, 126, 240, 0.08);
      border-color: rgba(61, 126, 240, 0.14);
      color: #0d2137;
    }
    .workspace-link.active {
      background: linear-gradient(180deg, rgba(238,248,255,0.98), rgba(230,242,252,0.98));
      border-color: rgba(15, 155, 142, 0.22);
      color: #0e1f33;
      box-shadow:
        inset 0 0 0 1px rgba(255,255,255,0.7),
        0 10px 24px rgba(61, 126, 240, 0.08);
    }
    .workspace-link-action {
      min-height: auto;
      padding: 0;
      border: none;
      background: transparent;
      box-shadow: none;
      border-radius: 0;
      color: var(--muted);
      cursor: pointer;
      font: inherit;
      font-size: 0.9rem;
      font-weight: 500;
      letter-spacing: 0;
      text-transform: none;
    }
    .workspace-link-action:hover {
      background: transparent;
      border-color: transparent;
      color: #0d2137;
      box-shadow: none;
    }
    .workspace-user {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      min-height: 40px;
      margin-left: 6px;
      color: var(--muted);
      font-size: 0.9rem;
      white-space: nowrap;
    }
    .workspace-user-name {
      color: #2b435f;
      font-weight: 500;
    }
    .brand-mark {
      font-size: 0.78rem;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--accent);
      font-weight: 700;
    }
    .brand-title {
      margin-top: 8px;
      font-family: "Space Grotesk", "Avenir Next", sans-serif;
      font-size: clamp(2.1rem, 4vw, 3.1rem);
      font-weight: 700;
      line-height: 0.95;
      letter-spacing: -0.05em;
    }
    .brand-copy {
      margin-top: 10px;
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.5;
      max-width: 420px;
    }
    .shell-action, .cta, .ghost, .inline-button, .tab-button {
      border: 1px solid var(--line);
      border-radius: 12px;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      text-decoration: none;
      transition: transform 0.16s ease, background 0.16s ease, border-color 0.16s ease, opacity 0.16s ease;
    }
    .shell-action, .ghost, .inline-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 42px;
      padding: 10px 14px;
      background: rgba(255,255,255,0.72);
      color: var(--ink);
    }
    .shell-action:hover, .ghost:hover, .inline-button:hover, .cta:hover, .tab-button:hover {
      transform: translateY(-1px);
      border-color: var(--line-strong);
      background: rgba(248,251,255,0.98);
    }
    .hero {
      display: grid;
      grid-template-columns: 1.08fr 0.92fr;
      gap: 22px;
      align-items: start;
    }
    .hero-copy, .auth-shell, .feature-card, .flow-card, .status-bar, .market-card {
      border: 1px solid var(--line);
      border-radius: 26px;
      box-shadow: var(--shadow);
    }
    .hero-copy {
      background: linear-gradient(145deg, rgba(255,255,255,0.98), rgba(246,249,253,0.98));
      padding: 34px;
      position: relative;
      overflow: hidden;
    }
    .hero-copy::after {
      content: "";
      position: absolute;
      inset: auto -70px -80px auto;
      width: 240px;
      height: 240px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(61,126,240,0.22), transparent 68%);
    }
    .eyebrow {
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 0.76rem;
      color: var(--accent);
      font-weight: 700;
      margin-bottom: 14px;
    }
    h1, h2, h3 {
      font-family: "Space Grotesk", "Avenir Next", sans-serif;
      margin: 0;
    }
    h1 {
      font-size: clamp(2.7rem, 5vw, 4.9rem);
      line-height: 0.92;
      letter-spacing: -0.05em;
      max-width: 720px;
    }
    .hero-copy p {
      margin: 18px 0 0;
      max-width: 640px;
      line-height: 1.65;
      color: var(--muted);
      font-size: 1.02rem;
    }
    .hero-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 26px;
    }
    .metric {
      background: rgba(248, 251, 255, 0.92);
      border: 1px solid rgba(61, 126, 240, 0.08);
      border-radius: 18px;
      padding: 16px;
    }
    .metric-label {
      font-size: 0.78rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
      font-weight: 700;
    }
    .metric-value {
      font-family: "Space Grotesk", "Avenir Next", sans-serif;
      font-size: 1.45rem;
      margin-top: 8px;
      letter-spacing: -0.03em;
    }
    .auth-shell {
      background: var(--panel);
      backdrop-filter: blur(10px);
      padding: 22px;
    }
    .auth-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 14px;
    }
    .auth-head p {
      margin: 8px 0 0;
      color: var(--muted);
      line-height: 1.55;
      font-size: 0.95rem;
    }
    .tabs {
      display: flex;
      gap: 10px;
      margin-bottom: 16px;
    }
    .tab-button {
      flex: 1;
      padding: 12px 14px;
      background: rgba(61, 126, 240, 0.06);
      color: var(--ink);
      font-weight: 600;
    }
    .tab-button.active {
      background: linear-gradient(135deg, rgba(15,155,142,0.94), rgba(18,125,164,0.92));
      border-color: rgba(15,155,142,0.22);
      color: #ffffff;
    }
    .panel { display: none; }
    .panel.active { display: block; }
    .field { margin-bottom: 12px; }
    label {
      display: block;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      margin-bottom: 6px;
      color: var(--muted);
      font-weight: 700;
    }
    input {
      width: 100%;
      border-radius: 14px;
      border: 1px solid rgba(75, 102, 138, 0.16);
      background: rgba(248, 251, 255, 0.98);
      padding: 13px 14px;
      font-size: 0.98rem;
      color: var(--ink);
    }
    input:focus {
      outline: none;
      border-color: rgba(15, 155, 142, 0.32);
      box-shadow: 0 0 0 3px rgba(15, 155, 142, 0.08);
    }
    .cta {
      width: 100%;
      border-radius: 14px;
      padding: 14px;
      background: linear-gradient(135deg, rgba(15,155,142,0.96), rgba(18,125,164,0.94));
      border-color: rgba(15,155,142,0.22);
      color: #ffffff;
      font-weight: 700;
      font-size: 0.98rem;
    }
    .ghost {
      width: 100%;
      padding: 14px;
      font-weight: 700;
      margin-top: 10px;
    }
    .signed-session {
      display: none;
      gap: 12px;
    }
    .signed-session.active {
      display: grid;
    }
    .status-bar {
      background: rgba(248,251,255,0.98);
      margin-top: 16px;
      padding: 14px 16px;
      color: var(--muted);
      font-size: 0.95rem;
      min-height: 56px;
    }
    .status-bar.error { color: var(--danger); }
    .status-bar.success { color: var(--ok); }
    .content {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
      margin-top: 24px;
      align-items: start;
    }
    .feature-card, .flow-card, .market-card {
      background: rgba(255, 255, 255, 0.94);
      backdrop-filter: blur(10px);
      padding: 22px;
    }
    .feature-list, .flow-list {
      display: grid;
      gap: 12px;
      margin-top: 14px;
    }
    .feature-item, .flow-item {
      border: 1px solid rgba(75, 102, 138, 0.1);
      border-radius: 18px;
      padding: 16px;
      background: rgba(248,251,255,0.98);
    }
    .feature-item strong, .flow-item strong {
      display: block;
      margin-bottom: 6px;
      font-family: "Space Grotesk", "Avenir Next", sans-serif;
      font-size: 1.04rem;
      letter-spacing: -0.02em;
    }
    .inline-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .inline-button {
      border-radius: 12px;
    }
    .muted-note {
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.5;
    }
    .market-card {
      margin-top: 18px;
    }
    .market-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
      align-items: start;
    }
    .market-item {
      padding: 14px;
      border-radius: 18px;
      border: 1px solid rgba(75, 102, 138, 0.1);
      background: rgba(248,251,255,0.98);
    }
    .market-item strong {
      display: block;
      font-size: 1rem;
      margin-bottom: 8px;
      font-family: "Space Grotesk", "Avenir Next", sans-serif;
    }
    .hidden { display: none; }
    @media (max-width: 980px) {
      .hero, .content, .market-grid { grid-template-columns: 1fr; }
      .hero-grid { grid-template-columns: 1fr; }
      .masthead { grid-template-columns: 1fr; align-items: start; padding-bottom: 4px; }
      .workspace-nav { justify-content: flex-start; }
      .workspace-link {
        min-height: 48px;
        padding: 0 16px;
        border-radius: 14px;
      }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="masthead">
      <div class="brand">
        <div class="brand-mark">Qubitx</div>
        <div class="brand-title">Market Control</div>
        <div class="brand-copy">A focused trading workspace for watchlists, structure tracking, runtime readiness, and review-grade reporting.</div>
      </div>
      <nav class="workspace-nav">
        <a class="workspace-link active" href="/">Home</a>
        <a class="workspace-link" href="/dashboard">Dashboard</a>
        <a class="workspace-link" href="/configuration">Configuration</a>
        <a class="workspace-link" href="/analytics">Analytics</a>
        <span id="workspaceNavSpacer" class="workspace-nav-spacer hidden"></span>
        <div id="workspaceUser" class="workspace-user hidden">
          <span id="workspaceGreeting" class="workspace-user-name"></span>
          <button id="logoutNavButton" class="workspace-link workspace-link-action" type="button">Log out</button>
        </div>
      </nav>
    </section>
    <section class="hero">
      <article class="hero-copy">
        <div class="eyebrow">Trading Workspace</div>
        <h1>Research-first trade intelligence before live execution.</h1>
        <p>Review Zerodha-native trigger lines, breakout events, generated signals, paper trades, and approval-gated access from one control surface built for future low-latency execution.</p>
        <div class="hero-grid">
          <div class="metric">
            <div class="metric-label">Pipeline</div>
            <div class="metric-value">Scan → Market Engine → Worker</div>
          </div>
          <div class="metric">
            <div class="metric-label">Security</div>
            <div class="metric-value">Role-based + 2FA ready</div>
          </div>
          <div class="metric">
            <div class="metric-label">Focus</div>
            <div class="metric-value">Paper-first analytics</div>
          </div>
        </div>
      </article>
      <aside class="auth-shell">
        <div class="auth-head">
          <div>
            <div class="eyebrow">Access Control</div>
            <h2>Enter the portal</h2>
            <p>Approved users can access the protected workspace. New signups still require admin approval before login is enabled.</p>
          </div>
        </div>
        <div id="loginPanel" class="panel active">
          <form id="loginForm">
            <div class="field">
              <label for="loginEmail">Email</label>
              <input id="loginEmail" name="email" type="email" autocomplete="username" required />
            </div>
            <div class="field">
              <label for="loginPassword">Password</label>
              <input id="loginPassword" name="password" type="password" autocomplete="current-password" required />
            </div>
            <div class="field hidden" id="twoFactorField">
              <label for="twoFactorCode">Two-factor code</label>
              <input id="twoFactorCode" name="two_factor_code" type="text" inputmode="numeric" maxlength="6" placeholder="123456" />
            </div>
            <button class="cta" type="submit">Log In</button>
            <button class="ghost" id="requestAccessButton" type="button">Request Access</button>
          </form>
        </div>
        <div id="signedInPanel" class="signed-session">
          <div class="status-bar success" id="signedInStatus">Signed in.</div>
          <div class="inline-actions">
            <a class="inline-button" href="/dashboard">Open Dashboard</a>
            <a class="inline-button" href="/configuration">Open Configuration</a>
          </div>
        </div>
        <div id="signupPanel" class="panel">
          <form id="signupForm">
            <div class="field">
              <label for="signupName">Full name</label>
              <input id="signupName" name="full_name" type="text" autocomplete="name" />
            </div>
            <div class="field">
              <label for="signupEmail">Email</label>
              <input id="signupEmail" name="email" type="email" autocomplete="email" required />
            </div>
            <div class="field">
              <label for="signupPassword">Password</label>
              <input id="signupPassword" name="password" type="password" autocomplete="new-password" required />
            </div>
            <button class="cta" type="submit">Request Approval</button>
            <button class="ghost" id="backToLoginButton" type="button">Back to Login</button>
          </form>
        </div>
        <div id="statusBar" class="status-bar">Approved users can access the protected dashboard. New signups require admin approval before login is enabled.</div>
      </aside>
    </section>
    <section class="market-card">
      <div class="eyebrow">Platform Scope</div>
      <h2>One visual system across the full portal.</h2>
      <div class="market-grid">
        <div class="market-item">
          <strong>Configuration</strong>
          Watchlists, validation, readiness, and live monitoring prerequisites.
        </div>
        <div class="market-item">
          <strong>Dashboard</strong>
          Reporting, coverage, active lines, and export-friendly operational review.
        </div>
        <div class="market-item">
          <strong>Analytics</strong>
          Placeholder for the next phase of signal quality and performance studies.
        </div>
        <div class="market-item">
          <strong>Security</strong>
          Admin approvals, role-based access, and two-factor readiness.
        </div>
      </div>
    </section>
    <section class="content">
      <article class="feature-card">
        <div class="eyebrow">What You Can Study</div>
        <h2>Built for structure, review, and iteration.</h2>
        <div class="feature-list">
          <div class="feature-item">
            <strong>Watchlist and symbol oversight</strong>
            Track curated NSE symbol groups, active membership, and where trigger coverage is strong or weak.
          </div>
          <div class="feature-item">
            <strong>Multi-line structure history</strong>
            Preserve multiple buy and sell trigger lines per symbol, including invalidated and triggered structures.
          </div>
          <div class="feature-item">
            <strong>Paper-trading feedback loop</strong>
            Review simulated entries, risk assumptions, and performance analytics before real broker integration is enabled.
          </div>
        </div>
      </article>
      <article class="flow-card">
        <div class="eyebrow">Security and Flow</div>
        <h2>Access stays gated. Signal ingestion stays fast.</h2>
        <div class="flow-list">
          <div class="flow-item">
            <strong>1. Landing and identity</strong>
            Users request access here, then log in once an admin approves their account.
          </div>
          <div class="flow-item">
            <strong>2. Queue-first processing</strong>
            Daily scans and live market signals are processed asynchronously without waiting on analytics or notifications.
          </div>
          <div class="flow-item">
            <strong>3. Future execution readiness</strong>
            The same records are ready to link with real Zerodha orders later without a data-model reset.
          </div>
        </div>
        <div class="inline-actions">
          <a class="inline-button" href="/dashboard">Dashboard</a>
          <a class="inline-button" href="/configuration">Configuration</a>
        </div>
        <p class="muted-note">Two-factor authentication can be enabled after login from the dashboard security panel. Market scanning and signal generation remain separate and unaffected by user sign-in.</p>
      </article>
    </section>
  </div>
  <script>
    const statusBar = document.getElementById("statusBar");
    const loginPanel = document.getElementById("loginPanel");
    const signupPanel = document.getElementById("signupPanel");
    const signedInPanel = document.getElementById("signedInPanel");
    const signedInStatus = document.getElementById("signedInStatus");
    const twoFactorField = document.getElementById("twoFactorField");
    const workspaceNavSpacer = document.getElementById("workspaceNavSpacer");
    const logoutNavButton = document.getElementById("logoutNavButton");
    const authStatusMessages = {
      logged_out: { message: "You have been logged out successfully.", tone: "success" },
      auth_required: { message: "You were logged out because authentication is required to open that page. Please sign in again.", tone: "warn" },
      session_expired: { message: "You were logged out because your session expired or became invalid. Please sign in again.", tone: "warn" },
    };

    function setStatus(message, tone = "") {
      statusBar.textContent = message;
      statusBar.className = `status-bar ${tone}`;
    }
    function formatWorkspaceName(user) {
      const fullName = (user?.full_name || "").trim();
      if (fullName) {
        return fullName;
      }
      const email = (user?.email || "").trim();
      if (!email) {
        return "there";
      }
      const localPart = email.split("@")[0] || email;
      return localPart
        .replace(/[._-]+/g, " ")
        .split(" ")
        .filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
    }

    function applyAuthStatusMessage() {
      const params = new URLSearchParams(window.location.search);
      const status = params.get("auth_status");
      if (!status || !authStatusMessages[status]) {
        return;
      }
      const { message, tone } = authStatusMessages[status];
      activateTab("login");
      setStatus(message, tone);
      params.delete("auth_status");
      const nextQuery = params.toString();
      const nextUrl = `${window.location.pathname}${nextQuery ? `?${nextQuery}` : ""}`;
      window.history.replaceState({}, "", nextUrl);
    }

    function showSignedInState(user) {
      loginPanel.classList.remove("active");
      signupPanel.classList.remove("active");
      loginPanel.classList.add("hidden");
      signupPanel.classList.add("hidden");
      signedInPanel.classList.add("active");
      workspaceNavSpacer.classList.remove("hidden");
      logoutNavButton.classList.remove("hidden");
      document.getElementById("workspaceUser").classList.remove("hidden");
      document.getElementById("workspaceGreeting").textContent = `Hi ${formatWorkspaceName(user)}`;
      signedInStatus.textContent = "Workspace ready.";
      setStatus("You already have an active session. Open the dashboard or continue to configuration.", "success");
    }

    function activateTab(tab) {
      const isLogin = tab === "login";
      signedInPanel.classList.remove("active");
      loginPanel.classList.remove("hidden");
      signupPanel.classList.remove("hidden");
      loginPanel.classList.toggle("active", isLogin);
      signupPanel.classList.toggle("active", !isLogin);
    }
    document.getElementById("requestAccessButton").addEventListener("click", () => activateTab("signup"));
    document.getElementById("backToLoginButton").addEventListener("click", () => activateTab("login"));

    document.getElementById("loginForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = {
        email: document.getElementById("loginEmail").value,
        password: document.getElementById("loginPassword").value,
        two_factor_code: document.getElementById("twoFactorCode").value || null,
      };
      const response = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        setStatus(data.detail || data.message || "Login failed.", "error");
        return;
      }
      if (data.requires_two_factor) {
        twoFactorField.classList.remove("hidden");
        setStatus(data.message, "");
        return;
      }
      setStatus(data.message, "success");
      showSignedInState(data.user);
      window.location.href = "/dashboard";
    });

    document.getElementById("signupForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = {
        full_name: document.getElementById("signupName").value || null,
        email: document.getElementById("signupEmail").value,
        password: document.getElementById("signupPassword").value,
      };
      const response = await fetch("/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        setStatus(data.detail || data.message || "Signup failed.", "error");
        return;
      }
      setStatus(data.message, "success");
      activateTab("login");
    });

    logoutNavButton.addEventListener("click", async () => {
      await fetch("/auth/logout", { method: "POST" });
      window.location.href = "/?auth_status=logged_out";
    });

    async function detectSession() {
      const response = await fetch("/auth/me");
      if (!response.ok) {
        return;
      }
      const user = await response.json();
      showSignedInState(user);
    }

    applyAuthStatusMessage();
    detectSession();
  </script>
</body>
</html>
"""


@router.post("/auth/signup", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupPayload, db: Session = Depends(get_db)) -> MessageResponse:
    existing = get_user_by_email(db, str(payload.email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")

    create_pending_user(db, payload)
    return MessageResponse(message="Signup received. An admin must approve your account before login is enabled.")


@router.post("/auth/login", response_model=AuthStatusResponse)
def login(payload: LoginPayload, response: Response, db: Session = Depends(get_db)) -> AuthStatusResponse:
    user = get_user_by_email(db, str(payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if not user.is_active or user.approval_status == "REJECTED":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is inactive")
    if user.approval_status != "APPROVED":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is awaiting admin approval")

    if user.two_factor_enabled:
        if not payload.two_factor_code:
            return AuthStatusResponse(
                authenticated=False,
                requires_two_factor=True,
                message="Two-factor code required to complete login.",
            )
        if not user.two_factor_secret or not verify_totp_code(user.two_factor_secret, payload.two_factor_code):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid two-factor code")

    user.last_login_at = datetime.now(UTC)
    db.commit()
    _set_session_cookie(response, user)
    return AuthStatusResponse(
        authenticated=True,
        requires_two_factor=False,
        message="Login successful.",
        user=UserResponse.model_validate(user),
    )


@router.post("/auth/logout", response_model=MessageResponse)
def logout(response: Response) -> MessageResponse:
    response.delete_cookie(settings.session_cookie_name, path="/")
    return MessageResponse(message="Logged out successfully.")


@router.get("/auth/me", response_model=UserResponse)
def get_current_account(current_user: User = Depends(require_approved_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.post("/auth/2fa/setup", response_model=TwoFactorSetupResponse)
def setup_two_factor(
    current_user: User = Depends(require_approved_user),
    db: Session = Depends(get_db),
) -> TwoFactorSetupResponse:
    secret = current_user.two_factor_secret or generate_totp_secret()
    current_user.two_factor_secret = secret
    db.commit()
    return TwoFactorSetupResponse(
        secret=secret,
        provisioning_uri=build_totp_uri(secret, current_user.email),
        enabled=current_user.two_factor_enabled,
    )


@router.post("/auth/2fa/enable", response_model=MessageResponse)
def enable_two_factor(
    payload: TwoFactorEnablePayload,
    current_user: User = Depends(require_approved_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    if not current_user.two_factor_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Set up two-factor before enabling it")
    if not verify_totp_code(current_user.two_factor_secret, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid two-factor code")

    current_user.two_factor_enabled = True
    db.commit()
    return MessageResponse(message="Two-factor authentication is now enabled.")


@router.post("/auth/2fa/disable", response_model=MessageResponse)
def disable_two_factor(
    payload: TwoFactorDisablePayload,
    current_user: User = Depends(require_approved_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    if not verify_password(payload.password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    if current_user.two_factor_enabled:
        if not current_user.two_factor_secret or not payload.code:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A valid two-factor code is required")
        if not verify_totp_code(current_user.two_factor_secret, payload.code):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid two-factor code")

    current_user.two_factor_enabled = False
    current_user.two_factor_secret = None
    db.commit()
    return MessageResponse(message="Two-factor authentication has been disabled.")


@router.get("/admin/users/pending", response_model=list[UserResponse])
def get_pending_users(
    _: User = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> list[UserResponse]:
    return [UserResponse.model_validate(user) for user in list_pending_users(db)]


@router.post("/admin/users/{user_id}/approve", response_model=UserResponse)
def approve_pending_user(
    user_id: UUID,
    admin_user: User = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    user = approve_user(db, user_id, admin_user)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.model_validate(user)


@router.post("/admin/users/{user_id}/reject", response_model=UserResponse)
def reject_pending_user(
    user_id: UUID,
    admin_user: User = Depends(require_admin_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    user = reject_user(db, user_id, admin_user)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.model_validate(user)
