from html import escape


def render_app_shell(
    *,
    title: str,
    heading: str,
    subtitle: str,
    active_nav: str,
    body_html: str,
    script: str,
) -> str:
    nav_items = [
        ("Home", "/", "home"),
        ("Dashboard", "/dashboard", "dashboard"),
        ("Configuration", "/configuration", "configuration"),
        ("Analytics", "/analytics", "analytics"),
    ]
    nav_html = "".join(
        (
            f'<a href="{href}" class="workspace-link{" active" if key == active_nav else ""}">{label}</a>'
            for label, href, key in nav_items
        )
    )
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --bg-elevated: #eef3f9;
      --panel: rgba(255, 255, 255, 0.94);
      --panel-soft: rgba(250, 252, 255, 0.98);
      --panel-strong: rgba(246, 249, 253, 0.98);
      --line: rgba(75, 102, 138, 0.14);
      --line-strong: rgba(75, 102, 138, 0.22);
      --text: #122033;
      --muted: #60738b;
      --accent: #0f9b8e;
      --accent-soft: rgba(15, 155, 142, 0.1);
      --accent-alt: #3d7ef0;
      --ok: #0b8f63;
      --warn: #b8731d;
      --danger: #cf4545;
      --shadow: 0 24px 55px rgba(20, 34, 56, 0.1);
      --radius-lg: 24px;
      --radius-md: 18px;
      --radius-sm: 14px;
    }}
    * {{ box-sizing: border-box; }}
    html {{ color-scheme: light; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: "IBM Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(61,126,240,0.12), transparent 22%),
        radial-gradient(circle at 82% 12%, rgba(15,155,142,0.08), transparent 24%),
        linear-gradient(180deg, #f7f9fc 0%, #edf2f8 100%);
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      background-image:
        linear-gradient(rgba(61,126,240,0.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(61,126,240,0.035) 1px, transparent 1px);
      background-size: 28px 28px;
      mask-image: linear-gradient(180deg, rgba(0,0,0,0.3), transparent 92%);
      pointer-events: none;
      z-index: 0;
    }}
    a {{
      color: inherit;
    }}
    .app-shell {{
      position: relative;
      z-index: 1;
      min-height: 100vh;
    }}
    .wrap {{
      max-width: 1380px;
      margin: 0 auto;
      padding: 24px 20px 56px;
      position: relative;
    }}
    .masthead {{
      display: grid;
      grid-template-columns: minmax(260px, 420px) 1fr;
      gap: 28px;
      margin-bottom: 18px;
      align-items: center;
      padding: 18px 8px 10px;
    }}
    .brand {{
      display: grid;
      gap: 4px;
    }}
    .brand-mark {{
      font-size: 0.78rem;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--accent);
      font-weight: 700;
    }}
    .brand-title {{
      margin-top: 8px;
      font-family: "Space Grotesk", "Avenir Next", sans-serif;
      font-size: clamp(2.1rem, 4vw, 3.1rem);
      font-weight: 700;
      line-height: 0.95;
      letter-spacing: -0.05em;
    }}
    .brand-copy {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.5;
      max-width: 420px;
    }}
    .workspace-nav {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
      min-width: 0;
      align-items: center;
    }}
    .workspace-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 58px;
      padding: 0 20px;
      border-radius: 18px;
      text-decoration: none;
      color: #26405f;
      background: transparent;
      border: 1px solid transparent;
      font-family: "Space Grotesk", "Avenir Next", sans-serif;
      font-size: clamp(0.94rem, 1.15vw, 1.15rem);
      font-weight: 600;
      letter-spacing: -0.02em;
      transition: background 0.16s ease, border-color 0.16s ease, transform 0.16s ease, color 0.16s ease, box-shadow 0.16s ease;
    }}
    .workspace-link:hover {{
      background: rgba(61, 126, 240, 0.08);
      border-color: rgba(61, 126, 240, 0.14);
      color: #0d2137;
      transform: translateY(-1px);
    }}
    .workspace-link.active {{
      background: linear-gradient(180deg, rgba(238,248,255,0.98), rgba(230,242,252,0.98));
      border-color: rgba(15, 155, 142, 0.22);
      color: #0e1f33;
      box-shadow:
        inset 0 0 0 1px rgba(255,255,255,0.7),
        0 10px 24px rgba(61, 126, 240, 0.08);
    }}
    .main-shell {{
      min-width: 0;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 20px;
      padding: 22px 24px;
      border-radius: var(--radius-lg);
      border: 1px solid var(--line);
      background:
        linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(246, 249, 253, 0.96)),
        var(--panel);
      box-shadow: var(--shadow);
    }}
    .topbar-copy {{
      min-width: 0;
    }}
    .eyebrow {{
      margin: 0 0 10px;
      color: var(--accent);
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }}
    .topbar h1 {{
      margin: 0;
      font-family: "Space Grotesk", "Avenir Next", sans-serif;
      font-size: clamp(2rem, 3vw, 3rem);
      line-height: 1.02;
      letter-spacing: -0.03em;
    }}
    .topbar p {{
      margin: 12px 0 0;
      max-width: 840px;
      color: var(--muted);
      font-size: 1rem;
      line-height: 1.65;
    }}
    .topbar-actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    button,
    .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      min-height: 42px;
      padding: 10px 14px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
      color: var(--text);
      text-decoration: none;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      transition: transform 0.16s ease, border-color 0.16s ease, background 0.16s ease, opacity 0.16s ease;
    }}
    button:hover,
    .button:hover {{
      transform: translateY(-1px);
      border-color: var(--line-strong);
      background: rgba(245,248,252,0.98);
    }}
    button.primary,
    .button.primary {{
      background: linear-gradient(135deg, rgba(15, 155, 142, 0.96), rgba(18, 125, 164, 0.94));
      border-color: rgba(15,155,142,0.28);
      color: #ffffff;
      box-shadow: 0 10px 24px rgba(15, 155, 142, 0.15);
    }}
    button.secondary,
    .button.secondary {{
      background: rgba(61, 126, 240, 0.08);
      border-color: rgba(61, 126, 240, 0.14);
      color: #24416d;
    }}
    button.ghost,
    .button.ghost {{
      background: transparent;
      color: var(--muted);
    }}
    button:disabled,
    .button:disabled {{
      opacity: 0.56;
      cursor: not-allowed;
      transform: none;
    }}
    .content {{
      display: grid;
      gap: 18px;
      margin-top: 18px;
      min-width: 0;
    }}
    .metric-strip {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 1px;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 22px;
      background: var(--line);
      box-shadow: var(--shadow);
    }}
    .metric {{
      min-height: 118px;
      padding: 18px 18px 16px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(247, 250, 254, 0.98)),
        var(--panel-soft);
    }}
    .metric-label {{
      color: var(--muted);
      font-size: 0.74rem;
      font-weight: 700;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }}
    .metric-value {{
      margin-top: 14px;
      font-family: "Space Grotesk", "Avenir Next", sans-serif;
      font-size: clamp(1.55rem, 2vw, 2.25rem);
      line-height: 1;
      letter-spacing: -0.04em;
    }}
    .metric-meta {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 0.88rem;
      line-height: 1.45;
    }}
    .layout-main-aside,
    .layout-halves,
    .layout-thirds {{
      display: grid;
      gap: 18px;
      align-items: start;
    }}
    .layout-main-aside {{
      grid-template-columns: minmax(0, 1.58fr) minmax(260px, 0.72fr);
    }}
    .layout-halves {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .layout-thirds {{
      grid-template-columns: 1.15fr 0.85fr 0.85fr;
    }}
    .rail-stack {{
      display: grid;
      gap: 18px;
      align-content: start;
    }}
    .panel {{
      min-width: 0;
      padding: 18px;
      border-radius: 22px;
      border: 1px solid var(--line);
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(247, 250, 254, 0.98)),
        var(--panel);
      box-shadow: var(--shadow);
      overflow: hidden;
    }}
    .panel-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 14px;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }}
    .panel-header h2,
    .panel-header h3,
    .panel h2,
    .panel h3 {{
      margin: 0;
      font-size: 1.08rem;
      letter-spacing: -0.02em;
    }}
    .panel-copy {{
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.55;
    }}
    .panel-actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .panel hr {{
      border: none;
      border-top: 1px solid var(--line);
      margin: 16px 0;
    }}
    .stack {{
      display: grid;
      gap: 12px;
      align-content: start;
    }}
    .inline {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
      min-width: 0;
    }}
    .status-box {{
      min-height: 52px;
      border-radius: 16px;
      border: 1px solid rgba(75, 102, 138, 0.12);
      background: rgba(248, 251, 255, 0.96);
      padding: 12px 14px;
      color: var(--muted);
      line-height: 1.55;
    }}
    .status-box.success {{ color: var(--ok); border-color: rgba(49,211,139,0.24); }}
    .status-box.warn {{ color: var(--warn); border-color: rgba(255,184,77,0.22); }}
    .status-box.error {{ color: var(--danger); border-color: rgba(255,114,114,0.24); }}
    .badge {{
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 4px 10px;
      border-radius: 999px;
      background: rgba(49, 211, 139, 0.12);
      color: var(--ok);
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .badge.warn {{
      background: rgba(255, 184, 77, 0.12);
      color: var(--warn);
    }}
    .badge.danger {{
      background: rgba(255, 114, 114, 0.12);
      color: var(--danger);
    }}
    .field {{
      margin-bottom: 12px;
    }}
    .field-help {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 0.82rem;
      line-height: 1.45;
    }}
    label {{
      display: block;
      margin-bottom: 7px;
      color: var(--muted);
      font-size: 0.8rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    input,
    select,
    textarea {{
      width: 100%;
      border-radius: 14px;
      border: 1px solid rgba(122, 151, 185, 0.16);
      padding: 12px 13px;
      background: rgba(248, 251, 255, 0.98);
      color: var(--text);
      font: inherit;
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.7);
    }}
    input:focus,
    select:focus,
    textarea:focus {{
      outline: none;
      border-color: rgba(0, 194, 168, 0.32);
      box-shadow: 0 0 0 3px rgba(0, 194, 168, 0.08);
    }}
    textarea {{
      min-height: 140px;
      resize: vertical;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 0;
      table-layout: fixed;
    }}
    th,
    td {{
      padding: 11px 8px;
      border-bottom: 1px solid rgba(122, 151, 185, 0.12);
      text-align: left;
      vertical-align: top;
      font-size: 0.93rem;
      white-space: normal;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    th {{
      color: var(--muted);
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}
    tbody tr:hover {{
      background: rgba(92, 167, 255, 0.035);
    }}
    .list {{
      display: grid;
      gap: 8px;
      margin: 0;
      padding: 0;
      list-style: none;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 34px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(61, 126, 240, 0.08);
      border: 1px solid rgba(61, 126, 240, 0.08);
      color: #26405f;
      font-size: 0.88rem;
    }}
    .pill-button {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 38px;
      padding: 8px 12px;
      border: 1px solid rgba(61, 126, 240, 0.1);
      border-radius: 999px;
      background: rgba(61, 126, 240, 0.08);
      color: #26405f;
      font: inherit;
      font-size: 0.88rem;
      cursor: pointer;
      transition: transform 0.16s ease, background 0.16s ease, border-color 0.16s ease;
    }}
    .pill-button:hover {{
      transform: translateY(-1px);
      background: rgba(61, 126, 240, 0.12);
      border-color: rgba(61, 126, 240, 0.18);
    }}
    .pill-button:disabled {{
      opacity: 0.56;
      cursor: not-allowed;
      transform: none;
    }}
    .table-link {{
      appearance: none;
      border: none;
      background: transparent;
      padding: 0;
      margin: 0;
      color: #24416d;
      font: inherit;
      font-size: 0.88rem;
      font-weight: 600;
      cursor: pointer;
      text-align: left;
      text-decoration: none;
      transition: color 0.16s ease, opacity 0.16s ease;
    }}
    .table-link:hover {{
      color: var(--accent);
    }}
    .table-link.subtle {{
      font-size: 0.83rem;
      font-weight: 500;
      color: var(--muted);
    }}
    .table-actions {{
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .inline-note {{
      margin: 0 0 12px;
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.6;
    }}
    .inline-note.success {{ color: var(--ok); }}
    .inline-note.warn {{ color: var(--warn); }}
    .inline-note.error {{ color: var(--danger); }}
    .readiness-links {{
      display: flex;
      gap: 10px 16px;
      flex-wrap: wrap;
      margin-top: 10px;
    }}
    .readiness-link {{
      appearance: none;
      border: none;
      background: transparent;
      padding: 0;
      margin: 0;
      color: #26405f;
      font: inherit;
      font-size: 0.88rem;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      text-decoration: none;
      transition: color 0.16s ease, opacity 0.16s ease;
    }}
    .readiness-link:hover {{
      color: var(--accent);
    }}
    .readiness-mark {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 18px;
      height: 18px;
      border-radius: 999px;
      font-size: 0.76rem;
      font-weight: 700;
      background: rgba(75, 102, 138, 0.1);
      color: var(--muted);
      flex: 0 0 auto;
    }}
    .readiness-mark.ok {{
      background: rgba(49, 211, 139, 0.12);
      color: var(--ok);
    }}
    .readiness-mark.warn {{
      background: rgba(255, 184, 77, 0.14);
      color: var(--warn);
    }}
    .mono {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      word-break: break-word;
    }}
    .muted {{
      color: var(--muted);
    }}
    .empty {{
      color: var(--muted);
      font-style: italic;
      padding: 20px 8px;
    }}
    .hidden {{
      display: none !important;
    }}
    @media (max-width: 960px) {{
      .masthead {{
        grid-template-columns: 1fr;
        align-items: start;
        padding-bottom: 4px;
      }}
      .workspace-nav {{
        justify-content: flex-start;
      }}
      .workspace-link {{
        min-height: 48px;
        padding: 0 16px;
        border-radius: 14px;
      }}
      .layout-main-aside,
      .layout-halves,
      .layout-thirds {{
        grid-template-columns: 1fr;
      }}
      .topbar {{
        padding: 18px;
      }}
    }}
  </style>
</head>
<body>
  <div class="app-shell">
    <div class="wrap">
      <section class="masthead">
        <div class="brand">
        <div class="brand-mark">Qubitx</div>
        <div class="brand-title">Market Control</div>
        <div class="brand-copy">A focused trading workspace for watchlists, structure tracking, runtime readiness, and review-grade reporting.</div>
        </div>
        <nav class="workspace-nav">{nav_html}</nav>
      </section>
      <main class="main-shell">
      <section class="topbar">
        <div class="topbar-copy">
          <div class="eyebrow">Trading Workspace</div>
          <h1>{escape(heading)}</h1>
          <p>{escape(subtitle)}</p>
        </div>
        <div class="topbar-actions">
          <button id="logoutButton" class="secondary" type="button">Log Out</button>
        </div>
      </section>
      <div class="content">
        {body_html}
      </div>
      </main>
    </div>
  </div>
  <script>
    async function apiGet(url) {{
      const res = await fetch(url);
      const contentType = res.headers.get("content-type") || "";
      const data = contentType.includes("application/json") ? await res.json() : await res.text();
      if (!res.ok) {{
        throw new Error(data.detail || data.message || "Request failed");
      }}
      return data;
    }}
    async function apiSend(url, method, payload) {{
      const res = await fetch(url, {{
        method,
        headers: {{ "Content-Type": "application/json" }},
        body: payload ? JSON.stringify(payload) : undefined,
      }});
      const data = await res.json();
      if (!res.ok) {{
        throw new Error(data.detail || data.message || "Request failed");
      }}
      return data;
    }}
    function renderMetricStrip(element, items) {{
      element.innerHTML = items.map((item) => `
        <article class="metric">
          <div class="metric-label">${{item.label}}</div>
          <div class="metric-value">${{item.value ?? "-"}}</div>
          <div class="metric-meta">${{item.meta ?? ""}}</div>
        </article>
      `).join("");
    }}
    function renderTable(element, headers, rows) {{
      const head = `<tr>${{headers.map((header) => `<th>${{header}}</th>`).join("")}}</tr>`;
      const body = rows.length
        ? rows.map((row) => `<tr>${{row.map((cell) => `<td>${{cell ?? ""}}</td>`).join("")}}</tr>`).join("")
        : `<tr><td colspan="${{headers.length}}" class="empty">No rows to display.</td></tr>`;
      element.innerHTML = `<thead>${{head}}</thead><tbody>${{body}}</tbody>`;
    }}
    function setBox(id, message, tone = "") {{
      const element = document.getElementById(id);
      element.textContent = message;
      element.className = `status-box ${{tone}}`;
    }}
    document.getElementById("logoutButton").addEventListener("click", async () => {{
      await apiSend("/auth/logout", "POST");
      window.location.href = "/";
    }});
    {script}
  </script>
</body>
</html>
"""
