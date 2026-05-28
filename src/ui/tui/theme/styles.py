"""
Centralized CSS theme for the Eggshell Backtester TUI.
All colors, spacing, and visual constants live here — no hardcoded styles in tab files.
"""

# ── Color palette ─────────────────────────────────────────────────────────────
PRIMARY     = "#00ffff"   # cyan  — titles, focus borders
SECONDARY   = "#ff00ff"   # magenta — section headers, run button
SUCCESS     = "#00ff00"   # green — valid inputs, positive P&L
WARNING     = "#ff8800"   # orange — save button
DANGER      = "#ff0000"   # red — errors, negative P&L
MUTED       = "#888888"   # grey — labels, inactive text
BG_DARK     = "#0a0a0a"   # near-black — main background
BG_PANEL    = "#1a1a1a"   # dark panel background
BG_INPUT    = "#111111"   # input field background
BG_OVERLAY  = "#111827"   # modal / overlay background
BORDER_DIM  = "#333333"   # inactive borders
BORDER_DARK = "#1a1a1a"   # subtle inner borders
TEXT_LIGHT  = "#eeeeee"   # primary text
TEXT_DIM    = "#555555"   # very muted text

# ── Component CSS sections ────────────────────────────────────────────────────

_SCREEN = f"""
Screen {{
    background: {BG_DARK};
    layers: base overlay;
    color: {TEXT_LIGHT};
    layout: vertical;
}}
Header {{ background: {BG_PANEL}; color: {PRIMARY}; text-style: bold; border-bottom: solid {BORDER_DIM}; }}
Footer {{ background: {BG_PANEL}; color: {PRIMARY}; border-top: solid {BORDER_DIM}; }}
Footer .footer--key {{ color: {SECONDARY}; }}
"""

_LAYOUT = f"""
#main-layout {{ padding: 0; margin: 0; height: 1fr; }}
#config-column {{ width: 45; }}
.btop-box {{ border: heavy {BORDER_DIM}; background: {BG_DARK}; margin: 0 1; height: 1fr; }}
.btop-box:focus-within {{ border: heavy {PRIMARY}; }}
.box-title {{ color: {PRIMARY}; background: {BG_PANEL}; text-style: bold; width: 100%; height: 1; text-align: center; margin-top: -1; margin-bottom: 1; }}
.section-header {{ color: {SECONDARY}; text-style: bold; margin-top: 1; margin-bottom: 0; text-align: center; background: {BG_PANEL}; }}
"""

_INPUTS = f"""
Label {{ color: {MUTED}; text-style: bold; margin: 0; }}
TabPane Label {{ margin-top: 1; }}
Input {{ border: none; background: {BG_PANEL}; color: {SUCCESS}; height: 1; margin-bottom: 0; }}
#start-date-input, #end-date-input {{ height: 3; border-bottom: solid {PRIMARY}; background: {BG_INPUT}; }}
Select {{ border: none; background: {BG_PANEL}; color: #ffff00; }}
SelectionList {{ border: none; background: {BG_PANEL}; height: 8; }}
Switch {{ margin-top: 1; }}
Input:disabled {{ color: #444444; background: {BG_INPUT}; }}
"""

_BUTTONS = f"""
Button {{ background: {BORDER_DIM}; color: #ffffff; border: none; height: 1; margin-top: 1; }}
Button:hover {{ background: {PRIMARY}; color: #000000; }}
Button:disabled {{ background: #222222; color: {TEXT_DIM}; }}

#run-btn {{ background: {SECONDARY}; color: #ffffff; text-style: bold; height: 3; margin-top: 1; width: 100%; }}
#run-btn:disabled {{ background: #550055; color: {MUTED}; }}

.sel-btn-row {{ height: 2; margin-bottom: 0; }}
#select-all-btn {{ background: #005500; }}
#deselect-all-btn {{ background: #550000; }}
"""

_TABS = f"""
#config-tabs {{ height: 1fr; width: 100%; }}
#config-tabs ContentSwitcher {{ height: 1fr; }}
TabPane {{ padding: 0 1; }}
#config-tabs TabPane {{ height: 1fr; }}
#config-tabs TabPane > VerticalScroll {{ height: 1fr; overflow-y: scroll; overflow-x: hidden; }}
#risk-tab-scroll {{ height: 1fr; overflow-y: scroll; overflow-x: hidden; }}
#strategy-picker-scroll {{ height: 1fr; overflow-y: scroll; overflow-x: hidden; }}
#dynamic-strategy-container {{ height: 1fr; overflow-y: scroll; overflow-x: hidden; }}
"""

