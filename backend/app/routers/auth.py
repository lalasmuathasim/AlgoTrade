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
  <title>AlgoTrade Control Center</title>
  <style>
    :root {
      --bg: #f4efe4;
      --ink: #16332f;
      --muted: #5f706b;
      --panel: rgba(255, 251, 245, 0.8);
      --panel-strong: rgba(16, 34, 31, 0.94);
      --accent: #b7652f;
      --accent-soft: rgba(183, 101, 47, 0.12);
      --ok: #0f766e;
      --danger: #b42318;
      --line: rgba(22, 51, 47, 0.12);
      --shadow: 0 24px 60px rgba(24, 39, 37, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 8% 12%, rgba(183, 101, 47, 0.18), transparent 26%),
        radial-gradient(circle at 92% 18%, rgba(15, 118, 110, 0.14), transparent 28%),
        linear-gradient(145deg, #efe6d6 0%, #f8f4ec 46%, #ebf3ef 100%);
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      background-image:
        linear-gradient(rgba(22, 51, 47, 0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(22, 51, 47, 0.03) 1px, transparent 1px);
      background-size: 44px 44px;
      pointer-events: none;
    }
    .wrap { max-width: 1320px; margin: 0 auto; padding: 28px 20px 56px; position: relative; }
    .hero {
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 22px;
      align-items: stretch;
    }
    .hero-copy, .auth-shell, .feature-card, .flow-card, .status-bar {
      border: 1px solid var(--line);
      border-radius: 26px;
      box-shadow: var(--shadow);
    }
    .hero-copy {
      background: linear-gradient(140deg, rgba(16, 34, 31, 0.97), rgba(24, 49, 45, 0.9));
      color: #f7f1e6;
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
      background: radial-gradient(circle, rgba(183, 101, 47, 0.38), transparent 68%);
    }
    .eyebrow {
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.8rem;
      color: rgba(247, 241, 230, 0.76);
      margin-bottom: 14px;
    }
    h1, h2, h3 {
      font-family: "Baskerville", "Palatino Linotype", serif;
      margin: 0;
    }
    h1 {
      font-size: clamp(2.6rem, 5vw, 4.7rem);
      line-height: 0.95;
      max-width: 720px;
    }
    .hero-copy p {
      margin: 18px 0 0;
      max-width: 640px;
      line-height: 1.65;
      color: rgba(247, 241, 230, 0.82);
      font-size: 1.02rem;
    }
    .hero-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 26px;
    }
    .metric {
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.09);
      border-radius: 18px;
      padding: 16px;
    }
    .metric-label {
      font-size: 0.78rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: rgba(247, 241, 230, 0.66);
    }
    .metric-value { font-size: 1.5rem; margin-top: 8px; }
    .auth-shell {
      background: var(--panel);
      backdrop-filter: blur(14px);
      padding: 22px;
    }
    .tabs {
      display: flex;
      gap: 10px;
      margin-bottom: 16px;
    }
    .tabs button, .cta, .ghost, .inline-button {
      border: none;
      cursor: pointer;
      transition: transform 0.16s ease, opacity 0.16s ease, background 0.16s ease;
    }
    .tabs button {
      flex: 1;
      padding: 12px 14px;
      border-radius: 14px;
      background: rgba(22, 51, 47, 0.07);
      color: var(--ink);
      font-weight: 600;
    }
    .tabs button.active {
      background: var(--panel-strong);
      color: #f7f1e6;
    }
    .panel { display: none; }
    .panel.active { display: block; }
    .field { margin-bottom: 12px; }
    label {
      display: block;
      font-size: 0.88rem;
      margin-bottom: 6px;
      color: var(--muted);
      font-weight: 600;
    }
    input {
      width: 100%;
      border-radius: 14px;
      border: 1px solid rgba(22, 51, 47, 0.14);
      background: rgba(255, 255, 255, 0.76);
      padding: 13px 14px;
      font-size: 0.98rem;
      color: var(--ink);
    }
    input:focus {
      outline: 2px solid rgba(183, 101, 47, 0.22);
      border-color: rgba(183, 101, 47, 0.45);
    }
    .cta {
      width: 100%;
      border-radius: 14px;
      padding: 14px;
      background: linear-gradient(135deg, #1d3f39, #10211e);
      color: #f7f1e6;
      font-weight: 700;
      font-size: 0.98rem;
    }
    .ghost {
      width: 100%;
      border-radius: 14px;
      padding: 14px;
      background: var(--accent-soft);
      color: var(--accent);
      font-weight: 700;
      margin-top: 10px;
    }
    .status-bar {
      background: rgba(255,255,255,0.72);
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
    }
    .feature-card, .flow-card {
      background: rgba(255, 251, 245, 0.72);
      backdrop-filter: blur(12px);
      padding: 22px;
    }
    .feature-list, .flow-list {
      display: grid;
      gap: 12px;
      margin-top: 14px;
    }
    .feature-item, .flow-item {
      border: 1px solid rgba(22, 51, 47, 0.08);
      border-radius: 18px;
      padding: 16px;
      background: rgba(255,255,255,0.62);
    }
    .feature-item strong, .flow-item strong {
      display: block;
      margin-bottom: 6px;
      font-family: "Baskerville", "Palatino Linotype", serif;
      font-size: 1.12rem;
    }
    .inline-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }
    .inline-button {
      border-radius: 999px;
      background: rgba(22, 51, 47, 0.08);
      color: var(--ink);
      padding: 10px 14px;
      text-decoration: none;
      font-weight: 600;
    }
    .muted-note {
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.5;
    }
    .hidden { display: none; }
    @media (max-width: 980px) {
      .hero, .content { grid-template-columns: 1fr; }
      .hero-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <article class="hero-copy">
        <div class="eyebrow">AlgoTrade Control Center</div>
        <h1>Research-first trade intelligence before live execution.</h1>
        <p>Review structure-based trigger lines, breakout events, historical signals, paper trades, and approval-gated access from one control surface built for future low-latency execution.</p>
        <div class="hero-grid">
          <div class="metric">
            <div class="metric-label">Pipeline</div>
            <div class="metric-value">Webhook → Redis → Worker</div>
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
        <div class="tabs">
          <button id="loginTab" class="active" type="button">Login</button>
          <button id="signupTab" type="button">Request Access</button>
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
            <button class="cta" type="submit">Enter Dashboard</button>
            <button class="ghost hidden" id="dashboardButton" type="button">Continue to Dashboard</button>
          </form>
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
          </form>
        </div>
        <div id="statusBar" class="status-bar">Approved users can access the protected dashboard. New signups require admin approval before login is enabled.</div>
      </aside>
    </section>
    <section class="content">
      <article class="feature-card">
        <div class="eyebrow" style="color: var(--accent);">What You Can Study</div>
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
        <div class="eyebrow" style="color: var(--accent);">Security and Flow</div>
        <h2>Access stays gated. Signal ingestion stays fast.</h2>
        <div class="flow-list">
          <div class="flow-item">
            <strong>1. Landing and identity</strong>
            Users request access here, then log in once an admin approves their account.
          </div>
          <div class="flow-item">
            <strong>2. Queue-first processing</strong>
            TradingView events are validated and queued immediately without waiting on analytics or notifications.
          </div>
          <div class="flow-item">
            <strong>3. Future execution readiness</strong>
            The same records are ready to link with real Zerodha orders later without a data-model reset.
          </div>
        </div>
        <div class="inline-actions">
          <a class="inline-button" href="/health">Health</a>
          <a class="inline-button" href="/dashboard">Dashboard</a>
          <a class="inline-button" href="/paper-trading/settings">Paper Settings</a>
        </div>
        <p class="muted-note">Two-factor authentication can be enabled after login from the dashboard security panel. Existing webhook ingestion remains separate and unaffected by user sign-in.</p>
      </article>
    </section>
  </div>
  <script>
    const statusBar = document.getElementById("statusBar");
    const loginTab = document.getElementById("loginTab");
    const signupTab = document.getElementById("signupTab");
    const loginPanel = document.getElementById("loginPanel");
    const signupPanel = document.getElementById("signupPanel");
    const twoFactorField = document.getElementById("twoFactorField");
    const dashboardButton = document.getElementById("dashboardButton");

    function setStatus(message, tone = "") {
      statusBar.textContent = message;
      statusBar.className = `status-bar ${tone}`;
    }

    function activateTab(tab) {
      const isLogin = tab === "login";
      loginTab.classList.toggle("active", isLogin);
      signupTab.classList.toggle("active", !isLogin);
      loginPanel.classList.toggle("active", isLogin);
      signupPanel.classList.toggle("active", !isLogin);
    }

    loginTab.addEventListener("click", () => activateTab("login"));
    signupTab.addEventListener("click", () => activateTab("signup"));

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
      dashboardButton.classList.remove("hidden");
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

    dashboardButton.addEventListener("click", () => {
      window.location.href = "/dashboard";
    });

    async function detectSession() {
      const response = await fetch("/auth/me");
      if (!response.ok) {
        return;
      }
      const user = await response.json();
      dashboardButton.classList.remove("hidden");
      setStatus(`Signed in as ${user.email}. Continue into the dashboard.`, "success");
    }

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
