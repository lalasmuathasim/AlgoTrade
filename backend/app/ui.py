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
        ("Dashboard", "/dashboard", "dashboard"),
        ("Configuration", "/configuration", "configuration"),
        ("Analytics", "/analytics", "analytics"),
    ]
    nav_html = "".join(
        (
            f'<a href="{href}" class="nav-link{" active" if key == active_nav else ""}">{label}</a>'
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
      --bg: #f3efe5;
      --panel: rgba(255,255,255,0.78);
      --panel-strong: rgba(18, 35, 33, 0.95);
      --line: #1d3a35;
      --muted: #576662;
      --accent: #ad5c2b;
      --accent-soft: rgba(173, 92, 43, 0.12);
      --ok: #0f766e;
      --warn: #b45309;
      --danger: #b42318;
      --shadow: 0 16px 40px rgba(31, 48, 43, 0.1);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--line);
      min-height: 100vh;
      background:
        radial-gradient(circle at top left, rgba(173,92,43,0.18), transparent 30%),
        radial-gradient(circle at top right, rgba(15,118,110,0.08), transparent 28%),
        linear-gradient(135deg, #ede4d3 0%, #f6f1e8 42%, #ecf4ef 100%);
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      background-image:
        linear-gradient(rgba(22, 51, 47, 0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(22, 51, 47, 0.03) 1px, transparent 1px);
      background-size: 40px 40px;
      pointer-events: none;
    }}
    .wrap {{ max-width: 1320px; margin: 0 auto; padding: 28px 20px 52px; position: relative; }}
    .hero {{
      background: linear-gradient(135deg, rgba(29,58,53,0.96), rgba(14,22,21,0.95));
      color: #f7f1e7;
      padding: 28px;
      border-radius: 24px;
      box-shadow: 0 20px 50px rgba(18,35,33,0.18);
      border: 1px solid rgba(255,255,255,0.08);
    }}
    .hero-top {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
      align-items: flex-start;
    }}
    .hero h1 {{
      margin: 0 0 10px;
      font-size: clamp(2rem, 3vw, 3.2rem);
      font-family: "Baskerville", "Palatino Linotype", serif;
    }}
    .hero p {{
      margin: 0;
      max-width: 760px;
      color: rgba(247, 241, 231, 0.84);
      line-height: 1.55;
    }}
    .hero-actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }}
    .hero-actions a, .hero-actions button, button, .button {{
      border: none;
      border-radius: 999px;
      padding: 10px 14px;
      text-decoration: none;
      cursor: pointer;
      font-weight: 700;
      font-size: 0.92rem;
      transition: transform 0.16s ease, opacity 0.16s ease;
    }}
    .hero-actions a {{
      background: rgba(255,255,255,0.09);
      color: #f7f1e7;
    }}
    .hero-actions button, button.primary, .button.primary {{
      background: #f7f1e7;
      color: #16332f;
    }}
    button.secondary, .button.secondary {{
      background: var(--accent-soft);
      color: var(--accent);
    }}
    .nav {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }}
    .nav-link {{
      padding: 10px 14px;
      border-radius: 999px;
      text-decoration: none;
      background: rgba(255,255,255,0.08);
      color: rgba(247,241,231,0.84);
      font-weight: 700;
      font-size: 0.92rem;
    }}
    .nav-link.active {{
      background: #f7f1e7;
      color: #16332f;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-top: 22px;
    }}
    .split {{
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 18px;
      margin-top: 18px;
    }}
    .panel {{
      background: var(--panel);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(29,58,53,0.12);
      border-radius: 18px;
      box-shadow: var(--shadow);
      padding: 18px;
      overflow: auto;
    }}
    .panel h2, .panel h3 {{
      margin: 0 0 12px;
      font-size: 1.16rem;
    }}
    .card {{
      background: var(--panel);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(29,58,53,0.12);
      border-radius: 18px;
      box-shadow: var(--shadow);
      padding: 18px;
    }}
    .label {{
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}
    .value {{
      margin-top: 10px;
      font-size: 2rem;
    }}
    .subvalue {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .status-box {{
      min-height: 52px;
      border-radius: 16px;
      border: 1px solid rgba(29,58,53,0.1);
      background: rgba(255,255,255,0.68);
      padding: 12px 14px;
      color: var(--muted);
    }}
    .status-box.success {{ color: var(--ok); }}
    .status-box.warn {{ color: var(--warn); }}
    .status-box.error {{ color: var(--danger); }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      background: rgba(15,118,110,0.12);
      color: var(--ok);
      font-size: 0.8rem;
      font-weight: 700;
    }}
    .badge.warn {{
      background: rgba(180,83,9,0.12);
      color: var(--warn);
    }}
    .badge.danger {{
      background: rgba(180,35,24,0.12);
      color: var(--danger);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      text-align: left;
      padding: 10px 8px;
      border-bottom: 1px solid rgba(29,58,53,0.1);
      font-size: 0.94rem;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-weight: 700;
    }}
    .field {{
      margin-bottom: 12px;
    }}
    label {{
      display: block;
      font-size: 0.84rem;
      color: var(--muted);
      margin-bottom: 6px;
      font-weight: 700;
    }}
    input, select, textarea {{
      width: 100%;
      border-radius: 12px;
      border: 1px solid rgba(29,58,53,0.14);
      padding: 12px 13px;
      font-size: 0.95rem;
      background: rgba(255,255,255,0.85);
      color: var(--line);
      font-family: inherit;
    }}
    textarea {{
      min-height: 132px;
      resize: vertical;
    }}
    .inline {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }}
    .stack {{
      display: grid;
      gap: 10px;
    }}
    .mono {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      word-break: break-all;
    }}
    .muted {{
      color: var(--muted);
    }}
    .empty {{
      color: var(--muted);
      font-style: italic;
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
      gap: 8px;
      align-items: center;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(22,51,47,0.06);
      color: var(--line);
      font-size: 0.88rem;
    }}
    .two-col {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
    }}
    @media (max-width: 960px) {{
      .split, .two-col {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="hero-top">
        <div>
          <h1>{escape(heading)}</h1>
          <p>{escape(subtitle)}</p>
        </div>
        <div class="hero-actions">
          <a href="/">Landing Page</a>
          <button id="logoutButton" type="button">Log Out</button>
        </div>
      </div>
      <nav class="nav">{nav_html}</nav>
    </section>
    {body_html}
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