_CALENDAR = f"""
CalendarWidget {{
    width: 36;
    height: auto;
    border: heavy {PRIMARY};
    background: {BG_OVERLAY};
    layer: overlay;
    offset: 46 5;
    padding: 1;
}}
.cal-container {{ width: 100%; }}
.cal-close-btn {{ background: #550000; color: #ffffff; min-width: 4; height: 1; margin-left: 1; }}
.cal-close-btn:hover {{ background: {DANGER}; }}
.hidden {{ display: none; }}
.cal-header {{ height: 3; align: center middle; }}
.cal-month-label {{ width: 15; text-align: center; color: {PRIMARY}; }}
.cal-grid {{ grid-size: 7; grid-gutter: 0; height: auto; }}
.day-header {{ text-align: center; color: #ffff00; }}
.calendar-day {{ min-width: 4; height: 1; border: none; padding: 0; }}
"""

_DATA_TABLE = f"""
DataTable {{ height: 1fr; border: none; background: {BG_DARK}; color: {TEXT_LIGHT}; }}
.stat-container {{ height: 4; margin-bottom: 1; padding: 0 1; width: 25%; background: {BG_INPUT}; border: solid {BORDER_DIM}; align: center middle; }}
.stat-container Label {{ margin: 0; width: 100%; text-align: center; }}
.stat-value {{ color: {SUCCESS}; text-style: bold; }}
.stat-bar {{ background: #222222; color: {SUCCESS}; width: 100%; height: 1; margin-top: 0; }}
"""

_COLLAPSIBLE = f"""
Collapsible {{ background: {BG_PANEL}; border: none; margin-top: 1; }}
Collapsible > .collapsible--title {{ color: {PRIMARY}; text-style: bold; }}

.indicator-collapsible {{
    background: #0f172a;
    border: none;
    margin-bottom: 0;
    margin-top: 0;
}}
.indicator-collapsible > .collapsible--title {{
    color: {PRIMARY};
    background: {BG_INPUT};
    text-style: bold;
    border-bottom: solid {BORDER_DIM};
    padding: 0 1;
}}
.indicator-collapsible > .collapsible--title:hover {{
    background: #1e293b;
    color: #ffffff;
}}
"""

_INLINE_FIELDS = f"""
.inline-field {{ height: 3; align: left middle; padding: 0 1; }}
.inline-field Label {{ width: 16; color: {MUTED}; margin: 0; }}
.inline-field Input {{ width: 10; color: {SUCCESS}; margin: 0; }}
.inline-field Switch {{ margin: 0; }}

.label-row {{ height: 2; align: left middle; }}
.label-row Label {{ margin-top: 0; }}
.info-icon {{ width: 3; color: #005566; text-style: bold; margin-left: 1; margin-top: 0; }}
.info-icon:hover {{ color: {PRIMARY}; }}
"""

_PROGRESS = f"""
#stats-column {{ width: 1fr; }}
ProgressBar {{
    width: 100%;
    height: 2;
    margin-top: 1;
    display: none;
}}
ProgressBar > .bar--bar {{ background: {PRIMARY}; }}
ProgressBar > .bar--complete {{ background: {SUCCESS}; }}
ProgressBar.visible {{ display: block; height: 2; }}
"""

_CONFIG_FOOTER = f"""
#stats-row {{ height: 6; margin-bottom: 1; }}
#config-footer {{
    height: auto;
    border-top: solid {BORDER_DIM};
    padding: 1;
    background: {BG_INPUT};
}}
#status-label {{
    color: {PRIMARY};
    text-align: center;
    width: 100%;
    height: 1;
    margin-bottom: 1;
    text-style: bold;
}}
#btn-row {{ height: 3; margin-top: 1; }}
#run-btn {{ width: 1fr; }}
#cancel-btn {{ width: 12; margin-left: 1; display: none; }}
#cancel-btn.visible {{ display: block; }}
"""

_RESULTS = f"""
#results-tabs {{ height: 1fr; }}
#tab-trades {{ padding: 0; }}
#tab-chart  {{ padding: 0; }}
#tab-stats  {{ padding: 0 1; }}
.chart-btn {{ width: 100%; margin: 1 0; display: none; }}
.chart-btn.visible {{ display: block; }}
#save-btn {{ width: 100%; margin: 2 0 0 0; background: {WARNING}; color: #000000; text-style: bold; height: 3; display: none; }}
#save-btn.visible {{ display: block; }}
#save-btn:hover {{ background: #ffaa00; }}
#load-btn {{ width: 100%; margin: 1 0 1 0; background: #1e3a5f; color: #00ccff; text-style: bold; height: 3; }}
#load-btn:hover {{ background: #00ccff; color: #000000; }}
#asset-chart-select {{ width: 100%; margin: 1 0; display: none; }}
#asset-chart-select.visible {{ display: block; }}
"""

