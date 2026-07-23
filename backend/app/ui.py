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
    body.is-routing .main-shell,
    body.is-routing .masthead {{
      opacity: 0.72;
      transition: opacity 0.16s ease;
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
    .workspace-nav-spacer {{
      flex: 1 1 auto;
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
    .workspace-link-action {{
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
    }}
    .workspace-link-action:hover {{
      background: transparent;
      border-color: transparent;
      color: #0d2137;
      box-shadow: none;
    }}
    .workspace-user {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      min-height: 40px;
      margin-left: 6px;
      color: var(--muted);
      font-size: 0.9rem;
      white-space: nowrap;
    }}
    .workspace-user-name {{
      color: #2b435f;
      font-weight: 500;
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
    button.is-busy,
    .button.is-busy {{
      position: relative;
      opacity: 0.92;
    }}
    button.is-busy::before,
    .button.is-busy::before {{
      content: "";
      width: 0.72rem;
      height: 0.72rem;
      border-radius: 999px;
      border: 2px solid currentColor;
      border-right-color: transparent;
      opacity: 0.7;
      animation: button-spin 0.78s linear infinite;
    }}
    button.is-success,
    .button.is-success {{
      border-color: rgba(49, 211, 139, 0.24);
      box-shadow: 0 0 0 1px rgba(49, 211, 139, 0.1);
    }}
    button.is-success::before,
    .button.is-success::before {{
      content: "✓";
      font-size: 0.82rem;
      line-height: 1;
      color: var(--ok);
    }}
    button.is-error,
    .button.is-error {{
      border-color: rgba(255, 114, 114, 0.24);
      box-shadow: 0 0 0 1px rgba(255, 114, 114, 0.08);
    }}
    button.is-error::before,
    .button.is-error::before {{
      content: "!";
      font-size: 0.8rem;
      line-height: 1;
      color: var(--danger);
    }}
    @keyframes button-spin {{
      to {{ transform: rotate(360deg); }}
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
    .builder-steps {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
      align-items: start;
    }}
    .builder-step {{
      min-width: 0;
      padding: 18px;
      border-radius: 18px;
      border: 1px solid rgba(75, 102, 138, 0.12);
      background: linear-gradient(180deg, rgba(250, 252, 255, 0.98), rgba(245, 249, 253, 0.96));
      transition: opacity 0.16s ease, transform 0.16s ease;
    }}
    .builder-step.is-disabled {{
      opacity: 0.56;
    }}
    .builder-step h3 {{
      margin: 10px 0 0;
      font-size: 1rem;
      letter-spacing: -0.02em;
    }}
    .builder-step .inline-note {{
      margin-top: 10px;
    }}
    .step-tag {{
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      padding: 4px 10px;
      border-radius: 999px;
      background: rgba(61, 126, 240, 0.08);
      color: #31527c;
      font-size: 0.74rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
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
      font-size: 0.92rem;
      line-height: 1.55;
    }}
    .status-box.success {{ color: var(--ok); border-color: rgba(49,211,139,0.24); }}
    .status-box.warn {{ color: var(--warn); border-color: rgba(255,184,77,0.22); }}
    .status-box.error {{ color: var(--danger); border-color: rgba(255,114,114,0.24); }}
    #readinessStatus.status-box {{
      font-size: 0.84rem;
      line-height: 1.45;
    }}
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
    .table-shell {{
      display: grid;
      gap: 10px;
      min-width: 0;
    }}
    .table-toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .table-toolbar-actions {{
      display: flex;
      align-items: flex-start;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
      margin-left: auto;
      min-width: min(100%, 840px);
    }}
    .table-toolbar-search {{
      position: relative;
      display: flex;
      flex-direction: column;
      align-self: flex-start;
      min-width: min(220px, 100%);
      max-width: 260px;
      flex: 0 1 240px;
      padding-bottom: 18px;
    }}
    .table-toolbar-copy {{
      margin: 0;
      color: var(--muted);
      font-size: 0.82rem;
      line-height: 1.45;
    }}
    .table-helper-copy {{
      margin: 0 0 2px;
      color: var(--muted);
      font-size: 0.82rem;
      line-height: 1.45;
    }}
    .table-toolbar-copy.success {{ color: var(--ok); }}
    .table-toolbar-copy.warn {{ color: var(--warn); }}
    .table-toolbar-copy.error {{ color: var(--danger); }}
    .table-toggle {{
      min-height: 34px;
      padding: 7px 12px;
      font-size: 0.82rem;
      font-weight: 600;
    }}
    .subtle-input {{
      min-height: 34px;
      width: auto;
      min-width: 128px;
      padding: 7px 10px;
      border-radius: 12px;
      border: 1px solid rgba(122, 151, 185, 0.16);
      background: rgba(248, 251, 255, 0.98);
      color: var(--text);
      font-size: 0.82rem;
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.7);
    }}
    .table-scroll-frame {{
      min-width: 0;
      overflow: auto;
      border: 1px solid rgba(122, 151, 185, 0.14);
      border-radius: 16px;
      background: rgba(250, 252, 255, 0.96);
    }}
    .table-scroll-frame.is-collapsed {{
      max-height: 360px;
    }}
    .table-scroll-frame table {{
      min-width: var(--table-min-width, 760px);
      table-layout: auto;
    }}
    thead th {{
      position: sticky;
      top: 0;
      z-index: 2;
      background: rgba(247, 250, 254, 0.97);
      box-shadow: inset 0 -1px 0 rgba(122, 151, 185, 0.14);
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
    .table-filter {{
      width: 100%;
      min-height: 34px;
      padding: 7px 10px;
      border-radius: 12px;
      border: 1px solid rgba(122, 151, 185, 0.18);
      background: rgba(255, 255, 255, 0.94);
      color: var(--text);
      font-size: 0.82rem;
    }}
    .table-filter-shell {{
      position: relative;
      width: 100%;
    }}
    .table-filter-input {{
      position: relative;
      z-index: 2;
      background: transparent;
    }}
    .table-filter-ghost {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      pointer-events: none;
      padding: 7px 10px;
      font-size: 0.82rem;
      color: rgba(18, 32, 51, 0.28);
      white-space: nowrap;
      overflow: hidden;
    }}
    .table-filter-ghost-query {{
      visibility: hidden;
      white-space: pre;
      flex: 0 0 auto;
    }}
    .table-filter-ghost-suffix {{
      white-space: pre;
      flex: 0 0 auto;
    }}
    .table-filter-measure {{
      position: absolute;
      visibility: hidden;
      white-space: pre;
      inset: auto;
      font-size: 0.82rem;
      font-family: inherit;
      font-weight: 400;
      padding: 0;
      margin: 0;
    }}
    .table-filter-suggestions {{
      position: absolute;
      top: calc(100% + 6px);
      left: 0;
      right: 0;
      z-index: 5;
      display: grid;
      gap: 2px;
      max-height: 220px;
      overflow: auto;
      padding: 8px;
      border-radius: 14px;
      border: 1px solid rgba(122, 151, 185, 0.18);
      background: rgba(255, 255, 255, 0.98);
      box-shadow: 0 18px 34px rgba(20, 34, 56, 0.12);
      text-align: left;
    }}
    .table-filter-suggestion {{
      display: flex;
      justify-content: flex-start;
      align-items: center;
      width: 100%;
      padding: 9px 10px;
      border: none;
      border-radius: 10px;
      background: transparent;
      color: var(--text);
      cursor: pointer;
      font: inherit;
      font-size: 0.88rem;
      text-align: left;
    }}
    .table-filter-suggestion:hover,
    .table-filter-suggestion.is-active {{
      background: rgba(61, 126, 240, 0.08);
      color: #163150;
      transform: none;
    }}
    .table-filter-meta {{
      position: absolute;
      top: calc(100% - 14px);
      right: 2px;
      color: var(--muted);
      font-size: 0.7rem;
      line-height: 1;
      white-space: nowrap;
      text-align: right;
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
    .validation-summary {{
      margin: 0 0 12px;
      padding: 0 0 10px;
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.55;
      border-bottom: 1px solid rgba(122, 151, 185, 0.14);
    }}
    .validation-summary.success {{ color: var(--ok); }}
    .validation-summary.warn {{ color: var(--warn); }}
    .validation-summary.error {{ color: var(--danger); }}
    .compact-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px 16px;
      align-items: start;
    }}
    .compact-grid .field {{
      margin-bottom: 0;
    }}
    .guide-list {{
      display: grid;
      gap: 8px;
      margin: 14px 0 0;
      padding-left: 18px;
      color: var(--muted);
      font-size: 0.86rem;
      line-height: 1.5;
    }}
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
      .builder-steps {{
        grid-template-columns: 1fr;
      }}
      .compact-grid {{
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
        <nav class="workspace-nav">{nav_html}<span id="workspaceNavSpacer" class="workspace-nav-spacer hidden"></span><div id="workspaceUser" class="workspace-user hidden"><span id="workspaceGreeting" class="workspace-user-name"></span><button id="logoutNavButton" class="workspace-link workspace-link-action" type="button">Log out</button></div></nav>
      </section>
      <main class="main-shell">
      <section class="topbar">
        <div class="topbar-copy">
          <div class="eyebrow">Trading Workspace</div>
          <h1>{escape(heading)}</h1>
          <p>{escape(subtitle)}</p>
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
      const contentType = res.headers.get("content-type") || "";
      const data = contentType.includes("application/json") ? await res.json() : await res.text();
      if (!res.ok) {{
        const message = typeof data === "string"
          ? data
          : data.detail || data.message || "Request failed";
        throw new Error(message);
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
    function tablePlainText(value) {{
      if (value == null) {{
        return "";
      }}
      const buffer = document.createElement("div");
      buffer.innerHTML = String(value);
      return (buffer.textContent || buffer.innerText || "").trim();
    }}
    function updateTableFilterGhost(slot, query, suggestions) {{
      const querySpan = slot.querySelector(".table-filter-ghost-query");
      const suffixSpan = slot.querySelector(".table-filter-ghost-suffix");
      const firstMatch = Array.isArray(suggestions)
        ? suggestions.find((item) => item.toLowerCase().startsWith((query || "").toLowerCase()))
        : null;
      querySpan.textContent = query || "";
      if (firstMatch && query && firstMatch.length > query.length) {{
        suffixSpan.textContent = firstMatch.slice(query.length);
      }} else {{
        suffixSpan.textContent = "";
      }}
    }}
    function renderTableSearchSuggestions(slot, state, filterConfig) {{
      const suggestionsPanel = slot.querySelector(".table-filter-suggestions");
      if (!suggestionsPanel) {{
        return;
      }}
      const query = (state.query || "").trim().toLowerCase();
      const suggestions = Array.isArray(state.suggestions) ? state.suggestions : [];
      const matches = suggestions
        .filter((item) => !query || item.toLowerCase().includes(query))
        .slice(0, 8);
      slot._visibleSuggestions = matches;
      updateTableFilterGhost(slot, state.query || "", suggestions);
      if (!matches.length || !slot._showSuggestions) {{
        suggestionsPanel.classList.add("hidden");
        suggestionsPanel.innerHTML = "";
        return;
      }}
      suggestionsPanel.classList.remove("hidden");
      suggestionsPanel.innerHTML = matches.map((item, index) => `
        <button class="table-filter-suggestion${{index === 0 ? " is-active" : ""}}" type="button" data-suggestion-value="${{item}}">
          ${{item}}
        </button>
      `).join("");
      suggestionsPanel.querySelectorAll(".table-filter-suggestion").forEach((button) => {{
        button.addEventListener("mousedown", (event) => {{
          event.preventDefault();
          const value = button.dataset.suggestionValue || "";
          state.query = value;
          slot.querySelector(".table-filter-input").value = value;
          slot._showSuggestions = false;
          renderTableFromState(slot._tableElement);
        }});
      }});
    }}
    function ensureTableSearch(element) {{
      const state = element._tableState || null;
      const toolbar = element.closest(".table-shell")?.querySelector(".table-toolbar");
      const actions = toolbar?.querySelector(".table-toolbar-actions") || toolbar;
      if (!toolbar || !actions || !state) {{
        return null;
      }}

      const filterConfig = state.options?.symbolFilter;
      let slot = actions.querySelector(`[data-table-filter-for="${{element.id}}"]`);
      if (!filterConfig?.enabled || !element.id) {{
        if (slot) {{
          slot.remove();
        }}
        return null;
      }}

      if (!slot) {{
        slot = document.createElement("div");
        slot.className = "table-toolbar-search";
        slot.dataset.tableFilterFor = element.id;
        slot.innerHTML = `
          <div class="table-filter-shell">
            <div class="table-filter-ghost">
              <span class="table-filter-ghost-query"></span><span class="table-filter-ghost-suffix"></span>
            </div>
            <input class="table-filter table-filter-input" type="search" autocomplete="off" spellcheck="false" />
            <span class="table-filter-measure"></span>
            <div class="table-filter-suggestions hidden"></div>
          </div>
          <span class="table-filter-meta"></span>
        `;
        actions.prepend(slot);
      }}

      slot._tableElement = element;
      const input = slot.querySelector(".table-filter-input");
      const meta = slot.querySelector(".table-filter-meta");
      const suggestions = Array.from(new Set(
        state.rows
          .map((row) => tablePlainText(row[filterConfig.columnIndex]))
          .filter(Boolean),
      )).sort((left, right) => left.localeCompare(right));
      state.suggestions = suggestions;
      input.placeholder = filterConfig.placeholder || "Filter symbols";
      input.value = state.query || "";
      if (slot._showSuggestions == null) {{
        slot._showSuggestions = false;
      }}
      input.oninput = () => {{
        state.query = input.value;
        slot._showSuggestions = true;
        renderTableFromState(element);
      }};
      input.onfocus = () => {{
        slot._showSuggestions = true;
        renderTableSearchSuggestions(slot, state, filterConfig);
      }};
      input.onblur = () => {{
        window.setTimeout(() => {{
          slot._showSuggestions = false;
          renderTableSearchSuggestions(slot, state, filterConfig);
        }}, 120);
      }};
      input.onkeydown = (event) => {{
        if (event.key === "Escape") {{
          slot._showSuggestions = false;
          renderTableSearchSuggestions(slot, state, filterConfig);
          return;
        }}
        if (event.key === "Enter") {{
          const matches = Array.isArray(slot._visibleSuggestions) ? slot._visibleSuggestions : [];
          if (matches.length && input.value.trim()) {{
            event.preventDefault();
            state.query = matches[0];
            input.value = matches[0];
            slot._showSuggestions = false;
            renderTableFromState(element);
          }}
        }}
      }};

      const filteredCount = state.filteredRows?.length ?? state.rows.length;
      meta.textContent = `${{filteredCount}} of ${{state.rows.length}}`;
      renderTableSearchSuggestions(slot, state, filterConfig);
      return slot;
    }}
    function renderTableFromState(element) {{
      const state = element._tableState;
      if (!state) {{
        return;
      }}
      const query = (state.query || "").trim().toLowerCase();
      const filterConfig = state.options?.symbolFilter;
      const filteredRows = query && filterConfig?.enabled
        ? state.rows.filter((row) => tablePlainText(row[filterConfig.columnIndex]).toLowerCase().includes(query))
        : state.rows;
      state.filteredRows = filteredRows;

      const head = `<tr>${{state.headers.map((header) => `<th>${{header}}</th>`).join("")}}</tr>`;
      const body = filteredRows.length
        ? filteredRows.map((row) => `<tr>${{row.map((cell) => `<td>${{cell ?? ""}}</td>`).join("")}}</tr>`).join("")
        : `<tr><td colspan="${{state.headers.length}}" class="empty">${{query ? "No matching symbols." : "No rows to display."}}</td></tr>`;
      element.innerHTML = `<thead>${{head}}</thead><tbody>${{body}}</tbody>`;
      ensureTableSearch(element);
    }}
    function renderTable(element, headers, rows, options = {{}}) {{
      const previousState = element._tableState || {{}};
      element._tableState = {{
        headers,
        rows,
        options,
        query: previousState.query || "",
        filteredRows: rows,
      }};
      renderTableFromState(element);
    }}
    function bindCollapsibleTable({{ buttonId, frameId, tableId, previewRows = 8 }}) {{
      const button = document.getElementById(buttonId);
      const frame = document.getElementById(frameId);
      const table = document.getElementById(tableId);
      if (!button || !frame || !table) {{
        return () => {{}};
      }}

      const sync = () => {{
        const totalRows = Array.isArray(table._tableState?.rows) ? table._tableState.rows.length : table.querySelectorAll("tbody tr").length;
        const needsToggle = totalRows > previewRows;
        if (!needsToggle) {{
          button.classList.add("hidden");
          frame.classList.add("is-collapsed");
          button.dataset.expanded = "false";
          button.setAttribute("aria-expanded", "false");
          return;
        }}

        button.classList.remove("hidden");
        const expanded = button.dataset.expanded === "true";
        frame.classList.toggle("is-collapsed", !expanded);
        button.setAttribute("aria-expanded", expanded ? "true" : "false");
        button.textContent = expanded ? "Collapse table" : "Expand table";
      }};

      button.dataset.expanded = "false";
      button.addEventListener("click", () => {{
        button.dataset.expanded = button.dataset.expanded === "true" ? "false" : "true";
        sync();
      }});

      sync();
      return sync;
    }}
    function setBox(id, message, tone = "") {{
      const element = document.getElementById(id);
      element.textContent = message;
      element.className = `status-box ${{tone}}`;
    }}
    function setAsyncButtonState(button, state, label) {{
      if (!button) {{
        return;
      }}
      if (!button.dataset.defaultLabel) {{
        button.dataset.defaultLabel = button.textContent.trim();
      }}
      button.classList.remove("is-busy", "is-success", "is-error");
      if (state === "idle") {{
        button.disabled = false;
        button.textContent = button.dataset.defaultLabel;
        return;
      }}
      button.disabled = state === "busy";
      if (label) {{
        button.textContent = label;
      }}
      if (state === "busy") {{
        button.classList.add("is-busy");
        return;
      }}
      button.classList.add(state === "success" ? "is-success" : "is-error");
      window.setTimeout(() => {{
        button.classList.remove("is-success", "is-error");
        button.disabled = false;
        button.textContent = button.dataset.defaultLabel || button.textContent;
      }}, 1400);
    }}
    async function runButtonAction(buttonOrId, action, options = {{}}) {{
      const button = typeof buttonOrId === "string" ? document.getElementById(buttonOrId) : buttonOrId;
      const pendingLabel = options.pendingLabel || "Working...";
      const successLabel = options.successLabel || "Done";
      const errorLabel = options.errorLabel || "Try again";
      setAsyncButtonState(button, "busy", pendingLabel);
      try {{
        const result = await action();
        setAsyncButtonState(button, "success", successLabel);
        return result;
      }} catch (error) {{
        setAsyncButtonState(button, "error", errorLabel);
        throw error;
      }}
    }}
    function formatWorkspaceName(user) {{
      const fullName = (user?.full_name || "").trim();
      if (fullName) {{
        return fullName;
      }}
      const email = (user?.email || "").trim();
      if (!email) {{
        return "there";
      }}
      const localPart = email.split("@")[0] || email;
      return localPart
        .replace(/[._-]+/g, " ")
        .split(" ")
        .filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
    }}
    async function syncWorkspaceUser() {{
      const workspaceUser = document.getElementById("workspaceUser");
      const workspaceNavSpacer = document.getElementById("workspaceNavSpacer");
      const greeting = document.getElementById("workspaceGreeting");
      try {{
        const user = await apiGet("/auth/me");
        greeting.textContent = `Hi ${{formatWorkspaceName(user)}}`;
        workspaceNavSpacer.classList.remove("hidden");
        workspaceUser.classList.remove("hidden");
      }} catch (_error) {{
        workspaceNavSpacer.classList.add("hidden");
        workspaceUser.classList.add("hidden");
        greeting.textContent = "";
      }}
    }}
    function isWorkspaceNavClick(event, link) {{
      if (!link || !link.classList.contains("workspace-link")) {{
        return false;
      }}
      if (event.defaultPrevented || event.button !== 0) {{
        return false;
      }}
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {{
        return false;
      }}
      if (link.target && link.target !== "_self") {{
        return false;
      }}
      const url = new URL(link.href, window.location.origin);
      return url.origin === window.location.origin;
    }}
    async function navigateWorkspace(url, options = {{}}) {{
      const nextUrl = new URL(url, window.location.origin);
      const currentUrl = new URL(window.location.href);
      if (!options.force && nextUrl.pathname === currentUrl.pathname && nextUrl.search === currentUrl.search) {{
        return;
      }}
      document.body.classList.add("is-routing");
      try {{
        const response = await fetch(nextUrl.toString(), {{
          headers: {{ "X-Qubitx-Navigation": "workspace" }},
          credentials: "same-origin",
        }});
        if (!response.ok) {{
          throw new Error(`Navigation failed with status ${{response.status}}`);
        }}
        const html = await response.text();
        if (options.replace) {{
          window.history.replaceState({{ qubitx: true }}, "", nextUrl.toString());
        }} else {{
          window.history.pushState({{ qubitx: true }}, "", nextUrl.toString());
        }}
        document.open();
        document.write(html);
        document.close();
      }} catch (_error) {{
        window.location.href = nextUrl.toString();
      }}
    }}
    function bindWorkspaceNavLinks() {{
      document.querySelectorAll(".workspace-link").forEach((link) => {{
        link.addEventListener("click", (event) => {{
          if (!isWorkspaceNavClick(event, link)) {{
            return;
          }}
          event.preventDefault();
          navigateWorkspace(link.href);
        }});
      }});
      window.addEventListener("popstate", () => {{
        navigateWorkspace(window.location.href, {{ replace: true, force: true }});
      }});
    }}
    document.getElementById("logoutNavButton").addEventListener("click", async () => {{
      await apiSend("/auth/logout", "POST");
      window.location.href = "/?auth_status=logged_out";
    }});
    bindWorkspaceNavLinks();
    syncWorkspaceUser();
    {script}
  </script>
</body>
</html>
"""