_SHORTCUTS = f"""
#top-shortcuts {{
    background: {BG_INPUT};
    color: #aaaaaa;
    text-align: center;
    width: 100%;
    height: auto;
    margin: 0;
    padding: 0 2;
    border-bottom: solid {BORDER_DIM};
    text-style: bold;
}}
"""

_CHART_WIDGETS = f"""
ChartWidget {{ height: 1fr; background: {BG_DARK}; padding: 0; }}
ChartWidget:focus {{ border: solid {PRIMARY}; }}
.chart-info-row {{ height: 1fr; }}
#ext-metrics {{ width: 36; padding: 0 1; border-right: solid {BORDER_DIM}; }}
#ext-metrics-content {{ color: {TEXT_LIGHT}; height: auto; }}
#sym-breakdown {{ width: 1fr; }}
#symbol-table {{ height: 1fr; border: none; background: {BG_DARK}; }}
"""

_DATE_VALIDATION = f"""
.date-status-ok {{ color: {SUCCESS}; }}
.date-status-fail {{ color: {DANGER}; }}
#min-date-hint {{ color: {TEXT_DIM}; text-align: right; width: 1fr; }}
.date-header-row {{ height: 2; align: left middle; }}
.date-header-row Label {{ margin-top: 0; }}
"""

_PIE_TAB = f"""
#tab-pie {{ padding: 0 1; }}
#assets-pie {{ width: 100%; height: auto; }}
#alloc-section {{ display: none; margin-top: 1; }}
#alloc-section.visible {{ display: block; }}
#alloc-open-btn {{ width: 100%; height: 3; background: #0a1a0a; border: solid {SUCCESS}; color: {SUCCESS}; margin-top: 1; }}
#alloc-open-btn:hover {{ background: {SUCCESS}; color: #000000; }}
#alloc-total {{ text-align: center; margin-top: 1; text-style: bold; color: {SUCCESS}; }}
#alloc-total.invalid {{ color: {DANGER}; }}
"""

_ASSET_LIST = f"""
#asset-checkbox-container {{ height: auto; }}
"""

_DUAL_STRATEGY = f"""
#dual-strategy-panel {{ margin-top: 1; border-top: solid {BORDER_DIM}; padding-top: 1; height: auto; }}
#dual-strategy-panel Label {{ margin-top: 1; color: {MUTED}; }}
#dual-slot-btn-a, #dual-slot-btn-b {{ width: 1fr; }}
#dual-slot-btn-a.active-slot, #dual-slot-btn-b.active-slot {{ background: {PRIMARY}; color: #000000; text-style: bold; }}
"""

_PORTFOLIO_BADGE = f"""
.portfolio-badge {{
    background: #0a2a0a;
    color: {SUCCESS};
    text-style: bold;
    text-align: center;
    border: solid {SUCCESS};
    margin: 1 0;
    padding: 0 1;
    height: 2;
}}
"""

_SETUP_TAB = f"""
#setup-scroll {{ height: 1fr; }}
#setup-status {{ color: {MUTED}; text-align: center; height: 2; }}
#setup-content {{ color: #cccccc; margin-bottom: 1; }}
.glossary-term {{ color: #005566; text-style: bold; margin: 0; padding: 0 1; height: 2; }}
.glossary-term:hover {{ color: {PRIMARY}; }}
"""

_DATA_TAB = f"""
.data-mode-desc {{ color: {TEXT_DIM}; margin: 1 0; padding: 0 1; height: auto; }}
#data-rw-section, #data-mc-section {{ margin-top: 1; border-top: solid {BORDER_DARK}; padding-top: 1; }}
"""

# ── Assembled app CSS ─────────────────────────────────────────────────────────

APP_CSS = "\n".join([
    _SCREEN,
    _LAYOUT,
    _INPUTS,
    _BUTTONS,
    _TABS,
    _CALENDAR,
    _DATA_TABLE,
    _COLLAPSIBLE,
    _INLINE_FIELDS,
    _PROGRESS,
    _CONFIG_FOOTER,
    _RESULTS,
    _SHORTCUTS,
    _CHART_WIDGETS,
    _DATE_VALIDATION,
    _PIE_TAB,
    _ASSET_LIST,
    _DUAL_STRATEGY,
    _PORTFOLIO_BADGE,
    _SETUP_TAB,
    _DATA_TAB,
])
